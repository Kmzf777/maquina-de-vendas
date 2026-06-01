import json
import logging
from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI

from app.config import settings
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts import get_stage_prompts
from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context
from app.agent.tools import get_tools_for_stage, execute_tool
from app.conversations.service import get_history
from app.agent.token_tracker import track_token_usage
from app.agent_profiles.service import get_agent_profile
from app.leads.service import get_lead, update_lead

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None
_gemini_client: AsyncOpenAI | None = None
TZ_BR = timezone(timedelta(hours=-3))
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_TOOL_ITERATIONS = 5

_OPENAI_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt-")
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _is_valid_openai_model(model: str) -> bool:
    return any(model.startswith(p) for p in _OPENAI_MODEL_PREFIXES)


def _is_gemini_model(model: str) -> bool:
    return model.startswith("gemini-")


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


def _get_gemini() -> AsyncOpenAI:
    global _gemini_client
    if _gemini_client is None:
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not configured — set it in .env to use Gemini models")
        _gemini_client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url=_GEMINI_BASE_URL,
        )
    return _gemini_client


def _get_client(model: str) -> AsyncOpenAI:
    return _get_gemini() if _is_gemini_model(model) else _get_openai()


def _resolve_prompt_key(profile: dict | None) -> str:
    """Return the prompt_key for this agent profile, defaulting to valeria_inbound."""
    if not profile:
        return "valeria_inbound"
    return profile.get("prompt_key", "valeria_inbound")


def build_system_prompt(
    lead: dict,
    stage: str,
    prompt_key: str = "valeria_inbound",
    lead_context: dict | None = None,
) -> str:
    now = datetime.now(TZ_BR)
    base = build_base_prompt(
        lead_name=lead.get("name"),
        lead_company=lead.get("company"),
        now=now,
        lead_context=lead_context,
    )
    stage_prompts = get_stage_prompts(prompt_key)
    stage_prompt = stage_prompts.get(stage, stage_prompts["secretaria"])
    return base + "\n\n" + stage_prompt


async def run_agent(
    conversation: dict,
    user_text: str,
    lead_context: dict | None = None,
    agent_profile_id: str | None = None,
) -> str:
    """Run the SDR AI agent for a conversation and return the response text."""
    stage = conversation.get("stage", "secretaria")
    lead = conversation.get("leads", {}) or {}
    lead_id = lead.get("id") or conversation.get("lead_id")
    conversation_id = conversation["id"]

    # Defense-in-depth: re-fetch lead from DB to catch any race where ai_enabled
    # was changed after the processor's own check but before run_agent was called.
    if lead_id:
        fresh = get_lead(lead_id)
        if fresh and not fresh.get("ai_enabled", True):
            logger.info(
                "[AI DISABLED DEFENSE] orchestrator bailing out for lead %s — ai_enabled=False",
                lead_id,
            )
            return ""
        if fresh:
            # Keep downstream code using the freshest lead state
            lead = fresh
            conversation["leads"] = fresh

    # Resolve agent profile
    profile = None
    if agent_profile_id:
        try:
            profile = get_agent_profile(agent_profile_id)
        except Exception:
            logger.warning("Failed to fetch agent_profile %s, using default", agent_profile_id, exc_info=True)

    prompt_key = _resolve_prompt_key(profile)
    model = profile.get("model", DEFAULT_MODEL) if profile else DEFAULT_MODEL
    if not (_is_valid_openai_model(model) or _is_gemini_model(model)):
        logger.warning("Agent profile model '%s' is not a valid model, falling back to %s", model, DEFAULT_MODEL)
        model = DEFAULT_MODEL
    elif _is_gemini_model(model):
        logger.info("Using Gemini model '%s' via OpenAI-compatible API", model)

    tools = get_tools_for_stage(stage)
    system_prompt = build_system_prompt(lead, stage, prompt_key=prompt_key, lead_context=lead_context)

    history = get_history(conversation_id, limit=60)
    # processor.py saves user message before calling run_agent, so history already
    # includes the current message — strip it to avoid sending it twice.
    if history and history[-1]["role"] == "user" and history[-1]["content"] == user_text:
        history = history[:-1]

    # Collapse consecutive assistant bubbles into a single turn so the AI sees
    # one coherent response per turn regardless of how many bubbles were saved.
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] not in ("user", "assistant"):
            continue
        if messages and messages[-1]["role"] == "assistant" == msg["role"]:
            messages[-1]["content"] += "\n\n" + msg["content"]
        else:
            messages.append({"role": msg["role"], "content": msg["content"]})

    is_outbound = prompt_key == "valeria_outbound"
    # history here has the current message already stripped (lines above); len == 0 means genuine first turn
    is_first_turn = len(history) == 0
    campaign_message = (lead_context or {}).get("campaign_message")

    if is_outbound and is_first_turn and campaign_message:
        ctx = build_outbound_first_turn_context(campaign_message, lead.get("name"))
        messages.append({"role": "user", "content": ctx})

    messages.append({"role": "user", "content": user_text})

    response = await _get_client(model).chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=500,
    )

    if response.usage:
        track_token_usage(
            lead_id=lead_id,
            stage=stage,
            model=model,
            call_type="response",
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

    message = response.choices[0].message

    tool_iterations = 0
    while message.tool_calls:
        tool_iterations += 1
        if tool_iterations > MAX_TOOL_ITERATIONS:
            logger.error(
                "[LOOP GUARD] max tool iterations (%d) reached for conv %s — forcing text response",
                MAX_TOOL_ITERATIONS, conversation_id,
            )
            if not message.content:
                try:
                    fallback = await _get_client(model).chat.completions.create(
                        model=model,
                        messages=messages,
                        tools=None,
                        temperature=0.7,
                        max_tokens=500,
                    )
                    message = fallback.choices[0].message
                except Exception as _exc:
                    logger.error("[LOOP GUARD] fallback call failed for conv %s: %s", conversation_id, _exc)
            break
        messages.append(message.model_dump(exclude_none=True))
        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            try:
                func_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as exc:
                logger.error(
                    "Malformed JSON args for tool %s in conv %s: %s",
                    func_name, conversation_id, exc,
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": f"erro: argumentos inválidos para {func_name} — tente novamente",
                })
                continue
            try:
                result = await execute_tool(
                    func_name, func_args, lead_id, lead.get("phone", ""), conversation_id
                )
            except Exception as exc:
                logger.error(
                    "Tool %s raised exception for conv %s: %s",
                    func_name, conversation_id, exc, exc_info=True,
                )
                result = f"erro ao executar {func_name} — tente novamente"
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        # encaminhar_humano sends the handoff message directly inside execute_tool.
        # Return empty to prevent the processor from sending a duplicate message.
        if any(tc.function.name == "encaminhar_humano" for tc in message.tool_calls):
            return ""

        # registrar_optout sets ai_enabled=False silently. The farewell Valéria
        # wrote lives in message.content of this same turn — return it now and skip
        # the second API call (there is nothing left to say after opt-out).
        if any(tc.function.name == "registrar_optout" for tc in message.tool_calls):
            return message.content or "Entendido, sem problema. Não entrarei mais em contato."

        # If mudar_stage was called, update in-memory state so the next API call
        # uses the correct stage prompt and tools — prevents infinite transition loop.
        for tc in message.tool_calls:
            if tc.function.name == "mudar_stage":
                try:
                    new_stage = json.loads(tc.function.arguments).get("stage", stage)
                except json.JSONDecodeError:
                    break
                old_stage = stage
                stage = new_stage
                tools = get_tools_for_stage(stage)
                system_prompt = build_system_prompt(lead, stage, prompt_key=prompt_key, lead_context=lead_context)
                messages[0] = {"role": "system", "content": system_prompt}
                if lead_id:
                    current_meta = lead.get("metadata") or {}
                    updated_meta = {**current_meta, "previous_stage": old_stage}
                    update_lead(lead_id, metadata=updated_meta)
                    lead["metadata"] = updated_meta
                break

        response = await _get_client(model).chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            temperature=0.7,
            max_tokens=500,
        )
        if response.usage:
            track_token_usage(
                lead_id=lead_id,
                stage=stage,
                model=model,
                call_type="response",
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )
        message = response.choices[0].message

    assistant_text = message.content or ""
    logger.info(
        f"SDR agent response for conv {conversation_id} (stage={stage}, prompt_key={prompt_key}): {assistant_text[:100]}..."
    )
    return assistant_text
