from unittest.mock import patch
from app.campaigns import google_export


def test_conversion_name_for_mapping():
    assert google_export.conversion_name_for("qualified") == "Lead_Qualificado"
    assert google_export.conversion_name_for("purchase") == "Venda_Fechada"
    assert google_export.conversion_name_for("lead") == "Lead_Captado"
    assert google_export.conversion_name_for("opportunity") == "Oportunidade_Criada"


def test_build_google_csv_format():
    rows = [
        {"id": "1", "gclid": "g1", "event": "qualified", "value": 50, "currency": "BRL",
         "created_at": "2026-07-02T19:00:00+00:00"},
        {"id": "2", "gclid": "g2", "event": "purchase", "value": None, "currency": "BRL",
         "created_at": "2026-07-02T21:30:00Z"},
    ]
    csv_text = google_export.build_google_csv(rows)
    lines = csv_text.strip().split("\n")
    assert lines[0] == "Parameters:TimeZone=America/Sao_Paulo"
    assert lines[1] == "Google Click ID,Conversion Name,Conversion Time,Conversion Value,Conversion Currency"
    assert lines[2] == "g1,Lead_Qualificado,2026-07-02 16:00:00,50,BRL"
    assert lines[3] == "g2,Venda_Fechada,2026-07-02 18:30:00,,BRL"


def test_export_marks_pending_but_not_when_include_all():
    rows = [{"id": "1", "gclid": "g1", "event": "qualified", "value": 50, "currency": "BRL",
             "created_at": "2026-07-02T19:00:00+00:00"}]
    with patch("app.campaigns.google_export.fetch_pending_google_rows", return_value=rows), \
         patch("app.campaigns.google_export.mark_exported") as mark:
        text, count = google_export.export_google_csv(include_all=False, mark=True)
    assert count == 1
    mark.assert_called_once_with(["1"])
    with patch("app.campaigns.google_export.fetch_pending_google_rows", return_value=rows), \
         patch("app.campaigns.google_export.mark_exported") as mark2:
        google_export.export_google_csv(include_all=True, mark=False)
    mark2.assert_not_called()
