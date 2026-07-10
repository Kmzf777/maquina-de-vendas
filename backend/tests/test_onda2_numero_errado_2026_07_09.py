"""TDD Onda 2: ponta morta do número errado (marcador na tool + higiene 72h no worker).

Auditoria 08/07 (caso Magda): número que mudou de dono fica pendurado no funil para
sempre — a Valéria abre a porta de re-engajamento, ninguém responde, e o lead segue
"vivo" na base, elegível a novos disparos. Contrato: o frame NUMERO ERRADO chama
`registrar_numero_errado` (marca `metadata.wrong_number_at`); o worker varre os
marcados — quem respondeu depois do marcador volta ao fluxo (marcador limpo); quem
ficou 72h mudo vira opt-out com nota analítica (nunca mais recebe disparo).
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.agent.tools as tools
import app.broadcast.worker as W


# ---------------------------------------------------------------------------
# Tool registrar_numero_errado
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_marca_wrong_number_at():
    with patch.object(tools, "get_lead", return_value={"id": "lead-1", "metadata": {}}), \
         patch.object(tools, "update_lead") as m_upd, \
         patch.object(tools, "save_message") as m_save:
        result = await tools.execute_tool(
            "registrar_numero_errado",
            {"contexto": "clicou Nao e disse 'nao conheco essa pessoa'"},
            lead_id="lead-1", phone="5567999295671", conversation_id="conv-1",
        )

    meta = m_upd.call_args.kwargs.get("metadata") or {}
    assert meta.get("wrong_number_at")
    # marcador em UTC ISO — o job compara com now(UTC)
    datetime.fromisoformat(meta["wrong_number_at"])
    assert "nao conheco" in meta.get("wrong_number_context", "")
    m_save.assert_called_once()
    assert "[registrar_numero_errado]" in m_save.call_args.args[2]
    assert "72h" in result


@pytest.mark.asyncio
async def test_tool_idempotente_quando_ja_marcado():
    """Re-execução da tool no MESMO lead (retry do agente — visto 4x no incidente
    thought_signature de 09/07) não duplica marcador nem system message."""
    with patch.object(tools, "get_lead", return_value={
            "id": "lead-1", "metadata": {"wrong_number_at": "2026-07-09T20:03:00+00:00"}}),          patch.object(tools, "update_lead") as m_upd,          patch.object(tools, "save_message") as m_save:
        result = await tools.execute_tool(
            "registrar_numero_errado", {"contexto": "disse Nao de novo"},
            lead_id="lead-1", phone="5527981691402", conversation_id="conv-1",
        )
    m_upd.assert_not_called()
    m_save.assert_not_called()
    assert "ja marcado" in result or "já marcado" in result


def test_tool_disponivel_na_secretaria():
    names = [t["name"] for t in tools.get_tools_for_stage("secretaria")]
    assert "registrar_numero_errado" in names


# ---------------------------------------------------------------------------
# Job process_wrong_number_deadends (worker)
# ---------------------------------------------------------------------------

def _lead_row(marked_hours_ago, last_reply_hours_ago=None, lead_id="lead-wn-1"):
    now = datetime.now(timezone.utc)
    marked = (now - timedelta(hours=marked_hours_ago)).isoformat()
    row = {
        "id": lead_id, "phone": "5567999295671", "opt_out": False,
        "metadata": {"wrong_number_at": marked, "wrong_number_context": "nao conheco"},
        "last_customer_message_at": (
            (now - timedelta(hours=last_reply_hours_ago)).isoformat()
            if last_reply_hours_ago is not None else None
        ),
    }
    return row


def _sb_with(rows):
    sb = MagicMock()
    res = MagicMock()
    res.data = rows
    sb.table.return_value.select.return_value.filter.return_value.eq.return_value.limit.return_value.execute.return_value = res
    return sb


def test_deadend_72h_vira_optout():
    row = _lead_row(marked_hours_ago=80)
    with patch.object(W, "get_supabase", return_value=_sb_with([row])), \
         patch.object(W, "apply_optout_side_effects") as m_opt, \
         patch.object(W, "append_lead_observation") as m_note, \
         patch.object(W, "update_lead") as m_upd:
        n = W.process_wrong_number_deadends()

    assert n == 1
    m_opt.assert_called_once_with("lead-wn-1")
    assert "ponta morta" in m_note.call_args.args[1].lower()


def test_lead_que_respondeu_depois_volta_ao_fluxo():
    """Resposta humana DEPOIS do marcador → limpa o marcador, sem opt-out."""
    row = _lead_row(marked_hours_ago=80, last_reply_hours_ago=2)
    with patch.object(W, "get_supabase", return_value=_sb_with([row])), \
         patch.object(W, "apply_optout_side_effects") as m_opt, \
         patch.object(W, "update_lead") as m_upd:
        n = W.process_wrong_number_deadends()

    assert n == 0
    m_opt.assert_not_called()
    meta = m_upd.call_args.kwargs.get("metadata") or {}
    assert "wrong_number_at" not in meta


def test_dentro_da_janela_no_op():
    row = _lead_row(marked_hours_ago=10)
    with patch.object(W, "get_supabase", return_value=_sb_with([row])), \
         patch.object(W, "apply_optout_side_effects") as m_opt, \
         patch.object(W, "update_lead") as m_upd:
        n = W.process_wrong_number_deadends()

    assert n == 0
    m_opt.assert_not_called()
    m_upd.assert_not_called()


def test_erro_de_db_fail_soft():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("db down")
    with patch.object(W, "get_supabase", return_value=sb):
        assert W.process_wrong_number_deadends() == 0
