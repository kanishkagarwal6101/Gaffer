"""FastAPI application entrypoint.

Exposes the Gaffer HTTP API. Per the plan (section 6), the core endpoint is
``POST /chat`` which accepts ``{ message, session_id }``, runs the LangGraph
agent, and returns ``{ answer, visuals: [urls], stats }``. Generated pitch
visualizations are served statically (or returned as base64 for v1).

v1 only ships a health/hello route at ``/``; the agent wiring lands in later
milestones (see GAFFER_PLAN.md section 8).
"""

from fastapi import FastAPI

app = FastAPI(title="Gaffer", version="0.1.0")


@app.get("/")
def read_root() -> dict[str, str]:
    """Health check / hello route used to confirm the server boots."""
    return {"message": "Hello from Gaffer"}
