"""Gemini generateContent provider (needs GEMINI_API_KEY)."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .base import LLMError, LoginError, Usage, parse_json_text

MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class GeminiProvider:
    name = "gemini"
    capabilities = dict(vision=True, strict_schema=True, tools=False)

    def __init__(self, model: str = "gemini-2.5-pro", api_key: str | None = None, base_url: str = "https://generativelanguage.googleapis.com/v1beta", **_):
        self.model = model
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self.usage = Usage()

    def cache_id(self) -> str:
        return f"gemini:{self.model}"

    def complete(self, prompt, *, system="", images=None, schema=None, tag=""):
        key = self._key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise LoginError("GEMINI_API_KEY is not set")
        parts = [dict(inline_data=dict(mime_type=MEDIA.get(Path(p).suffix.lower(), "image/png"), data=base64.b64encode(Path(p).read_bytes()).decode())) for p in images or []]
        parts.append(dict(text=prompt))
        gc: dict = dict(response_mime_type="application/json")
        if schema:
            gc["response_json_schema"] = schema
        body = dict(system_instruction=dict(parts=[dict(text=system)]), contents=[dict(role="user", parts=parts)], generationConfig=gc)
        req = urllib.request.Request(f"{self.base_url}/models/{self.model}:generateContent", json.dumps(body).encode(), {"x-goog-api-key": key, "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                res = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise LoginError(f"gemini API rejected the key ({e.code})") from None
            self.usage.add(tag, fail=True)
            raise LLMError(f"gemini API error {e.code}") from None
        self.usage.add(tag)
        return parse_json_text("".join(p.get("text", "") for p in res["candidates"][0]["content"]["parts"]))
