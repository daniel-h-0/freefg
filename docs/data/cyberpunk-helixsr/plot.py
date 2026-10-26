#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Cyberpunk/HelixSR output, rendering rate and derived FG cost, from data.json.

The two static layouts share data and scales. Higher-factor categories explicitly
identify the separate, unofficial MFG Unlocker route. Cost is throughput-derived,
not a GPU timestamp or input-latency measurement.
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE.parent))
import figstyle as s  # noqa: E402

D = json.loads((HERE / 'data.json').read_text())
ORDER = ('off', 'i2', 'f2', 'i3', 'f3', 'i4', 'f4')


def factor(arm):
    return 1 if arm == 'off' else int(arm[1:])


def added_cost(row, baseline):
    """Added ms per generated frame, calculated from unrounded game FPS means."""
    m = factor(row['arm'])
    if m == 1:
        return None
    return (1000 / row['game_fps']['mean'] - 1000 / baseline['game_fps']['mean']) / (m - 1)


def label(fig, ax, x, y, value, size, unofficial=False):
    main = s.text(ax, x, y, value, size, s.INK, 'bold')
    if unofficial:
        # Place the superscript after the measured label, independent of font width.
        fig.canvas.draw()
        box = main.get_window_extent(fig.canvas.get_renderer())
        end = ax.transData.inverted().transform((box.x1, box.y1))[0]
        s.text(ax, end + 3, y - 10, '(unofficial)', 12, s.MUTED)


def render(narrow=False):
    s.setup('freefg-cyberpunk-helixsr' + ('-narrow' if narrow else ''))
    arms = [a for a in ORDER if any(r['arm'] == a for r in D['conditions'])]
    assert all(sum(r['arm'] == a and r['range'] == group for r in D['conditions']) == 1
               for a in arms for group in ('sdr', 'hdr'))
    row_pitch = 100 if narrow else 70
    group_pitch = 68 + len(arms) * row_pitch
    axis_y = 184 + group_pitch + 48 + (len(arms) - 1) * row_pitch + (57 if narrow else 40)
    footer_y = axis_y + 58
    W = 540 if narrow else 1240
    H = footer_y + (260 if narrow else 178)
    left = 24 if narrow else 48
    x0, right = (24, 164) if narrow else (350, 762)
    out_x, game_x, cost_x = (282, 398, 516) if narrow else (904, 1040, 1192)
    fig, ax = s.canvas(W, H)
    s.text(ax, left, 49, f"FreeFG {D['freefg']['version']} with HelixSR", 28 if narrow else 36, s.INK, 'bold')
    subtitle = f"Cyberpunk 2077 {D['game']['version_label']} · AMD BC-250 · 1440p Quality"
    s.text(ax, left, 94, subtitle, 16 if narrow else 22, s.MUTED)
    s.text(ax, left, 128, 'Output = rendered + generated; game FPS = rendering.' if narrow else
           'Output includes generated frames; game FPS measures rendering.', 17 if narrow else 21, s.MUTED)
    maximum = max(r['output_fps']['ci95'][1] for r in D['conditions'])
    step = 40 if maximum >= 150 else 20
    ceiling = math.ceil(maximum / step) * step
    scale = (right - x0) / ceiling
    description = []
    for gi, (group_name, group) in enumerate((('SDR', 'sdr'), ('HDR10', 'hdr'))):
        top = 184 + gi * group_pitch
        s.text(ax, left, top, group_name, 23, s.INK, 'bold')
        for x, text in ((out_x, 'Output FPS'), (game_x, 'Game FPS'), (cost_x, 'Cost ms / FG')):
            s.text(ax, x, top, text, 16 if narrow else 20, s.MUTED, align='right')
        selected = {r['arm']: r for r in D['conditions'] if r['range'] == group}
        for i, arm in enumerate(arms):
            row = selected[arm]
            y = top + 48 + i * row_pitch
            v, g = row['output_fps']['mean'], row['game_fps']['mean']
            lo, hi = row['output_fps']['ci95']
            m = factor(arm)
            color = s.CHANGE if arm == 'off' else s.INTEL if arm.startswith('i') else s.FREEFG
            name = 'No FG' if arm == 'off' else ('Intel XeFG ' if arm.startswith('i') else 'FreeFG ') + f'{m}×'
            label(fig, ax, left, y - 14 if narrow else y - 3, name, 23 if narrow else 24, m > 2)
            if arm == 'off':
                s.text(ax, cost_x if narrow else left, y - 14 if narrow else y + 22,
                       'No generated frames', 16 if narrow else 18, s.MUTED, align='right' if narrow else 'left')
            elif arm.startswith('f'):
                gain = (v / selected['i' + str(m)]['output_fps']['mean'] - 1) * 100
                s.text(ax, cost_x if narrow else left, y - 14 if narrow else y + 22,
                       f'{gain:+.1f}% vs Intel at {m}×', 16 if narrow else 18, s.FREEFG,
                       align='right' if narrow else 'left')
            y += 22 if narrow else 0
            ax.barh(y, v * scale, height=28, left=x0, color=color, edgecolor='none', zorder=3)
            ax.errorbar(x0 + v * scale, y, xerr=[[max(0, v - lo) * scale], [max(0, hi - v) * scale]],
                        fmt='none', ecolor=s.INK, elinewidth=1.4, capsize=4, zorder=4)
            cost = added_cost(row, selected['off'])
            for x, value, tint in ((out_x, f'{v:.1f}', color), (game_x, f'{g:.1f}', s.INK),
                                    (cost_x, '—' if cost is None else f'{cost:.2f}', color)):
                s.text(ax, x, y, value, 26 if narrow else 28, tint, 'bold', align='right')
            description.append(f"{group_name}, {name}{' (unofficial)' if m > 2 else ''}: output {v:.2f} FPS "
                               f"(95% CI {lo:.2f}–{hi:.2f}), game {g:.2f} FPS, n={row['n']}" +
                               (f', derived cost {cost:.3f} ms per generated frame' if cost is not None else ''))
        # In the compact layout labels sit above each bar; a full vertical spine would cross them.
        if not narrow:
            ax.plot([x0, x0], [top + 26, top + 48 + (len(arms) - 1) * row_pitch + 20], color=s.LINE, linewidth=1)
    for tick in range(0, ceiling + 1, step):
        x = x0 + tick * scale
        ax.plot([x, x], [axis_y - 6, axis_y - 2], color=s.LINE, linewidth=1)
        s.text(ax, x, axis_y + 13, str(tick), 15 if narrow else 17, s.MUTED,
               align='left' if narrow and tick == 0 else 'center')
    if narrow:
        foot = [f"{D['method']['runs_per_condition']} runs per condition · whiskers: 95% CI across runs",
                'ms / FG = (1000 / game FPS − 1000 / no-FG FPS)',
                'divided by (factor − 1). Derived added time; lower is faster.',
                '3×/4× (unofficial): separate MFG Unlocker 1.6.0',
                'with XeFGModel=default · DLSS FG input → XeFG',
                'High, RT off · 1706×960 → 2560×1440 · headless 240 Hz',
                f"HelixSR {D['upscaler']['version']} · reactive mask off · warm caches",
                f"Measured {D['date_label']}"]
    else:
        foot = [f"{D['method']['runs_per_condition']} runs per condition · whiskers: 95% CI across runs · output/game FPS: higher is faster",
                'ms / FG = (1000 / game FPS − 1000 / no-FG FPS) / (factor − 1); lower is faster. Derived, not GPU timing.',
                '3×/4× (unofficial): separate MFG Unlocker 1.6.0 with XeFGModel=default',
                'High, ray tracing off · 1706×960 → 2560×1440 · DLSS FG input → XeFG · headless 240 Hz',
                f"HelixSR {D['upscaler']['version']} · reactive mask off · warm caches · measured {D['date_label']}"]
    for i, line in enumerate(foot):
        s.text(ax, left, footer_y + i * 26, line, 15 if narrow else 18, s.MUTED)
    s.check_inside(fig, W, H, margin=24)
    stem = 'cyberpunk-helixsr-fps' + ('-narrow' if narrow else '')
    return s.save(fig, stem, f"FreeFG {D['freefg']['version']} with HelixSR — Cyberpunk 2077",
                  subtitle + '. ' + '; '.join(description) + '. ' + '. '.join(foot) +
                  '. Source: docs/data/cyberpunk-helixsr/data.json.')


if __name__ == '__main__':
    for narrow in (False, True):
        for path in render(narrow):
            print(path)
