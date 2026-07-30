from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from .chatbot_placeholder import generate_mock_answer
from .models import ChatRequest, ChatResponse, UploadResponse


app = FastAPI(title="Folio Slide Tutor Mock API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "chatbot": "mock"}


@app.post("/api/upload", response_model=UploadResponse)
async def upload_slide(file: UploadFile = File(...)) -> UploadResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".ppt", ".pptx"}:
        raise HTTPException(status_code=400, detail="Upload a PDF, PPT, or PPTX file.")
    await file.read(1)
    return UploadResponse(
        deck_id=f"deck-{uuid4().hex[:8]}",
        name=Path(file.filename or "Untitled deck").stem,
        slide_count=12,
    )


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    # Integration boundary: swap this function for the real tutor pipeline.
    return generate_mock_answer(request)

