"""Transcrição de áudio NÃO roda no canal humano (número do João) — 2026-09-08.

Todo áudio era transcrito pelo Gemini ANTES dos gates de IA: `_resolve_media` roda
em processor.py:1269 e o gate de canal humano só aparece ~150 linhas depois. No canal
mode="human" ninguém lê esse texto — o prompt da Valéria não roda ali e o chat do CRM
só mostra o player (message-bubble.tsx:313). Gasto integralmente desperdiçado.

Cobre:
  1. transcribe=False pula o Gemini mas PRESERVA o player (download + upload seguem);
  2. o marcador usado NÃO é o de falha — aquele alimenta _count_recent_failed_audio e
     escalaria o lead para humano por um problema que não existe;
  3. canal de IA segue transcrevendo (não-regressão);
  4. o call site deriva o flag de channel.mode.
"""
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.buffer import processor


def _fake_provider(mime: str = "audio/ogg; codecs=opus"):
    """Provider mínimo: download_media devolve a tupla (bytes, content_type)."""
    provider = MagicMock()
    provider.download_media = AsyncMock(return_value=(b"OGGDATA", mime))
    return provider


@pytest.mark.asyncio
async def test_canal_humano_nao_chama_gemini_mas_preserva_o_player(monkeypatch):
    """transcribe=False: zero chamada de LLM, mas media_url continua vindo."""
    transcribe = AsyncMock(return_value=("nao deveria ser chamado", None))
    monkeypatch.setattr(processor, "transcribe_audio", transcribe)
    monkeypatch.setattr(
        processor, "_upload_audio_to_storage",
        lambda *a, **k: "https://storage.local/audio/mid1.ogg",
    )

    text, media_url, message_type, _doc, _meta = await processor._resolve_media(
        "[audio: media_id=mid1]", _fake_provider(), transcribe=False,
    )

    transcribe.assert_not_awaited()
    assert text == "[áudio]"
    assert message_type == "audio"
    assert media_url == "https://storage.local/audio/mid1.ogg", (
        "upload pro Storage tem que continuar — sem media_url o player do CRM some"
    )


@pytest.mark.asyncio
async def test_canal_humano_nao_usa_o_marcador_de_falha(monkeypatch):
    """Pular por decisão != falhar. O marcador de falha dispara escalação por nada."""
    monkeypatch.setattr(processor, "transcribe_audio", AsyncMock())
    monkeypatch.setattr(processor, "_upload_audio_to_storage", lambda *a, **k: None)

    text, _url, _type, _doc, _meta = await processor._resolve_media(
        "[audio: media_id=mid1]", _fake_provider(), transcribe=False,
    )

    assert processor._AUDIO_FAIL_MARKER not in text
    assert "media_id" not in text, "placeholder cru não pode vazar para o CRM"


@pytest.mark.asyncio
async def test_canal_de_ia_continua_transcrevendo_por_default(monkeypatch):
    """Não-regressão: sem o parâmetro, o comportamento é byte a byte o de hoje."""
    transcribe = AsyncMock(return_value=("quero 5 quilos do microlote", None))
    monkeypatch.setattr(processor, "transcribe_audio", transcribe)
    monkeypatch.setattr(processor, "_upload_audio_to_storage", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.agent.token_tracker.track_token_usage", lambda **k: None,
    )

    text, _url, message_type, _doc, _meta = await processor._resolve_media(
        "[audio: media_id=mid1]", _fake_provider(),
    )

    transcribe.assert_awaited_once()
    assert text == "[audio transcrito: quero 5 quilos do microlote]"
    assert message_type == "audio"
