"""Frente F4: motivo de perda estruturado (deals.lost_reason_code / lost_competitor)."""
from __future__ import annotations

import asyncio
import pathlib
import re
from unittest.mock import MagicMock, patch

import pytest

from app.leads import motivo_perda as mp

RAIZ = pathlib.Path(__file__).resolve().parents[2]
MIGRACAO = (RAIZ / "supabase/migrations/20261106_f4_deals_lost_reason_code.sql").read_text(encoding="utf-8")
FRONT = (RAIZ / "frontend/src/lib/lost-reason.ts").read_text(encoding="utf-8")

ESPERADO = ("preco_margem", "frete", "pedido_minimo", "condicao_bonificacao", "comprou_outro",
            "ainda_pesquisando", "consumidor_final", "sem_resposta", "outro")


# ── Vocabulário: uma lista só, em quatro lugares ────────────────────────────
def test_vocabulario_e_o_do_cartao():
    assert mp.CODIGOS == ESPERADO


def test_check_da_migracao_tem_exatamente_o_vocabulario():
    bloco = MIGRACAO.split("lost_reason_code IN (", 1)[1].split(")", 1)[0]
    assert tuple(re.findall(r"'([a-z_]+)'", bloco)) == ESPERADO


def test_migracao_aditiva_e_em_transacao():
    low = MIGRACAO.lower()
    assert "add column if not exists lost_reason_code text" in low
    assert "add column if not exists lost_competitor text" in low
    assert "begin;" in low and "commit;" in low
    assert "drop column" not in low.split("begin;", 1)[1]  # só no comentário de desfazer


def test_registro_de_nos_serve_o_mesmo_vocabulario():
    from app.campaigns.node_registry import REGISTRO, VALORES_FIXOS, VOCABULARIOS
    assert "motivo_perda" in VOCABULARIOS
    assert VALORES_FIXOS["motivo_perda"] == mp.MOTIVOS
    campos = {c.chave: c for c in REGISTRO[("action", "mark_deal_lost")].campos}
    assert campos["lost_reason_code"].vocab == "motivo_perda"


def test_frontend_tem_o_mesmo_vocabulario_na_mesma_ordem():
    codigos = tuple(re.findall(r'\{\s*code:\s*"([a-z_]+)"', FRONT))
    assert codigos == ESPERADO


# ── Normalização ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("entrada,saida", [
    ("frete", "frete"), (" FRETE ", "frete"), ("caro", None), (None, None), (3, None),
])
def test_normalizar_codigo(entrada, saida):
    assert mp.normalizar_codigo(entrada) == saida


def test_campos_de_perda_concorrente_so_com_comprou_outro():
    assert mp.campos_de_perda("comprou_outro", "  Orfeu   Cafés ") == {
        "lost_reason_code": "comprou_outro", "lost_competitor": "Orfeu Cafés"}
    assert mp.campos_de_perda("frete", "Orfeu") == {"lost_reason_code": "frete", "lost_competitor": None}
    assert mp.campos_de_perda("xyz") == {"lost_reason_code": "outro", "lost_competitor": None}
    assert len(mp.campos_de_perda("comprou_outro", "x" * 500)["lost_competitor"]) == mp.MAX_CONCORRENTE


@pytest.mark.parametrize("motivo,codigo", [
    ("Lead achou o preço alto para a margem dele", "preco_margem"),
    ("o frete ficou pesado para MG", "frete"),
    ("quer só para uso próprio, consumidor final", "consumidor_final"),
    ("já tem fornecedor e não quer trocar", "comprou_outro"),
    ("não respondeu mais depois da tabela", "sem_resposta"),
    # textos reais dos prompts: não podem virar comprou_outro nem preço
    ("lead é auto-produtor/concorrente de café — fora do ICP de atacado", None),
    ("lead busca café commodity/tradicional — fora do ICP de café especial", None),
    # dois motivos ao mesmo tempo: não adivinha
    ("preço e frete não fecharam", None),
    ("", None), (None, None),
])
def test_inferir_codigo(motivo, codigo):
    assert mp.inferir_codigo(motivo) == codigo


# ── Evento deal_closed_lost ─────────────────────────────────────────────────
def test_emitir_fora_do_loop_roda_o_gatilho():
    chamado = []

    async def falso(evento, lead_id, data=None):
        chamado.append((evento, lead_id, data))

    with patch("app.automation.triggers.fire_trigger", falso):
        mp.emitir_deal_closed_lost("L1", "D1", "frete")
    assert chamado == [("deal_closed_lost", "L1", {"deal_id": "D1", "lost_reason_code": "frete"})]


def test_emitir_dentro_do_loop_agenda_task():
    chamado = []

    async def falso(evento, lead_id, data=None):
        chamado.append(evento)

    async def cenario():
        mp.emitir_deal_closed_lost("L1", "D1", "frete")
        assert chamado == []          # agendado, não executado ainda
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    with patch("app.automation.triggers.fire_trigger", falso):
        asyncio.run(cenario())
    assert chamado == ["deal_closed_lost"]


def test_emitir_sem_lead_nao_faz_nada():
    with patch("app.automation.triggers.fire_trigger") as fire:
        mp.emitir_deal_closed_lost(None, "D1")
    fire.assert_not_called()


# ── move_lead_deals_to_perdido (descarte do agente) ─────────────────────────
def _sb_com_deals(deals):
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = deals
    return sb


def _updates(sb):
    return [c.args[0] for c in sb.table.return_value.update.call_args_list]


def test_descarte_grava_codigo_e_emite_por_deal():
    from app.leads import service
    sb = _sb_com_deals([{"id": "d1", "pipeline_id": "p1"}, {"id": "d2", "pipeline_id": "p1"}])
    with patch.object(service, "get_supabase", return_value=sb), \
         patch.object(service, "_perdido_stage_id", return_value="st-perdido"), \
         patch.object(mp, "emitir_deal_closed_lost") as emit:
        service.move_lead_deals_to_perdido("L1", reason="sem interesse", codigo="pedido_minimo")
    ups = _updates(sb)
    assert len(ups) == 2
    assert all(u["lost_reason_code"] == "pedido_minimo" and u["lost_competitor"] is None for u in ups)
    assert all(u["lost_reason"] == "sem interesse" and u["stage_id"] == "st-perdido" for u in ups)
    assert [c.args for c in emit.call_args_list] == [("L1", "d1", "pedido_minimo"), ("L1", "d2", "pedido_minimo")]


def test_descarte_sem_codigo_infere_do_motivo_e_cai_em_outro():
    from app.leads import service
    sb = _sb_com_deals([{"id": "d1", "pipeline_id": "p1"}])
    with patch.object(service, "get_supabase", return_value=sb), \
         patch.object(service, "_perdido_stage_id", return_value=None), \
         patch.object(mp, "emitir_deal_closed_lost"):
        service.move_lead_deals_to_perdido("L1", reason="o frete para MG pesou")
        service.move_lead_deals_to_perdido("L1", reason="fora do ICP")
        service.move_lead_deals_to_perdido("L1", reason="frete", codigo="invalido")
    a, b, c = _updates(sb)
    assert a["lost_reason_code"] == "frete"
    assert b["lost_reason_code"] == "outro"
    assert c["lost_reason_code"] == "frete"  # código inválido não vence a inferência


def test_descarte_sem_deal_cria_card_com_codigo_e_emite():
    from app.leads import service
    sb = _sb_com_deals([])
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "novo"}]
    with patch.object(service, "get_supabase", return_value=sb), \
         patch.object(service, "get_lead", return_value={"name": "Ana"}), \
         patch.object(service, "segmento_do_lead", return_value="atacado"), \
         patch.object(service, "_perdido_target_for_category", return_value=("p1", "s1")), \
         patch.object(mp, "emitir_deal_closed_lost") as emit:
        service.move_lead_deals_to_perdido("L1", reason="x", codigo="consumidor_final")
    ins = sb.table.return_value.insert.call_args.args[0]
    assert ins["lost_reason_code"] == "consumidor_final"
    emit.assert_called_once_with("L1", "novo", "consumidor_final")


def test_descarte_continua_fail_soft():
    from app.leads import service
    with patch.object(service, "get_supabase", side_effect=RuntimeError("banco fora")):
        service.move_lead_deals_to_perdido("L1", reason="x", codigo="frete")  # não levanta


# ── Ação mark_deal_lost da automação ────────────────────────────────────────
def _sb_deal_recente():
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [{"id": "d1"}]
    return sb


def test_mark_deal_lost_grava_codigo_do_no_e_emite():
    from app.automation.engine import _execute_action
    sb = _sb_deal_recente()
    node = {"config": {"action_type": "mark_deal_lost", "stage_id": "st",
                       "lost_reason_code": "sem_resposta", "lost_reason": "esteira"}}
    with patch("app.automation.engine.get_supabase", return_value=sb), \
         patch.object(mp, "emitir_deal_closed_lost") as emit:
        assert _execute_action({"id": "e1", "lead_id": "L1"}, node, {"id": "L1"}) is True
    up = _updates(sb)[0]
    assert up["lost_reason_code"] == "sem_resposta" and up["lost_reason"] == "esteira"
    emit.assert_called_once_with("L1", "d1", "sem_resposta")


def test_mark_deal_lost_sem_codigo_infere_da_observacao():
    from app.automation.engine import _execute_action
    sb = _sb_deal_recente()
    node = {"config": {"action_type": "mark_deal_lost", "stage_id": "st",
                       "lost_reason": "sem resposta na esteira de reposicao"}}
    with patch("app.automation.engine.get_supabase", return_value=sb), \
         patch.object(mp, "emitir_deal_closed_lost"):
        _execute_action({"id": "e1", "lead_id": "L1"}, node, {"id": "L1"})
    assert _updates(sb)[0]["lost_reason_code"] == "sem_resposta"


def test_mark_deal_won_nao_ganha_motivo_nem_evento():
    from app.automation.engine import _execute_action
    sb = _sb_deal_recente()
    node = {"config": {"action_type": "mark_deal_won", "stage_id": "st"}}
    with patch("app.automation.engine.get_supabase", return_value=sb), \
         patch.object(mp, "emitir_deal_closed_lost") as emit:
        _execute_action({"id": "e1", "lead_id": "L1"}, node, {"id": "L1"})
    assert "lost_reason_code" not in _updates(sb)[0]
    emit.assert_not_called()


def test_esteira_de_reposicao_perde_por_sem_resposta():
    from app.campaigns import esteiras
    txt = pathlib.Path(esteiras.__file__).read_text(encoding="utf-8")
    assert '"lost_reason_code": "sem_resposta"' in txt
