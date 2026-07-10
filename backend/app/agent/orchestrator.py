import asyncio
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone, timedelta

import httpx
from google.genai import errors as genai_errors

from app.agent import budget_guard
from app.agent.gemini_client import (
    GenerateResult,
    build_tools,
    function_response_content,
    generate,
    model_content,
    user_content,
)
from app.config import settings
from app.agent.prompts.base import build_base_prompt, FINAL_INSTRUCTION
from app.agent.prompts import get_stage_prompts
from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context
from app.agent.catalog import get_products_by_funnel
from app.agent.tools import get_tools_for_stage, execute_tool
from app.agent.adherence import (
    find_verbatim_prompt_echo,
    is_repeated_question,
    normalize_orthography,
    strip_prohibited_phrases,
)
from app.conversations.service import (
    get_history,
    resolve_message_text_by_wamid,
    resolve_message_texts_by_wamids,
)
from app.agent.token_tracker import track_token_usage
from app.agent_profiles.service import get_agent_profile
from app.leads.service import get_lead, sanitize_display_name, update_lead

logger = logging.getLogger(__name__)

TZ_BR = timezone(timedelta(hours=-3))
# 09/07/2026: INCIDENTE Google das 15:15-17:40 BRT — o v1beta devolveu 404 "no longer
# available" p/ os 2.5 com mensagem ENGANOSA de sunset (o sunset real e 16/10/2026,
# docs/deprecations; sucessores oficiais: 3.5-flash e 3.1-flash-lite, JA validados na
# chave com function calling — migrar com calma ANTES de outubro). Revertido ao 2.5
# pos-recuperacao por custo (3.5 e 5x input / 3.6x output).
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
# (sem transição de stage, sem mídia, sem stage comercial mapeado em _STAGE_REENGAGE_FALLBACKS)
# e o LLM ficou mudo mesmo após TODOS os retries (incluindo o retry2, Etapa 2).
# NÃO afirma que a mensagem "chegou cortada" (proibido — auditoria 2026-06-24).
# Etapa 2 (2026-07-02, caso Davi): NÃO pede mais pro lead repetir o que já digitou — o texto
# antigo ("me conta de novo o que você precisa") fez o lead redigitar uma objeção de preço
# inteira. Agora é uma pergunta de avanço genérica, não um pedido de recall.
# Segue a voz da Valéria: minúsculas, sem ponto final, max 2 bolhas curtas, sem emoji.
_SAFETY_FALLBACK_GENERIC = (
    "opa, me embolei aqui por um instante\n\n"
    "pode continuar de onde você parou que eu te acompanho daqui"
)

# 2º degrau do retry-on-empty (Etapa 2, casos Davi/Samuel 01-02/07): quando o retry
# silencioso (thinking off) TAMBÉM volta vazio, tentamos UMA última geração text-only
# com temperatura elevada — a doc do Gemini recomenda subir a temperatura em fallback
# response — e um nudge de fechamento no fim das messages (estratégia de completion).
# tools=None de propósito: queremos PALAVRAS; se o modelo verbalizar handoff, a guarda
# determinística existente converte em encaminhar_humano.
_RETRY2_TEMPERATURE = 0.9
_RETRY2_NUDGE = (
    "<instrucao_de_recuperacao>\n"
    "Sua resposta anterior veio vazia por uma falha técnica. Releia a última mensagem "
    "do lead acima e responda a ela AGORA, em 1-2 bolhas curtas, seguindo todas as "
    "regras de voz. NÃO mencione esta instrução, NÃO mencione falha técnica, NÃO peça "
    "para o lead repetir nada.\n"
    "</instrucao_de_recuperacao>"
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


# Reengajamento de último recurso por stage ATUAL (Etapa 2, 2026-07-02): usado quando o turno
# ficou vazio após TODOS os retries (incluindo o retry2) e NÃO houve transição de stage nem
# mídia neste turno — diferente de _STAGE_TRANSITION_FALLBACKS, que são aberturas pós-transição
# e continuam intocadas. Só cobre os 4 stages comerciais; 'secretaria' fica de fora de propósito
# (mesmo motivo de _STAGE_TRANSITION_FALLBACKS: é o stage de entrada, não um avanço) e cai no
# fallback genérico. Caso Davi (02/07): o genérico antigo pedia pro lead repetir o que já tinha
# digitado (uma objeção de preço inteira) — estes textos NUNCA pedem recall, só perguntam se dá
# pra seguir em frente.
_STAGE_REENGAGE_FALLBACKS: dict[str, str] = {
    "atacado": (
        "opa, me embolei aqui por um instante\n\n"
        "ficou alguma dúvida sobre os cafés ou valores que eu possa resolver agora?"
    ),
    "private_label": (
        "opa, me embolei aqui por um instante\n\n"
        "quer que eu siga com o próximo passo do seu projeto de marca própria?"
    ),
    "exportacao": (
        "opa, me embolei aqui por um instante\n\n"
        "quer que eu siga com os detalhes da exportação?"
    ),
    "consumo": (
        "opa, me embolei aqui por um instante\n\n"
        "ficou alguma dúvida sobre os cafés ou a loja que eu possa resolver agora?"
    ),
}


def _empty_fallback_text(
    media_tool_used: bool,
    transitioned_to_stage: str | None = None,
    current_stage: str | None = None,
) -> str:
    """Return a CONTEXTUALLY COHERENT fallback for the empty-response case.

    Priority order (highest first):
      1. Pergunta de avanço, quando houve um mudar_stage neste turno (transição silenciosa).
      2. Pergunta de fechamento de mídia, quando uma tool de foto foi usada.
      3. Reengajamento de último recurso do stage ATUAL (_STAGE_REENGAGE_FALLBACKS, Etapa 2):
         sem transição nem mídia neste turno, mas o lead já está num stage comercial mapeado.
         Pergunta de avanço coerente com esse stage — NUNCA pede pro lead repetir o que já
         disse (caso Davi 02/07: lead redigitou a objeção de preço inteira).
      4. Fallback genérico honesto (_SAFETY_FALLBACK_GENERIC): último recurso quando nem
         transição, nem mídia, nem stage comercial mapeado se aplicam (ex.: secretaria).
         NÃO afirma que a mensagem "chegou cortada" (proibido — auditoria 2026-06-24) e,
         desde a Etapa 2, também NÃO pede pra repetir. Garante que o lead NUNCA fica em
         silêncio total após um turno com historico real (Change C 2026-06-30).

    Os itens 3 e 4 são ambos "último recurso" para fins da exceção de silêncio em run_agent —
    ver _is_last_resort_fallback logo abaixo. Só os itens 1 e 2 são fallbacks CONTEXTUAIS de
    verdade e continuam vencendo mesmo quando essa exceção se aplicaria.

    Extracted as a pure helper so it can be unit-tested without running run_agent.
    """
    if transitioned_to_stage and transitioned_to_stage in _STAGE_TRANSITION_FALLBACKS:
        return _STAGE_TRANSITION_FALLBACKS[transitioned_to_stage]
    if media_tool_used:
        return _SAFETY_FALLBACK_MEDIA
    if current_stage and current_stage in _STAGE_REENGAGE_FALLBACKS:
        return _STAGE_REENGAGE_FALLBACKS[current_stage]
    return _SAFETY_FALLBACK_GENERIC


def _is_last_resort_fallback(text: str, current_stage: str | None) -> bool:
    """True quando `text` é um fallback de ÚLTIMO RECURSO (reengajamento por stage OU
    genérico) — os dois casos em que a exceção de silêncio de run_agent (soft_reject_used /
    suppress_generic_fallback) deve vencer e o turno terminar em "" em vez de reabrir a
    conversa. Fallbacks CONTEXTUAIS (transição de stage, mídia) NUNCA são "último recurso" e
    continuam vencendo a exceção — comportamento preservado da Change C (2026-06-30).

    Por quê uma função separada em vez de `_empty_fallback_text` devolver uma tupla: o
    contrato atual de `_empty_fallback_text` (retorna só `str`) já é testado diretamente por
    vários testes existentes (test_post_media_closing.py, test_post_stage_transition_closing.py,
    test_orchestrator_retry_no_silence_2026_06_30.py) — mudar pra tupla quebraria todos eles
    sem necessidade. A comparação antiga `assistant_text == _SAFETY_FALLBACK_GENERIC` (bloco
    final de run_agent) ficaria cega ao novo _STAGE_REENGAGE_FALLBACKS: cada stage comercial
    tem um texto DIFERENTE, então a igualdade direta com a constante genérica nunca bateria
    pra esses casos (Etapa 2, Task 2) — daí este helper, que sabe reconhecer os dois formatos.
    """
    if text == _SAFETY_FALLBACK_GENERIC:
        return True
    return current_stage is not None and _STAGE_REENGAGE_FALLBACKS.get(current_stage) == text


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
    # Guarda de aderência (2026-07-04): remove frases proibidas de jargão de
    # call-center ("pra te direcionar da melhor forma") que fogem da voz da
    # Valéria. Função pura, testada isoladamente em app.agent.adherence.
    after_phrase_strip = strip_prohibited_phrases(cleaned)
    if after_phrase_strip != cleaned:
        logger.info(
            "[ADHERENCE GUARD] frase proibida removida do texto final em conv %s "
            "(source=%s, stage=%s)",
            conversation_id, source, stage,
        )
    # Ortografia única (auditoria 08/07): o modelo oscila entre "você" e "voce" na
    # MESMA conversa (bolha real misturou "é" com "torrefacao/xicara"). O normalizador
    # determinístico fixa as palavras inequívocas do vocabulário da persona; URLs
    # ficam intactas (ver app.agent.adherence.normalize_orthography).
    normalized = normalize_orthography(after_phrase_strip)
    if normalized != after_phrase_strip:
        logger.debug(
            "[ORTHO GUARD] acentuação normalizada em conv %s (source=%s)",
            conversation_id, source,
        )
    return normalized


# ---------------------------------------------------------------------------
# Guarda determinística de handoff verbalizado (2026-06-30)
# ---------------------------------------------------------------------------
# Defesa em profundidade: quando a Valéria ANUNCIA a transferência no texto comum
# ("vou te conectar com o João", "vou deixar o contato dele aqui") SEM chamar
# encaminhar_humano, o lead fica parado — o cartão de contato nunca sai e a IA
# continua ativa. Este guard detecta o CTA no texto final e força o handoff.
#
# Invariante: se o código chegou até _looks_like_handoff_announcement, encaminhar_humano
# NÃO foi executado neste turno (uma tool call real teria retornado None sentinel mais
# cedo no loop) — não há risco de double-firing.
#
# Frases que NÃO disparam (menções informacionais):
#   "quem prepara isso é o Joao Bras"
#   "vou deixar salvo pro Joao dar uma olhada"
#   "você já tá em boas mãos com o time"
#   "qualquer coisa é só chamar"
# O guard é construído em torno do CTA de CONTATO/CONECTAR/TRANSFERIR, nunca do
# nome "João Bras" isolado.

def _strip_diacritics(text: str) -> str:
    """Remove diacríticos via NFD + filtro de combining marks (Mn)."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def _normalize_for_handoff_re(text: str) -> str:
    """Lowercase + remoção de diacríticos para matching acento-insensitivo."""
    return _strip_diacritics(text.lower())


# Padrões compilados uma vez; operam sobre texto já normalizado (lowercase, sem acentos).
_HANDOFF_ANNOUNCEMENT_RE = re.compile(
    r"(?:"
    r"vou te conectar"
    r"|deixa.{0,10}eu te conectar"   # "deixa eu te conectar" / "deixa-eu te conectar"
    r"|te conectar com o joao"
    r"|vou deixar o contato"          # "vou deixar o contato dele aqui"
    r"|deixando o contato"
    r"|te passar o contato"
    r"|contato dele aqui"
    r"|contato do joao aqui"
    r"|vou transferir"
    r"|vou te transferir"
    r"|vou te passar (?:pro|para o) joao"
    r")"
)


def _looks_like_handoff_announcement(text: str) -> bool:
    """Return True ONLY for unambiguous transfer-CTA phrasing.

    Accent- and case-insensitive (via diacritic stripping + lowercase).
    Returns False for mere informational mentions of the seller that are NOT
    a transfer CTA — e.g. "quem cuida disso é o Joao Bras", "em boas mãos".

    Função pura — sem I/O, testável sem mocks.
    """
    if not text:
        return False
    return bool(_HANDOFF_ANNOUNCEMENT_RE.search(_normalize_for_handoff_re(text)))


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


def _is_gemini_model(model: str) -> bool:
    return model.startswith("gemini-")


def _thinking_off_for(model: str) -> bool:
    """True quando o 'thinking' deve ser DESLIGADO nas chamadas mecânicas (pós-tool,
    retries) — via ThinkingConfig(thinking_budget=0) no gemini_client.

    Causa raiz do Bug 2: o flash gasta o budget de saída pensando e devolve saída
    visível zero logo após executar uma tool, deixando o lead mudo. Vale para a
    família flash/lite (2.5 e 3.x); os modelos *pro* seguem pensando (False).
    """
    return model.startswith("gemini-") and "pro" not in model and ("flash" in model or "lite" in model)


# Drops de conexão HTTP/2 (GOAWAY) sob concorrência (rajada de disparo) derrubavam
# chamadas ao LLM. Retry localizado é mais seguro que reexecutar o turno inteiro no
# processor — este reexecutaria tools já aplicadas (encaminhar_humano, mudar_stage).
# Chamadas a gemini_client.generate() não têm efeitos colaterais → seguras para retry.
_LLM_RETRY_ATTEMPTS = 3
_LLM_RETRY_DELAY = 2  # segundos


class LLMUnavailableError(Exception):
    """LLM persistentemente indisponível após esgotar os retries (conexão/403/429/5xx).

    Distingue 'LLM fora' de um bug qualquer: o processor usa este tipo para acionar o
    fallback de handoff (encaminhar_humano) em vez de falhar em silêncio.
    """


class LLMExhaustedError(LLMUnavailableError):
    """Exaustão LONGA do LLM — não volta em minutos (wartime 10/07/2026).

    Distingue "cofre vazio" (teto de gasto interno, quota diária/billing do Google) de
    um outage transitório de segundos. Antes, tudo herdava só de LLMUnavailableError e
    caía no MESMO parking de 30min: como o bloqueio dura até a virada do dia, todo lead
    que respondia ao disparo após o estouro era estacionado por 30min e recebia handoff
    CEGO definitivo (ai_enabled=false) — repetição industrializada do incidente de 08/07
    (2/9 respostas queimadas em 13min de outage). Com esta categoria, o parking usa um
    deadline de reset (virada do dia) em vez da janela curta. Continua sendo
    LLMUnavailableError por retrocompatibilidade: todo `except LLMUnavailableError`
    existente segue capturando."""


class LLMBudgetExceededError(LLMExhaustedError):
    """Teto diário de gasto atingido (kill-switch INTERNO). Reclassificado (10/07) de
    LLMUnavailableError para LLMExhaustedError: o bloqueio dura até a virada do dia (UTC),
    então o turno deve ser estacionado até o reset do budget_guard — não por 30min.
    Ver app/agent/budget_guard.py."""


class LLMQuotaExhaustedError(LLMExhaustedError):
    """Quota diária/billing esgotada do LADO GOOGLE (429 com marcador de quota diária,
    ou 403 persistente). Retry em minutos é inútil (o reset é na virada do dia
    America/Los_Angeles, fuso das quotas diárias da Gemini API) e só queima RPM —
    o parking usa esse horizonte como deadline. Wartime 10/07/2026."""


def _initial_thinking_off(model: str) -> bool:
    """Thinking da PRIMEIRA chamada (raciocínio inicial / escolha de tools).

    Por design endurecido por incidentes, o thinking já fica DESLIGADO em todas as chamadas
    mecânicas (pós-tool, follow-up, summary, memória) e LIGADO só nesta, a de alto esforço.
    Este knob permite desligá-lo TAMBÉM aqui via env, trocando qualidade de raciocínio por
    custo, sem deploy:
        LLM_INITIAL_THINKING=off  → thinking off também na 1ª chamada.
    Default (ausente/qualquer outro valor) = LIGADO — preserva o comportamento atual e a
    decisão testada em test_gemini_thinking_off_post_tool.py.
    """
    if os.environ.get("LLM_INITIAL_THINKING", "on").strip().lower() == "off":
        return _thinking_off_for(model)
    return False


def _genai_status_code(exc: genai_errors.APIError) -> int | None:
    """Extrai o status HTTP de um erro do google-genai (APIError.code)."""
    code = getattr(exc, "code", None)
    return code if isinstance(code, int) else None


# Marcador de quota DIÁRIA num 429 do Google: a mensagem cita o eixo do limite, e os
# formatos observados variam ("per day", "PerDay" em métricas camelCase tipo
# GenerateRequestsPerDayPerProjectPerModel, "per_day" em nomes snake_case). O regex
# cobre os três — case-insensitive — sem casar "per minute"/"PerMinute" (rate-limit
# comum, que continua retentável).
_DAILY_QUOTA_RE = re.compile(r"per[\s_-]?day", re.IGNORECASE)


def _is_daily_quota_429(status: int | None, exc: Exception) -> bool:
    """True quando o erro é um 429 de quota DIÁRIA esgotada (não rate-limit de minuto).

    Retentar aqui é inútil (o reset é só na virada do dia do Google) e ainda queima o
    RPM que sobrou — por isso _generate_with_retry converte em LLMQuotaExhaustedError
    IMEDIATO, sem gastar as 3 tentativas."""
    if status != 429:
        return False
    try:
        return bool(_DAILY_QUOTA_RE.search(str(exc)))
    except Exception:
        return False


async def _generate_with_retry(**gen_kwargs) -> GenerateResult:
    """`gemini_client.generate(...)` com retry transitório.

    Retenta drops de conexão (GOAWAY/timeout via httpx) E erros HTTP transitórios do
    provedor (429 rate-limit/quota, 403 billing/permissão negada, 5xx) com backoff
    exponencial, honrando Retry-After quando presente. Erros não-retentáveis (4xx exceto
    403/429) são relançados na hora. Ao esgotar as tentativas → LLMUnavailableError.

    Exceções do SDK nativo: google.genai.errors.APIError (ClientError=4xx, ServerError=5xx),
    com o status em `.code`. Timeouts/quedas de conexão sobem como httpx.TransportError.

    Kill-switch: antes de qualquer tentativa, checa o teto diário de gasto (budget_guard).
    Se estourado, levanta LLMBudgetExceededError (→ handoff) sem sequer chamar o provedor.
    """
    if budget_guard.is_exceeded():
        raise LLMBudgetExceededError(
            f"Teto diário de gasto do LLM atingido (US${budget_guard.today_spend_usd():.2f} "
            f">= US${budget_guard.daily_cost_limit_usd():.2f}) — chamadas bloqueadas ate a "
            f"virada do dia (UTC)."
        )

    last_exc: Exception | None = None
    for attempt in range(1, _LLM_RETRY_ATTEMPTS + 1):
        _delay = _LLM_RETRY_DELAY * (2 ** (attempt - 1))
        try:
            return await generate(**gen_kwargs)
        except httpx.TransportError as exc:
            last_exc = exc
            logger.warning(
                "[LLM RETRY] tentativa %d/%d falhou (conexão): %s",
                attempt, _LLM_RETRY_ATTEMPTS, exc,
            )
        except genai_errors.APIError as exc:
            status = _genai_status_code(exc)
            if _is_daily_quota_429(status, exc):
                # Quota DIÁRIA esgotada (wartime 10/07): retry é inútil até a virada do
                # dia e queima o RPM restante → classifica como exaustão longa na hora.
                raise LLMQuotaExhaustedError(
                    f"Quota diária do provedor esgotada (429 per-day): {exc}"
                ) from exc
            if status not in (403, 429) and not (isinstance(status, int) and status >= 500):
                raise  # 4xx não-retentável (400/401/404/...) → relança cru
            last_exc = exc
            try:
                _retry_after = float(getattr(exc, "response", None).headers.get("retry-after", 0) or 0)
            except Exception:
                _retry_after = 0.0
            _delay = max(_delay, _retry_after)
            logger.warning(
                "[LLM RETRY] tentativa %d/%d falhou (HTTP %s): %s",
                attempt, _LLM_RETRY_ATTEMPTS, status, exc,
            )
        if attempt < _LLM_RETRY_ATTEMPTS:
            await asyncio.sleep(_delay)
    # Classificação do esgotamento (wartime 10/07): 403 persistente é billing/permissão —
    # historicamente NUNCA é transitório de segundos (o reset depende de ação humana ou da
    # virada do dia) → exaustão longa. O 429-diário já foi convertido em
    # LLMQuotaExhaustedError na 1ª ocorrência acima; o check aqui é cinto de segurança
    # caso ele apareça só na última tentativa intercalado com erros de conexão.
    if isinstance(last_exc, genai_errors.APIError):
        _last_status = _genai_status_code(last_exc)
        if _last_status == 403 or _is_daily_quota_429(_last_status, last_exc):
            raise LLMQuotaExhaustedError(
                f"Quota/billing do provedor esgotado após {_LLM_RETRY_ATTEMPTS} "
                f"tentativas (HTTP {_last_status}): {last_exc}"
            ) from last_exc
    raise LLMUnavailableError(
        f"LLM indisponível após {_LLM_RETRY_ATTEMPTS} tentativas: {last_exc}"
    ) from last_exc


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
    # Harmonizado com a constraint do atacado.py (critical_constraints, "o cliente NUNCA
    # ve a cozinha"): variacao inexistente do MESMO produto (peso/moagem) != produto que
    # a Cafe Canastra nao trabalha — cada caso tem uma saida diferente.
    return (
        "<catalogo_de_produtos>\n"
        "ATENÇÃO: Você DEVE usar EXCLUSIVAMENTE os produtos, preços e links de "
        "imagens listados abaixo. NUNCA invente preços, pacotes ou imagens que não "
        "estejam nesta lista. Se o pedido for uma VARIAÇÃO de um produto listado "
        "(peso ou moagem diferente do catálogo), diga que essa variação não existe "
        "e ofereça a mais próxima da lista. Se for um produto que a Cafe Canastra "
        "não trabalha, diga que vai verificar com o time e, se fizer sentido, "
        "encaminhe para o Joao Bras.\n\n"
        "## PREÇOS — REGRA ABSOLUTA (tabela fixa)\n"
        "Os valores abaixo são TABELADOS e EXATOS. Você está ESTRITAMENTE PROIBIDA de "
        "inventar, arredondar ou alterar qualquer valor ou centavo. Informe o preço "
        "EXATAMENTE como está escrito aqui, com o mesmo centavo.\n"
        "- O NÚMERO é intocável; a MOLDURA da frase segue as regras de voz do seu estágio "
        "(o verbo de referência da regra 12 — 'gira em torno de', 'fica por volta de' — é "
        "permitido AO REDOR do valor exato: 'gira em torno de R$28,70'). PROIBIDO usar a "
        "moldura para vagar ou trocar o número: 'uns 30 reais', valor sem o centavo ou "
        "arredondado é alucinação de preço.\n"
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
    *,
    suppress_generic_fallback: bool = False,
) -> str:
    """Run the SDR AI agent for a conversation and return the response text.

    suppress_generic_fallback (keyword-only): quando True, o ramo de turno vazio NÃO emite nenhum
    fallback de ÚLTIMO RECURSO — nem _SAFETY_FALLBACK_GENERIC nem o reengajamento por stage de
    _STAGE_REENGAGE_FALLBACKS (Etapa 2) — retorna "" em vez disso. Usado por gatilhos INTERNOS
    sem mensagem real do lead (ex.: reabertura proativa ai_scheduled_return no scheduler), onde
    reabrir a conversa sozinho seria incoerente. Fallbacks contextuais de mídia/transição de
    stage continuam valendo. Default False preserva todos os outros callers.
    """
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
    if not _is_gemini_model(model):
        logger.warning("Agent profile model '%s' não é Gemini; coagindo para %s", model, DEFAULT_MODEL)
        model = DEFAULT_MODEL
    else:
        logger.info("Using Gemini model '%s' via native Google GenAI SDK", model)

    tools = build_tools(get_tools_for_stage(stage))
    catalog_text = get_products_by_funnel(stage, prompt_key=prompt_key)
    system_prompt = build_system_prompt(
        lead, stage, prompt_key=prompt_key, lead_context=lead_context, catalog_text=catalog_text
    )

    def _track(call_type: str, result: GenerateResult) -> None:
        """Contabiliza usage nativo no token_usage (colunas do banco inalteradas:
        completion_tokens = saída FATURADA = candidates + thoughts)."""
        um = result.usage_metadata
        if not um:
            return
        track_token_usage(
            lead_id=lead_id,
            stage=stage,
            model=model,
            call_type=call_type,
            prompt_tokens=um.prompt_token_count,
            completion_tokens=um.billed_output_tokens,
            cached_tokens=um.cached_content_token_count,
            reasoning_tokens=um.thoughts_token_count,
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
    # O turno vive como estado NATIVO: system_instruction (string, fora dos contents)
    # + contents (list[types.Content]) — sem round-trip por dicts (thought_signature
    # da família Gemini 3 viaja por construção no Content cru do candidato).
    convo_turns: list[dict] = []
    for msg in history:
        if msg["role"] not in ("user", "assistant"):
            continue
        enriched_content = _render_history_content(msg, resolved_wamids)
        if convo_turns and convo_turns[-1]["role"] == "assistant" == msg["role"]:
            convo_turns[-1]["content"] += "\n\n" + enriched_content
        else:
            convo_turns.append({"role": msg["role"], "content": enriched_content})
    contents = [
        user_content(t["content"]) if t["role"] == "user" else model_content(t["content"])
        for t in convo_turns
    ]

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
        # Lead antigo (pre-C4, commit 119232e) pode ter nome-saudacao gravado no
        # cadastro ("Olá, boa tarde") — sanitiza no call site pra nao vazar pro
        # contexto outbound do 1o turno (mesma defesa ja aplicada em build_base_prompt
        # e no scheduler de follow-up).
        ctx = build_outbound_first_turn_context(
            campaign_message,
            sanitize_display_name(lead.get("name")),
            campaign_segment=campaign_segment,
            template_intent=dispatch_intent,
            lp_message=(lead_context or {}).get("lp_message"),
        )
        contents.append(user_content(ctx))

    # Apply reply marker to the current user message when it was a reply
    if current_quoted_wamid:
        marker = _build_reply_marker(current_quoted_wamid, resolved_wamids)
        enriched_user_text = f"{marker}\n{user_text}"
    else:
        enriched_user_text = user_text
    contents.append(user_content(enriched_user_text))

    result = await _generate_with_retry(
        model=model,
        contents=contents,
        system_instruction=system_prompt,
        tools=tools,
        temperature=0.4,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        stop_sequences=_STOP_SEQUENCES,
        thinking_off=_initial_thinking_off(model),
    )
    _track("response", result)

    tool_iterations = 0
    media_tool_used = False
    # Falha de EXECUÇÃO de mídia (follow-up review E2, 2026-07-03): media_tool_used marca
    # INTENÇÃO — setado antes do try/except que chama execute_tool, independente do
    # resultado. Se execute_tool LEVANTAR exceção para uma tool de mídia, a intenção nunca
    # foi cumprida de fato (o lead não recebeu nada). Sem esta flag, o guard same-turn do
    # Change B (abaixo) usava só media_tool_used e bloqueava a RE-EXECUÇÃO LEGÍTIMA no
    # retry após uma falha real. Usada SÓ pelo guard — o fallback de mídia
    # (_empty_fallback_text/_SAFETY_FALLBACK_MEDIA) continua usando media_tool_used
    # (intenção), como antes: mudar essa semântica do fallback foi explicitamente ADIADA
    # pelo review, não faz parte deste follow-up.
    media_exec_failed = False
    transitioned_to_stage: str | None = None
    # Soft rejection (registrar_sem_interesse_atual): o lead foi descartado (stage=perdido,
    # ai_enabled=False). Se o turno terminar vazio, o silêncio é correto — NÃO o re-engajamento
    # genérico da Change C, que reabriria a conversa com um lead que acabou de ser descartado.
    soft_reject_used = False
    while result.function_calls:
        tool_iterations += 1
        if tool_iterations > MAX_TOOL_ITERATIONS:
            logger.error(
                "[LOOP GUARD] max tool iterations (%d) reached for conv %s — forcing text response",
                MAX_TOOL_ITERATIONS, conversation_id,
            )
            if not result.text:
                try:
                    fallback = await _generate_with_retry(
                        model=model,
                        contents=contents,
                        system_instruction=system_prompt,
                        tools=None,
                        temperature=0.4,
                        max_output_tokens=MAX_OUTPUT_TOKENS,
                        stop_sequences=_STOP_SEQUENCES,
                        thinking_off=_thinking_off_for(model),
                    )
                    # Turno patológico é o mais caro (histórico cheio reenviado N vezes) —
                    # esta era a única chamada do run_agent com usage DESCARTADO. call_type
                    # próprio p/ monitorar a frequência do loop descontrolado (FinOps 08/07).
                    _track("response_loopguard", fallback)
                    result = fallback
                except Exception as _exc:
                    logger.error("[LOOP GUARD] fallback call failed for conv %s: %s", conversation_id, _exc)
            break
        # Round-trip nativo: o Content CRU do candidato entra no histórico do turno
        # (preserva thought_signature — 400 da família 3 impossível por construção).
        if result.content is not None:
            contents.append(result.content)
        for fc in result.function_calls:
            func_name = fc.name
            if func_name in _MEDIA_TOOL_NAMES:
                media_tool_used = True
            func_args = fc.args
            if not isinstance(func_args, dict):
                # Defesa herdada dos args malformados da era OpenAI (arguments era string
                # JSON): o SDK nativo entrega dict, mas um shape inesperado não pode
                # chamar a tool (salvar_nome faz args["name"] → KeyError silencioso).
                logger.error(
                    "Malformed args for tool %s in conv %s: %r",
                    func_name, conversation_id, func_args,
                )
                if func_name in _MEDIA_TOOL_NAMES:
                    media_exec_failed = True
                contents.append(function_response_content(
                    func_name, f"erro: argumentos inválidos para {func_name} — tente novamente",
                ))
                continue
            try:
                tool_result = await execute_tool(
                    func_name, func_args, lead_id, lead.get("phone", ""), conversation_id
                )
            except Exception as exc:
                logger.error(
                    "Tool %s raised exception for conv %s: %s",
                    func_name, conversation_id, exc, exc_info=True,
                )
                tool_result = f"erro ao executar {func_name} — tente novamente"
                # media_exec_failed (follow-up review E2): a intenção (media_tool_used, acima)
                # não virou execução de fato — libera o guard same-turn do Change B pra
                # re-executar esta tool no retry, em vez de bloquear achando que já foi enviada.
                if func_name in _MEDIA_TOOL_NAMES:
                    media_exec_failed = True
            contents.append(function_response_content(func_name, tool_result))

        # encaminhar_humano sends the handoff message directly inside execute_tool.
        # Return None (sentinel) so the processor can distinguish an intentional
        # handoff from an unexpected empty response.
        if any(fc.name == "encaminhar_humano" for fc in result.function_calls):
            return None

        # registrar_optout sets ai_enabled=False silently. The farewell Valéria
        # wrote lives in result.text of this same turn — return it now and skip
        # the second API call (there is nothing left to say after opt-out).
        if any(fc.name == "registrar_optout" for fc in result.function_calls):
            return _sanitize_assistant_text(result.text or "", conversation_id, stage, source="optout") \
                or "sem problema, não te mando mais mensagem por aqui\n\nqualquer coisa é só chamar"

        # registrar_sem_interesse_atual (soft rejection): NÃO retornamos aqui — o modelo costuma
        # gerar um fechamento gracioso na chamada pós-tool. Só marcamos a flag para que, se o turno
        # terminar EMPTY (modelo mudo), o ramo final caia em silêncio em vez do genérico de
        # re-engajamento (que reabriria a conversa de um lead recém-descartado).
        if any(fc.name == "registrar_sem_interesse_atual" for fc in result.function_calls):
            soft_reject_used = True

        # If mudar_stage was called, update in-memory state so the next API call
        # uses the correct stage prompt and tools — prevents infinite transition loop.
        for fc in result.function_calls:
            if fc.name == "mudar_stage":
                if not isinstance(fc.args, dict):
                    break
                new_stage = fc.args.get("stage", stage)
                old_stage = stage
                stage = new_stage
                transitioned_to_stage = new_stage
                tools = build_tools(get_tools_for_stage(stage))
                catalog_text = get_products_by_funnel(stage, prompt_key=prompt_key)
                system_prompt = build_system_prompt(
                    lead, stage, prompt_key=prompt_key, lead_context=lead_context, catalog_text=catalog_text
                )
                if lead_id:
                    current_meta = lead.get("metadata") or {}
                    updated_meta = {**current_meta, "previous_stage": old_stage}
                    update_lead(lead_id, metadata=updated_meta)
                    lead["metadata"] = updated_meta
                    # Gatilho B: consolida o Dossiê do lead após a transição de segmento.
                    _schedule_memory_refresh(lead_id)
                break

        # Chamada PÓS-TOOL: desliga o thinking — é aqui que o modelo gastava o budget
        # pensando e devolvia saída visível zero (Bug 2).
        result = await _generate_with_retry(
            model=model,
            contents=contents,
            system_instruction=system_prompt,
            tools=tools,
            temperature=0.4,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            stop_sequences=_STOP_SEQUENCES,
            thinking_off=_thinking_off_for(model),
        )
        _track("response", result)

    assistant_text = result.text or ""

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
        retry_tools = None if tool_iterations > MAX_TOOL_ITERATIONS else tools
        try:
            retry_result = await _generate_with_retry(
                model=model,
                contents=contents,
                system_instruction=system_prompt,
                tools=retry_tools,
                temperature=0.4,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                stop_sequences=_STOP_SEQUENCES,
                thinking_off=_thinking_off_for(model),
            )
            # Etapa 2: chamadas do 1º degrau de retry (este + a continuação pós-tool do
            # Change B abaixo) passam a "response_retry" — a inicial e as pós-tool do
            # loop principal continuam "response". Permite medir o custo/frequência do
            # retry separadamente (casos Davi/Samuel 01-02/07).
            _track("response_retry", retry_result)
            # Change B (2026-06-30): se o retry recuperou tool_calls (porque tools foram mantidas),
            # executa a intenção em vez de silenciá-la. Cobre o caso exato do lead private_label:
            # a intenção era encaminhar_humano mas o retry sem tools re-vazava como tool_code.
            # Apenas UM nível de recuperação — não re-inicia o ciclo ReAct completo.
            if retry_result.function_calls and retry_tools is not None:
                # Espelha o loop principal: registra o Content do assistente e o resultado de cada
                # tool nos contents, para que a chamada PÓS-TOOL abaixo tenha o contexto e produza
                # a fala natural (fechamento do ciclo ReAct). Sem esses appends, a continuação
                # reprocessaria só o vazio e reincidiria no genérico (caso Karl 2026-07-01).
                if retry_result.content is not None:
                    contents.append(retry_result.content)
                for _fc in retry_result.function_calls:
                    _rname = _fc.name
                    # Guarda de idempotência POR TURNO (Etapa 2 Task 3, caso Samuel 01/07
                    # 08:11-08:12): o Change B roda DEPOIS do loop principal, no MESMO turno —
                    # se uma tool de mídia já executou lá (media_tool_used == True chegando
                    # aqui), o retry recuperou a MESMA intenção após o thinking-burn, e
                    # executá-la de novo manda o catálogo de fotos 2x pro lead. NÃO chama
                    # execute_tool; anexa um tool result sintético e segue o fluxo normalmente.
                    # O dedup por histórico (DB, tools.py::enviar_fotos/enviar_foto_produto,
                    # ver test_enviar_fotos_idempotente.py) continua como 2ª camada, cross-turn
                    # — este guard é a 1ª camada, same-turn, e não depende de read-after-write.
                    #
                    # Ciente de falha (media_exec_failed, follow-up review E2, 2026-07-03):
                    # media_tool_used marca INTENÇÃO, não sucesso — se a execução no loop
                    # principal LEVANTOU exceção, o lead não recebeu nada de fato, e bloquear
                    # a re-execução aqui deixaria a falha sem recuperação nenhuma. Só bloqueia
                    # quando a execução anterior teve sucesso de verdade.
                    if _rname in _MEDIA_TOOL_NAMES and media_tool_used and not media_exec_failed:
                        logger.info(
                            "[RETRY TOOL] %s ja executado neste turno (loop principal) — "
                            "Change B pulando re-execucao para conv %s",
                            _rname, conversation_id,
                        )
                        contents.append(function_response_content(
                            _rname, "fotos já processadas neste turno — não reenviar",
                        ))
                        continue
                    if _rname in _MEDIA_TOOL_NAMES:
                        media_tool_used = True
                    _rargs = _fc.args
                    if not isinstance(_rargs, dict):
                        # Mesmo contrato do loop principal: args com shape inesperado → PULA.
                        # NUNCA chama execute_tool com {} — tools como salvar_nome fazem
                        # args["name"] e estourariam KeyError = corrupção silenciosa.
                        logger.error(
                            "[RETRY TOOL] args inválidos para %s em conv %s — pulando: %r",
                            _rname, conversation_id, _rargs,
                        )
                        if _rname in _MEDIA_TOOL_NAMES:
                            media_exec_failed = True
                        contents.append(function_response_content(
                            _rname, f"erro: argumentos inválidos para {_rname} — tente novamente",
                        ))
                        continue
                    # mudar_stage recuperado: rastreia o novo stage (Minor #4) para que, se o turno
                    # ainda terminar vazio, _empty_fallback_text escolha a pergunta de avanço do
                    # stage em vez do genérico. Mínimo: só guardamos a string, sem rebuild de prompt.
                    if _rname == "mudar_stage":
                        _new_stage = _rargs.get("stage")
                        if _new_stage:
                            transitioned_to_stage = _new_stage
                    try:
                        _rresult = await execute_tool(
                            _rname, _rargs, lead_id, lead.get("phone", ""), conversation_id
                        )
                    except Exception as _te:
                        logger.error(
                            "[RETRY TOOL] %s levantou exceção em conv %s: %s",
                            _rname, conversation_id, _te, exc_info=True,
                        )
                        _rresult = f"erro ao executar {_rname} — tente novamente"
                        # Mesmo contrato do loop principal: marca a falha REAL de execução
                        # (não só a intenção) pra manter o guard same-turn ciente caso uma
                        # tool de mídia recuperada aqui também falhe.
                        if _rname in _MEDIA_TOOL_NAMES:
                            media_exec_failed = True
                    contents.append(function_response_content(_rname, _rresult))
                # Tools terminais recuperadas no retry — mesma ordem e contrato do loop principal,
                # ANTES da chamada pós-tool (senão o lead recebe despedida + continuação juntos).
                _retry_names = {_fc.name for _fc in retry_result.function_calls}
                # encaminhar_humano → sentinel None (handoff; card enviado dentro de execute_tool)
                if "encaminhar_humano" in _retry_names:
                    return None
                # registrar_optout → despedida sanitizada (mesmo default do loop principal)
                if "registrar_optout" in _retry_names:
                    return _sanitize_assistant_text(
                        retry_result.text or "", conversation_id, stage, source="retry-optout"
                    ) or "sem problema, não te mando mais mensagem por aqui\n\nqualquer coisa é só chamar"
                # registrar_sem_interesse_atual → silêncio é correto após soft rejection.
                # A regra "nunca mudo" vale só para turnos normais, não para descarte.
                if "registrar_sem_interesse_atual" in _retry_names:
                    return ""
                # Tools NÃO-terminais recuperadas (ex.: salvar_nome): fecha o ciclo ReAct com UMA
                # chamada PÓS-TOOL de continuação (espelha a linha ~763 do loop principal). Era a
                # peça que faltava: o retry executava a tool mas não gerava a fala, e o turno caía
                # no genérico (thinking-burn + retry incompleto, lead Karl 2026-07-01). Apenas UM
                # nível — não re-inicia o loop; se ainda vier vazio, cai no fallback final (Change C).
                post_result = await _generate_with_retry(
                    model=model,
                    contents=contents,
                    system_instruction=system_prompt,
                    tools=retry_tools,
                    temperature=0.4,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    stop_sequences=_STOP_SEQUENCES,
                    thinking_off=_thinking_off_for(model),
                )
                # Etapa 2: continuação pós-tool do Change B também é parte do 1º degrau
                # de retry — mesmo call_type "response_retry" da chamada retry_result acima.
                _track("response_retry", post_result)
                assistant_text = _sanitize_assistant_text(
                    post_result.text or "",
                    conversation_id, stage, source="retry-post-tool",
                )
            else:
                assistant_text = _sanitize_assistant_text(
                    retry_result.text or "", conversation_id, stage, source="retry"
                )
        except Exception as _exc:
            logger.error(
                "[AGENT EMPTY] retry silencioso falhou para conv %s: %s", conversation_id, _exc,
            )

    # RETRY 2 (Etapa 2 — casos Davi 02/07 15:45 e Samuel 01/07 08:10): o retry silencioso
    # ACIMA também voltou vazio. Antes de desistir para o fallback estático, tentamos UMA
    # última geração text-only com temperatura elevada (_RETRY2_TEMPERATURE) + o nudge de
    # fechamento (_RETRY2_NUDGE) como última message — evita que o lead precise redigitar
    # o que já escreveu (caso Davi: objeção de preço inteira). tools=None de propósito:
    # queremos PALAVRAS, não mais uma tool call; se o modelo verbalizar o handoff mesmo assim,
    # a guarda determinística (_looks_like_handoff_announcement, mais abaixo) cobre o caso.
    # UMA tentativa só — sem loop, sem retry do retry2.
    #
    # Quando soft_reject_used (descarte via registrar_sem_interesse_atual) ou
    # suppress_generic_fallback (gatilho interno sem mensagem real do lead), o destino do
    # turno já é silêncio ("") OU um fallback contextual estático (mídia/transição de stage)
    # que não depende do retry2 (ver _empty_fallback_text/_is_last_resort_fallback abaixo:
    # fallback CONTEXTUAL vence a exceção de silêncio) — por isso NÃO gastamos a chamada
    # aqui (custo/latência sem nenhum efeito no resultado final, em nenhum dos dois casos).
    if not assistant_text and not soft_reject_used and not suppress_generic_fallback:
        logger.warning(
            "[AGENT EMPTY] retry silencioso também vazio (tool_iterations=%d) para conv %s — "
            "retry2 com temperatura elevada + nudge",
            tool_iterations, conversation_id,
        )
        try:
            retry2_result = await _generate_with_retry(
                model=model,
                contents=contents + [user_content(_RETRY2_NUDGE)],
                system_instruction=system_prompt,
                tools=None,
                temperature=_RETRY2_TEMPERATURE,
                max_output_tokens=MAX_OUTPUT_TOKENS,
                stop_sequences=_STOP_SEQUENCES,
                thinking_off=_thinking_off_for(model),
            )
            _track("response_retry2", retry2_result)
            assistant_text = _sanitize_assistant_text(
                retry2_result.text or "",
                conversation_id, stage, source="retry2",
            )
        except Exception as _exc2:
            logger.error(
                "[AGENT EMPTY] retry2 falhou para conv %s: %s", conversation_id, _exc2,
            )

    # Ainda vazio após o retry. Escolhemos o fallback mais contextualmente coerente disponível
    # (transição de stage > mídia > reengajamento do stage ATUAL > genérico honesto — Etapa 2
    # acrescentou o 3º degrau). Change C (2026-06-30): _empty_fallback_text nunca retorna None —
    # o último degrau sempre devolve algum texto em vez de abortar em silêncio. Silêncio total
    # deixa o lead congelado (caso private_label, 21h sem resposta); um recomeço honesto é
    # sempre preferível. O texto NÃO afirma que a mensagem "chegou cortada" e, desde a Etapa 2
    # (caso Davi 02/07: lead redigitou a objeção de preço inteira), NÃO pede pro lead repetir o
    # que já disse — nem o reengajamento por stage nem o genérico.
    #
    # EXCEÇÕES onde o silêncio (return "") é correto e reabrir a conversa seria incoerente
    # (regressões da Change C corrigidas em 2026-06-30, estendidas ao reengajamento por stage na
    # Etapa 2): o fallback CONTEXTUAL (mídia/transição) ainda VENCE; mas se ele NÃO se aplica
    # (i.e. _empty_fallback_text caiu no reengajamento por stage OU no genérico — ambos são
    # "último recurso", ver _is_last_resort_fallback), então:
    #   - soft_reject_used: lead acabou de ser descartado (registrar_sem_interesse_atual) → silêncio.
    #   - suppress_generic_fallback: gatilho interno sem mensagem real do lead (reabertura proativa
    #     ai_scheduled_return) → silêncio (o job é cancelado pelo guard `if not response.strip()`).
    if not assistant_text:
        assistant_text = _empty_fallback_text(media_tool_used, transitioned_to_stage, current_stage=stage)
        if _is_last_resort_fallback(assistant_text, stage) and (soft_reject_used or suppress_generic_fallback):
            logger.error(
                "[AGENT EMPTY] vazio após todos os retries para conv %s — silêncio em vez do último recurso "
                "(soft_reject=%s, suppress=%s, tool_iterations=%d)",
                conversation_id, soft_reject_used, suppress_generic_fallback, tool_iterations,
            )
            return ""
        logger.error(
            "[AGENT EMPTY] vazio após todos os retries para conv %s — fallback "
            "(stage=%s, media=%s, tool_iterations=%d)",
            conversation_id, transitioned_to_stage, media_tool_used, tool_iterations,
        )

    # -----------------------------------------------------------------------
    # GUARDA DE PERGUNTA REPETIDA (auditoria 08/07 — caso Luciano)
    # -----------------------------------------------------------------------
    # O lead recebeu a MESMA pergunta de qualificação 3x depois de já tê-la
    # respondido — o script venceu a escuta e a conversa morreu em sem_interesse.
    # Se o texto final repete uma pergunta de turno anterior do assistente,
    # fazemos UMA regeneração corretiva ancorada na última fala do lead.
    # Fail-open: qualquer falha mantém o texto original (repetir é ruim;
    # fantasmar o lead é pior).
    if assistant_text:
        _prior_assistant = [m.get("content") or "" for m in history if m.get("role") == "assistant"]
        try:
            _repeated = is_repeated_question(assistant_text, _prior_assistant)
        except Exception:
            _repeated = None
        if _repeated:
            logger.warning(
                "[REPEAT QUESTION GUARD] conv %s repetiu pergunta já feita (%.120s) — "
                "regeneração corretiva única",
                conversation_id, _repeated,
            )
            try:
                _nudge = (
                    "ATENÇÃO (mensagem do sistema, invisível ao cliente): sua resposta "
                    "repetiu uma pergunta que você JÁ fez nesta conversa: «" + _repeated + "». "
                    "O lead já a respondeu (ou ela não cabe mais). Reescreva a resposta "
                    "INTEIRA: a primeira bolha reage à última mensagem do lead (ancoragem "
                    "no novo, regra 33), sem repetir essa pergunta, sem copiar frases "
                    "prontas, máximo 3 bolhas, sem ponto final."
                )
                _fix_result = await _generate_with_retry(
                    model=model,
                    contents=contents + [
                        model_content(assistant_text),
                        user_content(_nudge),
                    ],
                    system_instruction=system_prompt,
                    tools=None,
                    temperature=0.5,
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    stop_sequences=_STOP_SEQUENCES,
                    thinking_off=_thinking_off_for(model),
                )
                _track("response_retry", _fix_result)
                _fix_text = _sanitize_assistant_text(
                    _fix_result.text or "",
                    conversation_id, stage, source="repeat-question-fix",
                )
                if _fix_text and not is_repeated_question(_fix_text, _prior_assistant):
                    assistant_text = _fix_text
            except Exception as _rq_exc:
                logger.error(
                    "[REPEAT QUESTION GUARD] regeneração corretiva falhou p/ conv %s: %s",
                    conversation_id, _rq_exc,
                )
        # Telemetria de eco de semente (lei anti-carimbo, auditoria 08/07): cópia
        # literal dos exemplos do prompt identifica o carimbo. Log-only.
        try:
            from app.agent.prompts.valeria_outbound.secretaria import TONE_SEEDS as _SEEDS
            _echo = find_verbatim_prompt_echo(assistant_text, _SEEDS)
            if _echo:
                logger.warning(
                    "[PROMPT ECHO] conv %s copiou semente do prompt literalmente: %.80s",
                    conversation_id, _echo,
                )
        except Exception:
            pass

    # -----------------------------------------------------------------------
    # GUARDA DETERMINÍSTICA DE HANDOFF VERBALIZADO (2026-06-30)
    # -----------------------------------------------------------------------
    # Se o texto final contém um CTA de transferência ("vou te conectar",
    # "vou deixar o contato dele aqui", etc.) mas encaminhar_humano NÃO foi
    # chamado (caso contrário teríamos retornado None sentinel antes), forçamos
    # o handoff agora. Invariante: chegar aqui garante que encaminhar_humano
    # não rodou neste turno — sem risco de double-firing.
    if _looks_like_handoff_announcement(assistant_text):
        logger.warning(
            "[HANDOFF VERBAL GUARD] texto final anuncia transferência sem tool-call "
            "para conv %s — forçando encaminhar_humano. text=%.200s",
            conversation_id, assistant_text,
        )
        try:
            await execute_tool(
                "encaminhar_humano",
                {
                    "mensagem_despedida": assistant_text,
                    "vendedor": "Joao Bras",
                    "motivo": "handoff verbalizado sem tool-call (guarda deterministica)",
                },
                lead_id,
                lead.get("phone", ""),
                conversation_id,
            )
            return None
        except Exception as _guard_exc:
            logger.error(
                "[HANDOFF VERBAL GUARD] execute_tool falhou para conv %s: %s — "
                "retornando texto original (fail-soft)",
                conversation_id, _guard_exc,
            )
            # Fail-soft: não derruba o turno; entrega o texto como estava.

    logger.info(
        f"SDR agent response for conv {conversation_id} (stage={stage}, prompt_key={prompt_key}): {assistant_text[:100]}..."
    )
    return assistant_text
