"""Drawing of the waveform and of the structure on a matplotlib ``Axes``.

Shared by the on-screen canvas and by the PNG export, so that the exported
image is exactly what the application shows.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator

from .audio import WaveformEnvelope
from .export import format_timestamp
from .model import Structure

BACKGROUND = "#14171c"
WAVEFORM = "#d7dde6"
BOUNDARY = "#f2f4f7"
TEXT = "#f2f4f7"
SILENCE_COLOR = "#4a4f57"
PLAYHEAD = "#ff4d4d"

#: Colour-blind friendly palette (Okabe-Ito, reordered for contrast).
PALETTE = (
    "#56b4e9",
    "#e69f00",
    "#009e73",
    "#cc79a7",
    "#f0e442",
    "#d55e00",
    "#0072b2",
    "#9ad0a8",
    "#b39ddb",
    "#ef9a9a",
)


def label_colors(labels: Sequence[str]) -> dict[str, str]:
    """One colour per distinct label, stable in order of first appearance."""
    colors: dict[str, str] = {}
    index = 0
    for label in labels:
        if label in colors:
            continue
        if label.strip().lower() in ("silence", "silenzio"):
            colors[label] = SILENCE_COLOR
        else:
            colors[label] = PALETTE[index % len(PALETTE)]
            index += 1
    return colors


def style_axes(ax: Axes) -> None:
    ax.set_facecolor(BACKGROUND)
    ax.set_ylim(-1.05, 1.25)
    ax.set_yticks([])
    for side in ("top", "left", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#5c6470")
    ax.tick_params(axis="x", colors=TEXT, labelsize=8)
    ax.xaxis.set_major_locator(MaxNLocator(nbins=12))
    ax.xaxis.set_major_formatter(
        FuncFormatter(lambda value, _pos: format_timestamp(value, decimals=0))
    )
    ax.margins(x=0)


def draw_structure(
    ax: Axes,
    envelope: WaveformEnvelope | None,
    structure: Structure | None,
    view: tuple[float, float],
    columns: int = 1600,
    selected: Sequence[int] = (),
    chords: Sequence = (),
) -> None:
    """Draw waveform, coloured segments, boundaries and labels for ``view``."""
    ax.clear()
    style_axes(ax)
    start, end = view
    if end <= start:
        end = start + 1.0
    ax.set_xlim(start, end)

    if structure is not None:
        colors = label_colors(structure.labels())
        chosen = set(selected)
        for index, seg in enumerate(structure.segments):
            if seg.end < start or seg.start > end:
                continue
            color = colors[seg.label]
            ax.axvspan(
                seg.start,
                seg.end,
                ymin=0.0,
                ymax=1.0,
                color=color,
                alpha=0.55 if index in chosen else 0.28,
                linewidth=0,
            )
            ax.axvspan(seg.start, seg.end, ymin=0.9, ymax=1.0, color=color, alpha=0.95, linewidth=0)
            left, right = max(seg.start, start), min(seg.end, end)
            # Only write the name where it has room: about 7 px per character.
            room = (right - left) / (end - start) * columns
            if room >= 7 * min(len(seg.label), 4) + 8:
                text = seg.label if room >= 7 * len(seg.label) + 8 else seg.label[:3] + "…"
                ax.text(
                    (left + right) / 2,
                    1.135,
                    text,
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="#101214",
                    fontweight="bold",
                    clip_on=True,
                )
            if index > 0 and start <= seg.start <= end:
                ax.axvline(seg.start, color=BOUNDARY, linewidth=1.2, alpha=0.9)

    if envelope is not None:
        times, low, high = envelope.view(start, end, columns)
        if len(times):
            ax.fill_between(times, low, high, color=WAVEFORM, linewidth=0.6, alpha=0.95)

    # Chord lane along the bottom; names appear once there is room for them.
    for chord in chords:
        if chord.end < start or chord.start > end or chord.name == "N":
            continue
        left, right = max(chord.start, start), min(chord.end, end)
        room = (right - left) / (end - start) * columns
        if chord.start >= start:
            ax.axvline(chord.start, ymin=0.0, ymax=0.07, color=TEXT, linewidth=0.6, alpha=0.6)
        if room >= 7 * len(chord.name) + 6:
            ax.text(
                (left + right) / 2,
                -0.97,
                chord.name,
                ha="center",
                va="center",
                fontsize=7,
                color=TEXT,
                clip_on=True,
            )


def render_png(
    path: str | Path,
    envelope: WaveformEnvelope,
    structure: Structure,
    title: str = "",
    width_px: int = 2400,
    height_px: int = 520,
    dpi: int = 150,
) -> Path:
    """Save the whole song, with its structure, as a PNG image."""
    from matplotlib.backends.backend_agg import FigureCanvasAgg

    path = Path(path)
    fig = Figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi, facecolor=BACKGROUND)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    draw_structure(ax, envelope, structure, (0.0, structure.duration), columns=width_px)
    if title:
        ax.set_title(title, color=TEXT, fontsize=10, loc="left")
    fig.subplots_adjust(left=0.01, right=0.99, top=0.88 if title else 0.97, bottom=0.14)
    fig.savefig(path, dpi=dpi, facecolor=BACKGROUND)
    return path
