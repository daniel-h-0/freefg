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
             (--variant intel-free-mfg: and BC250-MFG.log has no FAST_COEXIST line: the runtime's entry table was read
             from the file and the unhooked runtime is not taken for a hooked one)
  altered    the same with one byte of bc250_xefg_original.dll changed
             expected: the wrapped entry refuses (CANT_LOAD_LIBRARY, -11) without loading it, and the log says why
  missing    the proxy alone
             expected: the same refusal
  hooked     (--variant intel-free-mfg only) as pinned, then the program writes a jump at eight of Intel's entries in its
             own process to a stub that records its caller, standing in for another module that hooks Intel's runtime
             expected: CreateContext, both initialisations, Destroy, D3D12GetSwapChainPtr and TagFrameConstants reach the
             stub with the program as the caller (tail calls); GetLastPresentStatus and SetNumInterpolatedFrames with the
             proxy as the caller; one stub call each (no status read for a NULL handle); BC250-MFG.log has the
             FAST_COEXIST line naming the program. Two stand-in modules (src/game/test_proxy_caller.c, built here with a
             version resource whose ProductName is "OptiScaler" or another product) then call CreateContext: the stub
             sees each module as the caller; only the OptiScaler one reaches the proxy's candidate check (CONTEXT_CALLER
             in the log, ended there by BC250_XEFG_DISABLE=1), while the program and the other module are logged as not
             accelerated beside another module (FAST_SKIP ... only OptiScaler's own contexts)
  unit       (--variant intel-free-mfg only) src/game/test_proxy_coexist.c: the proxy's bookkeeping beside another
             module (mfg_proxy_coexist.h with the real scoped forwarding objects and stand-ins for the rest; fake COM
             objects, no runtime): which contexts are scoped, claims by output pointer or device, releases, capacity,
             the deferred initialisation work, frame counts, references all released at the end
             expected: exit 0 and COEXIST_UNIT failures=0

  python3 release/check_proxy_wine.py [--variant intel-free-mfg]
      writes <build>/proxy-wine-check[-<variant>]/result.json; exit 1 on a failed check
"""
import argparse
import json
import os
import re
import shutil
import struct
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


def version_resource(product):
    """A .res file (as llvm-rc writes one) holding a VS_VERSION_INFO whose StringFileInfo has ProductName and
    OriginalFilename; lld links it into a module's resources, so no resource compiler is needed."""
    def pad(data):
        return data + b'\0' * (-len(data) % 4)

    def node(key, value=b'', text=False, children=()):
        body = pad(struct.pack('<HHH', 0, 0, 0) + (key + '\0').encode('utf-16-le')) + value
        for child in children:
            body = pad(body) + child
        return struct.pack('<HHH', len(body), len(value) // 2 if text else len(value), int(text)) + body[6:]

    strings = [node(key, (value + '\0').encode('utf-16-le'), True)
               for key, value in (('ProductName', product), ('OriginalFilename', product + '.dll'))]
    fixed = struct.pack('<13I', 0xFEEF04BD, 0x10000, 0x10000, 0, 0x10000, 0, 0x3f, 0, 4, 2, 0, 0, 0)
    info = node('VS_VERSION_INFO', fixed, children=[node('StringFileInfo', text=True,
                                                         children=[node('040904B0', text=True, children=strings)])])
    header = struct.pack('<HHHHIHHII', 0xFFFF, 16, 0xFFFF, 1, 0, 0x30, 0x409, 0, 0)  # RT_VERSION, ID 1, en-US
    empty = struct.pack('<II', 0, 32) + struct.pack('<HHHHIHHII', 0xFFFF, 0, 0xFFFF, 0, 0, 0, 0, 0, 0)
    return empty + pad(struct.pack('<II', len(info), 8 + len(header)) + header + info)


def compile_caller(config, xess, product, folder, output):
    """src/game/test_proxy_caller.c as a DLL whose version resource names the product."""
    resource = folder / (output.stem + '.res')
    resource.write_bytes(version_resource(product))
    wine = config.wine_include
    subprocess.run([config.clang, '--target=x86_64-w64-windows-gnu', '-fms-extensions', '-D__WINE_USE_MSVCRT',
                    '-isystem', str(wine / 'msvcrt'), '-isystem', str(wine / 'windows'), '-I', str(xess / 'inc/xess_fg'),
                    '-O2', '-Wall', '-Wextra', '-nostdlib', '-fuse-ld=lld', '-shared', '-Wl,--entry,DllMainCRTStartup',
                    '-Wl,--no-insert-timestamp', '-L' + str(config.wine_lib), str(REPO / 'src/game/test_proxy_caller.c'),
                    str(resource), '-lkernel32', '-o', str(output)], check=True, capture_output=True)


CALLERS = {'stand_in_optiscaler.dll': 'OptiScaler', 'stand_in_other.dll': 'Other product'}


def compile_unit(config, xess, folder, output):
    """src/game/test_proxy_coexist.c (the multi-frame proxy's bookkeeping beside another module, with stand-ins for
    the rest of the add-on), linked with the committed COM thunks and a version resource whose product is OptiScaler."""
    resource = folder / (output.stem + '.res')
    resource.write_bytes(version_resource('OptiScaler'))
    wine = config.wine_include
    subprocess.run([config.clang, '--target=x86_64-w64-windows-gnu', '-fms-extensions', '-D__WINE_USE_MSVCRT',
                    '-DXEFG_PROXY_MFG=1', '-DXEFG_MFG_RETIRE=1', '-isystem', str(wine / 'msvcrt'), '-isystem', str(wine / 'windows'),
                    '-I', str(xess / 'inc/xess_fg'), '-I', str(REPO / 'src'), '-I', str(REPO / 'src/game'),
                    '-I', str(build_proxy.common.COM_THUNKS), '-O2', '-Wall', '-Wextra', '-Wno-unused-function',
                    '-nostdlib', '-fuse-ld=lld', '-Wl,--entry,mainCRTStartup', '-Wl,--subsystem,console',
                    '-Wl,--no-insert-timestamp', '-L' + str(config.wine_lib), str(REPO / 'src/game/test_proxy_coexist.c'),
                    str(build_proxy.common.COM_THUNKS / 'com_thunks.S'), str(resource), '-lkernel32', '-lucrtbase',
                    '-o', str(output)], check=True, capture_output=True)


def run(folder, prefix, forwarders, hooks=False):
    env = {k: v for k, v in os.environ.items() if not k.startswith(('WINE', 'DISPLAY', 'WAYLAND', 'XEFG_', 'BC250_'))}
    env.update(WINEPREFIX=str(prefix), WINEDEBUG='-all', WINEDLLOVERRIDES='mscoree,mshtml=', PROXY_CHECK_FORWARDERS='1' if forwarders else '0',
               PROXY_CHECK_HOOKS='1' if hooks else '0')
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
    parser.add_argument('--variant', choices=sorted(build_proxy.VARIANTS), default=build_proxy.DEFAULT_VARIANT,
                        help=f'the proxy build to check (default {build_proxy.DEFAULT_VARIANT})')
    args = parser.parse_args()
    config = Config.from_args(args)
    if not shutil.which('wine'):
        raise ReleaseError('wine is not installed')
    _base, definition, _defines = build_proxy.definitions(args.variant)
    coexist = args.variant == 'intel-free-mfg'
    built = config.build / definition['addon']['output_dir']
    proxy, record = built / definition['addon']['output'], json.loads((built / 'build.json').read_text())
    if not proxy.is_file() or sha256(proxy) != record['sha256']:
        raise ReleaseError('No current proxy build: run release/build_proxy.py first')
    runtime = config.input_file(build_proxy.RUNTIME_GROUP, build_proxy.RUNTIME_FILE)
    xess = config.check_group('intel-xess')
    work = config.build / ('proxy-wine-check' if args.variant == build_proxy.DEFAULT_VARIANT else f'proxy-wine-check-{args.variant}')
    cases = ('pinned', 'altered', 'missing') + (('hooked',) if coexist else ())
    for name in cases + ('unit',):
        shutil.rmtree(work / name, ignore_errors=True)
    work.mkdir(exist_ok=True)
    program = work / 'test_proxy_load.exe'
    compile_program(config, xess, program)
    callers = {}
    if coexist:
        for name, product in CALLERS.items():
            callers[name] = work / name
            compile_caller(config, xess, product, work, callers[name])
        unit = work / 'test_proxy_coexist.exe'
        compile_unit(config, xess, work, unit)
    original = definition['addon']['original']
    results, problems = {}, []
    for case in cases:
        folder = work / case
        folder.mkdir()
        shutil.copy2(program, folder / program.name)
        shutil.copy2(proxy, folder / 'libxess_fg.dll')
        if case == 'hooked':
            for name, built in callers.items():
                shutil.copy2(built, folder / name)
        if case != 'missing':
            data = bytearray(runtime.read_bytes())
            if case == 'altered':
                data[len(data) // 2] ^= 0x01
            (folder / original).write_bytes(bytes(data))
        results[case] = run(folder, work / 'prefix', forwarders=case in ('pinned', 'hooked'), hooks=case == 'hooked')
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
        if case == 'hooked':
            if field(stdout, r'HOOKS written=(\d)') != ('1',):
                problems.append('hooked: the stand-in hooks were not written')
            for name, expected in (('xefgSwapChainD3D12CreateContext', 'program'), ('xefgSwapChainD3D12InitFromSwapChain', 'program'),
                                   ('xefgSwapChainD3D12InitFromSwapChainDesc', 'program'), ('xefgSwapChainDestroy', 'program'),
                                   ('xefgSwapChainTagFrameConstants', 'program'), ('xefgSwapChainD3D12GetSwapChainPtr', 'program'),
                                   ('xefgSwapChainGetLastPresentStatus', 'proxy'), ('xefgSwapChainSetNumInterpolatedFrames', 'proxy')):
                seen = field(stdout, r'HOOKED ' + name + r' result=(-?\d+) caller_in_program=(\d) caller_in_proxy=(\d) calls=(\d+)')
                want = ('-77', '1', '0', '1') if expected == 'program' else ('-77', '0', '1', '1')
                if seen != want:
                    problems.append(f'hooked: {name} reached the stand-in hook as {seen}, expected {want} (caller: {expected})')
            if not re.search(r'FAST_COEXIST another module hooks Intel\'s XeFG runtime \(\w+: its code was changed; jumps to '
                             r'test_proxy_load\.exe\)', log):
                problems.append('hooked: BC250-MFG.log lacks the FAST_COEXIST line naming the program')
            if 'entry table could not be read' in log:
                problems.append('hooked: the runtime\'s entry table was not read from the file')
            for name in CALLERS:
                seen = field(stdout, r'CALLER ' + re.escape(name) + r' loaded=(\d) result=(-?\d+) caller_in_module=(\d) calls=(\d+)')
                if seen != ('1', '-77', '1', '1'):
                    problems.append(f'hooked: {name} reached the stand-in hook as {seen}, expected loaded, -77, its own call')
            skipped = re.findall(r'FAST_SKIP beside another module hooking Intel\'s XeFG runtime only OptiScaler\'s own contexts '
                                 r'are accelerated; this one \(created from ([^)]+)\)', log)
            if sorted(skipped) != ['stand_in_other.dll', 'test_proxy_load.exe']:
                problems.append(f'hooked: contexts logged as not OptiScaler\'s: {skipped}, expected the program and '
                                'stand_in_other.dll')
            candidates = [line.rsplit('\\', 1)[-1] for line in re.findall(r'CONTEXT_CALLER (.*)', log)]
            if candidates != ['stand_in_optiscaler.dll']:
                problems.append(f'hooked: contexts that reached the candidate check: {candidates}, expected only '
                                'stand_in_optiscaler.dll')
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
            if coexist and 'FAST_COEXIST' in log:
                problems.append('pinned: the unhooked runtime was taken for a hooked one, or its entry table was not read: '
                                + '; '.join(line for line in log.splitlines() if 'FAST_COEXIST' in line))
        else:
            if int(wrapped[0]) != CANT_LOAD_LIBRARY or wrapped[2] != '0':
                problems.append(f'{case}: the wrapped entry was not refused before loading the runtime: {wrapped}')
            if 'not the pinned Intel XeFG runtime' not in log:
                problems.append(f'{case}: BC250-MFG.log does not say why XeFG is unavailable')
    if coexist:
        folder = work / 'unit'
        folder.mkdir()
        shutil.copy2(unit, folder / unit.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('WINE', 'DISPLAY', 'WAYLAND', 'XEFG_', 'BC250_'))}
        env.update(WINEPREFIX=str(work / 'prefix'), WINEDEBUG='-all', WINEDLLOVERRIDES='mscoree,mshtml=')
        ran = subprocess.run(['wine', str(folder / unit.name)], cwd=folder, env=env, capture_output=True, text=True, timeout=600)
        stdout = ran.stdout.replace('\r', '')
        results['unit'] = dict(returncode=ran.returncode, stdout=stdout, log=None)
        failed = [line for line in stdout.splitlines() if line.startswith('FAIL ')]
        if ran.returncode or 'COEXIST_UNIT failures=0' not in stdout or failed:
            problems.append(f'unit: exit {ran.returncode}; ' + ('; '.join(failed) or 'no COEXIST_UNIT failures=0 line'))
    report = dict(variant=args.variant, proxy_sha256=record['sha256'], runtime_sha256=sha256(runtime), program_sha256=sha256(program),
                  callers={name: sha256(path) for name, path in callers.items()},
                  unit_sha256=sha256(unit) if coexist else None,
                  wine=subprocess.run(['wine', '--version'], capture_output=True, text=True).stdout.strip(),
                  cases=results, problems=problems, result='pass' if not problems else 'fail')
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(result=report['result'], problems=problems,
                          stdout={case: [line for line in r['stdout'].strip().splitlines() if not line.startswith('ok line=')]
                                  for case, r in results.items()}), indent=2))
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
