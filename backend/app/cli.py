"""Demo database commands. Run from the backend/ directory:

    python -m app.cli init-db     create and seed the database if it doesn't exist yet
    python -m app.cli reset-db    delete all orders and reseed the three sample orders
    python -m app.cli show        print the current orders

All commands respect DATABASE_PATH (env var or .env). Use --database to override.
"""

import argparse
import sys
from contextlib import closing
from pathlib import Path

from . import db
from .clock import utc_now
from .config import Settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Aura AI demo database commands")
    parser.add_argument("command", choices=["init-db", "reset-db", "show"])
    parser.add_argument("--database", type=Path, help="Path to the SQLite file (overrides DATABASE_PATH)")
    args = parser.parse_args(argv)

    settings = Settings()
    path: Path = args.database or settings.database_file
    now = utc_now()

    if args.command == "init-db":
        seeded = db.prepare_database(path, now, settings.tz)
        print(f"Seeded a new demo database at {path}" if seeded else f"{path} already has orders; left unchanged")
        return 0

    if args.command == "reset-db":
        db.prepare_database(path, now, settings.tz)
        with closing(db.connect(path)) as conn:
            db.reset_demo_data(conn, now, settings.tz)
            print(f"Reset {path}: {db.order_count(conn)} sample orders, timing anchored to {now.isoformat()}")
        return 0

    if not path.exists():
        print(f"No database at {path}. Run: python -m app.cli init-db", file=sys.stderr)
        return 1
    with closing(db.connect(path)) as conn:
        for row in conn.execute("SELECT order_id, status, value_inr, cancelled_at FROM orders ORDER BY order_id"):
            extra = f"  cancelled {row['cancelled_at']}" if row["cancelled_at"] else ""
            print(f"{row['order_id']}  {row['status']:<17} ₹{row['value_inr']}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
