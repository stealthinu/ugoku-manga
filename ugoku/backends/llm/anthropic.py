"""Anthropic Messages API provider (for end users; needs ANTHROPIC_API_KEY). Plain HTTPS, no SDK dependency."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .base import LLMError, LoginError, Usage, parse_json_text

MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class AnthropicProvider:
    name = "anthropic"
    capabilities = dict(vision=True, strict_schema=True, tools=False)

    def __init__(self, model: str = "claude-opus-5-5", api_key: str | None = None, base_url: str = "https://api.anthropic.com", max_tokens: int = 16000, **_):
        self.model = model
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.usage = Usage()

    def cache_id(self) -> str:
        return f"anthropic:{self.model}"

    def complete(self, prompt, *, system="", images=None, schema=None, tag=""):
        key = self._key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LoginError("ANTHROPIC_API_KEY is not set")
        content = []
        for p in images or []:
            content.append(dict(type="image", source=dict(type="base64", media_type=MEDIA.get(Path(p).suffix.lower(), "image/png"), data=base64.b64encode(Path(p).read_bytes()).decode())))
        content.append(dict(type="text", text=prompt))
        body = dict(model=self.model, max_tokens=self.max_tokens, system=system, messages=[dict(role="user", content=content)])
        if schema:
            body["output_config"] = dict(format=dict(type="json_schema", schema=schema))
        req = urllib.request.Request(f"{self.base_url}/v1/messages", json.dumps(body).encode(), {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                res = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise LoginError(f"anthropic API rejected the key ({e.code})") from None
            self.usage.add(tag, fail=True)
            raise LLMError(f"anthropic API error {e.code}") from None
        self.usage.add(tag)
        return parse_json_text("".join(b.get("text", "") for b in res.get("content", [])))
