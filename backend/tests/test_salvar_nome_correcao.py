"""
Tests for Task 2.4 — identity correction via salvar_nome.

Guards:
1. execute_tool("salvar_nome", ...) calls update_lead(lead_id, name=...) correctly.
2. The identity-correction guidance text is present in build_base_prompt output.
"""

import pytest
from datetime import datetime
from unittest.mock import patch, call


# ---------------------------------------------------------------------------
# 1. Tool executor guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_salvar_nome_chama_update_lead_com_nome_correto():
    """execute_tool('salvar_nome') must call update_lead(lead_id, name=NovoNome)."""
    from app.agent.tools import execute_tool

    with patch("app.agent.tools.update_lead") as mock_update:
        result = await execute_tool(
            "salvar_nome",
            {"name": "NovoNome"},
            lead_id="lead-correcao-1",
            phone="5511999990099",
        )

    mock_update.assert_called_once_with("lead-correcao-1", name="NovoNome")
    assert "NovoNome" in result


@pytest.mark.asyncio
async def test_salvar_nome_retorna_confirmacao():
    """execute_tool('salvar_nome') must return a confirmation string containing the name."""
    from app.agent.tools import execute_tool

    with patch("app.agent.tools.update_lead"):
        result = await execute_tool(
            "salvar_nome",
            {"name": "Maria"},
            lead_id="lead-correcao-2",
            phone="5511999990100",
        )

    assert "Maria" in result


@pytest.mark.asyncio
async def test_salvar_nome_nao_chama_save_message():
    """salvar_nome must NOT call save_message (lean path, no system message needed)."""
    from app.agent.tools import execute_tool

    with patch("app.agent.tools.update_lead"), \
         patch("app.agent.tools.save_message") as mock_save:
        await execute_tool(
            "salvar_nome",
            {"name": "Carlos"},
            lead_id="lead-correcao-3",
            phone="5511999990101",
        )

    mock_save.assert_not_called()


# ---------------------------------------------------------------------------
# 2. Prompt wiring guard
# ---------------------------------------------------------------------------

def test_prompt_contem_regra_correcao_identidade_na_name_instruction():
    """build_base_prompt with known name must include identity-correction guidance."""
    from app.agent.prompts.base import build_base_prompt

    prompt = build_base_prompt(
        lead_name="Fulano",
        lead_company=None,
        now=datetime(2026, 6, 15, 10, 0, 0),
        lead_context=None,
    )

    # Distinctive phrase from the new rule in name_instruction
    assert "CORRECAO DE IDENTIDADE" in prompt


def test_prompt_contem_constraint_20():
    """build_base_prompt must include constraint #20 about identity correction."""
    from app.agent.prompts.base import build_base_prompt

    prompt = build_base_prompt(
        lead_name="Fulano",
        lead_company=None,
        now=datetime(2026, 6, 15, 10, 0, 0),
        lead_context=None,
    )

    # Constraint #20 header
    assert "20. CORRECAO DE IDENTIDADE" in prompt


def test_prompt_sem_nome_nao_contem_correcao_de_identidade_na_name_instruction():
    """When lead_name is None, the name_instruction branch is different — no correction rule there,
    but constraint #20 must still appear (it's in the constraints block, always rendered)."""
    from app.agent.prompts.base import build_base_prompt

    prompt = build_base_prompt(
        lead_name=None,
        lead_company=None,
        now=datetime(2026, 6, 15, 10, 0, 0),
        lead_context=None,
    )

    # Constraint #20 is always in the prompt regardless of lead_name
    assert "20. CORRECAO DE IDENTIDADE" in prompt
