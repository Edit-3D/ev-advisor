import pytest
from fastapi.testclient import TestClient

from backend.app.agents.workflow import get_workflow
from backend.app.agents.errors import AgentExecutionError, WorkflowDeadlineExceeded
from backend.app.main import app, get_chat_workflow


client = TestClient(app)


class FakeWorkflow:
    def invoke(self, message: str, conversation_id: str, **kwargs) -> dict:
        return {
            "reply": f"Agent response to: {message}",
            "citations": [],
            "agents_invoked": ["vehicle"],
            "tools_called": ["search_vehicles"],
        }


@pytest.fixture(autouse=True)
def fake_workflow() -> None:
    app.dependency_overrides[get_chat_workflow] = lambda: FakeWorkflow()
    yield
    app.dependency_overrides.clear()


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat() -> None:
    response = client.post("/chat", json={"message": "I need a family EV"})

    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Agent response to: I need a family EV"
    assert body["conversation_id"]
    assert body["agents_invoked"] == ["vehicle"]
    assert body["tools_called"] == ["search_vehicles"]


def test_chat_reuses_conversation_id() -> None:
    response = client.post(
        "/chat", json={"message": "Follow up", "conversation_id": "existing-session"}
    )
    assert response.status_code == 200
    assert response.json()["conversation_id"] == "existing-session"


def test_chat_rejects_empty_message() -> None:
    response = client.post("/chat", json={"message": ""})

    assert response.status_code == 422


def test_chat_reports_missing_gemini_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.dependency_overrides.pop(get_chat_workflow)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_workflow.cache_clear()

    response = client.post("/chat", json={"message": "Hello"})

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "configuration_error",
        "message": "EV Advisor is not configured correctly.",
    }


class ProviderFailureWorkflow:
    def invoke(self, message: str, conversation_id: str, **kwargs) -> dict:
        provider_error = type("APIError", (RuntimeError,), {})("sensitive provider detail")
        provider_error.code = 503
        raise AgentExecutionError("agent failed") from provider_error


class UnexpectedFailureWorkflow:
    def invoke(self, message: str, conversation_id: str, **kwargs) -> dict:
        raise AgentExecutionError("internal implementation detail")


class DeadlineFailureWorkflow:
    def invoke(self, message: str, conversation_id: str, **kwargs) -> dict:
        raise AgentExecutionError("agent deadline reached") from WorkflowDeadlineExceeded(
            "internal deadline detail"
        )


def test_chat_returns_safe_structured_provider_error() -> None:
    app.dependency_overrides[get_chat_workflow] = lambda: ProviderFailureWorkflow()
    response = client.post("/chat", json={"message": "Hello", "conversation_id": "provider-test"})

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "ai_provider_unavailable",
        "message": "The AI service is temporarily unavailable. Please try again shortly.",
    }
    assert "sensitive" not in response.text


def test_chat_distinguishes_unexpected_server_failure() -> None:
    app.dependency_overrides[get_chat_workflow] = lambda: UnexpectedFailureWorkflow()
    response = client.post("/chat", json={"message": "Hello", "conversation_id": "server-test"})

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "generation_failed"


def test_chat_returns_clear_request_deadline_error() -> None:
    app.dependency_overrides[get_chat_workflow] = lambda: DeadlineFailureWorkflow()
    response = client.post(
        "/chat", json={"message": "Hello", "conversation_id": "deadline-test"}
    )

    assert response.status_code == 504
    assert response.json()["detail"] == {
        "code": "request_timeout",
        "message": "This response took too long. Please try again.",
    }
    assert "internal deadline" not in response.text


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
