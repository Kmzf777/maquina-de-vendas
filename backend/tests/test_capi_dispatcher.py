"""Tests for the CAPI dispatcher: SHA-256 hashing, payload building, and env-gated send."""
import hashlib
from unittest.mock import patch

import threading

from app.campaigns.capi_dispatcher import (
    hash_email,
    hash_phone,
    build_fbc,
    build_meta_capi_event,
    build_meta_capi_payload,
    build_google_offline_conversion,
    dispatch_purchase_conversion,
    dispatch_purchase_conversion_background,
    meta_event_name,
    dispatch_conversion,
)


# --------------------------------------------------------------------------- #
# Hashing — SHA-256 over normalized values
# --------------------------------------------------------------------------- #

def test_hash_email_normalizes_then_sha256():
    assert hash_email("  John.Doe@Example.COM ") == hashlib.sha256(
        "john.doe@example.com".encode()
    ).hexdigest()


def test_hash_phone_strips_to_digits_then_sha256():
    assert hash_phone("+55 (34) 99665-2412") == hashlib.sha256("5534996652412".encode()).hexdigest()


def test_hash_helpers_return_none_for_empty():
    assert hash_email(None) is None
    assert hash_email("") is None
    assert hash_phone(None) is None
    assert hash_phone("") is None


def test_build_fbc_format():
    assert build_fbc("AbC123", event_time=1700000000) == "fb.1.1700000000000.AbC123"
    assert build_fbc(None) is None


# --------------------------------------------------------------------------- #
# Meta CAPI payload building
# --------------------------------------------------------------------------- #

def test_meta_event_uses_ctwa_clid_as_business_messaging():
    lead = {"id": "L1", "email": "a@b.com", "phone": "5534996652412", "ctwa_clid": "clid_123"}
    event = build_meta_capi_event(lead, value=199.9, currency="BRL", event_time=1700000000)
    assert event["action_source"] == "business_messaging"
    assert event["messaging_channel"] == "whatsapp"
    assert event["user_data"]["ctwa_clid"] == "clid_123"
    assert event["user_data"]["em"] == [hashlib.sha256("a@b.com".encode()).hexdigest()]
    assert event["user_data"]["ph"] == [hashlib.sha256("5534996652412".encode()).hexdigest()]
    assert event["custom_data"] == {"value": 199.9, "currency": "BRL"}


def test_meta_event_falls_back_to_fbclid_as_website():
    lead = {"id": "L2", "phone": "5511999999999", "fbclid": "fbc_xyz"}
    event = build_meta_capi_event(lead, event_time=1700000000)
    assert event["action_source"] == "website"
    assert "messaging_channel" not in event
    assert event["user_data"]["fbc"] == "fb.1.1700000000000.fbc_xyz"
    assert "ctwa_clid" not in event["user_data"]


def test_meta_event_prefers_wa_id_over_phone_for_hash():
    lead = {"id": "L3", "wa_id": "553432262600", "phone": "5534932262600", "ctwa_clid": "c"}
    event = build_meta_capi_event(lead)
    assert event["user_data"]["ph"] == [hashlib.sha256("553432262600".encode()).hexdigest()]


def test_meta_payload_includes_test_event_code_from_env():
    lead = {"id": "L4", "ctwa_clid": "c"}
    with patch.dict("os.environ", {"META_CAPI_TEST_EVENT_CODE": "TEST123"}):
        payload = build_meta_capi_payload(lead)
    assert payload["test_event_code"] == "TEST123"
    assert isinstance(payload["data"], list) and len(payload["data"]) == 1


# --------------------------------------------------------------------------- #
# Google offline conversion
# --------------------------------------------------------------------------- #

def test_google_conversion_requires_gclid():
    assert build_google_offline_conversion({"id": "L5"}) is None


def test_google_conversion_built_from_gclid():
    conv = build_google_offline_conversion({"id": "L6", "gclid": "g_123"}, value=50.0, currency="BRL")
    assert conv["gclid"] == "g_123"
    assert conv["conversion_value"] == 50.0
    assert conv["currency_code"] == "BRL"


# --------------------------------------------------------------------------- #
# Dispatch — env-gated, fail-soft, never sends without credentials
# --------------------------------------------------------------------------- #

def test_dispatch_is_noop_without_credentials():
    lead = {"id": "L7", "ctwa_clid": "clid", "gclid": "g", "email": "a@b.com"}
    # No META_CAPI_* / GOOGLE_ADS_* env → must not perform any HTTP call.
    with patch.dict("os.environ", {}, clear=True), \
         patch("app.campaigns.capi_dispatcher.httpx.Client") as client:
        result = dispatch_purchase_conversion(lead, value=10.0)
    client.assert_not_called()
    assert result["meta"]["sent"] is False
    assert result["meta"]["reason"] == "no_credentials"
    assert result["google"]["sent"] is False


def test_dispatch_sends_to_meta_when_credentials_present():
    lead = {"id": "L8", "ctwa_clid": "clid", "email": "a@b.com", "phone": "5534996652412"}
    env = {"META_CAPI_PIXEL_ID": "PIX1", "META_CAPI_ACCESS_TOKEN": "TOK1"}
    with patch.dict("os.environ", env, clear=True), \
         patch("app.campaigns.capi_dispatcher.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value.status_code = 200
        client.post.return_value.raise_for_status.return_value = None
        result = dispatch_purchase_conversion(lead, value=99.0)
    assert result["meta"]["sent"] is True
    # URL deve conter o pixel id e o endpoint /events
    args, kwargs = client.post.call_args
    assert "PIX1/events" in args[0]
    assert kwargs["params"]["access_token"] == "TOK1"


def test_dispatch_skips_meta_when_no_click_id():
    lead = {"id": "L9", "email": "a@b.com"}  # sem ctwa_clid nem fbclid
    env = {"META_CAPI_PIXEL_ID": "PIX1", "META_CAPI_ACCESS_TOKEN": "TOK1"}
    with patch.dict("os.environ", env, clear=True), \
         patch("app.campaigns.capi_dispatcher.httpx.Client") as client_cls:
        result = dispatch_purchase_conversion(lead, value=10.0)
    client_cls.assert_not_called()
    assert result["meta"]["reason"] == "no_click_id"


def test_background_dispatch_runs_in_thread_without_blocking():
    done = threading.Event()
    captured = {}

    def fake(lead, value, currency):
        captured["args"] = (lead, value, currency)
        done.set()

    with patch("app.campaigns.capi_dispatcher.dispatch_purchase_conversion", side_effect=fake):
        dispatch_purchase_conversion_background({"id": "L1"}, value=5.0, currency="USD")
        assert done.wait(timeout=2.0), "dispatch em background não executou"

    assert captured["args"] == ({"id": "L1"}, 5.0, "USD")


# --------------------------------------------------------------------------- #
# meta_event_name — canonical mapping + env override
# --------------------------------------------------------------------------- #

def test_meta_event_name_defaults():
    assert meta_event_name("purchase") == "Purchase"
    assert meta_event_name("qualified") == "Lead"
    assert meta_event_name("opportunity") == "Oportunidade_Criada"
    assert meta_event_name("lead") == "Lead"


def test_meta_event_name_env_override():
    with patch.dict("os.environ", {"META_EVENT_NAME_OPPORTUNITY": "MQL"}, clear=True):
        assert meta_event_name("opportunity") == "MQL"


def test_dispatch_conversion_sends_event_name_to_meta():
    lead = {"id": "L1", "ctwa_clid": "clid", "phone": "5534996652412"}
    env = {"META_CAPI_PIXEL_ID": "PIX1", "META_CAPI_ACCESS_TOKEN": "TOK1"}
    with patch.dict("os.environ", env, clear=True), \
         patch("app.campaigns.capi_dispatcher.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value.status_code = 200
        client.post.return_value.raise_for_status.return_value = None
        result = dispatch_conversion(lead, "opportunity", value=150.0)
    assert result["meta"]["sent"] is True
    _, kwargs = client.post.call_args
    assert kwargs["json"]["data"][0]["event_name"] == "Oportunidade_Criada"


def test_dispatch_purchase_conversion_still_uses_purchase_event():
    lead = {"id": "L2", "ctwa_clid": "clid", "phone": "5534996652412"}
    env = {"META_CAPI_PIXEL_ID": "PIX1", "META_CAPI_ACCESS_TOKEN": "TOK1"}
    with patch.dict("os.environ", env, clear=True), \
         patch("app.campaigns.capi_dispatcher.httpx.Client") as client_cls:
        client = client_cls.return_value.__enter__.return_value
        client.post.return_value.status_code = 200
        client.post.return_value.raise_for_status.return_value = None
        dispatch_purchase_conversion(lead, value=99.0)
        _, kwargs = client.post.call_args
    assert kwargs["json"]["data"][0]["event_name"] == "Purchase"
