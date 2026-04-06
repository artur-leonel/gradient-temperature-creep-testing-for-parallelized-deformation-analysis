# Archiving code and data (DOIs)

Checklist after Data Availability and Code Availability text exists in the manuscript. Insert **final** repository URLs and DOIs in the Word file and reference list.

## Code (citable snapshot)

1. Push to the public git host.
2. Tag a release (e.g. `v1.0.0`) matching the paper version.
3. Zenodo–GitHub integration or manual upload of the release archive.
4. Add Zenodo DOI and URL to Code Availability and to the references.

Optional: mirror on Code Ocean if required.

## Data (general repository)

1. Package minimum inputs: `data/raw/dic_mat/*.mat`, `data/raw/workbook/main.xlsx`, and if applicable `results/Source_Data.xlsx`, `results/source_data/*.npz`.
2. Upload through the chosen repository’s web interface (or its standard publisher workflow).
3. After the dataset is public, add its DOI to Data Availability and references.

## Manuscript sync

When DOIs/URLs change, update the manuscript and references in one pass so links resolve.

## Source Data workbook

Journal Source Data uploads should match numbers in `results/Source_Data.xlsx` from `python -m src.main run`.
