# Data Sources

Where each dataset comes from, how it is read, and where it is used.

<div style="page-break-after: always;"></div>

## Core inputs

| Source | Location | Format | Meaning | Code |
|---|---|---|---|---|
| DIC strain | `data/raw/dic_mat/strain.mat` | MATLAB `.mat` | Full-field strain vs time | `sio.loadmat(...)[\"strain\"]` |
| DIC temperature | `data/raw/dic_mat/temperature.mat` | MATLAB `.mat` | Full-field temperature vs time | `sio.loadmat(...)[\"temperature\"]` |
| Workbook | `data/raw/workbook/main.xlsx` | Excel | CCT sheets, ΔT sheets, manual sheets | `pd.read_excel`, `load_workbook` |
| CCT sheets | `main.xlsx` (`CCT 525` … `CCT 600`) | Excel | Conventional creep reference curves | `pd.read_excel(sheet_name='CCT ...')` |
| Manual ΔT | `main.xlsx` (`Manual_*`) | Excel | Manual extraction curves | `pd.read_excel(sheet_name=f\"Manual_{temp}\")` |

<div style="page-break-after: always;"></div>

## Workbook sheets

**Used in a normal run**

- `CCT 600`, `CCT 575`, `CCT 550`, `CCT 525`
- `all_data`
- `ΔT 600`, `ΔT 575`, `ΔT 550`, `ΔT 525` (opened by workbook index 1–4)
- `Manual_525`, `Manual_550`, `Manual_575`, `Manual_600`

**Present but not on the main run path**

- `graphs`, `Calculations`, `MCSR Filtered`, `MCSR`

No separate GraphPad export folder is required.

<div style="page-break-after: always;"></div>

## Workbook read logic (implementation)

### CCT sheets (`CCT 525` … `CCT 600`)

From `src/pipeline/data_access.py`:

- Data from Excel row 2 onward (`iloc[1:, ...]`).
- Time: column A (`iloc[1:, 0]`).
- Strain column chosen by header/data scoring (prefers `e1` / `engr` / `strain`, rejects index-like columns, requires enough valid points through `ANALYSIS_END`).
- Range: `A2:A_last` with the selected strain column where both are numeric.
- `CCT 525`: first valid point dropped after load.

### `all_data` sheet

From `plot_temperature_groups()` in `src/pipeline/workflow.py`:

- Rows from Excel row 3 (`iloc[2:, ...]`).
- Column windows: `600 Bottom` `B3:F_last`, `600 Top` `AK3:AO_last`, `575 Bottom` `G3:K_last`, `575 Top` `V3:Z_last`, `550 Bottom` `L3:P_last`, `550 Top` `AA3:AE_last`, `525 Bottom` `AF3:AJ_last`, `525 Top` `Q3:U_last`.

### Manual sheets (`Manual_*`)

From `load_manual_data_sheet()` in `src/pipeline/data_access.py`:

- Full sheet via `pd.read_excel(sheet_name='Manual_<temp>')`.
- Time: first column; strain channels filtered by `E*` naming and paper subsets.
- `Manual_600`: time column replaced with `0..N-1` (historical behavior).

### ΔT sheets (`ΔT 600` …)

From `load_manual_data_from_excel()` in `src/pipeline/manual_data.py`:

- Sheets by index 1–4; full read.
- Columns `P*` / `E*`; paper channel subsets (600: `E0–E4`, `E35–E39`; 575: `E5–E9`; 550: `E10–E14`; 525: `E15–E19`).
- Each kept `E` paired with nearest preceding `P`.
- MCSR and representative temperature on `[ANALYSIS_START:ANALYSIS_END]` (indices `99:199`).
- Non-positive MCSR slopes excluded from manual Arrhenius fit.

Manual Arrhenius: `Q_manual ≈ 333.3 kJ/mol` from 24 valid manual curves (25 candidates minus one negative-slope channel).

<div style="page-break-after: always;"></div>

## Outputs at run time

- Figures: `images/` (`.svg`)
- Tables: `results/workflow_exports/` (intermediate `.xlsx`); journal bundle `results/published/` (`Source_Data.xlsx`, `creep_curves_data.xlsx`, `all_delta_t_strain_full.npz`) — see `results/README.md`

No bundled `data/processed/` tree. Output subfolders are defined in `src/pipeline/constants.py` (`RESULTS_PUBLISHED_DIR`, `RESULTS_WORKFLOW_EXPORTS_DIR`). `src/config.py` holds project-root discovery for other tooling.

<div style="page-break-after: always;"></div>

## Manuscript context

Methods and reported culling counts are defined in the Word manuscript and supplementary file under the parent **`TMS 2025`** folder (see `docs/data_provenance.md`). PDFs are not required to run the pipeline.

<div style="page-break-after: always;"></div>

## Activation energy (reported fits)

- CCT headline fit: 550 / 575 / 600 °C points → ~`333.5 kJ/mol`.
- Manual ΔT: curated channels + window-aligned temperature → ~`333.3 kJ/mol`.
- Python ΔT (full-field pipeline): ~`337.5 kJ/mol`.
