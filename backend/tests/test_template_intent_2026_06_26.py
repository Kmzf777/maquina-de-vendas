"""Registro de Intenção de Template — classifica disparos como frio (recuperação),
quente (landing page) ou genérico. Fonte única de verdade para resolução de persona
(Eixo 1), contexto de 1º turno (Eixo 2c) e fallback de janela (Eixo 3B).
"""
from app.templates.intent import (
    classify_template_intent,
    WARM_LP,
    COLD_REACTIVATION,
    GENERIC,
)


def test_lp_templates_sao_warm():
    assert classify_template_intent("lp_solicitacao_recebida") == WARM_LP
    assert classify_template_intent("lp_cadastro_registrado") == WARM_LP
    assert classify_template_intent("lp_confirmacao_pendente") == WARM_LP


def test_cadastro_e_reativacao_sao_cold():
    assert classify_template_intent("atualizacao_cadastro_informacoes") == COLD_REACTIVATION
    assert classify_template_intent("atualizacao_interna_registros") == COLD_REACTIVATION
    assert classify_template_intent("reativar_atendimento_errado") == COLD_REACTIVATION
    assert classify_template_intent("template_utility_oficial_reativacao") == COLD_REACTIVATION


def test_templates_de_continuacao_nao_sao_cold():
    # Reabertura de janela é continuação morna de um lead JÁ engajado — não pode
    # disparar a persona de recuperação fria.
    assert classify_template_intent("continuar_conversa") == GENERIC
    assert classify_template_intent("retorno_de_solicitacao") == GENERIC
    assert classify_template_intent("continuidade_cotacao_pendente") == GENERIC


def test_vazio_e_desconhecido_default_generic():
    assert classify_template_intent(None) == GENERIC
    assert classify_template_intent("") == GENERIC
    assert classify_template_intent("   ") == GENERIC
    assert classify_template_intent("hello_world") == GENERIC


def test_case_insensitive():
    assert classify_template_intent("LP_Solicitacao_Recebida") == WARM_LP
    assert classify_template_intent("Atualizacao_Cadastro_Informacoes") == COLD_REACTIVATION
