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
