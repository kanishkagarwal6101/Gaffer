# Gaffer — backend

FastAPI service for Gaffer, a conversational football analyst grounded in real
StatsBomb event data. See `../GAFFER_PLAN.md` for the full spec.

## Setup

```bash
uv sync
```

## Run the dev server

```bash
uv run uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/ — it returns a hello message.

## Layout

```
app/
├── main.py          # FastAPI app, /chat endpoint
├── agent/
│   ├── graph.py     # LangGraph loop: plan → tools → ground → answer
│   ├── tools.py     # the analysis tools
│   └── schemas.py   # Pydantic models (tool args, final answer)
├── data/
│   ├── ingest.py    # statsbombpy → parquet cache
│   └── store.py     # DuckDB views + query helpers
├── viz/
│   └── pitch.py     # mplsoccer renderers → PNG
└── llm.py           # LiteLLM client + fallback
```
