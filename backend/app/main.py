import asyncio
from threading import Event
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from backend.app.agents import EVAdvisorWorkflow, get_workflow
from backend.app.agents.errors import AgentConfigurationError, AgentExecutionError
from backend.app.models import ChatRequest, ChatResponse


app = FastAPI(title="EV Advisor API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_chat_workflow() -> EVAdvisorWorkflow:
    try:
        return get_workflow()
    except AgentConfigurationError as error:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "configuration_error",
                "message": "EV Advisor is not configured correctly.",
            },
        ) from error


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _root_error(error: BaseException) -> BaseException:
    current = error
    seen: set[int] = set()
    while current.__cause__ is not None and id(current) not in seen:
        seen.add(id(current))
        current = current.__cause__
    return current


def _execution_error_response(error: AgentExecutionError) -> HTTPException:
    cause = _root_error(error)
    status = getattr(cause, "code", None) or getattr(cause, "status_code", None)
    if isinstance(cause, TimeoutError) or status == 504:
        return HTTPException(
            status_code=504,
            detail={"code": "request_timeout", "message": "This response took too long. Please try again."},
        )
    if status in {429, 500, 502, 503}:
        return HTTPException(
            status_code=503,
            detail={
                "code": "ai_provider_unavailable",
                "message": "The AI service is temporarily unavailable. Please try again shortly.",
            },
        )
    return HTTPException(
        status_code=500,
        detail={
            "code": "generation_failed",
            "message": "Something went wrong while generating your response. Please try again.",
        },
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    workflow: EVAdvisorWorkflow = Depends(get_chat_workflow),
) -> ChatResponse:
    conversation_id = payload.conversation_id or uuid4().hex
    cancellation = Event()
    task = asyncio.create_task(
        asyncio.to_thread(
            workflow.invoke,
            payload.message,
            conversation_id,
            retry=payload.retry,
            cancellation_event=cancellation,
        )
    )
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=0.1)
            if await request.is_disconnected():
                cancellation.set()
                try:
                    await task
                except Exception:
                    pass
                raise HTTPException(status_code=499, detail={"code": "client_closed_request", "message": "Request cancelled."})
        result = await task
    except asyncio.CancelledError:
        cancellation.set()
        try:
            await asyncio.shield(task)
        except Exception:
            pass
        raise
    except AgentConfigurationError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "configuration_error", "message": "EV Advisor is not configured correctly."},
        ) from error
    except AgentExecutionError as error:
        raise _execution_error_response(error) from error
    result.pop("_diagnostics", None)
    return ChatResponse(conversation_id=conversation_id, **result)
