"""Cancelamento de follow-ups no ENCERRAMENTO — auditoria do lead 5561984336980, 2026-06-24.

Contexto: o Daniel disse "Já converso com um humano da sua empresa" (Regra 27 — cliente já
conectado ao time). A Valéria encerrou cordialmente, mas NENHUMA ferramenta de
encerramento cancelava os follow-ups → o job seq=1 disparou um meta-comentário.

Lacunas cobertas aqui:
  (3a) encaminhar_humano deve cancelar follow-ups standard pendentes (handoff encerra o bot).
  (3b) adicionar_tag_lead com "Já é Cliente" / "Pediu Humano" (equivalente da Regra 27)
       deve cancelar follow-ups standard pendentes — sem marcar perdido, sem desligar IA.
"""
import pytest
from unittest.mock import patch, AsyncMock


# --- (3a) encaminhar_humano cancela follow-ups standard --------------------

@pytest.mark.asyncio
async def test_encaminhar_humano_cancela_followups():
    from app.agent import tools

    with patch.object(tools, "update_lead"), \
         patch.object(tools, "get_lead", return_value={"id": "L1", "stage": "atacado", "name": "Daniel"}), \
         patch.object(tools, "move_deal_to_vendor_pipeline", return_value=True), \
         patch.object(tools, "get_channel_for_lead", return_value=None), \
         patch.object(tools, "cancel_followups_by_phone") as mock_cancel, \
         patch.object(tools, "save_message"), \
         patch.object(tools, "append_lead_observation"):
        await tools.execute_tool(
            "encaminhar_humano",
            {"vendedor": "João Bras", "motivo": "lead qualificado"},
            "L1", "5561984336980", "conv-1",
        )

    mock_cancel.assert_called_once()
    assert mock_cancel.call_args.args[0] == "5561984336980"


# --- (3b) tags de encerramento cancelam follow-ups (equivalente da Regra 27) -

@pytest.mark.asyncio
@pytest.mark.parametrize("tag", ["Já é Cliente", "Pediu Humano"])
async def test_tag_de_encerramento_cancela_followups(tag):
    from app.agent import tools

    with patch.object(tools, "add_tags_to_lead", return_value=[tag]), \
         patch.object(tools, "cancel_followups_by_phone") as mock_cancel:
        await tools.execute_tool(
            "adicionar_tag_lead", {"tags": [tag]}, "L1", "5561984336980", "conv-1",
        )

    mock_cancel.assert_called_once()
    assert mock_cancel.call_args.args[0] == "5561984336980"


def test_regra27_instrui_tag_de_encerramento():
    """Regra 27 deve mandar aplicar a tag 'Já é Cliente'/'Pediu Humano' — é o gancho
    que dispara o cancelamento dos follow-ups no encerramento (cliente já conectado)."""
    from datetime import datetime
    from app.agent.prompts.base import build_base_prompt
    s = build_base_prompt(None, None, datetime(2026, 6, 24, 14, 0))
    assert "Já é Cliente" in s
    # A própria regra 27 (não só a 28) precisa amarrar a tag ao encerramento dos follow-ups.
    bloco = s.split("CLIENTE JA CONECTADO AO TIME", 1)[1][:900]
    assert "Já é Cliente" in bloco or "adicionar_tag_lead" in bloco


@pytest.mark.asyncio
async def test_tag_comum_nao_cancela_followups():
    """Tags de inteligência (B2B etc.) NÃO mexem no ciclo de follow-up."""
    from app.agent import tools

    with patch.object(tools, "add_tags_to_lead", return_value=["B2B"]), \
         patch.object(tools, "cancel_followups_by_phone") as mock_cancel:
        await tools.execute_tool(
            "adicionar_tag_lead", {"tags": ["B2B"]}, "L1", "5561984336980", "conv-1",
        )

    mock_cancel.assert_not_called()
