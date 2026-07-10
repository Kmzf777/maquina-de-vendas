"""Núcleo Gemini nativo (gemini_client.py) — contratos da migração 09/07/2026.

Pina as lições dos incidentes do dia: json_mode REAL (response_mime_type), thinking
off por thinking_budget=0, fallback texto-puro v1 SÓ na assinatura de falso-sunset e
SÓ sem tools/json (prova: v1 rejeita systemInstruction/tools/... com 400), assinatura
fechada (kwarg desconhecido = TypeError) e round-trip de tools SEM perder o
types.Content cru (thought_signature viaja por construção).
"""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import types

import app.agent.gemini_client as GC
from app.agent.gemini_client import (
    GenerateResult, UsageMetadata, build_tools, function_response_content, generate,
    history_to_contents, is_transient_error, parse_result, user_content,
)


def _fake_sdk_resp(text=None, fc_name=None, finish="STOP", thoughts=7):
    parts = []
    if text:
        parts.append(NS(text=text, function_call=None))
    if fc_name:
        parts.append(NS(text=None, function_call=NS(name=fc_name, args={"nome": "Ana"}),
                        thought_signature=b"sig"))
    return NS(
        candidates=[NS(finish_reason=NS(name=finish), content=NS(parts=parts))],
        usage_metadata=NS(prompt_token_count=100, candidates_token_count=40,
                          thoughts_token_count=thoughts, cached_content_token_count=25),
    )


def _capture_client(resp):
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=resp)
    return client


# ---------------------------------------------------------------------------
# parse_result
# ---------------------------------------------------------------------------

def test_parse_result_texto_tools_usage_e_content_cru():
    resp = _fake_sdk_resp(text="olá", fc_name="salvar_nome")
    r = parse_result(resp)
    assert r.text == "olá"
    assert r.function_calls[0].name == "salvar_nome"
    assert r.function_calls[0].args == {"nome": "Ana"}
    assert r.finish_reason == "STOP"
    assert r.usage_metadata.prompt_token_count == 100
    assert r.usage_metadata.billed_output_tokens == 47  # candidates + thoughts
    assert r.usage_metadata.cached_content_token_count == 25
    # o Content cru do candidato é preservado (thought_signature viaja por construção)
    assert r.content is resp.candidates[0].content


def test_parse_result_max_tokens_e_vazio():
    r = parse_result(_fake_sdk_resp(text=None, finish="MAX_TOKENS"))
    assert r.finish_reason == "MAX_TOKENS"
    assert r.text is None and r.function_calls == []


# ---------------------------------------------------------------------------
# generate: config nativa
# ---------------------------------------------------------------------------

def _run_generate(monkeypatch, client, **kw):
    monkeypatch.setattr(GC, "get_genai_client", lambda v=None: client)
    return asyncio.get_event_loop().run_until_complete(
        generate("gemini-2.5-flash", contents=[user_content("oi")], **kw)
    )


@pytest.mark.asyncio
async def test_generate_json_mode_e_thinking_off(monkeypatch):
    client = _capture_client(_fake_sdk_resp(text='{"ok": true}'))
    monkeypatch.setattr(GC, "get_genai_client", lambda v=None: client)
    await generate("m", contents=[user_content("oi")], system_instruction="sys",
                   thinking_off=True, json_mode=True, max_output_tokens=512)
    cfg = client.aio.models.generate_content.await_args.kwargs["config"]
    assert cfg.response_mime_type == "application/json"
    assert cfg.thinking_config.thinking_budget == 0
    assert cfg.system_instruction == "sys"
    assert cfg.max_output_tokens == 512
    assert cfg.automatic_function_calling.disable is True


@pytest.mark.asyncio
async def test_generate_kwarg_desconhecido_e_typeerror():
    with pytest.raises(TypeError):
        await generate("m", contents=[], response_format={"type": "json_object"})


# ---------------------------------------------------------------------------
# fallback v1 (falso-sunset)
# ---------------------------------------------------------------------------

class _Sunset404(Exception):
    def __str__(self):
        return "404 NOT_FOUND. This model is no longer available. Please update"


@pytest.mark.asyncio
async def test_fallback_v1_texto_puro_no_falso_sunset(monkeypatch):
    beta = MagicMock()
    beta.aio.models.generate_content = AsyncMock(side_effect=_Sunset404())
    v1 = _capture_client(_fake_sdk_resp(text="degradado ok"))
    monkeypatch.setattr(GC, "get_genai_client",
                        lambda v=None: v1 if v == "v1" else beta)
    r = await generate("gemini-2.5-flash", contents=[user_content("oi")],
                       system_instruction="persona")
    assert r.text == "degradado ok"
    # v1 não aceita systemInstruction: o system é dobrado no primeiro turno user
    sent = v1.aio.models.generate_content.await_args.kwargs["contents"]
    assert sent[0].parts[0].text == "persona"
    cfg = v1.aio.models.generate_content.await_args.kwargs["config"]
    assert cfg.system_instruction is None and cfg.tools is None


@pytest.mark.asyncio
async def test_fallback_nao_roda_com_tools_nem_erro_generico(monkeypatch):
    beta = MagicMock()
    beta.aio.models.generate_content = AsyncMock(side_effect=_Sunset404())
    monkeypatch.setattr(GC, "get_genai_client", lambda v=None: beta)
    tools = build_tools([{"name": "t", "parameters": {"type": "object", "properties": {}}}])
    with pytest.raises(_Sunset404):
        await generate("m", contents=[user_content("oi")], tools=tools)

    beta.aio.models.generate_content = AsyncMock(side_effect=RuntimeError("500 internal"))
    with pytest.raises(RuntimeError):
        await generate("m", contents=[user_content("oi")])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def test_history_to_contents_roles_e_texto():
    rows = [
        {"role": "user", "content": "oi"},
        {"role": "assistant", "content": "olá"},
        {"role": "system", "content": "[enviar_fotos] ..."},  # ignorado
        {"role": "user", "content": ""},                        # vazio ignorado
    ]
    contents = history_to_contents(rows)
    assert [c.role for c in contents] == ["user", "model"]
    assert contents[1].parts[0].text == "olá"


def test_function_response_content_role_user():
    c = function_response_content("salvar_nome", "Nome salvo.")
    assert c.role == "user"
    fr = c.parts[0].function_response
    assert fr.name == "salvar_nome"
    assert fr.response == {"result": "Nome salvo."}


def test_build_tools_native_shape():
    tools = build_tools([{"name": "x", "description": "d",
                          "parameters": {"type": "object", "properties": {}}}])
    decl = tools[0].function_declarations[0]
    assert decl.name == "x" and decl.description == "d"


def test_is_transient_error():
    assert is_transient_error(RuntimeError("429 RESOURCE_EXHAUSTED"))
    assert is_transient_error(RuntimeError("503 Service Unavailable"))
    assert is_transient_error(RuntimeError("Connection reset by peer"))
    assert not is_transient_error(RuntimeError("400 INVALID_ARGUMENT thought_signature"))
    assert not is_transient_error(_Sunset404())
