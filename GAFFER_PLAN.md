# Gaffer — v1 Build Plan & Project Spec

> **How to use this doc:** Drop it in the repo root as `PLAN.md`. Tell Cursor: *"Read PLAN.md — this is the source of truth for the project; keep changes consistent with it."* Cursor holds whole-project structure; use the Claude Code CLI for the hard isolated modules (marked **[CC]** in the milestones).

---

## 0. What we're building (v1)

A conversational football analyst grounded in **real StatsBomb event data**. You ask a tactical or scouting question in plain English; an agent retrieves the relevant data, runs the analysis, and answers with reasoning **plus** a pitch visualization — and it verifies its own numbers before answering.

**v1 scope (deliberately small):**
- One competition loaded (a tournament with players you care about — see Data layer).
- Conversational analyst with three analysis tools: shot map, pass network, player comparison.
- A grounding check so it never invents a stat.

**Out of scope for v1 (these are v2):** live/current data, the full auto-generated scouting report, multiple competitions, streaming UI.

---

## 1. Cost summary — everything is $0

| Layer | Choice | Cost | Catch |
|---|---|---|---|
| Match data | StatsBomb Open Data via `statsbombpy` | Free, no key | Historical/selected competitions only |
| App LLM | Gemini Flash free tier (primary) | Free, no card | ~1,500 req/day; prompts may train Google's models |
| LLM fallback | Groq (Llama 3.3 70B) | Free | ~30 RPM / 1,000 req/day; no training |
| Embeddings | `sentence-transformers` (local) | Free | Runs on CPU, slightly slower |
| Vector store | Chroma (local, embedded) | Free | No service needed |
| Event store | DuckDB over Parquet (local) | Free | — |
| Pitch viz | `mplsoccer` (matplotlib) | Free | — |
| Agent/orchestration | LangGraph + LiteLLM (OSS) | Free | — |
| Backend | FastAPI, run locally | Free | Deploy later on a free host |
| Frontend | Next.js on Vercel (Hobby) | Free | — |

**Net runtime cost: ₹0.** The only paid thing in your world is the Claude/Cursor subscription you already have for *coding*, not for the app.

---

## 2. The stack (and why)

- **Python 3.12 + `uv`** for the backend env (fast, free, no Conda pain).
- **FastAPI** — the API server.
- **LangGraph** — the agent loop (planning node + tool nodes + grounding node). Gives you explicit state and avoids `while True` agent spaghetti.
- **LiteLLM** — one interface over Gemini + Groq so you can swap models and add automatic fallback when a free tier rate-limits you.
- **`statsbombpy` → Parquet → DuckDB** — pull free event data once, cache as Parquet, query with DuckDB (SQL over files, no DB server).
- **`sentence-transformers` + Chroma** — local, free RAG over a small tactics knowledge base you write yourself.
- **`mplsoccer`** — football-correct pitch plots (shot maps, pass networks, heatmaps) rendered server-side to PNG.
- **Next.js (App Router) + React + Tailwind** — chat UI + a panel that renders returned visuals. Dark "tactics board" aesthetic.

---

## 3. Repo structure

```
gaffer/
├── PLAN.md                  # this file — source of truth
├── CLAUDE.md                # standing instructions for Claude Code (run /init, then edit)
├── .env.example             # GEMINI_API_KEY=, GROQ_API_KEY=
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py          # FastAPI app, /chat endpoint
│   │   ├── agent/
│   │   │   ├── graph.py     # LangGraph loop: plan → tools → ground → answer
│   │   │   ├── tools.py     # the analysis tools
│   │   │   └── schemas.py   # Pydantic models (tool args, final answer)
│   │   ├── data/
│   │   │   ├── ingest.py    # statsbombpy → parquet cache
│   │   │   └── store.py     # DuckDB views + query helpers
│   │   ├── viz/
│   │   │   └── pitch.py     # mplsoccer renderers → PNG
│   │   └── llm.py           # LiteLLM client + fallback
│   └── data_cache/          # parquet files (gitignored)
├── tactics_kb/              # markdown notes on tactical concepts (your RAG source)
└── frontend/                # Next.js app
```

---

## 4. Data layer

1. `from statsbombpy import sb; sb.competitions()` — list what's currently in the free open data.
2. **Pick a competition with players you care about.** A men's World Cup gives you Ronaldo + Messi; a 2008–2018 La Liga season gives you peak Messi. Confirm availability from step 1 rather than assuming.
3. `sb.matches(competition_id, season_id)` → `sb.events(match_id)` for each match → concatenate → write to `data_cache/events.parquet`. Cache once; never hit StatsBomb on every request.
4. Build a **DuckDB view** over the parquet. This is the queryable layer the agent reads.
5. Write a short schema note (in `tactics_kb/` or a comment) of the key columns: `player`, `team`, `type` (Pass/Shot/Carry…), `location` `[x,y]`, shot `xG` (`shot_statsbomb_xg`), pass `end_location`, and the shot **freeze-frame** (positions of all players at the shot — your tactical gold).

**Sanity gate:** before moving on, confirm a known number (e.g., a player's goal count in the tournament) matches reality.

---

## 5. Agent + tools (the core)

**The loop (LangGraph):** `question → plan → call tool(s) → ground → answer`. The planner decides which tools to call and can iterate (query, look at result, query again) before answering.

**Tools** (plain Python functions exposed to the LLM via structured args):

1. `query_events(filters)` — constrained, structured query over the DuckDB store (player, team, event type, match, zone). **Start with a fixed filter interface, not free-form SQL**, to avoid injection and malformed-query loops. Free SQL is a v2 hardening task.
2. `shot_map(subject, filters)` — pull shots + xG, render an `mplsoccer` pitch PNG, return both the numbers and the image path.
3. `pass_network(team, match)` — build the pass network, render, return.
4. `compare_players(player_a, player_b, metrics)` — aggregate the chosen metrics, return a radar chart + the raw numbers.
5. `tactics_lookup(query)` — RAG over `tactics_kb/` (Chroma) for qualitative concepts (what a low block is, etc.) so the reasoning is sound.

**Grounding check (the anti-hallucination flex):** after the LLM drafts its answer, verify every number in the draft against the actual tool outputs. v1 can be a programmatic check (extract numbers from the draft, confirm they appear in the tool results) plus a cheap LLM verify pass; if a number doesn't match, regenerate. This is the single most impressive thing in the build for interviews — make it real.

**Structured outputs:** use Pydantic for tool arguments and for the final answer object (`answer_text`, `visuals: list[url]`, `cited_stats: list`).

---

## 6. Backend API (FastAPI)

- `POST /chat` → body `{ message, session_id }` → runs the agent → returns `{ answer, visuals: [urls], stats }`.
- Serve generated viz images statically (or return base64 for v1 simplicity).
- Session memory: in-memory dict for v1; SQLite if you want persistence later.

---

## 7. Frontend (Next.js)

- Chat interface: message list, input box; render assistant text + inline viz images.
- Calls the backend `/chat`. Streaming (SSE) is optional for v1.
- Tailwind, dark tactics-board look. Backend URL via env var.
- Deploy to Vercel (Hobby, free).

---

## 8. Milestone plan (each milestone = one focused session)

| # | Goal | Tool |
|---|---|---|
| **M0** | Scaffold repo + envs (`uv` backend, Next.js frontend), `.env.example`, run `/init` for CLAUDE.md | Cursor |
| **M1** | Data pipeline: pull & cache one competition's events to Parquet; DuckDB view; pass the sanity gate | Cursor + **[CC]** for ingest logic |
| **M2** | One tool end-to-end: `shot_map` for a chosen player → correct xG → rendered PNG. Proves data→viz path | **[CC]** |
| **M3** | The agent loop: wire LangGraph + LiteLLM(Gemini), expose `query_events` + `shot_map`, get one grounded text+viz answer | **[CC]** |
| **M4** | Add `pass_network`, `compare_players`, and `tactics_lookup` (Chroma RAG) | Cursor + **[CC]** |
| **M5** | Grounding check + structured final output | **[CC]** |
| **M6** | FastAPI `/chat` endpoint + static viz serving | Cursor |
| **M7** | Next.js chat UI rendering answers + visuals | Cursor |
| **M8** | Polish, deploy (Vercel + free backend host), README with a demo GIF | Cursor |

Ship M1–M3 first and you already have a demoable thing. M4–M8 make it portfolio-grade.

---

## 9. Cursor vs Claude Code split (your workflow)

- **Cursor** — project-wide structure, scaffolding, boilerplate, multi-file wiring, "where does this go," refactors, the whole frontend. It holds the map.
- **Claude Code CLI [CC]** — the gnarly isolated brains: the agent orchestration, the query layer, the grounding logic, and any hard multi-step bug. Deep reasoning in one module.
- Keep `CLAUDE.md` current and keep this `PLAN.md` as the doc Cursor re-reads when it loses the thread.

---

## 10. Env & secrets

- `GEMINI_API_KEY` — free from ai.google.dev (Google AI Studio), no card.
- `GROQ_API_KEY` — optional fallback, free from the Groq console.
- **No StatsBomb credentials** needed for open data.
- Never commit `.env`; ship `.env.example` only.

---

## 11. Free-tier gotchas (design around these)

- **Gemini limits** (~1,500 req/day on Flash, 1M context) and **may use free-tier prompts for training** — fine for public football data; don't send secrets. Confirm current limits at ai.google.dev.
- The **grounding check adds LLM calls** — use a cheap/fast model (Gemini Flash-Lite or Groq) for the verify pass, and **cache tool results** so repeated questions don't re-query or re-render.
- Add **LiteLLM fallback to Groq** so a 429 from Gemini doesn't break the demo.
- Data is **historical/selected competitions** — by design for v1; the live layer is v2.

---

## 12. Stretch (v2+)

Live/current layer (API-Football free tier), the full auto-generated scouting report, more competitions, streaming responses, and a public deploy. Open-sourcing this also makes you a candidate for Anthropic's Claude for Open Source program.
