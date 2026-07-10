"""Núcleo LLM 100% nativo Google/Gemini (SDK `google-genai`) — SEM forma OpenAI.

Substitui a fachada `gemini_native.py` (que expunha a forma de chat do SDK da OpenAI →
`.choices`/`.usage`). Decisão executiva de 09/07/2026: nada que remeta à OpenAI — nem
forma, nem nomenclatura — permanece na base. Este módulo é a ÚNICA porta de saída
para o Gemini; todo o vocabulário é o do próprio SDK: `contents`/`parts`,
`system_instruction`, `GenerateContentConfig`, `FunctionDeclaration`,
`usage_metadata` (ver spec docs/superpowers/specs/2026-07-09-gemini-100-nativo-design.md).

Lições de incidentes codificadas aqui:
  - thought_signature (família Gemini 3): o `GenerateResult.content` é o
    `types.Content` CRU do candidato — o turno o re-anexa ao histórico sem round-trip
    por dicts, então a assinatura viaja nativamente (o 400 "missing thought_signature"
    do incidente 09/07 fica impossível por construção).
  - json_mode: `response_mime_type="application/json"` de verdade (a fachada engolia
    `response_format` em `**_ignored` — burn de 1.366 gerações do dossiê em 08/07).
  - kwargs desconhecidos = TypeError (assinatura fechada; nunca mais gap silencioso).
  - Versão de API: default v1beta (ÚNICA com paridade: prova de 09/07 — v1 rejeita
    systemInstruction/tools/thinkingConfig/responseMimeType com 400 "Cannot find
    field"). Fallback estruturado p/ v1 SÓ no modo-degradado texto-puro, quando o
    v1beta devolve o 404 de falso-sunset ("no longer available", incidente 09/07
    15:15-17:40) e a chamada não usa tools nem json_mode.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import google.genai as genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_API_VERSION = "v1beta"
# Assinatura do falso-sunset de 09/07 (v1beta negando modelo vivo com mensagem de
# descontinuação): gatilho do fallback texto-puro para v1.
_SUNSET_404_MARKER = "no longer available"

# Sinais de erro transitório (retry vale a pena): quota/limite, 5xx, transporte.
_TRANSIENT_MARKERS = (
    "429", "resource_exhausted", "rate limit",
    "500", "502", "503", "504", "internal", "unavailable", "deadline",
    "timeout", "timed out", "connection", "goaway", "reset",
)


# ---------------------------------------------------------------------------
# Resultado nativo
# ---------------------------------------------------------------------------
@dataclass
class FunctionCall:
    """Chamada de função pedida pelo modelo (args já como dict)."""
    name: str
    args: dict


@dataclass
class UsageMetadata:
    """Espelho enxuto do usage_metadata nativo (nomes do SDK)."""
    prompt_token_count: int = 0
    candidates_token_count: int = 0
    # thoughts são COBRADOS como saída pelo Gemini, mas não entram em
    # candidates_token_count — some via billed_output_tokens.
    thoughts_token_count: int = 0
    cached_content_token_count: int = 0

    @property
    def billed_output_tokens(self) -> int:
        return self.candidates_token_count + self.thoughts_token_count


@dataclass
class GenerateResult:
    """Resultado de uma geração.

    `content` é o types.Content CRU do candidato (role="model") — re-anexe-o ao
    `contents` do turno para o round-trip de tools (preserva thought_signature).
    """
    content: types.Content | None
    text: str | None
    function_calls: list[FunctionCall] = field(default_factory=list)
    finish_reason: str = "STOP"  # nome nativo: STOP | MAX_TOKENS | SAFETY | ...
    usage_metadata: UsageMetadata | None = None


# ---------------------------------------------------------------------------
# Clientes (singleton por versão de API)
# ---------------------------------------------------------------------------
_clients: dict[str, "genai.Client"] = {}


def _key_fingerprint(key: str) -> str:
    """sha256[:8] da chave — identifica QUAL chave está ativa sem vazá-la (prod e dev
    NÃO devem compartilhar GEMINI_API_KEY; a compartilhada drena o teto e derruba prod)."""
    import hashlib
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def default_api_version() -> str:
    return os.environ.get("GEMINI_API_VERSION", _DEFAULT_API_VERSION).strip() or _DEFAULT_API_VERSION


def get_genai_client(api_version: str | None = None) -> "genai.Client":
    """Cliente google-genai por versão de API. Levanta sem GEMINI_API_KEY."""
    version = api_version or default_api_version()
    client = _clients.get(version)
    if client is None:
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not configured — set it in .env to use Gemini models")
        logger.info(
            "[GEMINI] cliente nativo inicializado — api_version=%s key fp=%s dev_env=%s",
            version, _key_fingerprint(settings.gemini_api_key), getattr(settings, "is_dev_env", None),
        )
        client = genai.Client(
            api_key=settings.gemini_api_key,
            http_options=types.HttpOptions(api_version=version),
        )
        _clients[version] = client
    return client


# ---------------------------------------------------------------------------
# Helpers de Content (puros)
# ---------------------------------------------------------------------------
def user_content(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=text or "")])


def model_content(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=text or "")])


def function_response_content(name: str, result_text: str) -> types.Content:
    """Resposta de tool. A API Gemini espera function_response num turno role='user'."""
    return types.Content(
        role="user",
        parts=[types.Part.from_function_response(name=name, response={"result": result_text or ""})],
    )


def history_to_contents(rows: list[dict]) -> list[types.Content]:
    """Linhas de histórico do banco (role/content) → contents nativos.

    Só user/assistant com texto entram (mesma tolerância do transporte anterior:
    system vive em system_instruction; roles desconhecidos são ignorados)."""
    contents: list[types.Content] = []
    for m in rows or []:
        role = m.get("role")
        text = m.get("content")
        if not text:
            continue
        if role == "user":
            contents.append(user_content(text))
        elif role == "assistant":
            contents.append(model_content(text))
    return contents


def build_tools(declarations: list[dict] | None) -> list[types.Tool] | None:
    """Declarações nativas [{'name','description','parameters'}] → [types.Tool]."""
    if not declarations:
        return None
    decls = [
        types.FunctionDeclaration(
            name=d["name"],
            description=d.get("description", ""),
            parameters_json_schema=d.get("parameters") or {"type": "object", "properties": {}},
        )
        for d in declarations
    ]
    return [types.Tool(function_declarations=decls)]


# ---------------------------------------------------------------------------
# Parse do resultado
# ---------------------------------------------------------------------------
def _finish_name(fr) -> str:
    if fr is None:
        return "STOP"
    return getattr(fr, "name", None) or str(fr)


def parse_result(resp) -> GenerateResult:
    """Resposta crua do SDK → GenerateResult. Nunca inventa: campos ausentes viram
    None/0 (o retry-on-empty do orchestrator decide o que fazer com texto vazio)."""
    content = None
    text_chunks: list[str] = []
    function_calls: list[FunctionCall] = []
    finish = "STOP"

    candidates = getattr(resp, "candidates", None) or []
    if candidates:
        cand = candidates[0]
        finish = _finish_name(getattr(cand, "finish_reason", None))
        content = getattr(cand, "content", None)
        for p in (getattr(content, "parts", None) or []) if content is not None else []:
            txt = getattr(p, "text", None)
            if txt:
                text_chunks.append(txt)
            fc = getattr(p, "function_call", None)
            if fc is not None:
                function_calls.append(
                    FunctionCall(name=getattr(fc, "name", "") or "", args=dict(getattr(fc, "args", None) or {}))
                )

    usage = None
    um = getattr(resp, "usage_metadata", None)
    if um is not None:
        usage = UsageMetadata(
            prompt_token_count=getattr(um, "prompt_token_count", 0) or 0,
            candidates_token_count=getattr(um, "candidates_token_count", 0) or 0,
            thoughts_token_count=getattr(um, "thoughts_token_count", 0) or 0,
            cached_content_token_count=getattr(um, "cached_content_token_count", 0) or 0,
        )

    return GenerateResult(
        content=content,
        text=("".join(text_chunks) or None),
        function_calls=function_calls,
        finish_reason=finish,
        usage_metadata=usage,
    )


# ---------------------------------------------------------------------------
# Geração
# ---------------------------------------------------------------------------
def _is_sunset_404(exc: Exception) -> bool:
    s = str(exc).lower()
    return "404" in s and _SUNSET_404_MARKER in s


def is_transient_error(exc: Exception) -> bool:
    """Erro que vale retry (quota/5xx/transporte). 400/404 NÃO são transitórios."""
    s = str(exc).lower()
    if "400" in s or "invalid_argument" in s:
        return False
    return any(m in s for m in _TRANSIENT_MARKERS)


async def generate(
    model: str,
    *,
    contents: list[types.Content],
    system_instruction: str | None = None,
    tools: list[types.Tool] | None = None,
    temperature: float = 0.4,
    max_output_tokens: int | None = None,
    stop_sequences: list[str] | None = None,
    thinking_off: bool = False,
    json_mode: bool = False,
) -> GenerateResult:
    """Única porta de geração. Assinatura FECHADA — parâmetro desconhecido é
    TypeError do Python (nunca mais kwargs engolidos em silêncio)."""
    cfg = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        stop_sequences=stop_sequences or None,
        tools=tools,
        thinking_config=(types.ThinkingConfig(thinking_budget=0) if thinking_off else None),
        response_mime_type=("application/json" if json_mode else None),
        # ReAct manual: os function_call voltam CRUS para o loop do orchestrator.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    try:
        resp = await get_genai_client().aio.models.generate_content(
            model=model, contents=contents, config=cfg,
        )
    except Exception as exc:
        # Falso-sunset no v1beta (09/07): o v1 seguia servindo o modelo. Modo-degradado
        # TEXTO PURO: o v1 rejeita systemInstruction/tools/thinkingConfig/responseMimeType
        # (prova de 09/07), então o fallback só vale sem tools/json — o system é
        # dobrado no primeiro turno de usuário. Com tools, o erro sobe (parking cobre).
        if _is_sunset_404(exc) and not tools and not json_mode and default_api_version() != "v1":
            logger.warning(
                "[GEMINI] 404 falso-sunset no %s p/ %s — fallback texto-puro via v1",
                default_api_version(), model,
            )
            degraded_contents = list(contents)
            if system_instruction:
                degraded_contents = [user_content(system_instruction)] + degraded_contents
            degraded_cfg = types.GenerateContentConfig(
                temperature=temperature,
                max_output_tokens=max_output_tokens,
                stop_sequences=stop_sequences or None,
            )
            resp = await get_genai_client("v1").aio.models.generate_content(
                model=model, contents=degraded_contents, config=degraded_cfg,
            )
        else:
            raise
    return parse_result(resp)


# ---------------------------------------------------------------------------
# Transcrição de áudio (substitui o REST httpx do processor)
# ---------------------------------------------------------------------------
_TRANSCRIBE_PROMPT = (
    "Transcreva o áudio a seguir em português do Brasil. "
    "Responda APENAS com a transcrição literal, sem comentários, aspas ou rótulos."
)
_TRANSCRIBE_MAX_TOKENS = 2048


async def transcribe_audio(
    model: str, audio_bytes: bytes, mime_type: str,
) -> tuple[str, UsageMetadata | None]:
    """Transcreve áudio via generate_content nativo (inline bytes), thinking OFF.

    Retorna (texto, usage) — usage mesmo com texto vazio (tokens foram consumidos;
    a contabilidade fail-soft é do chamador, como antes). Levanta em falha de API."""
    contents = [
        types.Content(
            role="user",
            parts=[
                types.Part(text=_TRANSCRIBE_PROMPT),
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            ],
        )
    ]
    cfg = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_budget=0),
        max_output_tokens=_TRANSCRIBE_MAX_TOKENS,
    )
    resp = await get_genai_client().aio.models.generate_content(
        model=model, contents=contents, config=cfg,
    )
    result = parse_result(resp)
    return (result.text or "").strip(), result.usage_metadata
