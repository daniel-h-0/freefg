#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the present-pacing Vulkan layer libxefg_wave.so as shipped in tester v30, after its unit tests.

Unit tests (each built with gcc -O1 -g and the sanitizers shown, run, and required to end with a PASS line and to
print no sanitizer report; UBSan reports are made fatal with -fno-sanitize-recover=undefined):
  test_present_pacer        ASan/UBSan
  test_wave_layer           ASan/UBSan
  test_present_concurrency  ASan/UBSan
  test_present_concurrency  ThreadSanitizer
  test_wave_layer           ThreadSanitizer
The layer itself is built twice with v30's command (gcc -O2 -shared -fPIC -Wall -Wextra src/game/wave_layer.c
-lpthread) and both builds must be identical. <build>/layer/build.json records the result without absolute paths.

Exit status 0 when the build matches the reference hash in inputs.lock.json (or --no-reference-check), 1 otherwise.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import REPO, RELEASE, Config, ReleaseError, add_arguments, relative, sha256, tool_version  # noqa: E402

OUTPUT_NAME = 'libxefg_wave.so'
SOURCE = REPO / 'src/game/wave_layer.c'
SANITIZE_ASAN = ['-fsanitize=address,undefined', '-fno-sanitize-recover=undefined']
SANITIZE_TSAN = ['-fsanitize=thread']
SANITIZER_REPORTS = ('runtime error:', 'AddressSanitizer', 'LeakSanitizer', 'UndefinedBehaviorSanitizer',
                     'ThreadSanitizer')
TESTS = [
    ('test_present_pacer', SANITIZE_ASAN),
    ('test_wave_layer', SANITIZE_ASAN),
    ('test_present_concurrency', SANITIZE_ASAN),
    ('test_present_concurrency', SANITIZE_TSAN),
    ('test_wave_layer', SANITIZE_TSAN),
]
TEST_TIMEOUT = 600


def layer_command(config, output):
    return [config.gcc, '-O2', '-shared', '-fPIC', '-Wall', '-Wextra', str(SOURCE), '-o', str(output), '-lpthread']


def run_tests(config, folder):
    results = []
    for test, flags in TESTS:
        kind = 'tsan' if flags is SANITIZE_TSAN else 'asan'
        exe = folder / f'{test}-{kind}'
        subprocess.run([config.gcc, '-O1', '-g', *flags, str(REPO / f'src/game/{test}.c'), '-o', str(exe), '-lpthread', '-lm'],
                       check=True, capture_output=True)
        out = subprocess.run([str(exe)], capture_output=True, text=True, timeout=TEST_TIMEOUT)
        lines = out.stdout.strip().splitlines()
        reported = any(marker in out.stderr for marker in SANITIZER_REPORTS)
        if out.returncode or reported or not lines or not lines[-1].startswith('PASS'):
            raise ReleaseError(f'{test} {" ".join(flags)} failed:\n' + out.stdout[-1500:] + out.stderr[-3000:])
        results.append(dict(test=test, sanitizer=' '.join(flags), result=lines[-1]))
    return results


def dependencies(config):
    out = subprocess.run([config.gcc, '-M', str(SOURCE)], capture_output=True, text=True, check=True).stdout
    text = out.replace('\\\n', ' ').split(':', 1)[1]
    return sorted(Path(p.replace('\\ ', ' ')).resolve() for p in re.split(r'(?<!\\)\s+', text) if p)


def header_name(path):
    """A system header's name below its include directory (vulkan/vulkan.h), independent of where it is installed."""
    parts = path.parts
    last = max((i for i, part in enumerate(parts) if part == 'include'), default=len(parts) - 2)
    return '/'.join(parts[last + 1:])


def build(config, tests=True):
    out = config.build / 'layer'
    if out.exists():
        shutil.rmtree(out)
    (out / 'tests').mkdir(parents=True)
    test_results = run_tests(config, out / 'tests') if tests else []
    output = out / OUTPUT_NAME
    digests = set()
    for _ in range(2):
        subprocess.run(layer_command(config, output), check=True, capture_output=True)
        digests.add(sha256(output))
    if len(digests) != 1:
        raise ReleaseError('Two builds of the layer differ')
    depends = dependencies(config)
    own = [p for p in depends if p.is_relative_to(REPO) and not config.in_toolchain(p)
           and not (p.is_relative_to(config.build) or p.is_relative_to(config.cache))]
    system = sorted(f'{header_name(p)}\t{sha256(p)}\n' for p in depends
                    if config.in_toolchain(p) or not p.is_relative_to(REPO))
    # The tests and the build tooling count as sources too: assemble.py rechecks them, so a stale build is never packaged.
    own = set(own) | {REPO / f'src/game/{t}.c' for t, _ in TESTS} | {Path(__file__).resolve(), RELEASE / 'config.py'}
    digest = sha256(output)
    reference = config.lock.get('outputs', {}).get(OUTPUT_NAME)
    command = layer_command(config, output)
    record = dict(
        output=OUTPUT_NAME, sha256=digest, reference_sha256=reference, matches_reference=digest == reference,
        command=[relative(a, config) if a.startswith('/') else a for a in command],
        sources={str(p.relative_to(REPO)): sha256(p) for p in sorted(own)},
        system_headers=dict(count=len(system), sha256=hashlib.sha256(''.join(system).encode()).hexdigest()),
        toolchain=dict(gcc=tool_version([config.gcc, '--version']),
                       pinned=config.toolchain()['id'] if config.pinned_toolchain else None),
        unit_tests=test_results or 'skipped',
    )
    (out / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
    if config.pinned_toolchain:
        differences = toolchain_differences(config, record)
        if differences:
            raise ReleaseError('The pinned toolchain did not give the locked build environment: ' + '; '.join(differences))
    return output, record


def toolchain_differences(config, record):
    """The layer record's system headers and gcc against inputs.lock.json toolchain.layer."""
    locked = config.lock.get('toolchain', {}).get('layer', {})
    found = []
    if locked.get('system_headers') and record['system_headers'] != locked['system_headers']:
        found.append(f'system headers {record["system_headers"]} (locked {locked["system_headers"]})')
    if locked.get('gcc') and record['toolchain']['gcc'] != locked['gcc']:
        found.append(f'gcc {record["toolchain"]["gcc"]!r} (locked {locked["gcc"]!r})')
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    parser.add_argument('--skip-tests', action='store_true', help='build without running the unit tests')
    parser.add_argument('--no-reference-check', action='store_true', help='exit 0 even when the output differs from the lock')
    args = parser.parse_args()
    config = Config.from_args(args)
    output, record = build(config, tests=not args.skip_tests)
    locked = config.lock.get('toolchain', {}).get('layer', {}).get('system_headers')
    if locked and locked != record['system_headers']:
        print('warning: system headers differ from the locked toolchain; byte identity is not expected', file=sys.stderr)
    print(json.dumps(dict(output=relative(output, config), sha256=record['sha256'], reference=record['reference_sha256'],
                          matches_reference=record['matches_reference'],
                          unit_tests=[f'{t["test"]} ({t["sanitizer"]}): {t["result"]}' for t in record['unit_tests']]
                          if isinstance(record['unit_tests'], list) else record['unit_tests']), indent=2))
    if not record['matches_reference'] and not args.no_reference_check:
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        sys.exit(f'error: {error}')
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors='replace') if isinstance(error.stderr, bytes) else (error.stderr or '')
        sys.exit(f'error: command failed ({error.returncode}): {" ".join(map(str, error.cmd))[:300]}\n{detail[-3000:]}')
