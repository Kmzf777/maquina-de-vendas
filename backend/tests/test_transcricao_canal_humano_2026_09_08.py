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


def _patch_pipeline(stack: ExitStack, *, channel: dict) -> AsyncMock:
    """Mocka process_buffered_messages até logo depois do _resolve_media.

    VALERIA_ENABLED=False faz a função retornar no gate seguinte ao de canal humano,
    então tanto o canal 'human' quanto o 'ai' param cedo — o que basta: o objeto sob
    teste é o kwarg `transcribe` com que _resolve_media foi chamado.
    """
    lead = {"id": "L1", "phone": "5534988861441", "wa_id": "5534988861441",
            "ai_enabled": True, "stage": "atacado", "metadata": {}}
    conv = {"id": "conv1", "status": "active", "stage": "atacado", "followup_enabled": False}

    p = lambda name, *args, **kw: stack.enter_context(patch.object(processor, name, *args, **kw))

    p("get_or_create_lead", return_value=lead)
    p("get_channel_by_id", return_value=channel)
    p("get_or_create_conversation", return_value=conv)
    p("get_provider", return_value=MagicMock())
    p("update_conversation", MagicMock())
    p("get_supabase", MagicMock())
    p("run_with_retry", MagicMock(return_value=MagicMock(data={"unread_count": 0})))
    p("_wamid_already_processed", return_value=False)
    p("_is_recent_duplicate", return_value=False)
    p("save_message", MagicMock(return_value={"created_at": "2026-09-08T12:00:00Z"}))
    p("_update_last_msg", MagicMock())
    p("VALERIA_ENABLED", False)

    resolve = p("_resolve_media", new=AsyncMock(return_value=("[audio]", "u", "audio", None, None)))

    # Efeitos colaterais best-effort (lazy imports) — neutralizados p/ não tocar rede.
    stack.enter_context(patch("app.broadcast.service.record_broadcast_reply", MagicMock()))
    stack.enter_context(patch("app.campaigns.worker.handle_campaign_reply", MagicMock()))
    stack.enter_context(patch("app.automation.triggers.fire_trigger", new=AsyncMock()))
    # get_open_deal é lazy import e fail-soft (loga ERROR e segue), mas sem mock ele
    # tenta resolver DNS — deixaria o teste lento e dependente de rede no CI.
    stack.enter_context(patch("app.leads.service.get_open_deal", MagicMock(return_value=None)))

    return resolve


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "channel, esperado",
    [
        ({"id": "ch1", "mode": "human", "provider_config": {}}, False),
        ({"id": "ch1", "mode": "ai", "provider_config": {}}, True),
        ({"id": "ch1", "provider_config": {}}, True),
    ],
    ids=["canal-humano-nao-transcreve", "canal-ia-transcreve", "sem-mode-default-ai"],
)
async def test_flag_de_transcricao_vem_do_mode_do_canal(channel, esperado):
    with ExitStack() as stack:
        resolve = _patch_pipeline(stack, channel=channel)
        await processor.process_buffered_messages(
            "5534988861441", "[audio: media_id=mid1]", "ch1", wamid="wamid-1",
        )

    assert resolve.await_args.kwargs["transcribe"] is esperado
