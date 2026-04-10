# Results directory

Outputs from `python -m src.main run`. Paths are defined in `src/pipeline/constants.py`.

## `published/` — cite in Data Availability & Source Data

| File | Contents |
|------|-----------|
| `Source_Data.xlsx` | Multi-sheet numeric data backing Python-generated figures (Nature-style bundle). |
| `creep_curves_data.xlsx` | Per-isotherm creep strain columns (edge buffer 22) used for creep figures and optionally embedded into Source Data. |
| `all_delta_t_strain_full.npz` | Full DIC `strain` grid + `strain_shape` (companion to the “all curves” creep figure). |

## `workflow_exports/` — intermediate tables (reproducibility)

Step-by-step workbooks used to build plots (not all are duplicated inside `Source_Data.xlsx`):

- `activation_energy_calculations.xlsx`
- `activation_energy_vs_buffer.xlsx`
- `arrhenius_buffer_<n>_all_data.xlsx` and `_grouped_data.xlsx`
- `cov_vs_temperature_summary.xlsx`, `cov_vs_temperature_detailed.xlsx`

## Legacy layout

Older clones may still have spreadsheets at `results/` root or under `results/source_data/`. After one full run with the current code, new files appear only under `published/` and `workflow_exports/`; you may delete stale copies at the old paths if present.
