# Direction model: Opus 5.5 vs Sonnet 5.5 (same prompts p3, same 24 pages)

| metric | Sonnet 5.5 (R03) | Opus 5.5 (R04) |
|---|---|---|
| panel_mean_iou | 0.908 | 0.931 |
| panel_recall | 0.947 | 0.989 |
| panel_precision | 0.967 | 1.000 |
| bubble_recall | 0.988 | 1.000 |
| bubble_precision | 0.964 | 0.954 |
| sfx_manpu_recall | 0.836 | 0.866 |
| sfx_manpu_precision | 0.758 | 0.578 |
| unit_tau_mean | 0.982 | 0.983 |
| unit_page_exact | 0.762 | 0.762 |
| panel_page_exact | 0.917 | 0.917 |
| h3_agree | 0.954 | 0.956 |
| h3_kappa | 0.793 | 0.776 |
| mode_agree | 0.905 | 0.886 |
| magnitude_agree | 0.608 | 0.658 |
| schema_valid_no_degrade | 1.000 | 1.000 |

Calls: Sonnet 106 uncached, Opus 86 uncached; wall time 603 s vs 611 s (3 workers).

Reading: Opus fixes the panel recall miss (0.947 -> 0.989) and raises bubble recall to 1.0; it adds more SFX/manpu candidates (recall 0.84 -> 0.87, precision 0.76 -> 0.58), and the order page-exact is unchanged (0.76). Decision: Opus is the default direction model; Sonnet stays selectable as the cheaper option.
