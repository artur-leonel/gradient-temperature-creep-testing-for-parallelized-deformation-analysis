# Manuscript / supplementary to code outputs (SVG)

Generated figures live under `images/`. Align names with final published figure numbering if needed.

## Pipeline outputs

| Path | Producer |
|---|---|
| `images/arrhenius/arrhenius_buffer_*.svg` | `plot_arrhenius` |
| `images/activation_energy/activation_energy_vs_buffer.svg` | `plot_activation_energy_vs_buffer` |
| `images/temperature_analysis/cov_vs_temperature.svg` | `plot_cov_vs_temperature` |
| `images/creep_curves/creep_strain_curves.svg` | `plot_creep_curves` |
| `images/creep_curves/creep_strain_curves_v2.svg` | `plot_creep_strain_curves_with_manual_data` |
| `images/creep_curves/all_delta_t_creep_curves.svg` | `plot_all_delta_t_creep_curves` |
| `images/temperature_analysis/temperature_groups.svg` | `plot_temperature_groups` |
| `images/spatial_effects/arrhenius_spatial_stress_effects_buffer_*.svg` | `plot_arrhenius_spatial_stress_effects` |
| `images/spatial_effects/arrhenius_spatial_stress_effects.svg` | `plot_arrhenius_with_spatial_coloring` |
| `images/comparison/all_techniques_comparison.svg` | `plot_all_techniques_comparison` |
| `images/manual_data/manual_delta_t_extraction.svg` | `plot_manual_delta_t_extraction` |

## Figure strings detected in manuscript DOCX

### Main manuscript

**Main-style:** Fig. 1, Fig. 1., Fig. 2, Fig. 3, Fig. 3., Fig. 4, Fig. 4., Fig. 5, Fig. 6, Fig. 6., Fig. 7, Fig. 7., Figure 1, Figure 1., Figure 2., Figure 3


**Supplementary-style:** Supplementary Figure 1, Supplementary Figure 1., Supplementary Figure 2., Supplementary Figure 3, Supplementary Table 1., Supplementary Table 2., Supplementary Table 3., Supplementary Table 4.Blue, Supplementary Table 5.


### Supplementary Information

**Main-style:** Figure 1, Figure 2, Figure 3


**Supplementary-style:** Supplementary Figure 1, Supplementary Figure 2, Supplementary Figure 3, Supplementary Table 1, Supplementary Table 2, Supplementary Table 3, Supplementary Table 4, Supplementary Table 5


## Source data bundle

After `python -m src.main run`: `results/Source_Data.xlsx`, `results/source_data/all_delta_t_strain_full.npz`,
and per-step tables under `results/` (see `docs/data_provenance.md`).
