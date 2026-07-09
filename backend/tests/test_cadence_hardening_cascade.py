from app.automation.triggers import _keyword_hit


def test_keyword_word_boundary_no_substring_false_positive():
    assert _keyword_hit("isso é assim mesmo", ["sim"]) is False
    assert _keyword_hit("sim, quero", ["sim"]) is True
