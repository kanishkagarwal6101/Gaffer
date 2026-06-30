"""LiteLLM client + fallback.

One interface over Gemini (primary) and Groq (fallback) via LiteLLM so models
can be swapped and a free-tier 429 from Gemini automatically falls back to Groq
(plan sections 2, 5, 11). The grounding-verify pass should use a cheap/fast
model (Gemini Flash-Lite or Groq).

No logic yet — stub for milestone M3.
"""
