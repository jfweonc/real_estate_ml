from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence


DEFAULT_INVALID_ZIP5 = {"00000"}


def normalize_zip5(postal_code: str | None, invalid_zip5: Iterable[str] | None = None) -> str | None:
    """Normalize postal codes to ZIP5, dropping values in the invalid set."""
    if not postal_code:
        return None
    digits = "".join(ch for ch in str(postal_code) if ch.isdigit())
    if len(digits) < 5:
        return None
    z = digits[:5]
    invalid = set(invalid_zip5) if invalid_zip5 is not None else DEFAULT_INVALID_ZIP5
    return None if z in invalid else z


def to_domain(property_type: str | None) -> str:
    return "RENTAL" if (property_type or "").strip().lower() == "rental" else "SALE"


def canon_dt_iso8601(dt_str: str | None) -> str | None:
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(str(dt_str).replace("Z", "+00:00"))
    except Exception:
        try:
            dt = datetime.strptime(str(dt_str), "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    if not dt.tzinfo:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canon_date(value: str | None) -> str | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except Exception:
            continue
    return None


def canon_money(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    s = str(value).strip().replace(",", "")
    if s.startswith("$"):
        s = s[1:]
    try:
        return f"{float(s):.2f}"
    except Exception:
        return None


def canon_int(value: str | None) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return digits or None


__all__ = [
    "DEFAULT_INVALID_ZIP5",
    "normalize_zip5",
    "to_domain",
    "canon_dt_iso8601",
    "canon_date",
    "canon_money",
    "canon_int",
]
