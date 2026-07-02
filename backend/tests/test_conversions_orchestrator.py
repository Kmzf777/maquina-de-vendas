from unittest.mock import patch
from app.campaigns import conversions


LEAD = {"id": "L1", "name": "João", "phone": "5534996652412", "gclid": "g", "ctwa_clid": "c",
        "email": "j@x.com"}


def test_fire_stage_conversion_dedups():
    with patch("app.campaigns.conversions.already_fired", return_value=True), \
         patch("app.campaigns.conversions.dispatch_conversion") as disp:
        result = conversions.fire_stage_conversion(LEAD, "D1", "qualified", value=50.0)
    disp.assert_not_called()
    assert result["skipped"] == "already_fired"


def test_fire_stage_conversion_dispatches_meta_then_records():
    with patch("app.campaigns.conversions.already_fired", return_value=False), \
         patch("app.campaigns.conversions.dispatch_conversion", return_value={"meta": {"sent": True}, "google": {}}) as disp, \
         patch("app.campaigns.conversions.record_conversion_event") as record:
        conversions.fire_stage_conversion(LEAD, "D1", "qualified", value=50.0, currency="BRL")
    disp.assert_called_once_with(LEAD, "qualified", 50.0, "BRL")
    kw = record.call_args.kwargs
    assert kw["deal_id"] == "D1" and kw["event"] == "qualified" and kw["sent_meta"] is True


def test_fire_stage_conversion_records_even_when_meta_fails():
    with patch("app.campaigns.conversions.already_fired", return_value=False), \
         patch("app.campaigns.conversions.dispatch_conversion", return_value={"meta": {"sent": False}, "google": {}}), \
         patch("app.campaigns.conversions.record_conversion_event") as record:
        conversions.fire_stage_conversion(LEAD, "D1", "purchase", value=500.0)
    assert record.call_args.kwargs["sent_meta"] is False
