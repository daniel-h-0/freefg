# SPDX-License-Identifier: MIT
"""Shared helpers of the CI scripts in release/ci (see toolchain.py for what CI pins and why).

Nothing here is specific to one machine: locations come from the release build's own settings (release/config.py:
XEMFG_BUILD, XEMFG_CACHE, XEMFG_DXC, ...) and from the variables GitHub Actions sets (GITHUB_ENV, GITHUB_STEP_SUMMARY).
Outside GitHub Actions the annotations are printed as plain lines and nothing is appended to the environment files.
"""
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

CI = Path(__file__).resolve().parent
RELEASE = CI.parent
REPO = RELEASE.parent
CI_LOCK = CI / 'ci.lock.json'
WORKFLOWS = REPO / '.github' / 'workflows'
USER_AGENT = 'release-ci-pin-check'

sys.path.insert(0, str(RELEASE))
from config import Config, ReleaseError, load_lock, sha256  # noqa: E402,F401  (re-exported for the CI scripts)


def load_ci_lock():
    return json.loads(CI_LOCK.read_text())


def on_github():
    return os.environ.get('GITHUB_ACTIONS') == 'true'


def annotate(level, message, title=None):
    """A GitHub Actions annotation (error, warning, notice); a plain prefixed line elsewhere."""
    message = str(message).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    if on_github():
        print(f'::{level}' + (f' title={title}' if title else '') + f'::{message}', flush=True)
    else:
        print(f'{level}: ' + (f'{title}: ' if title else '') + message.replace('%0A', '\n').replace('%25', '%'),
              file=sys.stderr, flush=True)


def append_env(name, value):
    """Export a variable to the following workflow steps (GITHUB_ENV); printed elsewhere."""
    target = os.environ.get('GITHUB_ENV')
    if target:
        with open(target, 'a') as stream:
            stream.write(f'{name}={value}\n')
    print(f'{name}={value}')


def step_summary(markdown):
    """Append Markdown to the job summary (GITHUB_STEP_SUMMARY); ignored outside GitHub Actions."""
    target = os.environ.get('GITHUB_STEP_SUMMARY')
    if target:
        with open(target, 'a') as stream:
            stream.write(markdown.rstrip('\n') + '\n\n')


def download(url, destination=None, limit=1 << 30, timeout=120):
    """(sha256, bytes) of a download, streamed; written to destination when given (atomically, after the read)."""
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    digest, size = hashlib.sha256(), 0
    partial = Path(str(destination) + '.partial') if destination else None
    stream = partial.open('wb') if partial else None
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            while block := response.read(1 << 20):
                size += len(block)
                if size > limit:
                    raise ReleaseError(f'{url} exceeds {limit} bytes')
                digest.update(block)
                if stream:
                    stream.write(block)
        if stream:
            stream.close()
            stream = None
            partial.replace(destination)
    finally:
        if stream:
            stream.close()
        if partial and partial.exists():
            partial.unlink()
    return digest.hexdigest(), size


def build_config(**values):
    """The release build's Config (environment variables as the release scripts read them)."""
    return Config(values or None)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
