#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fetch the pinned, unmodified upstream files the installer needs (dependencies.json).

Every file belongs to a group:

- payload: a fresh OptiScaler setup: files of its nightly archive and OptiPatcher;
- runtime: what every installation needs: Intel's XeFG/XeLL runtime and its licence (bin/ and LICENSE.txt of Intel's
  XeSS repository at a pinned commit, equal to Intel's XeSS SDK 3.0.2 release and to the members of the same names in
  the OptiScaler nightly archive) and the BC250 FSR4 DLL (public bc250-fsr4-fork release). The installer places only
  these DLLs; the notices pinned beside them stay in the cache, and the package carries its own copies (licenses/);
- dlss: NVIDIA's DLSS helper (nvngx_dlss.dll, DLSS Super Resolution) with its licence, fetched only when the installer
  places it: a fresh OptiScaler setup on a DLSS input where OptiScaler's own search finds no nvngx_dlss.dll of the
  game's (install.py dlss_helper_plan).

Each file names its upstream input in 'sources' and may list mirrors: other inputs that hold the same bytes (Intel's
runtime is also in Intel's repository at the v3.0.2 tag, in the XeSS SDK 3.0.2 release archive and in the OptiScaler
nightly archive). An input already in the cache (or already downloaded for another file), or one another missing file
needs anyway, is used first, then the others in order; a candidate that cannot be downloaded (any network or TLS error,
also partway through) or does not hold the pinned bytes is skipped for the next one. Downloads and extracted files are
checked against their pinned SHA-256 and kept in the user's cache, so each is downloaded once. Archive members are
extracted by exact name to stdout: archive paths never control filesystem writes, links, permissions or executable bits.
"""
import fcntl, hashlib, http.client, json, os, shutil, subprocess, tempfile, urllib.error, urllib.request
from pathlib import Path

# The interface install.py expects: prepare(package, groups) and the groups/runtime/sources layout of dependencies.json.
# install.py refuses a dependencies.py without this value (an earlier build's prepare(package) fetches no runtime).
FORMAT = 2
# What prepare() fetches when the caller names no groups: a fresh setup and the runtime every install needs. The DLSS
# helper is not among them: the installer asks for it when it places it.
DEFAULT_GROUPS = ('payload', 'runtime')
DOWNLOAD_LIMIT = 512 * 1024 * 1024
# What a download can raise that means "this source did not deliver": URLError/HTTPError, TLS (ssl.SSLError), resets,
# timeouts and other socket errors (all OSError), and malformed or truncated HTTP (HTTPException, IncompleteRead).
NETWORK_ERRORS = (OSError, http.client.HTTPException)


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def cache_dir():
    return Path(os.environ.get('XDG_CACHE_HOME', str(Path.home()/'.cache')))/'bc250-xefg-testers'


def pinned_files(pins, groups):
    """{name: sha256} of every file in groups. A name pinned by two groups must have one digest."""
    expected = {}
    for group in groups:
        if group not in pins:
            raise ValueError('Unknown dependency group: ' + group)
        for name, digest in pins[group]['Files'].items():
            if Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('Unsafe dependency name: ' + name)
            if expected.setdefault(name, digest) != digest:
                raise ValueError('Conflicting pins for ' + name)
    return expected


def source(pins, name):
    """(input, archive member or None for the whole download) of a pinned file's primary source. A file without an
    entry in 'sources' is the member of the same name in the OptiScaler archive."""
    entry = pins.get('sources', {}).get(name, {'input': 'opti', 'member': name})
    return entry['input'], entry.get('member')


def candidates(pins, name):
    """[(input, member)] of a pinned file: its primary source, then its mirrors in order."""
    entry = pins.get('sources', {}).get(name, {'input': 'opti', 'member': name})
    found = []
    for item in [entry, *entry.get('mirrors', [])]:
        if item['input'] not in pins['inputs']:
            raise ValueError('Unknown dependency input for ' + name + ': ' + item['input'])
        if (item['input'], item.get('member')) not in found:
            found.append((item['input'], item.get('member')))
    return found


def cached(item, cache):
    """The pinned download is already in the cache with its pinned bytes."""
    dest = cache/item['file']
    return dest.is_file() and not dest.is_symlink() and sha(dest) == item['sha256']


def download(item, cache):
    """The pinned download in the cache, fetched when missing or different."""
    dest = cache/item['file']
    if cached(item, cache):
        return dest
    print('Downloading ' + item['file'] + ' from upstream…', flush=True)
    request = urllib.request.Request(item['url'], headers={'User-Agent': 'freefg-installer/1'})

    def unreachable(error):
        # A plain URLError wraps the cause ("<urlopen error ...>"); an HTTPError names its status itself. As a ValueError,
        # prepare() moves on to the next source.
        reason = error.reason if type(error) is urllib.error.URLError else error
        return ValueError('Cannot download ' + item['file'] + ' from ' + item['url'] + ' (' + str(reason) + '). The first '
                          'installation needs internet access, or this file already in ' + str(cache) + '.')
    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as output:
        temporary = Path(output.name)
        try:
            try:
                response = urllib.request.urlopen(request, timeout=90)
            except NETWORK_ERRORS as error:
                raise unreachable(error) from error
            with response:
                size = 0
                while True:
                    # Only the network reads are wrapped: a failing cache write (a full disk) stays an OSError.
                    try:
                        data = response.read(1024 * 1024)
                    except NETWORK_ERRORS as error:
                        raise unreachable(error) from error
                    if not data:
                        break
                    size += len(data)
                    if size > DOWNLOAD_LIMIT:
                        raise ValueError('Dependency exceeds download size limit')
                    output.write(data)
            output.flush()
            if 'size' in item and size != item['size']:
                raise ValueError('Download size mismatch: ' + item['file'])
            if sha(temporary) != item['sha256']:
                raise ValueError('Download checksum mismatch: ' + item['file'])
            os.replace(temporary, dest)
        finally:
            temporary.unlink(missing_ok=True)
    return dest


def prepare(package, groups=DEFAULT_GROUPS):
    """Directory holding every pinned file of groups (package/dependencies.json), downloading what is missing."""
    pins = json.loads((Path(package)/'dependencies.json').read_text())
    expected = pinned_files(pins, groups)
    cache = cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    with (cache/'prepare.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        target = cache/'payload'

        def present(name):
            path = target/name
            return path.is_file() and not path.is_symlink() and sha(path) == expected[name]
        missing = [name for name in expected if not present(name)]
        if not missing:
            return target
        options = {name: candidates(pins, name) for name in missing}
        if not shutil.which('bsdtar'):
            # Without bsdtar only whole-file downloads can be used; a file with no such source cannot be prepared.
            options = {name: [c for c in found if c[1] is None] for name, found in options.items()}
            if not all(options.values()):
                raise ValueError('Setup needs bsdtar (libarchive) to unpack its downloads. Install it and run setup again.')
        # Inputs that are the only source of some missing file are downloaded anyway; mirrors that are already in the
        # cache cost nothing. Both come before an input that would be downloaded for one file alone.
        needed = {found[0][0] for found in options.values() if len(found) == 1}
        is_cached = {key: cached(pins['inputs'][key], cache) for key in {c[0] for found in options.values() for c in found}}
        downloads, failed = {}, {}
        with tempfile.TemporaryDirectory(dir=cache) as scratch:
            staging = Path(scratch)
            for name in missing:
                order = sorted(options[name], key=lambda c: (not (is_cached[c[0]] or c[0] in downloads), c[0] not in needed))
                dest = staging/name
                dest.parent.mkdir(parents=True, exist_ok=True)
                problems = []
                for key, member in order:
                    try:
                        if key in failed:
                            raise failed[key]
                        if key not in downloads:
                            try:
                                downloads[key] = download(pins['inputs'][key], cache)
                            except ValueError as error:
                                failed[key] = error
                                raise
                        if member is None:
                            shutil.copyfile(downloads[key], dest)
                        else:
                            with dest.open('wb') as output:
                                subprocess.run(['bsdtar', '-xOf', str(downloads[key]), member], stdout=output, check=True, timeout=90)
                        if sha(dest) != expected[name]:
                            raise ValueError('Unexpected dependency: ' + name)
                        if problems:
                            print(name + ': ' + pins['inputs'][problems[0][0]]['file'] + ' was not usable; the same bytes came from ' +
                                  pins['inputs'][key]['file'] + '.', flush=True)
                        break
                    except (ValueError, subprocess.SubprocessError) as error:
                        dest.unlink(missing_ok=True)
                        problems.append((key, error))
                else:
                    first = problems[0][1]
                    others = [pins['inputs'][key]['url'] for key, _ in problems[1:]]
                    if not others:
                        raise first
                    raise ValueError(str(first) + ' Also tried ' + ', '.join(others) + ': ' +
                                     '; '.join(str(error) for _, error in problems[1:])) from first
            for name in missing:
                dest = target/name
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging/name, dest)
        return target
