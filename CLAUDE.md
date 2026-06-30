# CLAUDE.md — standing instructions for Claude Code

`GAFFER_PLAN.md` is the source of truth for this project; keep all changes
consistent with it.

## Project

Gaffer — a conversational football analyst grounded in real StatsBomb event
data. Ask a tactical/scouting question in plain English; a LangGraph agent
retrieves data, runs analysis, and answers with reasoning plus a pitch
visualization, verifying its own numbers before answering.

## Layout

- `backend/` — Python 3.12 + uv, FastAPI. `app/` holds the agent, data layer,
  viz, and LLM client (see `backend/README.md`).
- `frontend/` — Next.js (App Router) + TypeScript + Tailwind chat UI.
- `tactics_kb/` — markdown RAG source for the `tactics_lookup` tool.
- `.env.example` — required keys (`GEMINI_API_KEY`, `GROQ_API_KEY`).

## Conventions

- Backend env via `uv` (`uv sync`, `uv run ...`). Never commit `.env`.
- Cache StatsBomb data to `data_cache/` once; never hit the API per request.
- Use Pydantic for tool args and the final answer object.
- Use the `[CC]`-marked milestones (plan section 8) for the hard isolated
  modules: agent orchestration, query layer, grounding logic.
