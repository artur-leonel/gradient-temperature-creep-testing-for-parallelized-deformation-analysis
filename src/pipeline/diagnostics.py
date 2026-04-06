import numpy as np
import pandas as pd

from src.pipeline.constants import (
    ASTM_TEMP_TOL,
    GROUP_STEP,
    INITIAL_TEMP_THRESHOLD,
    ISOTHERM_LOW,
    WORKBOOK_PATH,
)
from src.pipeline.data_access import load_core_arrays


def examine_excel_data(excel_path=WORKBOOK_PATH):
    """
    Examine the Excel file structure to understand available data.
    """
    try:
        xl = pd.ExcelFile(excel_path)
        print("Available sheets in Excel file:")
        for i, sheet in enumerate(xl.sheet_names):
            try:
                print(f"{i+1}. {sheet}")
            except UnicodeEncodeError:
                print(f"{i+1}. [Sheet with Unicode characters]")

        # Examine CCT sheets
        cct_sheets = ["CCT 600", "CCT 575", "CCT 550", "CCT 525"]
        for sheet in cct_sheets:
            if sheet in xl.sheet_names:
                print(f"\nExamining CCT sheet: {sheet}")
                df = pd.read_excel(excel_path, sheet_name=sheet, nrows=10)
                print(f"Shape: {df.shape}")
                print("Columns:", list(df.columns))
                print("First few rows:")
                print(df.head())

        # Look for manual data in sheets with Unicode characters
        print("\nExamining sheets with Unicode characters (likely manual data):")
        for i, sheet in enumerate(xl.sheet_names):
            if "[Sheet with Unicode characters]" in str(sheet) or i in [1, 2, 3, 4]:
                try:
                    print(f"\nExamining sheet index {i+1}:")
                    df = pd.read_excel(excel_path, sheet_name=i, nrows=10)
                    print(f"Shape: {df.shape}")
                    print("Columns:", list(df.columns))
                    print("First few rows:")
                    print(df.head())
                except Exception as e:
                    print(f"Error reading sheet {i+1}: {e}")
    except Exception as e:
        print(f"Error examining Excel file: {e}")


def analyze_curve_filtering(edge_buffer=0):
    """
    Analyze curve filtering and report discarded counts.
    Returns X, Y, Z for temperature threshold, stability, and isotherm grouping.
    """
    print("Analyzing curve filtering process...")

    strain, temp = load_core_arrays()

    # Step 1: Total unprocessed creep curves
    total_curves = strain.shape[0] * strain.shape[1]
    print(f"Total unprocessed creep curves: {total_curves}")

    # Step 2: Apply edge buffer trimming
    if edge_buffer == 0:
        strain_trim, temp_trim = strain, temp
        curves_after_trimming = total_curves
    else:
        strain_trim = strain[edge_buffer:-edge_buffer, edge_buffer:-edge_buffer, :]
        temp_trim = temp[edge_buffer:-edge_buffer, edge_buffer:-edge_buffer, :]
        curves_after_trimming = strain_trim.shape[0] * strain_trim.shape[1]
        print(f"Curves after edge buffer trimming: {curves_after_trimming}")
        print(f"Curves discarded by edge buffer: {total_curves - curves_after_trimming}")

    # Step 3: Temperature threshold filtering (X)
    init_temp = temp_trim[:, :, 0]
    final_temp = temp_trim[:, :, -1]
    temp_threshold_mask = init_temp >= INITIAL_TEMP_THRESHOLD
    temp_threshold_passed = np.sum(temp_threshold_mask)
    temp_threshold_discarded = curves_after_trimming - temp_threshold_passed
    X = temp_threshold_discarded
    print(f"Temperature threshold discarded: {X} curves")

    # Step 4: ASTM temperature stability filtering (Y)
    astm_stability_mask = np.abs(final_temp - init_temp) <= ASTM_TEMP_TOL
    combined_temp_mask = temp_threshold_mask & astm_stability_mask
    astm_stability_discarded = temp_threshold_passed - np.sum(combined_temp_mask)
    Y = astm_stability_discarded
    print(f"ASTM temperature stability discarded: {Y} curves")

    # Step 5: Zero curve filtering
    valid_indices = np.where(combined_temp_mask)
    if valid_indices[0].size == 0:
        print("No valid datapoints found.")
        return X, Y, 0

    temp_valid = init_temp[combined_temp_mask]
    all_creep_curves = [strain_trim[i, j, :] for i, j in zip(*valid_indices)]
    zero_curves = sum(1 for curve in all_creep_curves if np.allclose(curve, 0))
    print(f"Zero curves discarded: {zero_curves}")

    # Step 6: Isotherm grouping filtering (Z)
    filtered_data = [(curve, T) for curve, T in zip(all_creep_curves, temp_valid) if not np.allclose(curve, 0)]
    if not filtered_data:
        print("All valid curves are zero.")
        return X, Y, 0

    _, temp_valid_filtered = zip(*filtered_data)
    temp_valid_filtered = np.array(temp_valid_filtered)
    isotherm_grouped_curves = 0
    discarded_by_isotherm = 0

    for center in np.arange(ISOTHERM_LOW, max(temp_valid_filtered) + GROUP_STEP, GROUP_STEP):
        idx = np.where(np.abs(temp_valid_filtered - center) <= ASTM_TEMP_TOL)[0]
        if len(idx) >= 5:
            isotherm_grouped_curves += len(idx)
        else:
            discarded_by_isotherm += len(idx)

    Z = discarded_by_isotherm
    print(f"Isotherm grouping discarded: {Z} curves")

    print("\nSummary:")
    print(f"Total unprocessed curves: {total_curves}")
    if edge_buffer > 0:
        print(f"Edge buffer discarded: {total_curves - curves_after_trimming}")
    print(f"Temperature threshold discarded (X): {X}")
    print(f"ASTM temperature stability discarded (Y): {Y}")
    print(f"Zero curves discarded: {zero_curves}")
    print(f"Isotherm grouping discarded (Z): {Z}")
    print(f"Final valid curves: {isotherm_grouped_curves}")

    remaining_after_filters = curves_after_trimming - X - Y - zero_curves
    print(f"Remaining after temperature filters: {remaining_after_filters}")
    print(f"Final after isotherm grouping: {isotherm_grouped_curves}")

    return X, Y, Z
