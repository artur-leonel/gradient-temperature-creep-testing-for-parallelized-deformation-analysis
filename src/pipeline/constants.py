ASTM_TEMP_TOL = 2.0
ISOTHERM_LOW = 525
ISOTHERM_HIGH = 600
INITIAL_TEMP_THRESHOLD = ISOTHERM_LOW - ASTM_TEMP_TOL
GROUP_STEP = 5
ANALYSIS_START = 99
ANALYSIS_END = 199
SCALING_FACTOR = 1.0
GAS_CONSTANT_J_PER_MOLK = 8.314

# Mixed workbook containing both CCT and manual Delta-T sheets.
WORKBOOK_PATH = "data/raw/workbook/main.xlsx"

# Delta-T sheet indices used in the manuscript workflow.
DELTA_T_SHEET_INDICES = (1, 2, 3, 4)
DELTA_T_SHEET_TEMP_MAP = {
    1: 600,
    2: 575,
    3: 550,
    4: 525,
}

# Paper-guided manual channel curation.
MANUAL_EXTRACTIONS = {
    600: {
        "top": ["E0", "E1", "E2", "E3", "E4"],
        "bottom": ["E35", "E36", "E37", "E38", "E39"],
    },
    575: {
        "top": ["E5", "E6", "E7", "E8", "E9"],
        "bottom": [],
    },
    550: {
        "top": ["E10", "E11", "E12", "E13", "E14"],
        "bottom": [],
    },
    525: {
        "top": ["E15", "E16", "E17", "E18", "E19"],
        "bottom": [],
    },
}

# Reported CCT activation-energy fit in the paper excludes 525C.
CCT_REPORTED_FIT_TEMPS = (550, 575, 600)

# --- Results layout (see results/README.md) ---
# Journal-facing bundle: cite these paths in Data Availability / Source Data.
RESULTS_PUBLISHED_DIR = "results/published"
SOURCE_DATA_XLSX_NAME = "Source_Data.xlsx"
CREEP_CURVES_XLSX_NAME = "creep_curves_data.xlsx"
STRAIN_NPZ_FILENAME = "all_delta_t_strain_full.npz"
# Intermediate spreadsheets (Arrhenius tables, COV, activation-energy sweep, etc.).
RESULTS_WORKFLOW_EXPORTS_DIR = "results/workflow_exports"

# Arrhenius / spatial figures and Source_Data arrh_buf_* / spatial_pts_* (workflow uses this tuple).
SOURCE_DATA_EDGE_BUFFERS = (0, 1, 5, 10, 15, 22, 23, 24, 25)

# If False, Source_Data.xlsx does not duplicate creep isotherm sheets (creep22_*); those stay
# only in results/published/creep_curves_data.xlsx — smaller journal bundle, same numbers.
SOURCE_DATA_EMBED_CREEP_ISOTHERMS = True
