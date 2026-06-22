"""Testes das correções estruturais (Falhas 2, 6, 9, 10) da auditoria 2026-06-22."""
import pytest
from datetime import datetime
from unittest.mock import patch


# --- Falha 10: sanitização de nome (handle vs nome real) -----------------

def test_sanitize_display_name_descarta_handles():
    from app.leads.service import sanitize_display_name
    assert sanitize_display_name("Brunor_barista") is None      # underscore
    assert sanitize_display_name("cassianofonseca15") is None    # dígito
    assert sanitize_display_name("") is None
    assert sanitize_display_name(None) is None


def test_sanitize_display_name_mantem_nomes_reais():
    from app.leads.service import sanitize_display_name
    assert sanitize_display_name("João Silva") == "João Silva"
    assert sanitize_display_name(" Maria ") == "Maria"
    assert sanitize_display_name("Ricardo") == "Ricardo"


def test_broadcast_name_token_fallback_para_voce():
    from app.broadcast.worker import _lead_first_name, _lead_full_name
    assert _lead_first_name({"name": "Brunor_barista"}) == "você"
    assert _lead_first_name({"name": "João Silva"}) == "João"
    assert _lead_full_name({"name": "cassianofonseca15"}) == "você"
    assert _lead_full_name({"name": "Maria Eduarda"}) == "Maria Eduarda"


# --- Falha 6: sinal lead_is_customer no prompt ---------------------------

def test_base_prompt_surface_lead_is_customer():
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt(
        "Grazieli", None, datetime(2026, 6, 22, 14, 0),
        lead_context={"lead_is_customer": True},
    )
    assert "LEAD JA E CLIENTE" in s


def test_base_prompt_sem_sinal_nao_adiciona():
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt("Grazieli", None, datetime(2026, 6, 22, 14, 0))
    assert "LEAD JA E CLIENTE / EM TRATATIVA" not in s


# --- Falha 2: transcrição via generateContent ---------------------------

def test_audio_mime_type_strips_codecs():
    from app.buffer.processor import _audio_mime_type
    assert _audio_mime_type("audio/ogg; codecs=opus") == "audio/ogg"
    assert _audio_mime_type("audio/mpeg") == "audio/mpeg"
    assert _audio_mime_type(None) == "audio/ogg"


class _FakeResp:
    def __init__(self, data):
        self._data = data
    def raise_for_status(self):
        return None
    def json(self):
        return self._data


class _FakeClient:
    def __init__(self, data):
        self._data = data
    async def __aenter__(self):
        return self
    async def __aexit__(self, *a):
        return False
    async def post(self, *a, **k):
        return _FakeResp(self._data)


@pytest.mark.asyncio
async def test_transcribe_audio_parses_generate_content():
    from app.buffer import processor
    data = {"candidates": [{"content": {"parts": [{"text": "olá tudo bem"}]}}]}
    with patch("app.buffer.processor.httpx.AsyncClient", return_value=_FakeClient(data)):
        out = await processor._transcribe_audio(b"\x00\x01", "audio/ogg; codecs=opus")
    assert out == "olá tudo bem"


@pytest.mark.asyncio
async def test_transcribe_audio_levanta_em_resposta_vazia():
    from app.buffer import processor
    data = {"candidates": [{"content": {"parts": []}, "finishReason": "SAFETY"}]}
    with patch("app.buffer.processor.httpx.AsyncClient", return_value=_FakeClient(data)):
        with pytest.raises(Exception):
            await processor._transcribe_audio(b"\x00\x01", "audio/ogg")


# --- Falha 9: canned texts seguem regra 22 (sem ponto final/sentença) ----

def test_canned_fallbacks_sem_ponto_final():
    from app.agent.orchestrator import _SAFETY_FALLBACK_MEDIA, _STAGE_TRANSITION_FALLBACKS
    assert not _SAFETY_FALLBACK_MEDIA.rstrip().endswith(".")
    assert ". " not in _SAFETY_FALLBACK_MEDIA
    for stage, txt in _STAGE_TRANSITION_FALLBACKS.items():
        assert ". " not in txt, f"ponto de sentença em {stage}: {txt!r}"
        assert not txt.rstrip().endswith("."), stage
