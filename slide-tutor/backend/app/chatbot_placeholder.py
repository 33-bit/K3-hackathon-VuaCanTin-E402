"""Replace this module with the real chatbot/RAG implementation later."""

from .models import ChatRequest, ChatResponse, Citation


def generate_mock_answer(request: ChatRequest) -> ChatResponse:
    referenced = sorted(
        {
            slide
            for ref in request.references
            for slide in range(ref.start, ref.end + 1)
        }
    ) or [3, 4]

    if request.selected_text:
        answer = (
            "The selected sentence is describing the attention bottleneck: "
            "a learner can hold only a few active ideas at once. The practical "
            "point is to group related details into one meaningful chunk, then "
            "connect that chunk to something already understood."
        )
    elif len(referenced) > 1:
        answer = (
            "Across these slides, the argument moves in three steps: first it "
            "defines the learning constraint, then introduces chunking as a "
            "strategy, and finally shows how retrieval practice makes those "
            "chunks easier to recall. In short: reduce load, organize meaning, "
            "then practise bringing it back without looking."
        )
    else:
        answer = (
            "This slide's key idea is that learning improves when information "
            "is actively reorganized, not merely reread. Try explaining the "
            "diagram in your own words before checking the labels again."
        )

    return ChatResponse(
        answer=answer,
        citations=[Citation(slide=n, label=f"Slide {n}") for n in referenced[:4]],
    )

