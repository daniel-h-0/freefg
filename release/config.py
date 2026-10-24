# SPDX-License-Identifier: MIT
"""Where the release build finds its inputs and puts its outputs.

No host-specific path is written in the tooling. Every location outside this repository comes from an environment
variable or the matching command-line option (the Wine defaults are the usual distribution paths):

  XEMFG_WORK          --work          work directory holding the inputs that are private or not fetched (shader
                                      profile, XeSSMFG enabler, OptiScaler fork build); see inputs.lock.json "work"
                                      (its "tree" groups are files of this repository, read in place)
  XEMFG_PROFILE       --profile       overrides XEMFG_WORK/<path> for the shader profile; with neither set, the
                                      profile committed in release/profile/ (the 42 own files the Intel-free builds
                                      read; the default build needs the work directory's full profile)
  XEMFG_ENABLER       --enabler       overrides XEMFG_WORK/<path> for the XeSSMFG enabler
  XEMFG_OPTISCALER    --optiscaler    overrides XEMFG_WORK/<path> for the OptiScaler fork build
  XEMFG_DXC           --dxc           DirectX Shader Compiler (its directory with bin/dxc, or the binary); optional,
                                      only used to check the profile's warp shader metadata
  XEMFG_OPTISCALER_SOURCE --optiscaler-source
                                      git checkout of the OptiScaler fork, read (never written) for the source
                                      companion (default: XEMFG_WORK/<locked source_in_work>)
  XEMFG_CACHE         --cache         downloads of pinned public inputs (default: <build>/cache)
  XEMFG_BUILD         --build-dir     build outputs (default: <repo>/build)
  XEMFG_CLANG         --clang         clang for the Windows add-on (default: clang)
  XEMFG_GCC           --gcc           gcc for the Linux layer and the unit tests (default: gcc)
  XEMFG_WINE_INCLUDE  --wine-include  Wine's include directory (default: /usr/include/wine)
  XEMFG_WINE_LIB      --wine-lib      Wine's x86_64 Windows import libraries (default: /usr/lib/wine/x86_64-windows)
  XEMFG_TOOLCHAIN     --toolchain     the pinned toolchain folder of release/toolchain.py, or "pinned" for
                                      <cache>/toolchain-<id> (prepared on first use): clang, ld.lld, gcc and Wine's
                                      headers and import libraries then come from it (not with the four settings above),
                                      and a compiler or header that differs from inputs.lock.json fails the build;
                                      unset: the host's tools, with warnings on a difference
  XEMFG_PACKAGES      --packages      folders holding the pinned package files, separated by ":" (searched before
                                      pacman's package cache); release/toolchain.py downloads what none holds

Run this file to print the resolved configuration.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RELEASE = REPO / 'release'
LOCK_PATH = RELEASE / 'inputs.lock.json'

# name: (environment variable, option, default, help)
SETTINGS = {
    'work': ('XEMFG_WORK', '--work', None, 'work directory with the private/large inputs listed under "work" in the lock'),
    'profile': ('XEMFG_PROFILE', '--profile', None,
                'shader profile directory (default: XEMFG_WORK/<locked path>, else release/profile)'),
    'enabler': ('XEMFG_ENABLER', '--enabler', None, 'XeSSMFG enabler directory (default: XEMFG_WORK/<locked path>)'),
    'optiscaler': ('XEMFG_OPTISCALER', '--optiscaler', None,
                   'OptiScaler fork build directory (default: XEMFG_WORK/<locked path>)'),
    'optiscaler_source': ('XEMFG_OPTISCALER_SOURCE', '--optiscaler-source', None,
                          'git checkout of the OptiScaler fork for the source companion (default: XEMFG_WORK/<locked '
                          'source_in_work>)'),
    'dxc': ('XEMFG_DXC', '--dxc', None, 'DXC directory (with bin/dxc) or binary; optional'),
    'cache': ('XEMFG_CACHE', '--cache', None, 'downloaded pinned inputs (default: <build>/cache)'),
    'build': ('XEMFG_BUILD', '--build-dir', str(REPO / 'build'), 'build output directory'),
    'clang': ('XEMFG_CLANG', '--clang', 'clang', 'clang executable'),
    'gcc': ('XEMFG_GCC', '--gcc', 'gcc', 'gcc executable'),
    'wine_include': ('XEMFG_WINE_INCLUDE', '--wine-include', '/usr/include/wine', "Wine's include directory"),
    'wine_lib': ('XEMFG_WINE_LIB', '--wine-lib', '/usr/lib/wine/x86_64-windows', "Wine's x86_64 Windows import libraries"),
    'toolchain': ('XEMFG_TOOLCHAIN', '--toolchain', None,
                  'pinned toolchain folder (release/toolchain.py), or "pinned" for <cache>/toolchain-<id>'),
    'packages': ('XEMFG_PACKAGES', '--packages', None,
                 'folders with the pinned toolchain package files, separated by ":"'),
}
# The settings a pinned toolchain (XEMFG_TOOLCHAIN) provides itself.
TOOLCHAIN_SETTINGS = ('clang', 'gcc', 'wine_include', 'wine_lib')

# Work inputs that a single-directory override replaces (lock group name -> setting name).
WORK_OVERRIDES = {'profile-cl-wino-q33': 'profile', 'xessmfg-enabler': 'enabler', 'optiscaler-fork': 'optiscaler'}
# Work inputs with a committed copy in this tree, used when neither the override nor XEMFG_WORK is set: the shader
# profile's own files (release/profile/ORIGIN.md; release/build_profile.py rebuilds them). Builds that need files the
# copy lacks (the default add-on) refuse with the missing file named.
IN_TREE = {'profile-cl-wino-q33': RELEASE / 'profile'}


class ReleaseError(Exception):
    """A check failed or an input is missing; the message says which and why."""


# The OptiScaler fork's group in inputs.lock.json: under "work" until the fork's release is public, then under "fetch"
# (release_fetch.about says how it moves). Its "source" record (commit, tree, tag, tag_commit, build_route, archive)
# moves with it: the source companion and release/fork_source_archive.py read it there.
FORK_GROUP = 'optiscaler-fork'


def fork_group(lock):
    """(section, group) of the OptiScaler fork in a lock: "work" until its release is public, then "fetch"."""
    for section in ('work', 'fetch'):
        group = (lock.get(section) or {}).get(FORK_GROUP)
        if group is not None:
            return section, group
    raise ReleaseError(f'inputs.lock.json has no {FORK_GROUP} group under "work" or "fetch"')


def fork_source_record(lock):
    """(section, group, source) of the OptiScaler fork: fork_group() and its "source" record, which must be there."""
    section, group = fork_group(lock)
    source = group.get('source')
    if not isinstance(source, dict) or not source:
        raise ReleaseError(f'inputs.lock.json {section}.{FORK_GROUP} has no "source" record (commit, tree, tag, '
                           'tag_commit, build_route, archive): it moves together with the group from "work" to "fetch"')
    return section, group, source


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def fnv1a64(data):
    """The add-on's 64-bit FNV-1a file hash, as 16 hex digits (the profile and loader manifests use it)."""
    value = 0xcbf29ce484222325
    for byte in data:
        value = ((value * 0x100000001b3) & 0xffffffffffffffff) ^ byte
    return f'{value:016x}'


def load_lock():
    return json.loads(LOCK_PATH.read_text())


def lock_group(lock, group):
    """A group of the lock's "fetch", "work" or "tree" section, or None."""
    return lock['fetch'].get(group) or lock['work'].get(group) or lock.get('tree', {}).get(group)


def add_arguments(parser):
    """Add one option per setting; each defaults to its environment variable."""
    group = parser.add_argument_group('locations (each option defaults to the environment variable shown)')
    for name, (variable, option, default, text) in SETTINGS.items():
        group.add_argument(option, dest=name, metavar=dict(clang='EXE', gcc='EXE', toolchain='DIR|pinned',
                                                           packages='DIRS').get(name, 'PATH'),
                           help=f'{text} [{variable}' + (f', default {default}]' if default else ']'))
    group.add_argument('--offline', action='store_true', help='never download; fail if a pinned input is not cached')


class Config:
    """Resolved locations. Use Config.from_args() in scripts, Config() for environment-only use."""

    def __init__(self, values=None, offline=False):
        values = values or {}
        self.offline = offline
        self.values = {}
        explicit = set()
        for name, (variable, _option, default, _text) in SETTINGS.items():
            value = values.get(name) or os.environ.get(variable)
            if value:
                explicit.add(name)
            self.values[name] = value or default
        self.lock = load_lock()
        self.fetched = {}  # fetch group -> checked cache directory
        self._toolchain = None
        if self.values['toolchain'] and explicit & set(TOOLCHAIN_SETTINGS):
            names = ', '.join(SETTINGS[n][0] for n in TOOLCHAIN_SETTINGS if n in explicit)
            raise ReleaseError(f'XEMFG_TOOLCHAIN provides clang, gcc and Wine\'s headers and libraries itself; {names} '
                               'cannot be set with it')

    @classmethod
    def from_args(cls, args):
        return cls({name: getattr(args, name, None) for name in SETTINGS}, offline=getattr(args, 'offline', False))

    def path(self, name):
        value = self.values[name]
        return Path(value).expanduser().resolve() if value else None

    @property
    def build(self):
        return self.path('build')

    @property
    def cache(self):
        """XEMFG_CACHE, else <build>/cache: a cache outside the build directory is never taken for repository files."""
        return self.path('cache') or self.build / 'cache'

    # -- the toolchain: the host's tools, or the pinned folder of release/toolchain.py (XEMFG_TOOLCHAIN)
    def toolchain_root(self):
        """The pinned toolchain folder, or None for the host's tools. Only the location: toolchain() prepares it."""
        value = self.values['toolchain']
        if not value:
            return None
        if value == 'pinned':
            from toolchain import pins_id  # local import: toolchain imports this module
            return self.cache / f'toolchain-{pins_id()}'
        return Path(value).expanduser().resolve()

    @property
    def pinned_toolchain(self):
        return bool(self.values['toolchain'])

    def toolchain(self):
        """The pinned toolchain's record (toolchain.json), prepared on first use; None for the host's tools."""
        root = self.toolchain_root()
        if root is None:
            return None
        if self._toolchain is None:
            from toolchain import ensure
            self._toolchain = ensure(self, root)
        return self._toolchain

    def in_toolchain(self, path):
        root = self.toolchain_root()
        return bool(root) and Path(path).resolve().is_relative_to(root)

    def _tool(self, name):
        return str(self.toolchain_root() / 'bin' / name) if self.toolchain() else None

    @property
    def clang(self):
        return self._tool('clang') or self.values['clang']

    @property
    def lld(self):
        """The ld.lld that clang -fuse-ld=lld runs (clang's own directory; for the host, the one on PATH)."""
        return self._tool('ld.lld') or 'ld.lld'

    @property
    def gcc(self):
        return self._tool('gcc') or self.values['gcc']

    @property
    def wine_include(self):
        if self.toolchain():
            return self.toolchain_root() / self._toolchain['wine_include']
        return self.path('wine_include')

    @property
    def wine_lib(self):
        if self.toolchain():
            return self.toolchain_root() / self._toolchain['wine_lib']
        return self.path('wine_lib')

    def dxc(self):
        """The dxc binary, or None when XEMFG_DXC is not set."""
        location = self.path('dxc')
        if location is None:
            return None
        binary = location / 'bin' / 'dxc' if location.is_dir() else location
        if not binary.is_file():
            raise ReleaseError(f'XEMFG_DXC does not name dxc or a directory with bin/dxc: {location}')
        return binary

    def work_dir(self, group):
        """Directory of a "work" input group: its override variable, else XEMFG_WORK/<locked path>."""
        entry = self.lock['work'][group]
        override = WORK_OVERRIDES.get(group)
        if override and self.path(override):
            folder = self.path(override)
        elif self.path('work'):
            folder = self.path('work') / entry['path']
        elif group in IN_TREE and IN_TREE[group].is_dir():
            folder = IN_TREE[group]
        else:
            variable = SETTINGS[override][0] if override else None
            raise ReleaseError(f'Input "{group}" lives in the work directory: set XEMFG_WORK (or --work)'
                               + (f', or {variable}' if variable else '') + f' (expected <work>/{entry["path"]})')
        if not folder.is_dir():
            raise ReleaseError(f'Input "{group}" not found: {folder}')
        return folder

    def fork_source(self):
        """The OptiScaler fork's git checkout: XEMFG_OPTISCALER_SOURCE, else XEMFG_WORK/<locked source_in_work> (a fork
        group whose source record names no work checkout, such as the fetch group of the fork's release, needs
        XEMFG_OPTISCALER_SOURCE)."""
        _section, _group, entry = fork_source_record(self.lock)
        in_work = entry.get('source_in_work')
        if self.path('optiscaler_source'):
            folder = self.path('optiscaler_source')
        elif self.path('work') and in_work:
            folder = self.path('work') / in_work
        else:
            expected = f' (expected <work>/{in_work})' if in_work else ''
            raise ReleaseError('The source companion reads the OptiScaler fork checkout: set XEMFG_OPTISCALER_SOURCE '
                               '(or --optiscaler-source)' + (' or XEMFG_WORK (or --work)' if in_work else '') + expected)
        if not (folder / '.git').exists():
            raise ReleaseError(f'Not a git checkout of the OptiScaler fork: {folder}')
        return folder

    def fetched_dir(self, group):
        """Cache directory of a "fetch" input group (one directory per group and pinned commit)."""
        entry = self.lock['fetch'][group]
        return self.cache / f'{group}-{entry["commit"][:12]}'

    def tree_dir(self, group):
        """Directory of a "tree" input group: committed files of this repository (inputs.lock.json "tree": path)."""
        folder = REPO / self.lock['tree'][group]['path']
        if not folder.is_dir():
            raise ReleaseError(f'Input "{group}" not found: {folder}')
        return folder

    def input_dir(self, group):
        if group in self.lock.get('tree', {}):
            return self.tree_dir(group)
        if group in self.lock['fetch']:
            if group not in self.fetched:
                from fetch import ensure  # local import: fetch imports this module
                self.fetched[group] = ensure(self, group)
            return self.fetched[group]
        if group in self.lock['work']:
            return self.work_dir(group)
        raise ReleaseError(f'Unknown input group: {group}')

    def input_file(self, group, name):
        """A file of a locked input group, after checking its sha256 against the lock."""
        entry = lock_group(self.lock, group)
        if entry is None or name not in entry['files']:
            raise ReleaseError(f'{group}/{name} is not in inputs.lock.json')
        path = self.input_dir(group) / name
        if not path.is_file():
            raise ReleaseError(f'Missing input {group}/{name}: {path}')
        expected = entry['files'][name]['sha256']
        if sha256(path) != expected:
            raise ReleaseError(f'Input {group}/{name} differs from the lock (expected {expected}): {path}')
        return path

    def check_group(self, group):
        """Check every locked file of a group; returns its directory."""
        entry = lock_group(self.lock, group)
        for name in entry['files']:
            self.input_file(group, name)
        return self.input_dir(group)


def tool_version(command):
    """First line of a tool's version output, or None when it cannot run."""
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or out.stderr).strip()
    return text.splitlines()[0] if text else None


def relative(path, config):
    """A path for records: relative to the repository, the build directory or the cache, never absolute."""
    path = Path(path).resolve()
    root = config.toolchain_root()
    if root and path.is_relative_to(root):
        # the pinned toolchain's files get the names the host's installation gives them (system-header digests)
        for base, label in ((root / 'tools/usr/include/wine', '$WINE_INCLUDE'),
                            (root / 'tools/usr/lib/wine/x86_64-windows', '$WINE_LIB')):
            if path == base:
                return label
            if path.is_relative_to(base):
                return f'{label}/{path.relative_to(base)}'
        return f'$SYSTEM/{path.name}'
    bases = [(config.cache, '$CACHE'), (config.build, '$BUILD'), (REPO, '$REPO')]
    for base, label in bases:
        if path == base:
            return label
        if path.is_relative_to(base):
            return f'{label}/{path.relative_to(base)}'
    for group in config.lock['work']:
        try:
            folder = config.work_dir(group)
        except ReleaseError:
            continue
        if path.is_relative_to(folder):
            return f'$WORK[{group}]/{path.relative_to(folder)}'
    for base, label in ((config.path('wine_include'), '$WINE_INCLUDE'), (config.path('wine_lib'), '$WINE_LIB')):
        if base and path == base:
            return label
        if base and path.is_relative_to(base):
            return f'{label}/{path.relative_to(base)}'
    return f'$SYSTEM/{path.name}'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    config = Config.from_args(parser.parse_args())
    shown = {name: (str(config.path(name)) if name not in ('clang', 'gcc', 'toolchain', 'packages') and config.values[name]
                    else config.values[name]) for name in SETTINGS}
    shown['cache'] = str(config.cache)
    root = config.toolchain_root()
    if root:
        shown['toolchain'] = str(root)
    print(json.dumps(shown, indent=2))


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        sys.exit(f'error: {error}')
