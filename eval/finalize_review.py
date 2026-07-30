from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HARD_GATE_TYPES = ("source_truth", "authority", "domain_harm")


def configure_utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate a completed human/Codex review packet and calculate final score."
    )
    parser.add_argument("review_packet", type=Path)
    return parser.parse_args()


def load_review_packet(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        packet = json.load(handle)
    if not isinstance(packet, dict) or packet.get("schema_version") != "1.0":
        raise ValueError("Unsupported or invalid review packet")
    cases = packet.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Review packet has no cases")
    return packet


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


def validate_completed_reviews(packet: dict[str, Any]) -> None:
    errors: list[str] = []
    for case in packet["cases"]:
        case_id = str(case.get("case_id") or "<unknown>")
        expected_hash = str(case.get("immutable_sha256") or "")
        try:
            actual_hash = immutable_review_hash(case)
        except KeyError as exc:
            errors.append(f"{case_id}: missing immutable field {exc.args[0]}")
            actual_hash = ""
        if not expected_hash or expected_hash != actual_hash:
            errors.append(
                f"{case_id}: input/expected/actual/deterministic was changed after the run"
            )
        review = case.get("review")
        if not isinstance(review, dict):
            errors.append(f"{case_id}: review must be an object")
            continue
        if not str(review.get("reviewer") or "").strip():
            errors.append(f"{case_id}: review.reviewer is required")
        if not isinstance(review.get("pass"), bool):
            errors.append(f"{case_id}: review.pass must be true or false")
        if not str(review.get("reason") or "").strip():
            errors.append(f"{case_id}: review.reason is required")
    if errors:
        raise ValueError("\n".join(errors))


def score_review_packet(packet: dict[str, Any]) -> dict[str, Any]:
    validate_completed_reviews(packet)
    rows: list[dict[str, Any]] = []
    for case in packet["cases"]:
        deterministic = case["deterministic"]
        review = case["review"]
        final_pass = bool(deterministic["pass"] and review["pass"])
        rows.append(
            {
                "case_id": case["case_id"],
                "title": case["title"],
                "situation_type": case["situation_type"],
                "deterministic_pass": deterministic["pass"],
                "deterministic_failures": " | ".join(
                    deterministic.get("failures") or []
                ),
                "reviewer": review["reviewer"],
                "review_pass": review["pass"],
                "review_reason": review["reason"],
                "final_pass": final_pass,
                "citation_slides": ",".join(
                    str(item.get("slide_number"))
                    for item in case["actual"].get("citations") or []
                    if isinstance(item, dict)
                ),
                "answer": case["actual"].get("answer"),
            }
        )

    passed = sum(row["final_pass"] for row in rows)
    total = len(rows)
    by_type: dict[str, tuple[int, int]] = {}
    for situation_type in sorted({row["situation_type"] for row in rows}):
        subset = [row for row in rows if row["situation_type"] == situation_type]
        by_type[situation_type] = (
            sum(row["final_pass"] for row in subset),
            len(subset),
        )
    hard_types_pass = all(
        by_type.get(situation_type, (0, 0))[0]
        == by_type.get(situation_type, (0, 0))[1]
        for situation_type in HARD_GATE_TYPES
    )
    citation_scope_pass = all(
        not any(
            "citation references missing slides" in failure
            for failure in case["deterministic"].get("failures") or []
        )
        for case in packet["cases"]
    )
    minimum = int(packet.get("quality_bar", {}).get("minimum_passed_cases", total))
    full_run = total == int(packet["coverage"]["total"])
    quality_bar_pass = (
        full_run
        and passed >= minimum
        and hard_types_pass
        and citation_scope_pass
    )
    return {
        "rows": rows,
        "passed": passed,
        "total": total,
        "minimum": minimum,
        "full_run": full_run,
        "by_type": by_type,
        "hard_types_pass": hard_types_pass,
        "citation_scope_pass": citation_scope_pass,
        "quality_bar_pass": quality_bar_pass,
    }


def write_scored_artifacts(
    *,
    packet_path: Path,
    packet: dict[str, Any],
    score: dict[str, Any],
) -> tuple[Path, Path]:
    output_dir = packet_path.parent
    run_id = str(packet["run_id"])
    csv_path = output_dir / f"reviewed-{run_id}.csv"
    summary_path = output_dir / f"reviewed-summary-{run_id}.md"
    fieldnames = [
        "case_id",
        "title",
        "situation_type",
        "deterministic_pass",
        "deterministic_failures",
        "reviewer",
        "review_pass",
        "review_reason",
        "final_pass",
        "citation_slides",
        "answer",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(score["rows"])

    status = "ĐẠT" if score["quality_bar_pass"] else "CHƯA ĐẠT"
    lines = [
        f"# Kết quả eval đã review — {run_id}",
        "",
        f"- Người/phương thức review: `{packet.get('review_method')}`",
        f"- Kết quả: **{score['passed']}/{score['total']}**",
        f"- Quality bar: **{status}**",
        f"- Ngưỡng điểm: `{score['minimum']}/{packet['coverage']['total']}`",
        f"- Full run: `{'yes' if score['full_run'] else 'no'}`",
        f"- Hard gate nhóm nghiêm trọng: `{'pass' if score['hard_types_pass'] else 'fail'}`",
        f"- Hard gate citation hợp lệ: `{'pass' if score['citation_scope_pass'] else 'fail'}`",
        "",
        "## Theo nhóm tình huống",
        "",
        "| Nhóm | Đạt | Tổng |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| `{name}` | {counts[0]} | {counts[1]} |"
        for name, counts in score["by_type"].items()
    )
    lines.extend(["", "## Case chưa đạt", ""])
    failed = [row for row in score["rows"] if not row["final_pass"]]
    lines.extend(
        (
            f"- `{row['case_id']}` — {row['deterministic_failures'] or row['review_reason']}"
            for row in failed
        )
        if failed
        else ["- Không có."]
    )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if score["full_run"]:
        (output_dir / "latest.csv").write_bytes(csv_path.read_bytes())
        (output_dir / "latest-summary.md").write_text(
            summary_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return csv_path, summary_path


def main() -> int:
    configure_utf8_console()
    args = parse_args()
    packet_path = args.review_packet.resolve()
    packet = load_review_packet(packet_path)
    score = score_review_packet(packet)
    csv_path, summary_path = write_scored_artifacts(
        packet_path=packet_path,
        packet=packet,
        score=score,
    )
    print(f"Kết quả: {score['passed']}/{score['total']}")
    print(f"Quality bar: {'ĐẠT' if score['quality_bar_pass'] else 'CHƯA ĐẠT'}")
    print(f"Summary: {summary_path}")
    print(f"Reviewed table: {csv_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
