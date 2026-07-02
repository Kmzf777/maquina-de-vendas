from unittest.mock import MagicMock, patch
from app.campaigns import sheets_export


def test_build_sheet_row_matches_contract():
    lead = {"name": "João", "gclid": "g123", "email": "j@x.com", "phone": "5534996652412"}
    row = sheets_export.build_sheet_row(lead, "qualified", value=50.0, currency="BRL",
                                        when="2026-07-02 16:00:00")
    assert row[0] == "João"
    assert row[1] == "g123"
    assert row[2] == "j@x.com"
    assert len(row[3]) == 64  # sha256 hex do telefone
    assert row[4] == "Lead_Qualificado"
    assert row[5] == "2026-07-02 16:00:00"
    assert row[6] == "BRL"
    assert row[7] == 50.0
    assert row[8] == "qualificado"


def test_append_conversion_row_noop_without_config():
    with patch.dict("os.environ", {}, clear=True):
        result = sheets_export.append_conversion_row(["a"])
    assert result["synced"] is False
    assert result["reason"] == "no_config"


def test_append_conversion_row_calls_sheets_api_when_configured():
    env = {"GOOGLE_SHEETS_CONV_ID": "SHEET1", "GOOGLE_SA_JSON": '{"type":"service_account"}'}
    fake_service = MagicMock()
    with patch.dict("os.environ", env, clear=True), \
         patch("app.campaigns.sheets_export._build_service", return_value=fake_service):
        result = sheets_export.append_conversion_row(["a", "b"])
    assert result["synced"] is True
    fake_service.spreadsheets.return_value.values.return_value.append.assert_called_once()
