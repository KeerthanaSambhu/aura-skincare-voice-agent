"""11-14. Standard returns (7-day window, unopened) and damaged/defective claims (48 h, photos)."""

import sqlite3
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tests.conftest import SEED_TIME


def set_delivered(conn: sqlite3.Connection, order_id: str, ago: timedelta) -> None:
    conn.execute(
        "UPDATE orders SET status = 'Delivered', delivered_at = ? WHERE order_id = ?",
        ((SEED_TIME - ago).isoformat(), order_id),
    )


def check_return(client: TestClient, order_id: str, **body: object) -> dict[str, object]:
    response = client.post(f"/api/orders/{order_id}/return-eligibility", json=body)
    assert response.status_code == 200, response.text
    result: dict[str, object] = response.json()
    return result


# ── 11. The 7-day window ────────────────────────────────────────────────────


def test_ord_102_outside_window_even_if_unopened(client: TestClient) -> None:
    """The brief's example: delivered 14 days ago, so no return regardless of condition."""
    body = check_return(client, "ORD-102", opened=False, reason="unwanted")
    assert (body["outcome"], body["eligible"], body["reason_code"]) == ("NOT_ELIGIBLE", False, "OUTSIDE_RETURN_WINDOW")
    assert "Don't promise a return or refund" in str(body["next_step"])
    assert body["details"]["days_since_delivery"] == 14  # type: ignore[index]


def test_brief_example_20_days_opened(client: TestClient, conn: sqlite3.Connection) -> None:
    """'I bought this 20 days ago and have opened it' -> outside policy."""
    set_delivered(conn, "ORD-102", timedelta(days=20))
    assert check_return(client, "ORD-102", opened=True, reason="unwanted")["eligible"] is False


@pytest.mark.parametrize(
    "ago,eligible",
    [
        (timedelta(days=1), True),
        (timedelta(days=6, hours=23), True),
        (timedelta(days=7), True),  # exactly 7 days: inclusive
        (timedelta(days=7, seconds=1), False),
        (timedelta(days=8), False),
    ],
)
def test_window_boundaries(client: TestClient, conn: sqlite3.Connection, ago: timedelta, eligible: bool) -> None:
    set_delivered(conn, "ORD-102", ago)
    assert check_return(client, "ORD-102", opened=False, reason="unwanted")["eligible"] is eligible


def test_within_window_unopened_is_eligible_without_promising_refund(
    client: TestClient, conn: sqlite3.Connection
) -> None:
    set_delivered(conn, "ORD-102", timedelta(days=3))
    body = check_return(client, "ORD-102", opened=False, reason="unwanted")
    assert (body["outcome"], body["reason_code"]) == ("ELIGIBLE", "WITHIN_WINDOW_UNOPENED")
    assert "original packaging" in str(body["next_step"])
    assert "don't quote refund dates" in str(body["next_step"])


# ── 12. Opened or used products ─────────────────────────────────────────────


def test_opened_within_window_is_not_eligible(client: TestClient, conn: sqlite3.Connection) -> None:
    set_delivered(conn, "ORD-102", timedelta(days=2))
    body = check_return(client, "ORD-102", opened=True, reason="unwanted")
    assert (body["outcome"], body["reason_code"]) == ("NOT_ELIGIBLE", "OPENED_OR_USED")
    assert "Don't promise a refund" in str(body["next_step"])


def test_unknown_opened_state_asks(client: TestClient, conn: sqlite3.Connection) -> None:
    set_delivered(conn, "ORD-102", timedelta(days=2))
    body = check_return(client, "ORD-102", reason="unwanted")
    assert (body["outcome"], body["eligible"], body["reason_code"]) == ("NEEDS_INFO", None, "OPENED_UNKNOWN")


def test_missing_reason_asks(client: TestClient) -> None:
    body = check_return(client, "ORD-102")
    assert (body["outcome"], body["reason_code"]) == ("NEEDS_INFO", "REASON_MISSING")


@pytest.mark.parametrize("oid,status", [("ORD-101", "Out for Delivery"), ("ORD-103", "Processing")])
def test_undelivered_orders_cannot_be_returned(client: TestClient, oid: str, status: str) -> None:
    body = check_return(client, oid, opened=False, reason="unwanted")
    assert (body["outcome"], body["reason_code"]) == ("NOT_ELIGIBLE", "NOT_DELIVERED")
    assert body["details"]["status"] == status  # type: ignore[index]


# ── 13. Damaged / defective: 48 hours ───────────────────────────────────────


@pytest.mark.parametrize("reason", ["damaged", "defective"])
@pytest.mark.parametrize(
    "ago,eligible",
    [
        (timedelta(hours=2), True),
        (timedelta(hours=48), True),  # exactly 48 h: inclusive
        (timedelta(hours=48, seconds=1), False),
        (timedelta(days=14), False),
    ],
)
def test_damage_window(
    client: TestClient, conn: sqlite3.Connection, reason: str, ago: timedelta, eligible: bool
) -> None:
    set_delivered(conn, "ORD-102", ago)
    body = check_return(client, "ORD-102", reason=reason, has_photos=True)
    assert body["check"] == "damage_claim"
    assert body["eligible"] is eligible
    if not eligible:
        assert body["reason_code"] == "OUTSIDE_DAMAGE_WINDOW"


def test_damage_claim_offers_replacement_not_refund(client: TestClient, conn: sqlite3.Connection) -> None:
    set_delivered(conn, "ORD-102", timedelta(hours=10))
    body = check_return(client, "ORD-102", reason="damaged", has_photos=True)
    assert body["details"]["remedy"] == "replacement"  # type: ignore[index]
    assert "not a refund" in str(body["next_step"])


def test_damaged_but_opened_still_qualifies(client: TestClient, conn: sqlite3.Connection) -> None:
    """Opening the box is how you find damage; the unopened rule is for standard returns."""
    set_delivered(conn, "ORD-102", timedelta(hours=10))
    assert check_return(client, "ORD-102", reason="damaged", opened=True, has_photos=True)["eligible"] is True


def test_ord_102_damage_claim_is_too_late(client: TestClient) -> None:
    body = check_return(client, "ORD-102", reason="damaged", has_photos=True)
    assert body["reason_code"] == "OUTSIDE_DAMAGE_WINDOW"
    assert "Don't promise a replacement or refund" in str(body["next_step"])


# ── 14. Photos ──────────────────────────────────────────────────────────────


def test_damage_without_photos_is_not_eligible(client: TestClient, conn: sqlite3.Connection) -> None:
    set_delivered(conn, "ORD-102", timedelta(hours=10))
    body = check_return(client, "ORD-102", reason="defective", has_photos=False)
    assert (body["outcome"], body["reason_code"]) == ("NOT_ELIGIBLE", "PHOTOS_REQUIRED")


def test_damage_photos_unknown_asks(client: TestClient, conn: sqlite3.Connection) -> None:
    set_delivered(conn, "ORD-102", timedelta(hours=10))
    body = check_return(client, "ORD-102", reason="damaged")
    assert (body["outcome"], body["eligible"], body["reason_code"]) == ("NEEDS_INFO", None, "PHOTOS_UNCONFIRMED")
