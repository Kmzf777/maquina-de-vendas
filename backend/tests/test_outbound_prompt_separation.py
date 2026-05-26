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


# ---------------------------------------------------------------------------
# Task 2 — secretaria.py outbound não contém mais conteúdo transitório
# ---------------------------------------------------------------------------

def test_secretaria_outbound_sem_bloco_transitorio():
    """SECRETARIA_PROMPT outbound não deve mais conter o bloco 'CONTEXTO DESTA ABORDAGEM'."""
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT

    assert "CONTEXTO DESTA ABORDAGEM" not in SECRETARIA_PROMPT
    assert "Voce iniciou este contato via campanha de WhatsApp. A mensagem que voce enviou foi" not in SECRETARIA_PROMPT
    assert "O lead esta RESPONDENDO a essa mensagem agora" not in SECRETARIA_PROMPT


def test_secretaria_outbound_mantem_regras_de_negocio():
    """As regras de negócio e o funil devem permanecer no prompt."""
    from app.agent.prompts.valeria_outbound.secretaria import SECRETARIA_PROMPT

    assert "CONTEXTO OUTBOUND" in SECRETARIA_PROMPT
    assert "POSTURA OUTBOUND" in SECRETARIA_PROMPT
    assert "REGRAS CRITICAS DE SEGURANCA" in SECRETARIA_PROMPT
    assert "ETAPA 1" in SECRETARIA_PROMPT
    assert "ETAPA 4" in SECRETARIA_PROMPT
