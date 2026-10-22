"""Contrato Onda 0 (b67f1c6b): evento lead_events 'qualificado' e o gancho no repasse."""
from unittest.mock import MagicMock, patch

import pytest

from app.leads import qualificado as q
from app.leads import repasse


def _sb_ok():
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])
    return sb


# ------------------------------------------------------------------ motivo_qualifica

def test_motivo_qualifica():
    assert q.motivo_qualifica("handoff proativo — âncoras") is True
    assert q.motivo_qualifica("IA temporariamente indisponível (fallback)") is False
    assert q.motivo_qualifica("Bot de recuperação: lead respondeu") is False
    assert q.motivo_qualifica("escalonamento por reclamação") is False
    assert q.motivo_qualifica(None) is True


def test_motivos_iguais_aos_de_conversions():
    from app.conversions import eligibility
    assert q.MOTIVOS_EXCLUIDOS == eligibility._MOTIVOS_EXCLUIDOS


# ------------------------------------------------------------- registrar_qualificado

def test_registrar_qualificado_insert(monkeypatch):
    sb = _sb_ok()
    monkeypatch.setattr(q, "get_supabase", lambda: sb)
    ok = q.registrar_qualificado(lead_id="L", criterio="repasse", source="ia",
                                 occurred_at="2026-10-22T10:00:00-03:00", segmento="atacado",
                                 b2b=True, motivo="lead qualificado", vendedor_id="U1")
    assert ok is True
    sb.table.assert_called_once_with("lead_events")
    ev = sb.table.return_value.insert.call_args.args[0]
    assert ev["lead_id"] == "L"
    assert ev["event_type"] == "qualificado"
    assert ev["dedupe_key"] == "qualificado:L"
    assert ev["source"] == "ia"
    assert ev["occurred_at"] == "2026-10-22T10:00:00-03:00"
    assert ev["metadata"] == {"criterio": "repasse", "segmento": "atacado", "b2b": True,
                              "motivo": "lead qualificado", "vendedor_id": "U1"}


def test_registrar_qualificado_sem_occurred_at(monkeypatch):
    sb = _sb_ok()
    monkeypatch.setattr(q, "get_supabase", lambda: sb)
    assert q.registrar_qualificado(lead_id="L", criterio="score", source="score") is True
    ev = sb.table.return_value.insert.call_args.args[0]
    assert "occurred_at" not in ev
    assert ev["metadata"] == {"criterio": "score", "segmento": None, "b2b": None,
                              "motivo": None, "vendedor_id": None}


@pytest.mark.parametrize("erro", [RuntimeError("boom"),
                                  Exception("duplicate key value violates unique constraint (23505)")])
def test_registrar_qualificado_fail_soft(monkeypatch, erro):
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = erro
    monkeypatch.setattr(q, "get_supabase", lambda: sb)
    assert q.registrar_qualificado(lead_id="L", criterio="repasse", source="ia") is False


def test_registrar_qualificado_sem_lead_nao_grava(monkeypatch):
    sb = _sb_ok()
    monkeypatch.setattr(q, "get_supabase", lambda: sb)
    assert q.registrar_qualificado(lead_id="", criterio="repasse", source="ia") is False
    sb.table.assert_not_called()


# ----------------------------------------------------------- gancho em registrar_repasse

def _repasse(**kw):
    base = dict(lead_id="L1", conversation_id="C1", message_id="M1",
                occurred_at="2026-10-22T10:00:00-03:00", source="ia", vendedor_id="U1",
                vendedor="João", segmento="atacado", motivo="lead qualificado")
    base.update(kw)
    return repasse.registrar_repasse(**base)


def test_repasse_comum_registra_qualificado(monkeypatch):
    monkeypatch.setattr(repasse, "get_supabase", lambda: _sb_ok())
    with patch("app.leads.qualificado.registrar_qualificado", return_value=True) as reg:
        assert _repasse() is True
    reg.assert_called_once_with(lead_id="L1", criterio="repasse", source="ia",
                                occurred_at="2026-10-22T10:00:00-03:00", segmento="atacado",
                                motivo="lead qualificado", vendedor_id="U1", b2b=None)


def test_repasse_sem_motivo_registra_qualificado(monkeypatch):
    monkeypatch.setattr(repasse, "get_supabase", lambda: _sb_ok())
    with patch("app.leads.qualificado.registrar_qualificado", return_value=True) as reg:
        assert _repasse(motivo=None, source="button_flow") is True
    assert reg.call_count == 1
    assert reg.call_args.kwargs["source"] == "button_flow"


def test_repasse_motivo_excluido_nao_registra(monkeypatch):
    monkeypatch.setattr(repasse, "get_supabase", lambda: _sb_ok())
    with patch("app.leads.qualificado.registrar_qualificado") as reg:
        assert _repasse(motivo="bot de recuperação") is True
    reg.assert_not_called()


def test_repasse_que_falhou_nao_registra(monkeypatch):
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.side_effect = RuntimeError("dup")
    monkeypatch.setattr(repasse, "get_supabase", lambda: sb)
    with patch("app.leads.qualificado.registrar_qualificado") as reg:
        assert _repasse() is False
    reg.assert_not_called()


def test_falha_do_qualificado_nao_muda_o_repasse(monkeypatch):
    monkeypatch.setattr(repasse, "get_supabase", lambda: _sb_ok())
    with patch("app.leads.qualificado.registrar_qualificado", return_value=False):
        assert _repasse() is True
