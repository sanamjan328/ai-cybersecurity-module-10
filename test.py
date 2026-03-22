#!/usr/bin/env python3
"""
Run the Django test suite from the project root.

Usage:
  python test.py
  python test.py archiver.tests
  uv run python test.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANAGE = ROOT / "vulnerable_archive" / "manage.py"


def main() -> int:
    if not MANAGE.is_file():
        print(f"Error: {MANAGE} not found.", file=sys.stderr)
        return 1
    cmd = [sys.executable, str(MANAGE), "test", *sys.argv[1:]]
    return subprocess.call(cmd, cwd=ROOT / "vulnerable_archive")


if __name__ == "__main__":
    raise SystemExit(main())
