"""Fotos da IA persistidas como mensagens reais (item 1 do plano 11/07).

Antes: _dispatch_deferred_media descartava o retorno da Meta — nenhuma linha por
imagem em `messages` (só o marcador system k/n). Reply do lead à foto ficava
irresolvível (frontend "Mensagem original não disponível"; prompt com marcador
genérico) e o operador nem via a foto no CRM.

Agora: cada imagem enviada grava linha role=assistant, message_type=image,
content=caption, wamid capturado e media_url (cópia no Storage, fail-soft).
O marcador k/n continua nascendo pós-envio (dedup da tool depende dele).
"""
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.buffer import processor as P


_B64 = base64.b64encode(b"fake-image-bytes").decode()


def _conv():
    return {"id": "conv-df-1", "stage": "atacado"}


def _lead():
    return {"id": "lead-df-1", "phone": "+5511999990001"}


def _provider(wamids=("wamid.IMG1", "wamid.IMG2")):
    provider = AsyncMock()
    results = [{"messages": [{"id": w}]} for w in wamids]
    provider.send_image_base64 = AsyncMock(side_effect=results)
    return provider


def _queue_items():
    return [
        {"b64": _B64, "mimetype": "image/jpeg",
         "caption": "Classico — torra media-escura",
         "marker": "[enviar_fotos] Fotos de atacado enviadas", "catalog": True},
        {"b64": _B64, "mimetype": "image/png", "caption": "",
         "marker": "[enviar_fotos] Fotos de atacado enviadas", "catalog": True},
    ]


@pytest.mark.asyncio
async def test_dispatch_persiste_linha_por_imagem_com_wamid():
    provider = _provider()

    with patch.object(P, "pop_deferred_media", return_value=_queue_items()), \
         patch.object(P, "record_deferred_media_delivery") as mock_marker, \
         patch.object(P, "_upload_image_to_storage", return_value="https://storage/x.jpg"), \
         patch.object(P, "save_message") as mock_save, \
         patch("asyncio.sleep", new=AsyncMock()):
        await P._dispatch_deferred_media(provider, "+5511999990001", _conv(), _lead())

    assert mock_save.call_count == 2
    first = mock_save.call_args_list[0]
    assert first.args[:4] == ("conv-df-1", "lead-df-1", "assistant", "Classico — torra media-escura")
    assert first.kwargs["message_type"] == "image"
    assert first.kwargs["wamid"] == "wamid.IMG1"
    assert first.kwargs["media_url"] == "https://storage/x.jpg"
    assert first.kwargs["media_mime"] == "image/jpeg"
    assert first.kwargs["sent_by"] == "agent"

    second = mock_save.call_args_list[1]
    assert second.kwargs["wamid"] == "wamid.IMG2"
    # Sem legenda: content vazio — o placeholder "[imagem]" nasce na leitura
    # (describe_media_placeholder), não na escrita.
    assert second.args[3] == ""

    # Marcador k/n intacto (dedup da tool): grupo com sent=2/total=2.
    mock_marker.assert_called_once()
    groups = mock_marker.call_args.args[2]
    assert groups[0]["sent"] == 2 and groups[0]["total"] == 2


@pytest.mark.asyncio
async def test_dispatch_falha_de_envio_nao_persiste_linha():
    """Envio da 2ª imagem falha → só a 1ª vira linha; contagem k/n honesta (1/2)."""
    provider = AsyncMock()
    provider.send_image_base64 = AsyncMock(
        side_effect=[{"messages": [{"id": "wamid.OK"}]}, RuntimeError("boom")],
    )

    with patch.object(P, "pop_deferred_media", return_value=_queue_items()), \
         patch.object(P, "record_deferred_media_delivery") as mock_marker, \
         patch.object(P, "_upload_image_to_storage", return_value=None), \
         patch.object(P, "save_message") as mock_save, \
         patch("asyncio.sleep", new=AsyncMock()):
        await P._dispatch_deferred_media(provider, "+5511999990001", _conv(), _lead())

    assert mock_save.call_count == 1
    assert mock_save.call_args.kwargs["wamid"] == "wamid.OK"
    groups = mock_marker.call_args.args[2]
    assert groups[0]["sent"] == 1 and groups[0]["total"] == 2


@pytest.mark.asyncio
async def test_dispatch_storage_indisponivel_persiste_sem_media_url():
    """Storage fora → linha ainda nasce (wamid é o que torna o reply resolvível);
    media_url=None é aceitável (bolha degrada p/ ícone)."""
    provider = _provider(("wamid.IMG9",))

    with patch.object(P, "pop_deferred_media", return_value=_queue_items()[:1]), \
         patch.object(P, "record_deferred_media_delivery"), \
         patch.object(P, "_upload_image_to_storage", return_value=None), \
         patch.object(P, "save_message") as mock_save, \
         patch("asyncio.sleep", new=AsyncMock()):
        await P._dispatch_deferred_media(provider, "+5511999990001", _conv(), _lead())

    assert mock_save.call_count == 1
    assert mock_save.call_args.kwargs["media_url"] is None
    assert mock_save.call_args.kwargs["wamid"] == "wamid.IMG9"


@pytest.mark.asyncio
async def test_dispatch_save_falha_nao_derruba_o_envio():
    """save_message levantando não pode escalar (a mídia JÁ foi entregue ao lead) —
    o marcador k/n ainda é registrado."""
    provider = _provider(("wamid.IMG1",))

    with patch.object(P, "pop_deferred_media", return_value=_queue_items()[:1]), \
         patch.object(P, "record_deferred_media_delivery") as mock_marker, \
         patch.object(P, "_upload_image_to_storage", return_value=None), \
         patch.object(P, "save_message", side_effect=RuntimeError("db fora")), \
         patch("asyncio.sleep", new=AsyncMock()):
        await P._dispatch_deferred_media(provider, "+5511999990001", _conv(), _lead())

    groups = mock_marker.call_args.args[2]
    assert groups[0]["sent"] == 1
