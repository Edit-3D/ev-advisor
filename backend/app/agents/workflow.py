from __future__ import annotations

import json
import logging
import os
import random
import time
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, Callable, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel
from google.genai.errors import APIError

from backend.app.agents.errors import AgentConfigurationError, AgentExecutionError
from backend.app.agents.prompts import (
    COLLABORATIVE_MODE_PROMPT,
    DIRECT_PROMPT,
    RESEARCH_PROMPT,
    STANDALONE_MODE_PROMPT,
    SUPERVISOR_PROMPT,
    SYNTHESIS_PROMPT,
    VEHICLE_PROMPT,
)
from backend.app.agents.tools import RESEARCH_TOOLS, VEHICLE_TOOLS


Destination = Literal["vehicle", "research", "both", "direct"]
LOGGER = logging.getLogger(__name__)
_DIAGNOSTICS: ContextVar[dict[str, Any] | None] = ContextVar("workflow_diagnostics", default=None)
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class RouteDecision(BaseModel):
    destination: Destination


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    destination: Destination
    vehicle_report: str | None
    research_report: str | None
    vehicle_tools: list[str]
    research_tools: list[str]
    research_citations: list[dict[str, str]]


@dataclass
class SpecialistResult:
    report: str
    tools_called: list[str]
    citations: list[dict[str, str]]


RouterOverride = Callable[[list[BaseMessage]], Destination]
SpecialistOverride = Callable[[str, list[BaseMessage]], SpecialistResult]
SynthesisOverride = Callable[[AgentState], str]


def _text(message: AIMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    parts = []
    for block in message.content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif isinstance(block, str):
            parts.append(block)
    return "\n".join(parts).strip()


def _history(messages: list[BaseMessage], limit: int = 12) -> list[BaseMessage]:
    return messages[-limit:]


class EVAdvisorWorkflow:
    def __init__(
        self,
        model: Any,
        *,
        checkpointer: InMemorySaver | None = None,
        router_override: RouterOverride | None = None,
        specialist_override: SpecialistOverride | None = None,
        synthesis_override: SynthesisOverride | None = None,
    ) -> None:
        self.model = model
        self.router_override = router_override
        self.specialist_override = specialist_override
        self.synthesis_override = synthesis_override
        self.graph = self._build_graph().compile(checkpointer=checkpointer or InMemorySaver())

    def _timed_invoke(self, stage: str, runnable: Any, messages: list[BaseMessage]) -> Any:
        diagnostics = _DIAGNOSTICS.get()
        max_retries = 2
        for attempt in range(max_retries + 1):
            started = time.perf_counter()
            try:
                result = runnable.invoke(messages)
                if diagnostics is not None:
                    diagnostics["gemini_calls"].append(
                        {"stage": stage, "attempt": attempt + 1, "duration_s": round(time.perf_counter() - started, 3), "success": True}
                    )
                return result
            except Exception as error:
                duration = time.perf_counter() - started
                status = getattr(error, "code", None) or getattr(error, "status_code", None)
                retryable = isinstance(error, (TimeoutError, APIError)) and (
                    isinstance(error, TimeoutError) or status in _RETRYABLE_STATUS_CODES
                )
                if diagnostics is not None:
                    diagnostics["gemini_calls"].append(
                        {
                            "stage": stage,
                            "attempt": attempt + 1,
                            "duration_s": round(duration, 3),
                            "success": False,
                            "error_type": type(error).__name__,
                            "status": status,
                            "retryable": retryable,
                        }
                    )
                if not retryable or attempt == max_retries:
                    raise
                if diagnostics is not None:
                    diagnostics["retry_count"] += 1
                delay = 0.5 * (2**attempt) + random.uniform(0, 0.1)
                LOGGER.warning(
                    "gemini_retry stage=%s attempt=%d error_type=%s status=%s delay_s=%.2f",
                    stage, attempt + 1, type(error).__name__, status, delay,
                )
                time.sleep(delay)

    def _record_stage(self, stage: str, started: float) -> None:
        diagnostics = _DIAGNOSTICS.get()
        if diagnostics is not None:
            diagnostics["stages_s"][stage] = round(
                diagnostics["stages_s"].get(stage, 0.0) + time.perf_counter() - started, 3
            )

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(AgentState)
        graph.add_node("supervisor", self._supervisor)
        graph.add_node("vehicle_agent", self._vehicle_agent)
        graph.add_node("research_agent", self._research_agent)
        graph.add_node(
            "parallel_specialists",
            lambda state: {"destination": state["destination"]},
        )
        graph.add_node("parallel_vehicle_agent", self._vehicle_agent)
        graph.add_node("parallel_research_agent", self._research_agent)
        graph.add_node("direct_response", self._direct_response)
        graph.add_node("finalize_specialist", self._finalize_specialist)
        graph.add_node("synthesize", self._synthesize)
        graph.add_edge(START, "supervisor")
        graph.add_conditional_edges(
            "supervisor",
            lambda state: state["destination"],
            {
                "vehicle": "vehicle_agent",
                "research": "research_agent",
                "both": "parallel_specialists",
                "direct": "direct_response",
            },
        )
        graph.add_conditional_edges(
            "parallel_specialists",
            lambda state: ["parallel_vehicle_agent", "parallel_research_agent"],
        )
        graph.add_edge("vehicle_agent", "finalize_specialist")
        graph.add_edge("research_agent", "finalize_specialist")
        graph.add_edge(
            ["parallel_vehicle_agent", "parallel_research_agent"], "synthesize"
        )
        graph.add_edge("direct_response", END)
        graph.add_edge("finalize_specialist", END)
        graph.add_edge("synthesize", END)
        return graph

    def _supervisor(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        messages = state.get("messages", [])
        try:
            if self.router_override:
                destination = self.router_override(_history(messages))
            else:
                router = self.model.with_structured_output(RouteDecision)
                decision = self._timed_invoke("supervisor", router, [SystemMessage(content=SUPERVISOR_PROMPT), *_history(messages)])
                destination = decision.destination
        except Exception as error:
            raise AgentExecutionError("The supervisor could not route the request.") from error
        finally:
            self._record_stage("supervisor", started)

        removals = [RemoveMessage(id=message.id) for message in messages[:-12] if message.id]
        return {
            "messages": removals,
            "destination": destination,
            "vehicle_report": None,
            "research_report": None,
            "vehicle_tools": [],
            "research_tools": [],
            "research_citations": [],
        }

    def _run_specialist(
        self,
        name: str,
        prompt: str,
        tools: list[BaseTool],
        messages: list[BaseMessage],
        *,
        collaborative: bool,
    ) -> SpecialistResult:
        if self.specialist_override:
            return self.specialist_override(name, _history(messages))

        tool_map = {tool.name: tool for tool in tools}
        mode_prompt = COLLABORATIVE_MODE_PROMPT if collaborative else STANDALONE_MODE_PROMPT
        transcript: list[BaseMessage] = [
            SystemMessage(content=f"{prompt}\n\n{mode_prompt}"),
            *_history(messages),
        ]
        tools_called: list[str] = []
        citations: list[dict[str, str]] = []
        for iteration in range(4):
            try:
                bound = self.model.bind_tools(
                    tools, tool_choice="any" if iteration == 0 else "auto"
                )
                response: AIMessage = self._timed_invoke(
                    f"{name}_agent", bound, transcript
                )
            except Exception as error:
                raise AgentExecutionError(f"The {name} agent could not call Gemini.") from error
            transcript.append(response)
            if not response.tool_calls:
                report = _text(response)
                if not report:
                    raise AgentExecutionError(f"The {name} agent returned an empty response.")
                return SpecialistResult(report, tools_called, citations)

            for call in response.tool_calls:
                tool_name = call.get("name", "unknown")
                tools_called.append(tool_name)
                tool_started = time.perf_counter()
                tool_success = False
                try:
                    selected_tool = tool_map[tool_name]
                    output = selected_tool.invoke(call.get("args", {}))
                    if tool_name == "search_ev_knowledge":
                        for item in output.get("results", []):
                            for url in item.get("source_urls", []):
                                citations.append(
                                    {
                                        "url": url,
                                        "title": item["document_title"],
                                        "document_filename": item["document_filename"],
                                        "section_heading": item["section_heading"],
                                    }
                                )
                    content = json.dumps(output, ensure_ascii=False, default=str)
                    tool_success = True
                except Exception as error:
                    content = json.dumps({"error": str(error)})
                finally:
                    diagnostics = _DIAGNOSTICS.get()
                    if diagnostics is not None:
                        diagnostics["tool_calls"].append(
                            {"name": tool_name, "duration_s": round(time.perf_counter() - tool_started, 3), "success": tool_success}
                        )
                transcript.append(
                    ToolMessage(
                        content=content,
                        tool_call_id=call.get("id", f"{tool_name}-{iteration}"),
                        name=tool_name,
                    )
                )
        raise AgentExecutionError(f"The {name} agent exceeded the tool-call limit.")

    def _vehicle_agent(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = self._run_specialist(
                "vehicle",
                VEHICLE_PROMPT,
                VEHICLE_TOOLS,
                state["messages"],
                collaborative=state["destination"] == "both",
            )
        finally:
            self._record_stage("vehicle_agent", started)
        return {
            "vehicle_report": result.report,
            "vehicle_tools": result.tools_called,
        }

    def _research_agent(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = self._run_specialist(
                "research",
                RESEARCH_PROMPT,
                RESEARCH_TOOLS,
                state["messages"],
                collaborative=state["destination"] == "both",
            )
        finally:
            self._record_stage("research_agent", started)
        unique_citations = {citation["url"]: citation for citation in result.citations}
        return {
            "research_report": result.report,
            "research_tools": result.tools_called,
            "research_citations": list(unique_citations.values()),
        }

    def _direct_response(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            response = self._timed_invoke("direct_response", self.model, [SystemMessage(content=DIRECT_PROMPT), *_history(state["messages"])])
            answer = _text(response)
        except Exception as error:
            raise AgentExecutionError("Gemini could not produce a response.") from error
        finally:
            self._record_stage("direct_response", started)
        return {"messages": [AIMessage(content=answer)]}

    def _finalize_specialist(self, state: AgentState) -> dict[str, Any]:
        report = (
            state.get("vehicle_report")
            if state["destination"] == "vehicle"
            else state.get("research_report")
        )
        if not report or not report.strip():
            raise AgentExecutionError("The specialist returned an empty response.")
        return {"messages": [AIMessage(content=report)]}

    def _synthesize(self, state: AgentState) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            if self.synthesis_override:
                answer = self.synthesis_override(state)
            else:
                evidence = {
                    "vehicle_report": state.get("vehicle_report"),
                    "research_report": state.get("research_report"),
                    "citations": state.get("research_citations", []),
                }
                response = self._timed_invoke(
                    "synthesis", self.model,
                    [
                        SystemMessage(content=SYNTHESIS_PROMPT),
                        *_history(state["messages"]),
                        HumanMessage(content=f"Specialist evidence:\n{json.dumps(evidence, ensure_ascii=False)}"),
                    ],
                )
                answer = _text(response)
        except Exception as error:
            raise AgentExecutionError("Gemini could not synthesize the specialist results.") from error
        finally:
            self._record_stage("synthesis", started)
        return {"messages": [AIMessage(content=answer)]}

    def invoke(self, message: str, conversation_id: str) -> dict[str, Any]:
        started = time.perf_counter()
        diagnostics: dict[str, Any] = {
            "gemini_calls": [], "tool_calls": [], "stages_s": {}, "retry_count": 0
        }
        token = _DIAGNOSTICS.set(diagnostics)
        try:
            result = self.graph.invoke(
                {"messages": [HumanMessage(content=message)]},
                config={"configurable": {"thread_id": conversation_id}},
            )
        except AgentExecutionError as error:
            diagnostics.update(
                total_duration_s=round(time.perf_counter() - started, 3),
                success=False,
                error_type=type(error.__cause__ or error).__name__,
            )
            LOGGER.error("workflow_diagnostics %s", json.dumps(diagnostics, default=str))
            raise
        except Exception as error:
            diagnostics.update(
                total_duration_s=round(time.perf_counter() - started, 3),
                success=False,
                error_type=type(error).__name__,
            )
            LOGGER.error("workflow_diagnostics %s", json.dumps(diagnostics, default=str))
            raise AgentExecutionError("The EV Advisor workflow failed.") from error
        finally:
            _DIAGNOSTICS.reset(token)
        diagnostics.update(total_duration_s=round(time.perf_counter() - started, 3), success=True)
        # Uvicorn's default production logging level reliably emits WARNING.
        LOGGER.warning("workflow_diagnostics %s", json.dumps(diagnostics, default=str))
        agents_invoked = []
        tools_called = []
        if result.get("vehicle_report") is not None:
            agents_invoked.append("vehicle")
            tools_called.extend(result.get("vehicle_tools", []))
        if result.get("research_report") is not None:
            agents_invoked.append("research")
            tools_called.extend(result.get("research_tools", []))
        return {
            "reply": _text(result["messages"][-1]),
            "citations": result.get("research_citations", []),
            "agents_invoked": agents_invoked,
            "tools_called": tools_called,
            "_diagnostics": diagnostics,
        }


@lru_cache(maxsize=1)
def get_workflow() -> EVAdvisorWorkflow:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise AgentConfigurationError("GEMINI_API_KEY is not configured on the backend.")
    model = ChatGoogleGenerativeAI(
        model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite"),
        api_key=api_key,
        temperature=0.1,
        request_timeout=60,
        retries=0,
    )
    return EVAdvisorWorkflow(model)
