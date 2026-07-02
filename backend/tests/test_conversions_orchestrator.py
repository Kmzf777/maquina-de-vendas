from datetime import datetime, timezone
from unittest.mock import patch
from app.campaigns import conversions


LEAD = {"id": "L1", "name": "João", "phone": "5534996652412", "gclid": "g", "ctwa_clid": "c",
        "email": "j@x.com"}


def test_fire_stage_conversion_dedups():
    with patch("app.campaigns.conversions.already_fired", return_value=True), \
         patch("app.campaigns.conversions.dispatch_conversion") as disp, \
         patch("app.campaigns.conversions.append_conversion_row") as sheet:
        result = conversions.fire_stage_conversion(LEAD, "D1", "qualified", value=50.0)
    disp.assert_not_called()
    sheet.assert_not_called()
    assert result["skipped"] == "already_fired"


def test_fire_stage_conversion_dispatches_meta_and_sheet_then_records():
    with patch("app.campaigns.conversions.already_fired", return_value=False), \
         patch("app.campaigns.conversions.dispatch_conversion", return_value={"meta": {"sent": True}, "google": {}}) as disp, \
         patch("app.campaigns.conversions.append_conversion_row", return_value={"synced": True}) as sheet, \
         patch("app.campaigns.conversions.record_conversion_event") as record:
        conversions.fire_stage_conversion(LEAD, "D1", "qualified", value=50.0, currency="BRL")
    disp.assert_called_once_with(LEAD, "qualified", 50.0, "BRL")
    sheet.assert_called_once()
    kw = record.call_args.kwargs
    assert kw["deal_id"] == "D1" and kw["event"] == "qualified"
    assert kw["sent_meta"] is True and kw["sheet_synced"] is True


def test_fire_stage_conversion_records_even_when_meta_fails():
    with patch("app.campaigns.conversions.already_fired", return_value=False), \
         patch("app.campaigns.conversions.dispatch_conversion", return_value={"meta": {"sent": False}, "google": {}}), \
         patch("app.campaigns.conversions.append_conversion_row", return_value={"synced": False}), \
         patch("app.campaigns.conversions.record_conversion_event") as record:
        conversions.fire_stage_conversion(LEAD, "D1", "purchase", value=500.0)
    kw = record.call_args.kwargs
    assert kw["sent_meta"] is False and kw["sheet_synced"] is False
