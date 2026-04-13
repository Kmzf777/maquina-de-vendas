import json
import logging
from datetime import datetime, timezone, timedelta

from openai import AsyncOpenAI

from app.config import settings
from app.agent.tools import get_tools_for_stage, execute_tool
from app.conversations.service import get_history, save_message

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None

# Brazil timezone
TZ_BR = timezone(timedelta(hours=-3))

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(
            api_key=settings.gemini_api_key,
            base_url=_GEMINI_BASE_URL,
        )
    return _openai_client


def build_system_prompt(conversation: dict, agent_profile: dict) -> str:
    """Build system prompt from agent_profile + conversation stage."""
    now = datetime.now(TZ_BR)
    stage = conversation.get("stage", "secretaria")

    base_prompt = agent_profile.get("base_prompt", "")
    stages = agent_profile.get("stages", {})
    stage_config = stages.get(stage, {})
    stage_prompt = stage_config.get("prompt", "")

    # Inject lead context
    lead = conversation.get("leads", {}) or {}
    lead_name = lead.get("name")
    lead_company = lead.get("company")

    context_lines = [f"Data/hora atual: {now.strftime('%d/%m/%Y %H:%M')}"]
    if lead_name:
        context_lines.append(f"Nome do lead: {lead_name}")
    if lead_company:
        context_lines.append(f"Empresa: {lead_company}")

    context = "\n".join(context_lines)

    return f"{base_prompt}\n\n--- CONTEXTO ---\n{context}\n\n--- STAGE: {stage} ---\n{stage_prompt}"


def build_messages(conversation: dict, agent_profile: dict, user_text: str) -> list[dict]:
    """Build the messages array for OpenAI from conversation history."""
    system_prompt = build_system_prompt(conversation, agent_profile)
    history = get_history(conversation["id"], limit=30)

    messages = [{"role": "system", "content": system_prompt}]

    for msg in history:
        if msg["role"] in ("user", "assistant"):
            messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_text})

    return messages


async def run_agent(conversation: dict, agent_profile: dict, user_text: str) -> str:
    """Run the AI agent for a conversation and return the response text."""
    stage = conversation.get("stage", "secretaria")
    lead = conversation.get("leads", {}) or {}
    lead_id = lead.get("id") or conversation.get("lead_id")
    conversation_id = conversation["id"]

    # Get model and tools from agent_profile stage config
    stages = agent_profile.get("stages", {})
    stage_config = stages.get(stage, {})
    model = stage_config.get("model", agent_profile.get("model", "gemini-3-flash-preview"))
    tool_names = stage_config.get("tools", [])
    tools = get_tools_for_stage(tool_names)

    messages = build_messages(conversation, agent_profile, user_text)

    # Save user message
    save_message(conversation_id, lead_id, "user", user_text, stage)

    # Call OpenAI
    response = await _get_openai().chat.completions.create(
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.7,
        max_tokens=1024,
    )

    message = response.choices[0].message

    # Process tool calls if any
    while message.tool_calls:
        messages.append(message.model_dump())

        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)

            result = await execute_tool(
                func_name, func_args, conversation_id, lead_id,
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
        message = response.choices[0].message

    assistant_text = message.content or ""

    # Save assistant message
    save_message(conversation_id, lead_id, "assistant", assistant_text, stage)

    logger.info(f"Agent response for conversation {conversation_id} (stage={stage}): {assistant_text[:100]}...")
    return assistant_text
