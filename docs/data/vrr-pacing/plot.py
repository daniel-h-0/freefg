#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Display commit intervals on a VRR TV at 2x: unpaced, paced, and FreeFG 0.9.0. Reads data.json beside it.

  python3 docs/data/vrr-pacing/plot.py      # writes docs/assets/vrr-pacing.svg and .png
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ beside the data
sys.path.insert(0, str(HERE.parent))
import figstyle as s  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

DATA = json.loads((HERE / 'data.json').read_text())
W, H = 1600, 1010
YMAX_MS = 22.0
SHARE_MAX = 40.0
SEQ = (470, 900)       # x range of the sequence panels (design pixels)
HIST = (990, 1544)     # x range of the histogram panels
ROW_H = 168


def axes(fig, x0, x1, top, height):
    ax = fig.add_axes([x0 / W, 1 - (top + height) / H, (x1 - x0) / W, height / H], facecolor=s.PANEL)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=s.FAINT, length=0, labelsize=14 * s.PX, pad=4)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontproperties(s.font())
    return ax


def style_ticks(ax):
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_fontproperties(s.font())
        label.set_fontsize(14 * s.PX)
        label.set_color(s.FAINT)


def row(fig, canvas, top, group, color, date):
    seq = np.array(group['sequence_ms'])
    counts = np.array(group['histogram_counts'], dtype=float)
    bins = np.array(DATA['bins_ms'])
    share = 100 * counts / counts.sum()
    p5, p50, p95 = group['p5_p50_p95_ms']
    s.text(canvas, 56, top + 14, group['label'].replace('2x', '2×'), 22, s.INK, 'bold')
    s.text(canvas, 56, top + 42, date, 16, s.MUTED)
    s.text(canvas, 56, top + 76, f'p5–p95  {p5:.1f}–{p95:.1f} ms', 17, color, 'bold')
    s.text(canvas, 56, top + 102, f'SD {group["sd_ms"]:.2f} ms  ·  median {p50:.1f} ms', 16, s.MUTED)
    long_per_s = group['over_1_5x_median'] / group['seconds']
    s.text(canvas, 56, top + 126, f'{group["over_1_5x_median"]} intervals over 1.5× their run\'s median', 16, s.MUTED)
    s.text(canvas, 56, top + 148, f'({long_per_s:.2f}/s in {group["seconds"]:.0f} s, {len(group["runs"])} runs); '
           f'over 25 ms: {group["over_25ms"]}', 16, s.MUTED)

    ax = axes(fig, *SEQ, top, ROW_H - 22)
    ax.set_xlim(-2, len(seq) + 1)
    ax.set_ylim(0, YMAX_MS)
    ax.axhline(1000 / 120, color=s.MUTED, linewidth=0.8, linestyle=(0, (2, 3)), zorder=1)
    ax.plot(np.arange(len(seq)), seq, color=color, linewidth=1.1, zorder=3)
    ax.scatter(np.arange(len(seq)), seq, s=5, color=color, linewidths=0, zorder=4)
    ax.set_yticks([0, 10, 20])
    ax.set_xticks([0, 50, 100, 150])
    ax.grid(axis='y', color=s.LINE, linewidth=0.6)
    style_ticks(ax)

    ax = axes(fig, *HIST, top, ROW_H - 22)
    ax.bar(bins[:-1], share, width=bins[1] - bins[0], align='edge', color=color, linewidth=0, zorder=3)
    ax.set_xlim(0, YMAX_MS)
    ax.set_ylim(0, SHARE_MAX)
    ax.axvline(1000 / 120, color=s.MUTED, linewidth=0.8, linestyle=(0, (2, 3)), zorder=2)
    ax.set_yticks([0, 20, 40])
    ax.set_yticklabels(['0', '20%', '40%'])
    ax.set_xticks([0, 5, 10, 15, 20])
    ax.grid(axis='y', color=s.LINE, linewidth=0.6)
    style_ticks(ax)


def render():
    s.setup('freefg-vrr-pacing')
    fig, canvas = s.canvas(W, H)
    c = DATA['conditions']
    s.text(canvas, 56, 56, 'Frame pacing on a VRR TV at 2×', 40, s.INK, 'bold')
    s.text(canvas, 56, 102, 'AMD BC-250  ·  LG G5 OLED TV, 2560×1440 at 120 Hz, VRR active  ·  Cyberpunk 2077 benchmark, '
           'FSR 4 Performance, native XeSS frame generation, SDR', 19, s.MUTED)
    s.text(canvas, 56, 136, 'Time between gamescope\'s display commits: under VRR the refresh follows the commits (no sooner '
           'than 8.33 ms), so even intervals mean even motion.', 19, s.MUTED)
    s.text(canvas, W - 56, 56, 'NARROWER IS BETTER', 15, s.FREEFG, 'bold', align='right')

    canvas.add_patch(Rectangle((40, 172), W - 80, 44, facecolor=s.PANEL, edgecolor='none'))
    s.text(canvas, SEQ[0], 194, 'The first 150 intervals of one run (ms)', 17, s.INK, 'bold')
    s.text(canvas, HIST[0], 194, 'All intervals: share per 0.25 ms', 17, s.INK, 'bold')
    s.text(canvas, 56, 194, '30 s per run, about the same point', 16, s.MUTED)

    groups = DATA['groups']
    canvas.add_patch(Rectangle((40, 236), W - 80, 30, facecolor=s.BG, edgecolor='none'))
    s.text(canvas, 56, 251, 'Same session, 29 Sep 2026: earlier private builds, no compute queue (as with stock Mesa)',
           16, s.CHANGE, 'bold')
    row(fig, canvas, 282, groups[0], s.WARN, 'pacing layer passing presents through')
    row(fig, canvas, 282 + ROW_H + 22, groups[1], s.INTEL, 'pacing layer presenting from the game\'s queue')
    y3 = 282 + 2 * (ROW_H + 22) + 30
    canvas.plot([56, W - 56], [y3 - 26, y3 - 26], color=s.LINE, linewidth=0.8)
    s.text(canvas, 56, y3 - 6, 'Another day and build, 18–19 Oct 2026: FreeFG 0.9.0\'s proxy, layer and shaders (placed by '
           'hand), with the test host\'s compute queue', 16, s.CHANGE, 'bold')
    row(fig, canvas, y3 + 24, groups[2], s.FREEFG, 'pacing layer holding while XeFG generates')

    foot = y3 + 24 + ROW_H + 20
    canvas.plot([56, W - 56], [foot, foot], color=s.LINE, linewidth=0.8)
    s.text(canvas, 56, foot + 26, 'Dotted line: 8.33 ms, the TV\'s shortest refresh (120 Hz). The TV\'s VRR floor is 40 Hz '
           '(25 ms). Commits: amdgpu_dm_atomic_commit_tail_begin, kernel trace.', 16, s.MUTED)
    fps = DATA['benchmark_fps']
    means = [np.mean([fps[r] for r in g['runs']]) for g in groups]
    s.text(canvas, 56, foot + 52, f'Benchmark FPS, mean of the runs: unpaced {means[0]:.2f}, paced {means[1]:.2f}, FreeFG '
           f'{means[2]:.2f}. Data: docs/data/vrr-pacing/data.json', 16, s.MUTED)
    s.check_inside(fig, W, H)
    return s.save(fig, 'vrr-pacing', 'Frame pacing on a VRR TV at 2x: unpaced, paced and FreeFG 0.9.0',
                  'Intervals between display commits on an LG G5 TV with VRR, Cyberpunk 2077 at 2x. '
                  'Source: docs/data/vrr-pacing/data.json.')


if __name__ == '__main__':
    for path in render():
        print(path.relative_to(HERE.parents[2]))
