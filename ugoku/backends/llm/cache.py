"""Response cache: re-running the same request costs nothing. Key = provider id + model + system + prompt + schema + image bytes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .base import Provider, Usage


def request_key(provider_id: str, prompt: str, system: str, images: list[Path], schema: dict | None) -> str:
    h = hashlib.sha256()
    for part in (provider_id, system, prompt, json.dumps(schema, sort_keys=True)):
        h.update(part.encode("utf-8"))
        h.update(b"\0")
    for p in images:
        h.update(hashlib.sha256(Path(p).read_bytes()).digest())
    return h.hexdigest()


class CachedProvider:
    """Wrap a provider with an on-disk JSON cache (one file per request)."""

    def __init__(self, inner: Provider, cache_dir: Path, readonly: bool = False):
        self.inner = inner
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.readonly = readonly
        self.name = inner.name
        self.model = inner.model
        self.capabilities = inner.capabilities
        self.usage = inner.usage if hasattr(inner, "usage") else Usage()

    def cache_id(self) -> str:
        return self.inner.cache_id()

    def key(self, prompt, system, images, schema) -> str:
        return request_key(self.inner.cache_id(), prompt, system, list(images or []), schema)

    def complete(self, prompt, *, system="", images=None, schema=None, tag=""):
        k = self.key(prompt, system, images or [], schema)
        f = self.dir / f"{k}.json"
        if f.exists():
            self.usage.add(tag, hit=True)
            return json.loads(f.read_text(encoding="utf-8"))["response"]
        out = self.inner.complete(prompt, system=system, images=images, schema=schema, tag=tag)
        if not self.readonly:
            tmp = f.with_suffix(".tmp")
            tmp.write_text(json.dumps(dict(tag=tag, provider=self.inner.cache_id(), response=out), ensure_ascii=False), encoding="utf-8")
            tmp.replace(f)
        return out
