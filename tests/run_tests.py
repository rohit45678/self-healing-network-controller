#!/usr/bin/env python3
"""Minimal test runner (no pytest required): discovers test_* functions in
this folder's test modules, runs them, exits non-zero on any failure."""

import importlib
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main() -> int:
    failures = 0
    total = 0
    for module_path in sorted(HERE.glob("test_*.py")):
        module = importlib.import_module(module_path.stem)
        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            fn = getattr(module, name)
            if not callable(fn):
                continue
            total += 1
            try:
                fn()
            except Exception:
                failures += 1
                print(f"FAIL {module_path.stem}.{name}")
                traceback.print_exc()
            else:
                print(f"PASS {module_path.stem}.{name}")
    print(f"\n{total - failures}/{total} tests passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
