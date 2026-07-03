"""Camada de transporte LLM 100% nativa Google/Gemini (SDK `google-genai`).

Substitui integralmente o antigo transporte via SDK da OpenAI (que falava com o
endpoint de compatibilidade do Google). NÃO há mais dependência, import ou tráfego
para aquele SDK: tudo passa por `google.genai.Client(...).aio.models.generate_content(...)`.

## Por que um wrapper com forma `.chat.completions.create`

O `run_agent` (orchestrator.py, ~1000 linhas) é código endurecido por incidentes —
cada ramo do loop ReAct, do retry-on-empty e dos fallbacks codifica uma auditoria de
produção com IDs de lead reais. Reescrever o corpo desse loop para a forma nativa
(`candidates[0].content.parts`, `contents`/`parts`) multiplicaria o risco de regressão.

Por isso este módulo isola 100%% do SDK nativo atrás de uma fina fachada de
compatibilidade (`client.chat.completions.create(...)` → objeto de resposta normalizado
com `.choices[0].message` / `.usage` / `.finish_reason`). A fachada é um objeto NOSSO,
implementado sobre o SDK do Google — não há pacote nem import `openai` em lugar nenhum.
A conversão de formatos (mensagens ↔ `contents`, tools OpenAI-schema ↔ `FunctionDeclaration`,
`reasoning_effort` ↔ `ThinkingConfig`) acontece toda aqui dentro.

O contrato preservado (o que os call sites consomem):
  resp.choices[0].message.content
  resp.choices[0].message.tool_calls[i].id / .function.name / .function.arguments
  resp.choices[0].message.model_dump(exclude_none=True)   # re-injeção no histórico
  resp.choices[0].finish_reason                            # "length" barra corte no follow-up
  resp.usage.prompt_tokens / .completion_tokens
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import google.genai as genai
from google.genai import types

from app.config import settings

logger = logging.getLogger(__name__)

# Role usado no Content que carrega a resposta de uma tool (function_response).
# A API Gemini espera as respostas de função em um turno com role "user".
_FUNCTION_RESPONSE_ROLE = "user"


# ---------------------------------------------------------------------------
# Objetos de resposta normalizados (forma de contrato consumida pelos call sites)
# ---------------------------------------------------------------------------
@dataclass
class _Function:
    name: str
    arguments: str  # JSON serializado (o loop faz json.loads nele — mesmo contrato de antes)


@dataclass
class _ToolCall:
    id: str
    function: _Function
    type: str = "function"


@dataclass
class _Usage:
    prompt_tokens: int
    completion_tokens: int


class _Message:
    """Mensagem do assistente. Expõe .content / .tool_calls e model_dump() para re-injeção."""

    def __init__(self, role: str, content: str | None = None, tool_calls: list[_ToolCall] | None = None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in self.tool_calls
            ]
        if exclude_none:
            d = {k: v for k, v in d.items() if v is not None}
        return d


@dataclass
class _Choice:
    message: _Message
    finish_reason: str = "stop"


@dataclass
class _Response:
    choices: list[_Choice]
    usage: _Usage | None = None


# ---------------------------------------------------------------------------
# Conversões formato-neutro (OpenAI-schema/chat) → nativo Gemini
# ---------------------------------------------------------------------------
def _convert_tools(openai_tools: list[dict] | None) -> list[types.Tool] | None:
    """[{'type':'function','function':{name,description,parameters}}] → [types.Tool(...)]."""
    if not openai_tools:
        return None
    decls: list[types.FunctionDeclaration] = []
    for t in openai_tools:
        fn = t.get("function", t)
        params = fn.get("parameters") or {"type": "object", "properties": {}}
        decls.append(
            types.FunctionDeclaration(
                name=fn["name"],
                description=fn.get("description", ""),
                parameters_json_schema=params,
            )
        )
    return [types.Tool(function_declarations=decls)] if decls else None


def _convert_messages(messages: list[dict]) -> tuple[str | None, list[types.Content]]:
    """Lista neutra de mensagens (system/user/assistant/tool) → (system_instruction, contents).

    - system → concatenado em system_instruction (fora dos contents, como o Gemini espera).
    - assistant com tool_calls → Content(role='model') com Part(function_call=...).
    - tool → Content(role='user') com Part.from_function_response(name=<lookup por id>, ...).
    """
    system_parts: list[str] = []
    contents: list[types.Content] = []

    # Mapa tool_call_id → nome da função (a resposta 'tool' só traz o id; o Gemini exige o nome).
    id_to_name: dict[str, str] = {}
    for m in messages:
        for tc in (m.get("tool_calls") or []):
            fn = (tc.get("function") or {})
            if tc.get("id") and fn.get("name"):
                id_to_name[tc["id"]] = fn["name"]

    for m in messages:
        role = m.get("role")
        if role == "system":
            if m.get("content"):
                system_parts.append(m["content"])
        elif role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=m.get("content") or "")]))
        elif role == "assistant":
            parts: list[types.Part] = []
            if m.get("content"):
                parts.append(types.Part(text=m["content"]))
            for tc in (m.get("tool_calls") or []):
                fn = tc.get("function") or {}
                raw_args = fn.get("arguments") or "{}"
                try:
                    args_dict = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except (json.JSONDecodeError, TypeError):
                    args_dict = {}
                parts.append(types.Part(function_call=types.FunctionCall(name=fn.get("name", ""), args=args_dict)))
            if not parts:
                parts.append(types.Part(text=""))
            contents.append(types.Content(role="model", parts=parts))
        elif role == "tool":
            name = id_to_name.get(m.get("tool_call_id"), m.get("name") or "tool")
            contents.append(
                types.Content(
                    role=_FUNCTION_RESPONSE_ROLE,
                    parts=[types.Part.from_function_response(name=name, response={"result": m.get("content") or ""})],
                )
            )
        # roles desconhecidos são ignorados (mesma tolerância do loop original)

    system_instruction = "\n\n".join(system_parts) if system_parts else None
    return system_instruction, contents


_FINISH_MAP = {"MAX_TOKENS": "length", "STOP": "stop"}


def _map_finish_reason(fr: Any) -> str:
    """FinishReason (enum nativo) → string do contrato. 'length' é vital no follow-up."""
    if fr is None:
        return "stop"
    name = getattr(fr, "name", None) or str(fr)
    return _FINISH_MAP.get(name, name.lower())


def _parse_response(resp: Any) -> _Response:
    text_chunks: list[str] = []
    tool_calls: list[_ToolCall] = []
    finish = "stop"

    candidates = getattr(resp, "candidates", None) or []
    if candidates:
        cand = candidates[0]
        finish = _map_finish_reason(getattr(cand, "finish_reason", None))
        content = getattr(cand, "content", None)
        parts = (getattr(content, "parts", None) or []) if content is not None else []
        for p in parts:
            txt = getattr(p, "text", None)
            if txt:
                text_chunks.append(txt)
            fc = getattr(p, "function_call", None)
            if fc is not None:
                args = dict(getattr(fc, "args", None) or {})
                tool_calls.append(
                    _ToolCall(
                        id=f"call_{len(tool_calls)}",
                        function=_Function(
                            name=getattr(fc, "name", "") or "",
                            arguments=json.dumps(args, ensure_ascii=False),
                        ),
                    )
                )

    usage = None
    um = getattr(resp, "usage_metadata", None)
    if um is not None:
        usage = _Usage(
            prompt_tokens=getattr(um, "prompt_token_count", 0) or 0,
            completion_tokens=getattr(um, "candidates_token_count", 0) or 0,
        )

    # Coerência de finish_reason: se houve tool call e o modelo não cortou por tamanho,
    # o contrato herdado espera "tool_calls" (o loop, porém, decide pelo message.tool_calls).
    if tool_calls and finish == "stop":
        finish = "tool_calls"

    message = _Message(
        role="assistant",
        content=("".join(text_chunks) or None),
        tool_calls=(tool_calls or None),
    )
    return _Response(choices=[_Choice(message=message, finish_reason=finish)], usage=usage)


# ---------------------------------------------------------------------------
# Fachada de cliente: client.chat.completions.create(...) sobre o SDK nativo
# ---------------------------------------------------------------------------
class _Completions:
    def __init__(self, client: "genai.Client"):
        self._client = client

    async def create(
        self,
        *,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.4,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        reasoning_effort: str | None = None,
        **_ignored: Any,
    ) -> _Response:
        system_instruction, contents = _convert_messages(messages)

        # reasoning_effort="none" (contrato herdado do thinking-off) → thinking_budget=0.
        thinking_config = None
        if reasoning_effort == "none":
            thinking_config = types.ThinkingConfig(thinking_budget=0)

        cfg = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=temperature,
            max_output_tokens=max_tokens,
            stop_sequences=stop or None,
            tools=_convert_tools(tools),
            thinking_config=thinking_config,
            # ReAct manual: NÃO deixar o SDK auto-executar as funções — queremos os
            # function_call crus de volta para o loop do orchestrator decidir.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

        resp = await self._client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=cfg,
        )
        return _parse_response(resp)


class _Chat:
    def __init__(self, client: "genai.Client"):
        self.completions = _Completions(client)


class GeminiNativeClient:
    """Cliente Gemini nativo com fachada .chat.completions.create (sem qualquer openai)."""

    def __init__(self, api_key: str):
        self._genai = genai.Client(api_key=api_key)
        self.chat = _Chat(self._genai)


_client: GeminiNativeClient | None = None


def get_client() -> GeminiNativeClient:
    """Singleton do cliente Gemini nativo. Levanta se a GEMINI_API_KEY não estiver setada."""
    global _client
    if _client is None:
        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is not configured — set it in .env to use Gemini models")
        _client = GeminiNativeClient(api_key=settings.gemini_api_key)
    return _client
