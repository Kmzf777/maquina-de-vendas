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


def test_aggregate_stats_counts_meta_google_and_events():
    rows = [
        {"event": "qualified", "sent_meta": True, "exported_at": None, "gclid": "g1", "value": 50},
        {"event": "opportunity", "sent_meta": False, "exported_at": "2026-07-02T10:00:00Z", "gclid": "g2", "value": 150},
        {"event": "purchase", "sent_meta": True, "exported_at": None, "gclid": "g3", "value": 500},
        {"event": "purchase", "sent_meta": True, "exported_at": None, "gclid": "", "value": 300},  # sem gclid
    ]
    stats = google_export.aggregate_stats(rows)
    assert stats["total"] == 4
    assert stats["meta_sent"] == 3
    assert stats["google_pending"] == 2   # g1 e g3 (não exportados, com gclid)
    assert stats["google_exported"] == 1  # g2
    assert stats["by_event"] == {"lead": 0, "qualified": 1, "opportunity": 1, "purchase": 2}
    assert stats["purchase_value"] == 800.0


def test_aggregate_stats_empty():
    stats = google_export.aggregate_stats([])
    assert stats["total"] == 0 and stats["meta_sent"] == 0
    assert stats["google_pending"] == 0 and stats["google_exported"] == 0
    assert stats["purchase_value"] == 0.0


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
