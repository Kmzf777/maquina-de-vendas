"""Playbook Hunter da Valeria Outbound (auditoria 13/07).

Falha real: apos o template de reativacao ("estamos atualizando nossos registros...") o lead
respondeu "Sim" e a IA fechou o turno com "como posso te ajudar hoje?" — postura de inbound,
sem ponte logica com o motivo do contato. 26% dos primeiros turnos livres do dia repetiram isso.

Estes testes travam a correcao: postura ativa + ponte de contexto nos prompts de OUTBOUND,
sem tocar no INBOUND.
"""
import pytest

from app.agent.prompts import PROMPT_REGISTRY
from app.agent.prompts.valeria_outbound.playbook import POSTURA_HUNTER
from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context

OUTBOUND_STAGES = ["secretaria", "atacado", "private_label", "exportacao", "consumo"]


@pytest.mark.parametrize("stage", OUTBOUND_STAGES)
def test_todo_estagio_outbound_carrega_o_playbook_hunter(stage):
    prompt = PROMPT_REGISTRY["valeria_outbound"][stage]
    assert POSTURA_HUNTER in prompt, f"estagio outbound '{stage}' sem a lei de postura ativa"


@pytest.mark.parametrize("stage", OUTBOUND_STAGES)
def test_estagio_outbound_proibe_o_fecho_passivo(stage):
    """A blacklist tem que estar VISIVEL no prompt do estagio (nao basta o tom)."""
    low = PROMPT_REGISTRY["valeria_outbound"][stage].lower()
    assert "como posso te ajudar" in low, "a frase banida precisa aparecer como PROIBICAO explicita"
    assert "blacklist" in low
    assert "pergunta investigativa" in low


def test_playbook_declara_ponte_de_contexto_e_motivo():
    low = POSTURA_HUNTER.lower()
    assert "ponte de contexto" in low
    assert "motivo real do contato" in low
    # origem != motivo: parar em "seu contato estava na nossa base" e proibido
    assert "origem nao e motivo" in low


def test_playbook_substitui_a_regra_26_no_outbound():
    """Regra 26 do BASE_STATIC ('pergunte no que pode ajudar HOJE') e a fonte literal do bug."""
    low = POSTURA_HUNTER.lower()
    assert "regra 26" in low
    assert "recompra" in low


def test_contexto_frio_do_primeiro_turno_exige_motivo_e_pergunta_ativa():
    ctx = build_outbound_first_turn_context(
        campaign_message="Estamos atualizando nossos registros de contato. Falo com Adriano?",
        lead_name="Adriano",
    )
    low = ctx.lower()
    assert "ponte de contexto" in low
    assert "motivo real do contato" in low
    assert "pergunta investigativa" in low
    assert "como posso te ajudar" in low  # citada como PROIBICAO
    assert "proibido fechar o turno" in low


def test_contexto_warm_lp_tambem_termina_ativo():
    ctx = build_outbound_first_turn_context(
        campaign_message="Recebemos sua solicitacao.",
        lead_name="Ana",
        template_intent="warm_lp",
        lp_message="quero preco de atacado",
    )
    low = ctx.lower()
    assert "pergunta investigativa" in low
    assert "proibido fechar com 'como posso te ajudar?'" in low


@pytest.mark.parametrize("stage", OUTBOUND_STAGES)
def test_inbound_permanece_intocado(stage):
    """O playbook e lei de outbound: nao pode vazar para o inbound (que atende quem PEDIU ajuda)."""
    assert POSTURA_HUNTER not in PROMPT_REGISTRY["valeria_inbound"][stage]


def test_regra_26_do_base_continua_valendo_para_o_inbound():
    from app.agent.prompts.base import BASE_STATIC

    assert "LEAD QUE JA E NOSSO CLIENTE" in BASE_STATIC
