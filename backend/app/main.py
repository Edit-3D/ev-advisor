from uuid import uuid4

from fastapi import FastAPI
from fastapi import Depends, HTTPException
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
        raise HTTPException(status_code=503, detail=str(error)) from error


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    workflow: EVAdvisorWorkflow = Depends(get_chat_workflow),
) -> ChatResponse:
    conversation_id = request.conversation_id or uuid4().hex
    try:
        result = workflow.invoke(request.message, conversation_id)
    except AgentConfigurationError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except AgentExecutionError as error:
        raise HTTPException(
            status_code=502,
            detail="EV Advisor could not complete the request. Please try again.",
        ) from error
    result.pop("_diagnostics", None)
    return ChatResponse(conversation_id=conversation_id, **result)
