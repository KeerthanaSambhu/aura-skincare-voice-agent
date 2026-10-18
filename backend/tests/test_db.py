"""10. Seeding, reset and reseed, startup behaviour, schema constraints, the CLI."""

import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import cli, db
from app.config import Settings
from app.main import create_app
from tests.conftest import SEED_TIME, FrozenClock

IST = ZoneInfo("Asia/Kolkata")


def rows(path: Path) -> dict[str, sqlite3.Row]:
    with closing(db.connect(path)) as conn:
        return {r["order_id"]: r for r in conn.execute("SELECT * FROM orders")}


def test_seed_contains_exactly_the_three_brief_orders(db_path: Path) -> None:
    assert db.prepare_database(db_path, SEED_TIME, IST) is True
    data = rows(db_path)
    assert sorted(data) == ["ORD-101", "ORD-102", "ORD-103"]
    assert [(r["customer_name"], r["value_inr"], r["status"]) for r in data.values()] == [
        ("Priya Sharma", 699, "Out for Delivery"),
        ("Rahul Verma", 499, "Delivered"),
        ("Ananya Patel", 850, "Processing"),
    ]


def test_relative_times_are_anchored_to_seed_time(db_path: Path) -> None:
    db.prepare_database(db_path, SEED_TIME, IST)
    data = rows(db_path)
    assert data["ORD-102"]["delivered_at"] == (SEED_TIME - timedelta(days=14)).isoformat()
    assert data["ORD-103"]["ordered_at"] == (SEED_TIME - timedelta(hours=3)).isoformat()
    assert data["ORD-101"]["expected_delivery_by"] == "2026-10-17T18:00:00+05:30"


def test_startup_never_overwrites_existing_data(db_path: Path, settings: Settings, clock: FrozenClock) -> None:
    with TestClient(create_app(settings, clock)) as c:
        c.post("/api/orders/ORD-103/cancel")
    clock.advance(days=3)
    with TestClient(create_app(settings, clock)) as c:  # second startup
        assert c.get("/api/orders/ORD-103").json()["status"] == "Cancelled"
    assert db.prepare_database(db_path, clock(), IST) is False


def test_reset_restores_seed_and_reanchors_time(db_path: Path, client: TestClient, clock: FrozenClock) -> None:
    client.post("/api/orders/ORD-103/cancel")
    assert rows(db_path)["ORD-103"]["status"] == "Cancelled"

    later = SEED_TIME + timedelta(days=2)
    with closing(db.connect(db_path)) as conn:
        db.reset_demo_data(conn, later, IST)
        assert db.order_count(conn) == 3
        assert conn.execute("SELECT value FROM demo_meta WHERE key='seeded_at'").fetchone()[0] == later.isoformat()

    data = rows(db_path)
    assert data["ORD-103"]["status"] == "Processing" and data["ORD-103"]["cancelled_at"] is None
    assert data["ORD-102"]["delivered_at"] == (later - timedelta(days=14)).isoformat()

    clock.now = later
    assert client.get("/api/orders/ORD-103/cancellation-eligibility").json()["eligible"] is True
    assert client.post("/api/orders/ORD-103/cancel").status_code == 200  # ORD-103 is testable again


def test_reset_removes_orders_that_are_not_in_the_brief(db_path: Path) -> None:
    db.prepare_database(db_path, SEED_TIME, IST)
    with closing(db.connect(db_path)) as conn:
        conn.execute(
            "INSERT INTO orders (order_id, customer_name, product, value_inr, status) "
            "VALUES ('ORD-900', 'X', 'Y', 1, 'Processing')"
        )
        db.reset_demo_data(conn, SEED_TIME, IST)
    assert sorted(rows(db_path)) == ["ORD-101", "ORD-102", "ORD-103"]


@pytest.mark.parametrize("column,value", [("status", "Lost"), ("value_inr", -1), ("order_id", "XYZ-1")])
def test_schema_rejects_invalid_values(db_path: Path, column: str, value: object) -> None:
    db.prepare_database(db_path, SEED_TIME, IST)
    with closing(db.connect(db_path)) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute(f"UPDATE orders SET {column} = ? WHERE order_id = 'ORD-101'", (value,))


def test_cli_init_reset_show(db_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["init-db", "--database", str(db_path)]) == 0
    assert "Seeded a new demo database" in capsys.readouterr().out
    assert cli.main(["init-db", "--database", str(db_path)]) == 0
    assert "left unchanged" in capsys.readouterr().out

    with closing(db.connect(db_path)) as conn:
        conn.execute("UPDATE orders SET status = 'Cancelled' WHERE order_id = 'ORD-103'")
    assert cli.main(["reset-db", "--database", str(db_path)]) == 0
    assert rows(db_path)["ORD-103"]["status"] == "Processing"

    assert cli.main(["show", "--database", str(db_path)]) == 0
    out = capsys.readouterr().out
    assert "ORD-103  Processing" in out


def test_cli_show_without_database(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["show", "--database", str(tmp_path / "missing.db")]) == 1
    assert "init-db" in capsys.readouterr().err
