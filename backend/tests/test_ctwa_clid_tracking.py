"""Tests for Click-to-WhatsApp (CTWA) attribution: extracting `referral.ctwa_clid`
from Meta webhook payloads and persisting it on the lead for future CAPI dispatches."""
from unittest.mock import MagicMock, patch

from app.webhook.meta_parser import parse_meta_webhook_payload


def _make_meta_payload(msg_dict: dict, from_number: str = "5511999999999") -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {
                        "display_phone_number": "5500000000000",
                        "phone_number_id": "999",
                    },
                    "contacts": [{"profile": {"name": "Test"}}],
                    "messages": [{
                        "from": from_number,
                        "id": "wamid.ctwa1",
                        "timestamp": "1716900000",
                        **msg_dict,
                    }],
                }
            }]
        }]
    }


# --------------------------------------------------------------------------- #
# Parser — defensive extraction of referral.ctwa_clid
# --------------------------------------------------------------------------- #

def test_parse_text_with_ctwa_referral_extracts_clid():
    """A first message from a CTWA ad carries a referral object with ctwa_clid."""
    payload = _make_meta_payload({
        "type": "text",
        "text": {"body": "vi o anuncio"},
        "referral": {
            "source_type": "ad",
            "source_id": "120210000000000000",
            "source_url": "https://fb.me/abc",
            "headline": "Compre agora",
            "ctwa_clid": "ARAaBbCcDd_clickid_123",
        },
    })
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].ctwa_clid == "ARAaBbCcDd_clickid_123"


def test_parse_organic_message_has_no_ctwa_clid():
    """Organic (non-ad) messages have no referral → ctwa_clid must stay None."""
    payload = _make_meta_payload({"type": "text", "text": {"body": "ola"}})
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].ctwa_clid is None


def test_parse_referral_without_clid_is_defensive():
    """A referral object lacking ctwa_clid (older/partial payloads) must not crash."""
    payload = _make_meta_payload({
        "type": "text",
        "text": {"body": "oi"},
        "referral": {"source_type": "ad", "source_id": "120210000000000000"},
    })
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].ctwa_clid is None


def test_parse_image_with_ctwa_referral_extracts_clid():
    """Referral can ride on any message type (e.g. an image first message)."""
    payload = _make_meta_payload({
        "type": "image",
        "image": {"id": "media123", "mime_type": "image/jpeg"},
        "referral": {"source_type": "ad", "ctwa_clid": "clid_on_image"},
    })
    msgs = parse_meta_webhook_payload(payload)
    assert len(msgs) == 1
    assert msgs[0].type == "image"
    assert msgs[0].ctwa_clid == "clid_on_image"


# --------------------------------------------------------------------------- #
# Router — _register_lead persists ctwa_clid (first-touch on insert, update on change)
# --------------------------------------------------------------------------- #

def test_register_lead_passes_ctwa_clid_to_get_or_create():
    from app.webhook.meta_router import _register_lead
    with patch("app.webhook.meta_router.get_or_create_lead",
               return_value={"id": "L1", "wa_id": "5511999999999", "ctwa_clid": "clid_x"}) as goc, \
         patch("app.webhook.meta_router.update_lead"):
        _register_lead("5511999999999", "Maria", ctwa_clid="clid_x")
    _, kwargs = goc.call_args
    assert kwargs.get("ctwa_clid") == "clid_x"


def test_register_lead_updates_ctwa_clid_when_new_click_arrives():
    """Returning lead clicks a new ad → ctwa_clid should be refreshed (last-touch)."""
    from app.webhook.meta_router import _register_lead
    with patch("app.webhook.meta_router.get_or_create_lead",
               return_value={"id": "L1", "wa_id": "5511999999999", "ctwa_clid": "old_clid"}), \
         patch("app.webhook.meta_router.update_lead") as upd:
        _register_lead("5511999999999", None, ctwa_clid="new_clid")
    upd.assert_called_once_with("L1", ctwa_clid="new_clid")


def test_register_lead_skips_ctwa_update_when_unchanged():
    from app.webhook.meta_router import _register_lead
    with patch("app.webhook.meta_router.get_or_create_lead",
               return_value={"id": "L1", "wa_id": "5511999999999", "ctwa_clid": "same_clid"}), \
         patch("app.webhook.meta_router.update_lead") as upd:
        _register_lead("5511999999999", None, ctwa_clid="same_clid")
    upd.assert_not_called()


def test_register_lead_organic_does_not_overwrite_existing_clid():
    """An organic message (ctwa_clid=None) must NOT wipe a previously captured clid."""
    from app.webhook.meta_router import _register_lead
    with patch("app.webhook.meta_router.get_or_create_lead",
               return_value={"id": "L1", "wa_id": "5511999999999", "ctwa_clid": "kept_clid"}), \
         patch("app.webhook.meta_router.update_lead") as upd:
        _register_lead("5511999999999", None, ctwa_clid=None)
    upd.assert_not_called()


# --------------------------------------------------------------------------- #
# Service — get_or_create_lead persists ctwa_clid on the new-lead insert
# --------------------------------------------------------------------------- #

def test_get_or_create_lead_inserts_ctwa_clid_for_new_lead():
    captured = {}

    def fake_insert(data):
        captured["data"] = data
        mock_result = MagicMock()
        mock_result.data = [{**data, "id": "lead-uuid-1"}]
        return MagicMock(execute=MagicMock(return_value=mock_result))

    # select(...).eq(...).execute() returns empty → forces the insert branch
    mock_select = MagicMock()
    mock_select.eq.return_value.execute.return_value = MagicMock(data=[])

    mock_table = MagicMock()
    mock_table.select.return_value = mock_select
    mock_table.insert.side_effect = fake_insert

    mock_sb = MagicMock()
    mock_sb.table.return_value = mock_table

    with patch("app.leads.service.get_supabase", return_value=mock_sb):
        from app.leads.service import get_or_create_lead
        get_or_create_lead("5511999999999", name="Maria", channel="whatsapp", ctwa_clid="clid_new")

    assert captured["data"].get("ctwa_clid") == "clid_new"


def test_get_or_create_lead_omits_ctwa_clid_when_absent():
    captured = {}

    def fake_insert(data):
        captured["data"] = data
        mock_result = MagicMock()
        mock_result.data = [{**data, "id": "lead-uuid-2"}]
        return MagicMock(execute=MagicMock(return_value=mock_result))

    mock_select = MagicMock()
    mock_select.eq.return_value.execute.return_value = MagicMock(data=[])

    mock_table = MagicMock()
    mock_table.select.return_value = mock_select
    mock_table.insert.side_effect = fake_insert

    mock_sb = MagicMock()
    mock_sb.table.return_value = mock_table

    with patch("app.leads.service.get_supabase", return_value=mock_sb):
        from app.leads.service import get_or_create_lead
        get_or_create_lead("5511999999999", name="Maria", channel="whatsapp")

    assert "ctwa_clid" not in captured["data"]
