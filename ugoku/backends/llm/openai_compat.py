"""OpenAI-compatible chat completions provider (OpenAI, vLLM, Ollama, ...). Needs OPENAI_API_KEY unless the server needs none."""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .base import LLMError, LoginError, Usage, parse_json_text

MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


class OpenAICompatProvider:
    name = "openai_compat"
    capabilities = dict(vision=True, strict_schema=True, tools=False)

    def __init__(self, model: str = "gpt-5", base_url: str = "https://api.openai.com/v1", api_key: str | None = None, strict: bool = True, **_):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._key = api_key
        self.strict = strict
        self.usage = Usage()
        self.capabilities = dict(vision=True, strict_schema=strict, tools=False)

    def cache_id(self) -> str:
        return f"openai_compat:{self.base_url}:{self.model}"

    def complete(self, prompt, *, system="", images=None, schema=None, tag=""):
        key = self._key or os.environ.get("OPENAI_API_KEY", "")
        parts = [dict(type="text", text=prompt)]
        for p in images or []:
            b = base64.b64encode(Path(p).read_bytes()).decode()
            parts.append(dict(type="image_url", image_url=dict(url=f"data:{MEDIA.get(Path(p).suffix.lower(), 'image/png')};base64,{b}")))
        body = dict(model=self.model, messages=[dict(role="system", content=system), dict(role="user", content=parts)])
        if schema and self.strict:
            body["response_format"] = dict(type="json_schema", json_schema=dict(name="out", schema=schema, strict=True))
        elif schema:  # no strict support: ask for JSON in text and validate afterwards
            body["messages"][0]["content"] += "\nAnswer with one JSON object matching this schema:\n" + json.dumps(schema)
        req = urllib.request.Request(f"{self.base_url}/chat/completions", json.dumps(body).encode(), {"Authorization": f"Bearer {key}", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                res = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise LoginError(f"server rejected the key ({e.code})") from None
            self.usage.add(tag, fail=True)
            raise LLMError(f"chat completions error {e.code}") from None
        self.usage.add(tag)
        return parse_json_text(res["choices"][0]["message"]["content"])
