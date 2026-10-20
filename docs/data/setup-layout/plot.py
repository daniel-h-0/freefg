#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""What Setup puts into a game folder and its launcher entry. Reads data.json beside it.

  python3 docs/data/setup-layout/plot.py      # writes docs/assets/setup-file-layout.svg and .png
"""
import json
import sys
import textwrap
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ beside the data
sys.path.insert(0, str(HERE.parent))
import figstyle as s  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

DATA = json.loads((HERE / 'data.json').read_text())
W, H = 1600, 1110
DOWNLOAD = '#7fb2e5'
KINDS = {'package': (s.FREEFG, 'from the FreeFG package'),
         'download': (DOWNLOAD, 'pinned download, checked by SHA-256'),
         'settings': (s.CHANGE, 'written by Setup'),
         'backup': (s.MUTED, 'kept for Restore'),
         'unchanged': (s.FAINT, 'the game\'s own, or a folder')}
ROW = 46


def chip(ax, x, y, color):
    ax.add_patch(Rectangle((x, y - 8), 16, 16, facecolor=color, edgecolor='none', zorder=4))


def mono(ax, x, y, value, size=18, color=s.INK, weight='regular'):
    return s.text(ax, x, y, value, size, color, weight, family='Liberation Mono')


def render():
    s.setup('freefg-setup-file-layout')
    fig, ax = s.canvas(W, H)
    entries = {e['path']: e for e in DATA['entries']}
    s.text(ax, 56, 56, 'What Setup changes in a game', 40, s.INK, 'bold')
    s.text(ax, 56, 102, 'FreeFG 1.0.0 on the AMD BC-250  ·  one game folder and its launcher entry  ·  Restore takes it '
           'out again', 19, s.MUTED)
    s.text(ax, 56, 136, 'Recorded in a live install of 0.9.0 on 19 Oct 2026 (Echo Point Nova, Steam, OptiFG input); 1.0.0 adds '
           'five shaders. File roles from the package manifest and the pinned downloads.', 17, s.FAINT)

    # Game folder
    left, right = 40, 1000
    s.text(ax, 64, 204, 'Game folder', 22, s.INK, 'bold')
    s.text(ax, 220, 205, 'the folder of the game\'s rendering .exe', 17, s.MUTED)
    rows = [('Game.exe', 0, None, 'the game itself, not changed', None),
            ('dxgi.dll', 0, 'dxgi.dll', None, None),
            ('OptiScaler.ini', 0, 'OptiScaler.ini', None, None),
            ('OptiScaler/', 0, 'OptiScaler/', None, None),
            ('amd_fidelityfx_upscaler_dx12.dll', 1, 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll', None, None),
            ('libxess_fg.dll', 0, 'libxess_fg.dll', None, None),
            ('bc250_xefg_original.dll', 0, 'bc250_xefg_original.dll', None, None),
            ('libxell.dll', 0, 'libxell.dll', None, None),
            ('nvngx_dlss.dll', 0, 'nvngx_dlss.dll', None, None),
            ('BC250-XeFG/', 0, None, 'FreeFG\'s folder', None),
            ('layer/', 1, 'BC250-XeFG/layer/', None, None),
            ('shaders/', 1, 'BC250-XeFG/shaders/', None, None),
            ('settings.ini', 1, 'BC250-XeFG/settings.ini', None, None),
            ('.bc250-xefg-experimental/', 0, '.bc250-xefg-experimental/', None, None)]
    used = {key for _, _, key, _, _ in rows if key}
    assert used == set(entries), sorted(set(entries) ^ used)
    y = 262
    previous = y
    for name, depth, key, fallback, _ in rows:
        x = 64 + depth * 34
        if depth:
            ax.plot([x - 20, x - 20, x - 6], [previous + 12, y, y], color=s.LINE, linewidth=1.2, zorder=3)
        entry = entries.get(key) if key else None
        color = KINDS[entry['kind']][0] if entry else KINDS['unchanged'][0]
        chip(ax, x, y, color)
        mono(ax, x + 26, y, name, 18, s.INK if entry else s.MUTED, 'bold' if entry and entry['kind'] == 'package' else 'regular')
        what = textwrap.wrap(entry['what'] if entry else fallback, 60)
        note = textwrap.wrap(entry['note'], 68) if entry and entry.get('note') else []
        lines = [(line, 16, s.INK if entry else s.MUTED) for line in what] + [(line, 14, s.FAINT) for line in note]
        for i, (line, size, tone) in enumerate(lines):
            s.text(ax, 520, y + i * 20, line, size, tone)
        previous = y
        y += ROW + 20 * (len(lines) - 1)
    folder_bottom = y - ROW + 30
    ax.add_patch(FancyBboxPatch((left, 172), right - left, folder_bottom - 172, boxstyle='round,pad=0,rounding_size=10',
                                facecolor=s.PANEL, edgecolor='none', zorder=0))

    # Launcher entry
    lx = 1030
    ax.add_patch(FancyBboxPatch((lx, 172), W - 40 - lx, 560, boxstyle='round,pad=0,rounding_size=10',
                                facecolor=s.PANEL, edgecolor='none'))
    s.text(ax, lx + 24, 204, 'Launcher entry', 22, s.INK, 'bold')
    s.text(ax, lx + 24, 234, 'Steam launch options, or the game\'s environment', 15, s.MUTED)
    s.text(ax, lx + 24, 254, 'in Heroic or Lutris; your own options stay', 15, s.MUTED)
    y = 300
    for item in DATA['launch_options_added']:
        chip(ax, lx + 24, y, s.CHANGE)
        mono(ax, lx + 50, y, item['key'], 17, s.INK, 'bold')
        mono(ax, lx + 50, y + 24, item['value'], 14, s.CHANGE)
        s.text(ax, lx + 50, y + 46, item['what'], 14, s.MUTED)
        y += 86

    # Key
    ky = 772
    s.text(ax, lx + 24, ky, 'Where each file comes from', 18, s.INK, 'bold')
    for i, (kind, (color, label)) in enumerate(KINDS.items()):
        chip(ax, lx + 24, ky + 36 + i * 30, color)
        s.text(ax, lx + 50, ky + 36 + i * 30, label, 15, s.MUTED)
    s.text(ax, lx + 24, ky + 202, 'Example values: this game\'s OptiScaler', 15, s.FAINT)
    s.text(ax, lx + 24, ky + 224, 'is winmm.dll; <game folder> stands for', 15, s.FAINT)
    s.text(ax, lx + 24, ky + 246, 'the folder\'s full path.', 15, s.FAINT)

    assert folder_bottom + 50 < H, folder_bottom
    s.text(ax, 56, H - 30, 'Restore copies back every file Setup replaced, deletes what it added and removes its launcher '
           'settings; a file a game update changed since is kept. Data: docs/data/setup-layout/data.json', 15, s.MUTED)
    s.check_inside(fig, W, H)
    return s.save(fig, 'setup-file-layout', 'What FreeFG Setup changes in a game folder and launcher entry',
                  'Files Setup places beside the game executable, where each comes from, and the launcher variables it '
                  'adds; recorded in a live install. Source: docs/data/setup-layout/data.json.')


if __name__ == '__main__':
    for path in render():
        print(path.relative_to(HERE.parents[2]))
