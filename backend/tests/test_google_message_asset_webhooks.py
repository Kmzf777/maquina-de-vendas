"""Webhooks Meta e Evolution carimbam o lead do botao de WhatsApp do anuncio Google."""
import inspect
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

TEXTO = "Olá, encontrei vocês pelo Google e gostaria de obter mais informações."


def test_meta_register_lead_carimba_com_o_texto():
    from app.webhook.meta_router import _register_lead
    lead = {"id": "L1", "wa_id": "5511999999999", "wa_id_confirmed_at": "x"}
    with patch("app.webhook.meta_router.get_or_create_lead", return_value=lead), \
         patch("app.webhook.meta_router.update_lead"), \
         patch("app.webhook.meta_router.stamp_google_message_asset") as stamp:
        _register_lead("5511999999999", "Maria", text=TEXTO)
    stamp.assert_called_once_with(lead, TEXTO)


def test_meta_register_lead_sem_texto_continua_funcionando():
    from app.webhook.meta_router import _register_lead
    lead = {"id": "L1", "wa_id": "5511999999999", "wa_id_confirmed_at": "x"}
    with patch("app.webhook.meta_router.get_or_create_lead", return_value=lead), \
         patch("app.webhook.meta_router.update_lead"), \
         patch("app.webhook.meta_router.stamp_google_message_asset") as stamp:
        _register_lead("5511999999999", "Maria")
    stamp.assert_called_once_with(lead, None)


def test_meta_register_lead_carimbo_que_explode_nao_derruba():
    from app.webhook.meta_router import _register_lead
    lead = {"id": "L1", "wa_id": "5511999999999", "wa_id_confirmed_at": "x"}
    with patch("app.webhook.meta_router.get_or_create_lead", return_value=lead), \
         patch("app.webhook.meta_router.update_lead"), \
         patch("app.webhook.meta_router.stamp_google_message_asset", side_effect=RuntimeError("x")):
        _register_lead("5511999999999", "Maria", text=TEXTO)  # não levanta


@pytest.mark.parametrize("sinal_meta", [{"ctwa_clid": "c"}, {"meta_ad_id": "a"}])
def test_meta_register_lead_clique_de_anuncio_meta_vence_o_texto_google(sinal_meta):
    from app.webhook.meta_router import _register_lead
    lead = {"id": "L1", "wa_id": "5511999999999", "wa_id_confirmed_at": "x"}
    with patch("app.webhook.meta_router.get_or_create_lead", return_value=lead),          patch("app.webhook.meta_router.update_lead"),          patch("app.webhook.meta_router.stamp_google_message_asset") as stamp:
        _register_lead("5511999999999", "Maria", text=TEXTO, **sinal_meta)
    stamp.assert_not_called()


def test_evolution_register_lead_carimba_com_o_texto():
    from app.webhook.router import _register_lead
    lead = {"id": "L2"}
    with patch("app.webhook.router.get_or_create_lead", return_value=lead), \
         patch("app.webhook.router.stamp_google_message_asset") as stamp:
        _register_lead("5511988887777", "Joao", TEXTO)
    stamp.assert_called_once_with(lead, TEXTO)


# ── call site: o endpoint Meta repassa o texto da mensagem ao _register_lead ──

FAKE_META_CHANNEL = {
    "id": "ch-meta-test",
    "is_active": True,
    "provider": "meta_cloud",
    "provider_config": {"phone_number_id": "PHONE_ID", "app_secret": ""},
}


def _payload_texto(body: str) -> dict:
    return {
        "entry": [{"changes": [{"value": {
            "messaging_product": "whatsapp",
            "messages": [{
                "from": "553496654020",
                "id": "wamid.google_btn_1",
                "text": {"body": body},
                "type": "text",
            }],
            "metadata": {"phone_number_id": "PHONE_ID"},
        }}]}]
    }


@pytest.fixture
def meta_client(fake_redis):
    from app.webhook.meta_router import router as meta_router
    app = FastAPI()
    app.include_router(meta_router)
    app.state.redis = fake_redis
    return TestClient(app, raise_server_exceptions=True)


def test_meta_webhook_repassa_texto_ao_register_lead(meta_client):
    with (
        patch("app.webhook.meta_router.get_channel_by_provider_config", return_value=FAKE_META_CHANNEL),
        patch("app.webhook.meta_router.get_provider"),
        patch("app.webhook.meta_router.push_to_buffer", new_callable=AsyncMock),
        patch("app.webhook.meta_router.get_dev_route", new_callable=AsyncMock, return_value=None),
        patch("app.webhook.meta_router.log_inbound"),
        patch("app.webhook.meta_router._track_inbound_message_time"),
        patch("app.webhook.meta_router._register_lead") as reg,
    ):
        response = meta_client.post(
            "/webhook/meta",
            content=json.dumps(_payload_texto(TEXTO)),
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 200
    reg.assert_called_once()
    assert reg.call_args.kwargs.get("text") == TEXTO


def test_evolution_call_site_repassa_texto():
    from app.webhook import router as evo_router
    src = inspect.getsource(evo_router)
    assert "add_task(_register_lead, msg.from_number, msg.push_name, msg.text)" in src
