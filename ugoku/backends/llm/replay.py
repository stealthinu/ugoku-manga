"""Replay provider: answers from recorded JSON, for CI and tests. No network, no CLI.

A recording is a directory of `<tag>.json` files (":" in a tag becomes "_" in the file name), or one `<tag>.<n>.json` per repeated call with the same tag.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from .base import LLMError, Usage


class ReplayProvider:
    name = "replay"
    capabilities = dict(vision=True, strict_schema=True, tools=False)

    def __init__(self, recording: Path | str, model: str = "replay", **_):
        self.dir = Path(recording)
        self.model = model
        self.usage = Usage()
        self._n: dict[str, int] = {}
        self._lock = threading.Lock()

    def cache_id(self) -> str:
        return "replay"

    def complete(self, prompt, *, system="", images=None, schema=None, tag=""):
        with self._lock:
            n = self._n.get(tag, 0)
            self._n[tag] = n + 1
        stem = tag.replace(":", "_")
        for cand in (self.dir / f"{stem}.{n}.json", self.dir / f"{stem}.json"):
            if cand.exists():
                self.usage.add(tag, hit=True)
                return json.loads(cand.read_text(encoding="utf-8"))
        raise LLMError(f"replay: no recording for tag {tag!r} (call {n}) in {self.dir}")
