"""Vision-LLM providers behind one interface: `complete(prompt, system=, images=, schema=) -> dict`."""
from __future__ import annotations

from .base import LLMError, LoginError, Provider, Usage
from .cache import CachedProvider

__all__ = ["LLMError", "LoginError", "Provider", "Usage", "CachedProvider", "make_provider"]


def make_provider(name: str, **kw) -> Provider:
    """Build a provider by name. `claude_cli` (subscription login) is the development/eval default; the HTTP providers are for end users."""
    if name == "claude_cli":
        from .claude_cli import ClaudeCLIProvider

        return ClaudeCLIProvider(**kw)
    if name == "anthropic":
        from .anthropic import AnthropicProvider

        return AnthropicProvider(**kw)
    if name == "openai_compat":
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(**kw)
    if name == "gemini":
        from .gemini import GeminiProvider

        return GeminiProvider(**kw)
    if name == "replay":
        from .replay import ReplayProvider

        return ReplayProvider(**kw)
    raise ValueError(f"unknown LLM provider: {name}")
