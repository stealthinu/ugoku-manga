# Round R05a (sample galleries, full GPU run, Opus judge)

Three original sample works, comfy_h3 video through the external runner (3090). 18 animated panels (static panels excluded, as in v5). No human or agent edits. Scores use the ported v5 `score5` formula; the judge and semantics calls are Opus 5.5 through the claude CLI (one at a time, cached).

| measure | R05a (samples) | v5 reference | bar met |
|---|---|---|---|
| score5 average | 2.89 | 3.30 | NO |
| panels >= 4 | 4 / 18 (22%) | 30 / 80 (37.5%) | NO |
| panels <= 2 | 5 / 18 (28%) | not recorded | - |
| qa_text flag rate | 1 / 18 (5.6%) | - | yes |
| LLM judge overall (1-5) | 2.83 | - | - |

Judge items (mean): matches_action 2.78, physically_plausible 3.22, consistent_drawing 3.28, no_invented_text 4.89, stable_background 3.56.

Direction semantics (Opus looking at 8 frames of each clip):
- reverse motion: 0 clips; added text or SFX: 0 clips
- direction not as directed: 3 (koma p01-p8, koma p01-p1, koma p03-p2)
- no visible motion: 7 clips (low-motion `fl` clips and some `f` clips)

Reading:
- Panel selection, bubble/SFX handling and text preservation are fine (no invented text 4.89, one qa_text flag, none of the leftover-text problems seen earlier in the shonen log).
- The weakness is the video model output: little motion in about 40% of the clips, and two running scenes (shonen p01-p5, p04-p4) score 2 because of large flicker (46.8 and 29.6) from the model redrawing the figure.
- v5 reached 3.30 with hand-curated regeneration of weak clips; this run is a single automatic pass. The sample art is also new (Qwen-Image panels), so the numbers are not like-for-like with the private set.
- Per-clip numbers and job ids are in the (untracked) `~/work/ugoku-eval-out/samples-R05a.json`.

Rounds used for samples: 1 of 5. No reseed round was run (see STATUS open decisions).
