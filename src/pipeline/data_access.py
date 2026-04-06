import os
import time

import numpy as np
import pandas as pd
import scipy.io as sio

from src.pipeline.constants import ANALYSIS_END, WORKBOOK_PATH


def ensure_output_dirs() -> None:
    os.makedirs("images", exist_ok=True)
    os.makedirs("results", exist_ok=True)


def load_core_arrays():
    strain = sio.loadmat("data/raw/dic_mat/strain.mat")["strain"]
    temp = sio.loadmat("data/raw/dic_mat/temperature.mat")["temperature"]
    return strain, temp


def load_cct_data(excel_path=WORKBOOK_PATH):
    cct_temps = [525, 550, 575, 600]
    cct_data = {}
    max_retries = 5

    def _extract_cct_series(df: pd.DataFrame, temperature: int):
        if df.shape[1] < 2:
            return None, None, None

        time_data = pd.to_numeric(df.iloc[1:, 0], errors="coerce")
        best = None
        for col_idx in range(1, df.shape[1]):
            strain_candidate = pd.to_numeric(df.iloc[1:, col_idx], errors="coerce")
            mask = (~time_data.isna()) & (~strain_candidate.isna())
            count = int(mask.sum())

            header_hint = str(df.iloc[0, col_idx]).lower() if col_idx < df.shape[1] else ""
            score = 0
            if "e1" in header_hint:
                score += 3
            if "engr" in header_hint or "strain" in header_hint:
                score += 2
            if "index" in header_hint or header_hint.startswith("r0"):
                score -= 3

            key = (score, count)
            if best is None or key > best["key"]:
                best = {"key": key, "mask": mask, "strain": strain_candidate, "col": col_idx}

        if best is None or best["key"][1] < ANALYSIS_END:
            return None, None, None

        mask = best["mask"]
        time_values = time_data[mask].to_numpy()
        strain_values = best["strain"][mask].to_numpy()

        if temperature == 525 and len(time_values) > 1:
            time_values = time_values[1:]
            strain_values = strain_values[1:]

        if len(strain_values) == 0:
            return None, None, None

        initial_strain = strain_values[0]
        normalized_strain = strain_values - initial_strain
        return time_values, normalized_strain, best["col"]

    try:
        for t in cct_temps:
            sheet_name = f"CCT {t}"
            for attempt in range(max_retries):
                try:
                    df = pd.read_excel(excel_path, sheet_name=sheet_name)
                    time_values, normalized_strain, _ = _extract_cct_series(df, t)
                    if time_values is None:
                        break
                    cct_data[t] = {"time": time_values, "strain": normalized_strain}
                    break
                except PermissionError:
                    if attempt < max_retries - 1:
                        time.sleep(2)
                    else:
                        print(
                            f"Warning: Could not load CCT {t}°C "
                            f"after {max_retries} attempts - file may be locked"
                        )
                except Exception:
                    break
    except Exception as e:
        print("Error loading CCT data:", e)

    return cct_data


def load_manual_data_sheet(temp, excel_path=WORKBOOK_PATH):
    sheet_name = f"Manual_{int(temp)}"
    data = pd.read_excel(excel_path, sheet_name=sheet_name)
    if int(temp) == 600 and len(data.columns) > 0:
        time_col = data.columns[0]
        data[time_col] = range(len(data))
    return data
