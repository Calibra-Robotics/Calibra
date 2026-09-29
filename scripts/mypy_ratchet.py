#!/usr/bin/env python3
"""
Fail CI if the mypy error count rises above the recorded baseline.

The codebase is not type-clean yet, so a plain `mypy` gate would always fail.
This lets the count only go down: new code must not add errors, and when a
change fixes some, lower BASELINE in the same pull request.

BASELINE is measured the way CI runs it: Python 3.12 with only the dev extra
installed. Installing other extras changes what mypy can see, so a local
count can differ by a few errors.

Run from the repo root:
    python scripts/mypy_ratchet.py
"""

from __future__ import annotations

import re
import subprocess
import sys

BASELINE = 225


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "mypy", "calibra"], capture_output=True, text=True
    )
    output = result.stdout + result.stderr
    if "errors prevented further checking" in output:
        print(output)
        print("mypy stopped early, so the error count is meaningless.")
        return 1
    match = re.search(r"Found (\d+) errors?", output)
    if match:
        count = int(match.group(1))
    elif "Success" in output:
        count = 0
    else:
        print(output)
        print("Could not parse mypy output.")
        return 1

    if count > BASELINE:
        print(output)
        print(f"mypy: {count} errors, baseline is {BASELINE}. Fix the new errors above.")
        return 1
    if count < BASELINE:
        print(f"mypy: {count} errors, below the baseline of {BASELINE}.")
        print(f"Lower BASELINE in scripts/mypy_ratchet.py to {count} to lock in the gain.")
        return 0
    print(f"mypy: {count} errors, at the baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
