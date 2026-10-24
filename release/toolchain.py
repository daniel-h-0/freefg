#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The pinned build toolchain in a folder of its own: release builds that do not depend on the host's packages.

release/ci/ci.lock.json pins, by file sha256, the Arch Linux packages the reference outputs were built with (inputs.lock.json
"toolchain"). This tool takes exactly those package files, from a local folder such as pacman's package cache or else
from the Arch Linux Archive, checks each file's sha256 and size, and unpacks them into one folder, as an ordinary user:

  <dir>/tools           clang, lld, llvm-libs, gcc, binutils; Wine's headers and x86-64 Windows import libraries only
  <dir>/sysroot         glibc, linux-api-headers, vulkan-headers and gcc's runtime libraries (gcc --sysroot)
  <dir>/bin             clang, ld.lld and gcc: wrappers that run the tools of this folder (tools/usr/lib as their only
                        LD_LIBRARY_PATH; gcc with --sysroot=<dir>/sysroot and binutils from tools)
  <dir>/toolchain.json  the pins it was made from, where each file came from, and a digest of every unpacked file

Nothing is installed and nothing outside the folder is written, except downloads into the package folder. The Python
package that ci.lock.json also pins is the interpreter of the CI job; it is not a build input and is not unpacked.

The build scripts use the folder when XEMFG_TOOLCHAIN (or --toolchain) names it: clang, ld.lld, gcc and Wine's
headers and import libraries then come from it, the setting cannot be combined with XEMFG_CLANG, XEMFG_GCC,
XEMFG_WINE_INCLUDE or XEMFG_WINE_LIB, and a compiler version, system-header digest or import-library digest that differs
from inputs.lock.json fails the build instead of printing a warning. XEMFG_TOOLCHAIN=pinned uses
<cache>/toolchain-<id> (id: the first 12 hex digits of the pins' digest) and prepares it on first use. What still
comes from the host: the Python interpreter, the shared libraries the compilers themselves load that no pinned package
holds (zlib, zstd, libxml2, GMP/MPFR/MPC/ISL and similar), the C library the unit tests run against, and the Wine that
runs release/check_proxy_wine.py's checks. None of them reaches an output; the build records name the compilers and
digest the headers and libraries that do.

  python3 release/toolchain.py prepare [--dest DIR] [--packages DIR[:DIR...]] [--offline]
  python3 release/toolchain.py check DIR       # every unpacked file against toolchain.json, the pins against the lock
  python3 release/toolchain.py env [DIR]       # the variables to build with it (shell syntax)
  python3 release/toolchain.py pins            # the pinned files, their roles, and the id

Package files are looked up, by name, in the folders of --packages / XEMFG_PACKAGES (separated by ":"), then in pacman's
package cache (pacman-conf CacheDir, else /var/cache/pacman/pkg) and in <cache>/packages; a file whose sha256 or size
differs is passed over. A file found nowhere is downloaded into <cache>/packages from the Arch Linux Archive (the
snapshot of ci.lock.json, or the archived package's own URL) unless --offline is given.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import RELEASE, Config, ReleaseError, add_arguments, sha256, tool_version  # noqa: E402

CI_LOCK = RELEASE / 'ci' / 'ci.lock.json'
LAYOUT = 1  # the unpacking scheme below; a change gives a new id
USER_AGENT = 'release-toolchain'
TIMEOUT = 120

# Where each pinned package is unpacked (every package of ci.lock.json "packages" and "archived" must be listed).
ROLES = {
    'clang': 'tools', 'lld': 'tools', 'llvm-libs': 'tools', 'gcc': 'tools', 'binutils': 'tools', 'wine': 'tools',
    'glibc': 'sysroot', 'linux-api-headers': 'sysroot', 'vulkan-headers': 'sysroot', 'libgcc': 'sysroot',
    'libstdc++': 'sysroot', 'libasan': 'sysroot', 'libtsan': 'sysroot', 'libubsan': 'sysroot',
    'python': None,  # the CI job's interpreter: not a build input, not unpacked
}
# Packages unpacked in part: Wine's headers and its x86-64 Windows import libraries (the proxy links two of them).
SELECTED = {'wine': ('usr/include/wine/', ('usr/lib/wine/x86_64-windows/', '.a'))}

WINE_INCLUDE = 'tools/usr/include/wine'
WINE_LIB = 'tools/usr/lib/wine/x86_64-windows'
WRAPPERS = {
    'clang': 'exec "$here/tools/usr/bin/clang" "$@"',
    'ld.lld': 'exec "$here/tools/usr/bin/ld.lld" "$@"',
    'gcc': 'exec "$here/tools/usr/bin/gcc" --sysroot="$here/sysroot" -B"$here/tools/usr/bin/" "$@"',
}
WRAPPER = '''#!/bin/sh
# release/toolchain.py: {name} from this pinned toolchain folder (see toolchain.json)
here=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P) || exit 1
export LD_LIBRARY_PATH="$here/tools/usr/lib"
{command}
'''


# ----------------------------------------------------------------------------------------------------------- the pins

def load_ci_lock(path=CI_LOCK):
    return json.loads(Path(path).read_text())


def pins(ci=None):
    """[{name, version, file, sha256, bytes, url, role}] of every unpacked package, sorted by name."""
    ci = ci or load_ci_lock()
    server = ci['snapshot']['server'].format(date=ci['snapshot']['date'])
    listed = {**ci['packages'], **ci['archived']}
    unknown = sorted(set(listed) - set(ROLES))
    if unknown:
        raise ReleaseError('release/ci/ci.lock.json pins packages release/toolchain.py has no role for: '
                           + ', '.join(unknown))
    rows = []
    for name, entry in sorted(listed.items()):
        if ROLES[name] is None:
            continue
        if 'url' in entry:
            url, file = entry['url'], entry['url'].rsplit('/', 1)[1]
        else:
            file = entry['file']
            url = server.replace('$repo', entry['repo']).replace('$arch', 'x86_64') + '/' + file
        rows.append(dict(name=name, version=entry['version'], file=file, sha256=entry['sha256'],
                         bytes=entry.get('bytes'), url=url, role=ROLES[name]))
    missing = sorted(n for n, role in ROLES.items() if role and n not in listed)
    if missing:
        raise ReleaseError('release/toolchain.py unpacks packages that ci.lock.json does not pin: ' + ', '.join(missing))
    return rows


def pins_digest(rows):
    """sha256 over the unpacking scheme and every pin that reaches the folder (not the download URLs)."""
    canonical = dict(layout=LAYOUT, selected={k: [v[0], list(v[1])] for k, v in SELECTED.items()},
                     wrappers=WRAPPERS, packages=[{k: r[k] for k in ('name', 'version', 'file', 'sha256', 'bytes', 'role')}
                                                  for r in rows])
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def pins_id(ci=None):
    return pins_digest(pins(ci))[:12]


# ------------------------------------------------------------------------------------------------- the package files

def default_package_dirs():
    """pacman's package cache folders (pacman-conf CacheDir), else /var/cache/pacman/pkg when it exists."""
    try:
        out = subprocess.run(['pacman-conf', 'CacheDir'], capture_output=True, text=True, timeout=30)
        folders = [Path(line.strip()) for line in out.stdout.splitlines() if line.strip()] if out.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        folders = []
    return folders or [p for p in (Path('/var/cache/pacman/pkg'),) if p.is_dir()]


def package_dirs(config, extra=None):
    """The folders searched for package files, in order (the download folder last)."""
    listed = []
    for value in (extra, config.values.get('packages')):
        if value:
            listed += [Path(p).expanduser() for p in str(value).split(':') if p]
    return [*listed, *default_package_dirs(), config.cache / 'packages']


def matches(path, pin):
    return (path.is_file() and (pin['bytes'] is None or path.stat().st_size == pin['bytes'])
            and sha256(path) == pin['sha256'])


def find_package(pin, folders):
    """(path, folder index) of a checked local copy of a pinned file, or (None, passed-over paths)."""
    passed = []
    for index, folder in enumerate(folders):
        path = folder / pin['file']
        if path.is_file():
            if matches(path, pin):
                return path, index
            passed.append(str(path))
    return None, passed


def download(pin, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + '.partial')
    request = urllib.request.Request(pin['url'], headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response, partial.open('wb') as stream:
            shutil.copyfileobj(response, stream, 1 << 20)
        if not matches(partial, pin):
            raise ReleaseError(f'{pin["url"]} did not serve the pinned file (sha256 {sha256(partial)}, '
                               f'{partial.stat().st_size} bytes; pinned {pin["sha256"]}, {pin["bytes"]} bytes)')
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def package_files(config, rows, extra=None, offline=False):
    """{name: (path, source)} of every pinned file, each checked; downloads what no folder holds."""
    folders = package_dirs(config, extra)
    found, missing = {}, []
    for pin in rows:
        path, where = find_package(pin, folders)
        if path is not None:
            found[pin['name']] = (path, 'downloaded earlier' if folders[where] == config.cache / 'packages' else 'local')
            continue
        if offline:
            missing.append(pin['file'] + (f' (passed over: {", ".join(where)})' if where else ''))
            continue
        print(f'+ download {pin["url"]}', file=sys.stderr, flush=True)
        found[pin['name']] = (download(pin, config.cache / 'packages' / pin['file']), 'downloaded')
    if missing:
        raise ReleaseError('--offline, and these pinned package files are in none of the package folders '
                           f'({", ".join(map(str, folders))}): ' + '; '.join(missing))
    return found


# ------------------------------------------------------------------------------------------------------- unpacking

def member_filter(name, selection):
    """The tarfile extraction filter of one package: pacman's metadata files are skipped, so is anything outside the
    package's selection; an absolute symbolic link is made relative to the package root (never to the host's /usr);
    then tarfile's "data" filter applies (no absolute or escaping paths, no special files, no set-id bits)."""
    def keep(member, path):
        if member.name.startswith('.'):
            return None
        if selection:
            # directories come with the files below them (tarfile creates the parent folders)
            if member.isdir() or not any(
                    member.name.startswith(rule) if isinstance(rule, str) else
                    (member.name.startswith(rule[0]) and member.name.endswith(rule[1])) for rule in selection):
                return None
        if member.issym() and member.linkname.startswith('/'):
            target = os.path.relpath(member.linkname.lstrip('/'), os.path.dirname(member.name) or '.')
            member = member.replace(linkname=target, deep=False)
        return tarfile.data_filter(member, path)
    return keep


def unpack(path, dest, name):
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, 'r:zst') as archive:
        archive.extractall(dest, filter=member_filter(name, SELECTED.get(name)))


def tree_digest(root, parts=('tools', 'sysroot', 'bin')):
    """(files, sha256) over "<path>\\t<sha256 or ->target>\\n" of every file and link below root/<part>."""
    rows = []
    for part in parts:
        base = root / part
        for folder, dirs, files in os.walk(base):
            dirs.sort()
            for entry in sorted(files + [d for d in dirs if (Path(folder) / d).is_symlink()]):
                path = Path(folder) / entry
                rel = str(path.relative_to(root))
                rows.append(f'{rel}\t->{os.readlink(path)}\n' if path.is_symlink() else f'{rel}\t{sha256(path)}\n')
    return len(rows), hashlib.sha256(''.join(sorted(rows)).encode()).hexdigest()


def write_wrappers(root):
    folder = root / 'bin'
    folder.mkdir(parents=True, exist_ok=True)
    for name, command in WRAPPERS.items():
        path = folder / name
        path.write_text(WRAPPER.format(name=name, command=command))
        path.chmod(0o755)


def versions(root):
    return dict(clang=tool_version([str(root / 'bin' / 'clang'), '--version']),
                lld=tool_version([str(root / 'bin' / 'ld.lld'), '--version']),
                gcc=tool_version([str(root / 'bin' / 'gcc'), '--version']))


def prepare(config, dest=None, extra=None, offline=False):
    """Unpack the pinned packages into dest (default: <cache>/toolchain-<id>); returns its record. A folder that already
    holds a complete toolchain of the same pins is reused as it is (check() re-hashes it)."""
    rows = pins()
    digest = pins_digest(rows)
    dest = Path(dest).expanduser().resolve() if dest else config.cache / f'toolchain-{digest[:12]}'
    existing = read_record(dest)
    if existing is not None:
        if existing.get('pins_sha256') != digest:
            raise ReleaseError(f'{dest} holds a toolchain made from other pins ({existing.get("id")}); this lock\'s is '
                               f'{digest[:12]}: prepare into another folder')
        return existing
    if dest.exists() and any(dest.iterdir()):
        raise ReleaseError(f'{dest} exists and is not a prepared toolchain (no complete toolchain.json): remove it or '
                           'choose another folder')
    files = package_files(config, rows, extra, offline)
    partial = dest.with_name(dest.name + '.partial')
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    for pin in rows:
        unpack(files[pin['name']][0], partial / pin['role'], pin['name'])
    write_wrappers(partial)
    count, tree = tree_digest(partial)
    record = dict(
        schema=1, tool='release/toolchain.py', id=digest[:12], pins_sha256=digest, layout=LAYOUT,
        packages={pin['name']: dict(version=pin['version'], file=pin['file'], sha256=pin['sha256'], bytes=pin['bytes'],
                                    role=pin['role'], source=files[pin['name']][1],
                                    selection=('part: ' + ', '.join(r if isinstance(r, str) else f'{r[0]}*{r[1]}'
                                                                    for r in SELECTED[pin['name']]))
                                    if pin['name'] in SELECTED else 'all')
                  for pin in rows},
        files=dict(count=count, sha256=tree),
        wine_include=WINE_INCLUDE, wine_lib=WINE_LIB, wrappers=sorted(WRAPPERS),
        complete=True)
    shutil.rmtree(dest, ignore_errors=True)
    partial.rename(dest)
    record['versions'] = versions(dest)
    (dest / 'toolchain.json').write_text(json.dumps(record, indent=2) + '\n')
    problems = version_problems(record['versions'], config.lock)
    if problems:
        raise ReleaseError(f'The unpacked toolchain in {dest} reports other versions than inputs.lock.json: '
                           + '; '.join(problems))
    return record


def read_record(root):
    path = Path(root) / 'toolchain.json'
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text())
    except ValueError:
        return None
    return record if record.get('complete') else None


def version_problems(found, lock):
    """Compiler version lines against inputs.lock.json toolchain (addon clang/lld, layer gcc)."""
    toolchain = lock.get('toolchain', {})
    wanted = dict(clang=toolchain.get('addon', {}).get('clang'), lld=toolchain.get('addon', {}).get('lld'),
                  gcc=toolchain.get('layer', {}).get('gcc'))
    return [f'{tool} reports {found.get(tool)!r}, inputs.lock.json names {line!r}'
            for tool, line in wanted.items() if line and found.get(tool) != line]


def ensure(config, root):
    """The record of the toolchain folder root, prepared there first when it does not exist yet (or is empty); a
    folder made from other pins is refused."""
    record = read_record(root)
    digest = pins_digest(pins())
    if record is None:
        return prepare(config, root, offline=config.offline)
    if record.get('pins_sha256') != digest:
        raise ReleaseError(f'XEMFG_TOOLCHAIN {root} was made from other pins ({record.get("id")}) than this tree\'s '
                           f'release/ci/ci.lock.json ({digest[:12]}): prepare a new one (release/toolchain.py prepare)')
    return record


def check(config, root):
    """Re-hash every unpacked file against toolchain.json; the pins against the lock; the version lines."""
    root = Path(root).expanduser().resolve()
    record = read_record(root)
    if record is None:
        raise ReleaseError(f'{root} holds no complete toolchain.json')
    problems = []
    if record.get('pins_sha256') != pins_digest(pins()):
        problems.append(f'made from other pins ({record.get("id")}) than release/ci/ci.lock.json')
    count, tree = tree_digest(root)
    if dict(count=count, sha256=tree) != record.get('files'):
        problems.append(f'unpacked files changed: {count} files, digest {tree} (recorded {record.get("files")})')
    found = versions(root)
    problems += version_problems(found, config.lock)
    if problems:
        raise ReleaseError(f'{root}: ' + '; '.join(problems))
    return dict(toolchain=str(root), id=record['id'], files=record['files'], versions=found, result='pass')


def environment(root):
    root = Path(root).expanduser().resolve()
    return dict(XEMFG_TOOLCHAIN=str(root))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('prepare', help='unpack the pinned packages into a folder')
    command.add_argument('--dest', type=Path, help='the folder (default <cache>/toolchain-<id>)')
    command = commands.add_parser('check', help='re-hash a prepared folder')
    command.add_argument('folder', type=Path)
    command = commands.add_parser('env', help='print the variables that select a prepared folder')
    command.add_argument('folder', type=Path, nargs='?')
    commands.add_parser('pins', help='the pinned package files and the id of their folder')
    args = parser.parse_args()
    config = Config({k: v for k, v in vars(args).items() if k != 'toolchain'}, offline=args.offline)
    if args.command == 'prepare':
        record = prepare(config, args.dest, offline=args.offline)
        dest = args.dest.resolve() if args.dest else config.cache / f'toolchain-{record["id"]}'
        print(json.dumps(dict(toolchain=str(dest), **{k: record[k] for k in ('id', 'pins_sha256', 'files', 'versions')},
                              sources={n: p['source'] for n, p in record['packages'].items()}), indent=2))
    elif args.command == 'check':
        print(json.dumps(check(config, args.folder), indent=2))
    elif args.command == 'env':
        folder = args.folder or config.cache / f'toolchain-{pins_id()}'
        for name, value in environment(folder).items():
            print(f"export {name}='{value}'")
    else:
        rows = pins()
        print(json.dumps(dict(id=pins_id(), pins_sha256=pins_digest(rows),
                              packages={r['name']: {k: r[k] for k in ('version', 'file', 'sha256', 'bytes', 'role', 'url')}
                                        for r in rows}), indent=2))


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        sys.exit(f'error: {error}')
