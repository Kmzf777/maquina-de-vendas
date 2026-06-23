from app.buffer.processor import _bubble_delays

# _bubble_delays(bubbles, is_rehearsal, llm_latency=0.0) — afinado p/ digitação humana
# em smartphone: o atraso antes de bubbles[i>=1] é proporcional a len(bubbles[i-1]),
# clamp(len(prev)/8, 2.0, 10.0). O PRIMEIRO bubble agora também tem delay de digitação
# (clamp do próprio tamanho) menos a latência da LLM, com piso 0. Rehearsal zera tudo.


def test_single_bubble_has_typing_delay():
    # Bubble único: "Olá!" = 4 chars → 4/8=0.5 → piso 2.0 (sem latência subtraída).
    assert _bubble_delays(["Olá!"], is_rehearsal=False) == [2.0]


def test_single_bubble_first_delay_minus_llm_latency():
    # 64 chars → 64/8 = 8.0s de digitação; LLM levou 3s → resta 5.0s.
    assert _bubble_delays(["x" * 64], is_rehearsal=False, llm_latency=3.0) == [5.0]


def test_two_bubbles_delay_capped_at_max():
    # prev com 80 chars → 80/8 = 10.0 (teto _MAX_BUBBLE_DELAY). 1º balão floored c/ latência alta.
    prev = "x" * 80
    assert _bubble_delays([prev, "segunda"], is_rehearsal=False, llm_latency=99.0) == [0.0, 10.0]


def test_short_prev_bubble_floored_at_min():
    # prev curto (3 chars) → 3/8 = 0.375 → piso _MIN_BUBBLE_DELAY (2.0).
    assert _bubble_delays(["abc", "segunda"], is_rehearsal=False, llm_latency=99.0) == [0.0, 2.0]


def test_four_bubbles_proportional_to_prev_length():
    prev_long = "x" * 80   # → 10.0 (teto)
    prev_mid = "x" * 48     # 48/8 = 6.0
    prev_short = "abc"      # → 2.0 (piso)
    delays = _bubble_delays(
        [prev_long, prev_mid, prev_short, "ultima"], is_rehearsal=False, llm_latency=99.0
    )
    # 1º balão floored em 0 (latência >> digitação); demais proporcionais ao anterior
    assert delays == [0.0, 10.0, 6.0, 2.0]


def test_rehearsal_no_delays():
    assert _bubble_delays(["a" * 80, "b", "c", "d"], is_rehearsal=True) == [
        0.0,
        0.0,
        0.0,
        0.0,
    ]


def test_zero_bubbles():
    assert _bubble_delays([], is_rehearsal=False) == []
