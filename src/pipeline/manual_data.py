import numpy as np
import pandas as pd

from src.pipeline.constants import (
    ANALYSIS_END,
    ANALYSIS_START,
    DELTA_T_SHEET_INDICES,
    DELTA_T_SHEET_TEMP_MAP,
    GAS_CONSTANT_J_PER_MOLK,
    MANUAL_EXTRACTIONS,
    WORKBOOK_PATH,
)


def get_manual_data_columns_by_temperature(temp):
    """
    Get the manual data columns for a given temperature according to paper methodology.
    Returns a list of column names that should be included.
    """
    extractions = MANUAL_EXTRACTIONS.get(temp, {"top": [], "bottom": []})
    return extractions["top"] + extractions["bottom"]


def load_manual_data_from_excel(excel_path=WORKBOOK_PATH):
    """
    Load manual Delta T data from Excel file and extract activation energy.
    Follows paper methodology: only top virtual extensometers + 600C bottom only.
    """
    try:
        manual_temps = []
        manual_ln_mcsr = []

        print("=== MANUAL DATA PROCESSING (PAPER METHODOLOGY) ===")
        print("Following paper: Only top virtual extensometers + 600°C bottom only")
        print("Bottom isotherms (575, 550, 525°C) excluded - don't meet ASTM ±2°C stability")

        # Process each Delta T sheet systematically
        for sheet_idx in DELTA_T_SHEET_INDICES:
            print(f"\nProcessing Sheet {sheet_idx}:")
            try:
                df = pd.read_excel(excel_path, sheet_name=sheet_idx)
                cols = df.columns.tolist()

                # Find P and E columns systematically
                p_cols = []
                e_cols = []
                for col in cols:
                    col_str = str(col)
                    if col_str.startswith("P") and not col_str.startswith("Unnamed"):
                        p_cols.append(col)
                    elif col_str.startswith("E") and not col_str.startswith("Unnamed"):
                        e_cols.append(col)
                    elif isinstance(col, (int, float)) and not col_str.startswith("Unnamed"):
                        # Likely P columns without explicit names
                        p_cols.append(col)

                print(f"  Found {len(p_cols)} P columns, {len(e_cols)} E columns")

                current_temp = DELTA_T_SHEET_TEMP_MAP.get(sheet_idx, None)
                if current_temp is None:
                    print(f"  Unknown temperature for sheet {sheet_idx}")
                    continue

                print(f"  Processing {current_temp}°C data")
                extractions = MANUAL_EXTRACTIONS.get(current_temp, {"top": [], "bottom": []})

                for e_col in e_cols:
                    e_col_name = str(e_col).split("-")[0].strip() if "-" in str(e_col) else str(e_col).strip()
                    should_include = False
                    position = ""

                    if e_col_name in extractions["top"]:
                        should_include = True
                        position = "top"
                    elif e_col_name in extractions["bottom"]:
                        should_include = True
                        position = "bottom"

                    if not should_include:
                        print(f"    {e_col}: EXCLUDED (not in paper methodology)")
                        continue

                    # Find the closest P column before this E column
                    p_col = None
                    e_actual_index = cols.index(e_col)
                    closest_p = None
                    closest_distance = float("inf")
                    for p in p_cols:
                        p_actual_index = cols.index(p)
                        if p_actual_index < e_actual_index:
                            distance = e_actual_index - p_actual_index
                            if distance < closest_distance:
                                closest_distance = distance
                                closest_p = p

                    if closest_p is not None:
                        p_col = closest_p
                    if p_col is None:
                        print(f"    {e_col}: No matching P column found")
                        continue

                    strain_vals = pd.to_numeric(df[e_col], errors="coerce").dropna()
                    if len(strain_vals) < 200:
                        print(f"    {p_col}-{e_col} ({position}): insufficient data ({len(strain_vals)} points)")
                        continue

                    # Use the same analysis window for slope and representative temperature.
                    temp_series = pd.to_numeric(df[p_col], errors="coerce")
                    analysis_start = ANALYSIS_START
                    analysis_end = min(ANALYSIS_END, len(strain_vals), len(temp_series))
                    if analysis_end <= analysis_start:
                        print(f"    {p_col}-{e_col} ({position}): analysis window too small")
                        continue

                    window_temp_vals = temp_series.iloc[analysis_start:analysis_end].dropna().to_numpy()
                    if len(window_temp_vals) == 0:
                        print(f"    {p_col}-{e_col} ({position}): no valid temperature data in analysis window")
                        continue
                    avg_temp = float(np.mean(window_temp_vals))

                    time_points = np.arange(len(strain_vals))
                    time_window = time_points[analysis_start:analysis_end]
                    strain_window = strain_vals[analysis_start:analysis_end]
                    coeffs = np.polyfit(time_window, strain_window, 1)
                    mcsr = coeffs[0]

                    if mcsr > 0:
                        ln_mcsr = np.log(mcsr)
                        manual_temps.append(avg_temp)
                        manual_ln_mcsr.append(ln_mcsr)
                        print(f"    {p_col}-{e_col} ({position}): T={avg_temp:.1f}C, MCSR={mcsr:.2e}, ln(MCSR)={ln_mcsr:.2f}")
                    else:
                        print(f"    {p_col}-{e_col} ({position}): T={avg_temp:.1f}C, negative MCSR ({mcsr:.2e})")

            except Exception as e:
                print(f"  Error processing sheet {sheet_idx}: {e}")

        print("\n=== RESULTS ===")
        print(f"Total valid data points: {len(manual_temps)}")
        print("Expected: 25 ASTM-valid creep curves (per paper)")

        if len(manual_temps) >= 2:
            manual_temps = np.array(manual_temps)
            manual_ln_mcsr = np.array(manual_ln_mcsr)
            inv_T_manual = 1 / (manual_temps + 273.15)
            coeffs_manual = np.polyfit(inv_T_manual, manual_ln_mcsr, 1)
            Q_manual = -coeffs_manual[0] * GAS_CONSTANT_J_PER_MOLK / 1000

            print(f"Temperature range: {manual_temps.min():.1f}C to {manual_temps.max():.1f}C")
            print(f"Calculated activation energy: {Q_manual:.1f} kJ/mol")
            print(f"Slope: {coeffs_manual[0]:.2f}")
            print(f"Intercept: {coeffs_manual[1]:.2f}")

            return {
                "manual_temps": manual_temps,
                "manual_ln_mcsr": manual_ln_mcsr,
                "manual_inv_T": inv_T_manual,
                "manual_Q": Q_manual,
                "manual_coeffs": coeffs_manual,
            }

        print("Insufficient data for activation energy calculation")
        return None

    except Exception as e:
        print(f"Error loading manual data: {e}")
        return None
