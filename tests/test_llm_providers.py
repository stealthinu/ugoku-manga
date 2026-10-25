"""Provider tests that need no network and no CLI: env hygiene, login preflight, cache."""
import json
import subprocess

import pytest

from ugoku.backends.llm import CachedProvider, LoginError, make_provider
from ugoku.backends.llm import claude_cli as cc


def test_child_env_strips_api_credentials(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "y")
    monkeypatch.setenv("KEEP_ME", "1")
    env = cc.child_env()
    assert "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env and env["KEEP_ME"] == "1"


class FakeRun:
    def __init__(self, status):
        self.status, self.calls = status, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if cmd[1] == "auth":
            return subprocess.CompletedProcess(cmd, 0, json.dumps(self.status), "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"is_error": False, "structured_output": {"ok": 1}, "result": ""}), "")


def test_preflight_requires_subscription_login(monkeypatch):
    monkeypatch.setattr(cc.shutil, "which", lambda b: "/bin/claude")
    monkeypatch.setattr(cc.subprocess, "run", FakeRun({"loggedIn": True, "authMethod": "api_key"}))
    with pytest.raises(LoginError):
        make_provider("claude_cli").complete("hi", schema={"type": "object"})


def test_cli_call_shape_and_cache(monkeypatch, tmp_path):
    fake = FakeRun({"loggedIn": True, "authMethod": "claude.ai"})
    monkeypatch.setattr(cc.shutil, "which", lambda b: "/bin/claude")
    monkeypatch.setattr(cc.subprocess, "run", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-not-printed")
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    prov = CachedProvider(make_provider("claude_cli", model="m"), tmp_path / "cache")
    for _ in range(2):
        assert prov.complete("q", images=[img], schema={"type": "object"}, tag="t") == {"ok": 1}
    runs = [c for c in fake.calls if c[0][1] != "auth"]
    assert len(runs) == 1 and prov.usage.cache_hits == 1  # second call came from the cache
    cmd, kw = runs[0]
    assert "--json-schema" in cmd and "Read" in cmd and "--model" in cmd
    assert "ANTHROPIC_API_KEY" not in kw["env"]
    assert all("secret-not-printed" not in part for part in cmd)
