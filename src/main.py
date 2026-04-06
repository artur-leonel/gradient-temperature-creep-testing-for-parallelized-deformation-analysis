from __future__ import annotations

import argparse
from pathlib import Path

from src.config import ensure_directories, get_paths
from src.pipeline.runner import run_workflow


def verify_images(project_root: Path) -> tuple[bool, str]:
    target = project_root / "images"
    if not target.exists():
        return False, "Missing images directory."
    count = sum(1 for p in target.rglob("*.svg") if p.is_file())
    ok = count == 27
    return ok, f"svg_count={count}, expected=27"

def main() -> None:
    parser = argparse.ArgumentParser(description="Paper workflow runner")
    parser.add_argument(
        "command",
        choices=["run", "verify-images", "all"],
        help="Action to execute",
    )
    args = parser.parse_args()

    paths = get_paths()
    ensure_directories(paths)

    if args.command in {"run", "all"}:
        result = run_workflow(paths)
        print(f"[run] return code: {result.return_code}")
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        if result.return_code != 0:
            raise SystemExit(result.return_code)

    if args.command in {"verify-images", "all"}:
        ok, report = verify_images(paths.project_root)
        print(f"[verify-images] {report}")
        if not ok:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
