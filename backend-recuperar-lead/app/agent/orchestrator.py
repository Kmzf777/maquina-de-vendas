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
        _openai_client = AsyncOpenAI(api_key=settings.gemini_api_key)
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

TZ_BR = timezone(timedelta(hours=-3))


def build_system_prompt(lead: dict, lead_context: dict | None = None) -> str:
    now = datetime.now(TZ_BR)
    stage = lead.get("stage", "secretaria")

    base = build_base_prompt(
        lead_name=lead.get("name"),
        lead_company=lead.get("company"),
        now=now,
        lead_context=lead_context,
    )

    stage_prompt = STAGE_PROMPTS.get(stage, SECRETARIA_PROMPT)
    return base + "\n\n" + stage_prompt


async def run_agent(
    lead: dict,
    user_text: str,
    channel: dict | None = None,
    conversation_id: str | None = None,
    lead_context: dict | None = None,
) -> str:
    """Run the SDR AI agent for a lead and return the response text."""
    stage = lead.get("stage", "secretaria")

    # If channel has an agent profile, use its stage config for model override
    agent_profile = channel.get("agent_profiles") if channel else None
    if agent_profile and agent_profile.get("stages"):
        profile_stages = agent_profile["stages"]
        stage_config = profile_stages.get(stage, {})
        model = stage_config.get("model") or agent_profile.get("model", "gpt-4.1")
    else:
        model = STAGE_MODELS.get(stage, "gpt-4.1")

    tools = get_tools_for_stage(stage)
    system_prompt = build_system_prompt(lead, lead_context=lead_context)

    # Build message history
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

    # Process tool calls
    while message.tool_calls:
        messages.append(message.model_dump())

        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)

            result = await execute_tool(func_name, func_args, lead["id"], lead.get("phone", ""))
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })

        response = await _get_openai().chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            temperature=0.7,
            max_tokens=500,
        )

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

    logger.info(f"SDR agent response for {lead.get('phone')} (stage={stage}): {assistant_text[:100]}...")
    return assistant_text
