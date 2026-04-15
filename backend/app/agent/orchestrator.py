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
from app.conversations.service import get_history
from app.agent.token_tracker import track_token_usage

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

TZ_BR = timezone(timedelta(hours=-3))

STAGE_PROMPTS = {
    "secretaria": SECRETARIA_PROMPT,
    "atacado": ATACADO_PROMPT,
    "private_label": PRIVATE_LABEL_PROMPT,
    "exportacao": EXPORTACAO_PROMPT,
    "consumo": CONSUMO_PROMPT,
}

STAGE_MODELS = {
    "secretaria": "gemini-3-flash-preview",
    "atacado": "gemini-3-flash-preview",
    "private_label": "gemini-3-flash-preview",
    "exportacao": "gemini-3-flash-preview",
    "consumo": "gemini-3-flash-preview",
}


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url=_GEMINI_BASE_URL,
        )
    return _openai_client


def build_system_prompt(
    lead: dict, stage: str, lead_context: dict | None = None
) -> str:
    now = datetime.now(TZ_BR)
    base = build_base_prompt(
        lead_name=lead.get("name"),
        lead_company=lead.get("company"),
        now=now,
        lead_context=lead_context,
    )
    stage_prompt = STAGE_PROMPTS.get(stage, SECRETARIA_PROMPT)
    return base + "\n\n" + stage_prompt


async def run_agent(
    conversation: dict,
    user_text: str,
    lead_context: dict | None = None,
) -> str:
    """Run the SDR AI agent for a conversation and return the response text.

    NOTE: The caller (processor) is responsible for saving the user message
    BEFORE calling run_agent. This function only saves the assistant message.
    """
    stage = conversation.get("stage", "secretaria")
    lead = conversation.get("leads", {}) or {}
    lead_id = lead.get("id") or conversation.get("lead_id")
    conversation_id = conversation["id"]

    model = STAGE_MODELS.get(stage, "gemini-3-flash-preview")
    tools = get_tools_for_stage(stage)
    system_prompt = build_system_prompt(lead, stage, lead_context=lead_context)

    # Build message history scoped by conversation_id (not lead_id)
    history = get_history(conversation_id, limit=30)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_text})

    # Call Gemini via OpenAI-compatible API
    response = await _get_openai().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=1024,
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

    # Process tool calls
    while message.tool_calls:
        messages.append(message.model_dump())
        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)
            result = await execute_tool(
                func_name, func_args, lead_id, lead.get("phone", "")
            )
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
            max_tokens=1024,
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
        f"SDR agent response for conv {conversation_id} (stage={stage}): {assistant_text[:100]}..."
    )
    return assistant_text
