"""LiteLLM client + fallback (plan sections 2, 11).

One interface over Gemini (primary) and Groq (fallback) via LiteLLM so models
can be swapped and a free-tier 429 from Gemini automatically falls back to Groq.

Models are configurable via env (sensible free-tier defaults):

- ``GAFFER_PRIMARY_MODEL``  default ``gemini/gemini-2.0-flash``
- ``GAFFER_FALLBACK_MODEL`` default ``groq/llama-3.3-70b-versatile``

Requires ``GEMINI_API_KEY`` (and optionally ``GROQ_API_KEY``) in the
environment; ``load_env()`` loads them from the repo-root ``.env`` if present.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import litellm

logger = logging.getLogger(__name__)

# Keep LiteLLM quiet: it logs every call at INFO and dumps full provider
# tracebacks when a model in the fallback chain errors. We handle the
# fallback ourselves and log succinctly.
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

# repo root: backend/app/llm.py -> backend/ -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

_DEFAULT_PRIMARY = "gemini/gemini-2.0-flash"
_DEFAULT_FALLBACK = "groq/llama-3.3-70b-versatile"

_env_loaded = False


def load_env(dotenv_path: Path | None = None) -> None:
    """Load ``KEY=value`` pairs from the repo-root ``.env`` into ``os.environ``.

    Minimal parser (no extra dependency): existing environment variables win, so
    a real shell export is never clobbered. Idempotent.
    """
    global _env_loaded
    if _env_loaded:
        return
    path = dotenv_path or (_REPO_ROOT / ".env")
    if path.exists():
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    _env_loaded = True


def primary_model() -> str:
    return os.getenv("GAFFER_PRIMARY_MODEL", _DEFAULT_PRIMARY)


def fallback_model() -> str:
    return os.getenv("GAFFER_FALLBACK_MODEL", _DEFAULT_FALLBACK)


def _model_chain(model: str) -> list[str]:
    """Ordered models to try: the chosen model, then Groq if its key exists."""
    chain = [model]
    fb = fallback_model()
    if fb and fb != model and os.getenv("GROQ_API_KEY"):
        chain.append(fb)
    return chain


def chat(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    temperature: float = 0.2,
    max_tokens: int | None = None,
) -> Any:
    """Single chat completion with automatic Gemini->Groq fallback.

    Returns the raw LiteLLM message object (``response.choices[0].message``),
    which exposes ``.content`` and ``.tool_calls``. Raises if every model in the
    chain fails.
    """
    load_env()
    model = model or primary_model()

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens

    # We drive the fallback chain ourselves (rather than LiteLLM's built-in
    # ``fallbacks=``) so a 429 from Gemini is a one-line log, not a stack dump.
    chain = _model_chain(model)
    last_exc: Exception | None = None
    for i, candidate in enumerate(chain):
        kwargs["model"] = candidate
        try:
            response = litellm.completion(**kwargs)
            return response.choices[0].message
        except Exception as exc:  # try the next model in the chain
            last_exc = exc
            nxt = chain[i + 1] if i + 1 < len(chain) else None
            if nxt:
                logger.warning(
                    "Model %s failed (%s); falling back to %s",
                    candidate, type(exc).__name__, nxt,
                )
            else:
                logger.error("All models failed; last was %s (%s)", candidate, type(exc).__name__)
    raise last_exc  # type: ignore[misc]
