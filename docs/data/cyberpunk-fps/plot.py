#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Cyberpunk 2077 benchmark frame rate as horizontal bars. Reads data.json beside it.

  python3 docs/data/cyberpunk-fps/plot.py      # writes docs/assets/cyberpunk-2x-fps.svg and .png

Everything drawn comes from data.json's "plot" entry, so a new measurement is an edit of data.json only:
  title, subtitle  one line each
  unit             the axis unit
  bars             in drawing order: id, label, group, role ("intel" or "freefg": the colour) and the value, either
                   value_from (a dotted path into data.json, such as "headless.freefg_sdr.fps_mean") or value (a number)
  differences      {"from": id, "to": id, "digits": 1}: the change from one bar to another, printed beside "to"
Bars of one group are drawn together; group names are printed only when there is more than one group.
Caveats (dates, run counts, cross-day comparisons) belong in MEASUREMENTS.md, not in the image.
"""
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ beside the data
sys.path.insert(0, str(HERE.parent))
import figstyle as s  # noqa: E402

DATA = json.loads((HERE / 'data.json').read_text())
PLOT = DATA['plot']
ROLES = {'intel': s.INTEL, 'freefg': s.FREEFG}

W = 1200
LEFT = 56                 # left margin of title and labels
PLOT_RIGHT = W - 130      # the axis maximum; the unit sits to its right
TOP = 168                 # first bar row starts here
ROW, BAR = 84, 46         # row pitch and bar thickness
GROUP_HEAD, GROUP_GAP = 40, 20
NOTE_GAP = 18             # between a bar's end and its difference


def value(bar):
    if 'value' in bar:
        return float(bar['value'])
    node = DATA
    for key in bar['value_from'].split('.'):
        node = node[key]
    if not isinstance(node, (int, float)):
        raise SystemExit(f'{bar["value_from"]} is not a number')
    return float(node)


def signed(number, digits):
    return f'{number:+.{digits}f}'.replace('-', '−')


def layout(bars):
    """Centre line of every bar, the y of every group name (only with several groups) and the bottom of the rows."""
    groups = list(dict.fromkeys(b['group'] for b in bars))
    heads, centres, y = [], {}, TOP
    for n, group in enumerate(groups):
        if len(groups) > 1:
            y += GROUP_GAP if n else 0
            heads.append((y + GROUP_HEAD - 4, group))  # close above its first bar
            y += GROUP_HEAD
        for b in (b for b in bars if b['group'] == group):
            centres[b['id']] = y + ROW / 2
            y += ROW
    return heads, centres, y


def difference(d, values):
    return signed((values[d['to']] / values[d['from']] - 1) * 100, d.get('digits', 1)) + '%'


def render():
    s.setup('freefg-cyberpunk-2x-fps')
    bars, differences = PLOT['bars'], PLOT.get('differences', [])
    values = {b['id']: value(b) for b in bars}
    heads, centres, bottom = layout(bars)
    H = int(bottom + 78)
    fig, ax = s.canvas(W, H)

    s.text(ax, LEFT, 62, PLOT['title'], 36, s.INK, 'bold')
    s.text(ax, LEFT, 106, PLOT['subtitle'], 20, s.MUTED)
    for y, group in heads:
        s.text(ax, LEFT, y, group, 18, s.MUTED)
    labels = [s.text(ax, LEFT, centres[b['id']], b['label'], 22, s.INK, 'bold') for b in bars]
    notes = {d['to']: s.text(ax, 0, 0, difference(d, values), 22, s.CHANGE, 'bold') for d in differences}

    # The bars start right of the longest label; the scale leaves room for each difference beside its bar.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    x0 = LEFT + max(t.get_window_extent(renderer).width for t in labels) + 36
    step = 20 if max(values.values()) <= 60 else 40
    top_value = step * math.ceil(max(values.values()) / step)
    scale = min([(PLOT_RIGHT - x0) / top_value] +
                [(W - LEFT - x0 - NOTE_GAP - t.get_window_extent(renderer).width) / values[i]
                 for i, t in notes.items()])

    def x(v):
        return x0 + v * scale

    # A zero line and tick values below the rows; the bars carry their own values, so no grid.
    rows_top, rows_bottom = TOP - 8, bottom + 8
    ax.plot([x0, x0], [rows_top, rows_bottom], color=s.LINE, linewidth=1.0, zorder=1)
    for tick in range(0, top_value + 1, step):
        s.text(ax, x(tick), rows_bottom + 22, f'{tick}', 16, s.FAINT, align='center')
    s.text(ax, x(top_value) + 22, rows_bottom + 22, PLOT['unit'], 18, s.MUTED)

    ends = {}
    for b in bars:
        y, v = centres[b['id']], values[b['id']]
        ax.add_patch(s.matplotlib.patches.Rectangle((x0, y - BAR / 2), v * scale, BAR, facecolor=ROLES[b['role']],
                                                    edgecolor='none', zorder=3))
        if v * scale > 130:
            s.text(ax, x(v) - 14, y + 1, f'{v:.2f}', 22, s.BG, 'bold', 'right', zorder=4)
            ends[b['id']] = x(v)
        else:
            label = s.text(ax, x(v) + 14, y + 1, f'{v:.2f}', 22, s.INK, 'bold', zorder=4)
            ends[b['id']] = x(v) + 14 + label.get_window_extent(renderer).width

    # Each difference sits beside its "to" bar, at the size of the bar values.
    for d in differences:
        b = d['to']
        notes[b].set_position((ends[b] + NOTE_GAP, centres[b] + 1))
        notes[b].set_zorder(4)

    s.check_inside(fig, W, H)
    description = '; '.join(f'{b["group"]} {b["label"]}: {values[b["id"]]:.2f} {PLOT["unit"]}' for b in bars)
    description += ''.join(f'; {b["group"]} {difference(d, values)}' for d in differences
                           for b in bars if b['id'] == d['to'])
    return s.save(fig, DATA['figure'], plain(PLOT['title']),
                  plain(f'{PLOT["subtitle"]}. {description}. Source: docs/data/cyberpunk-fps/data.json.'))


def plain(text):
    """Metadata in plain characters."""
    for old, new in (('×', 'x'), ('  ·  ', ', '), ('−', '-')):
        text = text.replace(old, new)
    return text


if __name__ == '__main__':
    for path in render():
        print(path.relative_to(HERE.parents[2]))
