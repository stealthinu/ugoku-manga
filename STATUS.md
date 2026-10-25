# STATUS  (リリース準備 完了 2026-10-24、未公開・未 push)

## オーナー向け要約（日本語）— リリース準備 0.1.0
- 何をしたか: 前回の中断（spend limit）で残っていた未コミット変更を確認し、問題が無かったのでそのまま採用（0.1.0 へのバージョン更新、Python 3.11 以上へ変更（tomllib 使用のため）、ruff 修正、hygiene.yml を ci.yml に統合、deny-grep の非公開語リストをリポジトリ外 ~/.config/ugoku/deny-patterns.txt へ移動、デモメディア作成スクリプトと配布 zip 作成スクリプト）。今回追加したもの: README.md（英語）と README.ja.md（日本語。デモ GIF 3本と Web UI スクリーンショット2枚、インストール、クイックスタート、Web UI、パイプライン、モデル/GPU 要件、制限事項）、CONTRIBUTING.md、CHANGELOG.md（0.1.0）、samples/manifest.json（3作品とも CC0-1.0、同期テスト付き）、docs/media/README.md（メディアのライセンス）。修正: デモスクリプト内の IP:port 表記（deny-grep で検出）を localhost に変更。
- コミット: 8a15c4a（リリース準備）、b338ca4（ドキュメント）、およびこの STATUS 更新。push、リモート作成、公開はしていません。GPU ジョブも実行していません。
- チェック結果: ruff クリーン。pytest は Python 3.13 で 42 passed（検出モデルありでゴールデン含む）、Python 3.11 で 43 passed（新しいマニフェストテストを含む）。Web UI e2e（Playwright）2 passed。deny-grep: 作業ツリーと履歴とも 0 hits（汎用6パターンのみの場合も、非公開9パターン込みの場合も）。gitleaks 8.30.1: 作業ツリー・全履歴（12+コミット）とも no leaks。check_repo: ok。ci.yml は YAML として妥当（GitHub 上ではまだ一度も実行されていない）。docs/media 合計 4.3 MB（最大 1.8 MB）。
- 履歴監査: author/committer は全コミット `ugoku-manga <ugoku@example.invalid>`（タイムゾーン +0900 は残る）。最大の blob はサンプルページの 693 KB で、大きなファイルは無し。参照は master のみ、削除済みファイルも無し。Jump+ の画像、私的パス、メールアドレス、VPN 上のホスト名、秘密情報は履歴に無い。**ただし 1 点問題あり**: 3c300da〜64d7566 の `scripts/deny_grep.sh` には、非公開語（オーナーの名前とハンドル、参照作品のスラッグ、社内ツール名、ホスト名の一部）がそのまま書かれている（deny-grep の履歴チェックはこのファイル自身を対象外にしているため検出されない）。現在のツリーでは削除済み。
- 公開前に判断が必要なこと:
  1. 履歴の扱い（書き換えはしていません）。案A（推奨）: 公開用に孤立ブランチを作り、最終ツリーを1コミットにまとめる（`git checkout --orphan public && git add -A && git commit`）。案B: `git filter-repo --replace-text` で deny_grep.sh の古い版から非公開語を消す。どちらも公開前ならリスクは小さい。
  2. 公開時の author 名とメールアドレス（今は placeholder の example.invalid。GitHub の noreply アドレスなどに変えるか）。
  3. STATUS.md と eval/rounds/*.md を公開に含めるか。GPU ジョブ ID、~/work 以下のパス、claude CLI サブスクリプションの運用メモ、非公開評価データ（24ページ）への言及が入っている（deny-grep は通過）。公開しないなら、公開前に追跡を外すか中身を整理する。
  4. デモ GIF（docs/media）と配布 zip（~/work/ugoku-oss-out/release-assets、3ファイル計 51 MB、未アップロード）には MiniMax H3 の生成物が含まれる。H3 の規約で再配布してよいか確認が必要。問題があるなら dummy バックエンドで作り直す。
  5. 品質基準は未達（score5 3.00、比較対象 3.30）。README の制限事項に明記したうえで alpha として出すか、改善を続けるか。
  6. CHANGELOG の日付（今は "unreleased"）とタグは公開時に決める。CI の任意シークレット `UGOKU_DENY_PATTERNS`（非公開語リスト）を GitHub に登録するか。

# STATUS  (R05b 完了 2026-10-24)

## オーナー向け要約（日本語）
- 何をしたか: R05a で点数の低かった6クリップ（koma p01-p1/p01-p2/p01-p8, shojo p01-p2, shonen p01-p5/p04-p4）をシードだけ変えて1回再生成（3090、GPU キューのジョブ g-20261024-012235-nifm、約1.2 GPU時間）。新旧を score5 で比較し、厳密に高いものだけ採用（qa_text が false→true になるものは不採用）。その後18クリップ全体を Opus 5.5（claude CLI サブスク）で再採点。
- 採用数: 2/6（koma p01-p1: 1→2、koma p01-p2: 2→3）。残り4件は同点のため元のまま（shonen p01-p5 は再生成版で qa_text も true になったため不採用）。
- 平均点: score5 2.89 → 3.00（v5 は 3.30）。4点以上 4/18（22%、v5 37.5%）、2点以下 5→4。qa_text フラグ 1/18。LLM 審査平均 2.83→2.72（ノイズの範囲）。品質基準は未達。
- ギャラリーURL（変更なし）: ~/work/ugoku-oss-out/gallery-samples/{koma-morning,shojo-afterschool,shonen-rooftop}/index.html（:8772 のパスも同じ）
- 残作業/判断: 追加のリシード（R05c 以降、1回で約3分の1しか改善しない）を続けるか、現状の数値で受け入れるか。ライセンス、フル24ページ GPU 実行などは下の英語版の Open decisions のとおり。詳細は eval/rounds/R05b.md。

# STATUS  (updated: 2026-10-24, P0-P5 done, P6 R05a + R05b (reseed) measured, P7/P8 done except as listed)

## R05b (done)
Reseeded 6 weak sample clips, adopted 2 (koma p01-p1 1->2, p01-p2 2->3); score5 avg 2.89 -> 3.00 (v5 3.30), >=4 4/18, <=2 4/18, qa flag 1/18, judge 2.72. Quality bar still NOT met. GPU job g-20261024-012235-nifm (~1.2 GPU-h). Details: eval/rounds/R05b.md.

## Owner summary
- Done: full pipeline (page image -> panels -> units -> LLM direction -> video -> player gallery) with no manual edits, WebUI (FastAPI, queue, SSE, Range, editing, exports; Playwright e2e passes: 2 tests with the dummy backend, includes Range 206), README, NOTICE, docs/DESIGN.md, docker files. Fresh-clone dummy run of all 3 samples: 517 s (< 10 min).
- Sample galleries (comfy_h3 video, GPU jobs g-20261023-111645-wedu, g-20261023-111702-j50a, g-20261023-111710-khsc, all rc=0): ~/work/ugoku-oss-out/gallery-samples/{koma-morning,shojo-afterschool,shonen-rooftop}/index.html
- Quality (R05a, 18 animated panels): score5 avg 2.89 (v5 3.30), >=4: 4/18 = 22% (v5 30/80 = 37.5%), <=2: 5/18, qa_text flag 1/18, LLM judge 2.83/5, reverse-motion 0, invented text/SFX 0, direction wrong 3, no visible motion 7. Quality bar NOT met; details eval/rounds/R05-samples.md.
- Open decisions: (1) run reseed/regeneration rounds for the weak clips (R05b..; ~6 clips, a few GPU hours plus ~90 min of judging per round) or accept the single-pass numbers; (2) repo licence (Apache-2.0 proposed); (3) Opus vs Sonnet direction default; (4) full 24-page GPU run (~19 GPU-h); (5) keep PLAN.md local or publish a sanitized copy.
- Not re-run this session: unit tests / ruff (pytest and ruff are not installed in the current python; last recorded 16 pass / clean). deny-grep 0 hits, gitleaks no leaks (re-checked).

Phase: P5 video backends and runner DONE. Direction model default is now Opus 5.5 (R04). P7 web UI implemented (not yet persistent). P2 samples: shojo work rendered, shonen and 4-koma art being regenerated. P6 GPU round G1 running.
Next: finish P2 (art regeneration, render, directions, truth, manifest), G1 score, P7 persistent start and e2e run, P8.
Blockers: none. LLM: claude CLI subscription only; no limit errors so far.
GPU used: about 2.5 h so far (2 video panels 0.5 h, sample art 1 h, art regeneration ~0.7 h, G1 about 2.8 h in progress) of the 15 h budget.

## Gates (round R03 = 3rd and last internal iteration; 24 private pages, Sonnet 5.5; numbers in eval/rounds/R0*.md)
| gate | value | target | ok |
|---|---|---|---|
| panel mean IoU (matched) | 0.908 | >= 0.85 | yes |
| panel recall at IoU 0.5 | 0.947 (89/94) | >= 0.95 | NO (0.003 short) |
| panel precision | 0.967 | >= 0.90 | yes |
| bubble recall (overlap based) / precision | 0.988 / 0.964 | >= 0.90 | yes |
| SFX+manpu recall / precision | 0.836 / 0.758 | >= 0.75 | yes |
| bubble order, Kendall tau (mean) | 0.982 | >= 0.90 | yes |
| bubble order, page exact | 0.762 (16/21) | >= 80% | NO |
| panel sequence page exact | 0.917 | >= 80% | yes |
| h3 selection agreement / Cohen kappa | 0.954 / 0.793 | >= 80% | yes |
| direction valid without degrade | 24/24 pages | >= 95% | yes |
| score5 formula reproduces v5 scores (self-test) | 79/80 (the 1 miss is the manually capped clip) | reproduce | yes |
| tests / lint / deny-grep / gitleaks / repo policy | 16 pass / clean / 0 hits / no leaks / ok | all clean | yes |

Round history (recall / bubble page-exact / tau / h3 agreement): R1 0.926 / 0.67 / 0.964 / 0.953, R2 0.926 / 0.62 / 0.969 / 0.976, R3 0.947 / 0.76 / 0.982 / 0.954.
Classical panels alone (no LLM): IoU 0.919, recall 0.80, precision 0.91; the LLM correction (add/merge/split/drop with code-snapped edges) lifts recall to 0.93-0.95.
Notes on the two misses: the 5 unmatched panels are borderless or inset panels drawn by eye in the reference; the page-exact misses are in-panel micro-order that follows conversation flow in the reference, and 2 pages where the reference reads a bottom or top row left to right. Both are partly reference quirks; the metric is relative to a by-eye reference.
Baseline of the trivial "animate everything" classifier: 91% h3 share in the reference, so the 95% agreement is only 4 points above it; kappa (0.79) is the fairer number. Magnitude agreement is low (0.61), mode agreement 0.91.
Not measured yet (need GPU video): qa_text flag rate, score5 on new videos, LLM visual judge, GPU-subset gates.
score5 self-test detail: our metric port differs from the stored reference metrics by at most 0.03 in motion, 0.95 in flicker and 8 in changed area (video decoder or re-encoded clips); the scores still reproduce. The v5 mean is 3.30 (30/80 at 4 or above); our formula without the manual cap gives 3.325.

## Phases
- [x] P0 bootstrap (commit 3c300da): skeleton, config, model registry with licence allowlist, CLI, CI workflows, deny-grep, repo policy check, pre-commit hook
- [x] P1 core CPU port (commit b198413): detect/text, segment, inpaint, stage, compose, web/player, dummy video backend, `ugoku run --direction`, `eval/convert_ref` + `eval/parity`; evidence above
- [x] P2 samples (commit 044ffe9): 3 original works, 11 pages (shonen-rooftop 4, shojo-afterschool 4, koma-morning 3), 59 panels of Qwen-Image art (Apache-2.0) + code-drawn borders, tone, balloons, OFL lettering, SFX, manpu; truth.json + label masks; Opus directions (all pages valid, 0 degraded); samples/LICENSE (CC0-1.0, provenance). Golden check (classical detectors, no LLM): panel mean IoU 0.953 / 0.952 / 0.959, bubble and SFX recall 1.0; known gaps: borderless fade panels are not found by the classical detector (shojo panel recall 0.70) and the 4-koma panel order is exact on 1 of 3 pages, bubble order exact on 0.5-1.0 of pages. Art job g-20261022-205507-empo (59 images, 1 h) and regeneration g-20261022-223138-kl67 (39 images; the model drew empty caption boxes when asked for free space)
- [x] P3 eval harness, panels, order: `eval/{metrics,panels_eval,layout_eval,score5,round_report}`, `pipeline/{panels,order,units}.py`; panel and order gates in the table above (2 near-misses)
- [x] P4 LLM direction: providers (claude_cli, anthropic, openai_compat, gemini, replay, cache), prompts, schemas, validator, critic, retry/degrade, `ugoku direct`, replay CI test; evidence eval/rounds/R03.md. `claude_agent` provider not written (the CLI provider covers the Read-tool path)
- [x] P5 video backends and runner (commit 184d618): `comfy_h3` + `minimax_api` (code only, never called) + local and external_command runners; `--check` passed on the GPU host through the external runner (job g-20261022-201835-hm5v); 2 panels generated (job g-20261022-202058-m3gx): one is bit-identical to the reference clip (mean abs frame diff 0.00), the other has the same style and size (mean diff 9.4, different motion); the prompt and graph match the reference script (only the output prefix differs). The deployment's runner config lives outside the repo (~/.config/ugoku/config.toml)
- [~] P6 eval rounds: Opus vs Sonnet done (R04); sample-gallery round R05a measured (bar not met, eval/rounds/R05-samples.md); no reseed round yet
- [x] P7 WebUI: FastAPI + SQLite queue + SSE + Range files + editing + exports, 35 unit tests; Playwright e2e passes (2 tests, includes Range 206); server running on :8771
- [x] P8 release prep: README, NOTICE, docs/DESIGN.md, docker files, runner example; fresh-clone dummy check ok in 517 s

## Decisions
- 2026-10-22 (owner brief) dev/eval LLM calls only through the local claude CLI with the subscription login; HTTP providers exist for end users and are never called here.
- 2026-10-22 direction model: Opus 5.5 is the default (R04: panel recall 0.989 vs 0.947, bubble recall 1.0 vs 0.988, SFX+manpu precision 0.58 vs 0.76, order page-exact 0.76 for both); Sonnet 5.5 stays selectable as the cheaper option. Details: eval/rounds/R04-opus-vs-sonnet.md.
- 2026-10-23 LLM note: a concurrent run of three claude CLI processes hit 'Failed to refresh OAuth token: another Claude Code process is refreshing it' (login itself stayed valid: `claude auth status` loggedIn claude.ai). The affected runs stopped (no fallback); the remaining calls were re-run one process at a time from the cache. No usage/spend/session limit error has occurred.
- 2026-10-23 process note: one `pkill -f` (pattern-matched kill of my own debug server) was used by mistake against the rule to stop processes by PID only; it matched only that server. Not repeated.
- 2026-10-22 licence: Apache-2.0 (LICENSE added). PLAN.md stays local and untracked; docs/DESIGN.md is the sanitized public design.

## Open decisions for the owner
- repo licence (proposed Apache-2.0); direction model Opus vs Sonnet; full 24-page GPU run (~19 GPU-h)
- PLAN.md contains deny-list terms (private slugs, internal tool names, paths), so it is kept untracked on purpose. Publish a sanitized copy, or keep it local?

## Remaining issues
- Two gates narrowly missed (panel recall 0.947, bubble page-exact 0.76); no further internal iteration was spent (limit of 3 reached).
- The reference panel and order data was made by eye; gates are relative to it. Insets and borderless panels, and flow-based micro-order, cap the scores.
- Balloons that cross panels are assigned by text-pixel overlap plus the LLM hint, not by tail anchor.
- The plain-API tool loop (zoom, validate) is not implemented; the workflow uses fixed crops and a validate-repair loop. The plan's A/B comparison of the claude_agent provider is not done.
- Magnitude (medium/large) agreement with the reference is low (0.61); not a gate, but worth a prompt look in P6.
- Opus vs Sonnet for direction is not compared. The SFX+manpu precision (0.76) shows some added or mis-typed fx.
- Direction semantics (action quality, left/right correctness, reverse-walk) are only checked by the critic and rules, not against video; that is P6.
- The inpainting model has no public download: the local dynamic-shape export is a fresh export (opset 18) of the MIT checkpoint, not a patch of the public fixed-512 ONNX. The registry marks it `manual` and records the expected sha256. A reproducible export script (needs torch and the checkpoint) is not written.
- The text segmentation model is GPL-3.0 upstream; kept as an optional user download behind `detect/text.py`. Replacement not yet studied (plan item for P1/P3).
- `python -m http.server` has no Range support, so video seeking (`__at(t)`) fails behind it; the player works with a Range-capable server (checked with a small one in Chromium: 6 layers, 2 videos, seek OK). `ugoku serve` (P7) must support Range.
- CI has never run (no remote). `hygiene.yml` is folded into `ci.yml`; the gitleaks 8.30.1 binary checksum in it matches the upstream release.
- Player verification is a manual Chromium check, not an automated test (planned for P7 e2e).
- Direction validation is only a format check; the full validator and schema semantics arrive in P4. `ugoku run` supports only the `dummy` backend and rect-based unit matching; id-based assignment arrives with the LLM direction.
- The reference-only behaviours dropped on purpose: re-filling frames of old videos, manual per-page patches, work-specific direction edits.
- System `ffmpeg` with libx264 and libvpx-vp9 is required for encoding (not bundled).

## Log (append-only, newest first)
- 2026-10-22 P3+P4: panels.py (gutter-colour estimate, flood fill, hull-rectangularity filter, XY-cut with border-line cuts, sliver merge, snap), order.py (XY-cut with tolerance escalation, 4-koma, bands, assignment), units.py, eval harness (panels, layout, direction, score5 port, round report), LLM layer (claude CLI provider with env strip and login preflight, cache, replay, 3 HTTP providers), direction workflow A/B/C + order check, validator, timing, `ugoku direct`. R1-R3 on 24 pages: see Gates. Fixed on the way: panel order bug with slightly overlapping panel edges; order check redesigned from pair questions to proposal correction; inset panels allowed.
- 2026-10-22 P0+P1: skeleton and CPU core ported by rewrite; parity on 23 private pages: base diff mean 0.003 (max 0.075), 239/240 layers at IoU >= 0.98 (mean 0.9988), hide/flat masks identical; dummy end-to-end run and player check done; public bubble detector matches the local one.
- 2026-10-22 plan: PLAN.md written (job 20261022-185523-plan-b82e).
