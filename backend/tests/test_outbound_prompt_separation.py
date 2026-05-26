import pytest


# ---------------------------------------------------------------------------
# Task 1 — build_outbound_first_turn_context
# ---------------------------------------------------------------------------

def test_context_builder_com_nome_e_campanha():
    """Deve incluir campaign_message, nome do lead e aviso de que está respondendo."""
    from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context

    result = build_outbound_first_turn_context(
        campaign_message="Ola, aqui e a Valeria da Cafe Canastra.",
        lead_name="Joao",
    )

    assert "Ola, aqui e a Valeria da Cafe Canastra." in result
    assert "O lead se chama Joao" in result
    assert "O lead está respondendo" in result


def test_context_builder_sem_nome():
    """Sem lead_name, não deve incluir linha de nome mas deve manter o restante."""
    from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context

    result = build_outbound_first_turn_context(
        campaign_message="Template da campanha.",
        lead_name=None,
    )

    assert "O lead se chama" not in result
    assert "Template da campanha." in result
    assert "O lead está respondendo" in result
