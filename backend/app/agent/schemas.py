"""Pydantic models for tool arguments and the final answer (plan section 5).

Two roles:

- **Tool argument schemas** (``QueryEventsArgs``, ``ShotMapArgs``) validate the
  structured args the LLM produces when it calls a tool, and double as the
  source for the JSON tool specs advertised to the model (see ``tools.py``).
- **Final answer object** (``AgentAnswer``) is the structured result the agent
  returns: ``answer_text`` (the grounded prose), ``visuals`` (PNG URLs), and
  ``cited_stats`` (the real numbers the answer references).

The grounding-verification step that checks every cited number against tool
output lands in M5; M3 just wires the loop and the structured output.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Event types present in the StatsBomb data the agent may filter on. Kept open
# (plain str) at the schema edge; the store validates against real data.

EVENT_TYPES = (
    "Shot",
    "Pass",
    "Carry",
    "Pressure",
    "Duel",
    "Dribble",
    "Interception",
    "Ball Recovery",
    "Foul Committed",
)


class QueryEventsArgs(BaseModel):
    """Filters for the constrained ``query_events`` tool (fixed interface, no SQL)."""

    player: str | None = Field(
        default=None,
        description="Full StatsBomb player name to filter on, e.g. 'Lionel Andrés Messi Cuccittini'.",
    )
    team: str | None = Field(
        default=None, description="Team name to filter on, e.g. 'Argentina'."
    )
    event_type: str | None = Field(
        default=None,
        description="Event type to filter on, e.g. 'Shot', 'Pass', 'Carry'.",
    )
    match_id: int | None = Field(
        default=None, description="StatsBomb match id to restrict to a single match."
    )
    limit: int = Field(
        default=50, ge=1, le=500, description="Max rows to return (1-500)."
    )


class ShotMapArgs(BaseModel):
    """Args for the ``shot_map`` tool — render a player's shots + xG."""

    player: str = Field(
        ...,
        description="Full StatsBomb player name whose shots to map, e.g. 'Lionel Andrés Messi Cuccittini'.",
    )


class PassNetworkArgs(BaseModel):
    """Args for ``pass_network`` — one team's completed-pass graph in one match.

    The model can pick the match either by an ``opponent`` (we resolve to a real
    ``match_id`` from the data) or by an explicit ``match_id`` if it knows one.
    Exactly one of those is required; ``team`` is always required.
    """

    team: str = Field(
        ..., description="Team name whose pass network to render, e.g. 'France'."
    )
    opponent: str | None = Field(
        default=None,
        description="Opponent team name to disambiguate the match, e.g. 'Argentina'.",
    )
    match_id: int | None = Field(
        default=None,
        description="StatsBomb match id. Use this OR ``opponent``; not both required.",
    )
    until_minute: int | None = Field(
        default=60,
        ge=1,
        le=120,
        description=(
            "Build the network from completed passes up to this minute (default 60). "
            "Stopping before mass substitutions keeps avg player positions meaningful."
        ),
    )


class ComparePlayersArgs(BaseModel):
    """Args for ``compare_players`` — radar of two players over the whole tournament."""

    player_a: str = Field(..., description="First player name (short ok, e.g. 'Mbappé').")
    player_b: str = Field(..., description="Second player name (short ok, e.g. 'Messi').")
    metrics: list[str] | None = Field(
        default=None,
        description=(
            "Optional subset of metric keys to compare. Available: shots, goals, xg, "
            "key_passes, assists, progressive_passes, passes_completed. Default uses "
            "shots, goals, xg, key_passes, assists, progressive_passes."
        ),
    )


class TacticsLookupArgs(BaseModel):
    """Args for ``tactics_lookup`` — semantic RAG over ``tactics_kb/``."""

    query: str = Field(
        ...,
        description=(
            "Natural-language question or concept to look up, e.g. 'what is a low block?'."
        ),
    )
    top_k: int = Field(
        default=3, ge=1, le=8, description="Max chunks to return (1-8)."
    )


class CitedStat(BaseModel):
    """A single number the answer references, tagged with the tool that produced it."""

    label: str
    value: str
    source: str = Field(description="Tool that produced the number, e.g. 'shot_map'.")


class AgentAnswer(BaseModel):
    """Structured final answer the agent returns (plan section 5)."""

    answer_text: str
    visuals: list[str] = Field(
        default_factory=list, description="PNG URLs rendered for this answer."
    )
    cited_stats: list[CitedStat] = Field(
        default_factory=list, description="The real numbers the answer references."
    )
