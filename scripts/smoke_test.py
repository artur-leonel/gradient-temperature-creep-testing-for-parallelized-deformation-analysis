"""
Fast checks that the repo layout and inputs exist (for reviewers / CI).

Does not run the full creep workflow. From repository root:
  python scripts/smoke_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    errors: list[str] = []

    raw = root / "data" / "raw"
    need = [
        raw / "dic_mat" / "strain.mat",
        raw / "dic_mat" / "temperature.mat",
        raw / "workbook" / "main.xlsx",
    ]
    for p in need:
        if not p.is_file():
            errors.append(f"Missing: {p.relative_to(root)}")

    src_main = root / "src" / "main.py"
    if not src_main.is_file():
        errors.append("Missing: src/main.py")

    if errors:
        print("Smoke test FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1

    print("Smoke test OK: raw inputs and src/main.py present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
