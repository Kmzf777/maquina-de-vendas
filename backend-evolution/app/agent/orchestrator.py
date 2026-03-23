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
from app.leads.service import get_history, save_message

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


async def run_agent(lead: dict, user_text: str) -> str:
    """Run the AI agent for a lead and return the response text."""
    stage = lead.get("stage", "secretaria")
    model = STAGE_MODELS.get(stage, "gpt-4.1")
    tools = get_tools_for_stage(stage)

    messages = build_messages(lead, user_text)

    # Save user message
    save_message(lead["id"], "user", user_text, stage)

    # Call OpenAI
    response = await _get_openai().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=500,
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
        message = response.choices[0].message

    assistant_text = message.content or ""

    # Save assistant message
    save_message(lead["id"], "assistant", assistant_text, stage)

    logger.info(f"Agent response for {lead['phone']} (stage={stage}): {assistant_text[:100]}...")
    return assistant_text
