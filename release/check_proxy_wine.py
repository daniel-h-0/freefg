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
  f4q-*      (variants built with XEFG_F4Q) src/game/test_f4q.c: F4Q's switch, model segment, pipelines and geometry,
             fallback and diagnostic check (src/model_f4q.h, src/game/f4q.h and the real settings reader, with mock
             D3D12 objects), one folder per case with its own BC250-XeFG/settings.ini:
               default     the package's settings.ini (F4Q=1): on; b3941ac8 and f030948d created from <hash>.f4q.dxil
                           (F4Q_REPLACE), another shader from its <hash>.dxil; F(4x4) geometry only for a dispatch that
                           binds a F(4x4) pipeline, none left after the context's release; segment sizes 36,864 /
                           73,728 bytes; no hook installed and no line of the check
               no-ini      no settings file: on
               ini-off     settings.ini F4Q=0: off (F(2x2) files and geometry, no segment, no F4Q_REPLACE)
               env-off     BC250_XEFG_F4Q=0 over settings.ini F4Q=1: off
               env-on      BC250_XEFG_F4Q=on over settings.ini F4Q=0: on
               shadow-off  BC250_XEFG_F4Q=0 with BC250_XEFG_F4Q_SHADOW=1: off, no line of the check
               fallback    on, b3941ac8's F(4x4) pipeline cannot be created and f030948d's F(4x4) file is missing:
                           both F4Q_FALLBACK, F(2x2) pipelines and geometry
               layout      on, but a model layout without the row16 segment: off (the kernels' offsets do not hold)
               shadow      BC250_XEFG_F4Q_SHADOW=1: F(2x2) output and geometry; at each target dispatch the F(4x4)
                           dispatch with the runtime's state and groups, its fingerprint, the runtime's own dispatch with
                           its state, the F(2x2) fingerprint and the compare with the right point and tags; nothing at
                           another shader; a z != 1 dispatch skipped; the stamped readback logged as F4Q_COUNT, then the
                           release-time status and summary; every reference released at release
               pack        the model owner's segment of a 2304- and a 4608-byte model equal to an independent product
             expected: each case exits 0 with DONE and the lines above

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
F4Q_DEC, F4Q_ENC, F4Q_OTHER = 'b3941ac8ff95efe7', 'f030948d38e74671', '1a3b0782583fef19'
# case: (test mode, environment, settings.ini text, 'package' for the package's file, or None for no file)
F4Q_CASES = {
    'default': ('switch', {}, 'package'),
    'no-ini': ('switch', {}, None),
    'ini-off': ('switch', {}, '[BC250]\nResolutionMode=0\nF4Q=0\n'),
    'env-off': ('switch', {'BC250_XEFG_F4Q': '0'}, 'package'),
    'env-on': ('switch', {'BC250_XEFG_F4Q': 'on'}, '[BC250]\nF4Q=0\n'),
    'shadow-off': ('switch', {'BC250_XEFG_F4Q': '0', 'BC250_XEFG_F4Q_SHADOW': '1'}, 'package'),
    'fallback': ('fallback', {}, 'package'),
    'layout': ('layout', {}, 'package'),
    'shadow': ('shadow', {'BC250_XEFG_F4Q_SHADOW': '1'}, 'package'),
    'pack': ('pack', {}, 'package'),
}


def compile_f4q(config, xess, output):
    """src/game/test_f4q.c with the multi-frame proxy's definitions F4Q depends on."""
    wine = config.wine_include
    subprocess.run([config.clang, '--target=x86_64-w64-windows-gnu', '-fms-extensions', '-D__WINE_USE_MSVCRT',
                    '-DXEFG_PROXY_MFG=1', '-DXEFG_INTEL_FREE=1', '-DXEFG_MFG_SETTINGS=1', '-DXEFG_F4Q=1',
                    '-isystem', str(wine / 'msvcrt'), '-isystem', str(wine / 'windows'), '-I', str(xess / 'inc/xess_fg'),
                    '-I', str(REPO / 'src'), '-I', str(REPO / 'src/game'), '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-function', '-nostdlib', '-fuse-ld=lld', '-Wl,--entry,mainCRTStartup',
                    '-Wl,--subsystem,console', '-Wl,--no-insert-timestamp', '-L' + str(config.wine_lib),
                    str(REPO / 'src/game/test_f4q.c'), '-lkernel32', '-lucrtbase', '-o', str(output)],
                   check=True, capture_output=True)


def run_f4q(program, work, case):
    mode, extra, ini = F4Q_CASES[case]
    folder = work / f'f4q-{case}'
    (folder / 'shaders').mkdir(parents=True)
    shutil.copy2(program, folder / program.name)
    if ini is not None:
        (folder / 'BC250-XeFG').mkdir()
        text = (REPO / 'release/files/BC250-XeFG-settings.ini').read_text() if ini == 'package' else ini
        (folder / 'BC250-XeFG/settings.ini').write_text(text)
    env = {k: v for k, v in os.environ.items() if not k.startswith(('WINE', 'DISPLAY', 'WAYLAND', 'XEFG_', 'BC250_'))}
    env.update(WINEPREFIX=str(work / 'prefix'), WINEDEBUG='-all', WINEDLLOVERRIDES='mscoree,mshtml=', **extra)
    shaders = 'Z:' + str(folder / 'shaders').replace('/', '\\')
    ran = subprocess.run(['wine', str(folder / program.name), mode, shaders], cwd=folder, env=env, capture_output=True,
                         text=True, timeout=600)
    return dict(returncode=ran.returncode, stdout=ran.stdout.replace('\r', ''), log=None)


def f4q_consts(line):
    return [int(x) for x in re.search(r' c=([0-9,]+)', line).group(1).split(',')]


def f4q_problems(results):
    """What the F4Q cases' output (F4Q_CASES) shows that it should not."""
    problems = []

    def need(ok, what):
        if not ok:
            problems.append(what)

    for case, r in results.items():
        text = r['stdout']
        need(r['returncode'] == 0 and text.rstrip().endswith('DONE'), f'f4q-{case}: exit {r["returncode"]}, last line '
             f'{text.strip().splitlines()[-1:] if text.strip() else None}')
        need('MODEL_FAIL' not in text and 'TEST ' not in text, f'f4q-{case}: model_fail or a test error')
    D, E, O = F4Q_DEC, F4Q_ENC, F4Q_OTHER
    on_lines = [f'PSO {D} hr=0x00000000 name=f4q-dec', f'PSO {E} hr=0x00000000 name=f4q-enc',
                f'PSO {O} hr=0x00000000 name=exact-other', f'GEOM {D} pso=f4q-dec -2 2 1', f'GEOM {E} pso=f4q-enc -4 2 2',
                f'GEOM {O} pso=exact-other 2 4 1', f'GEOM {D} pso=stranger 1 4 1', 'SEGMENT 2304=36864 4608=73728 9216=0',
                'VTABLE unchanged=1', 'TICKS 0 OWN 0', f'F4Q_REPLACE {D} {D}.f4q.dxil 7', f'F4Q_REPLACE {E} {E}.f4q.dxil 7']
    off_lines = [f'PSO {D} hr=0x00000000 name=exact-dec', f'PSO {E} hr=0x00000000 name=exact-enc',
                 f'PSO {O} hr=0x00000000 name=exact-other', f'GEOM {D} pso=exact-dec 1 4 1', f'GEOM {E} pso=exact-enc 1 2 2',
                 'SEGMENT 2304=0 4608=0 9216=0', 'VTABLE unchanged=1', 'TICKS 0 OWN 0']
    check_only = ('F4Q_SHADOW_PSO', 'F4Q_INSTALLED', 'F4Q_STATUS', 'F4Q_COUNT', 'F4Q_SUMMARY', 'F4Q_SKIP', 'F4Q_STOP')
    for case, source in (('default', 'default'), ('no-ini', 'default'), ('env-on', 'BC250_XEFG_F4Q')):
        text = results.get(case, {}).get('stdout', '')
        lines = text.splitlines()
        need(f'F4Q_CONFIG mode=on source={source} (' in text and 'CONFIG mode=1' in lines, f'f4q-{case}: not on from {source}')
        for want in on_lines:
            need(want in lines, f'f4q-{case}: no line {want!r}')
        need(lines.count(f'GEOM {D} pso=f4q-dec -2 2 1') == 2 and lines.count(f'F4Q_REPLACE {D} {D}.f4q.dxil 7') == 2,
             f'f4q-{case}: the second b3941ac8 pipeline is not F(4x4) with its geometry')
        need(lines[-3:-1] == [f'GEOM {D} pso=f4q-dec 1 4 1', 'TICKS 0 OWN 0'], f'f4q-{case}: F(4x4) geometry after release')
        need(not any(line.startswith(check_only) for line in lines), f'f4q-{case}: lines of the check without its variable')
    for case, source in (('ini-off', 'settings.ini'), ('env-off', 'BC250_XEFG_F4Q'), ('shadow-off', 'BC250_XEFG_F4Q')):
        text = results.get(case, {}).get('stdout', '')
        lines = text.splitlines()
        need(f'F4Q_CONFIG mode=off source={source} (' in text and 'CONFIG mode=0' in lines, f'f4q-{case}: not off from {source}')
        for want in off_lines:
            need(want in lines, f'f4q-{case}: no line {want!r}')
        need(not any(line.startswith(('F4Q_REPLACE', 'F4Q_FALLBACK') + check_only) for line in lines),
             f'f4q-{case}: F4Q_REPLACE, F4Q_FALLBACK or a line of the check while off')
    text = results.get('fallback', {}).get('stdout', '')
    lines = text.splitlines()
    need(f'F4Q_FALLBACK {D} pipeline creation failed (hr=0x80070057): the F(2x2) kernel runs for this pipeline' in lines,
         'f4q-fallback: no fallback line for the failed b3941ac8 pipeline')
    need(f'F4Q_FALLBACK {E} its F4Q file cannot be read (hr=0x00000000): the F(2x2) kernel runs for this pipeline' in lines,
         'f4q-fallback: no fallback line for the missing f030948d file')
    for want in (f'PSO {D} hr=0x00000000 name=exact-dec', f'PSO {E} hr=0x00000000 name=exact-enc',
                 f'GEOM {D} pso=exact-dec 1 4 1', f'GEOM {E} pso=exact-enc 1 2 2', 'CONFIG mode=1'):
        need(want in lines, f'f4q-fallback: no line {want!r}')
    need(not any(line.startswith('F4Q_REPLACE') for line in lines), 'f4q-fallback: a F(4x4) pipeline was noted')
    text = results.get('layout', {}).get('stdout', '')
    lines = text.splitlines()
    need('F4Q_CONFIG mode=off source=layout (' in text and 'CONFIG mode=0' in lines and 'SEGMENT 2304=0 4608=0 9216=0' in lines
         and f'PSO {D} hr=0x00000000 name=exact-dec' in lines, 'f4q-layout: F4Q not off for a layout it was not built for')
    lines = results.get('pack', {}).get('stdout', '').splitlines()
    for bytes_, size, values in ((2304, 36864, 9216), (4608, 73728, 18432)):
        packed = [line for line in lines if line.startswith(f'PACK bytes={bytes_} ')]
        m = re.fullmatch(r'PACK bytes=\d+ segment=(\d+) values=(\d+) differing=(\d+) maxabs=(\d+)', packed[0]) if packed else None
        need(m is not None and int(m[1]) == size and int(m[2]) == values and m[3] == '0' and int(m[4]) <= 73728,
             f'f4q-pack: {packed[:1]} (want segment {size}, {values} values, 0 differing, |U\'| <= 73728)')
        need(any(line.startswith(f'F4Q_SEGMENT bytes={bytes_} tbase=') for line in lines), f'f4q-pack: no F4Q_SEGMENT for {bytes_}')
    # the check (research build ce02's test, with this build's names)
    shadow = results.get('shadow', {}).get('stdout', '')
    need('F4Q_CONFIG mode=shadow source=BC250_XEFG_F4Q_SHADOW' in shadow and 'CONFIG mode=2' in shadow.splitlines(),
         'f4q-shadow: not in the check')
    need('PIPELINES dec=exact-dec enc=exact-enc other=exact-other' in shadow and f'GEOM {D} pso=exact-dec 1 4 1' in shadow,
         'f4q-shadow: the F(2x2) pipelines or geometry are not the runtime\'s')
    need('VTABLE unchanged=0' in shadow and 'F4Q_INSTALLED' in shadow and 'F4Q_REPLACE' not in shadow, 'f4q-shadow: hooks')
    pso_lines = re.findall(r'^F4Q_SHADOW_PSO (\S+) bytes=\d+ ok$', shadow, re.M)
    need(sorted(pso_lines) == sorted([D, E]), f'f4q-shadow: F(4x4) pipelines {pso_lines}')
    lines = [line for line in shadow.splitlines() if line.startswith(('OWN ', 'INTEL ', 'F4Q_SKIP'))]
    expect_groups = {('f4q-enc', '80,12,1'): '20,24,2', ('f4q-dec', '40,12,1'): '20,24,1', ('f4q-dec', '80,23,1'): '40,46,1'}
    fp_size = {'f4q-enc': '10,6,2', 'f4q-dec-half': '20,12,1', 'f4q-dec-full': '40,23,1'}
    point_of = {'f4q-enc': 2, 'f4q-dec-half': 1, 'f4q-dec-full': 0}
    i, targets, compares, others = 0, 0, 0, 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r'OWN pso=(f4q-(?:dec|enc)) groups=(\S+) heap=(\S+) RT (\w+)', line)
        if m:
            pso, groups, heap, rt = m.groups()
            j = next((k for k in range(i, len(lines)) if lines[k].startswith('INTEL ')), None)
            if j is None:
                problems.append('f4q-shadow: a F(4x4) dispatch without the runtime\'s')
                break
            intel = re.match(r'INTEL shader=(\S+) groups=(\S+) STATE (\w+)', lines[j])
            key = (pso, intel.group(2))
            need(expect_groups.get(key) == groups, f'f4q-shadow: F(4x4) groups {groups} for {key}')
            need(heap == 'intel' and rt == 'ok', f'f4q-shadow: F(4x4) dispatch without the runtime state ({heap}, RT {rt})')
            kind = 'f4q-enc' if pso == 'f4q-enc' else 'f4q-dec-full' if intel.group(2) == '80,23,1' else 'f4q-dec-half'
            seq = lines[i + 1:j]
            need(len(seq) == 2 and 'pso=f4q-check-aux' in seq[0] and f4q_consts(seq[0])[0] == 0 and 'pso=f4q-check-uav-uint' in seq[1]
                 and f'groups={fp_size[kind]}' in seq[1] and 'heap=own' in seq[1],
                 f'f4q-shadow: F(4x4) fingerprint sequence for {kind}: {[s[:60] for s in seq]}')
            tag_b = f4q_consts(seq[0])[3] if seq else None
            need(intel.group(3) == 'ok', f'f4q-shadow: runtime dispatch {intel.group(1)} state bad')
            own_rt = lines[j + 1] if j + 1 < len(lines) else ''
            need(own_rt.startswith('OWN pso=exact-') and 'RT ok' in own_rt, f'f4q-shadow: the runtime dispatch did not run the F(2x2) pipeline: {own_rt[:60]}')
            after = lines[j + 2:j + 5]
            ok = (len(after) == 3 and 'pso=f4q-check-aux' in after[0] and f4q_consts(after[0])[0] == 0 and 'pso=f4q-check-uav-uint' in after[1]
                  and 'pso=f4q-check-aux' in after[2] and f4q_consts(after[2])[0] == 1)
            need(ok, f'f4q-shadow: F(2x2) fingerprint + compare sequence for {kind}: {[s[:60] for s in after]}')
            if ok:
                c = f4q_consts(after[2])
                tag_a = f4q_consts(after[0])[3]
                need(c[11] == point_of[kind] and c[3] == 1 and c[4] == tag_a and c[5] == tag_b and c[13] == 2 and c[12] == 0,
                     f'f4q-shadow: compare constants for {kind}: point {c[11]} n {c[3]} tags {c[4]},{c[5]} (want {tag_a},{tag_b}) forced {c[13]}')
                compares += 1
            targets += 1
            i = j + 5
            continue
        if line.startswith('INTEL '):
            intel = re.match(r'INTEL shader=(\S+) groups=(\S+) STATE (\w+)', line)
            need(intel.group(3) == 'ok', f'f4q-shadow: runtime dispatch {intel.group(1)} state bad')
            if intel.group(1) == O:
                others += 1
                need(i + 1 < len(lines) and lines[i + 1].startswith('OWN pso=exact-other'), 'f4q-shadow: own work at another shader')
            i += 2
            continue
        i += 1
    need(targets == 9 and compares == 9 and others == 3, f'f4q-shadow: {targets} target dispatches, {compares} compares, {others} others (want 9, 9, 3)')
    need(re.search(r'^F4Q_SKIP geometry shader=' + D, shadow, re.M) is not None, 'f4q-shadow: the z=2 dispatch was not skipped')
    need('F4Q_COUNT stamp=7 point=b3941ac8-full equal=3 differ=0' in shadow and 'F4Q_COUNT stamp=7 point=b3941ac8-half equal=2 differ=1' in shadow
         and 'F4Q_COUNT stamp=7 point=f030948d equal=3 differ=0' in shadow and 'stamp=5' not in shadow, 'f4q-shadow: F4Q_COUNT lines')
    need(re.search(r'^F4Q_STATUS why=release ', shadow, re.M) is not None and re.search(r'^F4Q_SUMMARY ', shadow, re.M) is not None,
         'f4q-shadow: no release-time status and summary')
    after = dict(re.findall(r'^REFS after-finish (\S+) (-?\d+)$', shadow, re.M))
    need(bool(after) and all(v == '1' for k, v in after.items() if not k.startswith('own-')) and all(v == '0' for k, v in after.items() if k.startswith('own-')),
         f'f4q-shadow: references after finish {after}')
    psos = dict(re.findall(r'^REFS pso (\S+) (-?\d+)$', shadow, re.M))
    need(psos.get('f4q-dec') == '0' and psos.get('f4q-enc') == '0' and all(psos.get(n) == '0' for n in psos if n.startswith('f4q-check')),
         f'f4q-shadow: pipelines after finish {psos}')
    need(re.search(r'^TOTALS .* ticks_after_finish=0$', shadow, re.M) is not None, 'f4q-shadow: ticks not reset')
    return problems


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
    _base, definition, defines = build_proxy.definitions(args.variant)
    coexist = args.variant == 'intel-free-mfg'
    f4q = 'XEFG_F4Q=1' in defines
    built = config.build / definition['addon']['output_dir']
    proxy, record = built / definition['addon']['output'], json.loads((built / 'build.json').read_text())
    if not proxy.is_file() or sha256(proxy) != record['sha256']:
        raise ReleaseError('No current proxy build: run release/build_proxy.py first')
    runtime = config.input_file(build_proxy.RUNTIME_GROUP, build_proxy.RUNTIME_FILE)
    xess = config.check_group('intel-xess')
    work = config.build / ('proxy-wine-check' if args.variant == build_proxy.DEFAULT_VARIANT else f'proxy-wine-check-{args.variant}')
    cases = ('pinned', 'altered', 'missing') + (('hooked',) if coexist else ())
    for name in cases + ('unit',) + tuple(f'f4q-{case}' for case in F4Q_CASES):
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
    if f4q:
        f4q_program = work / 'test_f4q.exe'
        compile_f4q(config, xess, f4q_program)
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
    if f4q:
        f4q_results = {case: run_f4q(f4q_program, work, case) for case in F4Q_CASES}
        results.update({f'f4q-{case}': r for case, r in f4q_results.items()})
        problems += f4q_problems(f4q_results)
    report = dict(variant=args.variant, proxy_sha256=record['sha256'], runtime_sha256=sha256(runtime), program_sha256=sha256(program),
                  callers={name: sha256(path) for name, path in callers.items()},
                  unit_sha256=sha256(unit) if coexist else None, f4q_sha256=sha256(f4q_program) if f4q else None,
                  wine=subprocess.run(['wine', '--version'], capture_output=True, text=True).stdout.strip(),
                  cases=results, problems=problems, result='pass' if not problems else 'fail')
    (work / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(result=report['result'], problems=problems,
                          stdout={case: [line for line in r['stdout'].strip().splitlines() if not line.startswith('ok line=')]
                                  for case, r in results.items() if not case.startswith('f4q-')},
                          f4q={case[4:]: len(r['stdout'].splitlines()) for case, r in results.items() if case.startswith('f4q-')}),
                     indent=2))
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
