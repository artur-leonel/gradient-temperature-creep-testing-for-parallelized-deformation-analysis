import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib as mpl
import seaborn as sns
import pandas as pd
import matplotlib.patheffects as path_effects
import traceback
from src.pipeline.constants import (
    ANALYSIS_END,
    ANALYSIS_START,
    ASTM_TEMP_TOL,
    CCT_REPORTED_FIT_TEMPS,
    GAS_CONSTANT_J_PER_MOLK,
    GROUP_STEP,
    INITIAL_TEMP_THRESHOLD,
    ISOTHERM_HIGH,
    ISOTHERM_LOW,
    SCALING_FACTOR,
    WORKBOOK_PATH,
)
from src.pipeline.data_access import (
    ensure_output_dirs,
    load_cct_data,
    load_core_arrays,
    load_manual_data_sheet,
)
from src.pipeline.diagnostics import analyze_curve_filtering, examine_excel_data
from src.pipeline.manual_data import (
    get_manual_data_columns_by_temperature,
    load_manual_data_from_excel,
)

def set_plot_style(scaling_factor=SCALING_FACTOR):
    """Apply consistent, dynamic styling for publication-quality plots with adjusted font sizes."""
    base_font = 9 * scaling_factor  # Main font size (pt)
    plt.style.use("seaborn-v0_8-white")
    sns.set_palette("colorblind")

    # Set PDF font type for vector text in exported PDFs
    mpl.rcParams['pdf.fonttype'] = 42

    mpl.rcParams.update({
        'font.family': 'sans-serif',
        'font.sans-serif': ['Arial', 'DejaVu Sans', 'Liberation Sans'],
        'font.size': base_font,                # Main text
        'axes.titlesize': base_font,       # Axis title
        'axes.labelsize': base_font,       # Axis label
        'xtick.labelsize': base_font,          # Tick labels
        'ytick.labelsize': base_font,
        'legend.fontsize': base_font-1,          # Legend
        'figure.titlesize': base_font,
        'figure.figsize': (7, 5),          # Larger, journal-ready
        'figure.dpi': 300,
        'savefig.dpi': 600,
        'lines.linewidth': 1.5,
        'patch.linewidth': 1.0,
        'axes.linewidth': 1.0,
        'axes.grid': False,
        'grid.alpha': 0.5,
        'grid.linestyle': '--',
        'xtick.major.width': 1.0,
        'ytick.major.width': 1.0,
        'xtick.major.size': 5,
        'ytick.major.size': 5,
        'mathtext.default': 'regular',
        'mathtext.fontset': 'dejavusans',
        'axes.unicode_minus': True,
        # Stable clip-path / marker IDs across runs (byte-identical SVGs aside from dc:date metadata).
        'svg.hashsalt': 'delta-t-creep-ncomms',
    })

strain, temp = load_core_arrays()
ensure_output_dirs()

def run_analysis(edge_buffer):
    """
    Perform creep analysis using the given edge buffer.
    Returns a dictionary with analysis results (including CCT data) or None if data is insufficient.
    """
    # Trim data if necessary
    if edge_buffer == 0:
        strain_trim, temp_trim = strain, temp
    else:
        strain_trim = strain[edge_buffer:-edge_buffer, edge_buffer:-edge_buffer, :]
        temp_trim = temp[edge_buffer:-edge_buffer, edge_buffer:-edge_buffer, :]
    _, _, num_frames = strain_trim.shape
    if num_frames <= ANALYSIS_END:
        print(f"Frames ({num_frames}) less than required ANALYSIS_END ({ANALYSIS_END})!")
        return None

    # Compute initial temperature and validity mask
    init_temp = temp_trim[:, :, 0]
    final_temp = temp_trim[:, :, -1]
    valid_mask = (init_temp >= INITIAL_TEMP_THRESHOLD) & (np.abs(final_temp - init_temp) <= ASTM_TEMP_TOL)
    valid_indices = np.where(valid_mask)
    if valid_indices[0].size == 0:
        print(f"No valid datapoints found for edge_buffer={edge_buffer}.")
        return None

    # Gather creep curves and filter curves that are all zeros.
    temp_valid = init_temp[valid_mask]
    all_creep_curves = [strain_trim[i, j, :] for i, j in zip(*valid_indices)]
    filtered = [(curve, T) for curve, T in zip(all_creep_curves, temp_valid) if not np.allclose(curve, 0)]
    if not filtered:
        print("All valid curves are zero. Skipping analysis.")
        return None
    valid_curves, temp_valid = zip(*filtered)
    valid_curves = list(valid_curves)
    temp_valid = np.array(temp_valid)
    temp_std_arr = np.std(temp_trim, axis=2)[valid_mask]

    # Extract segments for regression
    strain_segments = np.array([curve[ANALYSIS_START:ANALYSIS_END] for curve in valid_curves])
    if strain_segments.shape[1] != (ANALYSIS_END - ANALYSIS_START):
        print("Insufficient data in some curves for regression.")
        return None

    # Compute slope using vectorized regression
    x = np.arange(ANALYSIS_START, ANALYSIS_END)
    mean_x = np.mean(x)
    denominator = np.sum((x - mean_x) ** 2)
    mean_y = np.mean(strain_segments, axis=1)
    numerator = np.sum((x - mean_x) * (strain_segments - mean_y[:, None]), axis=1)
    slopes = numerator / denominator
    slopes[slopes <= 0] = np.nan
    valid = ~np.isnan(slopes)
    if np.sum(valid) == 0:
        print(f"No valid slopes remain for edge_buffer={edge_buffer}.")
        return None

    slopes = slopes[valid]
    temp_valid = temp_valid[valid]
    temp_std_arr = temp_std_arr[valid]
    valid_curves = np.array(valid_curves, dtype=object)[valid].tolist()

    # Compute Arrhenius parameters
    ln_MCSR = np.log(slopes)
    inv_T = 1 / (temp_valid + 273.15)
    inv_T_err = temp_std_arr / (temp_valid + 273.15) ** 2
    mean_inv, mean_ln = np.mean(inv_T), np.mean(ln_MCSR)
    denom_fit = np.sum((inv_T - mean_inv) ** 2)
    numer_fit = np.sum((inv_T - mean_inv) * (ln_MCSR - mean_ln))
    slope_overall = numer_fit / denom_fit
    intercept_overall = mean_ln - slope_overall * mean_inv
    residuals = ln_MCSR - (slope_overall * inv_T + intercept_overall)
    std_err = np.sqrt(np.sum(residuals ** 2) / (len(ln_MCSR) - 2)) / np.sqrt(denom_fit)
    Q_cr_kJ = (-slope_overall * GAS_CONSTANT_J_PER_MOLK) / 1000
    Q_cr_err_kJ = (std_err * GAS_CONSTANT_J_PER_MOLK) / 1000

    # --- Load and process CCT data from Excel ---
    cct_result = {}
    cct_data = load_cct_data()
    cct_inv_T_vals, cct_ln_vals, cct_sheet_temps = [], [], []
    try:
        for sheet_temp in [600, 575, 550, 525]:
            if sheet_temp not in cct_data:
                continue
            time_vals = np.asarray(cct_data[sheet_temp]["time"])
            strain_vals = np.asarray(cct_data[sheet_temp]["strain"])
            if len(time_vals) < ANALYSIS_END or len(strain_vals) < ANALYSIS_END:
                continue
            time_seg = time_vals[ANALYSIS_START:ANALYSIS_END]
            strain_seg = strain_vals[ANALYSIS_START:ANALYSIS_END]
            if len(time_seg) < 2:
                continue
            slope_excel = np.polyfit(time_seg, strain_seg, 1)[0]
            if slope_excel <= 0:
                continue
            cct_sheet_temps.append(sheet_temp)
            cct_inv_T_vals.append(1 / (sheet_temp + 273.15))
            cct_ln_vals.append(np.log(slope_excel))
        if len(cct_inv_T_vals) >= 2:
            coef = np.polyfit(cct_inv_T_vals, cct_ln_vals, 1)
            slope_cct = coef[0]
            cct_result = {
                'cct_sheet_temps': cct_sheet_temps,
                'cct_inv_T_vals': cct_inv_T_vals,
                'cct_ln_vals': cct_ln_vals,
                'cct_slope': slope_cct,
                'cct_Q_cr': -slope_cct * GAS_CONSTANT_J_PER_MOLK / 1000
            }
    except Exception as e:
        print("Error loading CCT data:", e)
        traceback.print_exc()
        cct_result = {}
    # --- End CCT block ---

    return {
        'inv_T': inv_T,
        'ln_MCSR': ln_MCSR,
        'inv_T_err': inv_T_err,
        'slope': slope_overall,
        'intercept': intercept_overall,
        'Q_cr_kJ': Q_cr_kJ,
        'Q_cr_err_kJ': Q_cr_err_kJ,
        'temp_init': temp_valid,
        'MCSR': slopes,
        'creep_curves': valid_curves,
        'cct': cct_result
    }

def _get_activation_energy_components(res):
    """
    Shared helper to extract valid delta-T and CCT points and compute activation energies.
    Returns:
        valid_deltaT_points: list of dicts for each valid temperature group
        activation_energy_deltaT: float or None
        slope_deltaT: float or None
        intercept_deltaT: float or None
        activation_energy_CCT: float or None
        slope_CCT: float or None
        intercept_CCT: float or None
    """
    temp_data = res['temp_init']
    ln_MCSR_data = res['ln_MCSR']
    invT_data = 1 / (temp_data + 273.15)
    valid_temperatures = [525, 550, 575, 600]
    valid_deltaT_points = []
    for T in valid_temperatures:
        idx = np.where(np.abs(temp_data - T) <= ASTM_TEMP_TOL)[0]
        if len(idx) >= 5:
            valid_deltaT_points.append({
                'temperature': T,
                'invT': invT_data[idx],
                'ln_MCSR': ln_MCSR_data[idx],
                'count': len(idx)
            })
    if not valid_deltaT_points:
        return [], None, None, None, None, None, None

    # Delta-T regression
    combined_invT = np.concatenate([d['invT'] for d in valid_deltaT_points])
    combined_ln = np.concatenate([d['ln_MCSR'] for d in valid_deltaT_points])
    mean_inv = np.mean(combined_invT)
    mean_ln = np.mean(combined_ln)
    slope_num = np.sum((combined_invT - mean_inv) * (combined_ln - mean_ln))
    slope_den = np.sum((combined_invT - mean_inv) ** 2)
    slope_deltaT = slope_num / slope_den
    intercept_deltaT = mean_ln - slope_deltaT * mean_inv
    activation_energy_deltaT = -slope_deltaT * GAS_CONSTANT_J_PER_MOLK / 1000

    # CCT regression
    cct = res.get('cct', {})
    activation_energy_CCT = None
    slope_CCT = None
    intercept_CCT = None
    if cct and 'cct_inv_T_vals' in cct and len(cct['cct_inv_T_vals']) >= 2:
        valid_CCT_invT = []
        valid_CCT_ln = []
        # Match paper-reported CCT activation energy behavior by excluding 525C from CCT fit.
        cct_fit_temps = set(CCT_REPORTED_FIT_TEMPS)
        for sheet_temp, inv_val, ln_val in zip(cct.get('cct_sheet_temps', []),
                                               cct['cct_inv_T_vals'], cct['cct_ln_vals']):
            if sheet_temp in cct_fit_temps:
                valid_CCT_invT.append(inv_val)
                valid_CCT_ln.append(ln_val)
        if len(valid_CCT_invT) >= 2:
            valid_CCT_invT = np.array(valid_CCT_invT)
            valid_CCT_ln = np.array(valid_CCT_ln)
            mean_inv_CCT = np.mean(valid_CCT_invT)
            mean_ln_CCT = np.mean(valid_CCT_ln)
            slope_num_CCT = np.sum((valid_CCT_invT - mean_inv_CCT) * (valid_CCT_ln - mean_ln_CCT))
            slope_den_CCT = np.sum((valid_CCT_invT - mean_inv_CCT) ** 2)
            slope_CCT = slope_num_CCT / slope_den_CCT
            intercept_CCT = mean_ln_CCT - slope_CCT * mean_inv_CCT
            activation_energy_CCT = -slope_CCT * GAS_CONSTANT_J_PER_MOLK / 1000

    return valid_deltaT_points, activation_energy_deltaT, slope_deltaT, intercept_deltaT, activation_energy_CCT, slope_CCT, intercept_CCT

def compute_activation_energy_for_edge_buffer(edge_buffer):
    """
    Internal helper that computes activation energies for a given edge buffer.
    Returns a dict with 'deltaT (python)' and 'cct' energies or None if invalid.
    """
    res = run_analysis(edge_buffer)
    if not res:
        return None

    valid_deltaT_points, activation_energy_deltaT, _, _, activation_energy_CCT, _, _ = _get_activation_energy_components(res)
    if not valid_deltaT_points:
        return None

    return {'deltaT (python)': activation_energy_deltaT, 'cct': activation_energy_CCT}

def calculate_activation_energy(edge_buffer=22, save_path='results/activation_energy_calculations.xlsx'):
    """
    Calculate activation energies for the delta-T tests and CCT data.
    Results are saved to an Excel file.
    """
    res = run_analysis(edge_buffer)
    if not res:
        print("No valid data available for activation energy calculation.")
        return

    valid_deltaT_points, activation_energy_deltaT, slope_deltaT, intercept_deltaT, activation_energy_CCT, slope_CCT, intercept_CCT = _get_activation_energy_components(res)
    if not valid_deltaT_points:
        print("No valid delta-T tests available; cannot compute activation energies.")
        return

    # Load actual manual data instead of using hardcoded value
    manual_data = load_manual_data_from_excel()
    if manual_data is not None:
        activation_energy_manual = manual_data['manual_Q']
        slope_manual = manual_data['manual_coeffs'][0]
        intercept_manual = manual_data['manual_coeffs'][1]
        print(f"Using actual manual data: Q={activation_energy_manual:.1f} kJ/mol")
    else:
        print("Manual data could not be loaded; skipping manual activation-energy entry.")
        activation_energy_manual = None
        slope_manual = None
        intercept_manual = None

    # Calculate differences
    values = {
        "Delta-T (Python)": activation_energy_deltaT,
        "Delta-T (Manual)": activation_energy_manual,
        "CCT": activation_energy_CCT
    }
    diffs = []
    keys = list(values.keys())
    for i in range(len(keys)):
        for j in range(i+1, len(keys)):
            v1, v2 = values[keys[i]], values[keys[j]]
            if v1 is not None and v2 is not None:
                abs_diff = abs(v1 - v2)
                pct_diff = abs_diff / abs(v1) * 100 if v1 != 0 else None
                diffs.append({
                    "Comparison": f"{keys[i]} vs {keys[j]}",
                    "Absolute Difference (kJ/mol)": abs_diff,
                    "Percent Difference (%)": pct_diff
                })

    import pandas as pd
    results = [
        {
            "Test Type": "Delta-T (Python)",
            "Slope": slope_deltaT,
            "Intercept": intercept_deltaT,
            "Activation Energy (kJ/mol)": activation_energy_deltaT
        },
    ]
    if activation_energy_manual is not None:
        results.append(
            {
                "Test Type": "Delta-T (Manual)",
                "Slope": slope_manual,
                "Intercept": intercept_manual,
                "Activation Energy (kJ/mol)": activation_energy_manual,
            }
        )
    if activation_energy_CCT is not None:
        results.append({
            "Test Type": "CCT",
            "Slope": slope_CCT,
            "Intercept": intercept_CCT,
            "Activation Energy (kJ/mol)": activation_energy_CCT
        })
    df = pd.DataFrame(results)
    df_diff = pd.DataFrame(diffs)
    # Save both tables to Excel (two sheets)
    with pd.ExcelWriter(save_path) as writer:
        df.to_excel(writer, sheet_name='Activation Energies', index=False)
        df_diff.to_excel(writer, sheet_name='Differences', index=False)
    print(f"Activation energy calculations and differences saved to {save_path}")

def plot_activation_energy_vs_buffer(max_buffer=24, save_fig=True, display=False):
    """Plot activation energy versus edge buffer size as a point and line plot with gradient."""
    set_plot_style()
    buf_list, energies = [], []
    for eb in range(1, max_buffer + 1):
        results = compute_activation_energy_for_edge_buffer(eb)
        if results and results['deltaT (python)'] is not None:
            buf_list.append(eb)
            energies.append(results['deltaT (python)'])
        else:
            print(f"Buffer {eb} returned no valid result.")
    if not buf_list:
        print("No valid activation energy data to plot.")
        return

    buf_arr = np.array(buf_list)
    energies = np.array(energies)

    fig, ax1 = plt.subplots(figsize=mpl.rcParams['figure.figsize'])
    for sp in ['top', 'right']:
        ax1.spines[sp].set_visible(False)
    for sp in ['left', 'bottom']:
        ax1.spines[sp].set_linewidth(1 * SCALING_FACTOR)

    norm = mpl.colors.Normalize(vmin=buf_arr.min(), vmax=buf_arr.max())
    cmap = plt.cm.magma

    # Create segments for the line
    points = np.array([buf_arr, energies]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)

    # Create LineCollection
    from matplotlib.collections import LineCollection
    lc = LineCollection(segments, cmap=cmap, norm=norm)
    lc.set_array(buf_arr[:-1])  # Color based on start point of segment
    lc.set_linewidth(2 * SCALING_FACTOR)
    ax1.add_collection(lc)

    # Plot points
    ax1.scatter(buf_arr, energies, c=buf_arr, cmap=cmap, norm=norm, 
                edgecolors='gray', linewidths=0.5, s=30 * SCALING_FACTOR, zorder=3)

    ax1.set_xlabel(r'Edge Buffer Size, $b$ (datapoints)')
    ax1.set_ylabel(r'Activation Energy, $Q_\mathrm{cr}$ (kJ$\cdot$mol$^{-1}$)')
    ax1.xaxis.set_major_locator(mpl.ticker.MaxNLocator(integer=True))

    y_pad = 0.1 * (energies.max() - energies.min())
    ax1.set_ylim([energies.min() - y_pad, energies.max() + y_pad])
    ax1.set_xlim([buf_arr.min() - 1, buf_arr.max() + 1])

    # Add colorbar for buffer size
    sm = mpl.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax1, orientation='vertical', shrink=0.8)
    cbar.set_label(r'Edge Buffer Size (datapoints)')
    cbar.ax.yaxis.set_major_locator(mpl.ticker.MaxNLocator(integer=True))

    plt.tight_layout(rect=[0, 0, 1, 0.95])
    if save_fig:
        fig.savefig('images/activation_energy/activation_energy_vs_buffer.svg', bbox_inches='tight')
    if display:
        plt.show()
    else:
        plt.close(fig)

# ----------------- Plot Functions -----------------------

def plot_arrhenius(edge_buffers, save_fig=True, display=False):
    """Generate Arrhenius plots for specified edge buffers."""
    set_plot_style()
    all_inv_T, all_ln_MCSR = [], []
    for eb in edge_buffers:
        res = run_analysis(eb)
        if res:
            all_inv_T.extend(res['inv_T'])
            all_ln_MCSR.extend(res['ln_MCSR'])
    if all_inv_T and all_ln_MCSR:
        x_margin = 0.05 * (np.max(all_inv_T) - np.min(all_inv_T))
        y_margin = 0.05 * (np.max(all_ln_MCSR) - np.min(all_ln_MCSR))
        global_xmin = np.min(all_inv_T) - x_margin
        global_xmax = np.max(all_inv_T) + x_margin
        global_ymin = np.min(all_ln_MCSR) - y_margin
        global_ymax = np.max(all_ln_MCSR) + y_margin
    else:
        global_xmin = global_ymin = 0
        global_xmax = global_ymax = 1

    for eb in edge_buffers:
        res = run_analysis(eb)
        # Wider canvas so legend can sit comfortably to the right of the plot
        fig, ax = plt.subplots(figsize=(6.2, 2.6))
        # Reserve explicit margins; main axes occupies left ~60% of figure width
        fig.subplots_adjust(left=0.12, right=0.70, bottom=0.20, top=0.80)
        for sp in ['top', 'right']:
            ax.spines[sp].set_visible(False)
        for sp in ['left', 'bottom']:
            ax.spines[sp].set_linewidth(1.0 * SCALING_FACTOR)
        ax.xaxis.grid(True, linestyle='--', alpha=0.5)
        ax.yaxis.grid(False)
        ax.set_xlabel(r'Inverse Temperature, $1/T$ (K$^{-1}$)')
        ax.set_ylabel(r'Natural Logarithm of MCSR, $\ln(\mathrm{MCSR})$ (s$^{-1}$)')
        tick_positions = [1 / (temp + 273.15) for temp in [525, 550, 575, 600]]
        ax.set_xticks(tick_positions)
        if not res:
            ax.text(0.5, 0.5, f'No valid data for buffer={eb}', ha='center', va='center', color='darkred',
                    transform=ax.transAxes)
            legend = None
            cbar_ax = None
        else:
            inv_T, ln_MCSR = res['inv_T'], res['ln_MCSR']
            centers = np.arange(ISOTHERM_LOW, ISOTHERM_HIGH + GROUP_STEP, GROUP_STEP)
            colors = sns.color_palette("magma", n_colors=len(centers))
            markers = 'o'
            center_to_color = {c: colors[i] for i, c in enumerate(centers)}
            center_to_marker = {c: markers[i % len(markers)] for i, c in enumerate(centers)}
            # Plot delta-T data for each group:
            for center in centers:
                idx = np.where(np.abs(res['temp_init'] - center) <= ASTM_TEMP_TOL)[0]
                if len(idx) >= 5:
                    ax.plot(np.array(inv_T)[idx], np.array(ln_MCSR)[idx],
                            marker=center_to_marker[center],
                            linestyle='None',
                            markersize=3 * SCALING_FACTOR,
                            alpha=0.85,
                            color=center_to_color[center],
                            label=r'$\Delta T$ Data Points',
                            path_effects=[path_effects.withStroke(foreground='gray')])
            # Plot regression line for delta-T data (orange)
            if len(inv_T) >= 2:
                slope, intercept = np.polyfit(inv_T, ln_MCSR, 1)
                x_fit = np.linspace(min(inv_T), max(inv_T), 100)
                ax.plot(x_fit, slope * x_fit + intercept,
                        color='orange', lw=1.5 * SCALING_FACTOR, linestyle='-',
                        label='Delta T Regression',
                        path_effects=[path_effects.withStroke(foreground='gray')],
                        alpha=0.7)
            # Plot CCT regression and points.
            cct = res.get('cct', {})
            if cct and 'cct_inv_T_vals' in cct and len(cct['cct_inv_T_vals']) >= 2:
                cct_marker_map = {525: 'o', 550: 's', 575: '^', 600: 'D'}
                cct_temp_tol = 3.0
                coef = np.polyfit(cct['cct_inv_T_vals'], cct['cct_ln_vals'], 1)
                slope_cct = coef[0]
                x_fit_cct = np.linspace(min(cct['cct_inv_T_vals']), max(cct['cct_inv_T_vals']), 100)
                ax.plot(x_fit_cct, slope_cct * x_fit_cct + coef[1],
                        color='green', lw=1.5 * SCALING_FACTOR, linestyle='-',
                        label='CCT Regression',
                        path_effects=[path_effects.withStroke(foreground='gray')], alpha=0.7)
                plotted_cct_labels = set()
                for invT_val, ln_val in zip(cct['cct_inv_T_vals'], cct['cct_ln_vals']):
                    temp_c = 1 / invT_val - 273.15
                    # Snap to nearest nominal temperature
                    closest_temp = min(cct_marker_map.keys(), key=lambda T: abs(T - temp_c))
                    if abs(closest_temp - temp_c) > cct_temp_tol:
                        marker = 'D'
                        label = 'CCT Data Points'
                    else:
                        marker = cct_marker_map[closest_temp]
                        label = f'CCT Data Points {closest_temp}Â°C'
                    label_to_use = label if label not in plotted_cct_labels else None
                    if label_to_use:
                        plotted_cct_labels.add(label_to_use)
                    ax.plot(invT_val, ln_val,
                            marker=marker,
                            markersize=6 * SCALING_FACTOR,
                            linestyle='None',
                            markerfacecolor='green',
                            markeredgecolor='gray',
                            markeredgewidth=0.5 * SCALING_FACTOR,
                            label=label_to_use)
            
            # Add Manual extract data and line (plot with higher zorder to appear above CCT)
            manual_data = load_manual_data_from_excel()
            if manual_data is not None:
                # Use different markers for different temperatures (matching other plots)
                manual_markers = ['o', 's', '^', 'D']  # circle, square, triangle, diamond for 525, 550, 575, 600Â°C
                temperatures = [525, 550, 575, 600]
                # Reviewer-requested sample counts per temperature
                manual_counts_expected = {525: 5, 550: 5, 575: 5, 600: 10}
                
                # Plot manual data points grouped by temperature with different markers
                # Use a slightly more flexible tolerance for manual data matching (Â±3Â°C to catch all data)
                manual_temp_tol = 3.0
                for i, temp in enumerate(temperatures):
                    # Find data points near this temperature
                    temp_mask = np.abs(manual_data['manual_temps'] - temp) <= manual_temp_tol
                    if np.any(temp_mask):
                        temp_inv_T = manual_data['manual_inv_T'][temp_mask]
                        temp_ln_mcsr = manual_data['manual_ln_mcsr'][temp_mask]
                        temp_count_actual = int(np.sum(temp_mask))
                        temp_count = manual_counts_expected.get(temp, temp_count_actual)
                        # Plot with white fill and black edge, different marker per temperature
                        ax.plot(temp_inv_T, temp_ln_mcsr, 
                               marker=manual_markers[i], markersize=6 * SCALING_FACTOR, linestyle='None',
                               markerfacecolor='white', markeredgecolor='black', markeredgewidth=1.0 * SCALING_FACTOR,
                               alpha=0.9, zorder=5,
                               label=rf'Manual $\Delta T$ {temp}$^\circ$C (n={temp_count})')
                
                # Plot manual regression line
                manual_line = manual_data['manual_coeffs'][0] * manual_data['manual_inv_T'] + manual_data['manual_coeffs'][1]
                ax.plot(manual_data['manual_inv_T'], manual_line, 'k--', linewidth=2 * SCALING_FACTOR, alpha=0.9, zorder=4,
                        label=rf'Manual $\Delta T$ Regression (Q={manual_data["manual_Q"]:.1f} kJ/mol)')
            
            # Build legend for all data
            key_entries = {}
            for h, l in zip(*ax.get_legend_handles_labels()):
                # Handle manual regression label with variable Q value
                if r'Manual $\Delta T$ Regression' in l:
                    key_entries[r'Manual $\Delta T$ Regression'] = h
                elif l in ['CCT Regression', r'$\Delta T$ Data Points', 'Delta T Regression']:
                    key_entries[l] = h
                elif l and l.startswith('CCT Data Points'):
                    key_entries[l] = h
                elif l.startswith(r'Manual $\Delta T$ '):
                    # Include all manual temperature entries
                    key_entries[l] = h
            # Colorbar: positioned above main axes, aligned with plotting area
            xmin, xmax = ax.get_xlim()
            norm_cb = mpl.colors.Normalize(vmin=xmin, vmax=xmax)
            sm = mpl.cm.ScalarMappable(cmap=mpl.cm.magma, norm=norm_cb)
            sm.set_array([])
            cbar_ax = fig.add_axes([0.12, 0.83, 0.58, 0.03])
            cbar = fig.colorbar(sm, cax=cbar_ax, orientation='horizontal')
            cbar.set_label(r'Temperature ($^\circ$C)', labelpad=10 * SCALING_FACTOR)
            cbar.ax.xaxis.set_label_position('top')
            cbar.ax.xaxis.tick_top()
            cbar.set_ticks(tick_positions)
            tick_labels = [rf"{temp}$^\circ$C" for temp in [525, 550, 575, 600]]
            cbar.set_ticklabels(tick_labels)
            
            # Place legend on the right side outside the plot, clear of the colorbar
            legend = ax.legend(list(key_entries.values()), list(key_entries.keys()), 
                             loc='center left', bbox_to_anchor=(1.05, 0.5), 
                             frameon=True, edgecolor='gray')
            
            # No tight_layout here; subplots_adjust earlier already reserves space for legend/colorbar.
        if save_fig:
            fig.savefig(f'images/arrhenius/arrhenius_buffer_{eb}.svg', bbox_inches='tight',
                        bbox_extra_artists=[legend, cbar_ax] if legend and cbar_ax else None)
        if display:
            plt.show()
        else:
            plt.close(fig)

def plot_cov_vs_temperature(edge_buffer=22, save_fig=True, display=False):
    """Plot the Coefficient of Variation (COV) vs initial temperature."""
    set_plot_style()
    res = run_analysis(edge_buffer)
    if not res:
        print(f"No valid data for edge_buffer={edge_buffer}.")
        return
    temp_init, MCSR_vals = res['temp_init'], res['MCSR']
    group_centers, group_cov, group_count = [], [], []
    for center in np.arange(ISOTHERM_LOW, temp_init.max() + GROUP_STEP, GROUP_STEP):
        idx = np.where(np.abs(temp_init - center) <= ASTM_TEMP_TOL)[0]
        if len(idx) >= 5:
            group_centers.append(center)
            cov = np.std(MCSR_vals[idx]) / np.mean(MCSR_vals[idx])
            group_cov.append(cov * 100)
            group_count.append(len(idx))
    if not group_centers:
        print("No sufficient temperature groups found.")
        return
    fig, ax = plt.subplots(figsize=mpl.rcParams['figure.figsize'])
    for sp in ['top', 'right']:
        ax.spines[sp].set_visible(False)
    for sp in ['left', 'bottom']:
        ax.spines[sp].set_linewidth(1 * SCALING_FACTOR)
    colors = sns.color_palette("magma", n_colors=len(group_centers))
    bars = ax.bar(group_centers, group_cov, width=(GROUP_STEP - 1),
                  color=colors, alpha=0.9, edgecolor='gray', linewidth=1 * SCALING_FACTOR)
    for bar, count in zip(bars, group_count):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.02, f'n={count}',
                ha='center', va='bottom', fontsize=mpl.rcParams['legend.fontsize'])
    ax.set_xlabel(r'Initial Temperature, $T_\mathrm{i}$ ($^\circ$C)')
    ax.set_ylabel(r'Coefficient of Variation, COV (\%)')
    ax.set_xlim(min(group_centers) - GROUP_STEP / 2, max(group_centers) + GROUP_STEP / 2)
    ax.set_ylim(0, max(group_cov) * 1.2)
    ax.text(0.02, 0.95, f'Temperature groups: center Â± {ASTM_TEMP_TOL}Â°C', transform=ax.transAxes,
            bbox=dict(facecolor='white', alpha=0.9, edgecolor='gray'), ha='left', va='top')
    plt.tight_layout()
    if save_fig:
        fig.savefig('images/temperature_analysis/cov_vs_temperature.svg', bbox_inches='tight')
    if display:
        plt.show()
    else:
        plt.close(fig)

def plot_creep_curves(edge_buffer=22, save_fig=True, display=False, cct_data=None):
    """Plot creep strain curves grouped by initial temperature and overlay CCT curves if available."""
    set_plot_style()
    res = run_analysis(edge_buffer)
    if not res:
        print(f"No valid data for edge_buffer={edge_buffer}.")
        return
    creep_curves = res['creep_curves']
    temp_init = res['temp_init']
    group_centers = np.arange(ISOTHERM_LOW, max(temp_init) + GROUP_STEP, GROUP_STEP)
    fig, ax = plt.subplots(figsize=(3.3, 2.5), facecolor='white')
    for sp in ['top', 'right']:
        ax.spines[sp].set_visible(False)
    for sp in ['left', 'bottom']:
        ax.spines[sp].set_linewidth(1 * SCALING_FACTOR)
    delta_t_max_time = 0
    overall_max_strain = 0
    # Use magma colors, but skip the darkest ones for better visibility
    all_colors = sns.color_palette("magma", n_colors=len(group_centers) + 2)
    colors = all_colors[1:]  # Skip the first (darkest) color
    markers = ['o', 's', '^', 'D', 'v']
    marker_mapping = {525: markers[0], 550: markers[1], 575: markers[2], 600: markers[3]}
    cct_isotherms = [525, 550, 575, 600]
    
    for i, center in enumerate(group_centers):
        idx = np.where(np.abs(temp_init - center) <= ASTM_TEMP_TOL)[0]
        # For CCT-comparable temperatures, allow fewer curves (min 3), otherwise require 5
        min_curves_required = 3 if center in cct_isotherms else 5
        if len(idx) >= min_curves_required:
            min_length = min(len(creep_curves[j]) for j in idx)
            x_vals = np.arange(min_length)
            group_data = np.array([creep_curves[j][:min_length] for j in idx])
            delta_t_max_time = max(delta_t_max_time, min_length)
            overall_max_strain = max(overall_max_strain, np.max(group_data))
            
            # Mark Delta T tests that can be directly compared with CCT temperatures differently
            if center in cct_isotherms:
                # CCT-comparable temperatures: thicker line, different style
                linewidth = 1.5 * SCALING_FACTOR
                linestyle = "-"
                alpha_val = 0.9
                fill_alpha = 0.25
                label_prefix = r"$\Delta T$*"  # Asterisk to indicate CCT-comparable
            else:
                # Other temperatures: more subtle styling in background
                linewidth = 1.0 * SCALING_FACTOR
                linestyle = "--"
                alpha_val = 0.3
                fill_alpha = 0.125
                label_prefix = r"$\Delta T$"
            
            ax.fill_between(x_vals, np.min(group_data, axis=0), np.max(group_data, axis=0),
                            color=colors[i], alpha=fill_alpha)
            mkr = marker_mapping.get(center, 'o')
            
            ax.plot(x_vals, np.mean(group_data, axis=0),
                    color=colors[i],
                    linestyle=linestyle, 
                    linewidth=linewidth,
                    alpha=alpha_val,
                    label=rf'{label_prefix} {center:.0f}$^\circ$C $\pm$ {ASTM_TEMP_TOL:.1f}$^\circ$C (n={len(idx)})')
    
    # Plot CCT data independently of Delta T data availability
    # CCT markers that match manual data markers for each temperature
    cct_markers = ['o', 's', '^', 'D']
    if cct_data:
        for idx, temp in enumerate(cct_isotherms):
            if temp in cct_data:
                time_vals = cct_data[temp]['time']
                strain_vals = cct_data[temp]['strain']
                # Use markers with green fill, alternating with manual data
                # Manual data uses markevery=20 starting at 0 (positions: 0, 20, 40, 60, 80, 100...)
                # CCT uses markevery=20 starting at 10 (positions: 10, 30, 50, 70, 90, 110...)
                ax.plot(time_vals, strain_vals,
                        linestyle='None', 
                        linewidth=1.0 * SCALING_FACTOR,
                        alpha=0.7,
                        marker=cct_markers[idx],
                        markersize=2 * SCALING_FACTOR,
                        markevery=(10, 20),  # Start at position 10, then every 20 points
                        markerfacecolor='green',
                        markeredgecolor='black',
                        markeredgewidth=0.5 * SCALING_FACTOR,
                        zorder=3,
                        label=rf'CCT {temp:.0f}$^\circ$C $\pm$ {ASTM_TEMP_TOL:.1f}$^\circ$C')
                overall_max_strain = max(overall_max_strain, np.max(strain_vals))
    
    # Add manual data curves
    temperatures = [525, 550, 575, 600]
    
    # Different markers for each temperature
    manual_markers = ['o', 's', '^', 'D', 'v', '<', '>', 'p', '*', 'h']
    
    for i, temp in enumerate(temperatures):
        try:
            data = load_manual_data_sheet(temp)
            if data is not None:
                
                # Fix corrupted time column for 600Â°C file
                if temp == 600:
                    # The 600Â°C file has corrupted time data - reconstruct it
                    time_col = data.columns[0]
                    data[time_col] = range(len(data))  # 0 to 449 minutes
                
                # Get time column (first column)
                time_col = data.columns[0]
                time_data = data[time_col].values
                
                # Get strain columns and apply exact paper methodology filtering
                all_strain_cols = [col for col in data.columns if col != time_col and 'temp' not in col.lower() and not col.startswith('Î”T')]
                
                # Get the correct columns according to paper methodology
                correct_columns = get_manual_data_columns_by_temperature(temp)
                
                strain_cols = []
                
                for col in all_strain_cols:
                    # Extract base column name (e.g., "E0" from "E0 - 600")
                    base_col_name = col.split('-')[0].strip() if '-' in col else col.strip()
                    
                    if base_col_name in correct_columns:
                        strain_cols.append(col)
                        # Position tracking is intentionally omitted here; it is not needed for plotting.
                
                # Filter out columns with no valid data (like E39 in 600Â°C)
                valid_strain_cols = []
                for col in strain_cols:
                    strain_data = data[col].values
                    valid_data = strain_data[~np.isnan(strain_data)]
                    if len(valid_data) > 0 and np.max(np.abs(valid_data)) > 1e-6:
                        valid_strain_cols.append(col)
                
                # Plot individual curves with black markers and white fill
                for j, col in enumerate(valid_strain_cols):
                    strain_data = data[col].values
                    # Add label only for the first curve
                    if j == 0:
                        label = rf'Manual $\Delta T$ {temp}$^\circ$C (n={len(valid_strain_cols)})'
                    else:
                        label = None
                    ax.plot(time_data, strain_data,
                           linestyle='None', linewidth=1 * SCALING_FACTOR,
                           alpha=0.7, zorder=2, marker=manual_markers[i], 
                           markersize=2 * SCALING_FACTOR, markevery=20,
                           markerfacecolor='white', markeredgecolor='black', markeredgewidth=0.5 * SCALING_FACTOR,
                           label=label)
                    
        except Exception as e:
            print(f"Error loading manual data for {temp}Â°C: {e}")
            continue
    
    ax.set_xlabel(r'Time, $t$ (min)')
    ax.set_ylabel(r'Creep Strain, $\epsilon$ (mm/mm)')
    ax.set_xlim(0, min(delta_t_max_time, 450))
    ax.set_ylim(0, overall_max_strain * 1.05)
    handles, labels = ax.get_legend_handles_labels()
    # Place legend outside the plot, right side, with proper spacing
    legend = ax.legend(handles, labels, loc='center left', bbox_to_anchor=(1.02, 0.5), 
                      borderaxespad=0.5, title='Curves', edgecolor='gray',
                      fontsize=mpl.rcParams['legend.fontsize'], markerscale=2.0)
    legend.set_title('Curves', prop={'size': mpl.rcParams['legend.fontsize']})
    if save_fig:
        fig.savefig('images/creep_curves/creep_strain_curves.svg', bbox_inches='tight',
                    bbox_extra_artists=[legend])
    if display:
        plt.show()
    else:
        plt.close(fig)

def plot_creep_strain_curves_with_manual_data(edge_buffer=22, save_fig=True, display=False, cct_data=None):
    """Plot creep strain curves with manual data curves added."""
    set_plot_style()
    res = run_analysis(edge_buffer)
    if not res:
        print(f"No valid data for edge_buffer={edge_buffer}.")
        return
    creep_curves = res['creep_curves']
    temp_init = res['temp_init']
    group_centers = np.arange(ISOTHERM_LOW, max(temp_init) + GROUP_STEP, GROUP_STEP)
    fig, ax = plt.subplots(figsize=(3.3, 2.5), facecolor='white')
    for sp in ['top', 'right']:
        ax.spines[sp].set_visible(False)
    for sp in ['left', 'bottom']:
        ax.spines[sp].set_linewidth(1 * SCALING_FACTOR)
    delta_t_max_time = 0
    overall_max_strain = 0
    # Use magma colors, but skip the darkest ones for better visibility
    all_colors = sns.color_palette("magma", n_colors=len(group_centers) + 2)
    colors = all_colors[1:]  # Skip the first (darkest) color
    markers = ['o', 's', '^', 'D', 'v']
    marker_mapping = {525: markers[0], 550: markers[1], 575: markers[2], 600: markers[3]}
    cct_isotherms = [525, 550, 575, 600]
    
    for i, center in enumerate(group_centers):
        idx = np.where(np.abs(temp_init - center) <= ASTM_TEMP_TOL)[0]
        # For CCT-comparable temperatures, allow fewer curves (min 3), otherwise require 5
        min_curves_required = 3 if center in cct_isotherms else 5
        if len(idx) >= min_curves_required:
            min_length = min(len(creep_curves[j]) for j in idx)
            x_vals = np.arange(min_length)
            group_data = np.array([creep_curves[j][:min_length] for j in idx])
            delta_t_max_time = max(delta_t_max_time, min_length)
            overall_max_strain = max(overall_max_strain, np.max(group_data))
            
            # Mark Delta T tests that can be directly compared with CCT temperatures differently
            if center in cct_isotherms:
                # CCT-comparable temperatures: thicker line, different style
                linewidth = 1.5 * SCALING_FACTOR
                linestyle = "-"
                alpha_val = 0.9
                fill_alpha = 0.25
                label_prefix = r"$\Delta T$*"  # Asterisk to indicate CCT-comparable
            else:
                # Other temperatures: more subtle styling in background
                linewidth = 1.0 * SCALING_FACTOR
                linestyle = "--"
                alpha_val = 0.3
                fill_alpha = 0.125
                label_prefix = r"$\Delta T$"
            
            ax.fill_between(x_vals, np.min(group_data, axis=0), np.max(group_data, axis=0),
                            color=colors[i], alpha=fill_alpha)
            mkr = marker_mapping.get(center, 'o')
            
            ax.plot(x_vals, np.mean(group_data, axis=0),
                    color=colors[i],
                    linestyle=linestyle, 
                    linewidth=linewidth,
                    alpha=alpha_val,
                    label=rf'{label_prefix} {center:.0f}$^\circ$C $\pm$ {ASTM_TEMP_TOL:.1f}$^\circ$C (n={len(idx)})')
    
    # Plot CCT data independently of Delta T data availability
    # CCT markers that match manual data markers for each temperature
    cct_markers = ['o', 's', '^', 'D']
    if cct_data:
        for idx, temp in enumerate(cct_isotherms):
            if temp in cct_data:
                time_vals = cct_data[temp]['time']
                strain_vals = cct_data[temp]['strain']
                # Use markers with green fill, alternating with manual data
                # Manual data uses markevery=20 starting at 0 (positions: 0, 20, 40, 60, 80, 100...)
                # CCT uses markevery=20 starting at 10 (positions: 10, 30, 50, 70, 90, 110...)
                ax.plot(time_vals, strain_vals,
                        linestyle='None', 
                        linewidth=1.0 * SCALING_FACTOR,
                        alpha=0.7,
                        marker=cct_markers[idx],
                        markersize=2 * SCALING_FACTOR,
                        markevery=(10, 20),  # Start at position 10, then every 20 points
                        markerfacecolor='green',
                        markeredgecolor='black',
                        markeredgewidth=0.5 * SCALING_FACTOR,
                        zorder=3,
                        label=rf'CCT {temp:.0f}$^\circ$C $\pm$ {ASTM_TEMP_TOL:.1f}$^\circ$C')
                overall_max_strain = max(overall_max_strain, np.max(strain_vals))
    
    # Add manual data curves
    temperatures = [525, 550, 575, 600]
    manual_colors = sns.color_palette("magma", n_colors=len(temperatures))
    
    # Different markers for each temperature
    manual_markers = ['o', 's', '^', 'D', 'v', '<', '>', 'p', '*', 'h']
    
    for i, temp in enumerate(temperatures):
        try:
            data = load_manual_data_sheet(temp)
            if data is not None:
                
                # Fix corrupted time column for 600Â°C file
                if temp == 600:
                    # The 600Â°C file has corrupted time data - reconstruct it
                    time_col = data.columns[0]
                    data[time_col] = range(len(data))  # 0 to 449 minutes
                
                # Get time column (first column)
                time_col = data.columns[0]
                time_data = data[time_col].values
                
                # Get strain columns (all columns except time and any duplicate temp columns)
                strain_cols = [col for col in data.columns if col.startswith('E') or col.startswith('Î”T')]
                
                # Filter out the temperature column if it exists
                strain_cols = [col for col in strain_cols if not col.endswith(f'{temp}Â°C')]
                
                # Plot individual curves
                for j, col in enumerate(strain_cols[:10]):  # Limit to 10 curves per temperature
                    strain_data = data[col].values
                    # Check if the curve has meaningful data (not all zeros or very small values)
                    if len(strain_data) > 0 and np.max(np.abs(strain_data)) > 1e-6:
                        ax.plot(time_data, strain_data,
                               color=manual_colors[i], linestyle='None', linewidth=1 * SCALING_FACTOR,
                               alpha=0.5, zorder=2, marker=manual_markers[i], 
                               markersize=3 * SCALING_FACTOR, markevery=20)
                
                # Plot average curve
                valid_cols = [col for col in strain_cols if len(data[col].values) > 0 and np.max(np.abs(data[col].values)) > 1e-6]
                if valid_cols:
                    # Calculate average strain
                    strain_data_all = np.array([data[col].values for col in valid_cols])
                    avg_strain = np.mean(strain_data_all, axis=0)
                    
                    ax.plot(time_data, avg_strain,
                           color=manual_colors[i], linestyle='None', linewidth=1 * SCALING_FACTOR,
                           alpha=0.9, marker=manual_markers[i], markersize=3 * SCALING_FACTOR, markevery=20,
                           label=rf'Manual $\Delta T$ {temp}$^\circ$C (n={len(valid_cols)})', zorder=2)
                    
        except FileNotFoundError:
            print(f"Warning: Could not find data file for temperature {temp}Â°C")
            continue
    
    ax.set_xlabel(r'Time, $t$ (min)')
    ax.set_ylabel(r'Creep Strain, $\epsilon$ (mm/mm)')
    ax.set_xlim(0, min(delta_t_max_time, 450))
    ax.set_ylim(0, overall_max_strain * 1.05)
    handles, labels = ax.get_legend_handles_labels()
    # Place legend outside the plot, right side, with proper spacing
    legend = ax.legend(handles, labels, loc='center left', bbox_to_anchor=(1.02, 0.5), 
                      borderaxespad=0.5, title='Curves', edgecolor='gray',
                      fontsize=mpl.rcParams['legend.fontsize'], markerscale=2.0)
    legend.set_title('Curves', prop={'size': mpl.rcParams['legend.fontsize']})
    if save_fig:
        fig.savefig('images/creep_curves/creep_strain_curves.svg', bbox_inches='tight',
                    bbox_extra_artists=[legend])
    if display:
        plt.show()
    else:
        plt.close(fig)

def plot_creep_curves_v2(edge_buffer=22, save_fig=True, display=False, cct_data=None):
    """Plot creep strain curves (version 2) with maximum y-axis set to 0.02."""
    set_plot_style()
    res = run_analysis(edge_buffer)
    if not res:
        print(f"No valid data for edge_buffer={edge_buffer}.")
        return
    creep_curves = res['creep_curves']
    temp_init = res['temp_init']
    group_centers = np.arange(ISOTHERM_LOW, max(temp_init) + GROUP_STEP, GROUP_STEP)
    fig, ax = plt.subplots(figsize=(3.3, 2.5), facecolor='white')
    for sp in ['top', 'right']:
        ax.spines[sp].set_visible(False)
    for sp in ['left', 'bottom']:
        ax.spines[sp].set_linewidth(1 * SCALING_FACTOR)
    delta_t_max_time = 0
    colors = sns.color_palette("magma", n_colors=len(group_centers))
    markers = ['o', 's', '^', 'D', 'v']
    marker_mapping = {525: markers[0], 550: markers[1], 575: markers[2], 600: markers[3]}
    cct_isotherms = [525, 550, 575, 600]
    for i, center in enumerate(group_centers):
        idx = np.where(np.abs(temp_init - center) <= ASTM_TEMP_TOL)[0]
        # For CCT-comparable temperatures, allow fewer curves (min 3), otherwise require 5
        min_curves_required = 3 if center in cct_isotherms else 5
        if len(idx) >= min_curves_required:
            min_length = min(len(creep_curves[j]) for j in idx)
            x_vals = np.arange(min_length)
            group_data = np.array([creep_curves[j][:min_length] for j in idx])
            delta_t_max_time = max(delta_t_max_time, min_length)
            
            # Mark Delta T tests that can be directly compared with CCT temperatures differently
            if center in cct_isotherms:
                # CCT-comparable temperatures: thicker line, different style
                linewidth = 1.5 * SCALING_FACTOR
                linestyle = "-"
                alpha_val = 0.9
                fill_alpha = 0.25
                label_prefix = r"$\Delta T$*"  # Asterisk to indicate CCT-comparable
            else:
                # Other temperatures: more subtle styling in background
                linewidth = 1.0 * SCALING_FACTOR
                linestyle = "--"
                alpha_val = 0.3
                fill_alpha = 0.125
                label_prefix = r"$\Delta T$"
            
            ax.fill_between(x_vals, np.min(group_data, axis=0), np.max(group_data, axis=0),
                            color=colors[i], alpha=fill_alpha)
            mkr = marker_mapping.get(center, 'o')
            
            ax.plot(x_vals, np.mean(group_data, axis=0),
                    color=colors[i],
                    linestyle=linestyle, 
                    linewidth=linewidth,
                    alpha=alpha_val,
                    label=rf'{label_prefix} {center:.0f}$^\circ$C $\pm$ {ASTM_TEMP_TOL:.1f}$^\circ$C (n={len(idx)})')
    
    # Plot CCT data independently of Delta T data availability
    # CCT markers that match manual data markers for each temperature
    cct_markers = ['o', 's', '^', 'D']
    if cct_data:
        for idx, temp in enumerate(cct_isotherms):
            if temp in cct_data:
                time_vals = cct_data[temp]['time']
                strain_vals = cct_data[temp]['strain']
                # Use markers with green fill, alternating with manual data
                # Manual data uses markevery=20 starting at 0 (positions: 0, 20, 40, 60, 80, 100...)
                # CCT uses markevery=20 starting at 10 (positions: 10, 30, 50, 70, 90, 110...)
                ax.plot(time_vals, strain_vals,
                        linestyle='None', 
                        linewidth=1.0 * SCALING_FACTOR,
                        alpha=0.7,
                        marker=cct_markers[idx],
                        markersize=2 * SCALING_FACTOR,
                        markevery=(10, 20),  # Start at position 10, then every 20 points
                        markerfacecolor='green',
                        markeredgecolor='black',
                        markeredgewidth=0.5 * SCALING_FACTOR,
                        zorder=3,
                        label=rf'CCT {temp:.0f}$^\circ$C $\pm$ {ASTM_TEMP_TOL:.1f}$^\circ$C')
    
    # Add manual data curves
    temperatures = [525, 550, 575, 600]
    
    # Different markers for each temperature
    manual_markers = ['o', 's', '^', 'D', 'v', '<', '>', 'p', '*', 'h']
    
    for i, temp in enumerate(temperatures):
        try:
            data = load_manual_data_sheet(temp)
            if data is not None:
                
                # Fix corrupted time column for 600Â°C file
                if temp == 600:
                    # The 600Â°C file has corrupted time data - reconstruct it
                    time_col = data.columns[0]
                    data[time_col] = range(len(data))  # 0 to 449 minutes
                
                # Get time column (first column)
                time_col = data.columns[0]
                time_data = data[time_col].values
                
                # Get strain columns and apply exact paper methodology filtering
                all_strain_cols = [col for col in data.columns if col != time_col and 'temp' not in col.lower() and not col.startswith('Î”T')]
                
                # Get the correct columns according to paper methodology
                correct_columns = get_manual_data_columns_by_temperature(temp)
                
                strain_cols = []
                
                for col in all_strain_cols:
                    # Extract base column name (e.g., "E0" from "E0 - 600")
                    base_col_name = col.split('-')[0].strip() if '-' in col else col.strip()
                    
                    if base_col_name in correct_columns:
                        strain_cols.append(col)
                        # Position tracking is intentionally omitted here; it is not needed for plotting.
                
                # Filter out columns with no valid data (like E39 in 600Â°C)
                valid_strain_cols = []
                for col in strain_cols:
                    strain_data = data[col].values
                    valid_data = strain_data[~np.isnan(strain_data)]
                    if len(valid_data) > 0 and np.max(np.abs(valid_data)) > 1e-6:
                        valid_strain_cols.append(col)
                
                # Plot individual curves with black markers and white fill (no average)
                for j, col in enumerate(valid_strain_cols):
                    strain_data = data[col].values
                    # Add label only for the first curve
                    if j == 0:
                        label = rf'Manual $\Delta T$ {temp}$^\circ$C (n={len(valid_strain_cols)})'
                    else:
                        label = None
                    ax.plot(time_data, strain_data,
                           linestyle='None', linewidth=1 * SCALING_FACTOR,
                           alpha=0.7, zorder=2, marker=manual_markers[i], 
                           markersize=2 * SCALING_FACTOR, markevery=20,
                           markerfacecolor='white', markeredgecolor='black', markeredgewidth=0.5 * SCALING_FACTOR,
                           label=label)
                    
        except FileNotFoundError:
            print(f"Warning: Could not find data file for temperature {temp}Â°C")
            continue
    
    ax.set_xlabel(r'Time, $t$ (min)')
    ax.set_ylabel(r'Creep Strain, $\epsilon$ (mm/mm)')
    
    # Calculate max strain to accommodate both Delta T and CCT data
    max_strain = 0.01  # Default minimum
    
    # Check Delta T data (already plotted)
    for i, center in enumerate(group_centers):
        idx = np.where(np.abs(temp_init - center) <= ASTM_TEMP_TOL)[0]
        if len(idx) >= (3 if center in cct_isotherms else 5):
            min_length = min(len(creep_curves[j]) for j in idx)
            group_data = np.array([creep_curves[j][:min_length] for j in idx])
            max_strain = max(max_strain, np.max(group_data))
    
    # Check CCT data ranges
    if cct_data:
        for temp in cct_isotherms:
            if temp in cct_data:
                max_strain = max(max_strain, np.max(cct_data[temp]['strain']))
    
    ax.set_ylim(0, 0.01)
    ax.set_xlim(0, min(delta_t_max_time, 450))
    handles, labels = ax.get_legend_handles_labels()
    # Place legend outside the plot, right side, with proper spacing
    legend = ax.legend(handles, labels, loc='center left', bbox_to_anchor=(1.02, 0.5), 
                      borderaxespad=0.5, title='Curves', edgecolor='gray',
                      fontsize=mpl.rcParams['legend.fontsize'], markerscale=2.0)
    legend.set_title('Curves', prop={'size': mpl.rcParams['legend.fontsize']})
    if save_fig:
        fig.savefig('images/creep_curves/creep_strain_curves_v2.svg', bbox_inches='tight',
                    bbox_extra_artists=[legend])
    if display:
        plt.show()
    else:
        plt.close(fig)

def plot_all_delta_t_creep_curves(save_fig=True, display=False):
    """Plot all creep strain curves without trimming, colored by final strain, rasterized."""
    set_plot_style()
    strain_full = strain
    temp_full = temp
    n_rows, n_cols, num_frames = strain_full.shape
    all_curves = [strain_full[i, j, :] for i in range(n_rows) for j in range(n_cols)]
    final_strains = [curve[-1] for curve in all_curves]
    x_vals = np.arange(num_frames)
    fig, ax = plt.subplots(figsize=(3.3, 2.5))
    for sp in ['top', 'right']:
        ax.spines[sp].set_visible(False)
    for sp in ['left', 'bottom']:
        ax.spines[sp].set_linewidth(1 * SCALING_FACTOR)
    norm = mpl.colors.Normalize(vmin=0, vmax=max(final_strains))
    cmap = plt.cm.magma
    for curve, final in zip(all_curves, final_strains):
        ax.plot(x_vals, curve, color=cmap(norm(final)), lw=1 * SCALING_FACTOR, alpha=0.5, rasterized=True)
    ax.set_xlabel(r'Time, $t$ (min)')
    ax.set_ylabel(r'Creep Strain, $\epsilon$ (mm/mm)')
    ax.set_xlim(0, min(num_frames - 1, 450))
    ax.set_ylim(0, max(np.max(curve) for curve in all_curves))
    ax.set_title(f'Total: {n_rows * n_cols} curves')
    if save_fig:
        fig.savefig('images/creep_curves/all_delta_t_creep_curves.svg', bbox_inches='tight')
    if display:
        plt.show()
    else:
        plt.close(fig)

def save_arrhenius_data(edge_buffers, save_path='results/'):
    """Save Arrhenius data for each specified edge buffer to Excel files."""
    for eb in edge_buffers:
        res = run_analysis(eb)
        if not res:
            print(f"No valid data for buffer={eb} to save.")
            continue
        df_all = pd.DataFrame({
            'Initial_Temperature_C': res['temp_init'],
            'Inverse_Temperature_K-1': res['inv_T'],
            'ln_MCSR': res['ln_MCSR'],
            'MCSR': res['MCSR']
        })
        df_all.to_excel(f'{save_path}/arrhenius_buffer_{eb}_all_data.xlsx', index=False)
        group_dfs = []
        for center in np.arange(ISOTHERM_LOW, res['temp_init'].max() + GROUP_STEP, GROUP_STEP):
            idx = np.where(np.abs(res['temp_init'] - center) <= ASTM_TEMP_TOL)[0]
            if len(idx) >= 5:
                df_group = pd.DataFrame({
                    'Temperature_Group_C': [f"{center:.0f}Â±{ASTM_TEMP_TOL:.1f}"] * len(idx),
                    'Initial_Temperature_C': res['temp_init'][idx],
                    'Inverse_Temperature_K-1': res['inv_T'][idx],
                    'ln_MCSR': res['ln_MCSR'][idx],
                    'MCSR': res['MCSR'][idx]
                })
                group_dfs.append(df_group)
        if group_dfs:
            pd.concat(group_dfs, ignore_index=True).to_excel(f'{save_path}/arrhenius_buffer_{eb}_grouped_data.xlsx', index=False)
    print(f"Arrhenius data saved to {save_path}")

def save_cov_data(edge_buffer=22, save_path='results/'):
    """Save COV vs temperature data to Excel."""
    res = run_analysis(edge_buffer)
    if not res:
        print(f"No valid data for edge_buffer={edge_buffer} to save.")
        return
    temp_init, MCSR_vals = res['temp_init'], res['MCSR']
    summary, details = [], []
    for center in np.arange(ISOTHERM_LOW, temp_init.max() + GROUP_STEP, GROUP_STEP):
        idx = np.where(np.abs(temp_init - center) <= ASTM_TEMP_TOL)[0]
        if len(idx) >= 5:
            cov = np.std(MCSR_vals[idx]) / np.mean(MCSR_vals[idx])
            summary.append({
                'Temperature_Group_C': f"{center:.0f}Â±{ASTM_TEMP_TOL:.1f}",
                'Count': len(idx),
                'Mean_MCSR': np.mean(MCSR_vals[idx]),
                'Std_MCSR': np.std(MCSR_vals[idx]),
                'COV': cov
            })
            details.append(pd.DataFrame({
                'Temperature_Group_C': [f"{center:.0f}Â±{ASTM_TEMP_TOL:.1f}"] * len(idx),
                'Initial_Temperature_C': temp_init[idx],
                'MCSR': MCSR_vals[idx]
            }))
    if summary:
        pd.DataFrame(summary).to_excel(f'{save_path}/cov_vs_temperature_summary.xlsx', index=False)
    if details:
        pd.concat(details, ignore_index=True).to_excel(f'{save_path}/cov_vs_temperature_detailed.xlsx', index=False)
    print(f"COV data saved to {save_path}")

def save_activation_energy_data(max_buffer=24, save_path='results/'):
    """Save activation energy vs edge buffer data to Excel."""
    buf, energies, errors = [], [], []
    for eb in range(1, max_buffer + 1):
        res = run_analysis(eb)
        if res:
            buf.append(eb)
            energies.append(res['Q_cr_kJ'])
            errors.append(res['Q_cr_err_kJ'])
    if not buf:
        print("No valid activation energy data to save.")
        return
    df = pd.DataFrame({
        'Buffer_Size': buf,
        'Activation_Energy_kJ_mol': energies,
        'Error_kJ_mol': errors
    })
    df.to_excel(f'{save_path}/activation_energy_vs_buffer.xlsx', index=False)
    print(f"Activation energy data saved to {save_path}")

def save_creep_curves_data(edge_buffer=22, save_path='results/'):
    """Save creep strain curves data to Excel."""
    res = run_analysis(edge_buffer)
    if not res:
        print(f"No valid data for edge_buffer={edge_buffer} to save.")
        return
    creep_curves = res['creep_curves']
    temp_init = res['temp_init']
    with pd.ExcelWriter(f'{save_path}/creep_curves_data.xlsx') as writer:
        pd.DataFrame({
            'Parameter': ['Edge Buffer', 'Temperature Tolerance', 'Analysis Start Frame', 'Analysis End Frame', 'Total Curves'],
            'Value': [edge_buffer, ASTM_TEMP_TOL, ANALYSIS_START, ANALYSIS_END, len(creep_curves)]
        }).to_excel(writer, sheet_name='Metadata', index=False)
        for center in np.arange(ISOTHERM_LOW, max(temp_init) + GROUP_STEP, GROUP_STEP):
            idx = np.where(np.abs(temp_init - center) <= ASTM_TEMP_TOL)[0]
            if len(idx) >= 5:
                min_length = min(len(creep_curves[i]) for i in idx)
                frames = np.arange(min_length)
                data_dict = {'Frame': frames}
                for j, i in enumerate(idx):
                    data_dict[f'Curve_{j+1}_Temp_{temp_init[i]:.1f}C'] = creep_curves[i][:min_length]
                data_dict['Average_Curve'] = np.mean([creep_curves[i][:min_length] for i in idx], axis=0)
                pd.DataFrame(data_dict).to_excel(writer, sheet_name=f'Temp_{center:.0f}C', index=False)
    print(f"Creep curves data saved to {save_path}")

def plot_all_techniques_comparison(edge_buffer=22, save_fig=True, display=False):
    """
    Plot data points for all 3 techniques (CCT, Delta T manual, Delta T automatic) 
    in one Arrhenius plot with slope indicators.
    """
    set_plot_style()
    
    # Get Delta T automatic data
    res = run_analysis(edge_buffer)
    if not res:
        print(f"No valid data for edge_buffer={edge_buffer}.")
        return
    
    fig, ax = plt.subplots(figsize=(10, 6))
    for sp in ['top', 'right']:
        ax.spines[sp].set_visible(False)
    for sp in ['left', 'bottom']:
        ax.spines[sp].set_linewidth(1 * SCALING_FACTOR)
    ax.xaxis.grid(True, linestyle='--', alpha=0.5)
    ax.yaxis.grid(False)
    
    # Plot Delta T automatic data points
    inv_T_deltaT = res['inv_T']
    ln_MCSR_deltaT = res['ln_MCSR']
    temp_init = res['temp_init']
    
    # Group Delta T data by temperature for better visualization
    valid_temperatures = [525, 550, 575, 600]
    colors = sns.color_palette("magma", n_colors=len(valid_temperatures))
    temp_to_color = {temp: colors[i] for i, temp in enumerate(valid_temperatures)}
    
    # Plot Delta T data points grouped by temperature
    cct_temps = [525, 550, 575, 600]  # CCT temperatures for comparison
    for temp in valid_temperatures:
        idx = np.where(np.abs(temp_init - temp) <= ASTM_TEMP_TOL)[0]
        if len(idx) >= 5:
            # Use different markers for temperatures that match CCT
            if temp in cct_temps:
                marker = 'o'  # Circle for CCT-comparable temperatures
                edgecolor = 'black'
                linewidth = 1.0 * SCALING_FACTOR
                # Make CCT-comparable temperatures more prominent
                s_size = 50 * SCALING_FACTOR
                alpha_val = 0.9
            else:
                marker = 's'  # Square for other temperatures
                edgecolor = 'gray'
                linewidth = 0.5 * SCALING_FACTOR
                s_size = 30 * SCALING_FACTOR
                alpha_val = 0.7
            
            ax.scatter(inv_T_deltaT[idx], ln_MCSR_deltaT[idx], 
                      color=temp_to_color[temp], alpha=alpha_val, s=s_size,
                      marker=marker,
                      label=f'Delta T Auto {temp}Â°C (n={len(idx)})', 
                      edgecolors=edgecolor, linewidth=linewidth)
    
    # Plot Delta T automatic regression line
    if len(inv_T_deltaT) >= 2:
        slope_deltaT, intercept_deltaT = np.polyfit(inv_T_deltaT, ln_MCSR_deltaT, 1)
        x_fit_deltaT = np.linspace(min(inv_T_deltaT), max(inv_T_deltaT), 100)
        ax.plot(x_fit_deltaT, slope_deltaT * x_fit_deltaT + intercept_deltaT,
                color='blue', lw=2 * SCALING_FACTOR, linestyle='-',
                label=f'Delta T Auto Regression (Q={-slope_deltaT * GAS_CONSTANT_J_PER_MOLK / 1000:.1f} kJ/mol)',
                alpha=0.8)
    
    # Plot CCT data points and regression
    cct = res.get('cct', {})
    if cct and 'cct_inv_T_vals' in cct and len(cct['cct_inv_T_vals']) >= 2:
        # Plot individual CCT data points with different colors for each temperature
        cct_colors = {'525': 'red', '550': 'blue', '575': 'black', '600': 'green'}
        cct_markers = {'525': 'D', '550': 'D', '575': 'D', '600': 'D'}
        
        # Plot each CCT temperature separately with distinct styling
        for i, (invT_val, ln_val) in enumerate(zip(cct['cct_inv_T_vals'], cct['cct_ln_vals'])):
            temp_c = int(1/invT_val - 273.15)
            temp_key = str(temp_c)
            color = cct_colors.get(temp_key, 'red')
            marker = cct_markers.get(temp_key, 'D')
            
            ax.scatter(invT_val, ln_val, 
                      color=color, marker=marker, s=80 * SCALING_FACTOR, alpha=0.9,
                      label=f'CCT {temp_c}Â°C', edgecolors='darkred', linewidth=2 * SCALING_FACTOR)
        
        # Plot CCT regression line
        slope_cct = cct['cct_slope']
        intercept_cct = np.polyfit(cct['cct_inv_T_vals'], cct['cct_ln_vals'], 1)[1]
        x_fit_cct = np.linspace(min(cct['cct_inv_T_vals']), max(cct['cct_inv_T_vals']), 100)
        ax.plot(x_fit_cct, slope_cct * x_fit_cct + intercept_cct,
                color='red', lw=2 * SCALING_FACTOR, linestyle='-',
                label=f'CCT Regression (Q={-slope_cct * GAS_CONSTANT_J_PER_MOLK / 1000:.1f} kJ/mol)',
                alpha=0.8)
    
    # Load and plot actual Delta T manual data from Excel
    manual_data = load_manual_data_from_excel()
    if manual_data is not None:
        # Plot actual manual data points with distinct styling
        ax.scatter(manual_data['manual_inv_T'], manual_data['manual_ln_mcsr'], 
                  color='green', marker='^', s=100 * SCALING_FACTOR, alpha=0.9,
                  label=f'Delta T Manual (n={len(manual_data["manual_temps"])}, Q={manual_data["manual_Q"]:.1f} kJ/mol)', 
                  edgecolors='darkgreen', linewidth=2 * SCALING_FACTOR)
        
        # Plot manual regression line
        manual_line = manual_data['manual_coeffs'][0] * manual_data['manual_inv_T'] + manual_data['manual_coeffs'][1]
        ax.plot(manual_data['manual_inv_T'], manual_line, 'g--', linewidth=3 * SCALING_FACTOR, alpha=0.9)
    else:
        print("Warning: Manual Delta-T data could not be loaded for comparison plot.")
    
    
    # Set labels and formatting
    ax.set_xlabel(r'Inverse Temperature, $1/T$ (K$^{-1}$)')
    ax.set_ylabel(r'Natural Logarithm of MCSR, $\ln(\mathrm{MCSR})$ (s$^{-1}$)')
    
    # Set x-axis ticks to show temperature values
    tick_positions = [1 / (temp + 273.15) for temp in [525, 550, 575, 600]]
    ax.set_xticks(tick_positions)
    tick_labels = [rf"{temp}$^\circ$C" for temp in [525, 550, 575, 600]]
    ax.set_xticklabels(tick_labels)
    
    # Add title with activation energies
    title_text = f'Comparison of Creep Testing Techniques (Buffer={edge_buffer})\n'
    if 'slope' in res:
        title_text += f' | Delta T Auto: Q={-res["slope"] * GAS_CONSTANT_J_PER_MOLK / 1000:.1f} kJ/mol'
    if cct and 'cct_slope' in cct:
        title_text += f' | CCT: Q={-cct["cct_slope"] * GAS_CONSTANT_J_PER_MOLK / 1000:.1f} kJ/mol'
    if manual_data is not None:
        title_text += f' | Delta T Manual: Q={manual_data["manual_Q"]:.1f} kJ/mol'
    else:
        title_text += ' | Delta T Manual: unavailable'
    
    ax.set_title(title_text, fontsize=mpl.rcParams['font.size'], pad=20)
    
    # Add legend positioned at the right side of the plot with proper spacing
    legend = ax.legend(loc='center left', bbox_to_anchor=(1.02, 0.5), frameon=True, 
                      edgecolor='gray', fontsize=mpl.rcParams['legend.fontsize'], ncol=1,
                      borderaxespad=0.5)
    legend.set_title('Techniques', prop={'size': mpl.rcParams['legend.fontsize']})
    
    # Use tight_layout with proper margins to avoid overlapping
    plt.tight_layout(rect=[0, 0, 0.8, 1])
    
    if save_fig:
        fig.savefig('images/comparison/all_techniques_comparison.svg', bbox_inches='tight')
    if display:
        plt.show()
    else:
        plt.close(fig)

def plot_arrhenius_spatial_stress_effects(edge_buffers, save_fig=True, display=False):
    """Generate Arrhenius spatial stress effects plots for specified edge buffers."""
    set_plot_style()
    
    for eb in edge_buffers:
        res = run_analysis(eb)
        if not res:
            print(f"No valid data for edge_buffer={eb}.")
            continue
            
        # We need to get the original pixel coordinates to calculate distance from center
        # Re-run analysis to get the pixel coordinates
        if eb == 0:
            strain_trim, temp_trim = strain, temp
        else:
            strain_trim = strain[eb:-eb, eb:-eb, :]
            temp_trim = temp[eb:-eb, eb:-eb, :]
        
        init_temp = temp_trim[:, :, 0]
        final_temp = temp_trim[:, :, -1]
        valid_mask = (init_temp >= INITIAL_TEMP_THRESHOLD) & (np.abs(final_temp - init_temp) <= ASTM_TEMP_TOL)
        valid_indices = np.where(valid_mask)
        
        if valid_indices[0].size == 0:
            print(f"No valid datapoints found for edge_buffer={eb}.")
            continue
        
        # Calculate horizontal distance from center for each valid pixel
        n_rows, n_cols = strain_trim.shape[:2]
        center_row, center_col = n_rows // 2, n_cols // 2
        
        # Get the row and column indices of valid datapoints
        valid_rows = valid_indices[0]
        valid_cols = valid_indices[1]
        
        # Calculate horizontal distance from center (using column distance)
        horizontal_distances = np.abs(valid_cols - center_col)
        
        # Filter out zero curves and get corresponding distances
        temp_valid = init_temp[valid_mask]
        all_creep_curves = [strain_trim[i, j, :] for i, j in zip(valid_rows, valid_cols)]
        filtered_data = [(curve, T, dist) for curve, T, dist in zip(all_creep_curves, temp_valid, horizontal_distances) 
                         if not np.allclose(curve, 0)]
        
        if not filtered_data:
            print("All valid curves are zero. Skipping analysis.")
            continue
        
        valid_curves, temp_valid, horizontal_distances = zip(*filtered_data)
        temp_valid = np.array(temp_valid)
        horizontal_distances = np.array(horizontal_distances)
        
        # Calculate MCSR for each curve
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
            print("No valid slopes found.")
            continue
        
        # Filter data based on valid slopes
        slopes = slopes[valid]
        temp_valid = temp_valid[valid]
        horizontal_distances = horizontal_distances[valid]
        
        # Calculate Arrhenius parameters
        ln_MCSR = np.log(slopes)
        inv_T = 1 / (temp_valid + 273.15)
        
        fig, ax = plt.subplots(figsize=(3.3, 2.5))
        for sp in ['top', 'right']:
            ax.spines[sp].set_visible(False)
        for sp in ['left', 'bottom']:
            ax.spines[sp].set_linewidth(1.0 * SCALING_FACTOR)
        ax.xaxis.grid(True, linestyle='--', alpha=0.5)
        ax.yaxis.grid(False)
        
        # Create discrete color groups based on distance from center
        # Group distances into bins for better visual distinction
        max_distance = np.max(horizontal_distances)
        n_bins = min(6, max_distance + 1)  # Limit to 6 color groups for better distinction
        distance_bins = np.linspace(0, max_distance, n_bins)
        
        # Use the same color palette as the reference plot for consistency
        colors = sns.color_palette("magma", n_colors=n_bins)
        
        # Plot data points colored by distance group
        for i, (inv_t_val, ln_mcsr_val, dist) in enumerate(zip(inv_T, ln_MCSR, horizontal_distances)):
            # Find which bin this distance belongs to
            bin_idx = np.digitize(dist, distance_bins) - 1
            bin_idx = max(0, min(bin_idx, len(colors) - 1))  # Ensure valid index
            color = colors[bin_idx]
            
            ax.plot(inv_t_val, ln_mcsr_val, marker='o', markersize=3 * SCALING_FACTOR,
                    linestyle='None', color=color, alpha=0.85,
                    label='Î”T Data Points' if i == 0 else "",
                    path_effects=[path_effects.withStroke(foreground='gray')])
        
        # Add CCT data for comparison
        cct = res.get('cct', {})
        if cct and 'cct_inv_T_vals' in cct and len(cct['cct_inv_T_vals']) >= 2:
            # Plot CCT regression line
            coef = np.polyfit(cct['cct_inv_T_vals'], cct['cct_ln_vals'], 1)
            slope_cct = coef[0]
            x_fit_cct = np.linspace(min(cct['cct_inv_T_vals']), max(cct['cct_inv_T_vals']), 100)
            ax.plot(x_fit_cct, slope_cct * x_fit_cct + coef[1],
                    color='green', lw=1.5 * SCALING_FACTOR, linestyle='-',
                    label='CCT Regression',
                    path_effects=[path_effects.withStroke(foreground='gray')], alpha=0.7)
            
            # Plot CCT data points with temperature-specific markers
            cct_marker_map = {525: 'o', 550: 's', 575: '^', 600: 'D'}
            cct_temp_tol = 3.0
            plotted_cct_labels = set()
            for invT_val, ln_val in zip(cct['cct_inv_T_vals'], cct['cct_ln_vals']):
                temp_c = 1 / invT_val - 273.15
                closest_temp = min(cct_marker_map.keys(), key=lambda T: abs(T - temp_c))
                if abs(closest_temp - temp_c) > cct_temp_tol:
                    marker = 'D'
                    label = 'CCT Data Points'
                else:
                    marker = cct_marker_map[closest_temp]
                    label = f'CCT Data Points {closest_temp}Â°C'
                label_to_use = label if label not in plotted_cct_labels else None
                if label_to_use:
                    plotted_cct_labels.add(label_to_use)
                ax.plot(invT_val, ln_val, marker=marker, markersize=6 * SCALING_FACTOR, 
                        linestyle='None', markerfacecolor='green', 
                        markeredgecolor='gray', markeredgewidth=0.5 * SCALING_FACTOR,
                        label=label_to_use)
        
        # Add Manual extract data and line (plot with higher zorder to appear above CCT)
        manual_data = load_manual_data_from_excel()
        if manual_data is not None:
            # Plot manual data points with distinct styling
            ax.scatter(manual_data['manual_inv_T'], manual_data['manual_ln_mcsr'], 
                      color='black', marker='^', s=80 * SCALING_FACTOR, alpha=0.9,
                      label=rf'Manual $\Delta T$ (n={len(manual_data["manual_temps"])})', 
                      edgecolors='black', linewidth=1.0 * SCALING_FACTOR, zorder=5)
            
            # Plot manual regression line
            manual_line = manual_data['manual_coeffs'][0] * manual_data['manual_inv_T'] + manual_data['manual_coeffs'][1]
            ax.plot(manual_data['manual_inv_T'], manual_line, 'k--', linewidth=2 * SCALING_FACTOR, alpha=0.9, zorder=4,
                    label=rf'Manual $\Delta T$ Regression (Q={manual_data["manual_Q"]:.1f} kJ/mol)')
        
        # Set labels and formatting
        ax.set_xlabel(r'Inverse Temperature, $1/T$ (K$^{-1}$)')
        ax.set_ylabel(r'Natural Logarithm of MCSR, $\ln(\mathrm{MCSR})$ (s$^{-1}$)')
        
        # Set x-axis ticks to show inverse temperature values
        tick_positions = [1 / (temp + 273.15) for temp in [525, 550, 575, 600]]
        ax.set_xticks(tick_positions)
        tick_labels = [f"{1/(temp + 273.15):.7f}" for temp in [525, 550, 575, 600]]
        ax.set_xticklabels(tick_labels)
        
        # Build legend for all data
        key_entries = {}
        for h, l in zip(*ax.get_legend_handles_labels()):
            # Handle manual regression label with variable Q value
            if r'Manual $\Delta T$ Regression' in l:
                key_entries[r'Manual $\Delta T$ Regression'] = h
            elif l in ['CCT Regression', 'Î”T Data Points', r'$\Delta T$ Data Points', 'Delta T Regression']:
                # Update labels to use proper delta symbol
                if l == 'Delta T Regression':
                    key_entries[r'$\Delta T$ Regression'] = h
                else:
                    key_entries[l] = h
            elif l and l.startswith('CCT Data Points'):
                key_entries[l] = h
            elif l.startswith(r'Manual $\Delta T$ (n='):
                key_entries[r'Manual $\Delta T$'] = h
        legend = ax.legend(list(key_entries.values()), list(key_entries.keys()), loc="best", frameon=True, edgecolor='gray')
        
        # Colorbar: dynamically positioned for distance from center
        xmin, xmax = ax.get_xlim()
        norm_cb = mpl.colors.Normalize(vmin=0, vmax=max_distance)
        sm = mpl.cm.ScalarMappable(cmap=mpl.cm.magma, norm=norm_cb)
        sm.set_array([])
        cbar_ax = fig.add_axes([0.125 * SCALING_FACTOR, 0.90 * SCALING_FACTOR, 0.775, 0.03])
        cbar = fig.colorbar(sm, cax=cbar_ax, orientation='horizontal')
        cbar.set_label('Distance from Center (datapoints)', labelpad=10 * SCALING_FACTOR)
        cbar.ax.xaxis.set_label_position('top')
        cbar.ax.xaxis.tick_top()
        
        if save_fig:
            fig.savefig(f'images/spatial_effects/arrhenius_spatial_stress_effects_buffer_{eb}.svg', bbox_inches='tight',
                        bbox_extra_artists=[legend, cbar_ax] if legend and cbar_ax else None)
        if display:
            plt.show()
        else:
            plt.close(fig)

def plot_arrhenius_with_spatial_coloring(edge_buffer=0, save_fig=True, display=False):
    """
    Plot Arrhenius data with color coding based on horizontal distance from sample center.
    This helps visualize if stress state variations (due to position) affect the creep behavior.
    """
    set_plot_style()
    
    # Get Delta T automatic data
    res = run_analysis(edge_buffer)
    if not res:
        print(f"No valid data for edge_buffer={edge_buffer}.")
        return
    
    # We need to get the original pixel coordinates to calculate distance from center
    # Re-run analysis to get the pixel coordinates
    if edge_buffer == 0:
        strain_trim, temp_trim = strain, temp
    else:
        strain_trim = strain[edge_buffer:-edge_buffer, edge_buffer:-edge_buffer, :]
        temp_trim = temp[edge_buffer:-edge_buffer, edge_buffer:-edge_buffer, :]
    
    init_temp = temp_trim[:, :, 0]
    final_temp = temp_trim[:, :, -1]
    valid_mask = (init_temp >= INITIAL_TEMP_THRESHOLD) & (np.abs(final_temp - init_temp) <= ASTM_TEMP_TOL)
    valid_indices = np.where(valid_mask)
    
    if valid_indices[0].size == 0:
        print(f"No valid datapoints found for edge_buffer={edge_buffer}.")
        return
    
    # Calculate horizontal distance from center for each valid pixel
    n_rows, n_cols = strain_trim.shape[:2]
    center_row, center_col = n_rows // 2, n_cols // 2
    
    # Get the row and column indices of valid datapoints
    valid_rows = valid_indices[0]
    valid_cols = valid_indices[1]
    
    # Calculate horizontal distance from center (using column distance)
    horizontal_distances = np.abs(valid_cols - center_col)
    
    # Filter out zero curves and get corresponding distances
    temp_valid = init_temp[valid_mask]
    all_creep_curves = [strain_trim[i, j, :] for i, j in zip(valid_rows, valid_cols)]
    filtered_data = [(curve, T, dist) for curve, T, dist in zip(all_creep_curves, temp_valid, horizontal_distances) 
                     if not np.allclose(curve, 0)]
    
    if not filtered_data:
        print("All valid curves are zero. Skipping analysis.")
        return
    
    valid_curves, temp_valid, horizontal_distances = zip(*filtered_data)
    temp_valid = np.array(temp_valid)
    horizontal_distances = np.array(horizontal_distances)
    
    # Calculate MCSR for each curve
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
        print("No valid slopes found.")
        return
    
    # Filter data based on valid slopes
    slopes = slopes[valid]
    temp_valid = temp_valid[valid]
    horizontal_distances = horizontal_distances[valid]
    
    # Calculate Arrhenius parameters
    ln_MCSR = np.log(slopes)
    inv_T = 1 / (temp_valid + 273.15)
    
    fig, ax = plt.subplots(figsize=(3.3, 2.5))
    for sp in ['top', 'right']:
        ax.spines[sp].set_visible(False)
    for sp in ['left', 'bottom']:
        ax.spines[sp].set_linewidth(1.0 * SCALING_FACTOR)
    ax.xaxis.grid(True, linestyle='--', alpha=0.5)
    ax.yaxis.grid(False)
    
    # Create color map based on horizontal distance from center
    max_distance = np.max(horizontal_distances)
    norm = mpl.colors.Normalize(vmin=0, vmax=max_distance)
    cmap = plt.cm.magma  # Use magma for better color perception
    
    # Plot data points colored by horizontal distance from center
    scatter = ax.scatter(inv_T, ln_MCSR, c=horizontal_distances, cmap=cmap, norm=norm,
                        s=3 * SCALING_FACTOR, alpha=0.85, edgecolors='none',
                        label=r'$\Delta T$ Data Points')
    
    # Plot regression line for all data
    if len(inv_T) >= 2:
        slope, intercept = np.polyfit(inv_T, ln_MCSR, 1)
        x_fit = np.linspace(min(inv_T), max(inv_T), 100)
        ax.plot(x_fit, slope * x_fit + intercept,
                color='orange', lw=1.5 * SCALING_FACTOR, linestyle='-',
                label='Delta T Regression',
                path_effects=[path_effects.withStroke(foreground='gray')],
                alpha=0.7)
    
    # Add CCT data for comparison
    cct = res.get('cct', {})
    if cct and 'cct_inv_T_vals' in cct and len(cct['cct_inv_T_vals']) >= 2:
        # Plot CCT regression line
        coef = np.polyfit(cct['cct_inv_T_vals'], cct['cct_ln_vals'], 1)
        slope_cct = coef[0]
        x_fit_cct = np.linspace(min(cct['cct_inv_T_vals']), max(cct['cct_inv_T_vals']), 100)
        ax.plot(x_fit_cct, slope_cct * x_fit_cct + coef[1],
                color='green', lw=1.5 * SCALING_FACTOR, linestyle='-',
                label='CCT Regression',
                path_effects=[path_effects.withStroke(foreground='gray')], alpha=0.7)
        
        # Plot CCT data points
        first_point = True
        for invT_val, ln_val in zip(cct['cct_inv_T_vals'], cct['cct_ln_vals']):
            if first_point:
                ax.plot(invT_val, ln_val, marker='D', markersize=6 * SCALING_FACTOR, 
                        linestyle='None', markerfacecolor='green', 
                        markeredgecolor='gray', markeredgewidth=0.5 * SCALING_FACTOR,
                        label='CCT Data Points')
                first_point = False
            else:
                ax.plot(invT_val, ln_val, marker='D', markersize=6 * SCALING_FACTOR, 
                        linestyle='None', markerfacecolor='green', 
                        markeredgecolor='gray', markeredgewidth=0.5 * SCALING_FACTOR)
    
    # Add Manual extract data and line
    manual_data = load_manual_data_from_excel()
    if manual_data is not None:
        # Plot manual data points with distinct styling
        ax.scatter(manual_data['manual_inv_T'], manual_data['manual_ln_mcsr'], 
                  color='black', marker='^', s=80 * SCALING_FACTOR, alpha=0.9,
                  label=rf'Manual $\Delta T$ (n={len(manual_data["manual_temps"])})', 
                  edgecolors='black', linewidth=1.0 * SCALING_FACTOR, zorder=5)
        
        # Plot manual regression line
        manual_line = manual_data['manual_coeffs'][0] * manual_data['manual_inv_T'] + manual_data['manual_coeffs'][1]
        ax.plot(manual_data['manual_inv_T'], manual_line, 'k--', linewidth=2 * SCALING_FACTOR, alpha=0.9, zorder=4,
                label=rf'Manual $\Delta T$ Regression (Q={manual_data["manual_Q"]:.1f} kJ/mol)')
    
    # Set labels and formatting
    ax.set_xlabel(r'Inverse Temperature, $1/T$ (K$^{-1}$)')
    ax.set_ylabel(r'Natural Logarithm of MCSR, $\ln(\mathrm{MCSR})$ (s$^{-1}$)')
    
    # Set x-axis ticks to show inverse temperature values
    tick_positions = [1 / (temp + 273.15) for temp in [525, 550, 575, 600]]
    ax.set_xticks(tick_positions)
    tick_labels = [f"{1/(temp + 273.15):.7f}" for temp in [525, 550, 575, 600]]
    ax.set_xticklabels(tick_labels)
    
    # Build legend for all data
    key_entries = {}
    for h, l in zip(*ax.get_legend_handles_labels()):
        if r'Manual $\Delta T$ Regression' in l:
            key_entries[r'Manual $\Delta T$ Regression'] = h
        elif l in ['CCT Regression', r'$\Delta T$ Data Points', 'Delta T Regression']:
            key_entries[l] = h
        elif l and l.startswith('CCT Data Points'):
            key_entries[l] = h
        elif l.startswith(r'Manual $\Delta T$ (n='):
            key_entries[r'Manual $\Delta T$'] = h
    legend = ax.legend(list(key_entries.values()), list(key_entries.keys()), loc="best", frameon=True, edgecolor='gray')
    
    # Colorbar: dynamically positioned for distance from center
    xmin, xmax = ax.get_xlim()
    norm_cb = mpl.colors.Normalize(vmin=0, vmax=max_distance)
    sm = mpl.cm.ScalarMappable(cmap=mpl.cm.magma, norm=norm_cb)
    sm.set_array([])
    cbar_ax = fig.add_axes([0.125 * SCALING_FACTOR, 0.90 * SCALING_FACTOR, 0.775, 0.03])
    cbar = fig.colorbar(sm, cax=cbar_ax, orientation='horizontal')
    cbar.set_label('Distance from Center (datapoints)', labelpad=10 * SCALING_FACTOR)
    cbar.ax.xaxis.set_label_position('top')
    cbar.ax.xaxis.tick_top()
    
    if save_fig:
        fig.savefig('images/spatial_effects/arrhenius_spatial_stress_effects.svg', bbox_inches='tight',
                    bbox_extra_artists=[legend, cbar_ax] if legend and cbar_ax else None)
    if display:
        plt.show()
    else:
        plt.close(fig)

def plot_manual_delta_t_extraction(edge_buffer=22, save_fig=True, display=False):
    """
    Plot creep curves for CCTs and manual Delta T data in the same style as creep strain curves.
    Shows only CCT data and manual Delta T data, removing non-manual Delta T data.
    """
    set_plot_style()
    
    # Define temperatures
    temperatures = [525, 550, 575, 600]
    
    # Create figure with same style as creep strain curves
    fig, ax = plt.subplots(figsize=(3.3, 2.5), facecolor='white')
    for sp in ['top', 'right']:
        ax.spines[sp].set_visible(False)
    for sp in ['left', 'bottom']:
        ax.spines[sp].set_linewidth(1 * SCALING_FACTOR)
    
    # Analysis region
    ax.axvspan(ANALYSIS_START, ANALYSIS_END, alpha=0.1, color='gray', hatch='///', zorder=-1)
    ax.axvline(ANALYSIS_START, color='gray', linestyle='--', alpha=0.8, zorder=-1,
               label='MCSR Analysis Region')
    ax.axvline(ANALYSIS_END, color='gray', linestyle='--', alpha=0.8, zorder=-1)
    
    # Colors and markers
    colors = sns.color_palette("magma", n_colors=len(temperatures))
    markers = ['o', 's', '^', 'D']
    cct_markers = ['o', 's', '^', 'D']
    
    # Load and plot CCT data as symbols that intercalate with manual data
    cct_data = load_cct_data()
    if cct_data:
        for i, temp in enumerate(temperatures):
            if temp in cct_data:
                time_vals = cct_data[temp]['time']
                strain_vals = cct_data[temp]['strain']
                # Use green filled symbols that intercalate with manual data
                # Manual data uses markevery=20 starting at 0 (positions: 0, 20, 40, 60, 80, 100...)
                # CCT uses markevery=20 starting at 10 (positions: 10, 30, 50, 70, 90, 110...)
                ax.plot(time_vals, strain_vals,
                       linestyle='None', 
                       linewidth=1.0 * SCALING_FACTOR,
                       alpha=0.7,
                       marker=cct_markers[i],
                       markersize=3 * SCALING_FACTOR,
                       markevery=(10, 20),  # Start at position 10, then every 20 points
                       markerfacecolor='green',
                       markeredgecolor='black',
                       markeredgewidth=0.5 * SCALING_FACTOR,
                       zorder=1,
                       label=rf'CCT {temp:.0f}$^\circ$C $\pm$ {ASTM_TEMP_TOL:.1f}$^\circ$C')
    
    # Load and plot manual Delta T data (both individual and average curves, like in creep strain plot)
    # Use same markers as CCT for each temperature to match
    manual_markers = ['o', 's', '^', 'D']
    
    for i, temp in enumerate(temperatures):
        try:
            data = load_manual_data_sheet(temp)
            if data is not None:
                
                # Fix corrupted time column for 600Â°C file
                if temp == 600:
                    # The 600Â°C file has corrupted time data - reconstruct it
                    time_col = data.columns[0]
                    data[time_col] = range(len(data))  # 0 to 449 minutes
                
                # Get time column (first column)
                time_col = data.columns[0]
                time_data = data[time_col].values
                
                # Get strain columns and apply exact paper methodology filtering
                all_strain_cols = [col for col in data.columns if col.startswith('E') or col.startswith('Î”T')]
                
                # Get the correct columns according to paper methodology
                correct_columns = get_manual_data_columns_by_temperature(temp)
                
                strain_cols = []
                for col in all_strain_cols:
                    # Extract base column name (e.g., "E0" from "E0 - 600")
                    base_col_name = col.split('-')[0].strip() if '-' in col else col.strip()
                    
                    if base_col_name in correct_columns:
                        strain_cols.append(col)
                
                # Filter out columns with no valid data (like E39 in 600Â°C)
                valid_strain_cols = []
                for col in strain_cols:
                    strain_data = data[col].values
                    valid_data = strain_data[~np.isnan(strain_data)]
                    if len(valid_data) > 0 and np.max(np.abs(valid_data)) > 1e-6:
                        valid_strain_cols.append(col)
                
                # Plot individual curves (like in creep strain plot) - using black and white styling
                for j, col in enumerate(valid_strain_cols):
                    strain_data = data[col].values
                    ax.plot(time_data, strain_data,
                           color='black', linestyle='None', linewidth=1 * SCALING_FACTOR,
                           alpha=0.5, zorder=2, marker=manual_markers[i], 
                           markersize=3 * SCALING_FACTOR, markevery=20,
                           markerfacecolor='white', markeredgecolor='black', markeredgewidth=0.5 * SCALING_FACTOR)
                
                # Plot average curve - using black and white styling
                if valid_strain_cols:
                    strain_data_all = np.array([data[col].values for col in valid_strain_cols])
                    avg_strain = np.mean(strain_data_all, axis=0)
                    
                    ax.plot(time_data, avg_strain,
                           color='black', linestyle='None', linewidth=1 * SCALING_FACTOR,
                           alpha=0.9, marker=manual_markers[i], markersize=3 * SCALING_FACTOR, markevery=20,
                           label=rf'Manual $\Delta T$ {temp}$^\circ$C (n={len(valid_strain_cols)})', zorder=2,
                           markerfacecolor='white', markeredgecolor='black', markeredgewidth=0.5 * SCALING_FACTOR)
                    
        except Exception as e:
            print(f"Error loading manual data for {temp}Â°C: {e}")
            continue
    
    # Set labels and formatting (same as creep strain curves)
    ax.set_xlabel(r'Time, $t$ (min)')
    ax.set_ylabel(r'Creep Strain, $\epsilon$ (mm/mm)')
    ax.set_xlim(0, 455)  # Extended slightly to prevent markers at 450 from being clipped
    
    # Set y-axis limits based on data
    all_strain_data = []
    if cct_data:
        for temp in temperatures:
            if temp in cct_data:
                all_strain_data.extend(cct_data[temp]['strain'])
    
    if all_strain_data:
        ax.set_ylim(0, max(all_strain_data) * 1.05)
    
    # Create legend (same style as creep strain curves)
    handles, labels = ax.get_legend_handles_labels()
    legend = ax.legend(handles, labels, loc='center left', bbox_to_anchor=(1.02, 0.5), 
                      borderaxespad=0.5, title='Curves', edgecolor='gray',
                      fontsize=mpl.rcParams['legend.fontsize'])
    legend.set_title('Curves', prop={'size': mpl.rcParams['legend.fontsize']})
    
    if save_fig:
        fig.savefig('images/manual_data/manual_delta_t_extraction.svg', bbox_inches='tight',
                    bbox_extra_artists=[legend])
    if display:
        plt.show()
    else:
        plt.close(fig)

def plot_temperature_groups(save_fig=True, display=False):
    """Plot temperature group comparison data from Excel."""
    set_plot_style()
    try:
        excel_path = WORKBOOK_PATH
        df = pd.read_excel(excel_path, sheet_name='all_data')
    except FileNotFoundError:
        abs_path = os.path.join(os.getcwd(), '..', 'Data (Excels)', 'new', 'main.xlsx')
        df = pd.read_excel(abs_path, sheet_name='all_data')
    groups = {
        '600 Bottom': df.iloc[2:, 1:6].values,
        '600 Top':    df.iloc[2:, 36:41].values,
        '575 Bottom': df.iloc[2:, 6:11].values,
        '575 Top':    df.iloc[2:, 21:26].values,
        '550 Bottom': df.iloc[2:, 11:16].values,
        '550 Top':    df.iloc[2:, 26:31].values,
        '525 Bottom': df.iloc[2:, 31:36].values,
        '525 Top':    df.iloc[2:, 16:21].values,
    }
    fig, ax = plt.subplots(figsize=mpl.rcParams['figure.figsize'])
    for sp in ['top', 'right']:
        ax.spines[sp].set_visible(False)
    for sp in ['left', 'bottom']:
        ax.spines[sp].set_linewidth(1 * SCALING_FACTOR)
    time_axis = np.arange(df.shape[0] - 2)
    temperatures = [600, 575, 550, 525]
    palette = sns.color_palette("magma", n_colors=len(temperatures))
    sorted_temps = sorted(temperatures, reverse=True)
    base_colors = {temp: palette[i] for i, temp in enumerate(sorted_temps)}
    def lighten_color(color, amt=0.3):
        import colorsys
        r, g, b = color
        h, l, s = colorsys.rgb_to_hls(r, g, b)
        l = min(1, l + amt * (1 - l))
        return colorsys.hls_to_rgb(h, l, s)
    lightened = {temp: lighten_color(base_colors[temp]) for temp in sorted_temps}
    legend_handles, legend_labels = [], []
    for temp in sorted(temperatures, reverse=True):
        bottom = groups[f'{temp} Bottom']
        top = groups[f'{temp} Top']
        t_bottom = time_axis[:min(len(time_axis), bottom.shape[0])]
        # Plot one marker for the bottom group.
        for col in range(bottom.shape[1]):
            if col == 0:
                line, = ax.plot(t_bottom, bottom[:, col], color=base_colors[temp],
                                linestyle='-', marker='o', markersize=3 * SCALING_FACTOR, markevery=50, alpha=0.9, 
                                label=rf'{temp}$^\circ$C Bottom', zorder=10)
                legend_handles.append(line)
                legend_labels.append(rf'{temp}$^\circ$C Bottom')
            else:
                ax.plot(t_bottom, bottom[:, col], color=base_colors[temp],
                        linestyle='-', marker='', markersize=3 * SCALING_FACTOR, markevery=50, alpha=0.9)
        t_top = time_axis[:min(len(time_axis), top.shape[0])]
        # Plot one marker for the top group.
        for col in range(top.shape[1]):
            if col == 0:
                line, = ax.plot(t_top, top[:, col], color=lightened[temp],
                                linestyle='-', marker='s', markersize=3 * SCALING_FACTOR, markevery=50, alpha=0.9,
                                label=rf'{temp}$^\circ$C Top', zorder=10)
                legend_handles.append(line)
                legend_labels.append(rf'{temp}$^\circ$C Top')
            else:
                ax.plot(t_top, top[:, col], color=lightened[temp],
                        linestyle='-', marker='', markersize=3 * SCALING_FACTOR, markevery=50, alpha=0.9, 
                        markeredgecolor='gray')
    for temp in temperatures:
        ax.axhline(y=temp, color='gray', linestyle='-', alpha=0.3, linewidth=1 * SCALING_FACTOR)
    ax.set_xlabel(r'Time, $t$ (min)')
    ax.set_ylabel(r'Temperature, $T$ ($^\circ$C)')
    ax.set_ylim(min(temperatures) - 10, max(temperatures) + 10)
    ax.set_yticks(temperatures)
    ax.set_yticklabels([rf"{t}$^\circ$C" for t in temperatures])
    ax.set_xlim(0, min(time_axis[-1], 450))
    unique = {}
    for h, l in zip(legend_handles, legend_labels):
        if l not in unique:
            unique[l] = h
    # Place legend outside the plot, right side, vertically centered with proper spacing
    legend = ax.legend(
        list(unique.values()), list(unique.keys()),
        loc="center left", bbox_to_anchor=(1.05, 0.5),
        title="Temperature Groups", frameon=True, edgecolor='gray', ncol=1,
        borderaxespad=0.5, fontsize=mpl.rcParams['legend.fontsize']
    )
    legend.set_title('Temperature Groups', prop={'size': mpl.rcParams['legend.fontsize']})
    
    # Use tight_layout with proper margins to avoid overlapping
    plt.tight_layout(rect=[0, 0, 0.8, 1])
    
    if save_fig:
        fig.savefig('images/temperature_analysis/temperature_groups.svg', bbox_inches='tight',
                    bbox_extra_artists=[legend])
        plt.close(fig)
    elif display:
        plt.show()

def main():
    print("Starting creep analysis and visualization...")
    # Load the CCT data once.
    cct_data = load_cct_data()
    edge_buffers = [0, 1, 5, 10, 15, 22, 23, 24, 25]
    try:
        plot_arrhenius(edge_buffers, save_fig=True)
        save_arrhenius_data(edge_buffers)
    except Exception as e:
        print("Error in Arrhenius analysis:", e)
    try:
        plot_cov_vs_temperature(edge_buffer=22, save_fig=True)
        save_cov_data(edge_buffer=22)
    except Exception as e:
        print("Error in COV vs Temperature analysis:", e)
    try:
        plot_activation_energy_vs_buffer(max_buffer=24, save_fig=True)
        save_activation_energy_data(max_buffer=24)
    except Exception as e:
        print("Error in Activation Energy vs Buffer analysis:", e)
    try:
        plot_creep_curves(edge_buffer=22, save_fig=True, cct_data=cct_data)
        plot_creep_curves_v2(edge_buffer=22, save_fig=True, cct_data=cct_data)
        save_creep_curves_data(edge_buffer=22)
    except Exception as e:
        print("Error in Creep Curves analysis:", e)
    try:
        plot_all_delta_t_creep_curves(save_fig=True)
    except Exception as e:
        print("Error in All Delta T Creep Curves plot:", e)
    try:
        plot_temperature_groups(save_fig=True)
    except Exception as e:
        print("Error in Temperature Groups plot:", e)
    try:
        plot_arrhenius_spatial_stress_effects(edge_buffers, save_fig=True)
    except Exception as e:
        print("Error in Spatial Stress Effects plot:", e)
    try:
        calculate_activation_energy(edge_buffer=22, save_path='results/activation_energy_calculations.xlsx')
    except Exception as e:
        print("Error in activation energy calculation:", e)
    try:
        plot_all_techniques_comparison(edge_buffer=22, save_fig=True)
    except Exception as e:
        print("Error in all techniques comparison plot:", e)
    try:
        plot_arrhenius_with_spatial_coloring(edge_buffer=0, save_fig=True)
    except Exception as e:
        print("Error in spatial stress effects plot:", e)
    try:
        plot_manual_delta_t_extraction(edge_buffer=22, save_fig=True)
    except Exception as e:
        print("Error in manual Delta T extraction plot:", e)
    try:
        from src.pipeline.source_data_export import export_source_data_workbook

        export_source_data_workbook()
    except Exception as e:
        print("Source data export:", e)
    print("Analysis complete. All figures and data files generated.")

def test_all_techniques_plot():
    """Test function to run just the all techniques comparison plot."""
    print("Testing all techniques comparison plot...")
    try:
        plot_all_techniques_comparison(edge_buffer=22, save_fig=True, display=False)
        print("All techniques comparison plot generated successfully!")
    except Exception as e:
        print(f"Error in all techniques comparison plot: {e}")
        import traceback
        traceback.print_exc()

def test_spatial_stress_plot():
    """Test function to run just the spatial stress effects plot."""
    print("Testing spatial stress effects plot...")
    try:
        plot_arrhenius_with_spatial_coloring(edge_buffer=0, save_fig=True, display=False)
        print("Spatial stress effects plot generated successfully!")
    except Exception as e:
        print(f"Error in spatial stress effects plot: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
