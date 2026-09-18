from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


DEDUP_THRESHOLD = 0.30
GOLDEN_PATH = ROOT / "data" / "golden_set.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate stable local golden cases.")
    parser.add_argument(
        "--model",
        action="store_true",
        help="Use the configured live model instead of the deterministic local fallback.",
    )
    args = parser.parse_args()

    if not args.model:
        os.environ["USE_LLM"] = "false"

    from app.services.ai import answer_status, cosine_similarity, embedding, is_question

    cases = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    totals: dict[str, int] = {}
    correct: dict[str, int] = {}
    failures = []

    for case in cases:
        task = case["task"]
        totals[task] = totals.get(task, 0) + 1

        if task == "question_detection":
            actual = is_question(case["input"])
        elif task == "dedup":
            score = cosine_similarity(embedding(case["left"]), embedding(case["right"]))
            actual = score >= DEDUP_THRESHOLD
        elif task == "answer_detection":
            actual, _, _ = answer_status(case["question"], [{"text": case["context"], "score": 1.0}])
        else:
            raise ValueError(f"Unknown task: {task}")

        if actual == case["expected"]:
            correct[task] = correct.get(task, 0) + 1
        else:
            failures.append({"id": case["id"], "expected": case["expected"], "actual": actual})

    for task in sorted(totals):
        score = correct.get(task, 0) / totals[task]
        print(f"{task}: {correct.get(task, 0)}/{totals[task]} = {score:.1%}")

    if failures:
        print("\nFailures:")
        for failure in failures:
            print(f"- {failure['id']}: expected {failure['expected']}, got {failure['actual']}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
