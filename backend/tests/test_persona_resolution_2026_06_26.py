"""Eixo 1 — Resolução dinâmica de persona.

A persona é recomputada por turno a partir do histórico, ignorando o pin estático da
conversa. Regra ATUAL (sticky outbound, 2026-06-27): se a conversa tem um disparo FRIO
(cold_reactivation) e NENHUM humano interveio, a persona é `valeria_outbound` durante
TODA a conversa — não apenas no 1º turno. Qualquer intervenção humana joga para inbound.
Disparo quente (warm_lp) ou inbound orgânico → inbound.
"""
from app.agent.persona import decide_persona, persona_signals, resolve_persona_prompt_key


def _msg(role, sent_by=None, intent=None):
    md = {"dispatch": {"intent": intent}} if intent else {}
    return {"role": role, "sent_by": sent_by, "metadata": md}


# ── núcleo puro ──
def test_decide_cold_dispatch_e_outbound():
    assert decide_persona(has_human_message=False, has_cold_dispatch=True) == "valeria_outbound"


def test_decide_sem_cold_dispatch_e_inbound():
    assert decide_persona(has_human_message=False, has_cold_dispatch=False) == "valeria_inbound"


def test_decide_humano_forca_inbound_mesmo_com_cold_dispatch():
    # Mitigação: vendedor já interveio → o AI não retoma o frame de reativação fria
    assert decide_persona(has_human_message=True, has_cold_dispatch=True) == "valeria_inbound"


# ── resolução a partir do histórico ──
def test_broadcast_frio_sem_resposta_e_outbound():
    msgs = [_msg("assistant", "broadcast", "cold_reactivation")]
    assert resolve_persona_prompt_key(msgs) == "valeria_outbound"


def test_broadcast_frio_com_resposta_continua_outbound():
    # STICKY: o lead respondeu, mas o disparo foi frio/outbound → segue outbound até o fim
    msgs = [_msg("assistant", "broadcast", "cold_reactivation"), _msg("user", "user")]
    assert resolve_persona_prompt_key(msgs) == "valeria_outbound"


def test_broadcast_frio_conversa_longa_continua_outbound():
    # Vários turnos após a resposta — persona permanece outbound (sem humano)
    msgs = [
        _msg("assistant", "broadcast", "cold_reactivation"),
        _msg("user", "user"),
        _msg("assistant", "agent"),
        _msg("user", "user"),
    ]
    assert resolve_persona_prompt_key(msgs) == "valeria_outbound"


def test_disparo_warm_lp_sem_resposta_e_inbound():
    # Lead de landing page é quente — nunca cai no frame de recuperação fria
    msgs = [_msg("assistant", "broadcast", "warm_lp")]
    assert resolve_persona_prompt_key(msgs) == "valeria_inbound"


def test_intervencao_humana_forca_inbound():
    msgs = [
        _msg("assistant", "broadcast", "cold_reactivation"),
        _msg("user", "user"),
        _msg("assistant", "human"),
    ]
    assert resolve_persona_prompt_key(msgs) == "valeria_inbound"


def test_inbound_organico_sem_disparo_e_inbound():
    msgs = [_msg("user", "user")]
    assert resolve_persona_prompt_key(msgs) == "valeria_inbound"


def test_conversa_vazia_default_inbound():
    assert resolve_persona_prompt_key([]) == "valeria_inbound"


def test_persona_signals_detecta_cold_dispatch_independente_de_resposta():
    has_human, has_cold = persona_signals(
        [_msg("assistant", "broadcast", "cold_reactivation"), _msg("user", "user")]
    )
    assert has_human is False
    assert has_cold is True
