# DELTA-T creep analysis — code and minimum data

Python workflow for gradient-temperature creep DIC data (ASTM-oriented filtering) and manuscript figures/tables.

**Suggested folder name:** `delta-t-creep-code` (if this directory is still named `nature data and code`, rename it when nothing else has the folder open—OneDrive/Cursor can block renames on Windows.)

**License:** [MIT](LICENSE). The Ohio State University may hold copyright for work done under employment or sponsored research; see `LICENSE` and OSU Technology Commercialization Office for redistribution questions.

**Python:** Locked on **3.12** (`requirements-lock.txt`). **3.10+** expected with `requirements.txt`.

## Setup

1. Virtual environment recommended.
2. `pip install -r requirements.txt` (includes `pypdf` for `scripts/build_nature_docs.py`).
3. Optional exact env: `pip install -r requirements-lock.txt`.
4. Commands below: run from this directory (contains `src/`).

## Commands

| Action | Command |
|--------|---------|
| Full pipeline | `python -m src.main run` |
| Check 27 SVGs under `images/` | `python -m src.main verify-images` |
| Run + verify | `python -m src.main all` |
| Regenerate `docs/manuscript_figure_mapping.md` from manuscript DOCX in parent `TMS 2025` | `python scripts/build_nature_docs.py` |

## Quick validation

1. `python scripts/smoke_test.py` — required raw paths and `src/main.py` exist.
2. After a full run: `python -m src.main verify-images`.

## Archiving / DOIs

Checklist: [`docs/deposition.md`](docs/deposition.md). Citation file: [`CITATION.cff`](CITATION.cff) — set `repository-code` when the public git URL exists.

## Outputs (after `python -m src.main run`)

- `results/Source_Data.xlsx` — tabular source data for figures.
- `results/source_data/all_delta_t_strain_full.npz` — full strain array for the all-curves figure.
- Other tables under `results/`; figures under `images/`.

**SVG:** Matplotlib writes a metadata timestamp; bytes may differ between runs. `svg.hashsalt` in `set_plot_style()` stabilizes clip-path ids; use `scripts/compare_svg_semantic.py` or visual compare for regression checks.

## Activation energy (sanity check)

- CCT (reported subset): ~333.5 kJ/mol — `CCT_REPORTED_FIT_TEMPS = (550, 575, 600)` in `src/pipeline/constants.py`.
- Manual ΔT: ~333.3 kJ/mol.
- Python ΔT: ~337.5 kJ/mol.
- Regression window: `ANALYSIS_START` / `ANALYSIS_END` = 99 / 199 (100–200 min slice). Gas constant `R` = 8.314 J/mol·K.

## Layout

- `src/` — pipeline and CLI.
- `data/raw/` — `dic_mat/*.mat`, `workbook/main.xlsx` (CCT + ΔT + `Manual_*` sheets).
- `images/` — SVG figures.
- `results/` — generated spreadsheets and exports.
- `docs/` — provenance, data sources, code structure, deposition, figure mapping.
- `python_workflow.py` — calls `workflow.main()` directly (no `verify-images` subcommand).

## Documentation

- [`docs/data_provenance.md`](docs/data_provenance.md)
- [`docs/data_sources.md`](docs/data_sources.md)
- [`docs/code_structure.md`](docs/code_structure.md)
- [`docs/deposition.md`](docs/deposition.md)
- [`docs/manuscript_figure_mapping.md`](docs/manuscript_figure_mapping.md)
- [`data/raw/README.md`](data/raw/README.md)

Manuscript Word files live in the parent **`TMS 2025`** folder (not in this package).
