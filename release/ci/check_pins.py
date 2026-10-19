#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check that every pinned download still serves its pinned bytes (scheduled CI, .github/workflows/pins.yml).

Pins checked, each downloaded in full and hashed (nothing downloaded is executed or unpacked onto the tree):

  build     release/inputs.lock.json "fetch": every file of every group at its locked commit (the URLs fetch.py uses)
  installer packaging/dependencies.json "inputs": every download an installation makes, with its size when pinned;
            then the installer's own dependencies.prepare() runs on those downloads in a scratch cache, which unpacks
            each pinned member and checks it against its per-file pin, exactly as a player's first install does
  ci        release/ci/ci.lock.json: the Arch Linux Archive package files (snapshot and package archive), the DXC
            release, and the container image digest (a registry manifest request, no layers downloaded)

  python3 release/ci/check_pins.py [--only build,installer,ci] [--list] [--report FILE]

--list prints the URLs without any network access. Exit status 1 when a download fails (after retries), differs from
its pin, or the installer's preparation fails. A pin that has moved upstream must be changed in its lock and the
change qualified like any other input change; this check only reports it.
"""
import argparse
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, USER_AGENT, ReleaseError, annotate, download, load_ci_lock, load_lock, step_summary, write_json  # noqa: E402

DEPENDENCIES = REPO / 'packaging' / 'dependencies.json'
REGISTRY = 'https://registry-1.docker.io'
MANIFEST_TYPES = ', '.join(('application/vnd.oci.image.index.v1+json', 'application/vnd.docker.distribution.manifest.list.v2+json',
                            'application/vnd.oci.image.manifest.v1+json',
                            'application/vnd.docker.distribution.manifest.v2+json'))
RETRIES = 3
KINDS = ('build', 'installer', 'ci')


def pins_build():
    for group, entry in load_lock()['fetch'].items():
        for name, item in entry['files'].items():
            yield dict(kind='build', name=f'{group}/{name}', sha256=item['sha256'],
                       url=entry['url'].format(commit=entry['commit'], path=item.get('source', name)))


def pins_installer():
    pins = json.loads(DEPENDENCIES.read_text())
    for key, item in pins.get('inputs', {}).items():
        yield dict(kind='installer', name=f'inputs.{key} ({item.get("file", "")})', url=item['url'], sha256=item['sha256'],
                   bytes=item.get('size'), key=key, file=item.get('file'))


def pins_ci():
    ci = load_ci_lock()
    server = ci['snapshot']['server'].format(date=ci['snapshot']['date'])
    for name, entry in ci['packages'].items():
        url = server.replace('$repo', entry['repo']).replace('$arch', 'x86_64') + '/' + entry['file']
        yield dict(kind='ci', name=f'package {name} {entry["version"]}', url=url, sha256=entry['sha256'],
                   bytes=entry.get('bytes'))
    for name, entry in ci['archived'].items():
        yield dict(kind='ci', name=f'archived package {name} {entry["version"]}', url=entry['url'], sha256=entry['sha256'],
                   bytes=entry.get('bytes'))
    entry = ci['dxc']
    yield dict(kind='ci', name=f'DXC {entry["release"]}', url=entry['url'], sha256=entry['sha256'], bytes=entry.get('bytes'))
    image = ci['image']
    repository, _, _tag = image['name'].partition(':')
    if '/' not in repository:
        repository = 'library/' + repository
    yield dict(kind='ci', name=f'container image {image["name"]}', image=repository, digest=image['digest'],
               url=f'{REGISTRY}/v2/{repository}/manifests/{image["digest"]}')


def with_retries(action):
    for attempt in range(1, RETRIES + 1):
        try:
            return action()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            if attempt == RETRIES or (isinstance(error, urllib.error.HTTPError) and error.code in (403, 404, 410)):
                raise
            time.sleep(10 * attempt)


def check_image(pin):
    """The registry still serves the manifest the digest names (and reports that digest)."""
    def fetch():
        token_url = f'https://auth.docker.io/token?service=registry.docker.io&scope=repository:{pin["image"]}:pull'
        with urllib.request.urlopen(urllib.request.Request(token_url, headers={'User-Agent': USER_AGENT}), timeout=60) as r:
            token = json.load(r)['token']
        request = urllib.request.Request(pin['url'], method='HEAD', headers={
            'User-Agent': USER_AGENT, 'Authorization': f'Bearer {token}', 'Accept': MANIFEST_TYPES})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.headers.get('Docker-Content-Digest')
    served = with_retries(fetch)
    return dict(served_digest=served, ok=served == pin['digest'])


def check_download(pin, keep=None):
    target = keep / pin['file'] if keep is not None and pin.get('file') else None
    digest, size = with_retries(lambda: download(pin['url'], target, limit=1 << 31))
    ok = digest == pin['sha256'] and (pin.get('bytes') is None or size == pin['bytes'])
    return dict(served_sha256=digest, served_bytes=size, ok=ok)


def prepare_installer(cache_root):
    """packaging/dependencies.py prepare() over every group of dependencies.json, from the downloads already in its
    cache (it downloads anything missing itself), in a scratch XDG_CACHE_HOME."""
    sys.path.insert(0, str(DEPENDENCIES.parent))
    try:
        import dependencies
    finally:
        sys.path.pop(0)
    pins = json.loads(DEPENDENCIES.read_text())
    groups = tuple(name for name, value in pins.items() if isinstance(value, dict) and 'Files' in value)
    previous = os.environ.get('XDG_CACHE_HOME')
    os.environ['XDG_CACHE_HOME'] = str(cache_root)
    try:
        folder = Path(dependencies.prepare(DEPENDENCIES.parent, groups))
        files = sum(1 for p in folder.rglob('*') if p.is_file())
    finally:
        if previous is None:
            os.environ.pop('XDG_CACHE_HOME', None)
        else:
            os.environ['XDG_CACHE_HOME'] = previous
    return dict(groups=list(groups), files=files)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--only', default=','.join(KINDS), help='comma-separated subset of ' + ', '.join(KINDS))
    parser.add_argument('--list', action='store_true', help='print the pinned URLs without downloading')
    parser.add_argument('--report', type=Path, help='also write the results as JSON')
    args = parser.parse_args()
    kinds = [k for k in args.only.split(',') if k]
    unknown = sorted(set(kinds) - set(KINDS))
    if unknown:
        parser.error('unknown kinds: ' + ', '.join(unknown))
    sources = dict(build=pins_build, installer=pins_installer, ci=pins_ci)
    pins = [pin for kind in kinds for pin in sources[kind]()]
    if args.list:
        print(json.dumps([{k: v for k, v in pin.items() if k in ('kind', 'name', 'url', 'sha256', 'digest', 'bytes')}
                          for pin in pins], indent=2))
        return
    results, problems = [], []
    with tempfile.TemporaryDirectory(prefix='pin-check-') as scratch_name:
        scratch = Path(scratch_name)
        installer_cache = None
        if 'installer' in kinds:
            sys.path.insert(0, str(DEPENDENCIES.parent))
            try:
                import dependencies
                os.environ['XDG_CACHE_HOME'] = str(scratch)
                installer_cache = Path(dependencies.cache_dir())
            finally:
                sys.path.pop(0)
            installer_cache.mkdir(parents=True, exist_ok=True)
        for pin in pins:
            started = time.monotonic()
            try:
                if 'image' in pin:
                    outcome = check_image(pin)
                else:
                    outcome = check_download(pin, installer_cache if pin['kind'] == 'installer' else None)
            except Exception as error:  # noqa: BLE001 - every failure is reported, the remaining pins still run
                outcome = dict(ok=False, error=f'{type(error).__name__}: {error}')
            outcome['seconds'] = round(time.monotonic() - started, 1)
            results.append(dict(pin, **outcome))
            if not outcome['ok']:
                problems.append(f'{pin["name"]}: ' + outcome.get('error', f'served {outcome.get("served_sha256") or outcome.get("served_digest")}'))
            print(('ok    ' if outcome['ok'] else 'FAIL  ') + f'{pin["name"]}  {pin["url"]}', flush=True)
        prepared = None
        if 'installer' in kinds and not any(not r['ok'] for r in results if r['kind'] == 'installer'):
            try:
                prepared = prepare_installer(scratch)
                print(f'ok    installer preparation: {prepared["files"]} files of groups {", ".join(prepared["groups"])}')
            except Exception as error:  # noqa: BLE001
                prepared = dict(error=f'{type(error).__name__}: {error}')
                problems.append(f'installer preparation (dependencies.prepare): {prepared["error"]}')
    report = dict(checked=len(results), failed=len(problems), problems=problems, installer_preparation=prepared,
                  results=results)
    if args.report:
        write_json(args.report, report)
    rows = '\n'.join(f'| {"ok" if r["ok"] else "**FAIL**"} | {r["kind"]} | {r["name"]} |' for r in results)
    step_summary(f'### Pinned downloads\n\n| Result | Kind | Pin |\n| --- | --- | --- |\n{rows}\n\n'
                 + (f'Installer preparation: {prepared}\n\n' if prepared is not None else '')
                 + (f'**{len(problems)} problem(s).**' if problems else f'All {len(results)} pins serve their bytes.'))
    for problem in problems:
        annotate('error', problem, title='pinned download')
    print(json.dumps(dict(checked=len(results), failed=len(problems), installer_preparation=prepared), indent=2))
    if problems:
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        annotate('error', error, title='pinned downloads')
        sys.exit(1)
