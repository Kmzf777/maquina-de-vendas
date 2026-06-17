import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta

import httpx
import openai
from openai import AsyncOpenAI

from app.config import settings
from app.agent.prompts.base import build_base_prompt, FINAL_INSTRUCTION
from app.agent.prompts import get_stage_prompts
from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context
from app.agent.tools import get_tools_for_stage, execute_tool
from app.conversations.service import (
    get_history,
    resolve_message_text_by_wamid,
    resolve_message_texts_by_wamids,
)
from app.agent.token_tracker import track_token_usage
from app.agent_profiles.service import get_agent_profile
from app.leads.service import get_lead, update_lead

logger = logging.getLogger(__name__)

_openai_client: AsyncOpenAI | None = None
_gemini_client: AsyncOpenAI | None = None
TZ_BR = timezone(timedelta(hours=-3))
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_TOOL_ITERATIONS = 5
# gemini-2.5-flash conta tokens de "thinking" no MESMO budget que a saída via API
# OpenAI-compat. Com teto baixo (1024) o modelo gasta o orçamento pensando e devolve
# texto vazio após tool calls — deixando o lead sem resposta. 4096 dá folga ao thinking.
MAX_OUTPUT_TOKENS = 4096
# Stop sequences: corta saída runaway sem colidir com o separador de bolhas \n\n
# (usamos \n\n\n, três quebras), e barra alucinação de turnos/tokens de controle.
# Via endpoint OpenAI-compat do Gemini isto vira stopSequences (limite 5).
_STOP_SEQUENCES = ["\n\n\n", "User:", "<|im_end|>"]
# Resposta de segurança quando, mesmo após o fallback sem tools, a IA não produz texto.
# Garante que o lead nunca fique mudo (regressão observada: Ademilson, Thainara).
_SAFETY_FALLBACK_MESSAGE = (
    "Entendi! Só um momento enquanto verifico essas informações internamente."
)
# Resposta de segurança contextual para quando a última tool usada foi de mídia
# (enviar_fotos / enviar_foto_produto). O genérico "verifico internamente" é nonsense
# após um catálogo — preferimos uma pergunta de avanço coerente com o envio.
_SAFETY_FALLBACK_MEDIA = (
    "Te enviei as fotos aqui no chat. Qual delas chamou mais sua atenção?"
)

_MEDIA_TOOL_NAMES = frozenset({"enviar_fotos", "enviar_foto_produto"})

# Frases de avanço contextuais por stage, usadas quando a IA fica MUDA logo após um
# mudar_stage (gemini-2.5-flash devolvendo completion_tokens=0 — Bug 2: Elisangele,
# Ademilson, Renato). A transição é silenciosa por design, então o lead não pode ficar
# sem resposta: emitimos uma pergunta coerente com o novo stage no lugar do genérico
# "verifico internamente". `secretaria` fica de fora de propósito (é o stage de entrada,
# não um avanço comercial) → cai no fallback genérico.
_STAGE_TRANSITION_FALLBACKS: dict[str, str] = {
    "atacado": (
        "Pelo que você me contou, faz todo sentido a gente falar de condições para o seu "
        "negócio. Você procura o café para revender ou para servir no seu estabelecimento?"
    ),
    "private_label": (
        "Que ideia bacana! Você está pensando em ter o café com a sua própria marca? "
        "Me conta um pouco do que tem em mente."
    ),
    "exportacao": (
        "Mercado externo é um universo e tanto! Você já tem algum país de destino em mente "
        "para levar o café?"
    ),
    "consumo": (
        "Show! Pra eu te indicar o ideal pro seu dia a dia, você prefere o café em grãos "
        "ou já moído?"
    ),
}


def _empty_fallback_text(media_tool_used: bool, transitioned_to_stage: str | None = None) -> str:
    """Return the appropriate safety fallback message for the empty-response case.

    Priority (mais específico → mais genérico):
      1. Pergunta de avanço contextual, quando houve um mudar_stage neste turno — o lead
         nunca pode ficar mudo logo após uma transição silenciosa de funil.
      2. Pergunta de fechamento de mídia, quando uma tool de foto foi usada.
      3. Stall genérico.

    Extracted as a pure helper so it can be unit-tested without running run_agent.
    """
    if transitioned_to_stage and transitioned_to_stage in _STAGE_TRANSITION_FALLBACKS:
        return _STAGE_TRANSITION_FALLBACKS[transitioned_to_stage]
    return _SAFETY_FALLBACK_MEDIA if media_tool_used else _SAFETY_FALLBACK_MESSAGE

_OPENAI_MODEL_PREFIXES = ("gpt-", "o1", "o3", "o4", "chatgpt-")
_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"

# ---------------------------------------------------------------------------
# Helpers for reply/reaction context enrichment (prompt-only, never persisted)
# ---------------------------------------------------------------------------

_TRUNCATE_LEN = 120


def _truncate(text: str, length: int = _TRUNCATE_LEN) -> str:
    """Truncate text to `length` chars, appending '…' only when cut."""
    if len(text) <= length:
        return text
    return text[:length] + "…"


def _build_reply_marker(quoted_wamid: str, resolved: dict | None = None) -> str:
    """Return a '[Em resposta a: "..."]' prefix line for a quoted message.

    Resolves the quoted wamid to its stored content. Falls back to a soft
    marker when the message cannot be found.

    `resolved` is an optional {wamid: content} cache (batch pre-fetch); when the
    wamid is absent from it, falls back to a single DB lookup.
    """
    orig = _lookup_wamid_text(quoted_wamid, resolved)
    if orig:
        return f'[Em resposta a: "{_truncate(orig)}"]'
    return "[Em resposta a uma mensagem anterior]"


def _lookup_wamid_text(wamid: str, resolved: dict | None) -> str | None:
    """Read a wamid's text from the batch cache, falling back to a single query."""
    if resolved is not None and wamid in resolved:
        return resolved[wamid]
    return resolve_message_text_by_wamid(wamid)


def _render_history_content(msg: dict, resolved: dict | None = None) -> str:
    """Return the display content for a history message, with reply/reaction enrichment.

    - Reaction messages are translated to a human-readable line.
    - Messages with quoted_wamid get a reply-marker prepended.
    - All other messages pass through unchanged.

    `resolved` is an optional {wamid: content} cache (batch pre-fetch) used to avoid
    one DB query per message; absent wamids fall back to a single lookup.

    Never raises — degrades to the raw content on any error.
    """
    try:
        content = msg.get("content") or ""
        message_type = msg.get("message_type")

        # Reaction: replace content entirely with a translated line
        if message_type == "reaction":
            metadata = msg.get("metadata")
            emoji = "?"
            target_wamid = None
            if isinstance(metadata, dict):
                emoji = metadata.get("emoji") or "?"
                target_wamid = metadata.get("target_wamid")
            if target_wamid:
                target_text = _lookup_wamid_text(target_wamid, resolved)
                if target_text:
                    return f'[O lead reagiu com {emoji} à mensagem: "{_truncate(target_text)}"]'
            return f"[O lead reagiu com {emoji} a uma mensagem anterior]"

        # Reply: prepend a marker with the quoted text
        quoted_wamid = msg.get("quoted_wamid")
        if quoted_wamid:
            marker = _build_reply_marker(quoted_wamid, resolved)
            return f"{marker}\n{content}"

        return content
    except Exception as exc:  # pragma: no cover
        logger.warning("_render_history_content: erro ao enriquecer mensagem: %s", exc)
        return msg.get("content") or ""


def _is_valid_openai_model(model: str) -> bool:
    return any(model.startswith(p) for p in _OPENAI_MODEL_PREFIXES)


def _is_gemini_model(model: str) -> bool:
    return model.startswith("gemini-")


def _gemini_thinking_off(model: str) -> dict:
    """Kwargs que desligam o 'thinking' do Gemini 2.5 (flash/flash-lite) nas chamadas pós-tool.

    Causa raiz do Bug 2: gemini-2.5-flash gasta o budget de saída pensando e devolve
    completion_tokens=0 logo após executar uma tool, deixando o lead mudo. A doc oficial
    (OpenAI-compat) permite `reasoning_effort="none"` para DESLIGAR o thinking nos modelos
    2.5 — mas NÃO em 2.5-pro nem 3.x, que rejeitam o valor. Por isso retornamos {} nesses
    casos (e para modelos OpenAI), evitando um 400 em produção.
    """
    if model.startswith("gemini-2.5-") and not model.startswith("gemini-2.5-pro"):
        return {"reasoning_effort": "none"}
    return {}


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


# Drops de conexão HTTP/2 (GOAWAY) sob concorrência (rajada de disparo) derrubavam
# chamadas ao LLM. Retry localizado é mais seguro que reexecutar o turno inteiro no
# processor — este reexecutaria tools já aplicadas (encaminhar_humano, mudar_stage).
# Chamadas a chat.completions.create() não têm efeitos colaterais → seguras para retry.
_LLM_RETRY_ATTEMPTS = 3
_LLM_RETRY_DELAY = 2  # segundos


async def _create_with_retry(client: AsyncOpenAI, **kwargs):
    """chat.completions.create com retry em drops de conexão (GOAWAY/timeout)."""
    last_exc: Exception | None = None
    for attempt in range(1, _LLM_RETRY_ATTEMPTS + 1):
        try:
            return await client.chat.completions.create(**kwargs)
        except (openai.APIConnectionError, openai.APITimeoutError, httpx.TransportError) as exc:
            last_exc = exc
            logger.warning(
                "[LLM RETRY] tentativa %d/%d falhou (conexão): %s",
                attempt, _LLM_RETRY_ATTEMPTS, exc,
            )
            if attempt < _LLM_RETRY_ATTEMPTS:
                await asyncio.sleep(_LLM_RETRY_DELAY)
    raise last_exc


def get_ai_client(model: str) -> AsyncOpenAI:
    """Public accessor — returns the appropriate AI client for the given model."""
    return _get_client(model)


def _resolve_prompt_key(profile: dict | None) -> str:
    """Return the prompt_key for this agent profile, defaulting to valeria_inbound."""
    if not profile:
        return "valeria_inbound"
    return profile.get("prompt_key", "valeria_inbound")


def resolve_prompt_key(agent_profile_id: str | None) -> str:
    """Resolve o prompt_key (persona) a partir de um agent_profile_id.

    Usado para rastreabilidade (coluna messages.agent_persona): permite ao caller
    saber qual persona run_agent usará/usou sem alterar o retorno de run_agent.
    Fail-open: default valeria_inbound em qualquer falha de fetch.
    """
    profile = None
    if agent_profile_id:
        try:
            profile = get_agent_profile(agent_profile_id)
        except Exception:
            logger.warning("resolve_prompt_key: falha ao buscar profile %s", agent_profile_id, exc_info=True)
    return _resolve_prompt_key(profile)


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
    # Ordem hierarquica: base (persona) -> estagio (roteiro do funil) -> instrucao final.
    # FINAL_INSTRUCTION fica por ultimo para que <final_instruction> seja literalmente a
    # ultima tag da string, preservando a hierarquia XML esperada pelo Gemini.
    return base + "\n\n" + stage_prompt + "\n\n" + FINAL_INSTRUCTION


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
    # Capture quoted_wamid of the current turn BEFORE stripping so we can enrich
    # the user_text that gets appended at the end.
    current_quoted_wamid: str | None = None
    if history and history[-1]["role"] == "user" and history[-1]["content"] == user_text:
        current_quoted_wamid = history[-1].get("quoted_wamid")
        history = history[:-1]

    # Batch-resolve every wamid referenced by replies/reactions (history + current turn)
    # in ONE query, instead of one DB round-trip per message inside the loop.
    _wamids_to_resolve: list[str] = []
    if current_quoted_wamid:
        _wamids_to_resolve.append(current_quoted_wamid)
    for msg in history:
        qw = msg.get("quoted_wamid")
        if qw:
            _wamids_to_resolve.append(qw)
        if msg.get("message_type") == "reaction":
            meta = msg.get("metadata")
            if isinstance(meta, dict) and meta.get("target_wamid"):
                _wamids_to_resolve.append(meta["target_wamid"])
    resolved_wamids = resolve_message_texts_by_wamids(_wamids_to_resolve) if _wamids_to_resolve else {}

    # Collapse consecutive assistant bubbles into a single turn so the AI sees
    # one coherent response per turn regardless of how many bubbles were saved.
    # Reply/reaction enrichment is applied via _render_history_content (reads the batch cache).
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] not in ("user", "assistant"):
            continue
        enriched_content = _render_history_content(msg, resolved_wamids)
        if messages and messages[-1]["role"] == "assistant" == msg["role"]:
            messages[-1]["content"] += "\n\n" + enriched_content
        else:
            messages.append({"role": msg["role"], "content": enriched_content})

    is_outbound = prompt_key == "valeria_outbound"
    # history here has the current message already stripped (lines above); len == 0 means genuine first turn
    is_first_turn = len(history) == 0
    campaign_message = (lead_context or {}).get("campaign_message")

    if is_outbound and is_first_turn and campaign_message:
        ctx = build_outbound_first_turn_context(campaign_message, lead.get("name"))
        messages.append({"role": "user", "content": ctx})

    # Apply reply marker to the current user message when it was a reply
    if current_quoted_wamid:
        marker = _build_reply_marker(current_quoted_wamid, resolved_wamids)
        enriched_user_text = f"{marker}\n{user_text}"
    else:
        enriched_user_text = user_text
    messages.append({"role": "user", "content": enriched_user_text})

    response = await _create_with_retry(_get_client(model),
        model=model,
        messages=messages,
        tools=tools if tools else None,
        temperature=0.4,
        max_tokens=MAX_OUTPUT_TOKENS,
        stop=_STOP_SEQUENCES,
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
    media_tool_used = False
    transitioned_to_stage: str | None = None
    while message.tool_calls:
        tool_iterations += 1
        if tool_iterations > MAX_TOOL_ITERATIONS:
            logger.error(
                "[LOOP GUARD] max tool iterations (%d) reached for conv %s — forcing text response",
                MAX_TOOL_ITERATIONS, conversation_id,
            )
            if not message.content:
                try:
                    fallback = await _create_with_retry(_get_client(model),
                        model=model,
                        messages=messages,
                        tools=None,
                        temperature=0.4,
                        max_tokens=MAX_OUTPUT_TOKENS,
                        stop=_STOP_SEQUENCES,
                        **_gemini_thinking_off(model),
                    )
                    message = fallback.choices[0].message
                except Exception as _exc:
                    logger.error("[LOOP GUARD] fallback call failed for conv %s: %s", conversation_id, _exc)
            break
        messages.append(message.model_dump(exclude_none=True))
        for tool_call in message.tool_calls:
            func_name = tool_call.function.name
            if func_name in _MEDIA_TOOL_NAMES:
                media_tool_used = True
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
        # Return None (sentinel) so the processor can distinguish an intentional
        # handoff from an unexpected empty response.
        if any(tc.function.name == "encaminhar_humano" for tc in message.tool_calls):
            return None

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
                transitioned_to_stage = new_stage
                tools = get_tools_for_stage(stage)
                system_prompt = build_system_prompt(lead, stage, prompt_key=prompt_key, lead_context=lead_context)
                messages[0] = {"role": "system", "content": system_prompt}
                if lead_id:
                    current_meta = lead.get("metadata") or {}
                    updated_meta = {**current_meta, "previous_stage": old_stage}
                    update_lead(lead_id, metadata=updated_meta)
                    lead["metadata"] = updated_meta
                break

        # Chamada PÓS-TOOL: desliga o thinking do Gemini 2.5 — é aqui que o modelo
        # gastava o budget pensando e devolvia completion_tokens=0 (Bug 2).
        response = await _create_with_retry(_get_client(model),
            model=model,
            messages=messages,
            tools=tools if tools else None,
            temperature=0.4,
            max_tokens=MAX_OUTPUT_TOKENS,
            stop=_STOP_SEQUENCES,
            **_gemini_thinking_off(model),
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

    # If the AI returned empty content after tool calls (e.g. after enviar_fotos Gemini
    # sometimes returns nothing), force one more call without tools to get a text response.
    if not assistant_text and tool_iterations > 0:
        logger.warning(
            "[AGENT EMPTY AFTER TOOLS] resposta vazia após %d tool iteration(s) para conv %s "
            "— forçando chamada de texto sem tools",
            tool_iterations, conversation_id,
        )
        try:
            fallback_resp = await _create_with_retry(_get_client(model),
                model=model,
                messages=messages,
                tools=None,
                temperature=0.4,
                max_tokens=MAX_OUTPUT_TOKENS,
                stop=_STOP_SEQUENCES,
                **_gemini_thinking_off(model),
            )
            if fallback_resp.usage:
                track_token_usage(
                    lead_id=lead_id,
                    stage=stage,
                    model=model,
                    call_type="response",
                    prompt_tokens=fallback_resp.usage.prompt_tokens,
                    completion_tokens=fallback_resp.usage.completion_tokens,
                )
            assistant_text = fallback_resp.choices[0].message.content or ""
            if not assistant_text:
                logger.error(
                    "[AGENT EMPTY AFTER TOOLS] fallback também vazio para conv %s "
                    "— usando resposta de segurança",
                    conversation_id,
                )
        except Exception as _exc:
            logger.error(
                "[AGENT EMPTY AFTER TOOLS] fallback call falhou para conv %s: %s "
                "— usando resposta de segurança",
                conversation_id, _exc,
            )

    # Rede de segurança FINAL (atomicidade — "nunca deixar o lead no vácuo"): cobre tanto
    # o caso pós-tool (acima) quanto o turno normal vazio sem tool (ex: input vazio/figurinha
    # → completion_tokens=0, regressão observada: Lanny). Escolhe a mensagem mais contextual:
    # transição de stage > mídia > genérico.
    if not assistant_text:
        assistant_text = _empty_fallback_text(media_tool_used, transitioned_to_stage)
        logger.error(
            "[AGENT EMPTY] resposta final vazia para conv %s (tool_iterations=%d) — "
            "usando fallback de segurança (stage=%s, media=%s)",
            conversation_id, tool_iterations, transitioned_to_stage, media_tool_used,
        )

    logger.info(
        f"SDR agent response for conv {conversation_id} (stage={stage}, prompt_key={prompt_key}): {assistant_text[:100]}..."
    )
    return assistant_text
