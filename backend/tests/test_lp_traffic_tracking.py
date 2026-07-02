"""Tests for landing-page traffic attribution: fbclid/gclid/utm_* persistence on leads."""
from unittest.mock import MagicMock, patch

from app.leads.service import persist_lead_tracking


# --------------------------------------------------------------------------- #
# get_or_create_lead — persists tracking bag on the new-lead insert
# --------------------------------------------------------------------------- #

def test_get_or_create_lead_inserts_tracking_bag():
    captured = {}

    def fake_insert(data):
        captured["data"] = data
        result = MagicMock()
        result.data = [{**data, "id": "lead-1"}]
        return MagicMock(execute=MagicMock(return_value=result))

    mock_select = MagicMock()
    mock_select.eq.return_value.execute.return_value = MagicMock(data=[])
    mock_table = MagicMock()
    mock_table.select.return_value = mock_select
    mock_table.insert.side_effect = fake_insert
    mock_sb = MagicMock()
    mock_sb.table.return_value = mock_table

    with patch("app.leads.service.get_supabase", return_value=mock_sb):
        from app.leads.service import get_or_create_lead
        get_or_create_lead(
            "5511999999999",
            name="Maria",
            tracking={
                "fbclid": "fb_1", "gclid": "g_1",
                "utm_source": "facebook", "utm_medium": "cpc", "utm_campaign": "natal",
                "ignored_key": "should not be stored",
            },
        )

    data = captured["data"]
    assert data["fbclid"] == "fb_1"
    assert data["gclid"] == "g_1"
    assert data["utm_source"] == "facebook"
    assert data["utm_medium"] == "cpc"
    assert data["utm_campaign"] == "natal"
    # Whitelist defensiva: chave fora de TRACKING_COLUMNS não é gravada.
    assert "ignored_key" not in data


# --------------------------------------------------------------------------- #
# persist_lead_tracking — last-touch update, defensive about empty/unchanged
# --------------------------------------------------------------------------- #

def test_persist_lead_tracking_updates_only_changed_truthy_fields():
    with patch("app.leads.service.update_lead") as upd:
        persist_lead_tracking(
            {"id": "L1", "utm_source": "google", "gclid": None},
            {"utm_source": "facebook", "gclid": "g_new", "utm_medium": ""},
        )
    # utm_source mudou e gclid novo → atualiza; utm_medium vazio → ignorado
    # gclid presente → traffic_type="paid" também é incluído no update
    upd.assert_called_once()
    _, kwargs = upd.call_args
    assert kwargs == {"utm_source": "facebook", "gclid": "g_new", "traffic_type": "paid"}


def test_persist_lead_tracking_noop_when_no_new_data():
    with patch("app.leads.service.update_lead") as upd:
        persist_lead_tracking({"id": "L1", "utm_source": "google"}, {})
        # utm_source unchanged AND traffic_type already "organic" → no update
        persist_lead_tracking(
            {"id": "L1", "utm_source": "google", "traffic_type": "organic"},
            {"utm_source": "google"},
        )
        persist_lead_tracking({"id": "L1"}, None)
    upd.assert_not_called()


def test_persist_lead_tracking_does_not_overwrite_with_empty():
    """Organic resubmit (empty tracking) must never wipe a captured attribution."""
    with patch("app.leads.service.update_lead") as upd:
        persist_lead_tracking(
            {"id": "L1", "gclid": "kept", "utm_campaign": "kept_c"},
            {"gclid": "", "utm_campaign": "   "},
        )
    upd.assert_not_called()
