"""Transcrição de áudio: config de geração + contabilidade (FinOps 08/07/2026).

A transcrição era o único caminho LLM sem NENHUM generationConfig: thinking dinâmico
LIGADO por default (raciocínio pago para uma tarefa mecânica) e usageMetadata descartado
(gasto invisível ao token_usage/budget_guard). Cobre:

  1. Payload REST manda thinkingBudget=0 e maxOutputTokens (thinking off, saída limitada).
  2. usageMetadata da resposta vira linha em token_usage (call_type=media_transcription),
     com lead_id encanado desde process_buffered_messages.
  3. Modelo default de transcrição roteado para gemini-2.5-flash-lite (mecânico e barato;
     revertível por env TRANSCRIPTION_MODEL sem deploy).
"""
import types

import pytest


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Captura o POST do _transcribe_audio e devolve uma transcrição fake com usage."""

    captured: dict = {}
    response_payload: dict = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, params=None, json=None):
        _FakeAsyncClient.captured = {"url": url, "params": params, "json": json}
        return _FakeResp(_FakeAsyncClient.response_payload)


def _gemini_rest_payload(text="transcrição ok", prompt=250, candidates=40, thoughts=0, cached=0):
    return {
        "candidates": [
            {"content": {"parts": [{"text": text}]}, "finishReason": "STOP"},
        ],
        "usageMetadata": {
            "promptTokenCount": prompt,
            "candidatesTokenCount": candidates,
            "thoughtsTokenCount": thoughts,
            "cachedContentTokenCount": cached,
        },
    }


@pytest.mark.asyncio
async def test_payload_desliga_thinking_e_limita_saida(monkeypatch):
    from app.buffer import processor
    _FakeAsyncClient.response_payload = _gemini_rest_payload()
    monkeypatch.setattr(processor.httpx, "AsyncClient", _FakeAsyncClient)

    out = await processor._transcribe_audio(b"OGGDATA", "audio/ogg; codecs=opus")
    assert out == "transcrição ok"

    gen_cfg = _FakeAsyncClient.captured["json"].get("generationConfig")
    assert gen_cfg is not None, "transcrição sem generationConfig — thinking dinâmico ligado"
    assert gen_cfg["thinkingConfig"]["thinkingBudget"] == 0
    assert gen_cfg.get("maxOutputTokens", 0) > 0


@pytest.mark.asyncio
async def test_transcricao_rastreia_token_usage(monkeypatch):
    from app.buffer import processor
    from app.agent import token_tracker

    seen = {}
    monkeypatch.setattr(token_tracker, "track_token_usage", lambda **k: seen.update(k))
    _FakeAsyncClient.response_payload = _gemini_rest_payload(prompt=300, candidates=55, thoughts=7)
    monkeypatch.setattr(processor.httpx, "AsyncClient", _FakeAsyncClient)

    await processor._transcribe_audio(b"OGGDATA", "audio/ogg", lead_id="L1", stage="secretaria")

    assert seen["call_type"] == "media_transcription"
    assert seen["lead_id"] == "L1"
    assert seen["stage"] == "secretaria"
    assert seen["prompt_tokens"] == 300
    # padrão da fachada: thinking é cobrado como output → completion = visível + thoughts
    assert seen["completion_tokens"] == 62
    assert seen["reasoning_tokens"] == 7


@pytest.mark.asyncio
async def test_transcricao_sem_lead_nao_quebra_e_ainda_rastreia(monkeypatch):
    """Fail-soft: sem lead_id (caminho antigo/testes), transcreve normal e loga com lead nulo."""
    from app.buffer import processor
    from app.agent import token_tracker

    seen = {}
    monkeypatch.setattr(token_tracker, "track_token_usage", lambda **k: seen.update(k))
    _FakeAsyncClient.response_payload = _gemini_rest_payload()
    monkeypatch.setattr(processor.httpx, "AsyncClient", _FakeAsyncClient)

    out = await processor._transcribe_audio(b"OGGDATA", "audio/ogg")
    assert out == "transcrição ok"
    assert seen["lead_id"] is None


def test_transcription_model_default_flash_lite():
    """Tarefa mecânica → flash-lite por default (3x mais barato no input, 6x no output).
    Override por env TRANSCRIPTION_MODEL continua valendo (sem deploy p/ reverter)."""
    from app.config import Settings
    field = Settings.model_fields["transcription_model"]
    assert field.default == "gemini-3.1-flash-lite"  # sunset do 2.5 em 09/07
