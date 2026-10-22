"""Automação com fase e segmento separados (cartão b67f1c6b, B9).

- `move_stage` só grava FASE em `leads.stage`; valor que não é fase é ignorado (loga).
- `stage_enter` / `in_stage`: valor de segmento compara com `leads.segmento`; fase, com `stage`.
- `node_registry`: vocabulários `fase_lead` e `segmento_lead`; "Mover fase"; ativação recusa
  valor fora da lista.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.automation import engine
from app.automation.engine import _execute_action, _execute_condition
from app.automation.triggers import _passes_filter
from app.campaigns.node_registry import REGISTRO, VALORES_FIXOS, VOCABULARIOS
from app.leads.segmento import FASES, SEGMENTOS


# ── node_registry ─────────────────────────────────────────────────────────────────

def _campo(tipo, sub, chave):
    return next(c for c in REGISTRO[(tipo, sub)].campos if c.chave == chave)


def test_vocabularios_fase_e_segmento_batem_com_o_contrato():
    assert {"fase_lead", "segmento_lead"} <= VOCABULARIOS
    assert tuple(v for v, _ in VALORES_FIXOS["fase_lead"]) == FASES
    assert tuple(v for v, _ in VALORES_FIXOS["segmento_lead"]) == SEGMENTOS
    assert dict(VALORES_FIXOS["fase_lead"])["triagem"] == "Em triagem"


def test_fase_ou_segmento_e_a_uniao():
    valores = {v for v, _ in VALORES_FIXOS["fase_ou_segmento_lead"]}
    assert valores == set(FASES) | set(SEGMENTOS)
    assert "secretaria" not in valores


def test_move_stage_vira_mover_fase():
    t = REGISTRO[("action", "move_stage")]
    assert t.rotulo == "Mover fase"
    assert _campo("action", "move_stage", "stage").vocab == "fase_lead"


def test_gatilhos_por_leads_stage_usam_fase():
    for sub in ("no_message", "stage_stagnation", "no_sale_in_stage"):
        assert _campo("trigger", sub, "stage_filter").vocab == "fase_lead", sub


def test_stage_enter_e_in_stage_aceitam_fase_ou_segmento():
    assert _campo("trigger", "stage_enter", "stage_filter").vocab == "fase_ou_segmento_lead"
    assert _campo("condition", "in_stage", "stage").vocab == "fase_ou_segmento_lead"


def test_ativacao_recusa_valor_fora_da_lista():
    from app.campaigns.validation import _problemas_de_valor
    campo = _campo("action", "move_stage", "stage")
    no = {"id": "n1", "type": "action", "config": {"action_type": "move_stage", "stage": "atacado"}}
    assert _problemas_de_valor(no, campo, "atacado", "nó")
    assert _problemas_de_valor(no, campo, "secretaria", "nó")
    assert not _problemas_de_valor(no, campo, "triagem", "nó")
    seg = _campo("trigger", "stage_enter", "stage_filter")
    assert not _problemas_de_valor(no, seg, "atacado", "nó")
    assert _problemas_de_valor(no, seg, "secretaria", "nó")


# ── engine: move_stage ────────────────────────────────────────────────────────────

def test_move_stage_grava_fase():
    with patch("app.automation.engine.get_supabase", return_value=MagicMock()), \
         patch("app.leads.service.update_lead") as up:
        agiu = _execute_action({"id": "e1", "lead_id": "L1"},
                               {"config": {"action_type": "move_stage", "stage": "qualificando"}},
                               {"id": "L1", "phone": "55"})
    assert agiu is True
    up.assert_called_once_with("L1", stage="qualificando")


def test_move_stage_ignora_segmento_e_lixo():
    for valor in ("atacado", "secretaria", "Em conversa"):
        with patch("app.automation.engine.get_supabase", return_value=MagicMock()), \
             patch("app.leads.service.update_lead") as up:
            agiu = _execute_action({"id": "e1", "lead_id": "L1"},
                                   {"config": {"action_type": "move_stage", "stage": valor}},
                                   {"id": "L1", "phone": "55"})
        assert agiu is False, valor
        up.assert_not_called()


# ── engine: in_stage ──────────────────────────────────────────────────────────────

def _in_stage(alvo, fresh):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = fresh
    node = {"config": {"condition_type": "in_stage", "stage": alvo}, "yes_node_id": "SIM", "no_node_id": "NAO"}
    with patch("app.automation.engine.get_supabase", return_value=sb), \
         patch.object(engine, "_update") as upd, patch.object(engine, "_complete"):
        _execute_condition({"id": "e1", "lead_id": "L1"}, node, {"phone": "55"},
                           datetime.now(timezone.utc))
    return upd.call_args.kwargs["current_node_id"]


def test_in_stage_segmento_compara_com_leads_segmento():
    assert _in_stage("atacado", {"stage": "qualificando", "segmento": "atacado"}) == "SIM"
    assert _in_stage("atacado", {"stage": "qualificando", "segmento": "consumo"}) == "NAO"


def test_in_stage_segmento_cai_no_stage_antigo():
    assert _in_stage("private_label", {"stage": "private_label", "segmento": None}) == "SIM"


def test_in_stage_fase_compara_com_stage():
    assert _in_stage("qualificando", {"stage": "qualificando", "segmento": "atacado"}) == "SIM"
    assert _in_stage("triagem", {"stage": "pending", "segmento": None}) == "NAO"
    # transição: lead ainda em 'secretaria' conta como triagem
    assert _in_stage("triagem", {"stage": "secretaria", "segmento": None}) == "SIM"


# ── triggers: stage_enter ─────────────────────────────────────────────────────────

def test_stage_enter_segmento_compara_com_segmento():
    assert _passes_filter("stage_enter", {"stage_filter": "atacado"}, {"segmento": "atacado"})
    assert not _passes_filter("stage_enter", {"stage_filter": "atacado"}, {"segmento": "consumo"})
    # mudança só de fase não dispara gatilho de segmento
    assert not _passes_filter("stage_enter", {"stage_filter": "atacado"}, {"stage": "qualificando"})


def test_stage_enter_segmento_em_stage_legado():
    assert _passes_filter("stage_enter", {"stage_filter": "private_label"}, {"stage": "Private Label"})


def test_stage_enter_fase_compara_com_stage():
    assert _passes_filter("stage_enter", {"stage_filter": "triagem"}, {"stage": "triagem"})
    assert not _passes_filter("stage_enter", {"stage_filter": "triagem"}, {"segmento": "atacado"})
