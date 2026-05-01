import csv
import io
import re
from dataclasses import dataclass

from app.leads.service import normalize_phone as _canonical_normalize


@dataclass
class ImportResult:
    valid: list[str]
    invalid: list[str]


def normalize_phone(phone: str) -> str | None:
    """Normalize a Brazilian phone number to E.164 without '+'.
    Handles missing country code, then delegates to canonical normalization
    (which includes 9th digit injection for 12-digit BR numbers).
    Returns None if the number is structurally invalid.
    """
    digits = re.sub(r"\D", "", phone)

    if digits.startswith("0"):
        digits = digits[1:]

    if len(digits) in (10, 11):
        digits = "55" + digits
    elif len(digits) in (12, 13):
        if not digits.startswith("55"):
            return None
    else:
        return None

    if len(digits) not in (12, 13):
        return None

    return _canonical_normalize(digits)


def parse_csv(file_content: str | bytes) -> ImportResult:
    """Parse a CSV file and extract valid phone numbers."""
    if isinstance(file_content, bytes):
        file_content = file_content.decode("utf-8-sig")

    valid = []
    invalid = []

    reader = csv.reader(io.StringIO(file_content))
    header = next(reader, None)

    # Find phone column
    phone_col = 0
    if header:
        for i, col in enumerate(header):
            if col.strip().lower() in ("phone", "telefone", "numero", "whatsapp", "celular"):
                phone_col = i
                break

    for row in reader:
        if not row or len(row) <= phone_col:
            continue

        raw = row[phone_col].strip()
        if not raw:
            continue

        normalized = normalize_phone(raw)
        if normalized:
            valid.append(normalized)
        else:
            invalid.append(raw)

    return ImportResult(valid=valid, invalid=invalid)
