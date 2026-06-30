"""LangGraph agent loop: plan -> tools -> ground -> answer.

Defines the explicit-state agent graph (plan section 5). The planner node
decides which tools to call and may iterate (query, inspect result, query
again) before drafting an answer; the grounding node verifies every number in
the draft against actual tool outputs and regenerates on mismatch.

No logic yet — stub for milestone M3 / M5.
"""
