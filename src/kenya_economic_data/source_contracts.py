"""Small, verified source-contract helpers discovered during Phase 0."""

from __future__ import annotations

from datetime import date, datetime


def parse_cbk_date(value: str) -> date:
    """Parse either date representation observed in the official CBK CSV."""

    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise ValueError(f"unsupported CBK date: {value!r}")

