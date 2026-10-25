# Contributing

Thanks for helping. Issues and pull requests are welcome in English or Japanese.

## Setup

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
ugoku models fetch ctd bubble                 # needed for the golden and e2e tests (they are skipped without it)
python -m playwright install chromium         # for the e2e tests
git config core.hooksPath .githooks           # pre-commit: deny-grep + repo policy check
```

## Before you open a pull request

```
ruff check .
pytest -q                                     # unit + golden tests, CPU only, no network, no API keys
pytest -q -m e2e tests/e2e                    # browser test of the web UI with the dummy video backend
bash scripts/deny_grep.sh && python scripts/check_repo.py
```

CI runs the same checks plus gitleaks on the full history (`.github/workflows/ci.yml`).

## Rules

- Tests must not call hosted LLM or video services. Use the `replay` provider with recorded responses (`tests/fixtures/replay/`) or the `dummy` video backend.
- Media files (images, video, model weights) go only under `samples/`, `tests/fixtures/` or `docs/media/`, must be under 5 MB, and must be listed in
  `samples/MANIFEST.sha256` (`python -m tools.sample_gen.manifest` rewrites it).
- Never commit pages, scans or clips from published manga or any work you do not hold the rights to, not even as a test fixture.
  New sample material must be original and dedicated under CC0-1.0, with its provenance documented in `samples/LICENSE`.
- No model weights in the repository. A new downloadable model needs an entry in `ugoku/models.py` with a licence on the allowlist (Apache-2.0, MIT, BSD, OFL),
  or it must be an optional user download with a row in `NOTICE.md`.
- No absolute paths, host names, personal data or secrets in code, docs or commit messages. Machine-specific settings belong in `~/.config/ugoku/config.toml`.
  `scripts/deny_grep.sh` checks generic patterns; you can add your own private patterns in `~/.config/ugoku/deny-patterns.txt` (one regex per line).
- Keep the principle "the model judges, code measures": LLM output picks among candidates and writes text; coordinates, order and timing come from code.
- If a change affects detection, order or direction quality, run the golden tests and say in the PR what changed.

## Licence

By contributing you agree that your contribution is licensed under Apache-2.0 (code) or CC0-1.0 (sample material), as in `LICENSE` and `samples/LICENSE`.
