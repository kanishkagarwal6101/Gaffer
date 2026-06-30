# Pass network

A **pass network** is a graph drawn over a pitch that shows how a team built up play in a match. Each *node* is a player, positioned at their average pass location (the mean of the start coordinates of every pass they completed). Each *edge* between two nodes is drawn when those two players completed passes between each other; the edge's *thickness* is proportional to the volume of completed passes between that pair.

A pass network is read like a map: the *shape* tells you who the team played through, who they avoided, and how compact or stretched the structure was. Common patterns:

- A dense triangle on one flank → the team built attacks down that side.
- A thick edge between the two centre-backs and the goalkeeper → safe circulation in the first phase; rarely a sign of progression.
- A node sitting far higher than the rest → that player was the attacking outlet (often a 10 or a target striker).
- An isolated wide node with thin edges → a winger who was bypassed (left out of the build-up).

Caveats: a pass network only counts *completed* passes and only captures positions *while passing*, not defensive shape. It says nothing about *quality* of the pass or the result. Substitutions usually mean the network is built from a fixed window (e.g. up to the first substitution) so the average locations stay meaningful.

Related concepts: progressive passes (passes that move the ball materially closer to the opponent goal), expected threat (xT) (a more sophisticated, value-weighted view of progression).
