"""Deep module de Handoff (refatoração de arquitetura 12/07 — Card 2).

O comportamento de handoff vivia espalhado por 5 arquivos acoplados pela string
HANDOFF_RESULT_PREFIX: emitida em tools.py, detectada 2x no orchestrator (loop
principal + retry) e casada por LIKE no watchdog. Este módulo (app/agent/handoff.py)
passa a ser o ÚNICO dono do vocabulário e da detecção.

Contratos que NÃO podem mudar (dados persistidos + QA em produção):
  - HANDOFF_RESULT_PREFIX  == "Lead encaminhado para "  (byte-idêntico)
  - marcador de system message == "[encaminhar_humano] Lead encaminhado para <v>: <motivo>"
  - LIKE do daily QA       == "[encaminhar_humano] Lead encaminhado%"  (byte-idêntico —
    o LIKE amplo dobrava a contagem, lição do relatório de 10/07)
"""

import pytest


# ── vocabulário: strings derivadas de UMA base ──────────────────────────────

def test_prefix_byte_identico_ao_contrato_persistido():
    from app.agent.handoff import HANDOFF_RESULT_PREFIX
    assert HANDOFF_RESULT_PREFIX == "Lead encaminhado para "


def test_handoff_result_formato():
    from app.agent.handoff import handoff_result
    assert handoff_result("João Brás") == "Lead encaminhado para João Brás"


def test_handoff_system_marker_formato():
    from app.agent.handoff import handoff_system_marker
    assert handoff_system_marker("João Brás", "quer preço de atacado") == (
        "[encaminhar_humano] Lead encaminhado para João Brás: quer preço de atacado"
    )


def test_qa_like_byte_identico_ao_watchdog_atual():
    from app.agent.handoff import QA_HANDOFF_MARKER_LIKE
    assert QA_HANDOFF_MARKER_LIKE == "[encaminhar_humano] Lead encaminhado%"


def test_marker_persistido_casa_com_o_like_do_qa():
    """Todo marcador emitido deve ser capturado pelo LIKE do daily QA."""
    from app.agent.handoff import QA_HANDOFF_MARKER_LIKE, handoff_system_marker
    marker = handoff_system_marker("João Brás", "motivo qualquer")
    assert marker.startswith(QA_HANDOFF_MARKER_LIKE.rstrip("%"))


# ── detecção única (fix S1 11/07: nome explícito OU cascata via prefixo) ────

def test_is_handoff_por_nome_explicito():
    from app.agent.handoff import is_handoff
    assert is_handoff("encaminhar_humano", "qualquer resultado") is True


def test_is_handoff_por_cascata_via_prefixo():
    """qualificar_lead chama encaminhar_humano por dentro e propaga o retorno."""
    from app.agent.handoff import handoff_result, is_handoff
    assert is_handoff("qualificar_lead", handoff_result("João Brás")) is True


def test_is_handoff_false_para_tool_comum():
    from app.agent.handoff import is_handoff
    assert is_handoff("qualificar_lead", "lead qualificado com sucesso") is False


def test_is_handoff_false_para_resultado_nao_string():
    from app.agent.handoff import is_handoff
    assert is_handoff("salvar_nome", None) is False


# ── guarda de handoff verbalizado migrada para o módulo ─────────────────────

def test_looks_like_handoff_announcement_cta_real():
    from app.agent.handoff import looks_like_handoff_announcement
    assert looks_like_handoff_announcement("perfeito! vou te conectar com o João agora") is True


def test_looks_like_handoff_announcement_mencao_informacional():
    from app.agent.handoff import looks_like_handoff_announcement
    assert looks_like_handoff_announcement("quem prepara isso é o Joao Bras") is False


# ── retrocompatibilidade: call sites antigos continuam importáveis ──────────

def test_tools_reexporta_o_mesmo_prefixo():
    from app.agent.handoff import HANDOFF_RESULT_PREFIX as novo
    from app.agent.tools import HANDOFF_RESULT_PREFIX as legado
    assert legado is novo


def test_orchestrator_alias_aponta_para_o_modulo():
    from app.agent.handoff import looks_like_handoff_announcement
    from app.agent.orchestrator import _looks_like_handoff_announcement
    assert _looks_like_handoff_announcement is looks_like_handoff_announcement
