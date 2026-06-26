"""Eixo 1 — Resolução dinâmica de persona.

A persona é recomputada por turno a partir do histórico, ignorando o pin estático da
conversa. A persona outbound só governa o 1º turno reativo a um disparo FRIO ainda não
respondido; qualquer resposta do lead OU intervenção humana joga para inbound.
"""
from app.agent.persona import decide_persona, resolve_persona_prompt_key


def _msg(role, sent_by=None, intent=None):
    md = {"dispatch": {"intent": intent}} if intent else {}
    return {"role": role, "sent_by": sent_by, "metadata": md}


# ── núcleo puro ──
def test_decide_cold_open_unanswered_e_outbound():
    assert decide_persona(has_human_message=False, cold_open_unanswered=True) == "valeria_outbound"


def test_decide_cold_open_respondido_e_inbound():
    assert decide_persona(has_human_message=False, cold_open_unanswered=False) == "valeria_inbound"


def test_decide_humano_forca_inbound_mesmo_com_cold_open():
    # Mitigação: vendedor já interveio → nunca tratar como cold-open
    assert decide_persona(has_human_message=True, cold_open_unanswered=True) == "valeria_inbound"


# ── resolução a partir do histórico ──
def test_broadcast_frio_sem_resposta_e_outbound():
    msgs = [_msg("assistant", "broadcast", "cold_reactivation")]
    assert resolve_persona_prompt_key(msgs) == "valeria_outbound"


def test_broadcast_frio_com_resposta_vira_inbound():
    msgs = [_msg("assistant", "broadcast", "cold_reactivation"), _msg("user", "user")]
    assert resolve_persona_prompt_key(msgs) == "valeria_inbound"


def test_disparo_warm_lp_sem_resposta_e_inbound():
    # Lead de landing page é quente — nunca cai no frame de recuperação fria
    msgs = [_msg("assistant", "broadcast", "warm_lp")]
    assert resolve_persona_prompt_key(msgs) == "valeria_inbound"


def test_intervencao_humana_forca_inbound():
    msgs = [
        _msg("assistant", "broadcast", "cold_reactivation"),
        _msg("assistant", "human"),
    ]
    assert resolve_persona_prompt_key(msgs) == "valeria_inbound"


def test_inbound_organico_sem_disparo_e_inbound():
    msgs = [_msg("user", "user")]
    assert resolve_persona_prompt_key(msgs) == "valeria_inbound"


def test_conversa_vazia_default_inbound():
    assert resolve_persona_prompt_key([]) == "valeria_inbound"
