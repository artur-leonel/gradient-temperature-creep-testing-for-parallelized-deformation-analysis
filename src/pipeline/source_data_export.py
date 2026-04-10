"""Build Nature-style Source_Data.xlsx plus NPZ companion for oversized grids."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.pipeline.constants import (
    ANALYSIS_END,
    ANALYSIS_START,
    ASTM_TEMP_TOL,
    CREEP_CURVES_XLSX_NAME,
    GROUP_STEP,
    INITIAL_TEMP_THRESHOLD,
    ISOTHERM_LOW,
    RESULTS_PUBLISHED_DIR,
    SOURCE_DATA_EDGE_BUFFERS,
    SOURCE_DATA_EMBED_CREEP_ISOTHERMS,
    SOURCE_DATA_XLSX_NAME,
    STRAIN_NPZ_FILENAME,
    WORKBOOK_PATH,
)
from src.pipeline.data_access import load_manual_data_sheet
from src.pipeline.manual_data import get_manual_data_columns_by_temperature
from src.pipeline.workflow import (
    compute_activation_energy_for_edge_buffer,
    load_cct_data,
    load_manual_data_from_excel,
    run_analysis,
    strain,
    temp,
)


def _sheet(name: str) -> str:
    invalid = r"[]:*?/\\"
    out = "".join(c if c not in invalid else "_" for c in name)[:31]
    return out or "sheet"


def _spatial_points(eb: int):
    """Return inv_T, ln_MCSR, horizontal_distance_datapoints (valid curves only)."""
    if eb == 0:
        strain_trim, temp_trim = strain, temp
    else:
        strain_trim = strain[eb:-eb, eb:-eb, :]
        temp_trim = temp[eb:-eb, eb:-eb, :]
    init_temp = temp_trim[:, :, 0]
    final_temp = temp_trim[:, :, -1]
    valid_mask = (init_temp >= INITIAL_TEMP_THRESHOLD) & (
        np.abs(final_temp - init_temp) <= ASTM_TEMP_TOL
    )
    valid_indices = np.where(valid_mask)
    if valid_indices[0].size == 0:
        return None
    n_rows, n_cols = strain_trim.shape[:2]
    center_col = n_cols // 2
    valid_rows = valid_indices[0]
    valid_cols = valid_indices[1]
    horizontal_distances = np.abs(valid_cols - center_col)
    temp_valid = init_temp[valid_mask]
    all_creep_curves = [strain_trim[i, j, :] for i, j in zip(valid_rows, valid_cols)]
    filtered_data = [
        (curve, T, dist)
        for curve, T, dist in zip(all_creep_curves, temp_valid, horizontal_distances)
        if not np.allclose(curve, 0)
    ]
    if not filtered_data:
        return None
    valid_curves, temp_valid, horizontal_distances = zip(*filtered_data)
    temp_valid = np.array(temp_valid)
    horizontal_distances = np.array(horizontal_distances)
    strain_segments = np.array([curve[ANALYSIS_START:ANALYSIS_END] for curve in valid_curves])
    x = np.arange(ANALYSIS_START, ANALYSIS_END)
    mean_x = np.mean(x)
    denominator = np.sum((x - mean_x) ** 2)
    mean_y = np.mean(strain_segments, axis=1)
    numerator = np.sum((x - mean_x) * (strain_segments - mean_y[:, None]), axis=1)
    slopes = numerator / denominator
    slopes[slopes <= 0] = np.nan
    valid = ~np.isnan(slopes)
    if np.sum(valid) == 0:
        return None
    slopes = slopes[valid]
    temp_valid = temp_valid[valid]
    horizontal_distances = horizontal_distances[valid]
    ln_MCSR = np.log(slopes)
    inv_T = 1 / (temp_valid + 273.15)
    return inv_T, ln_MCSR, horizontal_distances


def export_source_data_workbook(
    xlsx_path: str | None = None,
    npz_path: str | None = None,
    *,
    edge_buffers: tuple[int, ...] | None = None,
    embed_creep_isotherms: bool | None = None,
) -> None:
    out_xlsx = xlsx_path or os.path.join(RESULTS_PUBLISHED_DIR, SOURCE_DATA_XLSX_NAME)
    out_npz = npz_path or os.path.join(RESULTS_PUBLISHED_DIR, STRAIN_NPZ_FILENAME)
    os.makedirs(RESULTS_PUBLISHED_DIR, exist_ok=True)

    eb_list = edge_buffers if edge_buffers is not None else SOURCE_DATA_EDGE_BUFFERS
    embed_creep = (
        SOURCE_DATA_EMBED_CREEP_ISOTHERMS
        if embed_creep_isotherms is None
        else embed_creep_isotherms
    )

    creep_rel = os.path.join(RESULTS_PUBLISHED_DIR, CREEP_CURVES_XLSX_NAME).replace("\\", "/")
    npz_rel = os.path.join(RESULTS_PUBLISHED_DIR, STRAIN_NPZ_FILENAME).replace("\\", "/")

    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        meta_rows = [
            {"key": "title", "value": "Source Data — Delta-T creep analysis"},
            {
                "key": "description",
                "value": "Numeric data underlying Python-generated figures; see docs/manuscript_figure_mapping.md",
            },
            {
                "key": "companion_npz",
                "value": npz_rel,
            },
        ]
        if not embed_creep:
            meta_rows.append(
                {
                    "key": "creep_isotherm_tables",
                    "value": (
                        f"In {creep_rel} (not duplicated here); "
                        "set SOURCE_DATA_EMBED_CREEP_ISOTHERMS=True to embed."
                    ),
                }
            )
        meta = pd.DataFrame(meta_rows)
        meta.to_excel(writer, sheet_name=_sheet("About"), index=False)

        buf_list, energies = [], []
        for eb in range(1, 25):
            results = compute_activation_energy_for_edge_buffer(eb)
            if results and results.get("deltaT (python)") is not None:
                buf_list.append(eb)
                energies.append(results["deltaT (python)"])
        if buf_list:
            pd.DataFrame(
                {"edge_buffer_datapoints": buf_list, "Q_cr_kJ_per_mol": energies}
            ).to_excel(writer, sheet_name=_sheet("act_energy_vs_buffer"), index=False)

        res22 = run_analysis(22)
        if res22:
            temp_init, MCSR_vals = res22["temp_init"], res22["MCSR"]
            summary = []
            for center in np.arange(ISOTHERM_LOW, temp_init.max() + GROUP_STEP, GROUP_STEP):
                idx = np.where(np.abs(temp_init - center) <= ASTM_TEMP_TOL)[0]
                if len(idx) >= 5:
                    cov = np.std(MCSR_vals[idx]) / np.mean(MCSR_vals[idx])
                    summary.append(
                        {
                            "temperature_group_C": f"{center:.0f}+-{ASTM_TEMP_TOL:.1f}",
                            "n": len(idx),
                            "mean_MCSR": float(np.mean(MCSR_vals[idx])),
                            "std_MCSR": float(np.std(MCSR_vals[idx])),
                            "COV": float(cov),
                            "COV_percent": float(cov * 100),
                        }
                    )
            if summary:
                pd.DataFrame(summary).to_excel(
                    writer, sheet_name=_sheet("cov_vs_temperature"), index=False
                )

        for eb in eb_list:
            res = run_analysis(eb)
            if not res:
                continue
            pd.DataFrame(
                {
                    "inv_T_K-1": res["inv_T"],
                    "ln_MCSR": res["ln_MCSR"],
                    "MCSR_s-1": res["MCSR"],
                    "initial_temperature_C": res["temp_init"],
                }
            ).to_excel(writer, sheet_name=_sheet(f"arrh_buf_{eb}"), index=False)

        rows = []
        if res22:
            for i in range(len(res22["inv_T"])):
                rows.append(
                    {
                        "series": "DeltaT_Python",
                        "inv_T_K-1": res22["inv_T"][i],
                        "ln_MCSR": res22["ln_MCSR"][i],
                        "temperature_C": res22["temp_init"][i],
                    }
                )
            cct = res22.get("cct", {})
            if cct and "cct_inv_T_vals" in cct:
                for invv, lnv in zip(cct["cct_inv_T_vals"], cct["cct_ln_vals"]):
                    rows.append(
                        {
                            "series": "CCT",
                            "inv_T_K-1": invv,
                            "ln_MCSR": lnv,
                            "temperature_C": float(1.0 / invv - 273.15),
                        }
                    )
        md = load_manual_data_from_excel()
        if md is not None:
            for i in range(len(md["manual_inv_T"])):
                rows.append(
                    {
                        "series": "DeltaT_Manual",
                        "inv_T_K-1": md["manual_inv_T"][i],
                        "ln_MCSR": md["manual_ln_mcsr"][i],
                        "temperature_C": float(md["manual_temps"][i]),
                    }
                )
        if rows:
            pd.DataFrame(rows).to_excel(
                writer, sheet_name=_sheet("all_techniques_points"), index=False
            )

        for eb in eb_list:
            sp = _spatial_points(eb)
            if sp is None:
                continue
            inv_T, ln_MCSR, dist = sp
            pd.DataFrame(
                {
                    "inv_T_K-1": inv_T,
                    "ln_MCSR": ln_MCSR,
                    "distance_from_center_datapoints": dist,
                }
            ).to_excel(writer, sheet_name=_sheet(f"spatial_pts_b{eb}"), index=False)

        cct_data = load_cct_data()
        temperatures = [525, 550, 575, 600]
        if cct_data:
            for t in temperatures:
                if t not in cct_data:
                    continue
                d = cct_data[t]
                pd.DataFrame({"time_min": d["time"], "strain_mm_mm": d["strain"]}).to_excel(
                    writer, sheet_name=_sheet(f"CCT_{t}C_curve"), index=False
                )

        manual_rows = []
        for temp in temperatures:
            try:
                data = load_manual_data_sheet(temp)
                if data is None:
                    continue
                if temp == 600:
                    time_col = data.columns[0]
                    data = data.copy()
                    data[time_col] = range(len(data))
                time_col = data.columns[0]
                time_data = data[time_col].values
                all_strain_cols = [
                    col
                    for col in data.columns
                    if str(col).startswith("E") or str(col).startswith("ΔT")
                ]
                correct_columns = get_manual_data_columns_by_temperature(temp)
                strain_cols = []
                for col in all_strain_cols:
                    base = str(col).split("-")[0].strip() if "-" in str(col) else str(col).strip()
                    if base in correct_columns:
                        strain_cols.append(col)
                for col in strain_cols:
                    sd = np.asarray(data[col].values, dtype=float)
                    valid = sd[~np.isnan(sd)]
                    if valid.size == 0 or np.max(np.abs(valid)) <= 1e-6:
                        continue
                    for tt, ee in zip(time_data, sd):
                        manual_rows.append(
                            {
                                "temperature_C": temp,
                                "column": str(col),
                                "time_min": float(tt),
                                "strain_mm_mm": float(ee),
                            }
                        )
            except Exception:
                continue
        if manual_rows:
            pd.DataFrame(manual_rows).to_excel(
                writer, sheet_name=_sheet("manual_DT_long"), index=False
            )

        try:
            df_ad = pd.read_excel(WORKBOOK_PATH, sheet_name="all_data")
        except Exception:
            df_ad = None
        if df_ad is not None:
            groups = {
                "600_Bottom": df_ad.iloc[2:, 1:6].values,
                "600_Top": df_ad.iloc[2:, 36:41].values,
                "575_Bottom": df_ad.iloc[2:, 6:11].values,
                "575_Top": df_ad.iloc[2:, 21:26].values,
                "550_Bottom": df_ad.iloc[2:, 11:16].values,
                "550_Top": df_ad.iloc[2:, 26:31].values,
                "525_Bottom": df_ad.iloc[2:, 31:36].values,
                "525_Top": df_ad.iloc[2:, 16:21].values,
            }
            tr = []
            time_axis = np.arange(df_ad.shape[0] - 2)
            for gname, arr in groups.items():
                if arr.size == 0:
                    continue
                n_t = min(len(time_axis), arr.shape[0])
                for col in range(arr.shape[1]):
                    for i in range(n_t):
                        v = arr[i, col]
                        tr.append(
                            {
                                "group": gname,
                                "curve_index": col,
                                "time_min": float(time_axis[i]),
                                "temperature_C": float(v) if not np.isnan(v) else np.nan,
                            }
                        )
            if tr:
                pd.DataFrame(tr).to_excel(
                    writer, sheet_name=_sheet("temperature_groups"), index=False
                )

        creep_xlsx = Path(RESULTS_PUBLISHED_DIR) / CREEP_CURVES_XLSX_NAME
        if embed_creep and creep_xlsx.is_file():
            xl = pd.ExcelFile(creep_xlsx)
            for sn in xl.sheet_names:
                pref = "creep22_" + sn
                xl.parse(sn).to_excel(writer, sheet_name=_sheet(pref), index=False)

    np.savez_compressed(
        out_npz,
        strain=strain,
        strain_shape=np.array(strain.shape, dtype=np.int64),
    )
    print(f"Source data workbook written: {out_xlsx}")
    print(f"Full grid strain NPZ: {out_npz}")
