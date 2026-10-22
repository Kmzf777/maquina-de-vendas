"""Leitores que ainda liam o segmento em `leads.stage` (revisão do cartão b67f1c6b).

Depois do F3, `leads.stage` é FASE ('qualificando', 'perdido'...). Quem decide por segmento
lê `segmento_do_lead` (`leads.segmento`, com o `stage` antigo como reserva de transição).
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.follow_up.service import should_proactive_handoff


# ── backstop pós-catálogo ─────────────────────────────────────────────────────

def test_backstop_le_leads_segmento_com_fase_qualificando():
    lead = {"id": "L1", "stage": "qualificando", "segmento": "private_label",
            "metadata": {"catalog_shown": True}}
    assert should_proactive_handoff(lead) is True


def test_backstop_lead_antigo_com_segmento_no_stage():
    assert should_proactive_handoff({"id": "L1", "stage": "atacado", "segmento": None,
                                     "metadata": {"catalog_shown": True}}) is True


def test_backstop_segmento_consumo_fica_fora():
    assert should_proactive_handoff({"id": "L1", "stage": "qualificando", "segmento": "consumo",
                                     "metadata": {"catalog_shown": True}}) is False


def test_backstop_releitura_do_lead_traz_segmento():
    from app.follow_up import scheduler as S
    sb = MagicMock()
    with patch.object(S, "get_supabase", return_value=sb):
        S._fetch_lead_for_backstop("L1")
    cols = sb.table.return_value.select.call_args.args[0]
    assert "segmento" in [c.strip() for c in cols.split(",")]


# ── deal Perdido criado na rejeição branda ───────────────────────────────────

def test_deal_perdido_novo_usa_segmento_e_nao_a_fase():
    from app.leads import service as svc
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    alvo = {}

    def _target(_sb, category):
        alvo["category"] = category
        return "p1", "s1"

    with patch.object(svc, "get_supabase", return_value=sb), \
         patch.object(svc, "get_lead", return_value={"id": "L1", "name": "Ana", "stage": "perdido",
                                                       "segmento": "atacado"}), \
         patch.object(svc, "_perdido_target_for_category", side_effect=_target):
        svc.move_lead_deals_to_perdido("L1", "sem interesse")
    assert alvo["category"] == "atacado"
    payload = sb.table.return_value.insert.call_args.args[0]
    assert payload["category"] == "atacado"


# ── simulador de cadência (modo teste) ───────────────────────────────────────

def test_simulador_in_stage_casa_segmento_como_o_motor():
    from app.automation import test_runner as tr
    lead = {"id": "L1", "stage": "qualificando", "segmento": "atacado"}
    now = datetime.now(timezone.utc)
    with patch.object(tr, "get_supabase", return_value=MagicMock()):
        assert tr._eval_condition({"condition_type": "in_stage", "stage": "atacado"}, lead,
                                  {"lead_id": "L1"}, now) == "yes"
        assert tr._eval_condition({"condition_type": "in_stage", "stage": "qualificando"}, lead,
                                  {"lead_id": "L1"}, now) == "yes"
        assert tr._eval_condition({"condition_type": "in_stage", "stage": "consumo"}, lead,
                                  {"lead_id": "L1"}, now) == "no"
