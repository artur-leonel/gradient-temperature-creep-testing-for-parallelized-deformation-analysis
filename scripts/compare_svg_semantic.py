"""
Compare two SVG exports for *visual* equivalence: strip timestamps, metadata, and
matplotlib's auto-generated path ids (still unstable across some versions without svg.hashsalt).

Usage:
  python scripts/compare_svg_semantic.py <svg_a> <svg_b>
  python scripts/compare_svg_semantic.py <dir_a> <dir_b>   # compares matching relative paths

Exit 0 if all pairs match semantically, 1 otherwise.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path


def semantic_svg_text(text: str) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"<metadata>.*?</metadata>", "", t, flags=re.DOTALL)
    t = re.sub(r"<dc:date>.*?</dc:date>", "<dc:date></dc:date>", t)
    # Stable remap: collect all id= and href=# targets, sort names, assign __id_n__
    # so Matplotlib's random hashes do not break run-to-run comparison.
    ids_found = set(re.findall(r'\bid="([^"]+)"', t))
    hrefs = set(re.findall(r'(?:xlink:)?href="#([^"]+)"', t))
    url_refs = set(re.findall(r"url\(#([^)]+)\)", t))
    all_ids = sorted(ids_found | hrefs | url_refs)
    mapping = {old: f"__id_{i}__" for i, old in enumerate(all_ids, start=1)}

    def _m(old: str) -> str:
        return mapping.get(old, old)

    def mid(m: re.Match[str]) -> str:
        return f'id="{_m(m.group(1))}"'

    def mh(m: re.Match[str]) -> str:
        return f'href="#{_m(m.group(1))}"'

    def mx(m: re.Match[str]) -> str:
        return f'xlink:href="#{_m(m.group(1))}"'

    def mu(m: re.Match[str]) -> str:
        return f"url(#{_m(m.group(1))})"

    t = re.sub(r'\bid="([^"]+)"', mid, t)
    t = re.sub(r'href="#([^"]+)"', mh, t)
    t = re.sub(r'xlink:href="#([^"]+)"', mx, t)
    t = re.sub(r"url\(#([^)]+)\)", mu, t)
    return t


def file_digest(path: Path) -> str:
    return hashlib.sha256(semantic_svg_text(path.read_text(encoding="utf-8")).encode("utf-8")).hexdigest()


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    a, b = Path(sys.argv[1]), Path(sys.argv[2])
    if a.is_file() and b.is_file():
        ha, hb = file_digest(a), file_digest(b)
        if ha == hb:
            print("OK: semantic match")
            return 0
        print(f"MISMATCH: {a} vs {b}", file=sys.stderr)
        print(f"  {ha[:16]}... vs {hb[:16]}...", file=sys.stderr)
        return 1

    if not a.is_dir() or not b.is_dir():
        print("Need two files or two directories.", file=sys.stderr)
        return 2

    files_a = {p.relative_to(a).as_posix(): p for p in a.rglob("*.svg")}
    files_b = {p.relative_to(b).as_posix(): p for p in b.rglob("*.svg")}
    keys = sorted(set(files_a) | set(files_b))
    bad = []
    for k in keys:
        if k not in files_a or k not in files_b:
            bad.append((k, "missing in one tree"))
            continue
        if file_digest(files_a[k]) != file_digest(files_b[k]):
            bad.append((k, "semantic hash differs"))

    if bad:
        print(f"Mismatches: {len(bad)}", file=sys.stderr)
        for k, reason in bad[:30]:
            print(f"  {k}: {reason}", file=sys.stderr)
        return 1
    print(f"OK: all {len(keys)} SVG pairs match semantically")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
