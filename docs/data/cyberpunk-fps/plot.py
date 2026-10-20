#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Cyberpunk 2077 at 2x: FreeFG against XeFG with Intel's shaders, headless and on a TV. Reads data.json beside it.

  python3 docs/data/cyberpunk-fps/plot.py      # writes docs/assets/cyberpunk-2x-fps.svg and .png
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ beside the data
sys.path.insert(0, str(HERE.parent))
import figstyle as s  # noqa: E402

DATA = json.loads((HERE / 'data.json').read_text())
W, H = 1600, 1016
X0, PER_FPS = 470, 7.6          # bar origin and scale (design pixels per FPS)
BAR = 40


def x(fps):
    return X0 + fps * PER_FPS


def date(iso):
    months = {'09': 'Sep', '10': 'Oct'}
    year, month, day = iso.split('-')[:3]
    return f'{int(day)} {months[month]} {year}'


def row(ax, y, name, detail, arm, color):
    runs = [r['fps'] for r in arm['runs']]
    mean = arm['fps_mean']
    s.text(ax, 56, y + 2, name, 23, s.INK, 'bold')
    s.text(ax, 56, y + 32, detail, 17, s.MUTED)
    ax.add_patch(s.matplotlib.patches.Rectangle((X0, y - BAR / 2 + 4), mean * PER_FPS, BAR, facecolor=color,
                                                edgecolor='none', zorder=3))
    s.text(ax, x(mean) - 12, y + 4, f'{mean:.2f}', 24, s.BG, 'bold', 'right', zorder=4)
    spread = f'{min(runs):.2f}–{max(runs):.2f}' if len(runs) > 1 else f'{runs[0]:.2f}'
    s.text(ax, X0, y + 42, f'{arm["game_fps_mean"]:.1f} game frames/s  ·  {1000 / mean:.2f} ms per shown frame  ·  '
           f'{len(runs)} runs, {spread} FPS', 16, s.MUTED, zorder=4).set_bbox(dict(facecolor=s.BG, edgecolor='none', pad=1))
    return mean


def axis(ax, top, bottom):
    for fps in range(0, 121, 20):
        ax.plot([x(fps), x(fps)], [top, bottom], color=s.LINE, linewidth=0.7, zorder=1)
        s.text(ax, x(fps), bottom + 16, f'{fps}', 15, s.FAINT, align='center')
    s.text(ax, x(120) + 26, bottom + 16, 'FPS', 15, s.FAINT)


def header(ax, y, title, when):
    ax.add_patch(s.matplotlib.patches.Rectangle((40, y - 26), W - 80, 52, facecolor=s.PANEL, edgecolor='none'))
    s.text(ax, 56, y, title, 21, s.INK, 'bold')
    s.text(ax, W - 56, y, when, 18, s.MUTED, align='right')


def render():
    s.setup('freefg-cyberpunk-2x-fps')
    fig, ax = s.canvas(W, H)
    c = DATA['conditions']
    hl, tv = DATA['headless'], DATA['tv']
    s.text(ax, 56, 56, 'Cyberpunk 2077 at 2×: frames per second', 40, s.INK, 'bold')
    s.text(ax, 56, 102, f'AMD BC-250  ·  {c["output"].replace("x", "×")}  ·  {c["upscaler"]}  ·  native XeSS frame '
           f'generation  ·  ray tracing {c["ray_tracing"]}  ·  built-in benchmark, game {c["game"].split()[2].rstrip(",")}',
           19, s.MUTED)
    s.text(ax, W - 56, 56, 'HIGHER IS BETTER', 15, s.FREEFG, 'bold', 'right')

    header(ax, 168, 'Headless: no display, gamescope at a fixed 120 Hz',
           f'{date(hl["dates"]["intel_sdr"])} and {date(hl["dates"]["freefg"])}')
    rows = [(238, 'XeFG, Intel\'s shaders', f'SDR  ·  {date(hl["dates"]["intel_sdr"])}', hl['intel_sdr'], s.INTEL),
            (334, 'FreeFG', f'SDR  ·  {date(hl["dates"]["freefg"])}', hl['freefg_sdr'], s.FREEFG),
            (430, 'FreeFG', f'HDR10  ·  {date(hl["dates"]["freefg"])}', hl['freefg_hdr10'], s.FREEFG)]
    axis(ax, 205, 486)
    means = [row(ax, *r) for r in rows]
    # The Intel level carried down onto the FreeFG bar, and the change between them.
    ax.plot([x(means[0]), x(means[0])], [238 + BAR / 2 + 4, 334 - BAR / 2 + 4], color=s.CHANGE, linewidth=1.2,
            linestyle=(0, (3, 3)), zorder=5)
    bridge = hl['bridge']
    moved = (bridge['reference_2026_10_16']['fps_mean'] / bridge['reference_2026_10_15']['fps_mean'] - 1) * 100
    change = (means[1] / means[0] - 1) * 100
    s.text(ax, x(means[1]) + 18, 324, f'+{change:.1f}%', 28, s.CHANGE, 'bold')
    for dy, line in ((354, 'measured a day apart; a reference'), (374, 'build run on both days moved ' +
                                                                         f'{moved:+.2f}%'.replace('-', '−'))):
        s.text(ax, x(means[1]) + 18, dy, line, 15, s.MUTED, zorder=4).set_bbox(
            dict(facecolor=s.BG, edgecolor='none', pad=1))
    s.text(ax, 56, 538, 'HDR10 with Intel\'s shaders: not measured.', 16, s.FAINT)

    header(ax, 600, 'On a TV with VRR: LG G5 OLED, 2560×1440 at 120 Hz, VRR active in every run',
           tv['dates'].replace('2026-10-18/19', '18–19 Oct 2026'))
    axis(ax, 637, 822)
    row(ax, 670, 'FreeFG', 'SDR', tv['freefg_sdr'], s.FREEFG)
    row(ax, 766, 'FreeFG', 'HDR10', tv['freefg_hdr10'], s.FREEFG)
    s.text(ax, 56, 872, 'Intel\'s shaders were not measured on the TV with this build. Headless and TV figures are '
           'not comparable with each other.', 16, s.FAINT)

    ax.plot([56, W - 56], [904, 904], color=s.LINE, linewidth=0.8)
    s.text(ax, 56, 930, 'FPS: the benchmark\'s average, generated frames included. Game frames/s: frames the game itself '
           'rendered (half the shown frames at 2×). Bars: mean of the runs.', 16, s.MUTED)
    loader = (hl['freefg_sdr']['fps_mean'] / bridge['reference_2026_10_16']['fps_mean'] - 1) * 100
    s.text(ax, 56, 958, f'FreeFG 0.9.0: proxy {c["proxy_sha256"][:8]}, pacing layer {c["layer_sha256"][:8]}. Intel\'s '
           'shaders: an internal build with its acceleration off, same harness and layer; its internal loader', 16,
           s.MUTED)
    s.text(ax, 56, 984, f'measured {loader:.2f}% slower than FreeFG\'s, both running FreeFG\'s shaders (16 Oct). Data: '
           'docs/data/cyberpunk-fps/data.json', 16, s.MUTED)
    s.check_inside(fig, W, H)
    return s.save(fig, 'cyberpunk-2x-fps', 'Cyberpunk 2077 at 2x on the AMD BC-250: FreeFG and XeFG with Intel\'s shaders',
                  'Benchmark FPS, 2560x1440, FSR 4 Performance, native XeSS frame generation at 2x; headless and on a TV '
                  'with VRR. Source: docs/data/cyberpunk-fps/data.json.')


if __name__ == '__main__':
    for path in render():
        print(path.relative_to(HERE.parents[2]))
