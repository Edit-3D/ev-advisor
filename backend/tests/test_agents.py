from collections import defaultdict
from threading import Barrier

import pytest
from langchain_core.messages import AIMessage

from backend.app.agents.errors import AgentConfigurationError, AgentExecutionError
from backend.app.agents.tools import (
    charging_cost_tool,
    knowledge_search_tool,
    vehicle_search_tool,
)
from backend.app.agents.workflow import (
    EVAdvisorWorkflow,
    SpecialistResult,
    get_workflow,
)


def workflow_for(destination: str) -> EVAdvisorWorkflow:
    def specialist(name, messages):
        citations = (
            [
                {
                    "url": "https://example.com/source",
                    "title": "EV source",
                    "document_filename": "source.md",
                    "section_heading": "Evidence",
                }
            ]
            if name == "research"
            else []
        )
        return SpecialistResult(f"{name} evidence", [f"{name}_tool"], citations)

    return EVAdvisorWorkflow(
        None,
        router_override=lambda messages: destination,
        specialist_override=specialist,
        synthesis_override=lambda state: "combined answer",
    )


@pytest.mark.parametrize(
    ("destination", "expected_agents"),
    [
        ("vehicle", ["vehicle"]),
        ("research", ["research"]),
        ("both", ["vehicle", "research"]),
    ],
)
def test_supervisor_routes_to_expected_agents(destination, expected_agents) -> None:
    result = workflow_for(destination).invoke("question", f"route-{destination}")
    assert result["agents_invoked"] == expected_agents


@pytest.mark.parametrize("destination", ["vehicle", "research"])
def test_single_specialist_response_bypasses_synthesis(destination) -> None:
    def synthesis(state):
        raise AssertionError("single-specialist routes must not synthesize")

    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: destination,
        specialist_override=lambda name, messages: SpecialistResult(
            f"user-facing {name} answer",
            [f"{name}_tool"],
            [
                {
                    "url": "https://example.com/evidence",
                    "title": "Evidence",
                    "document_filename": "evidence.md",
                    "section_heading": "Details",
                }
            ]
            if name == "research"
            else [],
        ),
        synthesis_override=synthesis,
    )

    result = workflow.invoke("question", f"standalone-{destination}")

    assert result["reply"] == f"user-facing {destination} answer"
    assert result["tools_called"] == [f"{destination}_tool"]
    assert len(result["citations"]) == (1 if destination == "research" else 0)
    assert "synthesis" not in result["_diagnostics"]["stages_s"]


def test_empty_standalone_specialist_response_fails_safely() -> None:
    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: "vehicle",
        specialist_override=lambda name, messages: SpecialistResult("  ", [], []),
    )

    with pytest.raises(AgentExecutionError, match="empty response"):
        workflow.invoke("question", "empty-standalone")


def test_combined_specialists_run_concurrently_and_merge_state() -> None:
    rendezvous = Barrier(2, timeout=2)

    def specialist(name, messages):
        rendezvous.wait()
        citations = (
            [{"url": "https://example.com/cold", "title": "Cold weather", "document_filename": "cold.md", "section_heading": "Range"}]
            if name == "research"
            else []
        )
        return SpecialistResult(f"{name} evidence", [f"{name}_tool"], citations)

    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: "both",
        specialist_override=specialist,
        synthesis_override=lambda state: f"{state['vehicle_report']} + {state['research_report']}",
    )

    result = workflow.invoke("combined", "parallel-combined")

    assert result["reply"] == "vehicle evidence + research evidence"
    assert result["agents_invoked"] == ["vehicle", "research"]
    assert result["tools_called"] == ["vehicle_tool", "research_tool"]
    assert result["citations"][0]["url"] == "https://example.com/cold"


def test_combined_specialist_failure_prevents_synthesis() -> None:
    synthesis_called = False

    def specialist(name, messages):
        if name == "research":
            raise AgentExecutionError("research failed")
        return SpecialistResult("vehicle evidence", ["vehicle_tool"], [])

    def synthesis(state):
        nonlocal synthesis_called
        synthesis_called = True
        return "should not be returned"

    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: "both",
        specialist_override=specialist,
        synthesis_override=synthesis,
    )

    with pytest.raises(AgentExecutionError, match="research failed"):
        workflow.invoke("combined", "parallel-failure")
    assert synthesis_called is False


def test_existing_vehicle_and_research_tools_are_callable() -> None:
    vehicles = vehicle_search_tool.invoke({"manufacturer": "Tesla", "limit": 2})
    knowledge = knowledge_search_tool.invoke(
        {"query": "cold weather driving range", "top_k": 1}
    )
    cost = charging_cost_tool.invoke(
        {
            "energy_kwh": 60,
            "electricity_price_per_kwh": 2.5,
            "currency": "SEK",
            "charging_efficiency": 0.9,
        }
    )

    assert vehicles["returned_count"] == 2
    assert all(vehicle["brand"] == "Tesla" for vehicle in vehicles["results"])
    assert knowledge["results"][0]["source_urls"]
    assert cost["estimated_cost"] == 166.67
    assert cost["currency"] == "SEK"


def test_invalid_tool_arguments_are_rejected() -> None:
    with pytest.raises(Exception):
        vehicle_search_tool.invoke({"max_price": 500_000, "limit": 2})
    with pytest.raises(Exception):
        charging_cost_tool.invoke(
            {"energy_kwh": -1, "electricity_price_per_kwh": 2, "currency": "SEK"}
        )


class ToolErrorModel:
    def __init__(self) -> None:
        self.calls = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_vehicles",
                        "args": {"max_price": 10},
                        "id": "invalid-call",
                        "type": "tool_call",
                    }
                ],
            )
        return AIMessage(content="I could not use that invalid price filter safely.")


class DirectModel:
    def invoke(self, messages):
        return AIMessage(content="Hello! Ask me about electric vehicles.")


class TransientDirectModel:
    def __init__(self) -> None:
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            raise TimeoutError("temporary provider timeout")
        return AIMessage(content="Recovered safely.")


class ModeCapturingModel:
    def __init__(self) -> None:
        self.system_prompts = []

    def bind_tools(self, tools, **kwargs):
        return self

    def invoke(self, messages):
        self.system_prompts.append(messages[0].content)
        return AIMessage(content="mode-aware answer")


def test_direct_route_skips_specialists() -> None:
    workflow = EVAdvisorWorkflow(
        DirectModel(), router_override=lambda messages: "direct"
    )
    result = workflow.invoke("Hello", "direct-route")
    assert result["reply"].startswith("Hello!")
    assert result["agents_invoked"] == []
    assert result["tools_called"] == []


def test_workflow_selects_specialist_output_mode_from_route() -> None:
    standalone_model = ModeCapturingModel()
    standalone = EVAdvisorWorkflow(
        standalone_model, router_override=lambda messages: "vehicle"
    )
    standalone.invoke("vehicle question", "standalone-mode")

    collaborative_model = ModeCapturingModel()
    collaborative = EVAdvisorWorkflow(
        collaborative_model,
        router_override=lambda messages: "both",
        synthesis_override=lambda state: "combined answer",
    )
    collaborative.invoke("combined question", "collaborative-mode")

    assert "Output mode: standalone" in standalone_model.system_prompts[0]
    assert len(collaborative_model.system_prompts) == 2
    assert all(
        "Output mode: collaborative" in prompt
        for prompt in collaborative_model.system_prompts
    )


def test_retryable_provider_timeout_is_retried_and_measured(monkeypatch) -> None:
    monkeypatch.setattr("backend.app.agents.workflow.time.sleep", lambda delay: None)
    model = TransientDirectModel()
    workflow = EVAdvisorWorkflow(model, router_override=lambda messages: "direct")

    result = workflow.invoke("Hello", "transient-timeout")

    assert result["reply"] == "Recovered safely."
    assert model.calls == 2
    assert result["_diagnostics"]["retry_count"] == 1
    assert [call["success"] for call in result["_diagnostics"]["gemini_calls"]] == [
        False,
        True,
    ]


def test_agent_recovers_from_tool_validation_error() -> None:
    workflow = EVAdvisorWorkflow(
        ToolErrorModel(),
        router_override=lambda messages: "vehicle",
        synthesis_override=lambda state: state["vehicle_report"],
    )
    result = workflow.invoke("Find a cheap EV", "tool-error")
    assert "invalid price filter" in result["reply"]
    assert result["tools_called"] == ["search_vehicles"]
    assert len(result["_diagnostics"]["gemini_calls"]) == 2
    assert "synthesis" not in result["_diagnostics"]["stages_s"]


def test_follow_up_context_is_preserved_and_sessions_are_isolated() -> None:
    seen = defaultdict(list)

    def router(messages):
        human_text = [message.content for message in messages if message.type == "human"]
        current = human_text[-1]
        seen[current] = human_text
        return "vehicle"

    workflow = EVAdvisorWorkflow(
        None,
        router_override=router,
        specialist_override=lambda name, messages: SpecialistResult("evidence", [], []),
        synthesis_override=lambda state: "answer",
    )
    workflow.invoke("Compare EX30 and IONIQ 5", "session-a")
    workflow.invoke("Which of those charges faster?", "session-a")
    workflow.invoke("Which of those is cheaper?", "session-b")

    assert seen["Which of those charges faster?"] == [
        "Compare EX30 and IONIQ 5",
        "Which of those charges faster?",
    ]
    assert seen["Which of those is cheaper?"] == ["Which of those is cheaper?"]


def test_missing_gemini_configuration_is_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    get_workflow.cache_clear()
    with pytest.raises(AgentConfigurationError, match="GEMINI_API_KEY"):
        get_workflow()
