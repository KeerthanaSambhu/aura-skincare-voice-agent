"""18. Invalid inputs and graceful error handling: no stack traces, no internals."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import FrozenClock


def assert_error(response_text: str) -> None:
    for leak in ("Traceback", 'File "', "sqlite3", ".py", "Exception"):
        assert leak not in response_text


@pytest.mark.parametrize(
    "body",
    [
        {"opened": "maybe"},
        {"reason": "changed my mind"},
        {"has_photos": "yes please"},
        {"opened": False, "reason": "unwanted", "refund": True},  # unknown field
    ],
)
def test_return_body_validation(client: TestClient, body: dict[str, object]) -> None:
    response = client.post("/api/orders/ORD-102/return-eligibility", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert_error(response.text)


def test_malformed_json(client: TestClient) -> None:
    response = client.post(
        "/api/orders/ORD-102/return-eligibility", content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422
    assert_error(response.text)


@pytest.mark.parametrize(
    "params",
    [
        {},  # neither
        {"order_value": "699", "order_id": "ORD-101"},  # both
        {"order_value": "-5"},
        {"order_value": "0"},
        {"order_value": "abc"},
        {"order_value": "1.234"},  # more than 2 decimals
        {"order_value": "99999999"},  # above the sanity cap
    ],
)
@pytest.mark.parametrize("endpoint", ["/api/policies/shipping", "/api/policies/cod"])
def test_policy_query_validation(client: TestClient, endpoint: str, params: dict[str, str]) -> None:
    response = client.get(endpoint, params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_policy_query_unknown_order(client: TestClient) -> None:
    assert client.get("/api/policies/cod", params={"order_id": "ORD-000"}).status_code == 404


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_database_errors_become_503_without_details(client: TestClient, db_path: Path) -> None:
    with closing(sqlite3.connect(db_path)) as conn, conn:
        conn.execute("DROP TABLE orders")
    response = client.get("/api/orders/ORD-101")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DATABASE_UNAVAILABLE"
    assert_error(response.text)
    assert "no such table" not in response.text


def test_unexpected_errors_become_500_without_details(
    tmp_path: Path, clock: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_: object, **__: object) -> None:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr("app.main.check_cancellation", boom)
    settings = Settings(database_path=tmp_path / "e.db", log_level="ERROR")
    with TestClient(create_app(settings, clock), raise_server_exceptions=False) as c:
        response = c.get("/api/orders/ORD-103/cancellation-eligibility")
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "INTERNAL_ERROR", "message": "Something went wrong on our side."}}
    assert "secret internal detail" not in response.text


def test_logs_are_json_and_skip_customer_names(client: TestClient) -> None:
    import io
    import json
    import logging

    from app.logging_config import JsonFormatter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("aura")
    logger.addHandler(handler)
    logger.setLevel("INFO")
    try:
        client.get("/api/orders/ORD-101")
    finally:
        logger.removeHandler(handler)

    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    lookup = next(e for e in events if e["event"] == "order_lookup")
    assert (lookup["order_id"], lookup["status"]) == ("ORD-101", "Out for Delivery")
    assert any(e["event"] == "request" and e["status"] == 200 for e in events)
    assert "Priya" not in stream.getvalue()


def test_invalid_settings_rejected() -> None:
    with pytest.raises(ValueError):
        Settings(app_timezone="Mars/Olympus")
    with pytest.raises(ValueError):
        Settings(log_level="LOUD")
