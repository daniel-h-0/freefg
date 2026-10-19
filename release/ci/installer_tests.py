#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the installer unit tests that release/package.json lists ("installer_tests"), each in its own process from
scripts/ (as release/assemble.py does), and report how many tests ran, failed and were skipped per module.

  python3 release/ci/installer_tests.py [--fail-on-skip] [--unprivileged-user NAME] [--report FILE]

--fail-on-skip treats a skipped test as a failure: in CI every tool the tests need (bsdtar among them) is installed,
so a skip means the environment is incomplete rather than that the test does not apply.

--unprivileged-user NAME, when this runs as root (a CI container job), runs the tests as that user instead (created
with useradd when missing; runuser from util-linux): the tests model a player's account, and some of them depend on
file permissions that root ignores (test_recipes makes a settings file unreadable and expects Restore to say so).
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO, RELEASE, ReleaseError, annotate, step_summary, write_json  # noqa: E402

RAN = re.compile(r'^Ran (\d+) tests? in ', re.M)
STATUS = re.compile(r'^(OK|FAILED)(?: \((.*)\))?\s*$', re.M)


def as_user(user):
    """The command prefix that drops root to user (created when missing); none when not root or no user named."""
    if not user or os.geteuid() != 0:
        return []
    if subprocess.run(['id', '-u', user], capture_output=True).returncode != 0:
        subprocess.run(['useradd', '--create-home', '--user-group', user], check=True)
    return ['runuser', '-u', user, '--']


def run(module, prefix=()):
    started = time.monotonic()
    out = subprocess.run([*prefix, sys.executable, '-m', 'unittest', '-v', module], cwd=REPO / 'scripts',
                         capture_output=True, text=True, timeout=1800)
    text = out.stderr
    ran = RAN.findall(text)
    status = STATUS.findall(text)
    counts = dict(failures=0, errors=0, skipped=0, expected_failures=0, unexpected_successes=0)
    if status:
        for item in filter(None, (status[-1][1] or '').split(', ')):
            key, _, value = item.partition('=')
            counts[key.replace(' ', '_')] = int(value)
    return dict(module=module, returncode=out.returncode, ran=int(ran[-1]) if ran else 0,
                status=status[-1][0] if status else 'unknown', seconds=round(time.monotonic() - started, 1),
                skipped_tests=re.findall(r'^(\S+ \(\S+\)) \.\.\. skipped (.*)$', text, re.M), **counts,
                tail=text[-3000:] if out.returncode else '')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--fail-on-skip', action='store_true', help='a skipped test fails the run')
    parser.add_argument('--unprivileged-user', metavar='NAME', help='when root, run the tests as this user')
    parser.add_argument('--report', type=Path, help='also write the results as JSON')
    args = parser.parse_args()
    modules = json.loads((RELEASE / 'package.json').read_text())['installer_tests']
    prefix = as_user(args.unprivileged_user)
    results = [run(module, prefix) for module in modules]
    problems = [f'{r["module"]}: {r["status"]} (exit {r["returncode"]})' for r in results if r['returncode']]
    if args.fail_on_skip:
        problems += [f'{r["module"]}: {r["skipped"]} skipped' for r in results if r['skipped']]
    for result in results:
        if result['returncode']:
            print(f'--- {result["module"]}\n{result["tail"]}', file=sys.stderr)
    total = dict(modules=len(results), tests=sum(r['ran'] for r in results), skipped=sum(r['skipped'] for r in results),
                 failed_modules=sum(1 for r in results if r['returncode']),
                 user=args.unprivileged_user if prefix else ('root' if os.geteuid() == 0 else 'current'))
    rows = '\n'.join(f'| {r["module"]} | {r["ran"]} | {r["status"]} | {r["skipped"]} |' for r in results)
    step_summary(f'### Installer tests\n\n| Module | Tests | Result | Skipped |\n| --- | --- | --- | --- |\n{rows}\n\n'
                 f'{total["tests"]} tests in {total["modules"]} modules.')
    if args.report:
        write_json(args.report, dict(total=total, results=results))
    print(json.dumps(dict(total=total, results=[{k: v for k, v in r.items() if k != 'tail'} for r in results]), indent=2))
    if problems:
        raise ReleaseError('Installer tests: ' + '; '.join(problems))


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        annotate('error', error, title='installer tests')
        sys.exit(1)
