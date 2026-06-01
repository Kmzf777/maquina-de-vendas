"""Tests for normalize_lp_phone and integration with process_landing_page_lead."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock, call


# ─── normalize_lp_phone unit tests ────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected_phone, expected_confidence", [
    # Full E.164 with + prefix
    ("+5534988861441", "5534988861441", "ok"),
    # 00-prefixed international
    ("005534988861441", "5534988861441", "ok"),
    # Already clean 13 digits with 55
    ("5534988861441", "5534988861441", "ok"),
    # 12 digits with 55 → normalize_phone injects 9 at position 4 (after DDD)
    # 553498886144 = 55 + 34 + 98886144 → inject 9 → 5534 + 9 + 98886144 = 5534998886144
    ("553498886144", "5534998886144", "ok"),
    # 11 digits without 55 → prepend 55 → 13 digits → no injection needed
    ("34988861441", "5534988861441", "assumed_br"),
    # 10 digits without 55 → prepend 55 → 12 digits → normalize_phone injects 9
    # 3498886144 → 553498886144 = 55 + 34 + 98886144 → inject 9 → 5534998886144
    ("3498886144", "5534998886144", "assumed_br"),
    # Formatted 11-digit local number → 34988861441 → prepend 55 → 5534988861441
    ("(34) 9 8886-1441", "5534988861441", "assumed_br"),
    # Formatted local number → strips to 34988861441 (11 digits) → prepend 55 → 5534988861441
    ("34 98886-1441", "5534988861441", "assumed_br"),
    # Unrecognized short number → uncertain
    ("912345678", "912345678", "uncertain"),
    # Empty string → uncertain
    ("", "", "uncertain"),
])
def test_normalize_lp_phone(raw, expected_phone, expected_confidence):
    from app.lp_webhook.phone import normalize_lp_phone

    phone, confidence = normalize_lp_phone(raw)

    assert phone == expected_phone, f"Input {raw!r}: expected phone {expected_phone!r}, got {phone!r}"
    assert confidence == expected_confidence, (
        f"Input {raw!r}: expected confidence {expected_confidence!r}, got {confidence!r}"
    )


def test_normalize_lp_phone_whatsapp_prefix():
    """whatsapp: prefix is stripped before normalization."""
    from app.lp_webhook.phone import normalize_lp_phone

    phone, confidence = normalize_lp_phone("whatsapp:+5534988861441")
    assert phone == "5534988861441"
    assert confidence == "ok"


def test_normalize_lp_phone_whitespace_only():
    """Whitespace-only input is treated as empty."""
    from app.lp_webhook.phone import normalize_lp_phone

    phone, confidence = normalize_lp_phone("   ")
    assert phone == ""
    assert confidence == "uncertain"


# ─── process_landing_page_lead integration tests ───────────────────────────────

@pytest.mark.anyio
async def test_process_lp_lead_assumed_br_saves_phone_raw():
    """confidence='assumed_br' → phone_raw saved in metadata, tag NOT applied."""
    from app.lp_webhook.service import process_landing_page_lead

    # 10-digit input → assumed_br
    raw_phone = "3498886144"
    fake_lead = {
        "id": "lead-1",
        "phone": "5534988861441",
        "name": "Ana",
        "email": None,
        "metadata": {},
    }

    redis = AsyncMock()

    # We patch normalize_lp_phone to control the confidence returned
    with patch("app.lp_webhook.service.normalize_lp_phone", return_value=("5534988861441", "assumed_br")), \
         patch("app.lp_webhook.service.get_or_create_lead", return_value=fake_lead), \
         patch("app.lp_webhook.service.get_lp_config", new=AsyncMock(return_value={
             "channel_id": "", "template_name": "", "language_code": "pt_BR", "delay_minutes": 15,
         })), \
         patch("app.lp_webhook.service._schedule_lp_welcome") as mock_schedule, \
         patch("app.lp_webhook.service._tag_lead_phone_uncertain") as mock_tag, \
         patch("app.lp_webhook.service.get_supabase") as mock_sb:

        # Track update calls
        mock_table = MagicMock()
        mock_sb.return_value.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

        payload = {"whatsapp": raw_phone, "nome": "Ana", "email": "", "origem": ""}
        result = await process_landing_page_lead(payload, redis)

    assert result["ok"] is True
    # phone_raw should have been saved via an update call
    update_calls = mock_table.update.call_args_list
    phone_raw_saved = any(
        "phone_raw" in str(c) for c in update_calls
    )
    assert phone_raw_saved, "Expected phone_raw to be saved in metadata for assumed_br"
    # Tag function should NOT be called for assumed_br
    mock_tag.assert_not_called()


@pytest.mark.anyio
async def test_process_lp_lead_uncertain_tags_lead():
    """confidence='uncertain' → _tag_lead_phone_uncertain called, phone_raw saved."""
    from app.lp_webhook.service import process_landing_page_lead

    raw_phone = "912345678"
    fake_lead = {
        "id": "lead-2",
        "phone": "912345678",
        "name": "Bob",
        "email": None,
        "metadata": {},
    }

    redis = AsyncMock()

    with patch("app.lp_webhook.service.normalize_lp_phone", return_value=("912345678", "uncertain")), \
         patch("app.lp_webhook.service.get_or_create_lead", return_value=fake_lead), \
         patch("app.lp_webhook.service.get_lp_config", new=AsyncMock(return_value={
             "channel_id": "", "template_name": "", "language_code": "pt_BR", "delay_minutes": 15,
         })), \
         patch("app.lp_webhook.service._schedule_lp_welcome") as mock_schedule, \
         patch("app.lp_webhook.service._tag_lead_phone_uncertain") as mock_tag, \
         patch("app.lp_webhook.service.get_supabase") as mock_sb:

        mock_table = MagicMock()
        mock_sb.return_value.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

        payload = {"whatsapp": raw_phone, "nome": "Bob", "email": "", "origem": ""}
        result = await process_landing_page_lead(payload, redis)

    assert result["ok"] is True
    # Tag function MUST be called for uncertain
    mock_tag.assert_called_once_with("lead-2")
    # phone_raw should also be saved
    update_calls = mock_table.update.call_args_list
    phone_raw_saved = any("phone_raw" in str(c) for c in update_calls)
    assert phone_raw_saved, "Expected phone_raw to be saved in metadata for uncertain"


@pytest.mark.anyio
async def test_process_lp_lead_ok_confidence_no_tag_no_phone_raw():
    """confidence='ok' → no tag, no phone_raw saved in metadata."""
    from app.lp_webhook.service import process_landing_page_lead

    raw_phone = "5534988861441"
    fake_lead = {
        "id": "lead-3",
        "phone": "5534988861441",
        "name": "Carlos",
        "email": None,
        "metadata": {},
    }

    redis = AsyncMock()

    with patch("app.lp_webhook.service.normalize_lp_phone", return_value=("5534988861441", "ok")), \
         patch("app.lp_webhook.service.get_or_create_lead", return_value=fake_lead), \
         patch("app.lp_webhook.service.get_lp_config", new=AsyncMock(return_value={
             "channel_id": "", "template_name": "", "language_code": "pt_BR", "delay_minutes": 15,
         })), \
         patch("app.lp_webhook.service._schedule_lp_welcome") as mock_schedule, \
         patch("app.lp_webhook.service._tag_lead_phone_uncertain") as mock_tag, \
         patch("app.lp_webhook.service.get_supabase") as mock_sb:

        mock_table = MagicMock()
        mock_sb.return_value.table.return_value = mock_table
        mock_table.update.return_value.eq.return_value.execute.return_value = MagicMock()

        payload = {"whatsapp": raw_phone, "nome": "Carlos", "email": "", "origem": ""}
        result = await process_landing_page_lead(payload, redis)

    assert result["ok"] is True
    # No tag for ok
    mock_tag.assert_not_called()
    # No phone_raw update for ok
    update_calls = mock_table.update.call_args_list
    phone_raw_saved = any("phone_raw" in str(c) for c in update_calls)
    assert not phone_raw_saved, "phone_raw should NOT be saved when confidence is ok"


# ─── _tag_lead_phone_uncertain unit tests ──────────────────────────────────────

def test_tag_lead_phone_uncertain_creates_tag_if_not_exists():
    """When tag doesn't exist yet → creates it, then inserts lead_tags row."""
    from app.lp_webhook.service import _tag_lead_phone_uncertain

    mock_sb = MagicMock()
    # Simulate tag not found
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
    # Simulate tag creation returning id
    mock_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "tag-new"}])

    with patch("app.lp_webhook.service.get_supabase", return_value=mock_sb):
        _tag_lead_phone_uncertain("lead-xyz")

    # insert should be called twice: once for tags, once for lead_tags
    insert_calls = mock_sb.table.return_value.insert.call_args_list
    assert len(insert_calls) == 2


def test_tag_lead_phone_uncertain_reuses_existing_tag():
    """When tag already exists → no tag creation, just lead_tags insert."""
    from app.lp_webhook.service import _tag_lead_phone_uncertain

    mock_sb = MagicMock()
    # Simulate tag found
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[{"id": "tag-existing"}]
    )
    mock_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "lt-1"}])

    with patch("app.lp_webhook.service.get_supabase", return_value=mock_sb):
        _tag_lead_phone_uncertain("lead-abc")

    # Only one insert call: lead_tags (no tag creation)
    insert_calls = mock_sb.table.return_value.insert.call_args_list
    assert len(insert_calls) == 1
    # Verify it was for lead_tags
    args = insert_calls[0][0][0]
    assert args == {"lead_id": "lead-abc", "tag_id": "tag-existing"}
