"""2-4. Order lookups, ID normalisation, unknown / malformed / missing IDs."""

import sqlite3
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import AppError
from app.main import create_app
from app.order_ids import normalize_order_id
from tests.conftest import SEED_TIME, FrozenClock

# ── 2. All three sample orders, exactly as in the brief ─────────────────────


def test_lookup_ord_101(client: TestClient) -> None:
    body = client.get("/api/orders/ORD-101").json()
    assert body["order_id"] == "ORD-101"
    assert body["customer_name"] == "Priya Sharma"
    assert body["product"] == "Vitamin C Serum (30ml)"
    assert body["value_inr"] == 699
    assert body["value_display"] == "₹699"
    assert body["status"] == "Out for Delivery"
    assert body["carrier"] == "BlueDart"
    assert body["tracking_id"] == "BD-982103"
    assert body["timing"]["expected_delivery_by"] == "2026-10-17T18:00:00+05:30"
    assert body["timing"]["expected_delivery_passed"] is None  # fixed snapshot: never evaluated
    assert body["timing"]["summary"] == "Expected by 6 PM today"
    assert "no live carrier tracking" in body["data_note"]
    assert "delivery estimates are fixed mock values" in body["data_note"]


def test_lookup_ord_102(client: TestClient) -> None:
    body = client.get("/api/orders/ORD-102").json()
    assert (body["customer_name"], body["product"], body["value_inr"], body["status"]) == (
        "Rahul Verma",
        "Hydrating Sunscreen SPF 50",
        499,
        "Delivered",
    )
    assert (body["carrier"], body["tracking_id"]) == ("Delhivery", "DL-441029")
    assert body["timing"]["days_since_delivery"] == 14
    assert body["timing"]["summary"] == "Delivered 14 days ago"


def test_lookup_ord_103(client: TestClient) -> None:
    body = client.get("/api/orders/ORD-103").json()
    assert (body["customer_name"], body["product"], body["value_inr"], body["status"]) == (
        "Ananya Patel",
        "Green Tea Face Wash + Toner",
        850,
        "Processing",
    )
    assert body["carrier"] is None and body["tracking_id"] is None
    assert body["timing"]["hours_since_order"] == 3
    assert body["timing"]["summary"] == "Ordered 3 hours ago"


def test_brief_gives_no_order_date_for_101_and_102(client: TestClient) -> None:
    for oid in ("ORD-101", "ORD-102"):
        assert client.get(f"/api/orders/{oid}").json()["timing"]["ordered_at"] is None


def test_other_orders_timing_still_relative_to_now(client: TestClient, clock: FrozenClock) -> None:
    """Only ORD-101's delivery estimate is a fixed snapshot; ORD-102 and ORD-103 still age."""
    clock.advance(days=1)
    assert client.get("/api/orders/ORD-102").json()["timing"]["summary"] == "Delivered 15 days ago"
    assert client.get("/api/orders/ORD-103").json()["timing"]["summary"] == "Ordered 27 hours ago"


# ORD-101's "Expected by 6 PM today" is a fixed mock snapshot (brief, section 4).
# It must read the same before and after 6 PM IST, on the seed day and later days.
@pytest.mark.parametrize(
    "ist_now",
    [
        "2026-10-17T10:00",  # seed time
        "2026-10-17T17:59",  # just before 6 PM
        "2026-10-17T18:00",  # exactly 6 PM
        "2026-10-17T18:01",  # just after 6 PM
        "2026-10-17T22:14",  # late evening
        "2026-10-17T23:59",  # last minute of the day (18:29 UTC)
        "2026-10-18T00:30",  # just after midnight IST, still 17 Oct in UTC
        "2026-10-18T19:00",  # after 6 PM the next day
        "2026-10-24T21:00",  # a week later, evening
    ],
)
def test_ord_101_always_expected_by_6pm_today(client: TestClient, clock: FrozenClock, ist_now: str) -> None:
    ist = ZoneInfo("Asia/Kolkata")
    clock.now = datetime.fromisoformat(ist_now).replace(tzinfo=ist).astimezone(UTC)
    timing = client.get("/api/orders/ORD-101").json()["timing"]
    assert timing["summary"] == "Expected by 6 PM today"
    assert timing["expected_delivery_passed"] is None
    # The stated time is 6 PM on the visitor's current IST date, never a past date.
    assert timing["expected_delivery_by"] == f"{ist_now[:10]}T18:00:00+05:30"


def test_seeded_after_6pm_still_says_expected_today(settings: Settings) -> None:
    """The case found in verification: seeding (or resetting) at 10:14 PM IST."""
    late = FrozenClock(datetime(2026, 10, 17, 22, 14, tzinfo=ZoneInfo("Asia/Kolkata")).astimezone(UTC))
    with TestClient(create_app(settings, late)) as c:
        timing = c.get("/api/orders/ORD-101").json()["timing"]
    assert timing["summary"] == "Expected by 6 PM today"


def test_no_delivery_estimate_once_delivered(client: TestClient, conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE orders SET status = 'Delivered', delivered_at = ? WHERE order_id = 'ORD-101'",
        (SEED_TIME.isoformat(),),
    )
    assert client.get("/api/orders/ORD-101").json()["timing"]["summary"] == "Delivered today"


# ── 3. Normalisation ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "ORD-101",
        "ord-101",
        "ord 101",
        "ORD101",
        "  ORD-101  ",
        "ord_101",
        "ORD.101",
        "Order 101",
        "order no. 101",
        "Order Number 101",
        "#101",
        "101",
        "ORD - 101",
    ],
)
def test_normalize_variants(raw: str) -> None:
    assert normalize_order_id(raw) == "ORD-101"


@pytest.mark.parametrize("raw", ["ord 101", "order number 102", "103"])
def test_lookup_through_api_with_variants(client: TestClient, raw: str) -> None:
    response = client.get(f"/api/orders/{raw}")
    assert response.status_code == 200
    assert response.json()["order_id"].startswith("ORD-10")


# ── 4. Unknown, malformed and missing IDs ───────────────────────────────────


@pytest.mark.parametrize("raw", ["ORD-999", "ORD-1010", "ORD-1", "999"])
def test_unknown_order_is_404_never_fabricated(client: TestClient, raw: str) -> None:
    response = client.get(f"/api/orders/{raw}")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "ORDER_NOT_FOUND"
    assert error["order_id"] == normalize_order_id(raw)
    assert "customer_name" not in response.json()


@pytest.mark.parametrize(
    "raw",
    ["abc", "ORD-1O1", "ABC-101", "ORD-101-2", "ORD 1 01", "1 01", "ORD-1234567", "ORD--", "ORD", "ORDNO", "x" * 65],
)
def test_malformed_ids_are_422(client: TestClient, raw: str) -> None:
    response = client.get(f"/api/orders/{raw}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ORDER_ID_INVALID"


@pytest.mark.parametrize("path", ["/api/orders", "/api/orders/%20", "/api/orders/%20%20%20"])
def test_missing_id_is_422(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ORDER_ID_MISSING"


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_normalize_missing(raw: str | None) -> None:
    with pytest.raises(AppError) as exc:
        normalize_order_id(raw)
    assert exc.value.code == "ORDER_ID_MISSING"


def test_long_input_is_truncated_in_message(client: TestClient) -> None:
    message = client.get("/api/orders/" + "z" * 60).json()["error"]["message"]
    assert "z" * 41 not in message
