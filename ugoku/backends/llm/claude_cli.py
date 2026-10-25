"""Provider that shells out to the local `claude` CLI, using the user's Claude subscription login.

Used for development and evaluation so that no pay-per-use API key is involved:
- API credentials are removed from the child environment (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN and cloud-provider switches).
- A preflight check requires `claude auth status` to report the claude.ai login; otherwise `LoginError` is raised.
  Callers must stop on `LoginError` and never fall back to another provider.
- Images are passed as file paths; the model opens them with the CLI's Read tool.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .base import LLMError, LoginError, Usage, parse_json_text

STRIP_ENV = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")
LOGIN_HINTS = ("not logged in", "please run /login", "invalid api key", "authentication", "oauth", "credentials")


def child_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in STRIP_ENV}
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


class ClaudeCLIProvider:
    name = "claude_cli"
    capabilities = dict(vision=True, strict_schema=True, tools=False)

    def __init__(self, model: str = "claude-opus-5-5", binary: str = "claude", timeout: int = 900, retries: int = 2, max_calls: int | None = None, **_):
        self.model = model
        self.binary = binary
        self.timeout = timeout
        self.retries = retries
        self.max_calls = max_calls
        self.usage = Usage()
        self._checked = False
        self._lock = threading.Lock()

    def cache_id(self) -> str:
        return f"claude_cli:{self.model}"

    def preflight(self) -> None:
        with self._lock:
            if self._checked:
                return
            if not shutil.which(self.binary):
                raise LoginError(f"`{self.binary}` not found on PATH")
            r = subprocess.run([self.binary, "auth", "status"], capture_output=True, text=True, env=child_env(), timeout=60, stdin=subprocess.DEVNULL)
            try:
                st = json.loads(r.stdout)
            except json.JSONDecodeError:
                raise LoginError("`claude auth status` gave no JSON; run `claude` once and log in") from None
            if not st.get("loggedIn") or st.get("authMethod") != "claude.ai":
                raise LoginError(f"claude CLI is not logged in with a subscription (authMethod={st.get('authMethod')!r})")
            self._checked = True

    def complete(self, prompt, *, system="", images=None, schema=None, tag=""):
        self.preflight()
        images = [Path(p).resolve() for p in (images or [])]
        if self.max_calls is not None and self.usage.calls >= self.max_calls:
            raise LLMError(f"call budget exhausted ({self.max_calls})")
        dirs = sorted({str(p.parent) for p in images})
        if images:
            prompt += "\n\nImage files (open each with the Read tool before answering):\n" + "\n".join(f"- {p}" for p in images)
        cmd = [self.binary, "-p", "--model", self.model, "--output-format", "json", "--no-session-persistence", "--setting-sources", "", "--system-prompt", system or "You answer with JSON only."]
        cmd += ["--tools", "Read", "--allowedTools", "Read"] if images else ["--tools", ""]
        for d in dirs:
            cmd += ["--add-dir", d]
        if schema:
            cmd += ["--json-schema", json.dumps(schema)]
        last = "unknown"
        for attempt in range(self.retries + 1):
            try:
                r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, env=child_env(), timeout=self.timeout, cwd=dirs[0] if dirs else None)
            except subprocess.TimeoutExpired:
                last = "timeout"
                self.usage.add(tag, fail=True)
                continue
            raw = r.stdout.strip()
            try:
                res = json.loads(raw)
            except json.JSONDecodeError:
                last = f"non-JSON output (rc={r.returncode}): {r.stderr.strip()[:200]}"
                if any(h in (r.stderr + raw).lower() for h in LOGIN_HINTS):
                    raise LoginError(last) from None
                self.usage.add(tag, fail=True)
                time.sleep(3 * (attempt + 1))
                continue
            if res.get("is_error"):
                msg = str(res.get("result", ""))[:200]
                if any(h in msg.lower() for h in LOGIN_HINTS) or res.get("api_error_status") in (401, 403):
                    raise LoginError(f"claude CLI error: {msg}")
                last = f"cli error: {msg}"
                self.usage.add(tag, fail=True)
                time.sleep(10 * (attempt + 1))
                continue
            self.usage.add(tag)
            out = res.get("structured_output")
            if isinstance(out, dict):
                return out
            try:
                return parse_json_text(str(res.get("result", "")))
            except LLMError as e:
                last = str(e)
                continue
        raise LLMError(f"claude_cli failed for {tag!r}: {last}")
