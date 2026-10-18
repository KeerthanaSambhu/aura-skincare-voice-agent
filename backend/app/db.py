"""SQLite schema, seeding and reset for the mock order database.

Timestamps are stored as ISO-8601 strings in UTC. The assessment gives order
timing in relative terms ("delivered 14 days ago", "expected by 6 PM today"),
so seeding converts those into absolute timestamps anchored to the moment the
database is seeded. Resetting re-anchors them, which restores the brief's exact
relative wording.
"""

import sqlite3
from contextlib import closing
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import TypedDict
from zoneinfo import ZoneInfo

ORDER_STATUSES = ("Processing", "Shipped", "Out for Delivery", "Delivered", "Cancelled")

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS orders (
    order_id             TEXT PRIMARY KEY CHECK (order_id GLOB 'ORD-[0-9]*'),
    customer_name        TEXT NOT NULL,
    product              TEXT NOT NULL,
    value_inr            INTEGER NOT NULL CHECK (value_inr >= 0),
    status               TEXT NOT NULL CHECK (status IN ({", ".join(f"'{s}'" for s in ORDER_STATUSES)})),
    carrier              TEXT,
    tracking_id          TEXT,
    ordered_at           TEXT,  -- NULL when the brief doesn't say
    expected_delivery_by TEXT,
    delivered_at         TEXT,
    cancelled_at         TEXT
);

CREATE TABLE IF NOT EXISTS demo_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Phase 4: one row per voice call. Only a hash of the session secret is stored.
CREATE TABLE IF NOT EXISTS voice_sessions (
    session_id       TEXT PRIMARY KEY,
    secret_sha256    TEXT NOT NULL,
    status           TEXT NOT NULL CHECK (status IN ('active', 'ended')),
    created_at       TEXT NOT NULL,
    token_expires_at TEXT NOT NULL,
    ended_at         TEXT,
    end_reason       TEXT
);

-- Every tool call the model made in a session, as executed by this server.
CREATE TABLE IF NOT EXISTS voice_tool_calls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES voice_sessions(session_id),
    call_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    args_json   TEXT NOT NULL,
    ok          INTEGER NOT NULL CHECK (ok IN (0, 1)),
    order_id    TEXT,
    outcome     TEXT,
    result_json TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS voice_tool_calls_session ON voice_tool_calls(session_id);

CREATE TABLE IF NOT EXISTS voice_transcript_turns (
    session_id TEXT NOT NULL REFERENCES voice_sessions(session_id),
    seq        INTEGER NOT NULL,
    speaker    TEXT NOT NULL CHECK (speaker IN ('customer', 'agent')),
    text       TEXT NOT NULL,
    PRIMARY KEY (session_id, seq)
);

CREATE TABLE IF NOT EXISTS voice_summaries (
    session_id   TEXT PRIMARY KEY REFERENCES voice_sessions(session_id),
    summary_json TEXT NOT NULL
);
"""


class SeedOrder(TypedDict):
    order_id: str
    customer_name: str
    product: str
    value_inr: int
    status: str
    carrier: str | None
    tracking_id: str | None
    ordered_at: str | None
    expected_delivery_by: str | None
    delivered_at: str | None


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection. Autocommit mode: writes manage their own transactions."""
    conn = sqlite3.connect(path, timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def iso(moment: datetime) -> str:
    return moment.isoformat()


def build_seed_orders(seeded_at: datetime, tz: ZoneInfo) -> list[SeedOrder]:
    """The three sample orders from the assessment brief, and nothing else.

    Only timing the brief states is filled in. It doesn't say when ORD-101 or
    ORD-102 were ordered, so those stay NULL rather than being invented.
    """
    local_seed = seeded_at.astimezone(tz)
    six_pm_today = datetime.combine(local_seed.date(), time(18, 0), tzinfo=tz)

    return [
        {
            "order_id": "ORD-101",
            "customer_name": "Priya Sharma",
            "product": "Vitamin C Serum (30ml)",
            "value_inr": 699,
            "status": "Out for Delivery",
            "carrier": "BlueDart",
            "tracking_id": "BD-982103",
            "ordered_at": None,
            # "Expected by 6 PM today" is a fixed snapshot: lookups use only this time of
            # day and always say "today" (see orders.describe_timing).
            "expected_delivery_by": iso(six_pm_today),
            "delivered_at": None,
        },
        {
            "order_id": "ORD-102",
            "customer_name": "Rahul Verma",
            "product": "Hydrating Sunscreen SPF 50",
            "value_inr": 499,
            "status": "Delivered",
            "carrier": "Delhivery",
            "tracking_id": "DL-441029",
            "ordered_at": None,
            "expected_delivery_by": None,
            "delivered_at": iso(seeded_at - timedelta(days=14)),  # "Delivered 14 days ago"
        },
        {
            "order_id": "ORD-103",
            "customer_name": "Ananya Patel",
            "product": "Green Tea Face Wash + Toner",
            "value_inr": 850,
            "status": "Processing",
            "carrier": None,
            "tracking_id": None,
            "ordered_at": iso(seeded_at - timedelta(hours=3)),  # "Ordered 3 hours ago"
            "expected_delivery_by": None,
            "delivered_at": None,
        },
    ]


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def order_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0])


def _write_seed(conn: sqlite3.Connection, seeded_at: datetime, tz: ZoneInfo) -> None:
    conn.executemany(
        """INSERT INTO orders (order_id, customer_name, product, value_inr, status, carrier,
                               tracking_id, ordered_at, expected_delivery_by, delivered_at, cancelled_at)
           VALUES (:order_id, :customer_name, :product, :value_inr, :status, :carrier,
                   :tracking_id, :ordered_at, :expected_delivery_by, :delivered_at, NULL)""",
        build_seed_orders(seeded_at, tz),
    )
    conn.execute(
        "INSERT INTO demo_meta (key, value) VALUES ('seeded_at', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (iso(seeded_at),),
    )


def seed_if_empty(conn: sqlite3.Connection, seeded_at: datetime, tz: ZoneInfo) -> bool:
    """Seed a brand-new database. Never touches a database that already has orders."""
    init_schema(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        if order_count(conn) > 0:
            conn.execute("ROLLBACK")
            return False
        _write_seed(conn, seeded_at, tz)
        conn.execute("COMMIT")
        return True
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def reset_demo_data(conn: sqlite3.Connection, seeded_at: datetime, tz: ZoneInfo) -> None:
    """Delete every order and reseed the three sample orders, in one transaction."""
    init_schema(conn)
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM orders")
        _write_seed(conn, seeded_at, tz)
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def prepare_database(path: Path, seeded_at: datetime, tz: ZoneInfo) -> bool:
    """Create the file, schema and seed data if needed. Returns True if it seeded."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        return seed_if_empty(conn, seeded_at, tz)
