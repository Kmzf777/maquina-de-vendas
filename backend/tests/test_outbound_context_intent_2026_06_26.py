"""Eixo 2c — Contexto de 1º turno outbound ciente da intenção do disparo.

O frame frio hardcoded ("estamos atualizando seu cadastro") era aplicado a TODO template,
inclusive aos quentes de landing page (lp_*). Agora o frame muda conforme a intenção e
injeta o pedido real da LP (lp_message).
"""
from app.agent.prompts.valeria_outbound.context import build_outbound_first_turn_context


def test_warm_lp_usa_frame_quente_e_injeta_pedido():
    ctx = build_outbound_first_turn_context(
        "corpo do template", "Pedro",
        template_intent="warm_lp",
        lp_message="quero café cru pra exportar pra Portugal",
    )
    low = ctx.lower()
    assert "landing page" in low or "pediu" in low or "solicit" in low
    assert "quero café cru pra exportar pra Portugal" in ctx
    # não usa o frame frio: o marcador exclusivo do frame de cadastro é a "ABERTURA FIXA do template"
    assert "abertura fixa do template" not in low


def test_cold_reactivation_mantem_frame_de_cadastro():
    ctx = build_outbound_first_turn_context(
        "corpo", "Pedro", template_intent="cold_reactivation"
    )
    assert "cadastro" in ctx.lower()


def test_chamada_antiga_sem_intent_e_retrocompativel():
    # Assinatura antiga (sem template_intent) continua válida → frame de cadastro
    ctx = build_outbound_first_turn_context("corpo", "Pedro")
    assert "cadastro" in ctx.lower()
