from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_GOLDEN_SET = EVAL_DIR / "golden_set.json"
RESULTS_DIR = EVAL_DIR / "results"
REQUIRED_HARD_TYPES = {
    "source_truth",
    "ambiguity",
    "authority",
    "domain_harm",
}


def configure_utf8_console() -> None:
    """Keep Vietnamese output readable on Windows PowerShell code pages."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the VLearn Slide Tutor golden set against a ready deck. "
            "This runner calls only the product API and creates a review packet; "
            "it never calls a separate LLM judge."
        )
    )
    parser.add_argument(
        "--golden-set",
        type=Path,
        default=DEFAULT_GOLDEN_SET,
        help="Path to the golden-set JSON file.",
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:8000",
        help="Slide Tutor API base URL.",
    )
    parser.add_argument("--course-id", help="Course UUID used by the uploaded deck.")
    parser.add_argument("--deck-id", help="Ready deck UUID to evaluate.")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate golden-set structure and coverage without calling the API.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Run only the first N cases for a smoke test; this cannot be scored.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=0.2,
        help="Delay between product API calls.",
    )
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"{path} must contain one JSON object")
    return data


def validate_golden_set(golden: dict[str, Any]) -> dict[str, Any]:
    cases = golden.get("cases")
    if not isinstance(cases, list):
        raise TypeError("golden_set.json must contain a cases array")
    if len(cases) < 20:
        raise ValueError(f"Golden set needs at least 20 cases; found {len(cases)}")

    ids: list[str] = []
    type_counts: Counter[str] = Counter()
    origin_counts: Counter[str] = Counter()
    rarity_counts: Counter[str] = Counter()
    errors: list[str] = []

    for index, case in enumerate(cases, start=1):
        case_id = case.get("id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"case #{index}: missing id")
            continue
        ids.append(case_id)
        for field in ("title", "situation_type", "origin", "input", "expected"):
            if field not in case:
                errors.append(f"{case_id}: missing {field}")
        case_input = case.get("input", {})
        expected = case.get("expected", {})
        if not isinstance(case_input, dict) or not case_input.get("question"):
            errors.append(f"{case_id}: input.question is required")
        if not isinstance(expected, dict) or not expected.get("description"):
            errors.append(f"{case_id}: expected.description is required")
        type_counts[str(case.get("situation_type"))] += 1
        origin = case.get("origin", {})
        if not isinstance(origin, dict):
            errors.append(f"{case_id}: origin must be an object")
            origin = {}
        origin_type = str(origin.get("type"))
        origin_counts[origin_type] += 1
        if origin_type == "chatlog" and (
            not origin.get("evidence_id") or not origin.get("turn_id")
        ):
            errors.append(f"{case_id}: chatlog origin needs evidence_id and turn_id")
        rarity_counts[str(case.get("rarity", "unspecified"))] += 1

    duplicates = sorted(case_id for case_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        errors.append(f"duplicate case ids: {', '.join(duplicates)}")
    for situation_type in sorted(REQUIRED_HARD_TYPES):
        if type_counts[situation_type] < 2:
            errors.append(
                f"{situation_type} needs at least 2 cases; "
                f"found {type_counts[situation_type]}"
            )
    real_origin_count = origin_counts["chatlog"] + origin_counts["self_test"]
    if origin_counts["chatlog"] < 10:
        errors.append(
            "At least 10 cases must derive from real chatlog; "
            f"found {origin_counts['chatlog']}"
        )
    if real_origin_count < 10:
        errors.append(
            f"At least 10 real-observation cases are recommended; found {real_origin_count}"
        )
    quality_bar = golden.get("quality_bar")
    if not isinstance(quality_bar, dict):
        errors.append("quality_bar must be an object fixed before the first run")
    else:
        if quality_bar.get("total_cases") != len(cases):
            errors.append(
                "quality_bar.total_cases must equal the number of golden-set cases"
            )
        minimum_passed = quality_bar.get("minimum_passed_cases")
        if (
            not isinstance(minimum_passed, int)
            or isinstance(minimum_passed, bool)
            or not 1 <= minimum_passed <= len(cases)
        ):
            errors.append("quality_bar.minimum_passed_cases must be a valid integer")
    if errors:
        raise ValueError("\n".join(errors))

    return {
        "total": len(cases),
        "type_counts": dict(sorted(type_counts.items())),
        "origin_counts": dict(sorted(origin_counts.items())),
        "real_origin_count": real_origin_count,
        "rarity_counts": dict(sorted(rarity_counts.items())),
    }


def request_json(
    *,
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout_seconds: int = 180,
) -> tuple[int, dict[str, Any]]:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    request = Request(url=url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"raw_error": raw}
        return exc.code, parsed
    except URLError as exc:
        raise RuntimeError(f"Cannot connect to {url}: {exc.reason}") from exc


def load_slides(api_base: str, deck_id: str) -> list[dict[str, Any]]:
    status, payload = request_json(
        method="GET",
        url=f"{api_base.rstrip('/')}/api/decks/{deck_id}/slides",
        timeout_seconds=30,
    )
    if status != 200:
        raise RuntimeError(
            f"Cannot load slides for deck {deck_id}: HTTP {status} "
            f"{json.dumps(payload, ensure_ascii=False)}"
        )
    slides = payload.get("slides")
    if not isinstance(slides, list) or not slides:
        raise RuntimeError(f"Deck {deck_id} has no active slides")
    return slides


def build_request_payload(
    *,
    case: dict[str, Any],
    course_id: str,
    deck_id: str,
    slides_by_number: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    case_input = case["input"]
    slide_number = int(case_input["current_slide_number"])
    slide = slides_by_number.get(slide_number)
    if slide is None:
        raise ValueError(
            f"{case['id']}: current_slide_number {slide_number} "
            "does not exist in the target deck"
        )
    payload: dict[str, Any] = {
        "course_id": course_id,
        "deck_id": deck_id,
        "current_slide_id": slide["id"],
        "question": case_input["question"],
        "language": case_input.get("language", "vi"),
        "references": case_input.get("references", []),
    }
    selected_text = case_input.get("selected_text")
    if selected_text:
        payload["selected_text"] = selected_text
    return payload


def deterministic_checks(
    *,
    case: dict[str, Any],
    http_status: int,
    response: dict[str, Any],
    valid_slide_numbers: set[int],
) -> tuple[bool, list[str]]:
    """Check facts that do not require subjective semantic grading."""
    expected = case["expected"]
    failures: list[str] = []
    expected_status = int(expected.get("expected_http_status", 200))
    if http_status != expected_status:
        failures.append(f"HTTP {http_status}, expected {expected_status}")
        return False, failures
    if http_status != 200:
        return True, failures

    answer = response.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        failures.append("answer is empty")

    citations = response.get("citations")
    if not isinstance(citations, list):
        failures.append("citations is not an array")
        citations = []
    citation_slides = [
        int(citation["slide_number"])
        for citation in citations
        if isinstance(citation, dict) and citation.get("slide_number") is not None
    ]
    invalid_slides = sorted(set(citation_slides) - valid_slide_numbers)
    if invalid_slides:
        failures.append(f"citation references missing slides: {invalid_slides}")

    minimum = int(expected.get("min_citation_count", 0))
    maximum = expected.get("max_citation_count")
    if len(citation_slides) < minimum:
        failures.append(f"only {len(citation_slides)} citations; expected >= {minimum}")
    if maximum is not None and len(citation_slides) > int(maximum):
        failures.append(f"{len(citation_slides)} citations; expected <= {maximum}")
    if expected.get("require_multiple_citation_slides") and len(set(citation_slides)) < 2:
        failures.append("expected citations from multiple slides")

    allowed = expected.get("allowed_citation_slides")
    if allowed is not None:
        disallowed = sorted(set(citation_slides) - {int(value) for value in allowed})
        if disallowed:
            failures.append(f"citations outside allowed scope: {disallowed}")

    expected_insufficient = expected.get("expected_insufficient_evidence")
    if (
        isinstance(expected_insufficient, bool)
        and response.get("insufficient_evidence") is not expected_insufficient
    ):
        failures.append(
            "insufficient_evidence="
            f"{response.get('insufficient_evidence')!r}, "
            f"expected {expected_insufficient!r}"
        )
    return not failures, failures


def origin_reference(origin: dict[str, Any]) -> str:
    references = [
        value
        for value in (origin.get("evidence_id"), origin.get("turn_id"))
        if value
    ]
    return "/".join(str(value) for value in references) or str(
        origin.get("basis") or origin.get("observed_input") or ""
    )


def immutable_review_hash(case: dict[str, Any]) -> str:
    immutable = {
        key: case[key]
        for key in ("case_id", "input", "expected", "actual", "deterministic")
    }
    serialized = json.dumps(
        immutable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def build_review_packet(
    *,
    golden: dict[str, Any],
    coverage: dict[str, Any],
    results: list[dict[str, Any]],
    deck_id: str,
    run_id: str,
) -> dict[str, Any]:
    cases_by_id = {case["id"]: case for case in golden["cases"]}
    review_cases: list[dict[str, Any]] = []
    for result in results:
        case = cases_by_id[result["case_id"]]
        review_case = {
                "case_id": result["case_id"],
                "title": result["title"],
                "situation_type": result["situation_type"],
                "rarity": result["rarity"],
                "origin": case["origin"],
                "input": case["input"],
                "expected": case["expected"],
                "actual": {
                    "http_status": result["http_status"],
                    "latency_ms": result["latency_ms"],
                    "answer": result["answer"],
                    "citations": result["citations"],
                    "confidence": result["confidence"],
                    "insufficient_evidence": result["insufficient_evidence"],
                },
                "deterministic": {
                    "pass": result["deterministic_pass"],
                    "failures": result["deterministic_failures"],
                },
                "review": {
                    "reviewer": "",
                    "pass": None,
                    "reason": "",
                },
            }
        review_case["immutable_sha256"] = immutable_review_hash(review_case)
        review_cases.append(review_case)
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "golden_set": {
            "name": golden.get("name"),
            "version": golden.get("version"),
        },
        "deck_id": deck_id,
        "coverage": coverage,
        "quality_bar": golden.get("quality_bar", {}),
        "review_method": "human_or_codex",
        "instructions": [
            "Đọc input, expected, actual và deterministic của từng case.",
            "Chỉ dùng nội dung expected/golden set; không bổ sung kiến thức ngoài.",
            "Điền review.reviewer, review.pass=true|false và review.reason.",
            "Không đổi input, expected, actual, deterministic hoặc quality_bar.",
            "finalize_review.py sẽ từ chối nếu phần dữ liệu bất biến bị sửa.",
            "Sau khi chấm đủ, chạy: python eval/finalize_review.py <review-packet.json>.",
        ],
        "cases": review_cases,
    }


def write_run_artifacts(
    *,
    golden: dict[str, Any],
    coverage: dict[str, Any],
    results: list[dict[str, Any]],
    deck_id: str,
) -> tuple[Path, Path, Path, Path]:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    jsonl_path = RESULTS_DIR / f"run-{run_id}.jsonl"
    csv_path = RESULTS_DIR / f"run-{run_id}.csv"
    summary_path = RESULTS_DIR / f"summary-{run_id}.md"
    review_path = RESULTS_DIR / f"review-{run_id}.json"

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    fieldnames = [
        "case_id",
        "title",
        "situation_type",
        "rarity",
        "origin_type",
        "origin_reference",
        "http_status",
        "latency_ms",
        "deterministic_pass",
        "deterministic_failures",
        "citation_slides",
        "insufficient_evidence",
        "confidence",
        "answer",
        "reviewer",
        "review_pass",
        "review_reason",
        "final_pass",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    **{field: result.get(field) for field in fieldnames},
                    "deterministic_failures": " | ".join(
                        result["deterministic_failures"]
                    ),
                }
            )

    packet = build_review_packet(
        golden=golden,
        coverage=coverage,
        results=results,
        deck_id=deck_id,
        run_id=run_id,
    )
    review_path.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    total = len(results)
    deterministic_passed = sum(
        result["deterministic_pass"] is True for result in results
    )
    full_run = total == coverage["total"]
    lines = [
        f"# Kết quả chạy sản phẩm — {run_id}",
        "",
        f"- Golden set: `{golden.get('name')}` version `{golden.get('version')}`",
        f"- Deck ID: `{deck_id}`",
        f"- Phạm vi: `{'full run' if full_run else 'partial/smoke run'}`",
        f"- Kiểm tra xác định: **{deterministic_passed}/{total}**",
        "- Chấm nội dung: **đang chờ human/Codex review**",
        "- Không có OpenAI judge call trong lượt chạy này.",
        "",
        (
            "Không được coi điểm kiểm tra xác định là điểm cuối. "
            "Điểm cuối chỉ có sau khi review từng câu và chạy "
            "`eval/finalize_review.py`."
        ),
        "",
        f"- Review packet: `{review_path.name}`",
        f"- Bảng chạy: `{csv_path.name}`",
        f"- Raw JSONL: `{jsonl_path.name}`",
    ]
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jsonl_path, csv_path, summary_path, review_path


def main() -> int:
    configure_utf8_console()
    args = parse_args()
    golden = load_json(args.golden_set.resolve())
    coverage = validate_golden_set(golden)
    print(json.dumps(coverage, ensure_ascii=False, indent=2))
    if args.validate_only:
        print("Golden set hợp lệ; không gọi product API hoặc OpenAI.")
        return 0
    if not args.course_id or not args.deck_id:
        raise ValueError("--course-id and --deck-id are required unless --validate-only")

    api_base = args.api_base.rstrip("/")
    slides = load_slides(api_base, args.deck_id)
    slides_by_number = {int(slide["slide_number"]): slide for slide in slides}
    valid_slide_numbers = set(slides_by_number)

    cases = golden["cases"]
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be >= 1")
        cases = cases[: args.limit]
        print(
            f"WARNING: running only {len(cases)} cases; "
            "this does not count as the scored full run."
        )

    results: list[dict[str, Any]] = []
    for position, case in enumerate(cases, start=1):
        print(f"[{position}/{len(cases)}] {case['id']} — {case['title']}")
        payload = build_request_payload(
            case=case,
            course_id=args.course_id,
            deck_id=args.deck_id,
            slides_by_number=slides_by_number,
        )
        started = time.perf_counter()
        http_status, response = request_json(
            method="POST",
            url=f"{api_base}/api/chat/answer",
            payload=payload,
        )
        latency_ms = round((time.perf_counter() - started) * 1000)
        deterministic_pass, deterministic_failures = deterministic_checks(
            case=case,
            http_status=http_status,
            response=response,
            valid_slide_numbers=valid_slide_numbers,
        )
        citations = (
            response.get("citations")
            if isinstance(response.get("citations"), list)
            else []
        )
        citation_slides = [
            citation.get("slide_number")
            for citation in citations
            if isinstance(citation, dict)
        ]
        origin = case["origin"]
        results.append(
            {
                "case_id": case["id"],
                "title": case["title"],
                "situation_type": case["situation_type"],
                "rarity": case.get("rarity"),
                "origin_type": origin.get("type"),
                "origin_reference": origin_reference(origin),
                "http_status": http_status,
                "latency_ms": latency_ms,
                "deterministic_pass": deterministic_pass,
                "deterministic_failures": deterministic_failures,
                "citation_slides": ",".join(str(value) for value in citation_slides),
                "citations": citations,
                "insufficient_evidence": response.get("insufficient_evidence"),
                "confidence": response.get("confidence"),
                "answer": response.get("answer")
                or json.dumps(response, ensure_ascii=False),
                "reviewer": "",
                "review_pass": None,
                "review_reason": "",
                "final_pass": None,
            }
        )
        print(
            f"  HTTP {http_status}; deterministic={deterministic_pass}; "
            f"review=pending; {latency_ms}ms"
        )
        if position < len(cases) and args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    jsonl_path, csv_path, summary_path, review_path = write_run_artifacts(
        golden=golden,
        coverage=coverage,
        results=results,
        deck_id=args.deck_id,
    )
    print("\nChưa có điểm cuối: nội dung đang chờ human/Codex review.")
    print(f"Summary: {summary_path}")
    print(f"Run table: {csv_path}")
    print(f"Raw results: {jsonl_path}")
    print(f"Review packet: {review_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (TypeError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
