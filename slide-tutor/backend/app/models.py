from pydantic import BaseModel, Field


class SlideReference(BaseModel):
    start: int = Field(ge=1)
    end: int = Field(ge=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    deck_id: str
    references: list[SlideReference] = []
    selected_text: str | None = None


class Citation(BaseModel):
    slide: int
    label: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    mode: str = "mock"


class UploadResponse(BaseModel):
    deck_id: str
    name: str
    slide_count: int
    status: str = "mock-processed"

