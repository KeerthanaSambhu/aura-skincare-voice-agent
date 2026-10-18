"""5-9 and 19. Cancellation eligibility, cancel_order, repeats, DB state, concurrency."""

import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.cancellation import CancelResult, cancel_order
from tests.conftest import SEED_TIME, FrozenClock

# ── 5-6. Eligibility ────────────────────────────────────────────────────────


def test_ord_103_is_eligible(client: TestClient) -> None:
    body = client.get("/api/orders/ORD-103/cancellation-eligibility").json()
    assert body["outcome"] == "ELIGIBLE"
    assert body["eligible"] is True
    assert body["reason_code"] == "STATUS_PROCESSING"
    assert "cancel_order" in body["next_step"]
    assert body["policy"].startswith("Orders can be cancelled only while their status is Processing.")


def test_ord_101_out_for_delivery_is_not_eligible(client: TestClient) -> None:
    body = client.get("/api/orders/ORD-101/cancellation-eligibility").json()
    assert body["outcome"] == "NOT_ELIGIBLE"
    assert body["eligible"] is False
    assert body["reason_code"] == "STATUS_OUT_FOR_DELIVERY"
    assert "refuse delivery at the doorstep" in body["next_step"]


def test_ord_102_delivered_is_not_eligible(client: TestClient) -> None:
    body = client.get("/api/orders/ORD-102/cancellation-eligibility").json()
    assert body["reason_code"] == "STATUS_DELIVERED"
    assert "return eligibility" in body["next_step"]


def test_shipped_status_is_not_eligible(client: TestClient, conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE orders SET status = 'Shipped' WHERE order_id = 'ORD-103'")
    body = client.get("/api/orders/ORD-103/cancellation-eligibility").json()
    assert (body["outcome"], body["reason_code"]) == ("NOT_ELIGIBLE", "STATUS_SHIPPED")


def test_eligibility_reads_current_database_status(client: TestClient, conn: sqlite3.Connection) -> None:
    assert client.get("/api/orders/ORD-103/cancellation-eligibility").json()["eligible"] is True
    conn.execute("UPDATE orders SET status = 'Out for Delivery' WHERE order_id = 'ORD-103'")
    assert client.get("/api/orders/ORD-103/cancellation-eligibility").json()["eligible"] is False


def test_eligibility_check_does_not_cancel(client: TestClient, order_status: Callable[[str], str]) -> None:
    client.get("/api/orders/ORD-103/cancellation-eligibility")
    assert order_status("ORD-103") == "Processing"


def test_eligibility_unknown_order(client: TestClient) -> None:
    assert client.get("/api/orders/ORD-404/cancellation-eligibility").status_code == 404


# ── 7-9. cancel_order ───────────────────────────────────────────────────────


def test_cancel_ord_103_succeeds_and_updates_db(
    client: TestClient, conn: sqlite3.Connection, clock: FrozenClock
) -> None:
    clock.advance(minutes=5)
    response = client.post("/api/orders/ord 103/cancel")
    assert response.status_code == 200
    body = response.json()
    assert body["cancelled"] is True
    assert body["outcome"] == "CANCELLED"
    assert (body["previous_status"], body["status"]) == ("Processing", "Cancelled")
    assert body["cancelled_at"] == clock.now.isoformat()
    assert "Mock assessment system" in body["note"]

    # 9. The database really changed, and only ORD-103 changed.
    rows = {r["order_id"]: (r["status"], r["cancelled_at"]) for r in conn.execute("SELECT * FROM orders")}
    assert rows["ORD-103"] == ("Cancelled", clock.now.isoformat())
    assert rows["ORD-101"] == ("Out for Delivery", None)
    assert rows["ORD-102"] == ("Delivered", None)


def test_lookup_after_cancel_reflects_new_state(client: TestClient) -> None:
    client.post("/api/orders/ORD-103/cancel")
    body = client.get("/api/orders/ORD-103").json()
    assert body["status"] == "Cancelled"
    assert body["timing"]["summary"] == "Cancelled today"
    assert body["timing"]["cancelled_at"] is not None
    eligibility = client.get("/api/orders/ORD-103/cancellation-eligibility").json()
    assert eligibility["reason_code"] == "ALREADY_CANCELLED"


def test_repeat_cancel_is_rejected_without_changing_timestamp(
    client: TestClient, conn: sqlite3.Connection, clock: FrozenClock
) -> None:
    first = client.post("/api/orders/ORD-103/cancel").json()
    clock.advance(minutes=10)
    second = client.post("/api/orders/ORD-103/cancel")
    assert second.status_code == 409
    assert second.json()["outcome"] == "ALREADY_CANCELLED"
    assert second.json()["cancelled"] is False
    stored = conn.execute("SELECT cancelled_at FROM orders WHERE order_id = 'ORD-103'").fetchone()[0]
    assert stored == first["cancelled_at"]


@pytest.mark.parametrize("oid,status", [("ORD-101", "Out for Delivery"), ("ORD-102", "Delivered")])
def test_cancel_ineligible_orders_is_409_and_db_unchanged(
    client: TestClient, order_status: Callable[[str], str], oid: str, status: str
) -> None:
    response = client.post(f"/api/orders/{oid}/cancel")
    assert response.status_code == 409
    body = response.json()
    assert (body["cancelled"], body["outcome"], body["status"]) == (False, "NOT_ELIGIBLE", status)
    assert order_status(oid) == status


def test_cancel_unknown_and_invalid(client: TestClient) -> None:
    assert client.post("/api/orders/ORD-555/cancel").json()["error"]["code"] == "ORDER_NOT_FOUND"
    assert client.post("/api/orders/nonsense/cancel").json()["error"]["code"] == "ORDER_ID_INVALID"


def test_cancel_get_method_not_allowed(client: TestClient, order_status: Callable[[str], str]) -> None:
    assert client.get("/api/orders/ORD-103/cancel").status_code == 405
    assert order_status("ORD-103") == "Processing"


def test_failed_update_rolls_back_and_reports_failure(
    db_path: Path, client: TestClient, conn: sqlite3.Connection
) -> None:
    """If the write fails, no success is reported and nothing changes."""
    conn.execute("""CREATE TRIGGER block_cancel BEFORE UPDATE ON orders
                    BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END""")
    response = client.post("/api/orders/ORD-103/cancel")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert "simulated" not in response.text
    assert conn.execute("SELECT status FROM orders WHERE order_id='ORD-103'").fetchone()[0] == "Processing"


# ── 19. Concurrent cancellation ─────────────────────────────────────────────


def test_concurrent_cancels_succeed_exactly_once(client: TestClient, db_path: Path) -> None:
    """Twelve threads, each with its own connection, try to cancel ORD-103 at the same instant."""
    workers = 12
    barrier = threading.Barrier(workers)
    results: list[CancelResult] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def attempt() -> None:
        try:
            with closing(db.connect(db_path)) as own_conn:
                barrier.wait()
                result = cancel_order(own_conn, "ORD-103", SEED_TIME)
            with lock:
                results.append(result)
        except BaseException as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=attempt) for _ in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, errors
    assert len(results) == workers
    assert sum(r.cancelled for r in results) == 1
    assert sorted(r.outcome for r in results) == ["ALREADY_CANCELLED"] * (workers - 1) + ["CANCELLED"]

    with closing(db.connect(db_path)) as check:
        status, cancelled_at = check.execute(
            "SELECT status, cancelled_at FROM orders WHERE order_id = 'ORD-103'"
        ).fetchone()
    assert status == "Cancelled"
    assert cancelled_at == next(r.cancelled_at for r in results if r.cancelled)


def test_concurrent_http_cancels(client: TestClient) -> None:
    barrier = threading.Barrier(6)
    codes: list[int] = []

    def attempt() -> None:
        barrier.wait()
        codes.append(client.post("/api/orders/ORD-103/cancel").status_code)

    threads = [threading.Thread(target=attempt) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(codes) == [200] + [409] * 5
