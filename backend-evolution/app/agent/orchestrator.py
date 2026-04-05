import json
import logging
from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI

from app.config import settings
from app.agent.prompts.base import build_base_prompt
from app.agent.prompts.secretaria import SECRETARIA_PROMPT
from app.agent.prompts.atacado import ATACADO_PROMPT
from app.agent.prompts.private_label import PRIVATE_LABEL_PROMPT
from app.agent.prompts.exportacao import EXPORTACAO_PROMPT
from app.agent.prompts.consumo import CONSUMO_PROMPT
from app.agent.tools import get_tools_for_stage, execute_tool
from app.leads.service import get_history, save_message, update_lead
from app.agent.token_tracker import track_token_usage

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client

STAGE_PROMPTS = {
    "secretaria": SECRETARIA_PROMPT,
    "atacado": ATACADO_PROMPT,
    "private_label": PRIVATE_LABEL_PROMPT,
    "exportacao": EXPORTACAO_PROMPT,
    "consumo": CONSUMO_PROMPT,
}

STAGE_MODELS = {
    "secretaria": "gpt-4.1",
    "atacado": "gpt-4.1",
    "private_label": "gpt-4.1",
    "exportacao": "gpt-4.1-mini",
    "consumo": "gpt-4.1-mini",
}

# Brazil timezone
TZ_BR = timezone(timedelta(hours=-3))


def build_system_prompt(lead: dict) -> str:
    now = datetime.now(TZ_BR)
    stage = lead.get("stage", "secretaria")

    base = build_base_prompt(
        lead_name=lead.get("name"),
        lead_company=lead.get("company"),
        now=now,
    )

    stage_prompt = STAGE_PROMPTS.get(stage, SECRETARIA_PROMPT)

    return base + "\n\n" + stage_prompt


def _build_profile_prompt(lead: dict, agent_profile: dict, stage: str) -> str:
    """Build system prompt from an agent_profile record."""
    now = datetime.now(TZ_BR)
    base = build_base_prompt(
        lead_name=lead.get("name"),
        lead_company=lead.get("company"),
        now=now,
    )

    # Use profile's base_prompt if set
    profile_base = agent_profile.get("base_prompt", "")
    if profile_base:
        base = base + "\n\n" + profile_base

    # Use stage-specific prompt from profile, fall back to hardcoded
    stages = agent_profile.get("stages", {})
    stage_config = stages.get(stage, {})
    stage_prompt = stage_config.get("prompt", "")
    if not stage_prompt:
        stage_prompt = STAGE_PROMPTS.get(stage, SECRETARIA_PROMPT)

    return base + "\n\n" + stage_prompt


def build_messages(lead: dict, user_text: str) -> list[dict]:
    """Build the messages array for OpenAI from conversation history."""
    system_prompt = build_system_prompt(lead)
    history = get_history(lead["id"], limit=30)

    messages = [{"role": "system", "content": system_prompt}]

    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_text})

    return messages


async def run_agent(lead: dict, user_text: str, channel: dict | None = None, conversation_id: str | None = None) -> str:
    """Run the AI agent for a lead and return the response text."""
    stage = lead.get("stage", "secretaria")

    # If channel has an agent profile, use its configuration
    agent_profile = channel.get("agent_profiles") if channel else None

    if agent_profile and agent_profile.get("stages"):
        profile_stages = agent_profile["stages"]
        stage_config = profile_stages.get(stage, {})
        model = stage_config.get("model") or agent_profile.get("model", "gpt-4.1")
        tools = get_tools_for_stage(stage)
        system_prompt = _build_profile_prompt(lead, agent_profile, stage)
    else:
        model = STAGE_MODELS.get(stage, "gpt-4.1")
        tools = get_tools_for_stage(stage)
        system_prompt = build_system_prompt(lead)

    # Build messages with the resolved system prompt
    history = get_history(lead["id"], limit=30)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})

    # Save user message
    save_message(lead["id"], "user", user_text, stage, conversation_id=conversation_id)

    # Call OpenAI
    response = await _get_openai().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=500,
    )

    # Track token usage
    if response.usage:
        track_token_usage(
            lead_id=lead["id"],
            stage=stage,
            model=model,
            call_type="response",
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )

    message = response.choices[0].message

    # Process tool calls if any
    while message.tool_calls:
        # Add assistant message with tool calls
        messages.append(message.model_dump())

        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)

            result = await execute_tool(
                func_name, func_args, lead["id"], lead["phone"]
            )

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        # Call again to get the text response after tool execution
        response = await _get_openai().chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            temperature=0.7,
            max_tokens=500,
        )

        # Track token usage for tool follow-up
        if response.usage:
            track_token_usage(
                lead_id=lead["id"],
                stage=stage,
                model=model,
                call_type="response",
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )

        message = response.choices[0].message

    assistant_text = message.content or ""

    # Save assistant message
    save_message(lead["id"], "assistant", assistant_text, stage, conversation_id=conversation_id)

    # Guardrail: if still in secretaria after enough conversation, force classification
    if stage == "secretaria":
        await _guardrail_secretaria(lead, messages)

    logger.info(f"Agent response for {lead['phone']} (stage={stage}): {assistant_text[:100]}...")
    return assistant_text


# ---------------------------------------------------------------------------
# Guardrail: prevent leads from getting stuck in secretaria
# ---------------------------------------------------------------------------

SECRETARIA_MAX_USER_MSGS = 4

CLASSIFY_PROMPT = """Analise o historico de conversa abaixo e classifique a necessidade do lead.
Responda APENAS com uma das opcoes (sem explicacao):
- atacado (quer comprar cafe para negocio: hotel, restaurante, cafeteria, revenda, loja, uso institucional)
- private_label (quer criar marca propria de cafe)
- exportacao (quer exportar cafe)
- consumo (quer comprar cafe para uso pessoal/domestico)
- indefinido (impossivel determinar com a conversa ate agora)
"""


async def _guardrail_secretaria(lead: dict, messages: list[dict]) -> None:
    """If a lead has too many messages in secretaria, force-classify and move."""
    history = get_history(lead["id"], limit=50)
    user_msgs_in_secretaria = [
        m for m in history if m["role"] == "user" and m.get("stage") == "secretaria"
    ]

    if len(user_msgs_in_secretaria) < SECRETARIA_MAX_USER_MSGS:
        return

    # Build a lightweight classification request
    conversation_summary = "\n".join(
        f"{m['role']}: {m['content']}" for m in history
        if m["role"] in ("user", "assistant")
    )

    classify_messages = [
        {"role": "system", "content": CLASSIFY_PROMPT},
        {"role": "user", "content": conversation_summary},
    ]

    try:
        response = await _get_openai().chat.completions.create(
            model="gpt-4.1-mini",
            messages=classify_messages,
            temperature=0,
            max_tokens=20,
        )

        # Track classification token usage
        if response.usage:
            track_token_usage(
                lead_id=lead["id"],
                stage="secretaria",
                model="gpt-4.1-mini",
                call_type="classification",
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
            )

        classification = (response.choices[0].message.content or "").strip().lower()

        valid_stages = {"atacado", "private_label", "exportacao", "consumo"}
        if classification in valid_stages:
            update_lead(lead["id"], stage=classification)
            logger.warning(
                f"Guardrail: force-moved lead {lead['phone']} from secretaria to "
                f"{classification} after {len(user_msgs_in_secretaria)} user messages"
            )
            save_message(
                lead["id"], "system",
                f"Guardrail: lead reclassificado automaticamente para {classification}",
                classification,
            )
    except Exception as e:
        logger.error(f"Guardrail classification failed for {lead['phone']}: {e}")
