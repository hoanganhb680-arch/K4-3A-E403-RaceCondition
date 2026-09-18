from __future__ import annotations

"""run_validation.py - Script tổng hợp chạy toàn bộ bộ kiểm thử chất lượng.

Chạy từ thư mục backend:
    python ../validation/run_validation.py
    python ../validation/run_validation.py --model   # dùng live LLM

Exit code:
    0  nếu tất cả bộ kiểm thử pass
    1  nếu có bộ nào fail
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
VALIDATION_DIR = Path(__file__).resolve().parent

CHECKS = [
    {
        "name": "Atomic golden set (question_detection / dedup / answer_detection)",
        "cmd": [sys.executable, str(BACKEND_DIR / "scripts" / "eval_golden.py")],
        "cwd": str(BACKEND_DIR),
    },
    {
        "name": "Session-level Precision@10",
        "cmd": [sys.executable, str(VALIDATION_DIR / "eval_session.py")],
        "cwd": str(BACKEND_DIR),
    },
]


def run_check(check: dict, model: bool = False) -> bool:
    cmd = check["cmd"]
    if model:
        cmd = cmd + ["--model"]
    print(f"\n{'━' * 60}")
    print(f"▶  {check['name']}")
    print(f"{'━' * 60}")
    t0 = time.time()
    result = subprocess.run(cmd, cwd=check["cwd"])
    elapsed = time.time() - t0
    status = "✅ PASS" if result.returncode == 0 else "❌ FAIL"
    print(f"\n{status}  ({elapsed:.1f}s)")
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Chạy toàn bộ validation suite.")
    parser.add_argument("--model", action="store_true", help="Dùng live LLM thay local fallback.")
    args = parser.parse_args()

    print("=" * 60)
    print("  VLearn Tutor – Full Validation Suite")
    print("=" * 60)

    passed = []
    failed = []
    for check in CHECKS:
        ok = run_check(check, model=args.model)
        (passed if ok else failed).append(check["name"])

    print(f"\n{'=' * 60}")
    print(f"  Summary: {len(passed)}/{len(CHECKS)} checks passed")
    print("=" * 60)
    for name in passed:
        print(f"  ✅ {name}")
    for name in failed:
        print(f"  ❌ {name}")

    if failed:
        sys.exit(1)
    else:
        print("\n🎉 All checks passed!")


if __name__ == "__main__":
    main()
