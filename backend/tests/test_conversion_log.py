from unittest.mock import MagicMock, patch
from app.campaigns import conversion_log


def _fake_sb():
    sb = MagicMock()
    return sb


def test_already_fired_true_when_row_exists():
    sb = _fake_sb()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{"id": "x"}]
    with patch("app.campaigns.conversion_log.get_supabase", return_value=sb):
        assert conversion_log.already_fired("deal1", "qualified") is True


def test_already_fired_false_when_no_row():
    sb = _fake_sb()
    sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    with patch("app.campaigns.conversion_log.get_supabase", return_value=sb):
        assert conversion_log.already_fired("deal1", "qualified") is False


def test_record_conversion_event_inserts_row():
    sb = _fake_sb()
    with patch("app.campaigns.conversion_log.get_supabase", return_value=sb):
        conversion_log.record_conversion_event(
            lead_id="L1", deal_id="D1", event="qualified", value=50.0,
            currency="BRL", gclid="g", ctwa_clid="c", sent_meta=True, sheet_synced=False,
        )
    args = sb.table.return_value.insert.call_args[0][0]
    assert args["deal_id"] == "D1" and args["event"] == "qualified"
    assert args["sent_meta"] is True and args["sheet_synced"] is False
