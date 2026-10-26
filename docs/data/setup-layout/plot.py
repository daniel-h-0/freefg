#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""What Setup puts into a game folder and its launcher entry. Reads data.json beside it.

  python3 docs/data/setup-layout/plot.py      # writes docs/assets/setup-file-layout.svg and .png

The figure names each file with a short role and lists the launcher variables by name; the variables' roles and
values, the conditions on each file and the recording live in data.json and in the document text beside the figure.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # no __pycache__ beside the data
sys.path.insert(0, str(HERE.parent))
import figstyle as s  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

DATA = json.loads((HERE / 'data.json').read_text())
W, H = 1160, 916
DOWNLOAD = '#7fb2e5'
KINDS = {'package': (s.FREEFG, 'FreeFG package'),
         'download': (DOWNLOAD, 'Pinned download'),
         'settings': (s.CHANGE, 'Written by Setup'),
         'backup': (s.MUTED, 'Kept for Restore')}

# (name shown, depth, data.json path, short role); the folder BC250-XeFG/ holds only package files
TREE = [('dxgi.dll', 0, 'dxgi.dll', 'OptiScaler DLL'),
        ('OptiScaler.ini', 0, 'OptiScaler.ini', 'OptiScaler settings'),
        ('OptiScaler/', 0, 'OptiScaler/', None),
        ('amd_fidelityfx_upscaler_dx12.dll', 1, 'OptiScaler/amd_fidelityfx_upscaler_dx12.dll', 'FSR 4 or HelixSR'),
        ('libxess_fg.dll', 0, 'libxess_fg.dll', 'FreeFG proxy'),
        ('bc250_xefg_original.dll', 0, 'bc250_xefg_original.dll', 'Intel XeFG, unmodified'),
        ('libxell.dll', 0, 'libxell.dll', 'Intel XeLL, unmodified'),
        ('nvngx_dlss.dll', 0, 'nvngx_dlss.dll', 'NVIDIA DLSS'),
        ('BC250-XeFG/', 0, None, None),
        ('layer/', 1, 'BC250-XeFG/layer/', 'Pacing layer'),
        ('shaders/', 1, 'BC250-XeFG/shaders/', 'FreeFG shaders'),
        ('settings.ini', 1, 'BC250-XeFG/settings.ini', 'FreeFG settings'),
        ('.bc250-xefg-experimental/', 0, '.bc250-xefg-experimental/', 'Originals and logs')]

TOP = 128            # top of both panels
ROW = 50             # row pitch of the tree and the launcher list
NAME = 19            # file and variable names (Liberation Mono)
ROLE = 19            # roles
CHIP = 16


def chip(ax, x, y, color):
    ax.add_patch(Rectangle((x, y - CHIP / 2), CHIP, CHIP, facecolor=color, edgecolor='none', zorder=4))


def panel(ax, x0, y0, x1, y1):
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle='round,pad=0,rounding_size=10',
                                facecolor=s.PANEL, edgecolor='none', zorder=0))


def mono(ax, x, y, value, color=s.INK):
    return s.text(ax, x, y, value, NAME, color, family='Liberation Mono')


def render():
    s.setup('freefg-setup-file-layout')
    fig, ax = s.canvas(W, H)
    entries = {e['path']: e for e in DATA['entries']}
    used = {path for _, _, path, _ in TREE if path}
    assert used == set(entries), sorted(set(entries) ^ used)

    s.text(ax, 56, 62, 'Setup layout in FreeFG 1.0–1.1.0', 36, s.INK, 'bold')

    # Game folder: the file tree
    left, right, role_x = 40, 780, 548
    s.text(ax, 72, TOP + 42, 'Game folder', 22, s.INK, 'bold')
    y = TOP + 104
    parent_y = None
    for name, depth, path, role in TREE:
        x = 72 + depth * 36
        if depth:
            ax.plot([x - 26, x - 26, x - 8], [parent_y + 14, y, y], color=s.LINE, linewidth=1.4, zorder=3,
                    solid_joinstyle='miter')
        else:
            parent_y = y
        kind = entries[path]['kind'] if path else 'package'
        chip(ax, x, y, KINDS[kind][0])
        mono(ax, x + CHIP + 12, y, name)
        if role:
            s.text(ax, role_x, y, role, ROLE, s.MUTED)
        y += ROW
    bottom = y - ROW + 44
    panel(ax, left, TOP, right, bottom)

    # Launcher entry: the variables Setup adds, by name only (their roles are in the document text)
    lx = right + 30
    s.text(ax, lx + 32, TOP + 42, 'Launcher entry', 22, s.INK, 'bold')
    y = TOP + 104
    for item in DATA['launch_options_added']:
        chip(ax, lx + 32, y, KINDS['settings'][0])
        mono(ax, lx + 32 + CHIP + 12, y, item['key'])
        y += ROW
    launcher_bottom = y - ROW + 44
    panel(ax, lx, TOP, W - 40, launcher_bottom)

    # Colour key, just below the launcher panel; muted so the file names read first
    ky = launcher_bottom + 64
    for i, (color, label) in enumerate(KINDS.values()):
        chip(ax, lx + 32, ky + i * 44, color)
        s.text(ax, lx + 32 + CHIP + 12, ky + i * 44, label, ROLE, s.MUTED)

    assert bottom + 40 == H, bottom
    s.check_inside(fig, W, H)
    return s.save(fig, 'setup-file-layout', 'Historical FreeFG 1.0–1.1.0 setup layout',
                  'Files Setup places beside the game executable, where each comes from, and the launcher variables it '
                  'adds. Historical example; later releases add cache settings and shaders. Source: docs/data/setup-layout/data.json.')


if __name__ == '__main__':
    for path in render():
        print(path.relative_to(HERE.parents[2]))
