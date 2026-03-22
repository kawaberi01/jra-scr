from __future__ import annotations

from fastapi.testclient import TestClient

from hitl_tiny_counter.app import app


def test_counter_page_and_api_flow() -> None:
    client = TestClient(app)

    page = client.get("/")
    assert page.status_code == 200
    assert "Tiny Counter" in page.text

    reset = client.post("/api/reset")
    assert reset.status_code == 200
    assert reset.json() == {"value": 0}

    current = client.get("/api/value")
    assert current.status_code == 200
    assert current.json() == {"value": 0}

    increment = client.post("/api/increment")
    assert increment.status_code == 200
    assert increment.json() == {"value": 1}

    after_increment = client.get("/api/value")
    assert after_increment.status_code == 200
    assert after_increment.json() == {"value": 1}

    reset_again = client.post("/api/reset")
    assert reset_again.status_code == 200
    assert reset_again.json() == {"value": 0}
