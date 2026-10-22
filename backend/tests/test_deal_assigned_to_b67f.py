"""deals.assigned_to no card novo/movido para funil de vendedor (revisão b67f1c6b).

Quando o card cai num pipeline com `owner_user_id` (ou o repasse resolve o vendedor), o
deal ganha `assigned_to` = esse vendedor — só se estiver vazio (`is null` no UPDATE) e se
o id existir no cadastro `vendedores` (FK). Fail-soft: erro não derruba o card.
"""
from unittest.mock import patch

import pytest

from app.vendedores import service as vendedores
from tests.test_create_deal_routing import FakeSupabase

JOAO = {"id": "u-joao", "nome": "João Brás", "segmentos": ["atacado", "private_label"], "ativo": True}


@pytest.fixture
def tabela(monkeypatch):
    vendedores.limpar_cache()
    monkeypatch.setattr(vendedores, "_carregar", lambda: [dict(JOAO)])
    yield
    vendedores.limpar_cache()


def _resolver(owner):
    def resolver(table, filters):
        if table == "pipelines":
            if filters.get("name") == "João - Atacado" or filters.get("id") == "pl-joao":
                return [{"id": "pl-joao", "owner_user_id": owner}]
            return []
        if table == "pipeline_stages":
            return [{"id": "st-novo"}]
        return []
    return resolver


def _assigns(updated):
    return [(p, f) for (t, p, f) in updated if t == "deals" and "assigned_to" in p]


def test_create_deal_em_funil_com_dono_grava_assigned_to(tabela):
    from app.leads.service import create_deal
    inserted, updated = [], []
    with patch("app.leads.service.get_supabase",
               return_value=FakeSupabase(_resolver("u-joao"), inserted, updated)):
        deal = create_deal("L1", "x", pipeline_name="João - Atacado")
    assert _assigns(updated) == [({"assigned_to": "u-joao"},
                                  {"id": "deals-new", ("is", "assigned_to"): "null"})]
    assert deal["assigned_to"] == "u-joao"


def test_create_deal_dono_fora_do_cadastro_nao_grava(tabela):
    from app.leads.service import create_deal
    inserted, updated = [], []
    with patch("app.leads.service.get_supabase",
               return_value=FakeSupabase(_resolver("u-desconhecido"), inserted, updated)):
        create_deal("L1", "x", pipeline_name="João - Atacado")
    assert _assigns(updated) == [] and len(inserted) == 1


def test_create_deal_funil_sem_dono_nao_grava(tabela):
    from app.leads.service import create_deal
    inserted, updated = [], []
    with patch("app.leads.service.get_supabase",
               return_value=FakeSupabase(_resolver(None), inserted, updated)):
        create_deal("L1", "x", pipeline_name="João - Atacado")
    assert _assigns(updated) == []


def test_erro_de_fk_nao_derruba_o_card(tabela):
    from app.leads.service import create_deal

    class _Falha(FakeSupabase):
        def resolve(self, q):
            if q.op == "update" and "assigned_to" in (q.payload or {}):
                raise RuntimeError("23503 violates foreign key constraint deals_assigned_to_fkey")
            return super().resolve(q)

    inserted = []
    with patch("app.leads.service.get_supabase", return_value=_Falha(_resolver("u-joao"), inserted)):
        deal = create_deal("L1", "x", pipeline_name="João - Atacado")
    assert deal["id"] == "deals-new" and "assigned_to" not in deal


def test_move_deal_to_vendor_pipeline_grava_dono_no_card_movido(tabela):
    from app.leads import service as svc
    inserted, updated = [], []
    with patch.object(svc, "get_supabase",
                      return_value=FakeSupabase(_resolver("u-joao"), inserted, updated)), \
         patch.object(svc, "get_open_deal", return_value={"id": "d-1", "pipeline_id": "pl-lp"}):
        svc.move_deal_to_vendor_pipeline("L1", "atacado", title="t")
    assert _assigns(updated) == [({"assigned_to": "u-joao"}, {"id": "d-1", ("is", "assigned_to"): "null"})]


def test_atribuir_vendedor_ao_deal_ignora_id_invalido(tabela):
    from app.leads.service import atribuir_vendedor_ao_deal
    assert atribuir_vendedor_ao_deal({"id": "d"}, None) is False
    assert atribuir_vendedor_ao_deal({"id": "d"}, "u-x") is False
    assert atribuir_vendedor_ao_deal({"id": "d", "assigned_to": "u-joao"}, "u-joao") is False
