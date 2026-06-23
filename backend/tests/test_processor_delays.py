from app.buffer.processor import _bubble_delays, _BUBBLE_TRANSITION_PAUSE

# _bubble_delays(bubbles, is_rehearsal, llm_latency=0.0) — digitação humana lenta:
# clamp(len(prev)/6, 4.0, 12.0). Balões após o 1º ganham +_BUBBLE_TRANSITION_PAUSE (1.5s)
# de "respiração cognitiva". O 1º balão = clamp do próprio tamanho menos latência da LLM
# (piso 0), SEM a pausa de transição. Rehearsal zera tudo.


def test_single_bubble_has_typing_delay():
    # "Olá!" = 4 chars → 4/6=0.67 → piso 4.0 (sem latência, sem transição no 1º).
    assert _bubble_delays(["Olá!"], is_rehearsal=False) == [4.0]


def test_single_bubble_first_delay_minus_llm_latency():
    # 48 chars → 48/6 = 8.0s; LLM levou 2s → resta 6.0s. Sem +1.5 (é o 1º balão).
    assert _bubble_delays(["x" * 48], is_rehearsal=False, llm_latency=2.0) == [6.0]


def test_two_bubbles_delay_capped_at_max_plus_transition():
    # prev 120 chars → 120/6 = 20 → teto 12.0 + 1.5 transição = 13.5. 1º floored (llm alto).
    prev = "x" * 120
    assert _bubble_delays([prev, "segunda"], is_rehearsal=False, llm_latency=99.0) == [0.0, 13.5]


def test_short_prev_bubble_floored_at_min_plus_transition():
    # prev curto (3 chars) → piso 4.0 + 1.5 transição = 5.5.
    assert _bubble_delays(["abc", "segunda"], is_rehearsal=False, llm_latency=99.0) == [0.0, 5.5]


def test_four_bubbles_proportional_to_prev_length():
    prev_long = "x" * 120   # → 12.0 (teto) + 1.5 = 13.5
    prev_mid = "x" * 48      # 48/6 = 8.0 + 1.5 = 9.5
    prev_short = "abc"       # → 4.0 (piso) + 1.5 = 5.5
    delays = _bubble_delays(
        [prev_long, prev_mid, prev_short, "ultima"], is_rehearsal=False, llm_latency=99.0
    )
    assert delays == [0.0, 13.5, 9.5, 5.5]


def test_transition_pause_only_after_first_bubble():
    # O 1º balão NÃO recebe a pausa de transição; os seguintes sim.
    delays = _bubble_delays(["x" * 48, "x" * 48], is_rehearsal=False, llm_latency=0.0)
    assert delays[0] == 8.0                              # 48/6, sem +1.5
    assert delays[1] == 8.0 + _BUBBLE_TRANSITION_PAUSE   # com +1.5


def test_rehearsal_no_delays():
    assert _bubble_delays(["a" * 120, "b", "c", "d"], is_rehearsal=True) == [
        0.0,
        0.0,
        0.0,
        0.0,
    ]


def test_zero_bubbles():
    assert _bubble_delays([], is_rehearsal=False) == []
