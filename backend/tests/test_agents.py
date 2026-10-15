from collections import defaultdict
from threading import Barrier, Event, Thread

import pytest
from langchain_core.messages import AIMessage

from backend.app.agents.errors import (
    AgentConfigurationError,
    AgentExecutionError,
    WorkflowDeadlineExceeded,
)
from backend.app.agents.prompts import (
    RESEARCH_PROMPT,
    SUPERVISOR_PROMPT,
    SYNTHESIS_PROMPT,
    VEHICLE_PROMPT,
)
from backend.app.agents.tools import (
    charging_cost_tool,
    knowledge_search_tool,
    vehicle_search_tool,
)
from backend.app.agents.workflow import (
    EVAdvisorWorkflow,
    SpecialistResult,
    _requests_manufacturer_links,
    _sanitize_source_links,
    _specific_source_urls,
    _strip_research_citations,
    _without_official_model_urls,
    get_workflow,
)
from backend.app.vehicles.official_urls import get_official_model_url


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


def test_vehicle_source_links_must_match_exact_official_tool_url() -> None:
    volvo_url = "https://www.volvocars.com/se/cars/ex30-electric/"
    tool_output = {
        "results": [
            {
                "source_url": "https://www.volvocars.com/intl/v/cars/ex30",
                "official_model_url": volvo_url,
            },
            {
                "source_url": "https://www.hyundai.com/",
                "official_model_url": None,
            },
        ]
    }

    allowed = _specific_source_urls(tool_output)
    answer = (
        f"[Volvo source]({volvo_url}) "
        "[Dataset provenance](https://www.volvocars.com/intl/v/cars/ex30) "
        "[Changed Volvo URL](https://www.volvocars.com/se/cars/ex30-electric) "
        "[Invented Hyundai URL](https://www.hyundai.com/se/sv) "
        "[Generic Hyundai homepage](https://www.hyundai.com/) "
        "<https://www.hyundai.com/se/sv> and https://www.hyundai.com/se/sv."
    )
    sanitized = _sanitize_source_links(answer, allowed)

    assert allowed == [volvo_url]
    assert f"[Volvo source]({volvo_url})" in sanitized
    assert "https://www.volvocars.com/intl/v/cars/ex30" not in sanitized
    assert "https://www.volvocars.com/se/cars/ex30-electric)" not in sanitized
    assert "https://www.hyundai.com" not in sanitized
    assert "Changed Volvo URL" in sanitized
    assert "Invented Hyundai URL" in sanitized


def test_normal_standalone_comparison_does_not_gain_an_unrequested_link() -> None:
    official_url = "https://www.volvocars.com/se/cars/ex30-electric/"
    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: "vehicle",
        specialist_override=lambda name, messages: SpecialistResult(
            (
                "The EX30 charges faster.\n\n"
                "For more information, visit the official manufacturer page:\n"
                f"- [Volvo EX30 Official Model URL]({official_url})"
            ),
            ["compare_vehicles"],
            [],
            [official_url],
        ),
    )

    result = workflow.invoke("Compare these vehicles", "comparison-without-links")

    assert result["reply"] == "The EX30 charges faster."
    assert official_url not in result["reply"]
    assert "Official Model URL" not in result["reply"]
    assert "For more information" not in result["reply"]


def test_explicit_official_link_survives_standalone_validation() -> None:
    official_url = "https://www.volvocars.com/se/cars/ex30-electric/"
    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: "vehicle",
        specialist_override=lambda name, messages: SpecialistResult(
            f"[Official Volvo EX30 page]({official_url})",
            ["search_vehicles"],
            [],
            [official_url],
        ),
    )

    result = workflow.invoke("Give me the official EX30 link", "explicit-link")

    assert result["reply"] == f"[Official Volvo EX30 page]({official_url})"


def test_ordinary_combined_synthesis_removes_manufacturer_links() -> None:
    volvo_url = "https://www.volvocars.com/se/cars/ex30-electric/"

    def specialist(name, messages):
        return SpecialistResult(
            f"{name} evidence",
            [f"{name}_tool"],
            [],
            [volvo_url] if name == "vehicle" else [],
        )

    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: "both",
        specialist_override=specialist,
        synthesis_override=lambda state: (
            f"[Volvo]({volvo_url}) and "
            "[Hyundai](https://www.hyundai.com/se/sv)"
        ),
    )

    result = workflow.invoke("compare", "source-link-synthesis")

    assert volvo_url not in result["reply"]
    assert "Volvo" not in result["reply"]
    assert "https://www.hyundai.com" not in result["reply"]
    assert "Hyundai" in result["reply"]


def test_prompts_forbid_reconstructed_source_links() -> None:
    assert "exact, non-null official_model_url returned by a vehicle" in VEHICLE_PROMPT
    assert "source_url field is immutable dataset provenance" in VEHICLE_PROMPT
    assert "never alter, localize, or reconstruct a URL" in SYNTHESIS_PROMPT
    assert "Do not mention manufacturer websites, links, URLs" in VEHICLE_PROMPT
    assert "unless the user explicitly requests them in the current turn" in SYNTHESIS_PROMPT
    assert "Manufacturer Model Trim/Variant (Year)" in VEHICLE_PROMPT
    assert "never show them unless the user explicitly requests IDs" in VEHICLE_PROMPT
    assert "Do not repeat this coverage" in VEHICLE_PROMPT
    assert "requests an unsupported manufacturer" in VEHICLE_PROMPT
    assert "never merge trims or\nmodel years" in VEHICLE_PROMPT
    assert "other trims\nor model years may differ" in VEHICLE_PROMPT
    assert 'Do not automatically append a "For more details"' in VEHICLE_PROMPT
    assert "Preserve natural configuration names" in SYNTHESIS_PROMPT
    assert "Do not expose internal vehicle IDs" in SYNTHESIS_PROMPT
    assert "displayed exclusively from structured metadata" in SYNTHESIS_PROMPT
    assert "Do not put research URLs" in RESEARCH_PROMPT
    assert "contextual follow-ups" in SUPERVISOR_PROMPT
    assert '"their links"' in SUPERVISOR_PROMPT


def test_unrequested_tool_output_hides_official_urls_without_mutating_it() -> None:
    official_url = "https://www.volvocars.com/se/cars/ex30-electric/"
    output = {
        "results": [{
            "id": "volvo:ex30:2025:base",
            "official_model_url": official_url,
            "source_url": "https://example.com/provenance",
        }]
    }

    redacted = _without_official_model_urls(output)

    assert "official_model_url" not in redacted["results"][0]
    assert redacted["results"][0]["source_url"] == "https://example.com/provenance"
    assert output["results"][0]["official_model_url"] == official_url


def test_rag_link_is_removed_when_unrequested_manufacturer_link_is_removed() -> None:
    official_url = "https://www.volvocars.com/se/cars/ex30-electric/"
    rag_url = "https://afdc.energy.gov/vehicles/electric-consumers"

    def specialist(name, messages):
        citations = [{
            "url": rag_url,
            "title": "EV consumer guide",
            "document_filename": "consumer.md",
            "section_heading": "Winter use",
        }] if name == "research" else []
        return SpecialistResult(
            f"{name} evidence",
            [f"{name}_tool"],
            citations,
            [official_url] if name == "vehicle" else [rag_url],
        )

    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: "both",
        specialist_override=specialist,
        synthesis_override=lambda state: (
            f"[Official model]({official_url}) [Knowledge source]({rag_url})"
        ),
    )

    result = workflow.invoke("compare winter use", "combined-link-preservation")

    assert official_url not in result["reply"]
    assert rag_url not in result["reply"]
    assert "Knowledge source" not in result["reply"]
    assert result["citations"][0]["url"] == rag_url


def test_explicit_manufacturer_link_survives_combined_validation() -> None:
    official_url = "https://www.volvocars.com/se/cars/ex30-electric/"
    rag_url = "https://afdc.energy.gov/vehicles/electric-consumers"

    def specialist(name, messages):
        citations = [{
            "url": rag_url,
            "title": "EV consumer guide",
            "document_filename": "consumer.md",
            "section_heading": "Winter use",
        }] if name == "research" else []
        return SpecialistResult(
            f"{name} evidence",
            [f"{name}_tool"],
            citations,
            [official_url] if name == "vehicle" else [rag_url],
        )

    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: "both",
        specialist_override=specialist,
        synthesis_override=lambda state: (
            f"[Official model]({official_url}) [Knowledge source]({rag_url})"
        ),
    )

    result = workflow.invoke(
        "Compare winter use and give me the official website",
        "combined-explicit-link",
    )

    assert official_url in result["reply"]
    assert rag_url not in result["reply"]
    assert "Knowledge source" not in result["reply"]
    assert result["citations"][0]["url"] == rag_url


def test_research_only_answer_moves_inline_citations_to_structured_metadata() -> None:
    rag_url = "https://example.com/winter-range"
    citation = {
        "url": rag_url,
        "title": "Winter Range Guide",
        "document_filename": "winter.md",
        "section_heading": "Cold weather",
    }
    report = (
        f"Cold increases resistance ([Winter Range Guide]({rag_url})) [1].\n\n"
        "- Precondition before departure.\n"
        "- Use seat heating efficiently.\n\n"
        "## Sources\n"
        f"- [Winter Range Guide]({rag_url})"
    )
    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: "research",
        specialist_override=lambda name, messages: SpecialistResult(
            report, ["search_ev_knowledge"], [citation, citation], [rag_url]
        ),
    )

    result = workflow.invoke("Why does winter reduce range?", "research-citations")

    assert result["reply"] == (
        "Cold increases resistance.\n\n"
        "- Precondition before departure.\n"
        "- Use seat heating efficiently."
    )
    assert result["citations"] == [citation]


def test_research_citation_cleanup_preserves_markdown_and_manufacturer_links() -> None:
    rag_url = "https://example.com/charging"
    manufacturer_url = "https://www.volvocars.com/se/cars/ex30-electric/"
    text = (
        "| Vehicle | Cost |\n| --- | ---: |\n| EX30 | €12 |\n\n"
        "1. Keep the calculation.\n"
        f"2. [Official EX30 page]({manufacturer_url})\n"
        f"3. Guidance ([Charging Guide]({rag_url}))."
    )
    cleaned = _strip_research_citations(
        text,
        [{"url": rag_url, "title": "Charging Guide"}],
    )

    assert "| EX30 | €12 |" in cleaned
    assert "1. Keep the calculation." in cleaned
    assert f"[Official EX30 page]({manufacturer_url})" in cleaned
    assert rag_url not in cleaned


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Compare the Volvo EX30 and Hyundai IONIQ 5.", False),
        ("Recommend an EV for winter.", False),
        ("Can you give me their links?", True),
        ("Can you get me links?", True),
        ("Give me the official EX30 website.", True),
        ("Can I have the manufacturer URLs?", True),
        ("Link me to the IONIQ 5 page.", True),
        ("Show me Volvo's official site.", True),
    ],
)
def test_manufacturer_link_intent_comes_from_user_request(
    message: str, expected: bool
) -> None:
    assert _requests_manufacturer_links(message) is expected


@pytest.mark.parametrize(
    "follow_up",
    [
        "Their links?",
        "Can you give me their links?",
        "Can you get me links?",
        "What are the official manufacturer websites?",
    ],
)
def test_contextual_link_follow_ups_use_history_and_curated_urls(
    follow_up: str,
) -> None:
    bmw_url = get_official_model_url("BMW", "i4")
    tesla_url = get_official_model_url("Tesla", "Model 3")
    assert bmw_url and tesla_url

    def router(messages):
        human_messages = [message.content for message in messages if message.type == "human"]
        if len(human_messages) == 2:
            assert human_messages[0] == "Compare the BMW i4 and Tesla Model 3."
            assert human_messages[1] == follow_up
        return "vehicle"

    def specialist(name, messages):
        human_messages = [message.content for message in messages if message.type == "human"]
        if len(human_messages) == 1:
            return SpecialistResult(
                "The BMW i4 and Tesla Model 3 have different strengths.",
                ["compare_vehicles"],
                [],
                [bmw_url, tesla_url],
            )
        return SpecialistResult(
            f"- [BMW i4]({bmw_url})\n- [Tesla Model 3]({tesla_url})",
            ["search_vehicles"],
            [],
            [bmw_url, tesla_url],
        )

    workflow = EVAdvisorWorkflow(
        None,
        router_override=router,
        specialist_override=specialist,
    )
    conversation_id = f"contextual-links-{abs(hash(follow_up))}"

    first = workflow.invoke(
        "Compare the BMW i4 and Tesla Model 3.", conversation_id
    )
    result = workflow.invoke(follow_up, conversation_id)

    assert "http" not in first["reply"]
    assert result["reply"] == (
        f"- [BMW i4]({bmw_url})\n- [Tesla Model 3]({tesla_url})"
    )
    assert result["agents_invoked"] == ["vehicle"]
    assert result["tools_called"] == ["search_vehicles"]


def test_missing_curated_url_is_explained_without_fabrication() -> None:
    invented_url = "https://manufacturer.example/not-reviewed"
    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: "vehicle",
        specialist_override=lambda name, messages: SpecialistResult(
            "The official manufacturer link is unavailable. "
            f"[Unverified page]({invented_url})",
            ["search_vehicles"],
            [],
            [],
        ),
    )

    result = workflow.invoke("Give me the official model link", "missing-link")

    assert "official manufacturer link is unavailable" in result["reply"]
    assert invented_url not in result["reply"]


def test_blank_tool_metadata_is_not_returned() -> None:
    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: "vehicle",
        specialist_override=lambda name, messages: SpecialistResult(
            "answer", ["", "  ", "compare_vehicles"], []
        ),
    )

    result = workflow.invoke("Compare two vehicles", "metadata-filtering")

    assert result["agents_invoked"] == ["vehicle"]
    assert result["tools_called"] == ["compare_vehicles"]


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


def test_retry_resumes_failed_checkpoint_without_duplicate_user_turn() -> None:
    attempts = 0
    observed_messages = []

    def specialist(name, messages):
        nonlocal attempts
        attempts += 1
        observed_messages.append([message.content for message in messages])
        if attempts == 1:
            raise AgentExecutionError("temporary failure")
        return SpecialistResult("recovered", ["search_vehicles"], [])

    workflow = EVAdvisorWorkflow(
        None,
        router_override=lambda messages: "vehicle",
        specialist_override=specialist,
    )

    with pytest.raises(AgentExecutionError, match="temporary failure"):
        workflow.invoke("Find an EV", "retry-checkpoint")
    result = workflow.invoke("Find an EV", "retry-checkpoint", retry=True)

    assert result["reply"] == "recovered"
    assert observed_messages == [["Find an EV"], ["Find an EV"]]


def test_cooperative_cancellation_leaves_a_resumable_checkpoint() -> None:
    started = Event()
    release = Event()
    cancellation = Event()
    outcomes = []

    class BlockingThenSuccessfulModel:
        calls = 0

        def invoke(self, messages):
            self.calls += 1
            if self.calls == 1:
                started.set()
                assert release.wait(timeout=2)
            return AIMessage(content="completed")

    model = BlockingThenSuccessfulModel()
    workflow = EVAdvisorWorkflow(model, router_override=lambda messages: "direct")

    def run() -> None:
        try:
            workflow.invoke(
                "Hello",
                "cancel-checkpoint",
                cancellation_event=cancellation,
            )
        except AgentExecutionError as error:
            outcomes.append(error)

    thread = Thread(target=run)
    thread.start()
    assert started.wait(timeout=2)
    cancellation.set()
    release.set()
    thread.join(timeout=2)

    assert len(outcomes) == 1
    result = workflow.invoke("Hello", "cancel-checkpoint", retry=True)
    state = workflow.graph.get_state(
        {"configurable": {"thread_id": "cancel-checkpoint"}}
    )
    assert result["reply"] == "completed"
    assert [message.content for message in state.values["messages"]].count("Hello") == 1


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


def test_precise_vehicle_filters_are_applied_before_result_limit() -> None:
    result = vehicle_search_tool.invoke(
        {
            "manufacturer": " BMW ",
            "model": "i4",
            "model_year": 2024,
            "trim": "m50",
            "variant": " M50 ",
            "limit": 10,
        }
    )

    assert result["count"] == 1
    assert result["returned_count"] == 1
    assert result["results"][0]["id"] == "bmw:i4:2024:i4_m50"


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


class AdvancingTimeoutModel:
    def __init__(self, clock) -> None:
        self.clock = clock
        self.calls = 0

    def invoke(self, messages):
        self.calls += 1
        self.clock.current += 10
        raise TimeoutError("provider attempt timed out")


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


def test_request_deadline_prevents_retry_that_cannot_finish(monkeypatch) -> None:
    class Clock:
        current = 100.0

        def __call__(self) -> float:
            return self.current

    clock = Clock()
    model = AdvancingTimeoutModel(clock)
    workflow = EVAdvisorWorkflow(
        model,
        router_override=lambda messages: "direct",
        request_budget_seconds=70,
        provider_timeout_seconds=60,
        clock=clock,
    )
    monkeypatch.setattr("backend.app.agents.workflow.random.uniform", lambda *_: 0)

    with pytest.raises(AgentExecutionError) as raised:
        workflow.invoke("Hello", "deadline-exhausted")

    assert model.calls == 1
    assert isinstance(raised.value.__cause__, WorkflowDeadlineExceeded)


@pytest.mark.parametrize(
    ("request_budget", "provider_timeout"),
    [(0, 60), (165, 0)],
)
def test_request_deadline_configuration_must_be_positive(
    request_budget: float, provider_timeout: float
) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        EVAdvisorWorkflow(
            DirectModel(),
            request_budget_seconds=request_budget,
            provider_timeout_seconds=provider_timeout,
        )


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
