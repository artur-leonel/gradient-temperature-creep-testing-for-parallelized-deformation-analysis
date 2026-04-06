"""Generate manuscript ↔ code mapping markdown from manuscript DOCX."""
from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_text(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    parts: list[str] = []
    for t in root.iter(W_NS + "t"):
        if t.text:
            parts.append(t.text)
        if t.tail:
            parts.append(t.tail)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    tms = root.parents[1]
    out_mapping = root / "docs" / "manuscript_figure_mapping.md"

    manuscript = tms / "Parallelized Creep Testing Using Temperature Gradients for Efficient Deformation Analysis.docx"
    si = tms / "Supplementary Information.docx"
    fig_lines = [
        "# Manuscript / supplementary to code outputs (SVG)",
        "",
        "Generated figures live under `images/`. Align names with published figure numbering if the journal renumbers.",
        "",
        "## Pipeline outputs",
        "",
        "| Path | Producer |",
        "|---|---|",
        "| `images/arrhenius/arrhenius_buffer_*.svg` | `plot_arrhenius` |",
        "| `images/activation_energy/activation_energy_vs_buffer.svg` | `plot_activation_energy_vs_buffer` |",
        "| `images/temperature_analysis/cov_vs_temperature.svg` | `plot_cov_vs_temperature` |",
        "| `images/creep_curves/creep_strain_curves.svg` | `plot_creep_curves` |",
        "| `images/creep_curves/creep_strain_curves_v2.svg` | `plot_creep_strain_curves_with_manual_data` |",
        "| `images/creep_curves/all_delta_t_creep_curves.svg` | `plot_all_delta_t_creep_curves` |",
        "| `images/temperature_analysis/temperature_groups.svg` | `plot_temperature_groups` |",
        "| `images/spatial_effects/arrhenius_spatial_stress_effects_buffer_*.svg` | `plot_arrhenius_spatial_stress_effects` |",
        "| `images/spatial_effects/arrhenius_spatial_stress_effects.svg` | `plot_arrhenius_with_spatial_coloring` |",
        "| `images/comparison/all_techniques_comparison.svg` | `plot_all_techniques_comparison` |",
        "| `images/manual_data/manual_delta_t_extraction.svg` | `plot_manual_delta_t_extraction` |",
        "",
        "## Figure strings detected in manuscript DOCX",
        "",
    ]
    for label, path in (("Main manuscript", manuscript), ("Supplementary Information", si)):
        fig_lines.append(f"### {label}\n")
        if not path.is_file():
            fig_lines.append(f"*Missing: `{path}`*\n\n")
            continue
        try:
            t = docx_to_text(path)
        except Exception as exc:
            fig_lines.append(f"*Read error: {exc}*\n\n")
            continue
        figs = sorted(set(re.findall(r"(?:Figure|Fig\.)\s*[0-9][0-9a-zA-Z.-]*", t, re.I)))
        supp = sorted(set(re.findall(r"Supplementary\s+(?:Figure|Table|Note)\s*[0-9][0-9a-zA-Z.-]*", t, re.I)))
        fig_lines.append("**Main-style:** " + (", ".join(figs) if figs else "(none)") + "\n\n")
        fig_lines.append("**Supplementary-style:** " + (", ".join(supp) if supp else "(none)") + "\n\n")

    fig_lines.extend(
        [
            "## Source data bundle",
            "",
            "After `python -m src.main run`: `results/Source_Data.xlsx`, `results/source_data/all_delta_t_strain_full.npz`,",
            "and per-step tables under `results/` (see `docs/data_provenance.md`).",
            "",
        ]
    )
    out_mapping.parent.mkdir(parents=True, exist_ok=True)
    out_mapping.write_text("\n".join(fig_lines), encoding="utf-8")
    print(f"Wrote {out_mapping}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
