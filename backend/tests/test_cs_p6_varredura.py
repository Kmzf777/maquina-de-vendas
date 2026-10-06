"""P6 — a varredura do João consulta `sales` (paginando) antes de matricular."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.follow_up import service as S
from tests.test_agendador_joao_2026_09_18 import JOAO_CHANNEL, _ligada, _linha_rpc
from tests.test_followup_joao_duplicacao_2026_10_05 import (
    _BancoComTeto, _leads_matriculados)

# Terça 06/10/2026 12:00 BRT — dentro da janela comercial.
NOW = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)
KIT_LIGADO = {"reposicao_atacado": {"kit": {"ativa": True, "toques": {
    1: {"template_name": "followjoao_kit_1"}, 2: {"template_name": "followjoao_kit_2"}}}}}


def _iso(dias):
    return (NOW - timedelta(days=dias)).isoformat()


def _venda(lead, dias, *, id=None, status="registrada", deal=None):
    return {"id": id or f"s-{lead}-{dias}", "lead_id": lead, "deal_id": deal,
            "sold_at": _iso(dias), "created_at": _iso(dias), "status": status}


def _rodar(banco, overrides):
    with (
        patch("app.follow_up.service.get_supabase", return_value=banco),
        patch("app.follow_up.service.carregar_overrides_joao", return_value=overrides),
        patch("app.follow_up.service.carregar_ajustes_joao",
              return_value={"teto_diario_disparos": 100, "adiamento_estoque_dias": 30}),
        patch("app.follow_up.service.get_channel_by_provider_config",
              return_value=JOAO_CHANNEL),
        patch("app.follow_up.service.get_or_create_conversation",
              side_effect=lambda lead_id, ch: {"id": f"conv-{lead_id}"}),
        patch("app.leads.service.is_lead_blacklisted", return_value=False),
        patch("app.follow_up.service.emit_event"),
    ):
        return S.agendar_cadencias_joao(now=NOW, teto=500)


def _proposta_so_no_atacado():
    return {"atacado": _ligada("proposta")["atacado"]}


def test_caso_real_proposta_nao_matricula_quem_comprou_em_outro_deal():
    banco = _BancoComTeto({
        "sales": [_venda("lead-comprou", 3, deal="deal-de-outro-card")],
        "deals": [{"id": "deal-comprou", "created_at": _iso(10)},
                  {"id": "deal-livre", "created_at": _iso(10)}],
    }, rpc_rows=[_linha_rpc(lead="lead-comprou", deal="deal-comprou"),
                 _linha_rpc(lead="lead-livre", deal="deal-livre")])
    _rodar(banco, _proposta_so_no_atacado())
    assert _leads_matriculados(banco) == {"lead-livre"}


def test_venda_depois_da_criacao_do_card_tambem_pula():
    banco = _BancoComTeto({
        "sales": [_venda("lead-a", 60)],
        "deals": [{"id": "deal-a", "created_at": _iso(90)}],
    }, rpc_rows=[_linha_rpc(lead="lead-a", deal="deal-a")])
    _rodar(banco, _proposta_so_no_atacado())
    assert banco.inserts == []


def test_leitura_de_vendas_pagina_acima_de_1000_linhas():
    # 1.200 vendas CANCELADAS antigas na frente; a venda que conta é a 1.201ª.
    antigas = [_venda("lead-a", 400, id=f"c{i:05d}", status="cancelada") for i in range(1200)]
    recente = _venda("lead-a", 2, id="z-recente")
    banco = _BancoComTeto({
        "sales": antigas + [recente],
        "deals": [{"id": "deal-a", "created_at": _iso(10)}],
    }, rpc_rows=[_linha_rpc(lead="lead-a", deal="deal-a")])
    _rodar(banco, _proposta_so_no_atacado())
    assert banco.inserts == []


def test_vendas_pedidas_em_lotes_de_ate_200_leads():
    linhas = [_linha_rpc(lead=f"lead-{i}", deal=f"deal-{i}") for i in range(450)]
    banco = _BancoComTeto({"sales": [], "deals": []}, rpc_rows=linhas)
    _rodar(banco, _proposta_so_no_atacado())
    lotes = [len(val) for nome, filtros, _f in banco.selects if nome == "sales"
             for op, col, val in filtros if op == "in" and col == "lead_id"]
    assert lotes and max(lotes) <= 200


def test_falha_ao_ler_vendas_nao_matricula_ninguem():
    class _SemVendas(_BancoComTeto):
        def table(self, nome):
            if nome == "sales":
                raise RuntimeError("statement timeout")
            return super().table(nome)

    banco = _SemVendas({"deals": []}, rpc_rows=[_linha_rpc(lead="lead-a", deal="deal-a")])
    _rodar(banco, _proposta_so_no_atacado())
    assert banco.inserts == []


def test_kit_matricula_so_quem_tem_kit_como_ultima_compra_ha_20_dias():
    banco = _BancoComTeto({
        "sales": [_venda("lead-kit", 20, id="s-kit"), _venda("lead-normal", 25, id="s-cafe"),
                  _venda("lead-recente", 19, id="s-kit-novo")],
        "sale_items": [
            {"id": "i1", "sale_id": "s-kit", "bling_product_id": 16536419853,
             "descricao": "Kit Degustação"},
            {"id": "i2", "sale_id": "s-cafe", "bling_product_id": 1,
             "descricao": "Café Clássico Moído 250g"},
            {"id": "i3", "sale_id": "s-kit-novo", "bling_product_id": 9256328993,
             "descricao": "KIT DEGUSTAÇÃO"},
        ],
    }, rpc_rows=[_linha_rpc(lead="lead-kit", deal="deal-kit"),
                 _linha_rpc(lead="lead-normal", deal="deal-normal"),
                 _linha_rpc(lead="lead-recente", deal="deal-recente")])
    _rodar(banco, KIT_LIGADO)

    assert _leads_matriculados(banco) == {"lead-kit"}
    jobs = [row for _t, rows in banco.inserts for row in rows]
    assert [j["job_type"] for j in jobs] == ["joao_kit", "joao_kit"]  # sem job de mover
    assert [j["metadata"]["template_name"] for j in jobs] == \
        ["followjoao_kit_1", "followjoao_kit_2"]
    assert {j["metadata"]["funil"] for j in jobs} == {"reposicao_atacado"}


def test_kit_desligado_nao_varre_nem_le_vendas():
    banco = _BancoComTeto({"sales": [_venda("lead-kit", 30)]},
                          rpc_rows=[_linha_rpc(lead="lead-kit", deal="deal-kit")])
    assert _rodar(banco, {}) == 0
    assert banco.inserts == []
    assert not any(nome == "sales" for nome, _f, _r in banco.selects)
