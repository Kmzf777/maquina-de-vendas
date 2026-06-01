"""Phone normalization for LP webhook payloads.

Handles a wider range of raw inputs than the standard normalize_phone(),
which expects mostly clean E.164 strings from WhatsApp.
"""
import re
from typing import Literal, Tuple

from app.leads.service import normalize_phone

_DIGITS_RE = re.compile(r"[^\d]+")

PhoneConfidence = Literal["ok", "assumed_br", "uncertain"]


def normalize_lp_phone(raw: str) -> Tuple[str, PhoneConfidence]:
    """Normalize a raw phone string from a landing-page form submission.

    Returns:
        (normalized_phone, confidence) where confidence is one of:
            "ok"          — number was unambiguously recognized
            "assumed_br"  — assumed Brazilian number (prefix 55 added)
            "uncertain"   — could not confidently parse; digits returned as-is
    """
    if not raw or not raw.strip():
        return "", "uncertain"

    cleaned = raw.strip()

    # Step 2 — remove whatsapp: prefix
    if cleaned.lower().startswith("whatsapp:"):
        cleaned = cleaned[len("whatsapp:"):]

    # Step 3 — remove leading +
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    # Step 4 — replace leading 00 with nothing (international dialing prefix)
    if cleaned.startswith("00"):
        cleaned = cleaned[2:]

    # Strip remaining non-digit characters
    digits = _DIGITS_RE.sub("", cleaned)

    if not digits:
        return "", "uncertain"

    # --- Classify and normalize ---

    # 13+ digits starting with 55 → already full Brazilian mobile (with 9th digit)
    if len(digits) >= 13 and digits.startswith("55"):
        normalized = normalize_phone(digits)
        return normalized, "ok"

    # 12 digits starting with 55 → Brazilian mobile without 9th digit → inject 9
    if len(digits) == 12 and digits.startswith("55"):
        # normalize_phone already handles 12-digit 55-prefixed numbers
        normalized = normalize_phone(digits)
        return normalized, "ok"

    # 11 digits without 55 → local Brazilian number with area code + 9 digit
    if len(digits) == 11 and not digits.startswith("55"):
        normalized = normalize_phone("55" + digits)
        return normalized, "assumed_br"

    # 10 digits without 55 → local Brazilian number with area code, no 9th digit
    if len(digits) == 10 and not digits.startswith("55"):
        # Prepend 55 → 12 digits → normalize_phone will inject 9
        normalized = normalize_phone("55" + digits)
        return normalized, "assumed_br"

    # Any other case → return cleaned digits, mark as uncertain
    return digits, "uncertain"
