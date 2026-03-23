import csv
import io
import re
from dataclasses import dataclass


@dataclass
class ImportResult:
    valid: list[str]
    invalid: list[str]


def normalize_phone(phone: str) -> str | None:
    """Normalize a Brazilian phone number to international format (5511999999999).
    Returns None if invalid.
    """
    digits = re.sub(r"\D", "", phone)

    # Remove leading 0
    if digits.startswith("0"):
        digits = digits[1:]

    # Add country code if missing
    if len(digits) == 10 or len(digits) == 11:
        digits = "55" + digits
    elif len(digits) == 12 or len(digits) == 13:
        if not digits.startswith("55"):
            return None
    else:
        return None

    # Validate: 55 + 2 digit DDD + 8-9 digit number
    if len(digits) < 12 or len(digits) > 13:
        return None

    return digits


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
