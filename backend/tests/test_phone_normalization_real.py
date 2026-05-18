"""
Tests using the user's real phone number 5534988861441.

Number breakdown:
  55       — country code (Brazil)
  34       — DDD (Uberlândia / Triângulo Mineiro)
  9        — 9th digit (mandatory for mobile in Brazil since 2012)
  88861441 — subscriber number (8 digits)

Legacy (12-digit) form: 553488861441  (same number, 9th digit absent)
Canonical (13-digit) form: 5534988861441

Tests cover normalize_phone and get_or_create_lead with mocked Supabase.
"""

from unittest.mock import MagicMock, patch

REAL_PHONE_13 = "5534988861441"   # canonical
REAL_PHONE_12 = "553488861441"    # legacy 12-digit (no 9th digit)


# ═══════════════════════════════════════════════════════════════
# normalize_phone
# ═══════════════════════════════════════════════════════════════

def test_normalize_phone_canonical_number_unchanged():
    """5534988861441 (13-digit canonical) must come out unchanged."""
    from app.leads.service import normalize_phone
    assert normalize_phone(REAL_PHONE_13) == REAL_PHONE_13


def test_normalize_phone_injects_ninth_digit_for_legacy_12_digit():
    """553488861441 (12-digit legacy) must become 5534988861441 after 9th-digit injection."""
    from app.leads.service import normalize_phone
    assert normalize_phone(REAL_PHONE_12) == REAL_PHONE_13


def test_normalize_phone_strips_dashes_and_spaces():
    """55-34-98886-1441 must normalize to 5534988861441."""
    from app.leads.service import normalize_phone
    assert normalize_phone("55-34-98886-1441") == REAL_PHONE_13


def test_normalize_phone_strips_parentheses_and_spaces():
    """+55 (34) 98886-1441 (international formatted) must normalize to 5534988861441."""
    from app.leads.service import normalize_phone
    assert normalize_phone("+55 (34) 98886-1441") == REAL_PHONE_13


def test_normalize_phone_strips_whatsapp_prefix_canonical():
    """whatsapp:5534988861441 must normalize to 5534988861441."""
    from app.leads.service import normalize_phone
    assert normalize_phone("whatsapp:5534988861441") == REAL_PHONE_13


def test_normalize_phone_strips_whatsapp_prefix_and_injects_ninth_digit():
    """whatsapp:553488861441 (12-digit with prefix) must normalize to 5534988861441."""
    from app.leads.service import normalize_phone
    assert normalize_phone("whatsapp:553488861441") == REAL_PHONE_13


# ═══════════════════════════════════════════════════════════════
# get_or_create_lead — canonical 13-digit number
# ═══════════════════════════════════════════════════════════════

def _sb_returns_lead(phone, lead_id="lead-real-uuid"):
    """Supabase mock: always finds the given phone on the first lookup."""
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
        {"id": lead_id, "phone": phone, "name": "Rafael Canastra", "stage": "pending"}
    ]
    return mock


def _sb_empty_then_insert():
    """Supabase mock: no existing lead; insert succeeds."""
    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
    mock.table.return_value.insert.return_value.execute.return_value.data = [
        {"id": "new-uuid", "phone": REAL_PHONE_13, "stage": "pending", "status": "imported"}
    ]
    return mock


def test_get_or_create_lead_finds_canonical_13_digit_number():
    """get_or_create_lead("5534988861441") must return the lead without creating a new one."""
    with patch("app.leads.service.get_supabase", return_value=_sb_returns_lead(REAL_PHONE_13)):
        from app.leads.service import get_or_create_lead
        lead = get_or_create_lead(REAL_PHONE_13)
    assert lead["phone"] == REAL_PHONE_13
    assert lead["id"] == "lead-real-uuid"


def test_get_or_create_lead_creates_new_lead_when_not_in_db():
    """When the number isn't in the DB, a new lead with canonical phone must be created."""
    with patch("app.leads.service.get_supabase", return_value=_sb_empty_then_insert()):
        from app.leads.service import get_or_create_lead
        lead = get_or_create_lead(REAL_PHONE_13)
    assert lead["phone"] == REAL_PHONE_13
    assert lead["id"] == "new-uuid"


# ═══════════════════════════════════════════════════════════════
# get_or_create_lead — legacy 12-digit (core of the dedup bug)
# ═══════════════════════════════════════════════════════════════

def _sb_12digit_in_db():
    """Supabase mock simulating a lead stored with the legacy 12-digit phone.

    Call sequence in get_or_create_lead("553488861441"):
      1. eq("phone", "5534988861441") → []  (normalized form not found)
      2. eq("phone", "553488861441")  → [lead]  (digits_only legacy form found)
      3. update({"phone": "5534988861441"}).eq("id", "legacy-uuid") → OK  (backfill)
    """
    call_count = [0]

    def eq_factory(col, val):
        chain = MagicMock()
        if val == REAL_PHONE_13:
            chain.execute.return_value.data = []
        elif val == REAL_PHONE_12:
            chain.execute.return_value.data = [
                {"id": "legacy-uuid", "phone": REAL_PHONE_12,
                 "name": "Rafael (legado)", "stage": "pending"}
            ]
        else:
            chain.execute.return_value.data = []
        return chain

    mock = MagicMock()
    mock.table.return_value.select.return_value.eq.side_effect = eq_factory
    mock.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    return mock


def test_get_or_create_lead_finds_legacy_12_digit_and_does_not_create_duplicate():
    """get_or_create_lead("553488861441") must find the existing 12-digit lead via backfill,
    NOT insert a new duplicate row.

    This is the exact root cause of the broadcast duplicate-send bug:
    two leads for the same person caused two templates to fire.
    """
    mock_sb = _sb_12digit_in_db()
    with patch("app.leads.service.get_supabase", return_value=mock_sb):
        from app.leads.service import get_or_create_lead
        lead = get_or_create_lead(REAL_PHONE_12)

    assert lead["id"] == "legacy-uuid", "Must return the existing lead, not a new one"
    mock_sb.table.return_value.insert.assert_not_called()


def test_get_or_create_lead_backfills_12_digit_to_13_digit_in_db():
    """After finding a 12-digit legacy lead, the DB must be updated to the canonical phone."""
    mock_sb = _sb_12digit_in_db()
    with patch("app.leads.service.get_supabase", return_value=mock_sb):
        from app.leads.service import get_or_create_lead
        get_or_create_lead(REAL_PHONE_12)

    # update() must have been called with the canonical phone
    update_call = mock_sb.table.return_value.update.call_args
    assert update_call is not None, "update() must be called to backfill the phone"
    updated_fields = update_call[0][0]
    assert updated_fields.get("phone") == REAL_PHONE_13, (
        f"DB must be updated to canonical {REAL_PHONE_13}, got {updated_fields}"
    )


def test_get_or_create_lead_returned_lead_has_canonical_phone_after_backfill():
    """Even before the DB update commits, the returned dict must have the canonical phone."""
    mock_sb = _sb_12digit_in_db()
    with patch("app.leads.service.get_supabase", return_value=mock_sb):
        from app.leads.service import get_or_create_lead
        lead = get_or_create_lead(REAL_PHONE_12)

    # The service patches the in-memory row so callers always see canonical
    assert lead["phone"] == REAL_PHONE_13
