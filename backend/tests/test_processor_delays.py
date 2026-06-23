from app.buffer.processor import _bubble_delays, _BUBBLE_TRANSITION_PAUSE

# _bubble_delays(bubbles, is_rehearsal, llm_latency=0.0) — digitação humana relaxada:
# clamp(len(prev)/4, 5.0, 15.0). Balões após o 1º ganham +_BUBBLE_TRANSITION_PAUSE (3.5s)
# de "respiração cognitiva". O 1º balão = clamp do próprio tamanho menos latência da LLM
# (piso 0), SEM a pausa de transição. Rehearsal zera tudo.


def test_single_bubble_has_typing_delay():
    # "Olá!" = 4 chars → 4/4=1.0 → piso 5.0 (sem latência, sem transição no 1º).
    assert _bubble_delays(["Olá!"], is_rehearsal=False) == [5.0]


def test_single_bubble_first_delay_minus_llm_latency():
    # 48 chars → 48/4 = 12.0s; LLM levou 2s → resta 10.0s. Sem +3.5 (é o 1º balão).
    assert _bubble_delays(["x" * 48], is_rehearsal=False, llm_latency=2.0) == [10.0]


def test_two_bubbles_delay_capped_at_max_plus_transition():
    # prev 120 chars → 120/4 = 30 → teto 15.0 + 3.5 transição = 18.5. 1º floored (llm alto).
    prev = "x" * 120
    assert _bubble_delays([prev, "segunda"], is_rehearsal=False, llm_latency=99.0) == [0.0, 18.5]


def test_short_prev_bubble_floored_at_min_plus_transition():
    # prev curto (3 chars) → piso 5.0 + 3.5 transição = 8.5.
    assert _bubble_delays(["abc", "segunda"], is_rehearsal=False, llm_latency=99.0) == [0.0, 8.5]


def test_four_bubbles_proportional_to_prev_length():
    prev_long = "x" * 120   # → 15.0 (teto) + 3.5 = 18.5
    prev_mid = "x" * 48      # 48/4 = 12.0 + 3.5 = 15.5
    prev_short = "abc"       # → 5.0 (piso) + 3.5 = 8.5
    delays = _bubble_delays(
        [prev_long, prev_mid, prev_short, "ultima"], is_rehearsal=False, llm_latency=99.0
    )
    assert delays == [0.0, 18.5, 15.5, 8.5]


def test_transition_pause_only_after_first_bubble():
    # O 1º balão NÃO recebe a pausa de transição; os seguintes sim.
    delays = _bubble_delays(["x" * 48, "x" * 48], is_rehearsal=False, llm_latency=0.0)
    assert delays[0] == 12.0                              # 48/4, sem +3.5
    assert delays[1] == 12.0 + _BUBBLE_TRANSITION_PAUSE   # com +3.5


def test_rehearsal_no_delays():
    assert _bubble_delays(["a" * 120, "b", "c", "d"], is_rehearsal=True) == [
        0.0,
        0.0,
        0.0,
        0.0,
    ]


def test_zero_bubbles():
    assert _bubble_delays([], is_rehearsal=False) == []
