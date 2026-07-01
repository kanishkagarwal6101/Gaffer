"""LiteLLM client + fallback (plan sections 2, 11).

One interface over Gemini (primary) and Groq (fallback) via LiteLLM so models
can be swapped and a free-tier 429 from Gemini automatically falls back to Groq.

Main chain (planning calls, requires tool-call support):
- ``GAFFER_PRIMARY_MODEL``  default ``gemini/gemini-2.0-flash``
- ``GAFFER_FALLBACK_MODEL`` default ``groq/llama-3.3-70b-versatile``

Verify chain (M5 verify/rewrite — NO tool calls; Groq is primary):
- ``GAFFER_VERIFY_MODEL``         default ``groq/llama-3.3-70b-versatile``
- ``GAFFER_VERIFY_FALLBACK_MODEL`` default ``gemini/gemini-2.0-flash-lite``

Why Groq-primary for verify: verify and rewrite are plain text/JSON calls with
no tool schemas. Groq handles those cleanly and fast, and reserving main Gemini
Flash quota for the planning hop keeps the demo safe on free-tier limits
(plan section 11).

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

# --- main planning chain --------------------------------------------------
_DEFAULT_PRIMARY = "gemini/gemini-2.0-flash"
_DEFAULT_FALLBACK = "groq/llama-3.3-70b-versatile"

# --- verify/rewrite chain (reversed: Groq primary, Gemini-lite fallback) --
# Groq handles non-tool-calling structured text reliably and doesn't draw on
# the main Gemini Flash quota that the planning hop needs.
_DEFAULT_VERIFY_PRIMARY = "groq/llama-3.3-70b-versatile"
_DEFAULT_VERIFY_FALLBACK = "gemini/gemini-2.0-flash-lite"

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


def verify_chain() -> list[str]:
    """Ordered model chain for the M5 verify/rewrite hop.

    Groq is primary (no tool calls needed → handles plain JSON/text cleanly),
    Gemini Flash-Lite is the fallback. Requires calling ``load_env()`` first.
    """
    load_env()
    chain: list[str] = []
    primary = os.getenv("GAFFER_VERIFY_MODEL", _DEFAULT_VERIFY_PRIMARY)
    fallback = os.getenv("GAFFER_VERIFY_FALLBACK_MODEL", _DEFAULT_VERIFY_FALLBACK)
    # Add Groq primary only when the key exists (it's optional).
    if "groq" not in primary.lower() or os.getenv("GROQ_API_KEY"):
        chain.append(primary)
    # Add Gemini fallback only when a key exists.
    if fallback not in chain and os.getenv("GEMINI_API_KEY"):
        chain.append(fallback)
    if not chain:
        # Absolute last resort: fall back to the main planning primary.
        chain.append(primary_model())
    return chain


def _model_chain(model: str) -> list[str]:
    """Ordered models to try for planning calls: chosen model, then Groq fallback."""
    chain = [model]
    fb = fallback_model()
    if fb and fb != model and os.getenv("GROQ_API_KEY"):
        chain.append(fb)
    return chain


def _run_chain(
    chain: list[str],
    base_kwargs: dict[str, Any],
) -> Any:
    """Try each model in ``chain`` in order; return first success or re-raise."""
    last_exc: Exception | None = None
    for i, candidate in enumerate(chain):
        kwargs = {**base_kwargs, "model": candidate}
        try:
            response = litellm.completion(**kwargs)
            return response.choices[0].message
        except Exception as exc:
            last_exc = exc
            nxt = chain[i + 1] if i + 1 < len(chain) else None
            if nxt:
                logger.warning(
                    "Model %s failed (%s); falling back to %s",
                    candidate, type(exc).__name__, nxt,
                )
            else:
                logger.error(
                    "All models failed; last was %s (%s)", candidate, type(exc).__name__
                )
    raise last_exc  # type: ignore[misc]


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
    kwargs: dict[str, Any] = {
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return _run_chain(_model_chain(model or primary_model()), kwargs)


def verify_chat(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.0,
    max_tokens: int | None = None,
) -> Any:
    """Chat using the verify/rewrite chain (Groq primary, Gemini Flash-Lite fallback).

    No tool schemas — verify and rewrite are pure text/JSON generation calls.
    Uses a separate quota bucket from the main planning ``chat()`` calls.
    """
    load_env()
    kwargs: dict[str, Any] = {
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return _run_chain(verify_chain(), kwargs)
