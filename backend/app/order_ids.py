"""Turn the many ways a customer (or a speech-to-text engine) writes an order ID
into the canonical form ORD-<digits>.

Accepted, case-insensitive: an optional ORD / ORDER / "order no." / "order number"
prefix, optional separators (space - _ . #), then ONE unbroken run of digits:
    ORD-101, ord 101, ORD101, ord_101, "Order 101", "order no. 101",
    "order number 101", "#101", "101"
Rejected: other letters or symbols ("ORD-1O1", "ABC-101"), and digits split by a
separator ("ORD-101-2"), which would otherwise silently become a different
order number (ORD-1012).
"""

import re

from .errors import order_id_invalid, order_id_missing

MAX_RAW_LENGTH = 64
_SEP = r"[\s\-_.#]*"
_PATTERN = re.compile(rf"^{_SEP}(?:(?:ORDER|ORD){_SEP}(?:(?:NUMBER|NUM|NO){_SEP})?)?(\d{{1,6}})$")


def normalize_order_id(raw: str | None) -> str:
    """Return the canonical order ID, or raise AppError (missing or invalid)."""
    if raw is None or not raw.strip():
        raise order_id_missing()
    if len(raw) > MAX_RAW_LENGTH:
        raise order_id_invalid(raw)
    match = _PATTERN.fullmatch(raw.strip().upper())
    if match is None:
        raise order_id_invalid(raw.strip())
    return f"ORD-{match.group(1)}"
