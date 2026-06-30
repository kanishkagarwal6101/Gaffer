# Gaffer

A conversational football analyst grounded in **real StatsBomb event data**. Ask a tactical or scouting question in plain English; an agent retrieves the relevant data, runs the analysis, and answers with reasoning **plus** an interactive pitch visualization — and it verifies its own numbers before answering.

> **Status:** early build. The data pipeline and a data-driven, interactive frontend shot map are working. The agent loop and `/chat` API are next. See [`GAFFER_PLAN.md`](./GAFFER_PLAN.md) for the full spec and roadmap.

---

## Why it's interesting

- **Grounded, not guessed.** Every number comes from cached StatsBomb events; a grounding check verifies the answer's stats against actual tool output before it's shown.
- **Real data on screen.** The shot map renders live from the 2022 World Cup Final (Argentina vs France) — 20 vs 10 shots, 3–3, xG 2.76 vs 2.27 — with hover/click-to-pin markers showing `player · minute · xG · outcome`.
- **$0 to run.** StatsBomb open data, local DuckDB + Chroma, free-tier LLMs (Gemini primary, Groq fallback).

---

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12 · `uv` · FastAPI |
| Agent | LangGraph (plan → tools → ground → answer) + LiteLLM (Gemini + Groq fallback) |
| Data | `statsbombpy` → Parquet → DuckDB |
| RAG | `sentence-transformers` + Chroma (local) |
| Viz | Native SVG pitch (primary) · `mplsoccer` PNG (export/fallback) |
| Frontend | React + Vite + TypeScript + Tailwind |

---

## Repo structure

```
Gaffer/
├── GAFFER_PLAN.md           # source of truth — full spec + milestones
├── .env.example             # GEMINI_API_KEY=, GROQ_API_KEY=
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py          # FastAPI app, /chat endpoint
│   │   ├── agent/           # graph.py, tools.py, schemas.py
│   │   ├── data/            # ingest.py (StatsBomb → Parquet), store.py (DuckDB)
│   │   ├── viz/pitch.py     # mplsoccer renderers
│   │   └── llm.py           # LiteLLM client + fallback
│   ├── scripts/             # gen_shotmap.py, verify_top_scorers.py
│   └── data_cache/          # Parquet cache (gitignored)
├── frontend/                # React + Vite app (two-pane chat + analysis canvas)
└── tactics_kb/              # markdown notes for RAG
```

---

## Getting started

### Prerequisites

- [`uv`](https://docs.astral.sh/uv/) for the backend
- Node 18+ for the frontend

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

Serves on http://127.0.0.1:8000 — `GET /` returns a hello message.

**Populate the data cache** (one-time pull of the 2022 World Cup into `data_cache/events.parquet`):

```bash
uv run python -m app.data.ingest
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Serves on http://localhost:5173.

The shot map is driven by `frontend/src/shotmap.generated.json`, produced from the real Parquet cache. Regenerate it after a data refresh:

```bash
cd backend
uv run python -m scripts.gen_shotmap
```

**Render a player's shot map** (mplsoccer PNG to `app/static/shot_maps/`, plus summary stats — shots, xG, goals, over/under-performance):

```bash
cd backend
uv run python -m scripts.test_shot_map "Lionel Andrés Messi Cuccittini"
```

---

## Configuration

Copy `.env.example` to `.env` and fill in (both free, no card):

```
GEMINI_API_KEY=    # ai.google.dev (Google AI Studio)
GROQ_API_KEY=      # console.groq.com — optional fallback
```

No StatsBomb credentials are needed for open data. Never commit `.env`.

---

## Roadmap

| # | Goal | Status |
|---|---|---|
| M0 | Scaffold repo + envs | done |
| M1 | Data pipeline: StatsBomb → Parquet → DuckDB, sanity gate | done |
| M2 | `shot_map` tool end-to-end (data → viz) | done |
| M3 | Agent loop: LangGraph + LiteLLM, one grounded text+viz answer | |
| M4 | `pass_network`, `compare_players`, `tactics_lookup` (RAG) | |
| M5 | Grounding check + structured final output | |
| M6 | FastAPI `/chat` endpoint | |
| M7 | Chat UI rendering answers + visuals | |
| M8 | Polish + deploy | |

---

## License

Not yet licensed. Built on [StatsBomb Open Data](https://github.com/statsbomb/open-data).
