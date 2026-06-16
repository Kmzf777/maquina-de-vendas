from app.buffer.processor import _bubble_delays

# _bubble_delays(bubbles: list[str], is_rehearsal) — o atraso antes de bubbles[i]
# é proporcional a len(bubbles[i-1]): clamp(len(prev)/15, 1.0, 3.0). O primeiro
# bubble vai sempre imediato (0.0); rehearsal zera tudo.


def test_single_bubble_no_delay():
    # Bubble único é enviado imediatamente.
    assert _bubble_delays(["Olá!"], is_rehearsal=False) == [0.0]


def test_two_bubbles_delay_capped_at_max():
    # prev com 45 chars → 45/15 = 3.0 (teto _MAX_BUBBLE_DELAY).
    prev = "x" * 45
    assert _bubble_delays([prev, "segunda"], is_rehearsal=False) == [0.0, 3.0]


def test_short_prev_bubble_floored_at_min():
    # prev curto (3 chars) → 3/15 = 0.2 → piso _MIN_BUBBLE_DELAY (1.0).
    assert _bubble_delays(["abc", "segunda"], is_rehearsal=False) == [0.0, 1.0]


def test_four_bubbles_proportional_to_prev_length():
    prev_long = "x" * 45   # → 3.0 (teto)
    prev_mid = "x" * 30    # 30/15 = 2.0
    prev_short = "abc"     # → 1.0 (piso)
    delays = _bubble_delays(
        [prev_long, prev_mid, prev_short, "ultima"], is_rehearsal=False
    )
    assert delays == [0.0, 3.0, 2.0, 1.0]


def test_rehearsal_no_delays():
    assert _bubble_delays(["a" * 45, "b", "c", "d"], is_rehearsal=True) == [
        0.0,
        0.0,
        0.0,
        0.0,
    ]


def test_zero_bubbles():
    assert _bubble_delays([], is_rehearsal=False) == []
