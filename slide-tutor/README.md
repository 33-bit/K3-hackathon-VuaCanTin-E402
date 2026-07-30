# Folio — Slide Tutor UI Prototype

A Claude-inspired (not affiliated) desktop UI prototype for studying slide decks with an AI tutor. The chatbot is intentionally mocked; there is no RAG, LLM, embedding, or document parsing integration.

## Structure

- `frontend/` — Node.js + Vite + React UI
- `backend/` — FastAPI mock API and explicit chatbot placeholder

## Run

Terminal 1:

```bash
cd slide-tutor/backend
python3 -m uvicorn app.main:app --reload --port 8000
```

Terminal 2:

```bash
cd slide-tutor/frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

## Prototype interactions

- Upload a `.pdf`, `.ppt`, or `.pptx` to create a mocked deck.
- Open the deck menu to rename, switch, or remove decks.
- Navigate slides with thumbnails, arrow buttons, or keyboard arrows.
- Select text directly on a slide, then choose **Ask about selection**.
- Type `@` in the composer to cite one slide or insert a range such as `@1–@5`.
- Click cited slide chips in mock tutor responses to navigate back to the source.

## Chatbot integration boundary

Replace `generate_mock_answer()` in `backend/app/chatbot_placeholder.py` when the real RAG/chatbot pipeline is ready. Keep the `POST /api/chat` response shape stable to avoid changing the UI.

