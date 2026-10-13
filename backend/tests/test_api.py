from fastapi.testclient import TestClient

from backend.app.main import app


client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat() -> None:
    response = client.post("/chat", json={"message": "I need a family EV"})

    assert response.status_code == 200
    assert response.json() == {
        "reply": 'EV Advisor received: "I need a family EV". '
        "Full advice is coming in Stage 2."
    }


def test_chat_rejects_empty_message() -> None:
    response = client.post("/chat", json={"message": ""})

    assert response.status_code == 422


def test_local_frontend_is_allowed_by_cors() -> None:
    response = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
