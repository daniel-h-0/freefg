#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""GPU time of one generated frame by stage: XeFG with Intel's shaders against FreeFG. Reads data.json beside it.

  python3 docs/data/gpu-time/plot.py      # writes docs/assets/gpu-time-per-generated-frame.svg and .png
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
W, H = 1600, 1040
X0, PER_MS = 560, 92.0


def x(ms):
    return X0 + ms * PER_MS


def bar(ax, y, ms, height, color, start=0.0, alpha=1.0, hatch=None):
    ax.add_patch(Rectangle((x(start), y - height / 2), ms * PER_MS, height, facecolor=color, edgecolor='none',
                           alpha=alpha, hatch=hatch, zorder=3))


def label_box(artist):
    artist.set_bbox(dict(facecolor=s.BG, edgecolor='none', pad=1))
    return artist


def render():
    s.setup('freefg-gpu-time-per-generated-frame')
    fig, ax = s.canvas(W, H)
    t, stages = DATA['totals'], DATA['stages']
    s.text(ax, 56, 56, 'GPU time per generated frame', 40, s.INK, 'bold')
    s.text(ax, 56, 102, 'AMD BC-250  ·  XeFG at 2×  ·  output 2560×1440 SDR  ·  engine motion vectors  ·  GPU timestamps '
           'around every dispatch  ·  headless test program', 19, s.MUTED)
    s.text(ax, W - 56, 56, 'LOWER IS BETTER', 15, s.FREEFG, 'bold', 'right')

    for ms in range(0, 11):
        ax.plot([x(ms), x(ms)], [156, 852], color=s.LINE, linewidth=0.7, zorder=1)
        s.text(ax, x(ms), 868, f'{ms}', 15, s.FAINT, align='center')
    s.text(ax, x(10) + 26, 868, 'ms', 15, s.FAINT)

    # Totals: Intel's shaders, and FreeFG split into its own shaders and the passes it leaves to Intel's.
    s.text(ax, 56, 182, 'XeFG, Intel\'s shaders', 23, s.INK, 'bold')
    s.text(ax, 56, 210, 'all of the frame-generation graph', 16, s.MUTED)
    bar(ax, 192, t['intel_ms'], 44, s.INTEL)
    s.text(ax, x(t['intel_ms']) - 12, 194, f'{t["intel_ms"]:.2f} ms', 24, s.BG, 'bold', 'right', zorder=4)
    s.text(ax, 56, 262, 'FreeFG', 23, s.INK, 'bold')
    s.text(ax, 56, 290, 'its own shaders + Intel\'s for the rest', 16, s.MUTED)
    bar(ax, 272, t['freefg_own_ms'], 44, s.FREEFG)
    bar(ax, 272, t['freefg_intel_ms'], 44, s.INTEL, start=t['freefg_own_ms'], alpha=0.45)
    s.text(ax, x(t['freefg_own_ms']) - 10, 274, f'{t["freefg_own_ms"]:.2f}', 20, s.BG, 'bold', 'right', zorder=4)
    s.text(ax, x(t['freefg_ms']) - 10, 274, f'{t["freefg_intel_ms"]:.2f}', 20, s.INK, 'bold', 'right', zorder=4)
    s.text(ax, x(t['freefg_ms']) + 14, 274, f'{t["freefg_ms"]:.2f} ms', 24, s.INK, 'bold', zorder=4)
    label_box(s.text(ax, x(t['freefg_ms']) + 128, 262, f'−{t["saved_in_replaced_stages_ms"]:.1f} ms in the stages FreeFG replaces', 22, s.CHANGE,
                     'bold', zorder=4))
    cross = DATA['cross_check']
    label_box(s.text(ax, x(t['freefg_ms']) + 128, 290, f'Cyberpunk 2077, headless: {cross["intel_fps"]:.2f} → '
                     f'{cross["freefg_fps"]:.2f} FPS ({cross["measured_change_percent"]:+.1f}%)', 16, s.MUTED, zorder=4))

    ax.add_patch(Rectangle((40, 322), W - 80, 40, facecolor=s.PANEL, edgecolor='none', zorder=2))
    s.text(ax, 56, 342, 'By stage', 19, s.INK, 'bold', zorder=4)
    ax.add_patch(Rectangle((X0, 334), 16, 16, facecolor=s.INTEL, edgecolor='none', zorder=4))
    s.text(ax, X0 + 24, 342, 'upper bar: XeFG, Intel\'s shaders', 17, s.MUTED, zorder=4)
    ax.add_patch(Rectangle((X0 + 300, 334), 16, 16, facecolor=s.FREEFG, edgecolor='none', zorder=4))
    s.text(ax, X0 + 324, 342, 'lower bar: FreeFG\'s own shaders', 17, s.MUTED, zorder=4)
    ax.add_patch(Rectangle((X0 + 580, 334), 16, 16, facecolor=s.INTEL, alpha=0.45, edgecolor='none', zorder=4))
    s.text(ax, X0 + 604, 342, 'FreeFG, Intel\'s shader kept', 17, s.MUTED, zorder=4)

    y = 410
    for stage in stages:
        own = stage['freefg_runs'] == 'own shaders'
        s.text(ax, 56, y - 6, stage['stage'], 20, s.INK, 'bold')
        s.text(ax, 56, y + 20, 'FreeFG runs its own shaders' if own else ('Intel\'s shader in both' if stage['intel_shader_count'] == 1 else 'Intel\'s shaders in both'), 16,
               s.FREEFG if own else s.MUTED)
        bar(ax, y - 12, stage['intel_ms'], 20, s.INTEL)
        bar(ax, y + 12, stage['freefg_ms'], 20, s.FREEFG if own else s.INTEL, alpha=1.0 if own else 0.45)
        label_box(s.text(ax, x(stage['intel_ms']) + 10, y - 12, f'{stage["intel_ms"]:.2f}', 16, s.MUTED, zorder=4))
        value = f'{stage["freefg_ms"]:.2f}'
        if own:
            value += f'   {stage["intel_ms"] / stage["freefg_ms"]:.1f}× faster'
        label_box(s.text(ax, x(stage['freefg_ms']) + 10, y + 12, value, 16, s.FREEFG if own else s.MUTED,
                         'bold' if own else 'regular', zorder=4))
        y += 74

    ax.plot([56, W - 56], [900, 900], color=s.LINE, linewidth=0.8)
    c = DATA['conditions']
    gaps = sorted(t['gaps_between_dispatches_ms'].values())
    s.text(ax, 56, 926, 'Two runs, not one session, and the inputs differ. Intel\'s shaders: Intel\'s runtime alone, 180 '
           'generated frames of replayed game inputs at 2560×1440, 27 Sep 2026.', 16, s.MUTED)
    s.text(ax, 56, 952, 'FreeFG: the released proxy, 3 runs × 220 frames of a synthetic scene with 1280×720 inputs, 18 Oct '
           '2026. So the stages left to Intel\'s shaders differ between the bars', 16, s.MUTED)
    s.text(ax, 56, 978, f'(the motion splat most), and the total gap includes {t["kept_stages_difference_ms"]:.2f} ms of that. '
           'The reference used another of Intel\'s warp variants (same grid). Data: docs/data/gpu-time/data.json', 16,
           s.MUTED)
    s.text(ax, 56, 1004, 'Intel\'s flow layers are matched to FreeFG\'s by dispatch grid and call count. Sums of dispatch '
           f'times; the gaps between dispatches ({gaps[0]:.2f}–{gaps[1]:.2f} ms) are not included.', 16, s.MUTED)
    s.check_inside(fig, W, H)
    return s.save(fig, 'gpu-time-per-generated-frame', 'GPU time per generated frame on the AMD BC-250, by stage',
                  'XeFG at 2x, output 2560x1440 SDR: Intel\'s shaders against FreeFG, stage by stage, from two runs '
                  'with different inputs. Source: docs/data/gpu-time/data.json.')


if __name__ == '__main__':
    for path in render():
        print(path.relative_to(HERE.parents[2]))
