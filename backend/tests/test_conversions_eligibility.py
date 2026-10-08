# backend/tests/test_conversions_eligibility.py
from datetime import datetime, timedelta, timezone

from app.conversions.eligibility import (
    Click, attributed_click, build_dedupe_key, build_event_id, clicks_from_entradas,
    clicks_from_lead_fallback, qualified_handoff_ok, segment_for, stage_allowed,
)

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def _entrada(at, **meta):
    return {"occurred_at": at.isoformat(), "metadata": meta}


def test_clicks_from_entradas_separa_por_plataforma():
    entradas = [
        _entrada(T0, ctwa_clid="C1", campanha_nome="PL | WA", meta_ad_id="ad1"),
        _entrada(T0 + timedelta(days=1), gclid="G1", campanha_nome="Atacado Search"),
        _entrada(T0 + timedelta(days=2), gbraid="B1"),
        _entrada(T0 + timedelta(days=3), utm_source="google"),  # sem ID de clique: ignora
    ]
    clicks = clicks_from_entradas(entradas)
    assert [(c.platform, c.click_id_type, c.click_id) for c in clicks] == [
        ("meta", "ctwa_clid", "C1"), ("google", "gclid", "G1"), ("google", "gbraid", "B1"),
    ]
    assert clicks[0].campaign_name == "PL | WA"


def test_fallback_do_lead_so_para_clique_sem_entrada():
    lead = {"ctwa_clid": "C1", "gclid": "G9", "created_at": T0.isoformat()}
    ja = [Click("meta", "C1", "ctwa_clid", T0, None)]
    extra = clicks_from_lead_fallback(lead, ja)
    assert [(c.click_id, c.click_at) for c in extra] == [("G9", T0)]


def test_attributed_click_pega_o_mais_recente_antes_do_evento():
    clicks = [
        Click("meta", "C1", "ctwa_clid", T0, None),
        Click("meta", "C2", "ctwa_clid", T0 + timedelta(days=2), None),
        Click("meta", "C3", "ctwa_clid", T0 + timedelta(days=9), None),  # depois do evento
    ]
    c = attributed_click(clicks, "meta", T0 + timedelta(days=3))
    assert c.click_id == "C2"


def test_attributed_click_respeita_janela_meta_7_dias():
    clicks = [Click("meta", "C1", "ctwa_clid", T0, None)]
    assert attributed_click(clicks, "meta", T0 + timedelta(days=7)) is not None
    assert attributed_click(clicks, "meta", T0 + timedelta(days=7, seconds=1)) is None


def test_attributed_click_google_90_dias():
    clicks = [Click("google", "G1", "gclid", T0, None)]
    assert attributed_click(clicks, "google", T0 + timedelta(days=89)) is not None
    assert attributed_click(clicks, "google", T0 + timedelta(days=91)) is None


def test_segment_for():
    assert segment_for("atacado") == "atacado"
    assert segment_for("private_label") == "private_label"
    for s in ("pending", "consumo", "secretaria", "exportacao", None, ""):
        assert segment_for(s) == "geral"


def test_qualified_handoff_ok_exclui_fallbacks():
    assert qualified_handoff_ok({"at": T0.isoformat(), "motivo": "private label qualificado"})
    assert qualified_handoff_ok({"at": T0.isoformat(), "motivo": "bot de botões da ValerIA: lead pediu atendimento do vendedor"})
    assert not qualified_handoff_ok({"at": T0.isoformat(), "motivo": "IA temporariamente indisponível — atendimento encaminhado ao humano"})
    assert not qualified_handoff_ok({"at": T0.isoformat(), "motivo": "bot de recuperação: lead pediu atendimento do vendedor"})
    assert not qualified_handoff_ok({"at": T0.isoformat(), "motivo": "ESCALONAMENTO — reclamacao sobre atendimento: x"})
    assert not qualified_handoff_ok({"motivo": "lead qualificado"})  # sem data
    assert not qualified_handoff_ok(None)


def test_stage_allowed_ja_era_cliente_so_venda():
    assert stage_allowed("purchase", True)
    for st in ("lead", "qualified", "opportunity"):
        assert not stage_allowed(st, True)
        assert stage_allowed(st, None)
        assert stage_allowed(st, False)


def test_chaves_deterministicas():
    assert build_dedupe_key("meta", "qualified", "C1", None) == "meta:qualified:C1"
    assert build_dedupe_key("google", "purchase", "G1", "sale-1") == "google:purchase:sale-1"
    e1 = build_event_id("qualified", "lead-1", "C1", None)
    assert e1 == build_event_id("qualified", "lead-1", "C1", None)
    assert e1.startswith("qualified:lead-1:") and len(e1) <= 64
    assert build_event_id("purchase", "lead-1", "C1", "sale-1") == "purchase:sale-1"
