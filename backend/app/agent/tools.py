"""Analysis tools exposed to the LLM via structured args (plan section 5).

Tools:
- ``query_events(filters)`` — constrained, structured query over the DuckDB
  store (fixed filter interface, not free-form SQL, for v1).
- ``shot_map(subject, filters)`` — shots + xG rendered to an mplsoccer PNG;
  returns numbers and image path.
- ``pass_network(team, match)`` — build, render, and return the pass network.
- ``compare_players(player_a, player_b, metrics)`` — aggregate metrics, return
  a radar chart plus raw numbers.
- ``tactics_lookup(query)`` — Chroma RAG over ``tactics_kb/`` for qualitative
  tactical concepts.

No logic yet — stubs for milestones M2-M4.
"""
