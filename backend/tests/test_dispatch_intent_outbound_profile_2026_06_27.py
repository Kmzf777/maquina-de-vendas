"""Fix 1a: disparo sob a persona outbound classifica como cold_reactivation.

Caso real: broadcast DSP-FRIOS-27-06-09-30 usou o template generico
`utilidade_22_04_2026_16_40` mas foi disparado sob o agent_profile valeria_outbound.
O classificador so olhava o NOME do template (=> generic), ignorando a escolha
explicita do operador pela persona outbound. Agora a escolha outbound e autoridade.
"""
from app.templates.intent import (
    classify_template_intent,
    dispatch_metadata,
    COLD_REACTIVATION,
    WARM_LP,
    GENERIC,
)


def test_template_generico_sob_outbound_vira_cold():
    # nome generico, mas operador escolheu a persona outbound => reativacao fria
    assert classify_template_intent("utilidade_22_04_2026_16_40", "valeria_outbound") == COLD_REACTIVATION


def test_template_generico_sob_inbound_continua_generic():
    assert classify_template_intent("utilidade_22_04_2026_16_40", "valeria_inbound") == GENERIC


def test_template_generico_sem_persona_continua_generic():
    # sem informacao de persona (default), comportamento legado preservado
    assert classify_template_intent("utilidade_22_04_2026_16_40") == GENERIC


def test_warm_lp_vence_mesmo_sob_outbound():
    # lead de landing page e quente — NUNCA reclassificar como frio, mesmo sob outbound
    assert classify_template_intent("lp_welcome", "valeria_outbound") == WARM_LP


def test_cold_explicito_continua_cold_sob_qualquer_persona():
    assert classify_template_intent("reativacao_30d", "valeria_inbound") == COLD_REACTIVATION
    assert classify_template_intent("atualizacao_cadastro", "valeria_outbound") == COLD_REACTIVATION


def test_dispatch_metadata_propaga_prompt_key():
    md = dispatch_metadata("utilidade_22_04_2026_16_40", "valeria_outbound")
    assert md == {
        "dispatch": {
            "template": "utilidade_22_04_2026_16_40",
            "intent": COLD_REACTIVATION,
        }
    }


def test_dispatch_metadata_sem_prompt_key_legado():
    md = dispatch_metadata("utilidade_22_04_2026_16_40")
    assert md["dispatch"]["intent"] == GENERIC
