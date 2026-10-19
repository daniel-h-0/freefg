#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Stage the shader-profile files the enabler-free build needs from this tree, for CI (no private work directory).

release/build_proxy.py reads the locked profile (inputs.lock.json work group "profile-cl-wino-q33") through
XEMFG_PROFILE, but only the files that release/intel_free.json keeps or rewrites: this project's own shaders, markers
and tables (origin "own"). This script finds each of them in the tree by its locked sha256, wherever and under whatever
name the tree holds it (build directories, .git and the download cache are skipped), copies them under their locked
names into a fresh directory, and prints (or exports to later workflow steps) XEMFG_PROFILE for it.

It fails when a needed file is missing, and it never stages a file whose lock origin is not "own" (it refuses an
intel_free.json that would need one). With XEMFG_PROFILE already set, that directory is checked and used as it is.

  python3 release/ci/profile.py stage --dest DIR [--github-env]
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, RELEASE, ReleaseError, annotate, append_env, build_config, load_lock, sha256  # noqa: E402

GROUP = 'profile-cl-wino-q33'
SKIP_DIRS = {'.git', 'build', '__pycache__', 'node_modules'}
MAX_BYTES = 8 << 20


def needed():
    """{name: sha256} of the locked profile files the Intel-free builds read (intel_free.json keep and rewrite)."""
    definition = json.loads((RELEASE / 'intel_free.json').read_text())['profile']
    locked = load_lock()['work'][GROUP]['files']
    names = sorted(set(definition['keep']) | set(definition['rewrite']))
    foreign = sorted(n for n in names if locked.get(n, {}).get('origin') != 'own')
    if foreign:
        raise ReleaseError('intel_free.json keeps profile files whose lock origin is not "own": ' + ', '.join(foreign))
    return {name: locked[name]['sha256'] for name in names}


def candidates(excluded):
    """Every regular file of the tree below MAX_BYTES, outside the skipped and excluded directories."""
    for root, dirs, files in os.walk(REPO):
        here = Path(root)
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS
                         and not any((here / d).resolve() == e for e in excluded))
        for name in sorted(files):
            path = here / name
            if path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_BYTES:
                yield path


def stage(dest):
    wanted = needed()
    config = build_config()
    preset = config.path('profile')
    if preset:
        missing = [n for n, d in wanted.items() if not (preset / n).is_file() or sha256(preset / n) != d]
        if missing:
            raise ReleaseError(f'XEMFG_PROFILE ({preset}) lacks or differs in {len(missing)} needed files: '
                               + ', '.join(missing[:8]))
        return preset, {n: 'XEMFG_PROFILE' for n in wanted}
    by_digest = {}
    for name, digest in wanted.items():
        by_digest.setdefault(digest, []).append(name)
    excluded = [p.resolve() for p in (config.build, config.cache) if p]
    sources = {}
    for path in candidates(excluded):
        digest = sha256(path)
        for name in by_digest.get(digest, ()):
            sources.setdefault(name, []).append(path)
    missing = sorted(set(wanted) - set(sources))
    if missing:
        raise ReleaseError(f'{len(missing)} of the {len(wanted)} own profile files the enabler-free build needs are not '
                           'in this tree (by their sha256 in inputs.lock.json): ' + ', '.join(missing[:10])
                           + (' ...' if len(missing) > 10 else '') + '. The public tree must carry the own shader '
                           'profile (or set XEMFG_PROFILE to a directory holding it).')
    dest = dest.resolve()
    partial = dest.with_name(dest.name + '.partial')
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    for name in sorted(wanted):
        shutil.copyfile(sources[name][0], partial / name)
        if sha256(partial / name) != wanted[name]:
            raise ReleaseError(f'Copy of {name} differs')
    shutil.rmtree(dest, ignore_errors=True)
    partial.rename(dest)
    return dest, {name: str(paths[0].relative_to(REPO)) for name, paths in sorted(sources.items())}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('stage')
    command.add_argument('--dest', type=Path, required=True, help='new directory for the staged files')
    command.add_argument('--github-env', action='store_true', help='export XEMFG_PROFILE to later workflow steps')
    args = parser.parse_args()
    folder, sources = stage(args.dest)
    if args.github_env:
        append_env('XEMFG_PROFILE', str(folder))
    directories = sorted({str(Path(s).parent) for s in sources.values()})
    print(json.dumps(dict(profile=str(folder), files=len(sources), found_in=directories), indent=2))


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        annotate('error', error, title='shader profile')
        sys.exit(1)
