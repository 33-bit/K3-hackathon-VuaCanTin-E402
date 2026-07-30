from __future__ import annotations

import re
from collections.abc import Sequence

from app.services.openai_service import QueryUnderstanding

_SPACE_RE = re.compile(r"\s+")
_DAY_RE = re.compile(r"\bday[\s_-]*0*(\d+)\b", re.IGNORECASE)
_RANGE_RE = re.compile(
    r"\b(?:slide|trang)\s*(\d+)\s*"
    r"(?:đến|tới|to|[-–])\s*(?:slide|trang)?\s*(\d+)\b",
    re.IGNORECASE,
)
_SINGLE_SLIDE_RE = re.compile(r"\bslide\s*(\d+)\b", re.IGNORECASE)
_PRIVATE_USE_RE = re.compile(r"[\ue000-\uf8ff]")

_ALL_DECK_PATTERNS = (
    r"\b(?:tóm tắt|summary|tổng hợp|ôn lại|tạo quiz|quiz).{0,120}"
    r"\b(?:tất cả|toàn bộ)\b.{0,40}\b(?:slide|trang|tài liệu|bài|bài giảng)\b",
    r"\btóm tắt\s+(?:lại\s+)?buổi học này\b",
    r"\btóm tắt.*\bbuổi đầu tiên\b",
    r"\btài liệu này\s+(?:đang\s+)?dạy\b",
    r"\bbài này\s+học về gì\b",
    r"\btổng hợp\s+toàn bộ\b",
    r"\btoàn bộ\s+những\s+kiến thức\b",
    r"\bkiến thức chính\s+trong\s+bài này\b",
)
_LOGISTICS_RE = re.compile(
    r"\b(?:deadline|hạn nộp|link nộp|cách nộp|nộp ở đâu|"
    r"hướng dẫn.{0,40}(?:làm|hoàn thành|nộp).{0,20}(?:lab|bài))\b",
    re.IGNORECASE,
)


def route_query(
    *,
    question: str,
    selected_text: str | None,
    explicit_ranges: Sequence[tuple[int, int]],
    language: str,
    deck_title: str | None,
    first_slide_title: str | None,
    current_slide_title: str | None,
    slide_count: int,
) -> QueryUnderstanding | None:
    """Apply deterministic product rules before probabilistic query understanding."""
    normalized = _normalize(question)
    english = not language.lower().startswith("vi")

    direct = _policy_response(question=question, normalized=normalized, english=english)
    if direct is not None:
        return direct

    deck_identity = _clean_title(first_slide_title or deck_title or "deck đang mở")
    requested_day = _extract_day(question)
    actual_day = _extract_day(deck_identity)
    if requested_day is not None and actual_day is not None and requested_day != actual_day:
        answer = (
            f"The open deck is {deck_identity}, not Day {requested_day}. "
            f"Do you want to open/upload Day {requested_day}, or did you mean slide "
            f"{requested_day} in the current deck?"
            if english
            else (
                f"Deck đang mở là {deck_identity}, không phải Day {requested_day}. "
                f"Bạn muốn mở/upload tài liệu Day {requested_day}, hay đang muốn hỏi "
                f"slide số {requested_day} của deck hiện tại?"
            )
        )
        return _direct_query(
            question=question,
            mode="clarify",
            reason_code="deck_reference_mismatch",
            answer=answer,
            insufficient=True,
        )

    if _is_ambiguous_comparison(normalized, selected_text, explicit_ranges):
        answer = (
            "Which two concepts or slides would you like me to compare?"
            if english
            else "Bạn muốn mình so sánh hai khái niệm hoặc hai slide nào?"
        )
        return _direct_query(
            question=question,
            mode="clarify",
            reason_code="ambiguous_comparison",
            answer=answer,
            insufficient=True,
        )

    requested_ranges = list(explicit_ranges)
    if not requested_ranges:
        range_match = _RANGE_RE.search(question)
        if range_match:
            requested_ranges = [
                (int(range_match.group(1)), int(range_match.group(2)))
            ]
        else:
            slide_match = _SINGLE_SLIDE_RE.search(question)
            if slide_match and requested_day is None:
                number = int(slide_match.group(1))
                requested_ranges = [(number, number)]

    if requested_ranges:
        return _range_query(
            question=question,
            requested_ranges=requested_ranges,
            slide_count=slide_count,
            logistics_requested=bool(_LOGISTICS_RE.search(normalized)),
            english=english,
        )

    if any(re.search(pattern, normalized, re.IGNORECASE) for pattern in _ALL_DECK_PATTERNS):
        return QueryUnderstanding(
            rewritten_query=question,
            scope="range",
            intent="all_deck_summary",
            slide_start=1,
            slide_end=slide_count,
            generation_question=question,
        )

    if _LOGISTICS_RE.search(normalized):
        answer = (
            "The open deck does not contain the submission deadline, submission link, "
            "or official lab-submission procedure. Please check the LMS/Discord announcement "
            "or ask the TA."
            if english
            else (
                "Tài liệu đang mở không chứa deadline, link nộp hoặc quy trình nộp lab "
                "chính thức. Bạn hãy kiểm tra LMS/Discord hoặc hỏi TA."
            )
        )
        return _direct_query(
            question=question,
            mode="insufficient",
            reason_code="logistics_not_in_deck",
            answer=answer,
            insufficient=True,
        )

    if selected_text and _has_text_extraction_warning(selected_text):
        notice = (
            "The unusual symbol is likely a PDF font/glyph extraction error, so there is "
            "not enough evidence to treat it as an official formula."
            if english
            else (
                "Ký hiệu lạ có khả năng là lỗi font/glyph khi trích xuất PDF, nên không "
                "đủ căn cứ để coi đó là một công thức chính thức."
            )
        )
        return QueryUnderstanding(
            rewritten_query=question,
            scope="current_slide",
            intent="explain_selected_text",
            generation_question=(
                "Explain only the readable surrounding text. Do not interpret the unusual "
                "glyph as an official formula."
                if english
                else (
                    "Chỉ giải thích phần văn bản đọc được xung quanh và không diễn giải "
                    "ký tự glyph lạ như một công thức chính thức."
                )
            ),
            notices=[notice],
            force_insufficient=True,
            reason_code="text_extraction_warning",
        )

    if selected_text or re.search(
        r"\b(?:slide|trang|đoạn)\s+này\b",
        normalized,
        re.IGNORECASE,
    ):
        return QueryUnderstanding(
            rewritten_query=question,
            scope="current_slide",
            intent="explain_current_context",
            generation_question=question,
        )
    return None


def normalize_range_query(
    query: QueryUnderstanding,
    *,
    question: str,
    slide_count: int,
    language: str,
) -> QueryUnderstanding:
    """Validate model-produced ranges against canonical deck metadata."""
    if query.scope != "range":
        return query
    start = query.slide_start or 1
    end = query.slide_end or slide_count
    return _range_query(
        question=question,
        requested_ranges=[(start, end)],
        slide_count=slide_count,
        logistics_requested=bool(_LOGISTICS_RE.search(_normalize(question))),
        english=not language.lower().startswith("vi"),
        intent=query.intent,
        rewritten_query=query.rewritten_query,
    )


def _policy_response(
    *,
    question: str,
    normalized: str,
    english: bool,
) -> QueryUnderstanding | None:
    if re.search(
        r"\b(?:system prompt|openai_api_key|qdrant_api_key|api[_ ]?key|secret)\b",
        normalized,
        re.IGNORECASE,
    ):
        answer = (
            "I cannot reveal system prompts, API keys, or other internal secrets."
            if english
            else "Mình không thể tiết lộ system prompt, API key hoặc secret nội bộ."
        )
        return _direct_query(
            question=question,
            mode="refuse",
            reason_code="secret_exfiltration",
            answer=answer,
        )

    if re.search(
        r"\b(?:sửa|đổi|cập nhật).{0,30}\bđiểm\b|"
        r"\bđánh dấu.{0,30}\bhoàn thành\b",
        normalized,
        re.IGNORECASE,
    ):
        answer = (
            "I do not have permission to change grades or completion status in the LMS. "
            "If the record is wrong, please contact the TA or course operations team."
            if english
            else (
                "Mình không có quyền thay đổi điểm hoặc trạng thái hoàn thành trên LMS. "
                "Nếu dữ liệu đang sai, bạn hãy liên hệ TA hoặc ban vận hành khóa học."
            )
        )
        return _direct_query(
            question=question,
            mode="refuse",
            reason_code="unauthorized_lms_action",
            answer=answer,
        )

    graded_assessment = re.search(
        r"\b(?:quiz|bài kiểm tra|bài thi|exam)\b",
        normalized,
        re.IGNORECASE,
    ) and re.search(
        r"\b(?:chấm điểm|copy\s*nộp|đáp án cuối|nộp bài)\b",
        normalized,
        re.IGNORECASE,
    )
    if graded_assessment:
        answer = (
            "I cannot provide a final answer for a graded assessment to copy and submit. "
            "I can explain the concept, give step-by-step hints, or create a similar practice "
            "question."
            if english
            else (
                "Đây là bài đang chấm điểm nên mình không thể đưa đáp án cuối để bạn copy "
                "nộp. Mình có thể giải thích khái niệm, đưa gợi ý từng bước hoặc tạo một "
                "câu luyện tập tương tự."
            )
        )
        return _direct_query(
            question=question,
            mode="refuse",
            reason_code="graded_assessment",
            answer=answer,
        )

    if re.search(
        r"\b(?:viết|làm).{0,30}\b(?:trọn|toàn bộ).{0,30}\b(?:báo cáo|bài)\b|"
        r"\bnộp nguyên văn\b|\bbịa.{0,30}\bsố liệu\b",
        normalized,
        re.IGNORECASE,
    ):
        answer = (
            "I cannot write an entire submission for you or fabricate evaluation data. "
            "I can help create an outline, explain concepts, or review your draft."
            if english
            else (
                "Mình không thể viết trọn bài để bạn nộp nguyên văn hoặc bịa số liệu đánh "
                "giá. Mình có thể hỗ trợ lập dàn ý, giải thích kiến thức hoặc review bản "
                "nháp của bạn."
            )
        )
        return _direct_query(
            question=question,
            mode="refuse",
            reason_code="assignment_fabrication",
            answer=answer,
        )

    if re.search(
        r"\b(?:số điện thoại|email cá nhân|địa chỉ nhà|thông tin liên hệ cá nhân)\b",
        normalized,
        re.IGNORECASE,
    ):
        answer = (
            "I cannot provide or guess a teacher's personal contact information. It is not "
            "present in the deck; please use an official course contact channel."
            if english
            else (
                "Mình không thể cung cấp hoặc suy đoán số điện thoại, email cá nhân của "
                "giảng viên. Thông tin này không có trong deck; bạn hãy dùng kênh liên hệ "
                "chính thức của khóa học."
            )
        )
        return _direct_query(
            question=question,
            mode="refuse",
            reason_code="personal_information",
            answer=answer,
            insufficient=True,
        )
    return None


def _range_query(
    *,
    question: str,
    requested_ranges: Sequence[tuple[int, int]],
    slide_count: int,
    logistics_requested: bool,
    english: bool,
    intent: str = "range_summary",
    rewritten_query: str | None = None,
) -> QueryUnderstanding:
    starts = [min(start, end) for start, end in requested_ranges]
    ends = [max(start, end) for start, end in requested_ranges]
    requested_start = min(starts)
    requested_end = max(ends)
    valid_start = max(1, requested_start)
    valid_end = min(slide_count, requested_end)

    if valid_start > valid_end:
        answer = (
            f"The open deck has {slide_count} slides, so slides {requested_start}–"
            f"{requested_end} do not exist."
            if english
            else (
                f"Deck đang mở chỉ có {slide_count} slide, nên phạm vi slide "
                f"{requested_start}–{requested_end} không tồn tại."
            )
        )
        return _direct_query(
            question=question,
            mode="insufficient",
            reason_code="range_out_of_bounds",
            answer=answer,
            insufficient=True,
        )

    notices: list[str] = []
    if requested_start < 1 or requested_end > slide_count:
        notices.append(
            f"The open deck has only {slide_count} slides. I used the available range "
            f"{valid_start}–{valid_end}; the remaining requested slides do not exist."
            if english
            else (
                f"Deck đang mở chỉ có {slide_count} slide. Mình chỉ sử dụng phạm vi "
                f"{valid_start}–{valid_end}; phần slide còn lại trong yêu cầu không tồn tại."
            )
        )
    if logistics_requested:
        notices.append(
            "The deck does not contain the official lab-completion or submission "
            "procedure. Please check the LMS/Discord announcement or ask the TA."
            if english
            else (
                "Deck không có hướng dẫn chính thức về cách hoàn thành hoặc nộp lab. "
                "Bạn hãy kiểm tra LMS/Discord hoặc hỏi TA."
            )
        )

    action = (
        "Summarize"
        if re.search(r"\b(?:tóm tắt|tổng hợp|summary)\b", question, re.I)
        else "Explain"
    )
    generation_question = (
        f"{action} only the available slides {valid_start} through {valid_end}."
        if english
        else (
            f"{'Tóm tắt' if action == 'Summarize' else 'Giải thích'} chỉ nội dung đang có "
            f"từ slide {valid_start} đến slide {valid_end}."
        )
    )
    return QueryUnderstanding(
        rewritten_query=rewritten_query or question,
        scope="range",
        intent=intent,
        slide_start=valid_start,
        slide_end=valid_end,
        generation_question=generation_question if notices else question,
        notices=notices,
        force_insufficient=bool(notices),
        reason_code="partial_range" if notices else None,
    )


def _direct_query(
    *,
    question: str,
    mode: str,
    reason_code: str,
    answer: str,
    insufficient: bool = False,
) -> QueryUnderstanding:
    return QueryUnderstanding(
        rewritten_query=question,
        response_mode=mode,  # type: ignore[arg-type]
        reason_code=reason_code,
        direct_answer=answer,
        force_insufficient=insufficient,
    )


def _extract_day(text: str) -> int | None:
    match = _DAY_RE.search(text)
    return int(match.group(1)) if match else None


def _is_ambiguous_comparison(
    normalized: str,
    selected_text: str | None,
    explicit_ranges: Sequence[tuple[int, int]],
) -> bool:
    if selected_text or explicit_ranges:
        return False
    return bool(
        re.search(
            r"\b(?:so sánh|phân biệt)\s+(?:hai|2)\s+"
            r"(?:cái|thứ|khái niệm)\s+này\b",
            normalized,
            re.IGNORECASE,
        )
    )


def _has_text_extraction_warning(text: str) -> bool:
    return bool(_PRIVATE_USE_RE.search(text) or "\ufffd" in text)


def _normalize(text: str) -> str:
    return _SPACE_RE.sub(" ", text).strip().casefold()


def _clean_title(text: str) -> str:
    return _SPACE_RE.sub(" ", _PRIVATE_USE_RE.sub("-", text)).strip()
