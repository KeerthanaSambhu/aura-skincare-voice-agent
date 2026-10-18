"""1. Health endpoint."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import FrozenClock


def test_health_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_reports_unavailable_database(client: TestClient, db_path: Path) -> None:
    db_path.unlink()
    db_path.mkdir()  # a directory where the database file should be: SQLite can't open it
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "unavailable"}


def test_health_works_without_cors_preflight_issues(client: TestClient) -> None:
    response = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_request_id_header(client: TestClient) -> None:
    assert len(client.get("/health").headers["x-request-id"]) == 12


def test_unlisted_origin_gets_no_cors_header(tmp_path: Path, clock: FrozenClock) -> None:
    settings = Settings(database_path=tmp_path / "x.db", allowed_origins="https://aura.example", log_level="WARNING")
    with TestClient(create_app(settings, clock)) as c:
        response = c.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers
