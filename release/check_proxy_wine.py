#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""CPU-only check of the enabler-free proxy (release/build_proxy.py output) with Wine's real loader; no GPU work.

src/game/test_proxy_load.c is compiled to a console program and run under `wine` in a private prefix
(<build>/proxy-wine-check/prefix), with no display and no D3D12 device, in three folders laid out as an installation:
  pinned     libxess_fg.dll (the proxy) + bc250_xefg_original.dll (Intel's runtime, the locked bytes) + Intel's libxell.dll
             expected: the forwarded xefgSwapChainGetVersion reports Intel's version from bc250_xefg_original.dll; the
             wrapped xefgSwapChainD3D12CreateContext(NULL) reaches Intel's runtime (its own error for a NULL device, not
             CANT_LOAD_LIBRARY); the settings interface answers (Intel-free: no filters); version.dll is not loaded;
             BC250-MFG.log says the proxy is ready
  altered    the same with one byte of bc250_xefg_original.dll changed
             expected: the wrapped entry refuses (CANT_LOAD_LIBRARY, -11) without loading it, and the log says why
  missing    the proxy alone
             expected: the same refusal

  python3 release/check_proxy_wine.py           # writes <build>/proxy-wine-check/result.json; exit 1 on a failed check
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import REPO, Config, ReleaseError, add_arguments, sha256  # noqa: E402
import build_proxy  # noqa: E402

CANT_LOAD_LIBRARY = -11


def compile_program(config, xess, output):
    wine = config.wine_include
    subprocess.run([config.clang, '--target=x86_64-w64-windows-gnu', '-fms-extensions', '-D__WINE_USE_MSVCRT',
                    '-isystem', str(wine / 'msvcrt'), '-isystem', str(wine / 'windows'), '-I', str(xess / 'inc/xess_fg'),
                    '-I', str(REPO / 'src'), '-O2', '-Wall', '-Wextra', '-nostdlib', '-fuse-ld=lld',
                    '-Wl,--entry,mainCRTStartup', '-Wl,--subsystem,console', '-Wl,--no-insert-timestamp',
                    '-L' + str(config.wine_lib), str(REPO / 'src/game/test_proxy_load.c'), '-lkernel32', '-lucrtbase',
                    '-o', str(output)], check=True, capture_output=True)


def run(folder, prefix, forwarders):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('WINE', 'DISPLAY', 'WAYLAND', 'XEFG_', 'BC250_'))}
    env.update(WINEPREFIX=str(prefix), WINEDEBUG='-all', WINEDLLOVERRIDES='mscoree,mshtml=', PROXY_CHECK_FORWARDERS='1' if forwarders else '0')
    out = subprocess.run(['wine', str(folder / 'test_proxy_load.exe')], cwd=folder, env=env, capture_output=True, text=True,
                         timeout=600)
    log = folder / 'BC250-MFG.log'
    return dict(returncode=out.returncode, stdout=out.stdout.replace('\r', ''), log=log.read_text() if log.is_file() else None)


def field(text, pattern):
    match = re.search(pattern, text)
    return match.groups() if match else None


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    args = parser.parse_args()
    config = Config.from_args(args)
    if not shutil.which('wine'):
        raise ReleaseError('wine is not installed')
    _base, definition, _defines = build_proxy.definitions()
    built = config.build / definition['addon']['output_dir']
    proxy, record = built / definition['addon']['output'], json.loads((built / 'build.json').read_text())
    if not proxy.is_file() or sha256(proxy) != record['sha256']:
        raise ReleaseError('No current proxy build: run release/build_proxy.py first')
    runtime = config.input_file(build_proxy.RUNTIME_GROUP, build_proxy.RUNTIME_FILE)
    xess = config.check_group('intel-xess')
    work = config.build / 'proxy-wine-check'
    for name in ('pinned', 'altered', 'missing'):
        shutil.rmtree(work / name, ignore_errors=True)
    work.mkdir(exist_ok=True)
    program = work / 'test_proxy_load.exe'
    compile_program(config, xess, program)
    original = definition['addon']['original']
    results, problems = {}, []
    for case in ('pinned', 'altered', 'missing'):
        folder = work / case
        folder.mkdir()
        shutil.copy2(program, folder / program.name)
        shutil.copy2(proxy, folder / 'libxess_fg.dll')
        if case != 'missing':
            data = bytearray(runtime.read_bytes())
            if case == 'altered':
                data[len(data) // 2] ^= 0x01
            (folder / original).write_bytes(bytes(data))
        results[case] = run(folder, work / 'prefix', forwarders=case == 'pinned')
        stdout, log = results[case]['stdout'], results[case]['log'] or ''
        if results[case]['returncode'] or 'DONE' not in stdout:
            problems.append(f'{case}: the program did not finish (exit {results[case]["returncode"]})')
            continue
        wrapped = field(stdout, r'WRAPPED \S+ result=(-?\d+) in_proxy=(\d) original_loaded=(\d)')
        settings = field(stdout, r'SETTINGS ok=(\d) ready=(\d+) resolution=(\d+) downscale_mask=(\d+) upscale_mask=(\d+)')
        if field(stdout, r'ENABLER version_dll_loaded=(\d)') != ('0',):
            problems.append(f'{case}: version.dll was loaded')
        if not wrapped or wrapped[1] != '1':
            problems.append(f'{case}: xefgSwapChainD3D12CreateContext is not implemented by the proxy')
            continue
        if case == 'pinned':
            forwarded = field(stdout, r'FORWARDED \S+ result=(-?\d+) version=(\S+) module=(.*) in_proxy=(\d)')
            if not forwarded or forwarded[0] != '0' or not forwarded[2].lower().endswith(original) or forwarded[3] != '0':
                problems.append(f'pinned: the forwarded entry did not reach {original}: {forwarded}')
            if int(wrapped[0]) == CANT_LOAD_LIBRARY or wrapped[2] != '1':
                problems.append(f'pinned: the wrapped entry did not reach Intel\'s runtime: {wrapped}')
            if not settings or settings[0] != '1' or settings[3:] != ('0', '0'):
                problems.append(f'pinned: settings interface {settings}')
            if 'MFG proxy ready' not in log:
                problems.append('pinned: BC250-MFG.log lacks the ready line')
        else:
            if int(wrapped[0]) != CANT_LOAD_LIBRARY or wrapped[2] != '0':
                problems.append(f'{case}: the wrapped entry was not refused before loading the runtime: {wrapped}')
            if 'not the pinned Intel XeFG runtime' not in log:
                problems.append(f'{case}: BC250-MFG.log does not say why XeFG is unavailable')
    report = dict(proxy_sha256=record['sha256'], runtime_sha256=sha256(runtime), program_sha256=sha256(program),
                  wine=subprocess.run(['wine', '--version'], capture_output=True, text=True).stdout.strip(),
                  cases=results, problems=problems, result='pass' if not problems else 'fail')
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(result=report['result'], problems=problems,
                          stdout={case: r['stdout'].strip().splitlines() for case, r in results.items()}), indent=2))
    if problems:
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        sys.exit(f'error: {error}')
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors='replace') if isinstance(error.stderr, bytes) else (error.stderr or '')
        sys.exit(f'error: command failed ({error.returncode}): {" ".join(map(str, error.cmd))[:300]}\n{detail[-3000:]}')
