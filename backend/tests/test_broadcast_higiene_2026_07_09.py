"""Higiene de outbound frio — auditoria 2026-07-08.

Casos reais:
- Nayara (cliente com compra em 26/05 e cotação do vendedor humano em 15/05)
  entrou na lista fria e recebeu o template de "atualização de cadastro" 3x em
  13 dias. `lead_has_active_relationship` não a pegou porque a compra nunca
  virou `sales`/deal fechado — mas as MENSAGENS do vendedor estavam lá.
- Daniel Vitor recebeu o MESMO template em 04/07 e 08/07 e clicou
  "Parar mensagens" no segundo (re-blast idêntico queima lista).
"""
import pytest
from unittest.mock import MagicMock

from app.templates.intent import COLD_REACTIVATION, GENERIC


class _SbStub:
    """Stub encadeável mínimo do supabase-py: qualquer método devolve self;
    execute() devolve .data fixado (ou levanta, se raise_exc)."""

    def __init__(self, data=None, raise_exc: Exception | None = None):
        self._data = data or []
        self._raise = raise_exc

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        if self._raise:
            raise self._raise
        result = MagicMock()
        result.data = self._data
        return result


# ---------------------------------------------------------------------------
# leads.service.lead_recently_engaged (janela de 90d de contato humano)
# ---------------------------------------------------------------------------

def test_lead_recently_engaged_true_com_msg_de_seller(monkeypatch):
    from app.leads import service
    monkeypatch.setattr(service, "get_supabase", lambda: _SbStub(data=[{"id": "m1"}]))
    assert service.lead_recently_engaged("L1") is True


def test_lead_recently_engaged_false_sem_msgs(monkeypatch):
    from app.leads import service
    monkeypatch.setattr(service, "get_supabase", lambda: _SbStub(data=[]))
    assert service.lead_recently_engaged("L1") is False


def test_lead_recently_engaged_fail_open_em_erro(monkeypatch):
    from app.leads import service
    monkeypatch.setattr(service, "get_supabase", lambda: _SbStub(raise_exc=RuntimeError("db down")))
    assert service.lead_recently_engaged("L1") is False


def test_active_relationship_inclui_contato_recente_de_seller(monkeypatch):
    """O caso Nayara: sem sales/deal, mas COM mensagens do vendedor há <90d."""
    from app.leads import service
    monkeypatch.setattr(service, "get_supabase", lambda: _SbStub(data=[]))
    monkeypatch.setattr(service, "lead_recently_engaged", lambda *a, **k: True)
    assert service.lead_has_active_relationship("L1") is True


# ---------------------------------------------------------------------------
# broadcast.worker guardrails (camada de envio)
# ---------------------------------------------------------------------------

def test_hot_guardrail_bloqueia_lead_quente_em_disparo_frio(monkeypatch):
    from app.broadcast import worker
    monkeypatch.setattr(worker, "lead_has_active_relationship", lambda _id: True)
    reason = worker._hot_lead_guardrail({"id": "L1", "phone": "55349"}, COLD_REACTIVATION)
    assert reason


def test_hot_guardrail_nao_bloqueia_intent_generico(monkeypatch):
    from app.broadcast import worker
    monkeypatch.setattr(worker, "lead_has_active_relationship", lambda _id: True)
    assert worker._hot_lead_guardrail({"id": "L1"}, GENERIC) is None


def test_hot_guardrail_libera_lead_frio(monkeypatch):
    from app.broadcast import worker
    monkeypatch.setattr(worker, "lead_has_active_relationship", lambda _id: False)
    assert worker._hot_lead_guardrail({"id": "L1"}, COLD_REACTIVATION) is None


def test_dedup_guardrail_bloqueia_template_repetido_na_janela(monkeypatch):
    from app.broadcast import worker
    monkeypatch.setattr(worker, "get_supabase", lambda: _SbStub(data=[{"id": "bl-antigo"}]))
    reason = worker._template_dedup_guardrail("L1", "utilidade_22_04_2026_16_40")
    assert reason and "utilidade_22_04_2026_16_40" in reason


def test_dedup_guardrail_libera_template_inedito(monkeypatch):
    from app.broadcast import worker
    monkeypatch.setattr(worker, "get_supabase", lambda: _SbStub(data=[]))
    assert worker._template_dedup_guardrail("L1", "utilidade_22_04_2026_16_40") is None


def test_dedup_guardrail_fail_open_em_erro(monkeypatch):
    from app.broadcast import worker
    monkeypatch.setattr(worker, "get_supabase", lambda: _SbStub(raise_exc=RuntimeError("db down")))
    assert worker._template_dedup_guardrail("L1", "t") is None


class _RecordingSbStub:
    """Stub encadeável que GRAVA a cadeia de filtros emitida — necessário para
    afirmar a FORMA da query do dedup (o furo delivered/read era invisível ao
    _SbStub opaco, que aceita qualquer cadeia)."""

    def __init__(self, data=None):
        self._data = data or []
        self.calls: list[tuple] = []

    def table(self, name):
        self.calls.append(("table", name))
        return self

    def select(self, *a, **k):
        self.calls.append(("select",) + a)
        return self

    def eq(self, col, val):
        self.calls.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.calls.append(("in", col, list(vals)))
        return self

    def gte(self, col, val):
        self.calls.append(("gte", col, val))
        return self

    def limit(self, n):
        self.calls.append(("limit", n))
        return self

    def execute(self):
        result = MagicMock()
        result.data = self._data
        return result


def test_dedup_guardrail_cobre_status_delivered_e_read(monkeypatch):
    """Caso Daniel, parte 2 (go/no-go 11/07): o webhook promove broadcast_leads de
    'sent' para 'delivered' — um lead com entrega CONFIRMADA escapava do dedup de
    14 dias (filtro .eq status='sent'). A query deve cobrir o ciclo de vida
    inteiro do envio bem-sucedido: status IN ('sent','delivered','read')."""
    from app.broadcast import worker
    stub = _RecordingSbStub(data=[{"id": "bl-entregue"}])
    monkeypatch.setattr(worker, "get_supabase", lambda: stub)

    reason = worker._template_dedup_guardrail("L1", "utilidade_22_04_2026_16_40")

    assert reason and "utilidade_22_04_2026_16_40" in reason
    assert ("in", "status", ["sent", "delivered", "read"]) in stub.calls
    assert ("eq", "status", "sent") not in stub.calls
