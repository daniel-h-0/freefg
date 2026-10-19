#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install an assembled package into a throwaway game folder and restore it again, offline.

The package's own install.py runs as Setup would (fresh OptiScaler setup, OptiFG on the upscaler input) against:
  - a fake 64-bit game executable in a new temporary folder,
  - a temporary HOME with one Heroic (GOG) entry for it, which receives the launcher settings,
  - a prepared dependency directory (--deps): every file of the dependencies.json groups the install needs, by name,
    for example <XDG_CACHE_HOME>/bc250-xefg-testers/payload after a Setup run. Nothing is downloaded.
Launchers and caches of this machine are neither read nor changed: HOME and XDG_CACHE_HOME point into the temporary
folder, and the installer's running-launcher check is skipped (the fixture's launcher entry is not a real launcher).

Checks: every file the package must not carry (package.json never_ship) is installed from the pinned downloads with
the bytes the package used to carry, and Restore returns the game folder to its original contents.
--compare-with PACKAGE installs another package (for example the previous tester) the same way and lists the files
whose presence or bytes differ. --variant NAME checks a package.json variant (its own never_ship rules); for the
enabler-free one (intel-free-2x) also that the package's libxess_fg.dll proxy is what the game folder gets and that
nothing of the XeSSMFG enabler is installed.

  python3 release/smoke_install.py --deps ~/.cache/bc250-xefg-testers/payload [--compare-with OTHER_PACKAGE]
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

RELEASE = Path(__file__).resolve().parent
sys.path.insert(0, str(RELEASE))
from config import ReleaseError  # noqa: E402


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree(root, skip):
    return {str(p.relative_to(root)): digest(p) for p in sorted(root.rglob('*'))
            if p.is_file() and not str(p.relative_to(root)).startswith(skip)}


def exe_bytes():
    """The smallest file the installer accepts as a 64-bit Windows executable."""
    header = bytearray(128)
    header[:2] = b'MZ'
    struct.pack_into('<I', header, 60, 64)
    header[64:70] = b'PE\0\0d\x86'
    struct.pack_into('<H', header, 88, 0x20b)
    return bytes(header)


def single(package, deps):
    """Run inside a child process whose HOME and XDG_CACHE_HOME are temporary: install, record, restore."""
    from unittest.mock import patch
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(package))
    spec = importlib.util.spec_from_file_location('package_install', package / 'install.py')
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    import launcher_config  # the package's own copy (its directory is first on sys.path)
    home = Path(os.environ['HOME'])
    game = home.parent / 'game'
    game.mkdir()
    (game / 'Game.exe').write_bytes(exe_bytes())
    heroic = home / '.config/heroic'
    (heroic / 'gog_store').mkdir(parents=True)
    (heroic / 'GamesConfig').mkdir(parents=True)
    (heroic / 'gog_store/installed.json').write_text(
        json.dumps({'installed': [{'appName': '123', 'install_path': str(game)}]}))
    (heroic / 'GamesConfig/123.json').write_text(json.dumps({'123': {'enviromentOptions': [], 'wrapperOptions': []}}))
    before = tree(game, installer.STATE)
    no_download = (patch.object(installer, 'prepare_dependencies', side_effect=RuntimeError('a download was attempted'))
                   if hasattr(installer, 'prepare_dependencies') else contextlib.nullcontext())
    with patch.object(launcher_config, 'require_stopped'), no_download, contextlib.redirect_stdout(sys.stderr):
        installer.install(package, game / 'Game.exe', route='opti', fg_input='upscaler', dependency_dir=deps)
        installed = tree(game, installer.STATE)
        installer.restore(game / 'Game.exe')
    restored = tree(game, installer.STATE)
    return dict(package=package.name, installed=installed, restored_to_original=restored == before)


def run(package, deps):
    """single() in a child process with a temporary HOME and cache; returns its report."""
    with tempfile.TemporaryDirectory(prefix='bc250-smoke-') as scratch:
        home = Path(scratch) / 'home'
        home.mkdir()
        env = dict(os.environ, HOME=str(home), XDG_CACHE_HOME=str(Path(scratch) / 'cache'), PYTHONDONTWRITEBYTECODE='1')
        out = subprocess.run([sys.executable, __file__, '--single', str(package), '--deps', str(deps)],
                             capture_output=True, text=True, env=env, timeout=900)
        if out.returncode:
            raise ReleaseError(f'Installing {package.name} failed:\n{out.stderr[-3000:]}')
        return json.loads(out.stdout)


def check(report, spec, package=None):
    """Never-ship files must be installed from the downloads with the bytes the package used to carry."""
    rules = spec['never_ship']
    installed = report['installed']
    problems = [] if report['restored_to_original'] else ['Restore did not return the game folder to its original files']
    if package is not None and spec['manifest'].get('addon_entry') == 'libxess_fg-proxy':
        if installed.get('libxess_fg.dll') != digest(package / 'payload/libxess_fg.dll'):
            problems.append('libxess_fg.dll in the game folder is not the package\'s proxy')
        enabler = sorted(t for t in installed if t == 'version.dll' or t.startswith(('XeSSMFG/', 'OptiScaler/plugins/BC250-MFG')))
        if enabler:
            problems.append('enabler files installed: ' + ', '.join(enabler))
    for path in rules['paths']:
        if path.startswith('payload/'):
            target = path.removeprefix('payload/')
            if installed.get(target) not in rules['sha256']:
                problems.append(f'{target} (package path {path}) is missing or not the expected bytes')
        else:
            name = Path(path).name
            if not any(Path(t).name == name and d in rules['sha256'] for t, d in installed.items()):
                problems.append(f'{name} (package path {path}) is not installed with the expected bytes')
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--package', type=Path, help='assembled package directory (default: build/package/<name>)')
    parser.add_argument('--deps', type=Path, required=True, help='prepared dependency directory (files by pinned name)')
    parser.add_argument('--compare-with', type=Path, metavar='PACKAGE', help='another package to install the same way')
    parser.add_argument('--variant', metavar='NAME', help='the package is this package.json variant (e.g. intel-free-2x)')
    parser.add_argument('--single', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.single:
        print(json.dumps(single(args.single.resolve(), args.deps.resolve())))
        return
    spec = json.loads((RELEASE / 'package.json').read_text())
    if args.variant:
        from assemble import apply_variant
        spec = apply_variant(spec, args.variant)
    package = (args.package or RELEASE.parent / 'build' / spec.get('package_dir', 'package') / spec['name']).resolve()
    if not (package / 'manifest.json').is_file():
        raise ReleaseError(f'No assembled package at {package}: run release/assemble.py first')
    if not args.deps.is_dir():
        raise ReleaseError(f'--deps is not a directory: {args.deps}')
    report = run(package, args.deps.resolve())
    problems = check(report, spec, package)
    summary = dict(package=report['package'], installed_files=len(report['installed']),
                   restored_to_original=report['restored_to_original'], problems=problems)
    if args.compare_with:
        other = run(args.compare_with.resolve(), args.deps.resolve())
        mine, theirs = report['installed'], other['installed']
        summary['comparison'] = dict(
            package=other['package'], installed_files=len(theirs),
            only_this=sorted(set(mine) - set(theirs)), only_other=sorted(set(theirs) - set(mine)),
            different=sorted(k for k in set(mine) & set(theirs) if mine[k] != theirs[k]))
    print(json.dumps(summary, indent=2))
    if problems:
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        sys.exit(f'error: {error}')
