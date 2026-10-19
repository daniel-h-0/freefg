#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fetch the pinned public build inputs listed under "fetch" in inputs.lock.json.

Each group (Intel's XeSS SDK headers, MinHook, licence texts) is fetched file by file from its repository at the
locked commit into its own directory, <cache>/<group>-<commit[:12]>, and every file is checked against its locked
sha256 before the directory is put in place. Nothing fetched is executed; the build only compiles or copies it.
A group already in the cache is re-checked, not downloaded again.

  python3 release/fetch.py              # every group
  python3 release/fetch.py intel-xess   # one group
"""
import argparse
import hashlib
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import Config, ReleaseError, add_arguments, sha256  # noqa: E402

TIMEOUT = 60


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'freefg-release-fetch'})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def cached(config, group):
    """True when the group's cache directory holds every locked file with the locked hash."""
    folder = config.fetched_dir(group)
    files = config.lock['fetch'][group]['files']
    return folder.is_dir() and all((folder / name).is_file() and sha256(folder / name) == entry['sha256']
                                   for name, entry in files.items())


def ensure(config, group):
    """The group's cache directory, fetched first when missing or incomplete."""
    entry = config.lock['fetch'].get(group)
    if entry is None:
        raise ReleaseError(f'Unknown fetch group: {group}')
    folder = config.fetched_dir(group)
    if cached(config, group):
        return folder
    if config.offline:
        raise ReleaseError(f'{group} is not in the cache ({folder}) and --offline forbids downloading')
    config.cache.mkdir(parents=True, exist_ok=True)
    # A new, empty directory per download; it replaces the group's directory only after every file checks out.
    staging = Path(tempfile.mkdtemp(prefix=f'.{group}-', dir=config.cache))
    try:
        for name, item in entry['files'].items():
            url = entry['url'].format(commit=entry['commit'], path=item.get('source', name))
            data = download(url)
            actual = hashlib.sha256(data).hexdigest()
            if actual != item['sha256']:
                raise ReleaseError(f'{group}/{name} from {url} has sha256 {actual}, locked {item["sha256"]}')
            target = staging / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if folder.exists():
            shutil.rmtree(folder)
        staging.rename(folder)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return folder


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('groups', nargs='*', help='fetch groups (default: all)')
    add_arguments(parser)
    args = parser.parse_args()
    config = Config.from_args(args)
    for group in args.groups or list(config.lock['fetch']):
        folder = ensure(config, group)
        print(f'{group}: {len(config.lock["fetch"][group]["files"])} files checked in {folder}')


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        sys.exit(f'error: {error}')
