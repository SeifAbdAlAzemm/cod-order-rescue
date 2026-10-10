"""Deterministic text and phone normalization (Arabic-aware)."""

from __future__ import annotations

import re

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"})
_DIACRITICS = re.compile(r"[ً-ْـ]")  # harakat + tatweel
_NON_WORD = re.compile(r"[^\w\s]")


def normalize_text(text: str | None) -> str:
    """Lower-case, unify Arabic letter variants and digits, drop punctuation, collapse spaces."""
    if not text:
        return ""
    t = _DIACRITICS.sub("", text.translate(_DIGITS).lower()).translate(_LETTERS)
    return " ".join(_NON_WORD.sub(" ", t).split())


def normalize_phone(raw: str | None) -> str:
    """'+20 100 000 0008' / '00201000000008' / '٠١٠٠٠٠٠٠٠٠٨' -> '01000000008'. No validation here."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw.translate(_DIGITS))
    if digits.startswith("0020"):
        digits = "0" + digits[4:]
    elif digits.startswith("20") and len(digits) == 12:
        digits = "0" + digits[2:]
    return digits


def is_grounded(value: str | None, source: str | None) -> bool:
    """True if `value` literally appears (token-aligned, after normalization) in `source`.

    Used to refuse extracted fields that the customer never actually supplied.
    """
    v, s = normalize_text(value), normalize_text(source)
    return bool(v) and f" {v} " in f" {s} "
