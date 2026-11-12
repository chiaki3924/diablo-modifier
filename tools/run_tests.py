"""Run every tests/test_*.py with the current Python and summarize the result.

Usage:
    python tools/run_tests.py
    set D1_TEST_SAVES=D:\\saves-backup
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"


def main() -> int:
    if sys.version_info[:2] != (3, 12):
        print("WARNING: _d1pyc modules require Python 3.12 (current %d.%d)"
              % sys.version_info[:2])
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("D1_TEST_SAVES", str(TESTS / "fixtures" / "saves"))

    files = sorted(TESTS.glob("test_*.py"))
    if not files:
        print("no tests found")
        return 1

    failed = []
    started = time.time()
    for path in files:
        print("\n" + "=" * 72)
        print(path.name)
        print("=" * 72, flush=True)
        proc = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(ROOT),
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        if proc.returncode != 0:
            failed.append(path.name)

    print("\n" + "=" * 72)
    print("%d/%d test files passed in %.1fs"
          % (len(files) - len(failed), len(files), time.time() - started))
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
