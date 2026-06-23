from app.buffer.processor import (
    _bubble_delays, _SUBSEQUENT_MIN_DELAY, _SUBSEQUENT_MAX_DELAY,
)

# Delays ASSIMÉTRICOS (limite da Meta API: typing não re-renderiza após o 1º balão):
# - 1º balão (pensativo): clamp(len/4, 5.0, 15.0) menos a latência da LLM (piso 0).
#   O "digitando…" funciona aqui, então vale a pena demorar.
# - Balões seguintes (sucessão rápida): SEM pausa de transição; clamp(len(prev)/4,
#   1.5, 2.5) — caem rápido em sequência, pois não há indicador visual entre eles.
# Rehearsal zera tudo.


def test_single_bubble_has_typing_delay():
    # "Olá!" = 4 chars → 4/4=1.0 → piso 5.0 do 1º balão (sem latência).
    assert _bubble_delays(["Olá!"], is_rehearsal=False) == [5.0]


def test_single_bubble_first_delay_minus_llm_latency():
    # 48 chars → 48/4 = 12.0s; LLM levou 2s → resta 10.0s.
    assert _bubble_delays(["x" * 48], is_rehearsal=False, llm_latency=2.0) == [10.0]


def test_subsequent_bubble_capped_at_subsequent_max():
    # prev longo (120 chars → 30s teórico) é ENGESSADO no teto de sucessão (2.5s).
    prev = "x" * 120
    assert _bubble_delays([prev, "segunda"], is_rehearsal=False, llm_latency=99.0) == [0.0, _SUBSEQUENT_MAX_DELAY]


def test_subsequent_bubble_floored_at_subsequent_min():
    # prev curto (3 chars → 0.75s) é elevado ao piso de sucessão (1.5s).
    assert _bubble_delays(["abc", "segunda"], is_rehearsal=False, llm_latency=99.0) == [0.0, _SUBSEQUENT_MIN_DELAY]


def test_subsequent_bubble_proportional_within_range():
    # prev de 8 chars → 8/4 = 2.0s, dentro de [1.5, 2.5] → proporcional.
    assert _bubble_delays(["x" * 8, "segunda"], is_rehearsal=False, llm_latency=99.0) == [0.0, 2.0]


def test_four_bubbles_fast_succession_no_transition_pause():
    prev_long = "x" * 120   # → teto 2.5
    prev_mid = "x" * 48      # 48/4=12 → teto 2.5
    prev_in_range = "x" * 8  # 8/4=2.0 (dentro do range)
    delays = _bubble_delays(
        [prev_long, prev_mid, prev_in_range, "ultima"], is_rehearsal=False, llm_latency=99.0
    )
    # 1º floored (llm alto); seguintes engessados em 1.5–2.5, SEM +3.5 de transição
    assert delays == [0.0, 2.5, 2.5, 2.0]


def test_first_bubble_thoughtful_subsequent_fast():
    """Assimetria: 1º balão demorado, 2º rápido — mesmo com textos longos iguais."""
    delays = _bubble_delays(["x" * 48, "x" * 48], is_rehearsal=False, llm_latency=0.0)
    assert delays[0] == 12.0                    # 48/4, pensativo
    assert delays[1] == _SUBSEQUENT_MAX_DELAY   # engessado em 2.5, sucessão rápida


def test_rehearsal_no_delays():
    assert _bubble_delays(["a" * 120, "b", "c", "d"], is_rehearsal=True) == [
        0.0,
        0.0,
        0.0,
        0.0,
    ]


def test_zero_bubbles():
    assert _bubble_delays([], is_rehearsal=False) == []
