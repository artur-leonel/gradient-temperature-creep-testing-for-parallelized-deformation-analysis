# Publication-ready repo — checklist

Use this before tagging a release or submitting a Zenodo / journal archive.

## Repository shape

- [x] **Root:** `README.md`, `LICENSE`, `CITATION.cff`, `requirements.txt`, `requirements-lock.txt`, `python_workflow.py`, `.gitignore`
- [x] **Code:** `src/` for the analysis pipeline; `scripts/` for smoke test, figure-mapping helper, SVG compare
- [ ] **Inputs:** `data/raw/` lists only runtime-required paths in [`data_sources.md`](data_sources.md). *(Optional: ship a trimmed `main.xlsx` without unused sheets for a smaller deposit.)*
- [x] **Outputs:** `results/published/`, `results/workflow_exports/`, and `images/` populated after a full run; [`manuscript_figure_mapping.md`](manuscript_figure_mapping.md) tracks DOCX ↔ outputs *(re-run `python scripts/build_nature_docs.py` after manuscript renumbering).*

## Metadata and legal

- [x] **`CITATION.cff`:** title, author, affiliation, `repository-code`, `license`, `date-released` *(update `date-released` and any co-authors on each formal release).*
- [ ] **`LICENSE`:** confirm OSU / TCO wording matches your clearance before final publication.

## Data bundle for readers

- [x] **`results/published/Source_Data.xlsx`:** built after `python -m src.main run`; optional slimming via `SOURCE_DATA_EMBED_CREEP_ISOTHERMS` in `src/pipeline/constants.py` — see [`data_provenance.md`](data_provenance.md).
- [x] **NPZ:** `results/published/all_delta_t_strain_full.npz` documented in provenance / README.
- [ ] **Manuscript:** Data Availability and Code Availability text matches repository URLs and DOIs when deposits are final.

## Technical verification

- [x] Dependencies: `requirements.txt` matches the intent of `requirements-lock.txt` (re-freeze after changing `requirements.txt`).
- [x] `python scripts/smoke_test.py` — OK *(2026-03-30).*
- [x] `python -m src.main verify-images` — **27 / 27** SVGs *(2026-03-30, after full run).*
- [x] `python -m src.main run` — full pipeline completed successfully; Source Data and NPZ regenerated *(2026-03-30).*

## Archive

- [ ] **Git tag** on the commit referenced by Zenodo (e.g. `v1.0.0`) — see [`deposition.md`](deposition.md).

---

## Verification log (automated pass)

| Check | Result | Date |
|--------|--------|------|
| Orphan `results/arrhenius_buffer_20_*` removed (historical flat layout) | Done | 2026-03-30 |
| Results split: `results/published/` vs `results/workflow_exports/` | Done | 2026-03-31 |
| `workflow.main()` uses `SOURCE_DATA_EDGE_BUFFERS` from `constants.py` | Done | 2026-03-30 |
| `.gitignore` extended (`data/processed/`, `Thumbs.db`, `*.tmp`, `*.log`) | Done | 2026-03-30 |
| `src/` grep: no hardcoded secrets / user profile paths | Done | 2026-03-30 |
| `python -m src.main run` (exit 0, ~3 min on reference machine) | Done | 2026-03-30 |
| `python -m src.main verify-images` post-run | 27 / 27 | 2026-03-30 |
