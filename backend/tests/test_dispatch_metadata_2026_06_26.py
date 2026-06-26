"""Eixo 2a — metadados de disparo gravados em messages.metadata.dispatch.

A resolução de persona (Eixo 1) lê metadata.dispatch.intent para saber se um disparo
broadcast/followup é frio (cold_reactivation) ou quente. dispatch_metadata() é a fábrica
única desse bloco.
"""
from app.templates.intent import dispatch_metadata


def test_dispatch_metadata_cold():
    md = dispatch_metadata("atualizacao_cadastro_informacoes")
    assert md["dispatch"]["template"] == "atualizacao_cadastro_informacoes"
    assert md["dispatch"]["intent"] == "cold_reactivation"


def test_dispatch_metadata_warm_lp():
    md = dispatch_metadata("lp_solicitacao_recebida")
    assert md["dispatch"]["intent"] == "warm_lp"


def test_dispatch_metadata_generic():
    md = dispatch_metadata("continuar_conversa")
    assert md["dispatch"]["intent"] == "generic"


def test_leads_save_message_aceita_metadata(monkeypatch):
    from app.leads import service

    inserted = {}

    class _Tbl:
        def insert(self, payload):
            inserted.update(payload)
            return self

        def update(self, *a, **k):
            return self

        def eq(self, *a, **k):
            return self

        def execute(self):
            from unittest.mock import MagicMock
            return MagicMock(data=[{"id": "m1"}])

    from unittest.mock import MagicMock
    monkeypatch.setattr(service, "get_supabase", lambda: MagicMock(table=lambda n: _Tbl()))

    service.save_message(
        lead_id="l1", role="assistant", content="oi",
        conversation_id="c1", sent_by="broadcast",
        metadata={"dispatch": {"template": "x", "intent": "cold_reactivation"}},
    )
    assert inserted.get("metadata", {}).get("dispatch", {}).get("intent") == "cold_reactivation"
