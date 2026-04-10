# Publication-ready repo — checklist

Use this before tagging a release or submitting a Zenodo / journal archive.

## Repository shape

- [ ] **Root:** `README.md`, `LICENSE`, `CITATION.cff`, `requirements.txt`, `requirements-lock.txt`, `python_workflow.py`, `.gitignore`
- [ ] **Code:** `src/` only for the analysis pipeline; `scripts/` for smoke test, figure-mapping helper, SVG compare (if kept)
- [ ] **Inputs:** `data/raw/` contains only what `docs/data_sources.md` lists; optional trimmed `main.xlsx` (no unused sheets) for a smaller deposit
- [ ] **Outputs:** `results/` and `images/` match what the manuscript cites; `docs/manuscript_figure_mapping.md` updated if figure numbering changed

## Metadata and legal

- [ ] **`CITATION.cff`:** title, authors, `repository-code` URL, license match the public record
- [ ] **`LICENSE`:** copyright holder and OSU / TCO wording match your clearance

## Data bundle for readers

- [ ] **`Source_Data.xlsx`:** reflects final figures; if the file is too large, set `SOURCE_DATA_EMBED_CREEP_ISOTHERMS = False` and ship **`results/creep_curves_data.xlsx`** alongside (see `docs/data_provenance.md`)
- [ ] **NPZ:** `results/source_data/all_delta_t_strain_full.npz` cited where the full grid is needed
- [ ] **Data Availability** text in the manuscript matches paths, repository URLs, and DOIs

## Technical verification

- [ ] Clean venv: `pip install -r requirements.txt` (or `-r requirements-lock.txt`)
- [ ] `python scripts/smoke_test.py`
- [ ] `python -m src.main run` then `python -m src.main verify-images` (27 SVGs)

## Archive

- [ ] Git tag on the exact commit referenced by Zenodo (or journal) — see `docs/deposition.md`
