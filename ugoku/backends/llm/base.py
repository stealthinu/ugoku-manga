"""Provider interface shared by all vision-LLM backends."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class LLMError(RuntimeError):
    """A call failed (transient or malformed output)."""


class LoginError(LLMError):
    """The provider's credentials are missing or invalid. Callers must stop instead of falling back to another provider."""


@dataclass
class Usage:
    """Call counters, kept per provider instance (thread-safe)."""

    calls: int = 0
    cache_hits: int = 0
    failures: int = 0
    by_tag: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, tag: str = "", hit: bool = False, fail: bool = False) -> None:
        with self._lock:
            if hit:
                self.cache_hits += 1
            elif fail:
                self.failures += 1
            else:
                self.calls += 1
            if tag:
                self.by_tag[tag] = self.by_tag.get(tag, 0) + 1


class Provider(Protocol):
    name: str
    model: str
    capabilities: dict  # vision / strict_schema / tools
    usage: Usage

    def cache_id(self) -> str: ...

    def complete(self, prompt: str, *, system: str = "", images: list[Path] | None = None, schema: dict | None = None, tag: str = "") -> dict:
        """Return the JSON object answering `prompt` about `images`, conforming to `schema`."""
        ...


def parse_json_text(text: str) -> dict:
    """Fallback for providers without strict schema support: the first JSON object found in free text."""
    import json

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        if a < 0 or b <= a:
            raise LLMError("no JSON object in model output") from None
        try:
            return json.loads(text[a : b + 1])
        except json.JSONDecodeError as e:
            raise LLMError(f"invalid JSON in model output: {e}") from None
