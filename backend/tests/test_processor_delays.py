from app.buffer.processor import _bubble_delays


def test_single_bubble_no_delay():
    assert _bubble_delays(1, is_rehearsal=False) == [0.0]


def test_two_bubbles_production():
    assert _bubble_delays(2, is_rehearsal=False) == [0.0, 4.0]


def test_four_bubbles_production():
    assert _bubble_delays(4, is_rehearsal=False) == [0.0, 4.0, 2.0, 2.0]


def test_rehearsal_no_delays():
    assert _bubble_delays(4, is_rehearsal=True) == [0.0, 0.0, 0.0, 0.0]


def test_zero_bubbles():
    assert _bubble_delays(0, is_rehearsal=False) == []
