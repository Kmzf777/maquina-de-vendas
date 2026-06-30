import asyncio
import json
import logging
import re
from datetime import datetime, timezone, timedelta

import httpx
import openai
from openai import AsyncOpenAI

from app.config import settings
from app.agent.prompts.base import build_base_prompt, FINAL_INSTRUCTION
from app.agent.prompts import get_stage_prompts
from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context
from app.agent.catalog import get_products_by_funnel
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
# DEPRECADO (2026-06-24): este stall genérico NÃO é mais enviado. Disparava sobre mensagens
# perfeitamente válidas quando o gemini devolvia completion_tokens=0 (auditoria leads
# 5549984064339 / 5551984772757), enganando o cliente ("sua mensagem chegou cortada" sendo
# que ela chegou inteira). Desde a Change C (2026-06-30) o turno vazio genérico NÃO é mais
# abortado em silêncio: após um retry sem thinking, envia-se _SAFETY_FALLBACK_GENERIC — um
# recomeço HONESTO que re-engaja o lead sem mentir que a mensagem chegou cortada (ver run_agent).
# Mantido só como referência/constante de teste.
_SAFETY_FALLBACK_MESSAGE = (
    "acho que sua mensagem chegou cortada aqui\n\nme manda de novo por texto?"
)
# Resposta de segurança contextual para quando a última tool usada foi de mídia
# (enviar_fotos / enviar_foto_produto). O genérico stall é nonsense
# após um catálogo — preferimos uma pergunta de avanço coerente com o envio.
_SAFETY_FALLBACK_MEDIA = (
    "te mandei as fotos aqui no chat\n\nqual delas chamou mais a sua atenção?"
)
# Fallback genérico honesto (Change C, 2026-06-30): usado quando não há contexto coerente
# (sem transição de stage, sem mídia) e o LLM ficou mudo mesmo após o retry.
# NÃO afirma que a mensagem "chegou cortada" (proibido — auditoria 2026-06-24).
# Segue a voz da Valéria: minúsculas, sem ponto final, max 2 bolhas curtas, sem emoji.
_SAFETY_FALLBACK_GENERIC = (
    "opa, me embolei aqui por um instante\n\nme conta de novo o que você precisa que eu já te ajudo"
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
        "pelo que você me contou, faz sentido a gente falar de condições pro seu negócio\n\n"
        "você procura o café pra revender ou pra servir no seu estabelecimento?"
    ),
    "private_label": (
        "que ideia bacana ter o café com a sua própria marca\n\n"
        "me conta um pouco do que você tem em mente?"
    ),
    "exportacao": (
        "mercado externo é um universo e tanto\n\n"
        "você já tem algum país de destino em mente pra levar o café?"
    ),
    "consumo": (
        "show, pra eu te indicar o ideal pro seu dia a dia, você prefere o café em grãos "
        "ou já moído?"
    ),
}


def _empty_fallback_text(media_tool_used: bool, transitioned_to_stage: str | None = None) -> str:
    """Return a CONTEXTUALLY COHERENT fallback for the empty-response case.

    Priority order (highest first):
      1. Pergunta de avanço, quando houve um mudar_stage neste turno (transição silenciosa).
      2. Pergunta de fechamento de mídia, quando uma tool de foto foi usada.
      3. Fallback genérico honesto (_SAFETY_FALLBACK_GENERIC): re-engaja o lead sem afirmar
         que a mensagem "chegou cortada" (proibido — auditoria 2026-06-24). Garante que o
         lead NUNCA fica em silêncio total após um turno com historico real (Change C 2026-06-30).

    Extracted as a pure helper so it can be unit-tested without running run_agent.
    """
    if transitioned_to_stage and transitioned_to_stage in _STAGE_TRANSITION_FALLBACKS:
        return _STAGE_TRANSITION_FALLBACKS[transitioned_to_stage]
    if media_tool_used:
        return _SAFETY_FALLBACK_MEDIA
    return _SAFETY_FALLBACK_GENERIC


# ---------------------------------------------------------------------------
# Rede de segurança contra vazamento de function-call em CÓDIGO (lead 5575992317829)
# ---------------------------------------------------------------------------
# O gemini-2.5-flash, via endpoint OpenAI-compat, às vezes serializa o function-call na
# sua forma de CÓDIGO nativa DENTRO de message.content (em vez de tool_calls), ex.:
#   <tool_code> print(default_api.encaminhar_humano(mensagem_despedida='...')) </tool_code>
# Como tool_calls fica vazio, o `while message.tool_calls` nunca executa a tool e o código
# cru ia direto pro cliente (assistant_text = message.content). A Valéria NUNCA manda
# código, markdown cercado ou XML pra um lead de café — então qualquer uma destas
# assinaturas é vazamento e é removida ANTES do envio. Defesa em profundidade junto do
# guardrail de prompt (base.py): o prompt reduz a frequência; isto garante que o cliente
# nunca veja código, de forma determinística.
_TOOL_CODE_BLOCK_RE = re.compile(r"<\s*tool_code\s*>.*?<\s*/\s*tool_code\s*>", re.DOTALL | re.IGNORECASE)
_FENCED_BLOCK_RE = re.compile(r"```[\w-]*\b.*?```", re.DOTALL)
_BARE_PRINT_LINE_RE = re.compile(r"^\s*print\s*\(.*\)\s*$")


def _strip_leaked_tool_code(text: str) -> str:
    """Remove vazamentos de function-call em código do texto final, preservando o humano.

    Função pura para ser unit-testada sem rodar run_agent. Remove:
      - blocos <tool_code>...</tool_code> (com ou sem print/default_api dentro)
      - blocos markdown cercados por ``` (Valéria nunca manda código ao lead)
      - tags <tool_code> órfãs (sem par)
      - linhas que são chamada crua: `print(...)` ou contêm `default_api.<tool>(...)`
    Colapsa quebras de linha resultantes e apara as bordas.
    """
    if not text:
        return text
    cleaned = _TOOL_CODE_BLOCK_RE.sub("", text)
    cleaned = _FENCED_BLOCK_RE.sub("", cleaned)
    kept: list[str] = []
    for line in cleaned.splitlines():
        low = line.strip().lower()
        if low in ("<tool_code>", "</tool_code>"):
            continue
        if "default_api." in low:
            continue
        if _BARE_PRINT_LINE_RE.match(line):
            continue
        kept.append(line)
    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _sanitize_assistant_text(text: str, conversation_id: str, stage: str | None, source: str) -> str:
    """Passa QUALQUER texto de saída do agente pela rede anti-tool_code e loga o vazamento.

    Centraliza a defesa em profundidade: toda saída textual de run_agent (resposta inicial,
    retry-on-empty, despedida de opt-out) passa por aqui antes de ser retornada OU avaliada como
    vazia — fechando a lacuna do retry (lead 5567996264477), onde o leak reincidente ia cru pro
    cliente. Se o strip esvaziar, o chamador cai no fluxo de vazio (retry / fallback / silêncio).
    """
    pre = text or ""
    cleaned = _strip_leaked_tool_code(pre)
    if cleaned != pre:
        logger.error(
            "[TOOL_CODE LEAK] Gemini vazou function-call como texto em conv %s "
            "(source=%s, stage=%s) — sanitizado antes do envio. Vazamento: %.200s",
            conversation_id, source, stage, pre,
        )
    return cleaned


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


def _schedule_memory_refresh(lead_id: str) -> None:
    """Gatilho B (Camada de Memória): agenda um refresh do Dossiê fire-and-forget após uma
    mudança de stage (alto sinal). Não bloqueia o turno; o lock no banco resolve a corrida
    com o Gatilho A (worker). Fail-soft: nunca levanta para o caller."""
    if not lead_id:
        return
    try:
        from app.agent.memory_manager import refresh_lead_memory
        asyncio.create_task(refresh_lead_memory(lead_id))
    except Exception as exc:  # pragma: no cover
        logger.warning("_schedule_memory_refresh: falha ao agendar refresh p/ lead %s: %s", lead_id, exc)


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


def _build_catalog_block(catalog_text: str) -> str:
    """Envolve o catálogo dinâmico numa tag XML com a diretriz anti-alucinação.

    Injetado entre o prompt de estágio e o FINAL_INSTRUCTION para servir de fonte
    de verdade de produtos/preços/imagens — substituindo o grounding estático.
    """
    return (
        "<catalogo_de_produtos>\n"
        "ATENÇÃO: Você DEVE usar EXCLUSIVAMENTE os produtos, preços e links de "
        "imagens listados abaixo. NUNCA invente preços, pacotes ou imagens que não "
        "estejam nesta lista. Se o cliente pedir um produto que não está aqui, diga "
        "que vai verificar com o time e, se fizer sentido, encaminhe para o Joao Bras.\n\n"
        "## PREÇOS — REGRA ABSOLUTA (tabela fixa)\n"
        "Os valores abaixo são TABELADOS e EXATOS. Você está ESTRITAMENTE PROIBIDA de "
        "inventar, arredondar ou alterar qualquer valor ou centavo. Informe o preço "
        "EXATAMENTE como está escrito aqui, com o mesmo centavo.\n"
        "- NUNCA amacie o valor com 'por volta de', 'em torno de', 'mais ou menos', "
        "'uns', 'aproximadamente' ou 'a partir de' — preço de tabela NÃO é estimativa.\n"
        "- Quando o mesmo café tiver variações com preços diferentes (ex.: embalagem do "
        "cliente vs. embalagem Canastra, moído vs. em grãos, 250g vs. 500g), CONFIRME "
        "com o cliente qual variação ele quer ANTES de dizer o preço. Nunca chute a "
        "variação nem misture os valores de duas variações.\n"
        "- Se o preço exato do que o cliente pediu não estiver na lista, NÃO estime: "
        "diga que confirma com o João Brás.\n\n"
        f"{catalog_text}\n"
        "</catalogo_de_produtos>"
    )


def build_system_prompt(
    lead: dict,
    stage: str,
    prompt_key: str = "valeria_inbound",
    lead_context: dict | None = None,
    catalog_text: str | None = None,
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
    # Ordem hierarquica: base (persona) -> estagio (roteiro do funil) -> catalogo
    # dinamico -> instrucao final.
    # FINAL_INSTRUCTION fica por ultimo para que <final_instruction> seja literalmente a
    # ultima tag da string, preservando a hierarquia XML esperada pelo Gemini.
    parts = [base, stage_prompt]
    if catalog_text:
        parts.append(_build_catalog_block(catalog_text))
    parts.append(FINAL_INSTRUCTION)
    return "\n\n".join(parts)


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
    catalog_text = get_products_by_funnel(stage, prompt_key=prompt_key)
    system_prompt = build_system_prompt(
        lead, stage, prompt_key=prompt_key, lead_context=lead_context, catalog_text=catalog_text
    )

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
    # Primeiro turno REAL = o lead ainda não tem nenhuma mensagem 'user' no histórico
    # (a mensagem atual já foi removida acima). A abertura outbound (broadcast/followup)
    # é uma mensagem 'assistant' e NÃO conta como turno de diálogo — por isso checamos a
    # ausência de mensagens 'user', e não len(history)==0. O bug anterior (len==0) nunca
    # era verdade em outbound, pois a abertura ficava no histórico → o contexto de 1º turno
    # outbound era código morto (auditoria 2026-06-22).
    is_first_turn = not any(m.get("role") == "user" for m in history)
    campaign_message = (lead_context or {}).get("campaign_message")
    # Fallback: deriva a abertura fixa a partir do próprio template já enviado
    # (broadcast/followup no histórico), já que campaign_message raramente é plumbado
    # via lead_context. Sem isso, build_outbound_first_turn_context nunca dispararia.
    dispatch_intent = None
    if is_outbound and is_first_turn and not campaign_message:
        dispatch_msg = next(
            (
                m
                for m in reversed(history)
                if m.get("role") == "assistant" and m.get("sent_by") in ("broadcast", "followup")
            ),
            None,
        )
        if dispatch_msg:
            campaign_message = dispatch_msg.get("content")
            # Eixo 2c: a intenção do disparo (warm_lp/cold) muda o frame do 1º turno.
            dispatch_intent = ((dispatch_msg.get("metadata") or {}).get("dispatch") or {}).get("intent")

    if is_outbound and is_first_turn and campaign_message:
        campaign_segment = (lead_context or {}).get("campaign_segment")
        ctx = build_outbound_first_turn_context(
            campaign_message,
            lead.get("name"),
            campaign_segment=campaign_segment,
            template_intent=dispatch_intent,
            lp_message=(lead_context or {}).get("lp_message"),
        )
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
            return _sanitize_assistant_text(message.content or "", conversation_id, stage, source="optout") \
                or "sem problema, não te mando mais mensagem por aqui\n\nqualquer coisa é só chamar"

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
                catalog_text = get_products_by_funnel(stage, prompt_key=prompt_key)
                system_prompt = build_system_prompt(
                    lead, stage, prompt_key=prompt_key, lead_context=lead_context, catalog_text=catalog_text
                )
                messages[0] = {"role": "system", "content": system_prompt}
                if lead_id:
                    current_meta = lead.get("metadata") or {}
                    updated_meta = {**current_meta, "previous_stage": old_stage}
                    update_lead(lead_id, metadata=updated_meta)
                    lead["metadata"] = updated_meta
                    # Gatilho B: consolida o Dossiê do lead após a transição de segmento.
                    _schedule_memory_refresh(lead_id)
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

    # REDE DE SEGURANÇA ANTI-TOOL_CODE (lead 5575992317829, auditoria 2026-06-25). O gemini
    # às vezes vaza o function-call como CÓDIGO no content (tool_calls vazio), e o código cru
    # ia direto pro cliente. Removemos qualquer vazamento ANTES do envio. Se o strip esvaziar
    # o texto (o turno era SÓ código), caímos no RETRY-ON-EMPTY abaixo (tools=None → o modelo
    # não consegue emitir tool_code e devolve fala humana real). Determinístico: o cliente
    # nunca vê código, independente do prompt.
    assistant_text = _sanitize_assistant_text(assistant_text, conversation_id, stage, source="initial")

    # RETRY-ON-EMPTY (unificado — auditoria 2026-06-24, leads 5549984064339 / 5551984772757,
    # reincidência da Carla). gemini-2.5-flash às vezes queima o budget pensando e devolve
    # completion_tokens=0, MESMO num input perfeitamente válido. A chamada inicial deste turno
    # NÃO desliga o thinking, então o vazio é justamente o turno em que o modelo "pensou demais".
    # Vale para QUALQUER turno vazio (com ou sem tool — antes só reentrávamos após tool, e o turno
    # normal vazio caía no stall enganoso). Tentamos UM retry silencioso com o thinking 100% off,
    # que costuma recuperar o texto real. NUNCA derruba o turno por exceção — só loga.
    #
    # Change A (2026-06-30): o retry mantém as tools do stage, EXCETO quando o vazio veio de um
    # loop de tools descontrolado (tool_iterations > MAX_TOOL_ITERATIONS), único caso genuinamente
    # prejudicial — aí sim tools=None. O bug anterior passava tools=None sempre, castrando o agente
    # quando o turno vazio precisava de encaminhar_humano/mudar_stage: o modelo re-vazava o call
    # como tool_code, o sanitizer limpava, e o lead ficava 21h em silêncio (lead private_label,
    # auditoria 2026-06-30).
    if not assistant_text:
        logger.warning(
            "[AGENT EMPTY] resposta vazia (tool_iterations=%d) para conv %s — retry silencioso sem thinking",
            tool_iterations, conversation_id,
        )
        # Change A: preserva tools salvo em loop descontrolado
        retry_tools = None if tool_iterations > MAX_TOOL_ITERATIONS else (tools or None)
        try:
            retry_resp = await _create_with_retry(_get_client(model),
                model=model,
                messages=messages,
                tools=retry_tools,
                temperature=0.4,
                max_tokens=MAX_OUTPUT_TOKENS,
                stop=_STOP_SEQUENCES,
                **_gemini_thinking_off(model),
            )
            if retry_resp.usage:
                track_token_usage(
                    lead_id=lead_id,
                    stage=stage,
                    model=model,
                    call_type="response",
                    prompt_tokens=retry_resp.usage.prompt_tokens,
                    completion_tokens=retry_resp.usage.completion_tokens,
                )
            retry_msg = retry_resp.choices[0].message
            # Change B (2026-06-30): se o retry recuperou tool_calls (porque tools foram mantidas),
            # executa a intenção em vez de silenciá-la. Cobre o caso exato do lead private_label:
            # a intenção era encaminhar_humano mas o retry sem tools re-vazava como tool_code.
            # Apenas UM nível de recuperação — não re-inicia o ciclo ReAct completo.
            if retry_msg.tool_calls and retry_tools is not None:
                for _tc in retry_msg.tool_calls:
                    _rname = _tc.function.name
                    if _rname in _MEDIA_TOOL_NAMES:
                        media_tool_used = True
                    try:
                        _rargs = json.loads(_tc.function.arguments)
                    except json.JSONDecodeError as _je:
                        # Mesmo contrato do loop principal: JSON malformado → PULA o tool_call.
                        # NUNCA chama execute_tool com {} — tools como salvar_nome fazem args["name"]
                        # e estourariam KeyError (engolido pelo except externo) = corrupção silenciosa.
                        logger.error(
                            "[RETRY TOOL] JSON inválido para %s em conv %s — pulando: %s",
                            _rname, conversation_id, _je,
                        )
                        continue
                    # mudar_stage recuperado: rastreia o novo stage (Minor #4) para que, se o turno
                    # ainda terminar vazio, _empty_fallback_text escolha a pergunta de avanço do
                    # stage em vez do genérico. Mínimo: só guardamos a string, sem rebuild de prompt.
                    if _rname == "mudar_stage":
                        _new_stage = _rargs.get("stage")
                        if _new_stage:
                            transitioned_to_stage = _new_stage
                    try:
                        await execute_tool(
                            _rname, _rargs, lead_id, lead.get("phone", ""), conversation_id
                        )
                    except Exception as _te:
                        logger.error(
                            "[RETRY TOOL] %s levantou exceção em conv %s: %s",
                            _rname, conversation_id, _te, exc_info=True,
                        )
                # Tools terminais recuperadas no retry — mesma ordem e contrato do loop principal,
                # ANTES do fallback genérico (senão o lead recebe despedida + re-engajamento juntos).
                _retry_names = {_tc.function.name for _tc in retry_msg.tool_calls}
                # encaminhar_humano → sentinel None (handoff; card enviado dentro de execute_tool)
                if "encaminhar_humano" in _retry_names:
                    return None
                # registrar_optout → despedida sanitizada (mesmo default do loop principal)
                if "registrar_optout" in _retry_names:
                    return _sanitize_assistant_text(
                        retry_msg.content or "", conversation_id, stage, source="retry-optout"
                    ) or "sem problema, não te mando mais mensagem por aqui\n\nqualquer coisa é só chamar"
                # registrar_sem_interesse_atual → silêncio é correto após soft rejection.
                # A regra "nunca mudo" vale só para turnos normais, não para descarte.
                if "registrar_sem_interesse_atual" in _retry_names:
                    return ""
                # Demais tools recuperadas: executadas acima; cai no fallback final (Change C)
                # para garantir que o lead receba texto
            assistant_text = _sanitize_assistant_text(
                retry_msg.content or "", conversation_id, stage, source="retry"
            )
        except Exception as _exc:
            logger.error(
                "[AGENT EMPTY] retry silencioso falhou para conv %s: %s", conversation_id, _exc,
            )

    # Ainda vazio após o retry. Escolhemos o fallback mais contextualmente coerente disponível
    # (transição de stage > mídia > genérico honesto). Change C (2026-06-30): _empty_fallback_text
    # nunca retorna None — o caso genérico agora devolve _SAFETY_FALLBACK_GENERIC em vez de abortar
    # em silêncio. Silêncio total deixa o lead congelado (caso private_label, 21h sem resposta);
    # um recomeço honesto é sempre preferível. O texto NÃO afirma que a mensagem "chegou cortada".
    if not assistant_text:
        assistant_text = _empty_fallback_text(media_tool_used, transitioned_to_stage)
        logger.error(
            "[AGENT EMPTY] vazio após retry para conv %s — fallback "
            "(stage=%s, media=%s, tool_iterations=%d)",
            conversation_id, transitioned_to_stage, media_tool_used, tool_iterations,
        )

    logger.info(
        f"SDR agent response for conv {conversation_id} (stage={stage}, prompt_key={prompt_key}): {assistant_text[:100]}..."
    )
    return assistant_text
