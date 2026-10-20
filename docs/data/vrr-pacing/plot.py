#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Display commit intervals on a VRR TV at 2x: unpaced, paced, and FreeFG 0.9.0. Reads data.json beside it.

  python3 docs/data/vrr-pacing/plot.py      # writes docs/assets/vrr-pacing.svg and .png

One histogram per group (every run pooled, share of intervals per 0.25 ms bin, one shared scale) and its 5th-95th
percentile range. The two earlier-build rows and the FreeFG row come from different days and builds, so a rule
separates them and a caption marks the earlier pair; conditions and caveats are in MEASUREMENTS.md. The earlier paced
row is an outline in a colour with no assigned meaning (figstyle's INTEL means Intel's shaders in the other figures).
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ beside the data
sys.path.insert(0, str(HERE.parent))
import figstyle as s  # noqa: E402
import numpy as np  # noqa: E402

DATA = json.loads((HERE / 'data.json').read_text())
W, H = 1200, 636
X0, X1 = 250, 930        # histogram x range (design pixels)
MS_MAX = 22.0            # x range 0-22 ms holds every interval in the data
SHARE_MAX = 40.0         # one vertical scale for all rows (% of intervals per bin)
HIST_H = 96              # height of SHARE_MAX
RANGE_X = W - 56         # right edge of the p5-p95 column
REFRESH_MS = 1000 / 120  # the TV's shortest refresh


def x(ms):
    return X0 + ms * (X1 - X0) / MS_MAX


def row(ax, base, label, group, color, fill=True):
    bins = np.array(DATA['bins_ms'])
    counts = np.array(group['histogram_counts'], dtype=float)
    share = 100 * counts / counts.sum()
    keep = bins[1:] <= MS_MAX
    edges = np.append(bins[:-1][keep], bins[1:][keep][-1])
    share = share[keep]
    if not fill:
        # An outline would draw single intervals as a 2 px line along the baseline, which a filled row leaves
        # invisible (under half a design pixel tall); it spans the bins that would be visible when filled.
        used = np.flatnonzero(share / SHARE_MAX * HIST_H >= 0.5)
        share, edges = share[used[0]:used[-1] + 1], edges[used[0]:used[-1] + 2]
    ax.stairs(base - share / SHARE_MAX * HIST_H, x(edges), baseline=base, fill=fill, color=color,
              linewidth=0 if fill else 2, zorder=3)
    ax.plot([X0, X1], [base, base], color=s.LINE, linewidth=1.0, zorder=2)
    p5, _, p95 = group['p5_p50_p95_ms']
    s.text(ax, 56, base - 22, label, 22, s.INK, 'bold')
    s.text(ax, RANGE_X, base - 22, f'{p5:.1f}–{p95:.1f}', 22, color, 'bold', 'right')


def render():
    s.setup('freefg-vrr-pacing')
    fig, ax = s.canvas(W, H)
    s.text(ax, 56, 62, 'Frame pacing at 2× on a VRR TV', 36, s.INK, 'bold')
    s.text(ax, 56, 106, 'AMD BC-250  ·  2560×1440 SDR  ·  Cyberpunk 2077', 20, s.MUTED)

    unpaced, paced, freefg = DATA['groups']
    top = 166
    s.text(ax, RANGE_X, top, 'p5–p95 (ms)', 18, s.MUTED, align='right')
    s.text(ax, x(REFRESH_MS), top, '120 Hz', 18, s.MUTED, align='center')
    s.text(ax, 56, 222, 'Earlier build', 18, s.MUTED)  # caption of the top pair only, left of the Unpaced spike
    row(ax, 294, 'Unpaced', unpaced, s.WARN)
    row(ax, 400, 'Paced', paced, s.MUTED, fill=False)
    # FreeFG was measured on another day with another build: its own group below a rule.
    ax.plot([56, W - 56], [440, 440], color=s.LINE, linewidth=1.0, zorder=1)
    row(ax, 536, 'FreeFG 0.9.0', freefg, s.FREEFG)
    ax.plot([x(REFRESH_MS)] * 2, [top + 18, 536], color=s.MUTED, linewidth=1.0, linestyle=(0, (2, 3)), zorder=4)

    for ms in range(0, 21, 5):
        s.text(ax, x(ms), 560, f'{ms}', 16, s.FAINT, align='center')
    s.text(ax, (X0 + X1) / 2, 596, 'ms between display commits', 18, s.MUTED, align='center')
    s.check_inside(fig, W, H)
    return s.save(fig, 'vrr-pacing', 'Frame pacing at 2x on a VRR TV',
                  'Intervals between display commits on an LG G5 TV with VRR, Cyberpunk 2077 at 2x: unpaced and paced '
                  '(earlier build), FreeFG 0.9.0. Source: docs/data/vrr-pacing/data.json.')


if __name__ == '__main__':
    for path in render():
        print(path.relative_to(HERE.parents[2]))
