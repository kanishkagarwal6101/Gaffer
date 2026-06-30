"""mplsoccer renderers -> PNG (plan sections 2, 5).

Football-correct pitch plots rendered server-side to PNG. v1 ships the shot map
(shots placed by location, xG encoded by marker size, goals distinguished from
misses by BOTH shape and colour so it stays colourblind-safe). Images are saved
to a served static dir and the file path is returned for the API to expose.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless: render to file, never open a window

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from mplsoccer import VerticalPitch  # noqa: E402

# Dark "tactics board" palette — mirrors the frontend.
_PITCH_BG = "#0E1512"      # dark turf
_LINE = "#E8EDEB"          # light chalk lines
_ACCENT = "#34D399"        # turf-green accent (goals)
_MISS = "#9FB1AB"          # muted chalk (misses)
_TEXT = "#E8EDEB"

# Default served static dir: backend/app/static/shot_maps/.
STATIC_DIR = Path(__file__).resolve().parents[1] / "static" / "shot_maps"

# xG (0..1) -> marker area in points^2.
_SIZE_MIN = 120.0
_SIZE_SPAN = 1100.0


def _slug(text: str) -> str:
    keep = [c.lower() if c.isalnum() else "-" for c in text.strip()]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "shot-map"


def render_shot_map(
    shots_df: pd.DataFrame,
    title: str,
    out_dir: Path | str = STATIC_DIR,
) -> str:
    """Render a single shot map to a PNG and return its file path.

    Args:
        shots_df: rows with ``x``, ``y``, ``shot_statsbomb_xg`` and a boolean
            ``is_goal`` (the shape returned by ``store.get_player_shots``).
        title: figure title (also used to name the file).
        out_dir: directory to write into; created if missing.

    xG is encoded by marker *size*. Goals are filled green circles; misses are
    hollow circles — shape + colour together, so the map reads correctly in
    greyscale and for colourblind viewers. A player with zero shots still
    produces a labelled empty pitch.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slug(title)}.png"

    pitch = VerticalPitch(
        pitch_type="statsbomb",
        half=True,
        pitch_color=_PITCH_BG,
        line_color=_LINE,
        line_alpha=0.45,
        linewidth=1.2,
        pad_top=12,
    )
    fig, ax = pitch.draw(figsize=(7.5, 8.0))
    fig.set_facecolor(_PITCH_BG)

    df = shots_df if shots_df is not None else pd.DataFrame()
    if not df.empty:
        sizes = _SIZE_MIN + df["shot_statsbomb_xg"].astype(float).clip(0, 1) * _SIZE_SPAN
        goals = df["is_goal"].astype(bool)

        # Misses: hollow circles (no fill, coloured edge).
        miss = df[~goals]
        if not miss.empty:
            pitch.scatter(
                miss["x"], miss["y"], s=sizes[~goals], ax=ax,
                marker="o", facecolor="none", edgecolors=_MISS,
                linewidths=1.6, alpha=0.9, zorder=2,
            )
        # Goals: filled green circles with a light rim.
        goal = df[goals]
        if not goal.empty:
            pitch.scatter(
                goal["x"], goal["y"], s=sizes[goals], ax=ax,
                marker="o", facecolor=_ACCENT, edgecolors=_LINE,
                linewidths=1.2, alpha=0.95, zorder=3,
            )
    else:
        ax.text(
            0.5, 0.5, "No shots on record", transform=ax.transAxes,
            ha="center", va="center", color=_MISS, fontsize=13,
        )

    ax.set_title(title, color=_TEXT, fontsize=15, pad=10, fontweight="bold")

    # Legend: shape/colour key + a note that size encodes xG.
    legend_handles = [
        plt.scatter([], [], s=160, marker="o", facecolor=_ACCENT,
                    edgecolors=_LINE, linewidths=1.2, label="Goal"),
        plt.scatter([], [], s=160, marker="o", facecolor="none",
                    edgecolors=_MISS, linewidths=1.6, label="No goal"),
        plt.scatter([], [], s=320, marker="o", facecolor="none",
                    edgecolors=_TEXT, linewidths=1.0, label="Larger = higher xG"),
    ]
    leg = ax.legend(
        handles=legend_handles, loc="lower center", ncol=3,
        frameon=False, labelcolor=_TEXT, fontsize=9,
        bbox_to_anchor=(0.5, -0.04), handletextpad=0.4, columnspacing=1.2,
    )
    for txt in leg.get_texts():
        txt.set_color(_TEXT)

    fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor=_PITCH_BG)
    plt.close(fig)
    return str(out_path)


# Static dirs for the M4 renderers — each tool writes to its own subdir.
PASS_NETWORK_DIR = Path(__file__).resolve().parents[1] / "static" / "pass_networks"
RADAR_DIR = Path(__file__).resolve().parents[1] / "static" / "radars"

# Pass-network marker sizing: nodes scaled by passes touched (in+out).
# Common WC22 names where the literal last token isn't the football-press
# label (Mbappé Lottin -> "Mbappé", Messi Cuccittini -> "Messi"). Falls back
# to the last token for everyone else, which is correct ~95% of the time.
_SHORT_NAMES: dict[str, str] = {
    "Lionel Andrés Messi Cuccittini": "Messi",
    "Kylian Mbappé Lottin": "Mbappé",
    "Ángel Fabián Di María Hernández": "Di María",
    "Julián Álvarez": "Álvarez",
    "Lautaro Javier Martínez": "Martínez",
    "Randal Kolo Muani": "Kolo Muani",
    "Theo Bernard François Hernández": "Hernández",
    "Dayotchanculle Upamecano": "Upamecano",
    "Antoine Griezmann": "Griezmann",
    "Hugo Lloris": "Lloris",
    "Olivier Giroud": "Giroud",
    "Raphaël Varane": "Varane",
    "Aurélien Tchouaméni": "Tchouaméni",
    "Adrien Rabiot": "Rabiot",
    "Ousmane Dembélé": "Dembélé",
    "Jules Koundé": "Koundé",
    "Marcus Thuram": "Thuram",
}


def short_name(full: str) -> str:
    """Football-press short label for a player; falls back to the last token."""
    if full in _SHORT_NAMES:
        return _SHORT_NAMES[full]
    return full.split()[-1] if full else full


_NODE_MIN, _NODE_SPAN = 220.0, 900.0
# Edge widths: completed-pair count -> line width in points.
_EDGE_MIN, _EDGE_SPAN = 0.6, 4.4


def render_pass_network(
    passes_df: pd.DataFrame,
    title: str,
    *,
    until_minute: int | None = None,
    out_dir: Path | str = PASS_NETWORK_DIR,
) -> dict:
    """Render a team's pass network for one match and return path + summary.

    Args:
        passes_df: rows with ``passer``, ``recipient``, ``location``,
            ``pass_end_location``, ``minute`` (the shape returned by
            ``store.team_match_passes``).
        title: figure title (also drives the filename).
        until_minute: optional cap so the window stays meaningful before mass
            substitutions (e.g. ``60``). ``None`` uses every pass.
        out_dir: directory to write into; created if missing.

    Nodes are players placed at their average pass start location, sized by
    total passes touched. Edges are pairs of players who completed passes
    between each other, with line width proportional to the pair's volume.
    """
    from mplsoccer import Pitch  # local to keep import cost off shot_map  # noqa: E402

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slug(title)}.png"

    df = passes_df if passes_df is not None else pd.DataFrame()
    if until_minute is not None and "minute" in df.columns and not df.empty:
        df = df[df["minute"] <= until_minute]

    pitch = Pitch(
        pitch_type="statsbomb",
        pitch_color=_PITCH_BG,
        line_color=_LINE,
        line_alpha=0.45,
        linewidth=1.2,
    )
    fig, ax = pitch.draw(figsize=(10.0, 7.0))
    fig.set_facecolor(_PITCH_BG)

    nodes: dict[str, tuple[float, float, int]] = {}
    edges: dict[tuple[str, str], int] = {}
    if not df.empty:
        # Each pass contributes a start location for the passer and an end
        # location for the recipient. Both feed node placement so a player who
        # only *received* completed passes (never completed one themselves)
        # still gets a node — otherwise an edge endpoint can be unknown.
        df = df.copy()
        df["sx"] = df["location"].apply(lambda v: float(v[0]) if v is not None else None)
        df["sy"] = df["location"].apply(lambda v: float(v[1]) if v is not None else None)
        df["ex"] = df["pass_end_location"].apply(lambda v: float(v[0]) if v is not None else None)
        df["ey"] = df["pass_end_location"].apply(lambda v: float(v[1]) if v is not None else None)
        df = df.dropna(subset=["sx", "sy", "passer", "recipient"])

        passer_pos = df.groupby("passer").agg(
            x=("sx", "mean"), y=("sy", "mean"), made=("sx", "size"),
        )
        recv_pos = df.dropna(subset=["ex", "ey"]).groupby("recipient").agg(
            rx=("ex", "mean"), ry=("ey", "mean"), recd=("ex", "size"),
        )

        # Union of passers and recipients — every edge endpoint is now in nodes.
        all_players = set(passer_pos.index) | set(recv_pos.index)
        for player in all_players:
            made = int(passer_pos.loc[player, "made"]) if player in passer_pos.index else 0
            recd = int(recv_pos.loc[player, "recd"]) if player in recv_pos.index else 0
            if player in passer_pos.index:
                x = float(passer_pos.loc[player, "x"])
                y = float(passer_pos.loc[player, "y"])
            else:
                # Receive-only: place at the average end-location of incoming passes.
                x = float(recv_pos.loc[player, "rx"])
                y = float(recv_pos.loc[player, "ry"])
            nodes[player] = (x, y, made + recd)

        pair_counts = df.groupby(["passer", "recipient"]).size().reset_index(name="n")
        for _, r in pair_counts.iterrows():
            a, b = sorted([r["passer"], r["recipient"]])
            # Belt-and-braces: skip the impossible case (both endpoints must
            # be in nodes after the union build above).
            if a not in nodes or b not in nodes:
                continue
            edges[(a, b)] = edges.get((a, b), 0) + int(r["n"])

    if not nodes:
        ax.text(0.5, 0.5, "No completed passes", transform=ax.transAxes,
                ha="center", va="center", color=_MISS, fontsize=13)
    else:
        max_edge = max(edges.values()) if edges else 1
        max_touches = max(t for *_, t in nodes.values())

        # Edges first so nodes sit on top.
        for (a, b), n in edges.items():
            x0, y0, _ = nodes[a]
            x1, y1, _ = nodes[b]
            width = _EDGE_MIN + (n / max_edge) * _EDGE_SPAN
            alpha = 0.25 + 0.55 * (n / max_edge)
            pitch.lines(x0, y0, x1, y1, lw=width, color=_ACCENT,
                        alpha=alpha, ax=ax, zorder=2)

        for player, (x, y, touches) in nodes.items():
            size = _NODE_MIN + (touches / max_touches) * _NODE_SPAN
            pitch.scatter(x, y, s=size, ax=ax, marker="o",
                          facecolor=_PITCH_BG, edgecolors=_ACCENT,
                          linewidths=1.8, zorder=3)
            label = short_name(player)
            ax.text(x, y, label, color=_TEXT, ha="center", va="center",
                    fontsize=8, fontweight="bold", zorder=4)

    ax.set_title(title, color=_TEXT, fontsize=15, pad=10, fontweight="bold")
    if until_minute is not None:
        ax.text(0.5, -0.02, f"first {until_minute}' of completed passes",
                transform=ax.transAxes, ha="center", va="top",
                color=_MISS, fontsize=9)

    fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor=_PITCH_BG)
    plt.close(fig)
    return {
        "path": str(out_path),
        "nodes": [
            {"player": p, "x": round(x, 2), "y": round(y, 2), "touches": t}
            for p, (x, y, t) in nodes.items()
        ],
        "edges": [
            {"a": a, "b": b, "passes": n}
            for (a, b), n in sorted(edges.items(), key=lambda kv: -kv[1])[:20]
        ],
    }


def render_player_radar(
    player_a: str,
    metrics_a: dict[str, float],
    player_b: str,
    metrics_b: dict[str, float],
    *,
    title: str,
    out_dir: Path | str = RADAR_DIR,
) -> str:
    """Render a comparison radar (spider chart) for two players and return its path.

    Each axis is one metric; both players are overlaid as filled polygons. Axes
    are scaled independently to the pair's per-metric maximum so the chart is
    legible regardless of metric magnitudes. The metric keys/order are taken
    from ``metrics_a`` and must match ``metrics_b``.
    """
    import numpy as np  # noqa: E402

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_slug(title)}.png"

    labels = list(metrics_a.keys())
    if list(metrics_b.keys()) != labels:
        raise ValueError("metrics_a and metrics_b must have the same keys in the same order")

    a_vals = [float(metrics_a[k]) for k in labels]
    b_vals = [float(metrics_b[k]) for k in labels]
    # Per-axis max (so a 6 xG line and a 32 shot line both fill the chart).
    axis_max = [max(av, bv, 1e-6) for av, bv in zip(a_vals, b_vals)]
    a_norm = [v / m for v, m in zip(a_vals, axis_max)]
    b_norm = [v / m for v, m in zip(b_vals, axis_max)]

    # Close the loops.
    angles = np.linspace(0, 2 * np.pi, len(labels), endpoint=False).tolist()
    angles += angles[:1]
    a_norm += a_norm[:1]
    b_norm += b_norm[:1]

    fig = plt.figure(figsize=(8.0, 8.0), facecolor=_PITCH_BG)
    ax = fig.add_subplot(111, polar=True)
    ax.set_facecolor(_PITCH_BG)
    ax.set_theta_offset(np.pi / 2)
    ax.set_theta_direction(-1)

    # Concentric rings + spokes.
    ax.set_rlim(0, 1)
    ax.set_rgrids([0.25, 0.5, 0.75, 1.0], labels=[], angle=0)
    ax.spines["polar"].set_color(_LINE)
    ax.spines["polar"].set_alpha(0.4)
    ax.grid(color=_LINE, alpha=0.18, linewidth=0.8)
    ax.tick_params(colors=_TEXT)

    # Axis labels at each angle, with the per-axis max printed at the rim.
    ax.set_xticks(angles[:-1])
    pretty = [lbl.replace("_", " ") for lbl in labels]
    ax.set_xticklabels(pretty, color=_TEXT, fontsize=10)
    for ang, mx in zip(angles[:-1], axis_max):
        ax.text(ang, 1.08, _fmt_axis_max(mx), color=_MISS, ha="center", va="center", fontsize=8)

    # Player A: turf-green.
    ax.plot(angles, a_norm, color=_ACCENT, linewidth=2.0, label=short_name(player_a))
    ax.fill(angles, a_norm, color=_ACCENT, alpha=0.22)
    # Player B: muted chalk for contrast that stays colourblind-friendly.
    ax.plot(angles, b_norm, color=_LINE, linewidth=2.0, label=short_name(player_b))
    ax.fill(angles, b_norm, color=_LINE, alpha=0.12)

    ax.set_yticklabels([])
    leg = ax.legend(loc="upper right", bbox_to_anchor=(1.18, 1.10),
                    frameon=False, labelcolor=_TEXT, fontsize=11)
    for txt in leg.get_texts():
        txt.set_color(_TEXT)

    fig.suptitle(title, color=_TEXT, fontsize=15, fontweight="bold", y=0.97)
    fig.savefig(out_path, dpi=200, bbox_inches="tight", facecolor=_PITCH_BG)
    plt.close(fig)
    return str(out_path)


def _fmt_axis_max(mx: float) -> str:
    """Compact rim label for the radar (e.g. 32, 6.0)."""
    return str(int(round(mx))) if mx >= 5 else f"{mx:.1f}"
