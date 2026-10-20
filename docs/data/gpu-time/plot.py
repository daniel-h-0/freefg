#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""GPU time of one generated frame: XeFG with Intel's shaders against FreeFG 0.9.0, totals and the stages FreeFG
replaces. Reads data.json beside it.

  python3 docs/data/gpu-time/plot.py      # writes docs/assets/gpu-time-per-generated-frame.svg and .png

Conditions, runs, dates and the caveats of comparing the two arms are in packaging/public/MEASUREMENTS.md, not in the
image.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ beside the data
sys.path.insert(0, str(HERE.parent))
import figstyle as s  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

DATA = json.loads((HERE / 'data.json').read_text())
W, H = 1200, 540
X0, PER_MS = 330, 78.0        # bar origin and scale (design pixels per millisecond)
LEFT, RIGHT = 56, W - 56
TOTAL_BAR, STAGE_BAR = 40, 18

# Short names of the stages FreeFG runs with its own shaders; the table in MEASUREMENTS.md gives the full names and
# the stages both arms run with Intel's shaders (left out here: their differences come from the arms' inputs).
NAMES = {
    'Reconstruction network': 'Reconstruction network',
    'Optical flow: 224-channel layers': 'Flow, 224 channels',
    'Optical flow: 64-channel refinement': 'Flow, 64 channels',
}


def x(ms):
    return X0 + ms * PER_MS


def bar(ax, y, ms, height, color, start=0.0):
    ax.add_patch(Rectangle((x(start), y - height / 2), ms * PER_MS, height, facecolor=color, edgecolor='none',
                           zorder=3))


def legend(fig, ax, y, items):
    """Swatch + label pairs on one line, right-aligned to the canvas margin."""
    renderer = fig.canvas.get_renderer()
    swatch, pad, gap = 16, 10, 32
    labels = [s.text(ax, 0, y, label, 18, s.MUTED) for _, label in items]
    widths = [artist.get_window_extent(renderer).width for artist in labels]
    left = RIGHT - sum(swatch + pad + w for w in widths) - gap * (len(items) - 1)
    for (color, _), artist, width in zip(items, labels, widths):
        ax.add_patch(Rectangle((left, y - swatch / 2), swatch, swatch, facecolor=color, edgecolor='none'))
        artist.set_x(left + swatch + pad)
        left += swatch + pad + width + gap


def render():
    s.setup('freefg-gpu-time-per-generated-frame')
    fig, ax = s.canvas(W, H)
    t = DATA['totals']
    stages = [stage for stage in DATA['stages'] if stage['freefg_runs'] == 'own shaders']

    s.text(ax, LEFT, 62, 'GPU time per generated frame at 2×', 36, s.INK, 'bold')
    s.text(ax, LEFT, 106, 'AMD BC-250  ·  2560×1440 SDR', 20, s.MUTED)
    legend(fig, ax, 106, [(s.FREEFG, 'FreeFG\'s shaders'), (s.INTEL, 'Intel\'s shaders')])

    # Totals: Intel's shaders throughout; FreeFG 0.9.0 = its own shaders, then the passes it leaves to Intel's.
    y = 190
    s.text(ax, LEFT, y, 'XeFG, Intel\'s shaders', 22, s.INK, 'bold')
    bar(ax, y, t['intel_ms'], TOTAL_BAR, s.INTEL)
    s.text(ax, x(t['intel_ms']) - 14, y + 1, f'{t["intel_ms"]:.2f} ms', 22, s.BG, 'bold', 'right', zorder=4)
    y = 248
    s.text(ax, LEFT, y, 'FreeFG 0.9.0', 22, s.INK, 'bold')
    bar(ax, y, t['freefg_own_ms'], TOTAL_BAR, s.FREEFG)
    bar(ax, y, t['freefg_intel_ms'], TOTAL_BAR, s.INTEL, start=t['freefg_own_ms'])
    ax.plot([x(t['freefg_own_ms'])] * 2, [y - TOTAL_BAR / 2, y + TOTAL_BAR / 2], color=s.BG, linewidth=1.5, zorder=4)
    s.text(ax, x(t['freefg_ms']) - 14, y + 1, f'{t["freefg_ms"]:.2f} ms', 22, s.BG, 'bold', 'right', zorder=4)

    ax.plot([LEFT, RIGHT], [296, 296], color=s.LINE, linewidth=0.8, zorder=2)

    # The stages FreeFG replaces: upper bar Intel's shaders, lower bar FreeFG's own.
    y = 342
    for stage in stages:
        s.text(ax, LEFT, y, NAMES[stage['stage']], 20, s.INK)
        upper, lower = y - STAGE_BAR / 2 - 2, y + STAGE_BAR / 2 + 2
        bar(ax, upper, stage['intel_ms'], STAGE_BAR, s.INTEL)
        bar(ax, lower, stage['freefg_ms'], STAGE_BAR, s.FREEFG)
        s.text(ax, x(stage['intel_ms']) + 10, upper, f'{stage["intel_ms"]:.2f}', 18, s.INTEL, zorder=4)
        s.text(ax, x(stage['freefg_ms']) + 10, lower, f'{stage["freefg_ms"]:.2f}', 18, s.FREEFG, zorder=4)
        end = lower + STAGE_BAR / 2
        y += 66
    ax.plot([X0, X0], [162, end + 10], color=s.LINE, linewidth=1.0, zorder=4)  # zero line

    s.check_inside(fig, W, H)
    return s.save(fig, 'gpu-time-per-generated-frame', 'GPU time per generated frame at 2x on the AMD BC-250',
                  'XeFG at 2x, output 2560x1440 SDR: totals for Intel\'s shaders and FreeFG 0.9.0, and the three '
                  'stages FreeFG replaces, from two runs with different inputs. Source: docs/data/gpu-time/data.json.')


if __name__ == '__main__':
    for path in render():
        print(path.relative_to(HERE.parents[2]))
