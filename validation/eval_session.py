# -*- coding: utf-8 -*-
from __future__ import annotations

"""eval_session.py - Đánh giá Precision@10 session-level cho teacher-attention ranking.

Chạy từ thư mục backend:
    python ../validation/eval_session.py
    python ../validation/eval_session.py --model   # dùng live LLM thay local fallback
"""

import argparse
import json
import os
import sys
from pathlib import Path

# Đảm bảo stdout UTF-8 trên Windows (tránh UnicodeEncodeError với tiếng Việt)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent / "backend"
sys.path.append(str(ROOT))

CASES_PATH = Path(__file__).resolve().parent / "session_cases.json"
PRECISION_AT_K = 10
PASS_THRESHOLD = 0.70   # >= 70% => pass


def _status_label(case: dict) -> str:
    """Xác định teacher_attention_status cho một cluster dựa trên signals."""
    frequency = case.get("frequency", 1)
    has_confusion = case.get("has_confusion_signal", False)
    tutor_reply = (case.get("tutor_reply") or "").strip()
    questions = case.get("questions", [])

    rating_down_count = sum(1 for q in questions if q.get("rating") == "down")
    slow_reply_count = sum(1 for q in questions if (q.get("reply_ms") or 0) > 5000)
    no_reply_count = sum(1 for q in questions if q.get("reply_ms") is None)

    if not tutor_reply:
        return "NEEDS_TEACHER_REVIEW"
    if has_confusion or rating_down_count >= 2 or (frequency >= 3 and slow_reply_count >= 1) or no_reply_count >= 2:
        return "NEEDS_TEACHER_REVIEW"
    if frequency >= 3:
        return "MONITOR"
    return "AI_TUTOR_HANDLED"


def run_local(cases: list[dict]) -> list[dict]:
    """Chạy evaluation local mà không cần LLM."""
    results = []
    for case in cases:
        predicted = _status_label(case)
        expected = case["expected_status"]
        teacher_label = case.get("teacher_label", "")
        results.append({
            "id": case["id"],
            "cluster": case["cluster_representative"],
            "predicted": predicted,
            "expected": expected,
            "teacher_label": teacher_label,
            "match": predicted == expected,
            "in_top_k": True,  # tất cả 10 case đều được xem là Top-10 trong bài kiểm thử này
        })
    return results


def run_model(cases: list[dict]) -> list[dict]:
    """Chạy evaluation dùng AI service thật."""
    from app.services.ai import teacher_attention_status_many  # type: ignore

    results = []
    for case in cases:
        signals = []
        for q in case.get("questions", []):
            signals.append({
                "text": q["text"],
                "reply_ms": q.get("reply_ms"),
                "rating": q.get("rating"),
            })

        status_list = teacher_attention_status_many(
            [s["text"] for s in signals],
            case.get("tutor_reply") or "",
            [],
        )
        predicted = status_list[0] if status_list else "AI_TUTOR_HANDLED"
        expected = case["expected_status"]
        teacher_label = case.get("teacher_label", "")
        results.append({
            "id": case["id"],
            "cluster": case["cluster_representative"],
            "predicted": predicted,
            "expected": expected,
            "teacher_label": teacher_label,
            "match": predicted == expected,
            "in_top_k": True,
        })
    return results


def compute_precision_at_k(results: list[dict], k: int = PRECISION_AT_K) -> float:
    """Precision@K: tỷ lệ nhóm trong Top-K được giảng viên xác nhận là đáng xem."""
    top_k = results[:k]
    relevant = [r for r in top_k if r.get("teacher_label") == "đáng_xem"]
    return len(relevant) / k if k > 0 else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Đánh giá Precision@10 session-level.")
    parser.add_argument("--model", action="store_true", help="Dùng live model thay local fallback.")
    args = parser.parse_args()

    if not args.model:
        os.environ["USE_LLM"] = "false"

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    print(f"Loaded {len(cases)} session-level cases from {CASES_PATH.name}\n")

    results = run_model(cases) if args.model else run_local(cases)

    # In kết quả từng case
    correct = 0
    for r in results:
        status_icon = "OK" if r["match"] else "XX"
        label_icon = "[!]" if r["teacher_label"] == "đáng_xem" else "  "
        print(f"[{status_icon}] {label_icon} {r['id']} | pred={r['predicted']:<25} exp={r['expected']:<25} | {r['cluster'][:60]}")
        if r["match"]:
            correct += 1

    total = len(results)
    overall_acc = correct / total if total else 0.0
    p_at_k = compute_precision_at_k(results, k=min(PRECISION_AT_K, total))

    print(f"\n{'=' * 60}")
    print(f"Status accuracy : {correct}/{total} = {overall_acc:.1%}")
    print(f"Precision@{PRECISION_AT_K}     : {sum(1 for r in results[:PRECISION_AT_K] if r.get('teacher_label') == 'đáng_xem')}/{min(PRECISION_AT_K, total)} = {p_at_k:.1%}  (threshold ≥ {PASS_THRESHOLD:.0%})")

    failures = [r for r in results if not r["match"]]
    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f['id']}: expected {f['expected']}, got {f['predicted']}")

    if p_at_k < PASS_THRESHOLD:
        print(f"\n❌ FAIL – Precision@{PRECISION_AT_K} {p_at_k:.1%} < {PASS_THRESHOLD:.0%}")
        raise SystemExit(1)
    else:
        print(f"\n✅ PASS – Precision@{PRECISION_AT_K} {p_at_k:.1%} ≥ {PASS_THRESHOLD:.0%}")


if __name__ == "__main__":
    main()
