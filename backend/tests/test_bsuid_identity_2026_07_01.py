from app.leads.service import is_bsuid, normalize_phone


def test_is_bsuid_true_for_bsuid_format():
    assert is_bsuid("US.13491208655302741918") is True
    assert is_bsuid("BR.9988776655") is True


def test_is_bsuid_false_for_phone_and_junk():
    assert is_bsuid("5534999999999") is False
    assert is_bsuid("+55 34 99999-9999") is False
    assert is_bsuid("") is False
    assert is_bsuid(None) is False


def test_normalize_phone_passes_bsuid_through_unchanged():
    assert normalize_phone("US.13491208655302741918") == "US.13491208655302741918"


def test_normalize_phone_still_normalizes_real_phones():
    assert normalize_phone("553499999999") == "5534999999999"
