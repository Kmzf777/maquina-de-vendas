"""TDD — 2026-06-30: ai_scheduled_return deve sobreviver ao sweep de cancelamento.

Contexto forense: 100% dos jobs ai_scheduled_return em produção terminaram
status=cancelled / cancel_reason='rescheduled' e ZERO dispararam. Causa-raiz:
schedule_followup, cancel_followups e cancel_followups_by_phone só excluíam
'handoff_rescue' (e 'lp_welcome' no schedule_followup) do sweep — ai_scheduled_return
era varrido junto.

Estes testes verificam que, em cada uma das três funções, o filtro de cancelamento
exclui AMBOS 'handoff_rescue' E 'ai_scheduled_return'.
"""
import pytest


# ---------------------------------------------------------------------------
# Infraestrutura de captura de chamadas à chain do Supabase
# ---------------------------------------------------------------------------

class _NotAccessor:
    """Representa o objeto retornado por `chain.not_` — captura `.in_()` chamado a seguir."""
    def __init__(self, record: list):
        self._record = record

    def in_(self, field: str, values):
        self._record.append((field, list(values)))
        return _EndChain()


class _EndChain:
    """Ponta do chain após not_.in_() — apenas implementa execute()."""
    def execute(self):
        return type("R", (), {"data": []})()


class _BaseChain:
    """Chain genérico que delega tudo a si mesmo e captura not_.in_ via _NotAccessor."""

    def __init__(self, not_in_record: list, tbl: str = ""):
        self._not_in_record = not_in_record
        self._tbl = tbl

    @property
    def not_(self):
        return _NotAccessor(self._not_in_record)

    # métodos comuns de query — todos retornam self para encadeamento
    def select(self, *a, **k): return self
    def eq(self, *a, **k): return self
    def neq(self, *a, **k): return self           # usado pelo código OLD — NÃO registra nada
    def limit(self, *a, **k): return self
    def in_(self, *a, **k): return self           # in_ sem not_ (ex: .in_("conversation_id", ...))
    def gte(self, *a, **k): return self
    def lt(self, *a, **k): return self
    def order(self, *a, **k): return self
    def update(self, *a, **k): return self
    def insert(self, *a, **k): return self

    def execute(self):
        # Adapta data conforme o tipo de tabela consultada
        if self._tbl == "conversations":
            return type("R", (), {"data": [{"id": "conv-1"}]})()
        if self._tbl == "leads":
            return type("R", (), {"data": [{"id": "lead-1"}]})()
        # follow_up_jobs e outros: lista vazia é suficiente
        return type("R", (), {"data": []})()


# ---------------------------------------------------------------------------
# 1. cancel_followups
# ---------------------------------------------------------------------------

def test_cancel_followups_excludes_ai_scheduled_return(monkeypatch):
    """cancel_followups deve usar not_.in_ excluindo tanto 'handoff_rescue' quanto
    'ai_scheduled_return', em vez de neq('job_type', 'handoff_rescue').
    """
    from app.follow_up import service

    not_in_calls: list = []

    class _SB:
        def table(self, name):
            return _BaseChain(not_in_calls, name)

    monkeypatch.setattr(service, "get_supabase", lambda: _SB())
    service.cancel_followups("conv-1", "replied")

    assert len(not_in_calls) == 1, (
        "Esperava exatamente 1 chamada a not_.in_() em cancel_followups, "
        f"mas houve {len(not_in_calls)}. "
        "Código ainda pode estar usando neq() em vez de not_.in_()."
    )
    field, values = not_in_calls[0]
    assert field == "job_type", f"Filtro aplicado ao campo errado: {field!r}"
    assert "handoff_rescue" in values, "'handoff_rescue' deve continuar excluído"
    assert "ai_scheduled_return" in values, (
        "'ai_scheduled_return' não está excluído do cancelamento em cancel_followups"
    )


# ---------------------------------------------------------------------------
# 2. cancel_followups_by_phone
# ---------------------------------------------------------------------------

def test_cancel_followups_by_phone_excludes_ai_scheduled_return(monkeypatch):
    """cancel_followups_by_phone deve usar not_.in_ excluindo 'handoff_rescue' E
    'ai_scheduled_return'.
    """
    from app.follow_up import service

    not_in_calls: list = []

    class _SB:
        def table(self, name):
            return _BaseChain(not_in_calls, name)

    monkeypatch.setattr(service, "get_supabase", lambda: _SB())
    service.cancel_followups_by_phone("+5511999999999", "optout")

    assert len(not_in_calls) == 1, (
        "Esperava exatamente 1 chamada a not_.in_() em cancel_followups_by_phone, "
        f"mas houve {len(not_in_calls)}. "
        "Código ainda pode estar usando neq() em vez de not_.in_()."
    )
    field, values = not_in_calls[0]
    assert field == "job_type", f"Filtro aplicado ao campo errado: {field!r}"
    assert "handoff_rescue" in values, "'handoff_rescue' deve continuar excluído"
    assert "ai_scheduled_return" in values, (
        "'ai_scheduled_return' não está excluído do cancelamento em cancel_followups_by_phone"
    )


# ---------------------------------------------------------------------------
# 3. schedule_followup (o cancel interno — não o insert)
# ---------------------------------------------------------------------------

def test_schedule_followup_excludes_ai_scheduled_return(monkeypatch):
    """O bloco de cancelamento de idempotência em schedule_followup deve excluir
    'ai_scheduled_return' além de 'handoff_rescue' e 'lp_welcome'.
    """
    from app.follow_up import service

    not_in_calls: list = []

    class _SB:
        def table(self, name):
            return _BaseChain(not_in_calls, name)

    monkeypatch.setattr(service, "get_supabase", lambda: _SB())
    # Evita que _already_touched_today tente consultar o banco (é patched abaixo)
    monkeypatch.setattr(service, "_already_touched_today", lambda conv_id, now: False)

    service.schedule_followup("conv-1", "lead-1", "chan-1")

    # Deve haver exatamente 1 chamada a not_.in_ — o sweep de cancelamento de pending
    assert len(not_in_calls) == 1, (
        "Esperava exatamente 1 chamada a not_.in_() no sweep de cancel em schedule_followup, "
        f"mas houve {len(not_in_calls)}."
    )
    field, values = not_in_calls[0]
    assert field == "job_type", f"Filtro aplicado ao campo errado: {field!r}"
    assert "handoff_rescue" in values, "'handoff_rescue' deve continuar excluído"
    assert "lp_welcome" in values, "'lp_welcome' deve continuar excluído"
    assert "ai_scheduled_return" in values, (
        "'ai_scheduled_return' não está excluído do sweep em schedule_followup"
    )
