#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Install and check the CI toolchain pinned in release/ci/ci.lock.json.

What CI pins, and what it may expect:

  pinned   (every push and pull request) An official Arch Linux container image (by digest) whose pacman is pointed at
           one Arch Linux Archive snapshot. Every package comes from that snapshot, and the packages that reach an
           output (clang, lld, llvm-libs, gcc, glibc, binutils, wine, vulkan-headers, python, plus linux-api-headers
           6.18-1 from the package archive) are also pinned by file sha256 and reinstalled from the checked files.
           Their versions are those of release/inputs.lock.json toolchain.packages, the system-header and import
           library digests the build scripts record are expected to equal the lock's, and the builds have already been
           shown to be independent of the tree's location (release/export_tree.py). Byte-identical reproduction of
           the reference outputs is therefore EXPECTED here, and a mismatch fails the job: it means a source, an
           input or the toolchain changed, and a changed binary is a new build that needs its own qualification (and
           its new hash in inputs.lock.json "outputs" in the same change).
  current  (weekly, .github/workflows/pins.yml) Today's Arch packages, unpinned. Best effort only: the job builds,
           runs every test and the Intel-free check, and reports whether the outputs still match the lock as
           warnings. A newer clang, Wine or glibc normally changes the bytes.

Only the enabler-free proxy (libxess_fg.dll, release/build_proxy.py) and the pacing layer (libxefg_wave.so,
release/build_layer.py) can be built from the public tree. The maintainers' BC250-MFG.asi add-on builds need private
work-directory inputs; CI does not build them and reports their reference hashes as not checked.

  python3 release/ci/toolchain.py check-lock        # ci.lock.json against inputs.lock.json (no root, no network)
  python3 release/ci/toolchain.py check-workflows   # the workflows name the pinned image and snapshot
  python3 release/ci/toolchain.py install [--toolchain pinned|current]   # as root in the CI container (pacman)
  python3 release/ci/toolchain.py verify [--toolchain pinned|current]    # installed versions against both locks
  python3 release/ci/toolchain.py dxc --dest DIR [--downloads DIR]       # pinned DXC release, extracted and checked
"""
import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (REPO, WORKFLOWS, ReleaseError, annotate, append_env, download, load_ci_lock, load_lock,  # noqa: E402
                    sha256, step_summary, write_json)

TOOLCHAINS = ('pinned', 'current')
IMAGE_PATTERN = re.compile(r'archlinux:[A-Za-z0-9._-]+(?:@sha256:[0-9a-f]{64})?')
USES_PATTERN = re.compile(r'^\s*(?:-\s*)?uses:\s*(\S+)', re.M)
SNAPSHOT_PATTERN = re.compile(r'^\s*ARCH_SNAPSHOT:\s*["\']?([0-9]{4}/[0-9]{2}/[0-9]{2})["\']?\s*$', re.M)


# ------------------------------------------------------------------------------------------------------------ the locks

def locked_toolchain():
    """{package: version} of inputs.lock.json toolchain.packages ("name version" strings) and its python version."""
    toolchain = load_lock()['toolchain']
    packages = {}
    for entry in toolchain['packages']:
        name, _, version = entry.partition(' ')
        packages[name] = version
    return packages, toolchain.get('python')


def check_lock():
    """ci.lock.json must pin exactly the versions inputs.lock.json names, and be well formed."""
    ci, problems = load_ci_lock(), []
    packages, python = locked_toolchain()
    pinned = {name: entry['version'] for name, entry in ci['packages'].items()}
    for name, version in packages.items():
        if pinned.get(name) != version:
            problems.append(f'inputs.lock.json toolchain names {name} {version}; ci.lock.json pins {pinned.get(name)}')
    if python and not pinned.get('python', '').startswith(python + '-'):
        problems.append(f'inputs.lock.json names python {python}; ci.lock.json pins {pinned.get("python")}')
    for name, entry in {**ci['packages'], **ci['archived']}.items():
        if not re.fullmatch(r'[0-9a-f]{64}', entry['sha256']):
            problems.append(f'{name}: sha256 is not 64 hex digits')
        if 'file' in entry and not entry['file'].startswith(f'{name}-{entry["version"]}-'):
            problems.append(f'{name}: file {entry["file"]} does not name version {entry["version"]}')
        if 'url' in entry and not entry['url'].endswith(f'/{name}-{entry["version"]}-x86_64.pkg.tar.zst'):
            problems.append(f'{name}: url does not name version {entry["version"]}')
    overlap = sorted(set(ci['packages']) & (set(ci['archived']) | set(ci['extra_packages'])))
    if overlap:
        problems.append('packages listed twice: ' + ', '.join(overlap))
    if not re.fullmatch(r'[0-9]{4}/[0-9]{2}/[0-9]{2}', ci['snapshot']['date']):
        problems.append('snapshot date is not YYYY/MM/DD')
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', ci['image']['digest']):
        problems.append('image digest is not sha256:<64 hex digits>')
    if problems:
        raise ReleaseError('ci.lock.json: ' + '; '.join(problems))
    return dict(packages=len(ci['packages']), archived=sorted(ci['archived']), snapshot=ci['snapshot']['date'],
                image=pinned_image(ci), matches_inputs_lock=sorted(packages))


def pinned_image(ci=None):
    ci = ci or load_ci_lock()
    return f'{ci["image"]["name"]}@{ci["image"]["digest"]}'


def check_workflows():
    """Every workflow names only the pinned image (or the unpinned archlinux:base of the current-toolchain run), the
    pinned snapshot, and actions pinned by full commit sha."""
    ci = load_ci_lock()
    image, problems, seen = pinned_image(ci), [], {}
    files = sorted(WORKFLOWS.glob('*.yml')) + sorted(WORKFLOWS.glob('*.yaml'))
    if not files:
        raise ReleaseError(f'No workflows in {WORKFLOWS.relative_to(REPO)}')
    yaml = vendored_yaml()
    for path in files:
        text = path.read_text()
        name = str(path.relative_to(REPO))
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as error:
            problems.append(f'{name}: not valid YAML ({error})')
        for found in IMAGE_PATTERN.findall(text):
            seen.setdefault(found, []).append(name)
            if found not in (image, 'archlinux:base'):
                problems.append(f'{name} names container image {found}, not the pinned {image}')
        for found in SNAPSHOT_PATTERN.findall(text):
            if found != ci['snapshot']['date']:
                problems.append(f'{name} sets ARCH_SNAPSHOT {found}, not the pinned {ci["snapshot"]["date"]}')
        for action in USES_PATTERN.findall(text):
            if action.startswith('./'):
                continue
            if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}', action):
                problems.append(f'{name} uses {action}, which is not pinned by a full commit sha')
    if image not in seen:
        problems.append(f'No workflow uses the pinned image {image}')
    if problems:
        raise ReleaseError('; '.join(problems))
    return dict(workflows=[str(p.relative_to(REPO)) for p in files], images={k: sorted(set(v)) for k, v in seen.items()})


def vendored_yaml():
    """PyYAML: the installed one, else the copy vendored for the installer (packaging/vendor)."""
    try:
        import yaml
        return yaml
    except ImportError:
        sys.path.insert(0, str(REPO / 'packaging' / 'vendor'))
        import yaml
        return yaml


# ------------------------------------------------------------------------------------------------------------- pacman

def pacman(*arguments):
    print('+ pacman ' + ' '.join(arguments), flush=True)
    subprocess.run(['pacman', *arguments], check=True)


def installed(names):
    """{package: installed version or None}."""
    versions = {}
    for name in names:
        out = subprocess.run(['pacman', '-Q', name], capture_output=True, text=True)
        versions[name] = out.stdout.split()[1] if out.returncode == 0 else None
    return versions


def cache_dir():
    out = subprocess.run(['pacman-conf', 'CacheDir'], capture_output=True, text=True, check=True).stdout.split()
    return Path(out[0] if out else '/var/cache/pacman/pkg')


def check_mirrorlist(ci):
    """pacman must already point at the pinned snapshot (the workflow's first step writes the mirror list)."""
    server = ci['snapshot']['server'].format(date=ci['snapshot']['date'])
    expected = f'Server = {server}'
    text = Path('/etc/pacman.d/mirrorlist').read_text()
    servers = [line.strip() for line in text.splitlines() if line.strip().startswith('Server')]
    if servers != [expected]:
        raise ReleaseError(f'/etc/pacman.d/mirrorlist must hold exactly "{expected}" (found {servers}); the workflow\'s '
                           'bootstrap step writes it')
    variable = os.environ.get('ARCH_SNAPSHOT')
    if variable and variable != ci['snapshot']['date']:
        raise ReleaseError(f'ARCH_SNAPSHOT is {variable}, ci.lock.json pins {ci["snapshot"]["date"]}')


def checked_file(path, entry):
    if not path.is_file():
        raise ReleaseError(f'{path.name} is not in the package cache')
    digest, size = sha256(path), path.stat().st_size
    if digest != entry['sha256'] or ('bytes' in entry and size != entry['bytes']):
        raise ReleaseError(f'{path.name}: sha256 {digest} ({size} bytes), pinned {entry["sha256"]} ({entry.get("bytes")})')
    return path


def install(toolchain):
    if os.geteuid() != 0:
        raise ReleaseError('install runs pacman and must run as root (inside the CI container)')
    ci = load_ci_lock()
    names = list(ci['packages']) + list(ci['extra_packages'])
    if toolchain == 'current':
        pacman('-Syu', '--noconfirm', '--needed', *names, *ci['archived'])
        return verify(toolchain)
    check_mirrorlist(ci)
    pacman('-S', '--noconfirm', '--needed', *names)
    # Download the pinned packages (again, if they came with the image), check each file, then reinstall from the
    # checked files so that what is installed is exactly what is pinned.
    pacman('-Sw', '--noconfirm', *ci['packages'])
    cache = cache_dir()
    files = [checked_file(cache / entry['file'], entry) for entry in ci['packages'].values()]
    for name, entry in ci['archived'].items():
        target = cache / entry['url'].rsplit('/', 1)[1]
        if not (target.is_file() and sha256(target) == entry['sha256']):
            print(f'+ download {entry["url"]}', flush=True)
            download(entry['url'], target)
        files.append(checked_file(target, entry))
    pacman('-U', '--noconfirm', *map(str, files))
    return verify(toolchain)


def verify(toolchain):
    """Installed versions against ci.lock.json and inputs.lock.json; a difference fails the pinned toolchain and is
    reported as a warning for the current one."""
    ci = load_ci_lock()
    packages, python = locked_toolchain()
    wanted = {name: entry['version'] for name, entry in {**ci['packages'], **ci['archived']}.items()}
    wanted.update(packages)
    found = installed(sorted(wanted))
    differences = {name: dict(locked=version, installed=found[name]) for name, version in wanted.items()
                   if found[name] != version}
    if python and platform.python_version() != python:
        differences['python (interpreter)'] = dict(locked=python, installed=platform.python_version())
    result = dict(toolchain=toolchain, installed=found, python=platform.python_version(), differences=differences,
                  matches_lock=not differences)
    rows = '\n'.join(f'| {name} | {wanted[name]} | {found[name]} |' for name in sorted(wanted))
    step_summary(f'### Toolchain ({toolchain})\n\n| Package | Locked | Installed |\n| --- | --- | --- |\n{rows}\n\n'
                 + ('Every package is at its locked version.' if not differences else
                    f'{len(differences)} differ from the lock.'))
    if differences:
        text = ', '.join(f'{n} {d["installed"]} (locked {d["locked"]})' for n, d in sorted(differences.items()))
        if toolchain == 'pinned':
            raise ReleaseError('The pinned toolchain differs from the lock: ' + text)
        annotate('warning', 'Toolchain differs from inputs.lock.json, so byte identity is not expected: ' + text,
                 title='current toolchain')
    return result


# ---------------------------------------------------------------------------------------------------------------- DXC

def dxc(dest, downloads):
    """The pinned DXC release unpacked into dest (checked by sha256 and by its version line); returns its binary."""
    entry = load_ci_lock()['dxc']
    archive = downloads / entry['url'].rsplit('/', 1)[1]
    downloads.mkdir(parents=True, exist_ok=True)
    if not (archive.is_file() and sha256(archive) == entry['sha256']):
        print(f'+ download {entry["url"]}', flush=True)
        download(entry['url'], archive)
    checked_file(archive, entry)
    # Unpacked afresh from the checked archive every time (only the archive is cached between runs).
    partial = dest.with_name(dest.name + '.partial')
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    with tarfile.open(archive) as stream:
        stream.extractall(partial, filter='data')
    shutil.rmtree(dest, ignore_errors=True)
    partial.rename(dest)
    binary = dest / 'bin' / 'dxc'
    out = subprocess.run([str(binary), '--version'], capture_output=True, text=True)
    version = (out.stdout or out.stderr).strip().splitlines()
    if out.returncode or not version or version[0] != entry['version']:
        raise ReleaseError(f'{binary} reports {version[:1]}, pinned {entry["version"]!r}')
    return binary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check-lock', help='ci.lock.json against inputs.lock.json')
    commands.add_parser('check-workflows', help='pinned image, snapshot and action shas in .github/workflows')
    for name in ('install', 'verify'):
        command = commands.add_parser(name)
        command.add_argument('--toolchain', choices=TOOLCHAINS, default=os.environ.get('TOOLCHAIN', 'pinned'))
        command.add_argument('--report', type=Path, help='also write the result as JSON')
    command = commands.add_parser('dxc', help='download, check and unpack the pinned DXC release')
    command.add_argument('--dest', type=Path, required=True, help='directory to unpack into (bin/dxc below it)')
    command.add_argument('--downloads', type=Path, help='where the archive is kept (default: beside dest)')
    command.add_argument('--github-env', action='store_true', help='export XEMFG_DXC=<dest> to later workflow steps')
    args = parser.parse_args()
    if args.command == 'check-lock':
        result = check_lock()
    elif args.command == 'check-workflows':
        result = check_workflows()
    elif args.command in ('install', 'verify'):
        result = (install if args.command == 'install' else verify)(args.toolchain)
        if args.report:
            write_json(args.report, result)
    else:
        dest = args.dest.resolve()
        binary = dxc(dest, (args.downloads or dest.parent).resolve())
        if args.github_env:
            append_env('XEMFG_DXC', str(dest))
        result = dict(dxc=str(binary), release=load_ci_lock()['dxc']['release'])
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        annotate('error', error, title='toolchain')
        sys.exit(1)
    except subprocess.CalledProcessError as error:
        annotate('error', f'command failed ({error.returncode}): {" ".join(map(str, error.cmd))[:300]}', title='toolchain')
        sys.exit(1)
