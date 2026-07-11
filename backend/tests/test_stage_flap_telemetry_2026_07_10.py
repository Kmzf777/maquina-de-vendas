"""Trilha B / B2 — Anti-flapping de mudar_stage: TELEMETRIA sem bloqueio (auditoria 10/07).

Caso Nilson: private_label → atacado → private_label em ~3 min reagindo a áudios ambíguos.
Diretriz do usuário: precisão SEM engessar o funil — nada de guarda hard que bloqueie a
mudança. Só MEDIMOS: se a chamada reverte para um stage por onde já passamos nos últimos 15
min, o executor loga [STAGE FLAP] e a transição SEGUE normalmente.
"""
import asyncio
import logging
from unittest.mock import patch

from app.agent import tools


def _run(coro):
    return asyncio.run(coro)


def test_flap_dentro_da_janela_loga_warning_e_aplica_transicao(caplog):
    # Lead atualmente em 'atacado'; volta para 'private_label' (marcador recente existe).
    with patch.object(tools, "_recent_stage_marker_exists", return_value=True), \
         patch.object(tools, "get_lead", return_value={"stage": "atacado"}), \
         patch.object(tools, "get_conversation", return_value={"stage": "atacado"}), \
         patch.object(tools, "update_conversation") as m_uconv, \
         patch.object(tools, "update_lead") as m_ulead, \
         patch.object(tools, "ensure_segment_deal"), \
         patch.object(tools, "save_message") as m_save:
        with caplog.at_level(logging.WARNING):
            result = _run(tools.execute_tool(
                "mudar_stage", {"stage": "private_label"},
                lead_id="L1", phone="55", conversation_id="C1",
            ))

    assert "[STAGE FLAP]" in caplog.text
    # A transição prossegue mesmo sinalizando flap (sem bloqueio).
    assert result == "Stage alterado para: private_label"
    m_uconv.assert_called_once_with("C1", stage="private_label")
    m_ulead.assert_called_once_with("L1", stage="private_label")
    m_save.assert_called_once()


def test_primeira_mudanca_nao_loga_warning(caplog):
    with patch.object(tools, "_recent_stage_marker_exists", return_value=False), \
         patch.object(tools, "get_lead", return_value={"stage": "secretaria"}), \
         patch.object(tools, "get_conversation", return_value={"stage": "secretaria"}), \
         patch.object(tools, "update_conversation"), \
         patch.object(tools, "update_lead"), \
         patch.object(tools, "ensure_segment_deal"), \
         patch.object(tools, "save_message"):
        with caplog.at_level(logging.WARNING):
            result = _run(tools.execute_tool(
                "mudar_stage", {"stage": "atacado"},
                lead_id="L1", phone="55", conversation_id="C1",
            ))

    assert "[STAGE FLAP]" not in caplog.text
    assert result == "Stage alterado para: atacado"


def test_recent_stage_marker_fail_open_false():
    # Sem conversation_id → False sem tocar o banco (telemetria nunca bloqueia).
    assert tools._recent_stage_marker_exists("", "atacado") is False
