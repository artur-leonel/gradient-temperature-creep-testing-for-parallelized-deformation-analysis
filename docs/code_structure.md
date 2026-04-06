# Code Structure

Modular layout: `src/` entrypoints call the same legacy analysis pipeline as before.

<div style="page-break-after: always;"></div>

## Module Layout

| Module | Path | Responsibility |
|---|---|---|
| Configuration | `src/config.py` | Centralized project path discovery and directory creation |
| Pipeline constants | `src/pipeline/constants.py` | Shared constants used across analysis and plotting |
| Data access | `src/pipeline/data_access.py` | Data loading from MAT/Excel and output-folder setup |
| Manual Delta-T processing | `src/pipeline/manual_data.py` | Manual channel curation and manual activation-energy extraction from workbook |
| Diagnostics utilities | `src/pipeline/diagnostics.py` | Workbook inspection and curve-filtering diagnostics helpers |
| Workflow implementation | `src/pipeline/workflow.py` | Main analysis, plotting, and export logic |
| Workflow runner | `src/pipeline/runner.py` | Runs pipeline workflow and captures stdout/stderr |
| CLI entrypoint | `src/main.py` | User-facing commands (`run`, `verify-images`, `all`) |
| Compatibility wrapper | `python_workflow.py` | Thin wrapper that forwards to `src/pipeline/workflow.py` |

<div style="page-break-after: always;"></div>

## Execution Flow

1. `python -m src.main run`  
   Executes the legacy analysis workflow to regenerate figures and tables.
2. `python -m src.main verify-images`  
   Confirms `images/` has the expected number of SVG files for the paper outputs.

<div style="page-break-after: always;"></div>

## Design notes

- Root `python_workflow.py` is a thin wrapper; logic lives under `src/pipeline/`.
- Data loading and constants are separated from plotting/analysis.
- Paths are centralized in `src/config.py`.
- Activation-energy behavior matches the manuscript: CCT reported fit uses 550/575/600 °C; manual ΔT uses paper channel curation and window-aligned temperature averaging in `load_manual_data_from_excel()`.

## Paths and reproducibility

- Run the pipeline from the repository root (directory that contains `src/`).
- Inputs are read under `data/raw/` via `src/config.py`.
- **Legacy fallback:** `plot_temperature_groups` in `workflow.py` can look for `main.xlsx` at `../Data (Excels)/new/main.xlsx` relative to the process current working directory if the canonical `data/raw/workbook/main.xlsx` is missing. For reproducible runs, keep the workbook at the canonical path and start from the repo root.
