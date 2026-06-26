"""TDD — Task 2: leads.service.get_relationship_summary

Casos (spec §6 item 6):
  (a) com venda → "CLIENTE ATIVO. Última compra…" incl. product e data formatada
  (b) sem venda mas lead_has_active_relationship True → mensagem de tratativa
  (c) nada → "lead novo"
  (d) fail-soft: supabase levanta → string neutra, sem exception

Padrão FakeSupabase: espelha test_cold_funnel_reflex_2026_06_25.py (_Query/FakeSupabase,
patch("app.leads.service.get_supabase", ...)).
A chain suportada aqui é: .select().eq().order().limit().execute()
"""
from unittest.mock import patch
import pytest


class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, fake):
        self.table = table
        self.fake = fake
        self.filters = {}

    def select(self, *a, **k):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def execute(self):
        return _Resp(self.fake.resolve(self))


class FakeSupabase:
    def __init__(self, resolver):
        self._resolver = resolver

    def table(self, name):
        return _Query(name, self)

    def resolve(self, q):
        return self._resolver(q.table, q.filters)


# ── (a) com venda ────────────────────────────────────────────────────────────

def test_with_sale_returns_active_client_message():
    """Com venda na tabela sales → mensagem CLIENTE ATIVO com produto, valor e data DD/MM/YYYY."""
    from app.leads.service import get_relationship_summary

    sale_row = {
        "product": "Café Especial 1kg",
        "value": 150.0,
        "sold_at": "2026-01-15T10:30:00",
    }

    def resolver(table, filters):
        if table == "sales" and filters.get("lead_id") == "lead-1":
            return [sale_row]
        return []

    with patch("app.leads.service.get_supabase", return_value=FakeSupabase(resolver)):
        result = get_relationship_summary("lead-1")

    assert "CLIENTE ATIVO" in result
    assert "Café Especial 1kg" in result
    assert "R$ 150" in result
    assert "15/01/2026" in result
    assert "reabastecimento" in result or "upsell" in result
    assert "NÃO requalifique" in result


def test_with_sale_value_formatted_brazillian():
    """Valor com casas decimais é formatado no padrão BRL."""
    from app.leads.service import get_relationship_summary

    sale_row = {
        "product": "Cápsulas Premium",
        "value": 1169.70,
        "sold_at": "2026-03-22T14:00:00",
    }

    def resolver(table, filters):
        if table == "sales":
            return [sale_row]
        return []

    with patch("app.leads.service.get_supabase", return_value=FakeSupabase(resolver)):
        result = get_relationship_summary("lead-x")

    assert "22/03/2026" in result
    # Valor deve aparecer no formato BRL (R$ 1.169,70 — ponto milhar, vírgula decimal)
    assert "1.169,70" in result


# ── (b) sem venda mas lead_has_active_relationship True ─────────────────────

def test_no_sale_active_relationship_returns_tratativa_message():
    """Sem venda mas relacionamento ativo → mensagem de tratativa (não 'lead novo')."""
    from app.leads.service import get_relationship_summary

    def resolver(table, filters):
        return []  # sem vendas

    with patch("app.leads.service.get_supabase", return_value=FakeSupabase(resolver)), \
         patch("app.leads.service.lead_has_active_relationship", return_value=True):
        result = get_relationship_summary("lead-2")

    assert "CLIENTE ATIVO" in result
    assert "tratativa" in result
    # "lead novo" aparece na string de tratativa como "NÃO rode funil de lead novo"
    # — o que NÃO deve aparecer é a mensagem do caminho SEM histórico ("tratar como lead novo")
    assert "tratar como lead novo" not in result
    assert "NÃO rode funil de lead novo" in result


# ── (c) nada → lead novo ─────────────────────────────────────────────────────

def test_no_history_returns_lead_novo():
    """Sem venda e sem relacionamento ativo → 'tratar como lead novo'."""
    from app.leads.service import get_relationship_summary

    def resolver(table, filters):
        return []

    with patch("app.leads.service.get_supabase", return_value=FakeSupabase(resolver)), \
         patch("app.leads.service.lead_has_active_relationship", return_value=False):
        result = get_relationship_summary("lead-3")

    assert "lead novo" in result
    assert "CLIENTE ATIVO" not in result


# ── (d) fail-soft: supabase levanta ──────────────────────────────────────────

def test_fail_soft_on_supabase_error():
    """Exceção no Supabase → string neutra, nunca levanta."""
    from app.leads.service import get_relationship_summary

    def boom():
        raise RuntimeError("db is down")

    with patch("app.leads.service.get_supabase", side_effect=boom):
        result = get_relationship_summary("lead-4")

    # Deve retornar string segura — não pode propagar a exceção
    assert isinstance(result, str)
    assert len(result) > 0
    assert "possível consultar" in result or "relacionamento" in result
