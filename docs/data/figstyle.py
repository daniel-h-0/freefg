# SPDX-License-Identifier: MIT
"""Shared look of the figures in docs/assets: dark slate background, Liberation Sans, direct labels.

Every figure script in docs/data/<figure>/plot.py reads only its own data.json and writes an SVG and a PNG into
docs/assets/. The output is byte-stable for a given matplotlib, numpy and font version: fixed fonts, text as paths,
a fixed SVG hash salt and no dates in the metadata.
"""
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

ASSETS = Path(__file__).resolve().parents[1] / 'assets'

BG = '#18232d'        # page
PANEL = '#22323f'     # panels and header bands
INK = '#f1f4f7'       # main text
MUTED = '#b8c7d3'     # secondary text
FAINT = '#7d91a3'     # tertiary text, axis ticks
LINE = '#3d5162'      # rules and grid
FREEFG = '#5de2b5'    # FreeFG and its own shaders
INTEL = '#8fa3b8'     # XeFG with Intel's shaders
WARN = '#ef8f7a'      # unpaced output
CHANGE = '#e6b687'    # differences and annotations

PX = 0.72             # points per design pixel (sizes below are given in design pixels at 100 dpi)


def font(weight='regular', family='Liberation Sans'):
    """FontProperties of an installed Liberation font file; refuses a substitute, so every build draws the same glyphs."""
    props = font_manager.FontProperties(family=family, weight=weight)
    path = font_manager.findfont(props, fallback_to_default=False)
    expected = {'Liberation Sans': 'LiberationSans', 'Liberation Mono': 'LiberationMono'}[family]
    if expected not in Path(path).name:
        raise SystemExit(f'{family} is not installed (found {path}); install the Liberation fonts')
    return font_manager.FontProperties(fname=path)


def setup(salt):
    plt.rcParams.update({'svg.fonttype': 'path', 'svg.hashsalt': salt, 'axes.unicode_minus': False,
                         'path.simplify': False})


def canvas(width, height):
    """A figure of width x height design pixels with one invisible axes in pixel coordinates (y down)."""
    fig = plt.figure(figsize=(width / 100, height / 100), dpi=100, facecolor=BG)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set(xlim=(0, width), ylim=(height, 0))
    ax.axis('off')
    return fig, ax


def text(ax, x, y, value, size=20, color=INK, weight='regular', align='left', va='center', family='Liberation Sans',
         **kwargs):
    return ax.text(x, y, value, fontsize=size * PX, fontproperties=font(weight, family), color=color, ha=align, va=va,
                   **kwargs)


def check_inside(fig, width, height, margin=36):
    """Every text artist lies inside the canvas less a margin, and no two texts overlap."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    boxes = []
    for artist in fig.findobj(matplotlib.text.Text):
        if not artist.get_visible() or not artist.get_text().strip():
            continue
        box = artist.get_window_extent(renderer)
        if box.x0 < margin or box.y0 < 8 or box.x1 > width - margin or box.y1 > height - 8:
            raise SystemExit(f'text outside the canvas: {artist.get_text()!r}')
        boxes.append((artist.get_text(), box))
    for i, (a, box_a) in enumerate(boxes):
        for b, box_b in boxes[i + 1:]:
            if box_a.overlaps(box_b) and box_a.width and box_b.width:
                inter_w = min(box_a.x1, box_b.x1) - max(box_a.x0, box_b.x0)
                inter_h = min(box_a.y1, box_b.y1) - max(box_a.y0, box_b.y0)
                if inter_w > 1 and inter_h > 1:
                    raise SystemExit(f'texts overlap: {a!r} and {b!r}')


def save(fig, stem, title, description):
    """SVG (text as paths, no date) and PNG at 2x, both without timestamps."""
    ASSETS.mkdir(parents=True, exist_ok=True)
    svg = ASSETS / f'{stem}.svg'
    fig.savefig(svg, facecolor=BG, metadata={'Date': None, 'Creator': None, 'Title': title, 'Description': description})
    svg.write_text('\n'.join(line.rstrip() for line in svg.read_text().splitlines()) + '\n')
    png = ASSETS / f'{stem}.png'
    fig.savefig(png, dpi=200, facecolor=BG, metadata={'Software': None, 'Title': title, 'Description': description})
    plt.close(fig)
    return svg, png
