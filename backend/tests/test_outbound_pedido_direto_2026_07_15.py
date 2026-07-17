"""Aderência das correções de roteamento outbound (auditoria 15/07).

- LEI 5 (caso Francine): pedido direto se atende ANTES de qualificar.
- LEI 1 reforçada (caso Hueiner): proibido AFIRMAR recompra sem lastro.
- Regra de escalonamento de reclamação humana (caso Aislan) no BASE_STATIC + tool.
"""
import pytest

from app.agent.prompts import PROMPT_REGISTRY
from app.agent.prompts.base import BASE_STATIC
from app.agent.prompts.valeria_outbound.playbook import POSTURA_HUNTER

OUTBOUND_STAGES = ["secretaria", "atacado", "private_label", "exportacao", "consumo"]


# --- LEI 5: pedido direto se atende primeiro (Francine) ----------------------

def test_lei5_declarada_no_playbook():
    low = POSTURA_HUNTER.lower()
    assert "pedido direto se atende primeiro" in low
    assert "atenda o pedido no mesmo turno" in low
    assert "manda a tabela" in low  # exemplo canônico do caso Francine


@pytest.mark.parametrize("stage", OUTBOUND_STAGES)
def test_lei5_presente_em_todo_estagio_outbound(stage):
    assert "pedido direto se atende primeiro" in PROMPT_REGISTRY["valeria_outbound"][stage].lower()


@pytest.mark.parametrize("stage", OUTBOUND_STAGES)
def test_lei5_nao_vaza_para_o_inbound(stage):
    assert "pedido direto se atende primeiro" not in PROMPT_REGISTRY["valeria_inbound"][stage].lower()


def test_lei2_fecho_ativo_preservado():
    """LEI 5 não pode revogar a LEI 2 — o fecho com pergunta investigativa continua."""
    low = POSTURA_HUNTER.lower()
    assert "postura ativa" in low
    assert "pergunta investigativa" in low


# --- LEI 1 reforçada: anti-presunção (Hueiner) -------------------------------

def test_lei1_proibe_afirmar_recompra_sem_lastro():
    low = POSTURA_HUNTER.lower()
    assert "voce ja compra da gente" in low   # exemplo banido literal
    assert "pergunta, nunca afirmacao" in low


# --- Escalonamento de reclamação humana (Aislan) -----------------------------

def test_base_prompt_tem_regra_de_escalonamento():
    assert "escalar_reclamacao" in BASE_STATIC
    assert "RECLAMACAO SOBRE ATENDIMENTO HUMANO" in BASE_STATIC
    # distinção explícita da reclamação de robô (que segue encaminhar_humano)
    assert "encaminhar_humano (handoff normal)" in BASE_STATIC


def test_tool_escalar_reclamacao_oferecida_nos_stages_b2b():
    from app.agent.tools import REGISTRY
    tool = REGISTRY.get("escalar_reclamacao")
    assert tool is not None
    # Todos os stages menos consumo (B2C nunca faz handoff).
    for st in ("secretaria", "atacado", "private_label", "exportacao"):
        assert tool.name in [t.name for t in REGISTRY.tools_for_stage(st)], (
            f"escalar_reclamacao não ofertada no stage {st}"
        )
    assert tool.name not in [t.name for t in REGISTRY.tools_for_stage("consumo")]
