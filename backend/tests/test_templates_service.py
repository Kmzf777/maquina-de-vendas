# backend/tests/test_templates_service.py
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# Fixtures de dados reutilizáveis
CHANNEL_META = {
    "id": "chan-1",
    "provider": "meta_cloud",
    "provider_config": {
        "phone_number_id": "111",
        "access_token": "tok-test",
        "waba_id": "waba-123",
    },
}

TEMPLATE_DATA = {
    "name": "order_update_v1",
    "language": "pt_BR",
    "category": "UTILITY",
    "components": [
        {"type": "BODY", "text": "Olá {{1}}, seu pedido foi atualizado."}
    ],
}

DB_RECORD_PENDING = {
    "id": "tpl-1",
    "channel_id": "chan-1",
    "name": "order_update_v1",
    "language": "pt_BR",
    "requested_category": "UTILITY",
    "category": "UTILITY",
    "status": "pending",
    "meta_template_id": "meta-tpl-1",
    "components": TEMPLATE_DATA["components"],
}

DB_RECORD_REVIEW = {
    **DB_RECORD_PENDING,
    "id": "tpl-2",
    "category": "MARKETING",
    "status": "pending_category_review",
    "meta_template_id": "meta-tpl-2",
}


# --- create_template ---

async def test_create_template_no_category_divergence():
    """Meta retorna mesma categoria → status pending, HTTP 201."""
    meta_resp = {"id": "meta-tpl-1", "status": "PENDING", "category": "UTILITY"}

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [DB_RECORD_PENDING]

    with patch("app.templates.service.get_channel", return_value=CHANNEL_META), \
         patch("app.templates.service.get_supabase", return_value=mock_sb), \
         patch("app.templates.service.MetaTemplateClient") as MockClient:

        MockClient.return_value.create_template = AsyncMock(return_value=meta_resp)

        from app.templates.service import create_template
        result, status = await create_template("chan-1", TEMPLATE_DATA)

    assert status == "pending"
    assert result["status"] == "pending"
    assert "suggested_category" not in result


async def test_create_template_category_divergence():
    """Meta muda UTILITY → MARKETING → status pending_category_review, HTTP 202."""
    meta_resp = {"id": "meta-tpl-2", "status": "PENDING", "category": "MARKETING"}

    mock_sb = MagicMock()
    mock_sb.table.return_value.insert.return_value.execute.return_value.data = [DB_RECORD_REVIEW]

    with patch("app.templates.service.get_channel", return_value=CHANNEL_META), \
         patch("app.templates.service.get_supabase", return_value=mock_sb), \
         patch("app.templates.service.MetaTemplateClient") as MockClient:

        MockClient.return_value.create_template = AsyncMock(return_value=meta_resp)

        from app.templates.service import create_template
        result, status = await create_template("chan-1", TEMPLATE_DATA)

    assert status == "pending_category_review"
    assert result["suggested_category"] == "MARKETING"
    assert result["template"]["status"] == "pending_category_review"
