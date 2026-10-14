from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)
    conversation_id: str | None = Field(
        default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$"
    )
    retry: bool = False


class Citation(BaseModel):
    url: str
    title: str
    document_filename: str
    section_heading: str


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    citations: list[Citation] = Field(default_factory=list)
    agents_invoked: list[str] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
