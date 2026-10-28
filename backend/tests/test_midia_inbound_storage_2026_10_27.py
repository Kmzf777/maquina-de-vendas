"""Cartão da1f51a7: mídia não-áudio do cliente ganha cópia em whatsapp-media/inbound/."""
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.buffer import processor as p


def _provider(data=b"\x89PNGfake", ctype="image/jpeg", exc=None):
    prov = MagicMock()
    if exc:
        prov.download_media = AsyncMock(side_effect=exc)
    else:
        prov.download_media = AsyncMock(return_value=(data, ctype))
    return prov


def _sb(public="https://supabase.x/storage/v1/object/public/whatsapp-media/inbound/123.jpg"):
    sb = MagicMock()
    bucket = sb.storage.from_.return_value
    bucket.get_public_url.return_value = public
    return sb, bucket


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,placeholder,ctype,ext", [
    ("image", "[image: media_url=123]", "image/jpeg", "jpg"),
    ("video", "[video: media_url=123]", "video/mp4", "mp4"),
    ("document", "[document: media_url=123]", "application/pdf", "pdf"),
    ("sticker", "[sticker: media_url=123]", "image/webp", "webp"),
])
async def test_copia_para_inbound(kind, placeholder, ctype, ext):
    sb, bucket = _sb()
    with patch("app.db.supabase.get_supabase", return_value=sb), \
         patch("app.buffer.processor.asyncio.sleep", new=AsyncMock()):
        text, url, mtype, _, _ = await p._resolve_media(placeholder, _provider(ctype=ctype))
    assert mtype == kind
    assert url.startswith("https://")
    sb.storage.from_.assert_any_call("whatsapp-media")
    path = bucket.upload.call_args.args[0]
    assert path == f"inbound/123.{ext}"
    # O texto resolvido não muda: o marcador continua sendo removido.
    assert text == ""


@pytest.mark.asyncio
async def test_documento_mantem_nome_e_texto():
    sb, bucket = _sb()
    fname = base64.b64encode("Contrato.pdf".encode()).decode()
    with patch("app.db.supabase.get_supabase", return_value=sb):
        text, url, mtype, doc_name, _ = await p._resolve_media(
            f"segue\n[document: media_url=42 filename_b64={fname}]",
            _provider(ctype="application/pdf"),
        )
    assert mtype == "document" and doc_name == "Contrato.pdf"
    assert url.startswith("https://")
    assert bucket.upload.call_args.args[0] == "inbound/42.pdf"
    assert text.strip() == "segue"


@pytest.mark.asyncio
async def test_falha_no_download_mantem_media_id():
    with patch("app.buffer.processor.asyncio.sleep", new=AsyncMock()):
        _, url, mtype, _, _ = await p._resolve_media(
            "[image: media_url=999]", _provider(exc=RuntimeError("400"))
        )
    assert mtype == "image" and url == "999"


@pytest.mark.asyncio
async def test_falha_no_upload_mantem_media_id():
    sb, bucket = _sb()
    bucket.upload.side_effect = RuntimeError("storage down")
    with patch("app.db.supabase.get_supabase", return_value=sb):
        _, url, _, _, _ = await p._resolve_media("[image: media_url=777]", _provider())
    assert url == "777"


@pytest.mark.asyncio
async def test_acima_do_teto_nao_copia():
    sb, bucket = _sb()
    grande = b"x" * (p._INBOUND_MAX_MEDIA + 1)
    with patch("app.db.supabase.get_supabase", return_value=sb):
        _, url, _, _, _ = await p._resolve_media("[image: media_url=555]", _provider(data=grande))
    assert url == "555"
    bucket.upload.assert_not_called()


@pytest.mark.asyncio
async def test_url_http_nao_baixa_de_novo():
    prov = _provider()
    _, url, _, _, _ = await p._resolve_media("[image: media_url=https://x/y.jpg]", prov)
    assert url == "https://x/y.jpg"
    prov.download_media.assert_not_called()


@pytest.mark.asyncio
async def test_sem_provider_mantem_media_id():
    _, url, mtype, _, _ = await p._resolve_media("[image: media_url=321]", None)
    assert mtype == "image" and url == "321"
