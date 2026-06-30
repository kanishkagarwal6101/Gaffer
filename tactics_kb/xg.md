# Expected goals (xG)

**Expected goals (xG)** is a per-shot probability that a given chance is scored, taking into account everything the model knows about that chance *at the moment the shot is taken*: location and angle to the goal, distance, body part, assist type (cutback vs cross vs through ball), whether the attacker is one-on-one with the keeper, defender pressure, and the game state. A penalty has an xG of about 0.76; a header from the edge of the six-yard box might be 0.30; a speculative effort from 30 yards is closer to 0.02.

xG separates *chance quality* from *finishing variance*. Over a single match a team can underperform or overperform xG significantly — the ball is round, the keeper has a day, the woodwork intervenes — but across a season the gap usually narrows. A striker scoring 15 goals from 7 xG is finishing well above the model's expectation; whether that is repeatable or hot variance is the interesting question.

Signals and uses in the data:
- Sum of a player's shot xG over a tournament vs actual goals → over/under-performance (e.g. Messi at WC22: 6.03 xG, 7 goals → +0.97).
- xG-on-target (xGOT, sometimes "post-shot xG") factors in the shot's trajectory after it leaves the foot — useful for evaluating goalkeepers.
- A side dominating xG but losing the match is usually a sign of finishing or keeping variance rather than tactical failure.

Related concepts: xA (expected assists — the xG value of the shot a pass creates), npxG (xG excluding penalties).
