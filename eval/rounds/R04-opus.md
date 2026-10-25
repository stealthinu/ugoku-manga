# Round R04 (Opus)

Prompt p3, model claude-opus-5-5 (86 uncached calls, 611 s). Same pages and code as R03 (Sonnet 5.5).

| gate | value | target | ok |
|---|---|---|---|
| panel mean IoU | 0.931 | >= 0.85 | yes |
| panel recall (IoU>=0.5) | 0.989 | >= 0.95 | yes |
| panel precision | 1.000 | >= 0.9 | yes |
| bubble recall | 1.000 | >= 0.9 | yes |
| SFX+manpu recall | 0.866 | >= 0.75 | yes |
| order tau (bubbles) | 0.983 | >= 0.9 | yes |
| order page exact | 0.762 | >= 0.8 | NO |
| panel sequence page exact | 0.917 | >= 0.8 | yes |
| h3 selection agreement | 0.956 | >= 0.8 | yes |
| schema valid without degrade (pages) | 1.000 | >= 0.95 | yes |

Other numbers:

```
{
 "bubble_precision": 0.953757225433526,
 "sfx_manpu_precision": 0.5777777777777777,
 "panel_tau_mean": 0.9583333333333334,
 "h3_kappa": 0.775585696670777,
 "h3_ours_share": 0.9010989010989011,
 "h3_ref_share": 0.8791208791208791,
 "mode_agree": 0.8860759493670886,
 "magnitude_agree": 0.6582278481012658,
 "schema_valid": 1.0,
 "pages_degraded": [],
 "pages_failed": [],
 "repairs": 2,
 "critic_rounds": 39
}
```
