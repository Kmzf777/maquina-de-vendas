from app.leads.service import derive_traffic_type


def test_paid_by_gclid():
    assert derive_traffic_type({"gclid": "g"}) == "paid"


def test_paid_by_fbclid():
    assert derive_traffic_type({"fbclid": "f"}) == "paid"


def test_paid_by_ctwa_clid():
    assert derive_traffic_type({"ctwa_clid": "c"}) == "paid"


def test_paid_by_utm_medium_variants():
    for m in ["cpc", "ppc", "paid", "paid_social", "paidsocial", "paid_search", "display", "cpm"]:
        assert derive_traffic_type({"utm_medium": m}) == "paid", m
    assert derive_traffic_type({"utm_medium": "CPC"}) == "paid"  # case-insensitive


def test_organic_by_utm_signal():
    assert derive_traffic_type({"utm_source": "instagram", "utm_medium": "bio"}) == "organic"
    assert derive_traffic_type({"utm_medium": "organic"}) == "organic"
    assert derive_traffic_type({"utm_campaign": "link_bio"}) == "organic"


def test_none_when_no_signal():
    assert derive_traffic_type({}) is None
    assert derive_traffic_type(None) is None
    assert derive_traffic_type({"gclid": "", "utm_medium": ""}) is None


def test_paid_takes_precedence_over_organic_medium():
    # gclid present but medium looks organic → still paid (click id wins)
    assert derive_traffic_type({"gclid": "g", "utm_medium": "organic"}) == "paid"
