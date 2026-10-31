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
             expected: the wrapped entry refuses (CANT_LOAD_LIBRARY, -11) without loading it, and the log says why, once
             (a second call is refused without another check)
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
  f4q-*      (variants built with XEFG_F4Q) src/game/test_f4q.c: the switches of F4Q and F4Q2, model segments, pipelines
             and geometry, fallback and diagnostic check (src/model_f4q.h, src/game/f4q.h and the real settings reader,
             with mock D3D12 objects), one folder per case with its own BC250-XeFG/settings.ini:
               default     the package's settings.ini (F4Q=1, F4Q2=1): both on; b3941ac8 and f030948d and F4Q2's
                           1a3b0782, e83e868f and 9e0080ee created from <hash>.f4q.dxil (F4Q_REPLACE), f2e2e13f from
                           its <hash>.dxil; F(4x4) geometry only for a dispatch that binds a F(4x4) pipeline, none left
                           after the context's release; segment sizes 36,864 / 73,728 bytes and, for F4Q2, 294,912 /
                           1,179,648 bytes; no hook installed and no line of the check
               no-ini      no settings file: both on
               ini-off     settings.ini F4Q=0: both off (F(2x2) files and geometry, no segment, no F4Q_REPLACE)
               env-off     BC250_XEFG_F4Q=0 over settings.ini F4Q=1: both off
               env-on      BC250_XEFG_F4Q=on over settings.ini F4Q=0: both on
               shadow-off  BC250_XEFG_F4Q=0 with BC250_XEFG_F4Q_SHADOW=1: off, no line of the check
               f4q2-*      F4Q on and F4Q2 off by settings.ini F4Q2=0 or BC250_XEFG_F4Q2=0; BC250_XEFG_F4Q2=yes over
                           F4Q2=0: on; an unreadable value: the file decides; BC250_XEFG_F4Q2=1 with F4Q off: off
               fallback    on, b3941ac8's F(4x4) pipeline cannot be created and f030948d's F(4x4) file is missing:
                           both F4Q_FALLBACK, F(2x2) pipelines and geometry; F4Q2's three layers F(4x4)
               layout      on, but a model layout without the row16 segment: off (the kernels' offsets do not hold),
                           F4Q2 with it
               f4q2-layout a model layout without the 18432- and 73728-byte forms: F4Q on, F4Q2 on 1a3b0782 only
               shadow      BC250_XEFG_F4Q_SHADOW=1: F(2x2) output and geometry; at each target dispatch the F(4x4)
                           dispatch with the runtime's state and groups, its fingerprint, the runtime's own dispatch with
                           its state, the F(2x2) fingerprint and the compare with the right point and tags, at F4Q's
                           points 0..2 and F4Q2's 3..5; nothing at another shader; a z != 1 dispatch skipped; the stamped
                           readback logged as F4Q_COUNT, then the release-time status and summary; every reference
                           released at release
               shadow-f4q2-off  the same with BC250_XEFG_F4Q2=false: F4Q's points 0..2 and F4Q3's 6..7, no F4Q2 line
               pack        (BC250_XEFG_EXACT=1) the model owner's segment of a 2304-, 4608-, 18432- and 73728-byte model
                           equal to an independent product
               settings-env, settings-env-dos  BC250_XEFG_SETTINGS names another settings file (F4Q=0 there) as a Unix
                           path (Wine maps it) or a Windows path: off from settings.ini, as ini-off
             1.1.2 (F4Q3 and the FP16 forms): every switch case also checks FP16_CONFIG and F4Q3_CONFIG, the pipeline
             and geometry of all eleven U-Net shaders and a shader no form replaces, the FP16 copies' sizes of every
             model size (SEGMENT3) and the FP16_REPLACE lines; by default (the FP16 forms' bits 1 and 2) seven are
             created from <hash>.fp16.dxil (same geometry: the three F4Q2 encoders and four F(2x2) layers) and the other
             four F4Q targets from <hash>.f4q.dxil (the row layers by F4Q3, with the F(4x4) groups x / 4, y / 2); with the
             exact switch the seven F4Q targets from <hash>.f4q.dxil and the other four from <hash>.dxil:
               exact-ini, exact-env, exact-env-over-ini, exact-env-bad, exact-f4q2-off
                           Exact=1 in settings.ini; BC250_XEFG_EXACT=1; BC250_XEFG_EXACT=no over Exact=1 (on); an
                           unreadable value (the file decides); the exact switch with F4Q2 off
               fallback    runs with BC250_XEFG_EXACT=1 (F4Q's own fallbacks)
               fp16-fallback  the FP16 forms' fallbacks: a missing FP16 file of e83e868f (its table is FP16 in place: F(2x2)),
                           of 1a3b0782 (an FP16 copy: its F(4x4) file) and of 1f27b449 (F(2x2)); a failed FP16 pipeline of
                           f2e2e13f (its F(2x2) kernel)
               f4q2-layout also drops the FP16 forms' bit 2 (no 18432- / 73728-byte copies): forms 1
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
# F4Q2's layers (F4Q_OTHER is the first: its F(2x2) file is named exact-other) and a shader no form replaces
F4Q2_E83E, F4Q2_9E00, F4Q_NEVER = 'e83e868f8d5d2c0f', '9e0080eee00255f2', '0123456789abcdef'
# F4Q3's row layers and the F(2x2) layers of the FP16 forms' bit 2 (with their dispatch-scale rows)
F4Q3_60ED, F4Q3_B3DD = '60edebbbd2f9fb69', 'b3ddf030f661d487'
FP16_XU1 = {'1f27b449fb99a587': '1 2 4', 'f2e2e13fea432d20': '1 1 2', '5654aa3800432b13': '2 1 2', '4bb52a635e6d221a': '1 1 4'}
# case: (test mode, environment, settings.ini text, 'package' for the package's file, or None for no file)
F4Q_CASES = {
    'default': ('switch', {}, 'package'),
    'no-ini': ('switch', {}, None),
    'ini-off': ('switch', {}, '[BC250]\nResolutionMode=0\nF4Q=0\n'),
    'env-off': ('switch', {'BC250_XEFG_F4Q': '0'}, 'package'),
    'env-on': ('switch', {'BC250_XEFG_F4Q': 'on'}, '[BC250]\nF4Q=0\n'),
    'shadow-off': ('switch', {'BC250_XEFG_F4Q': '0', 'BC250_XEFG_F4Q_SHADOW': '1'}, 'package'),
    'f4q2-ini-off': ('switch', {}, '[BC250]\nResolutionMode=0\nF4Q=1\nF4Q2=0\n'),
    'f4q2-env-off': ('switch', {'BC250_XEFG_F4Q2': '0'}, 'package'),
    'f4q2-env-on': ('switch', {'BC250_XEFG_F4Q2': 'yes'}, '[BC250]\nF4Q2=0\n'),
    'f4q2-env-bad': ('switch', {'BC250_XEFG_F4Q2': '7'}, '[BC250]\nF4Q2=0\n'),
    'f4q2-on-f4q-off': ('switch', {'BC250_XEFG_F4Q': 'off', 'BC250_XEFG_F4Q2': '1'}, 'package'),
    'exact-ini': ('switch', {}, '[BC250]\nResolutionMode=0\nF4Q=1\nF4Q2=1\nExact=1\n'),
    'exact-env': ('switch', {'BC250_XEFG_EXACT': '1'}, 'package'),
    'exact-env-over-ini': ('switch', {'BC250_XEFG_EXACT': 'no'}, '[BC250]\nExact=1\n'),
    'exact-env-bad': ('switch', {'BC250_XEFG_EXACT': '2'}, '[BC250]\nExact=1\n'),
    'exact-f4q2-off': ('switch', {'BC250_XEFG_EXACT': 'true', 'BC250_XEFG_F4Q2': '0'}, 'package'),
    'fallback': ('fallback', {'BC250_XEFG_EXACT': '1'}, 'package'),
    'fp16-fallback': ('fp16fallback', {}, 'package'),
    'layout': ('layout', {}, 'package'),
    'f4q2-layout': ('layout2', {}, 'package'),
    'shadow': ('shadow', {'BC250_XEFG_F4Q_SHADOW': '1'}, 'package'),
    'shadow-f4q2-off': ('shadow', {'BC250_XEFG_F4Q_SHADOW': '1', 'BC250_XEFG_F4Q2': 'false'}, 'package'),
    'pack': ('pack', {'BC250_XEFG_EXACT': '1'}, 'package'),
    # BC250_XEFG_SETTINGS names another settings file (F4Q=0 there, F4Q=1 in the package's file beside the program), as a
    # Unix path (mapped through Wine) and as a Windows path
    'settings-env': ('switch', {'BC250_XEFG_SETTINGS': '{unix}/elsewhere/settings.ini'}, 'package'),
    'settings-env-dos': ('switch', {'BC250_XEFG_SETTINGS': '{dos}\\elsewhere\\settings.ini'}, 'package'),
}
# Files a case writes besides its settings.ini (relative to its folder).
F4Q_FILES = {case: {'elsewhere/settings.ini': '[BC250]\nResolutionMode=0\nF4Q=0\n'} for case in ('settings-env', 'settings-env-dos')}


def compile_f4q(config, xess, output):
    """src/game/test_f4q.c with the multi-frame proxy's definitions F4Q depends on."""
    wine = config.wine_include
    subprocess.run([config.clang, '--target=x86_64-w64-windows-gnu', '-fms-extensions', '-D__WINE_USE_MSVCRT',
                    '-DXEFG_PROXY_MFG=1', '-DXEFG_INTEL_FREE=1', '-DXEFG_MFG_SETTINGS=1', '-DXEFG_F4Q=1',
                    '-DXEFG_OWN_FRAME_SCALING=1', '-DXEFG_MFG_UP_FILTERS=1',
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
    for name, text in F4Q_FILES.get(case, {}).items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    extra = {key: value.format(unix=folder, dos='Z:' + str(folder).replace('/', '\\')) for key, value in extra.items()}
    env = {k: v for k, v in os.environ.items() if not k.startswith(('WINE', 'DISPLAY', 'WAYLAND', 'XEFG_', 'BC250_'))}
    env.update(WINEPREFIX=str(work / 'prefix'), WINEDEBUG='-all', WINEDLLOVERRIDES='mscoree,mshtml=', **extra)
    shaders = 'Z:' + str(folder / 'shaders').replace('/', '\\')
    ran = subprocess.run(['wine', str(folder / program.name), mode, shaders], cwd=folder, env=env, capture_output=True,
                         text=True, timeout=600)
    return dict(returncode=ran.returncode, stdout=ran.stdout.replace('\r', ''), log=None)


def f4q_consts(line):
    return [int(x) for x in re.search(r' c=([0-9,]+)', line).group(1).split(',')]


def fp16_sizes(f4q, f4q2, fp16):
    """model_fp16_size of the six model sizes (src/model_f4q.h): the rest of the F4Q room, the PK copy, the half copy."""
    if not fp16:
        return dict.fromkeys((2304, 4608, 9216, 18432, 36864, 73728), 0)
    room = {2304: 36864, 4608: 73728, 18432: 294912, 73728: 1179648}
    f4q_seg = {2304: 36864 if f4q else 0, 4608: 73728 if f4q else 0, 18432: 294912 if f4q2 & 2 else 0,
               73728: 1179648 if f4q2 & 4 else 0}
    pk = {2304: 6144, 4608: 12288, 9216: 32768, 18432: 65536, 36864: 131072, 73728: 262144}
    out = {}
    for size in (2304, 4608, 9216, 18432, 36864, 73728):
        pk_on = bool(fp16 & (8 if size in (2304, 4608) else 2))
        h_on = (size == 2304 and ((fp16 & 1 and f4q2 & 1) or fp16 & 4)) or (size == 4608 and fp16 & 4)
        h = {2304: 18432, 4608: 36864}.get(size, 0) if h_on else 0
        out[size] = room.get(size, 0) - f4q_seg.get(size, 0) + pk[size] + h if pk_on or h_on else 0
    return out


def f4q_pso(f4q, f4q2, fp16):
    """{shader: (pipeline name, geometry)} that switch mode prints for F4Q on/off, F4Q2's layers (bits 1 = 1a3b0782,
    2 = e83e868f, 4 = 9e0080ee) and the FP16 forms' bits (1 F4Q2 encoders, 2 XU-1 layers, 4 F4Q, 8 row layers)."""
    D, E, A, EE, X = F4Q_DEC, F4Q_ENC, F4Q_OTHER, F4Q2_E83E, F4Q2_9E00
    f4q3 = f4q and not fp16 & 8
    out = {D: ('fp16-dec' if fp16 & 4 else 'f4q-dec', '-2 2 1') if f4q else ('exact-dec', '1 4 1'),
           E: ('fp16-enc' if fp16 & 4 else 'f4q-enc', '-4 2 2') if f4q else ('exact-enc', '1 2 2'),
           A: ('fp16-1a3b' if fp16 & 1 else 'f4q-1a3b', '1 2 1') if f4q2 & 1 else ('exact-other', '2 4 1'),
           EE: ('fp16-e83e' if fp16 & 1 else 'f4q-e83e', '-4 1 4') if f4q2 & 2 else ('exact-e83e', '1 1 4'),
           X: ('fp16-9e00' if fp16 & 1 else 'f4q-9e00', '-2 -2 8') if f4q2 & 4 else ('exact-9e00', '1 1 8')}
    for h in (F4Q3_60ED, F4Q3_B3DD):
        out[h] = (f'fp16-{h[:4]}', '1 1 1') if fp16 & 8 else (f'f4q-{h[:4]}', '-4 -2 1') if f4q3 else (f'exact-{h[:4]}', '1 1 1')
    for h, row in FP16_XU1.items():
        out[h] = (f'fp16-{h[:4]}' if fp16 & 2 else f'exact-{h[:4]}', row)
    out[F4Q_NEVER] = ('exact-0123', '1 1 2')
    return out


def f4q_switch_lines(f4q, f4q2, fp16=0):
    """The lines switch mode prints for F4Q on/off, F4Q2's layers and the FP16 forms (f4q_pso)."""
    D = F4Q_DEC
    rows = ['SEGMENT 2304=36864 4608=73728 9216=0', 'CONFIG mode=1'] if f4q else ['SEGMENT 2304=0 4608=0 9216=0', 'CONFIG mode=0']
    for h, (name, geom) in f4q_pso(f4q, f4q2, fp16).items():
        rows += [f'PSO {h} hr=0x00000000 name={name}', f'GEOM {h} pso={name} {geom}']
    s = fp16_sizes(f4q, f4q2, fp16)
    f4q3 = 3 if f4q and not fp16 & 8 else 0
    rows += [f'GEOM {D} pso=stranger 1 4 1',
             f'SEGMENT2 18432={294912 if f4q2 & 2 else 0} 73728={1179648 if f4q2 & 4 else 0} 36864=0 mask={f4q2}',
             f'SEGMENT3 2304={s[2304]} 4608={s[4608]} 9216={s[9216]} 18432={s[18432]} 36864={s[36864]} 73728={s[73728]} '
             f'fp16={fp16} f4q3={f4q3}', 'VTABLE unchanged=1', 'TICKS 0 OWN 0']
    return rows


def f4q_replaced(f4q, f4q2, fp16=0):
    """Sorted (shader, file, file size) of the F4Q_REPLACE lines switch mode prints (b3941ac8 has two pipelines)."""
    rows = []
    for h, (name, geom) in f4q_pso(f4q, f4q2, fp16).items():
        if name.startswith(('f4q-', 'fp16-')) and not (name.startswith('fp16-') and h in FP16_XU1 | {F4Q3_60ED: 1, F4Q3_B3DD: 1}):
            row = (h, f'{h}.{name.split("-")[0]}.dxil', str(len(name)))
            rows += [row, row] if h == F4Q_DEC else [row]
    return sorted(rows)


def fp16_replaced(f4q, f4q2, fp16):
    """Sorted (shader, file size) of the FP16_REPLACE lines: every pipeline created from a <hash>.fp16.dxil."""
    rows = []
    for h, (name, _geom) in f4q_pso(f4q, f4q2, fp16).items():
        if name.startswith('fp16-'):
            rows += [(h, str(len(name)))] * (2 if h == F4Q_DEC else 1)
    return sorted(rows)


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
    check_only = ('F4Q_SHADOW_PSO', 'F4Q_INSTALLED', 'F4Q_STATUS', 'F4Q_COUNT', 'F4Q_SUMMARY', 'F4Q_SKIP', 'F4Q_STOP',
                  'F4Q2_INSTALLED', 'F4Q2_STATUS', 'F4Q3_INSTALLED', 'F4Q3_STATUS')
    # (case, F4Q on, F4Q source, F4Q2 layers, F4Q2 line: mode and source, FP16 forms, FP16 line source)
    switch_cases = (('default', 1, 'default', 7, 'on', 'default', 3, 'default'),
                    ('no-ini', 1, 'default', 7, 'on', 'default', 3, 'default'),
                    ('env-on', 1, 'BC250_XEFG_F4Q', 7, 'on', 'default', 3, 'default'),
                    ('ini-off', 0, 'settings.ini', 0, 'off', 'F4Q', 0, 'F4Q'),
                    ('settings-env', 0, 'settings.ini', 0, 'off', 'F4Q', 0, 'F4Q'),
                    ('settings-env-dos', 0, 'settings.ini', 0, 'off', 'F4Q', 0, 'F4Q'),
                    ('env-off', 0, 'BC250_XEFG_F4Q', 0, 'off', 'F4Q', 0, 'F4Q'),
                    ('shadow-off', 0, 'BC250_XEFG_F4Q', 0, 'off', 'F4Q', 0, 'F4Q'),
                    ('f4q2-ini-off', 1, 'default', 0, 'off', 'settings.ini', 3, 'default'),
                    ('f4q2-env-off', 1, 'default', 0, 'off', 'BC250_XEFG_F4Q2', 3, 'default'),
                    ('f4q2-env-on', 1, 'default', 7, 'on', 'BC250_XEFG_F4Q2', 3, 'default'),
                    ('f4q2-env-bad', 1, 'default', 0, 'off', 'settings.ini', 3, 'default'),
                    ('f4q2-on-f4q-off', 0, 'BC250_XEFG_F4Q', 0, 'off', 'F4Q', 0, 'F4Q'),
                    ('exact-ini', 1, 'default', 7, 'on', 'default', 0, 'settings.ini'),
                    ('exact-env', 1, 'default', 7, 'on', 'default', 0, 'BC250_XEFG_EXACT'),
                    ('exact-env-over-ini', 1, 'default', 7, 'on', 'default', 3, 'BC250_XEFG_EXACT'),
                    ('exact-env-bad', 1, 'default', 7, 'on', 'default', 0, 'settings.ini'),
                    ('exact-f4q2-off', 1, 'default', 0, 'off', 'BC250_XEFG_F4Q2', 0, 'BC250_XEFG_EXACT'))
    for case, f4q, source, f4q2, mode2, source2, fp16, source16 in switch_cases:
        text = results.get(case, {}).get('stdout', '')
        lines = text.splitlines()
        on = 'on' if f4q else 'off'
        need(f'F4Q_CONFIG mode={on} source={source} (' in text, f'f4q-{case}: F4Q not {on} from {source}')
        need(f'F4Q2_CONFIG mode={mode2} source={source2} layers={f4q2} f4q={on} dropped_by_layout=0 ('
             in text, f'f4q-{case}: F4Q2_CONFIG {[x for x in lines if x.startswith("F4Q2_CONFIG")]}')
        need(f'FP16_CONFIG mode={"on" if fp16 else "off"} source={source16} forms={fp16} f4q={on} f4q2={f4q2} dropped=0 ('
             in text, f'f4q-{case}: FP16_CONFIG {[x for x in lines if x.startswith("FP16_CONFIG")]}')
        f4q3 = ('F4Q3_CONFIG mode=on layers=3 f4q=on (' if f4q and not fp16 & 8 else
                f'F4Q3_CONFIG mode=off layers=0 f4q={on} source={"FP16" if f4q else "F4Q"} (')
        need(f4q3 in text, f'f4q-{case}: F4Q3_CONFIG {[x for x in lines if x.startswith("F4Q3_CONFIG")]}, want {f4q3!r}')
        for want in f4q_switch_lines(f4q, f4q2, fp16):
            need(want in lines, f'f4q-{case}: no line {want!r}')
        replaced = sorted(re.findall(r'^F4Q_REPLACE (\S+) (\S+) (\d+)$', text, re.M))
        need(replaced == f4q_replaced(f4q, f4q2, fp16), f'f4q-{case}: F4Q_REPLACE {replaced}, want {f4q_replaced(f4q, f4q2, fp16)}')
        fp16_rows = sorted(re.findall(r'^FP16_REPLACE (\S+) \S+\.fp16\.dxil (\d+)$', text, re.M))
        need(fp16_rows == fp16_replaced(f4q, f4q2, fp16), f'f4q-{case}: FP16_REPLACE {fp16_rows}, want {fp16_replaced(f4q, f4q2, fp16)}')
        dec = f4q_pso(f4q, f4q2, fp16)[D][0]
        need(lines.count(f'GEOM {D} pso={dec} {"-2 2 1" if f4q else "1 4 1"}') == (2 if f4q else 3),
             f'f4q-{case}: the second b3941ac8 pipeline does not follow F4Q')
        need(lines[-3:-1] == [f'GEOM {D} pso={dec} 1 4 1', 'TICKS 0 OWN 0'], f'f4q-{case}: F(4x4) geometry after release')
        need(not any(line.startswith(('F4Q_FALLBACK', 'FP16_FALLBACK') + check_only) for line in lines),
             f'f4q-{case}: a fallback line or a line of the check without its variable')
    text = results.get('fallback', {}).get('stdout', '')
    lines = text.splitlines()
    need(f'F4Q_FALLBACK {D} pipeline creation failed (hr=0x80070057): the F(2x2) kernel runs for this pipeline' in lines,
         'f4q-fallback: no fallback line for the failed b3941ac8 pipeline')
    need(f'F4Q_FALLBACK {E} its F4Q file cannot be read (hr=0x00000000): the F(2x2) kernel runs for this pipeline' in lines,
         'f4q-fallback: no fallback line for the missing f030948d file')
    for want in (f'PSO {D} hr=0x00000000 name=exact-dec', f'PSO {E} hr=0x00000000 name=exact-enc',
                 f'GEOM {D} pso=exact-dec 1 4 1', f'GEOM {E} pso=exact-enc 1 2 2', 'CONFIG mode=1',
                 f'PSO {O} hr=0x00000000 name=f4q-1a3b', f'GEOM {O} pso=f4q-1a3b 1 2 1'):
        need(want in lines, f'f4q-fallback: no line {want!r}')
    replaced = sorted(re.findall(r'^F4Q_REPLACE (\S+) (\S+) (\d+)$', text, re.M))
    want = [r for r in f4q_replaced(1, 7, 0) if r[0] not in (D, E)]
    need(replaced == want, f'f4q-fallback: F4Q_REPLACE {replaced}: only the F4Q2 and F4Q3 layers, whose files are there')
    need('FP16_CONFIG mode=off source=BC250_XEFG_EXACT forms=0 f4q=on f4q2=7 dropped=0 (' in text, 'f4q-fallback: FP16 forms not off')
    # the FP16 forms' fallbacks: a missing FP16 file of an in-place layer (F(2x2)), of a copy-reading target (its F(4x4) file)
    # and of a packed-FP16 layer (F(2x2)); a failed packed-FP16 pipeline (F(2x2))
    text = results.get('fp16-fallback', {}).get('stdout', '')
    lines = text.splitlines()
    for want in (f'FP16_FALLBACK {F4Q2_E83E} {F4Q2_E83E}.fp16.dxil cannot be read: the F(2x2) kernel runs (its table is FP16 in place)',
                 f'F4Q_FALLBACK {F4Q2_E83E} its F4Q file cannot be read (hr=0x00000000): the F(2x2) kernel runs for this pipeline',
                 f'PSO {F4Q2_E83E} hr=0x00000000 name=exact-e83e', f'GEOM {F4Q2_E83E} pso=exact-e83e 1 1 4',
                 f'FP16_FALLBACK {F4Q_OTHER} {F4Q_OTHER}.fp16.dxil cannot be read: the F(4x4) file runs',
                 f'PSO {F4Q_OTHER} hr=0x00000000 name=f4q-1a3b', f'GEOM {F4Q_OTHER} pso=f4q-1a3b 1 2 1',
                 'FP16_FALLBACK 1f27b449fb99a587 1f27b449fb99a587.fp16.dxil cannot be read: the F(2x2) / 1D kernel runs',
                 'PSO 1f27b449fb99a587 hr=0x00000000 name=exact-1f27',
                 'FP16_FALLBACK f2e2e13fea432d20 f2e2e13fea432d20.fp16.dxil 9 pipeline creation failed (hr=0x80070057): the F(2x2) / 1D kernel runs',
                 'PSO f2e2e13fea432d20 hr=0x00000000 name=exact-f2e2', 'GEOM f2e2e13fea432d20 pso=exact-f2e2 1 1 2',
                 f'PSO {D} hr=0x00000000 name=f4q-dec', f'PSO {E} hr=0x00000000 name=f4q-enc',
                 f'PSO {F4Q2_9E00} hr=0x00000000 name=fp16-9e00', f'PSO {F4Q3_60ED} hr=0x00000000 name=f4q-60ed',
                 f'PSO {F4Q3_B3DD} hr=0x00000000 name=f4q-b3dd', 'PSO 5654aa3800432b13 hr=0x00000000 name=fp16-5654',
                 'FP16_CONFIG mode=on source=default forms=3 f4q=on f4q2=7 dropped=0 ('):
        need(any(line.startswith(want) for line in lines), f'f4q-fp16-fallback: no line {want!r}')
    replaced = sorted(re.findall(r'^F4Q_REPLACE (\S+) (\S+) (\d+)$', text, re.M))
    want = sorted([(D, f'{D}.f4q.dxil', '7')] * 2 + [(E, f'{E}.f4q.dxil', '7'), (F4Q_OTHER, f'{F4Q_OTHER}.f4q.dxil', '8'),
                                                     (F4Q2_9E00, f'{F4Q2_9E00}.fp16.dxil', '9'),
                                                     (F4Q3_60ED, f'{F4Q3_60ED}.f4q.dxil', '8'), (F4Q3_B3DD, f'{F4Q3_B3DD}.f4q.dxil', '8')])
    need(replaced == want, f'f4q-fp16-fallback: F4Q_REPLACE {replaced}, want {want}')
    fp16_rows = sorted(re.findall(r'^FP16_REPLACE (\S+) \S+\.fp16\.dxil (\d+)$', text, re.M))
    want = sorted([(F4Q2_9E00, '9'), ('4bb52a635e6d221a', '9'), ('5654aa3800432b13', '9')])
    need(fp16_rows == want, f'f4q-fp16-fallback: FP16_REPLACE {fp16_rows}, want {want}')
    text = results.get('layout', {}).get('stdout', '')
    lines = text.splitlines()
    need('F4Q_CONFIG mode=off source=layout (' in text and 'CONFIG mode=0' in lines and 'SEGMENT 2304=0 4608=0 9216=0' in lines
         and f'PSO {D} hr=0x00000000 name=exact-dec' in lines, 'f4q-layout: F4Q not off for a layout it was not built for')
    need('F4Q2_CONFIG mode=off source=F4Q layers=0 f4q=off dropped_by_layout=0 (' in text
         and 'SEGMENT2 18432=0 73728=0 36864=0 mask=0' in lines and f'PSO {O} hr=0x00000000 name=exact-other' in lines,
         'f4q-layout: F4Q2 not off with F4Q off by the layout check')
    need('FP16_CONFIG mode=off source=F4Q forms=0 f4q=off f4q2=0 dropped=0 (' in text
         and 'F4Q3_CONFIG mode=off layers=0 f4q=off source=F4Q (' in text and 'PSO 1f27b449fb99a587 hr=0x00000000 name=exact-1f27' in lines,
         'f4q-layout: the FP16 forms or F4Q3 not off with F4Q off by the layout check')
    # a layout that holds for F4Q's sizes but not for 18432- and 73728-byte models: those two layers stay F(2x2)
    text = results.get('f4q2-layout', {}).get('stdout', '')
    lines = text.splitlines()
    need('F4Q_CONFIG mode=on source=default (' in text
         and 'F4Q2_CONFIG mode=on source=default layers=1 f4q=on dropped_by_layout=6 (' in text
         and 'FP16_CONFIG mode=on source=default forms=1 f4q=on f4q2=1 dropped=2 (' in text,
         f'f4q-f4q2-layout: config {[x for x in lines if "_CONFIG" in x]}')
    for want in f4q_switch_lines(1, 1, 1):
        need(want in lines, f'f4q-f4q2-layout: no line {want!r}')
    lines = results.get('pack', {}).get('stdout', '').splitlines()
    for bytes_, size, values, tbase in ((2304, 36864, 9216, 3025), (4608, 73728, 18432, 6049), (18432, 294912, 73728, 18049),
                                        (73728, 1179648, 294912, 72193)):
        packed = [line for line in lines if line.startswith(f'PACK bytes={bytes_} ')]
        m = re.fullmatch(r'PACK bytes=\d+ segment=(\d+) values=(\d+) differing=(\d+) maxabs=(\d+)', packed[0]) if packed else None
        need(m is not None and int(m[1]) == size and int(m[2]) == values and m[3] == '0' and int(m[4]) <= 73728,
             f'f4q-pack: {packed[:1]} (want segment {size}, {values} values, 0 differing, |U\'| <= 73728)')
        need(any(line.startswith(f'F4Q_SEGMENT bytes={bytes_} tbase={tbase} ') for line in lines),
             f'f4q-pack: no F4Q_SEGMENT for {bytes_} at {tbase}')
    problems += f4q_shadow_problems(results.get('shadow-f4q2-off', {}).get('stdout', ''), 'shadow-f4q2-off', False)
    problems += f4q_shadow_problems(results.get('shadow', {}).get('stdout', ''), 'shadow', True)
    return problems


def f4q_shadow_problems(shadow, case, f4q2):
    """The diagnostic check: F4Q's points 0..2 (research build ce02's test, with this build's names), and with F4Q2 on
    its points 3..5 (F(4x4) groups from Intel's dispatch, compare point, counters)."""
    problems = []

    def need(ok, what):
        if not ok:
            problems.append(what.replace('f4q-shadow:', f'f4q-{case}:'))

    D, E, O = F4Q_DEC, F4Q_ENC, F4Q_OTHER
    need(f'F4Q2_CONFIG mode={"shadow" if f4q2 else "off"} source={"default" if f4q2 else "BC250_XEFG_F4Q2"} '
         f'layers={7 if f4q2 else 0} f4q=shadow dropped_by_layout=0 (' in shadow, 'f4q-shadow: F4Q2_CONFIG')
    need('F4Q_CONFIG mode=shadow source=BC250_XEFG_F4Q_SHADOW' in shadow and 'CONFIG mode=2' in shadow.splitlines(),
         'f4q-shadow: not in the check')
    need(f'FP16_CONFIG mode=off source=F4Q forms=0 f4q=shadow f4q2={7 if f4q2 else 0} dropped=0 (' in shadow
         and 'F4Q3_CONFIG mode=shadow layers=3 f4q=shadow (' in shadow and 'FP16_REPLACE' not in shadow,
         'f4q-shadow: the FP16 forms not off, or F4Q3 not in the check')
    need('PIPELINES dec=exact-dec enc=exact-enc other=exact-other' in shadow and f'GEOM {D} pso=exact-dec 1 4 1' in shadow,
         'f4q-shadow: the F(2x2) pipelines or geometry are not the runtime\'s')
    need('VTABLE unchanged=0' in shadow and 'F4Q_INSTALLED' in shadow and 'F4Q_REPLACE' not in shadow, 'f4q-shadow: hooks')
    pso_lines = re.findall(r'^F4Q_SHADOW_PSO (\S+) bytes=\d+ ok$', shadow, re.M)
    need(sorted(pso_lines) == sorted([D, E, F4Q3_60ED, F4Q3_B3DD] + ([O, F4Q2_E83E, F4Q2_9E00] if f4q2 else [])),
         f'f4q-shadow: F(4x4) pipelines {pso_lines}')
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
    lines = shadow.splitlines()
    # F4Q3's points (6 = 60edebbb, 7 = b3ddf030), on in the check whatever F4Q2 does: each runtime dispatch of a row layer
    # preceded by its F(4x4) dispatch with the groups from Intel's dispatch (x / 4, y / 2), followed by the compare
    problems += f4q_shadow_points(lines, 'f4q-' + case, {F4Q3_60ED: ('f4q-60ed', '80,45,1', '20,23,1', 6),
                                                         F4Q3_B3DD: ('f4q-b3dd', '40,23,1', '10,12,1', 7)})
    for name, eq, ne in (('60edebbb', 3, 0), ('b3ddf030', 2, 1)):
        need(f'F4Q_COUNT stamp=7 point={name} equal={eq} differ={ne}' in lines, f'f4q-shadow: no F4Q_COUNT for {name}')
    need('F4Q3_INSTALLED shadow compares also at the F4Q3 row layers 3 (points 6..7)' in lines
         and 'PIPELINES3 60ed=exact-60ed b3dd=exact-b3dd' in lines and 'F4Q3_STATUS dispatches=3/3 (60edebbb/b3ddf030)' in lines,
         'f4q-shadow: F4Q3 install, runtime pipelines or status')
    need(all(psos.get(n) == '0' for n in ('f4q-60ed', 'f4q-b3dd')), f'f4q-shadow: F4Q3 pipelines after finish {psos}')
    if not f4q2:
        need(not re.search(r'^(F4Q2_INSTALLED|F4Q2_STATUS|OWN pso=f4q-(1a3b|e83e|9e00))', shadow, re.M)
             and 'point=1a3b0782' not in shadow and 'point=e83e868f' not in shadow and 'point=9e0080ee' not in shadow,
             'f4q-shadow: F4Q2 work or lines while F4Q2 is off')
        return problems
    # F4Q2's points: each runtime dispatch of a layer preceded by its F(4x4) dispatch with the groups from Intel's
    # dispatch, followed by the compare at its point (3 = 1a3b0782, 4 = e83e868f, 5 = 9e0080ee)
    need('F4Q2_INSTALLED shadow compares also at the F4Q2 layers 7 (points 3..5)' in lines
         and 'PIPELINES2 e83e=exact-e83e 9e00=exact-9e00' in lines, 'f4q-shadow: F4Q2 install or runtime pipelines')
    problems += f4q_shadow_points(lines, 'f4q-' + case, {O: ('f4q-1a3b', '40,23,1', '40,46,1', 3),
                                                         F4Q2_E83E: ('f4q-e83e', '40,12,1', '10,12,4', 4),
                                                         F4Q2_9E00: ('f4q-9e00', '10,12,1', '5,6,8', 5)})
    for name, eq, ne in (('1a3b0782', 3, 0), ('e83e868f', 3, 0), ('9e0080ee', 2, 1)):
        need(f'F4Q_COUNT stamp=7 point={name} equal={eq} differ={ne}' in lines, f'f4q-shadow: no F4Q_COUNT for {name}')
    need('F4Q2_STATUS dispatches=3/3/3 (1a3b0782/e83e868f/9e0080ee)' in lines, 'f4q-shadow: F4Q2_STATUS')
    need(all(psos.get(n) == '0' for n in ('f4q-1a3b', 'f4q-e83e', 'f4q-9e00')),
         f'f4q-shadow: F4Q2 pipelines after finish {psos}')
    return problems


def f4q_shadow_points(lines, case, want_groups):
    """Each runtime dispatch of a layer of want_groups ({shader: (F(4x4) pipeline, Intel's groups, F(4x4) groups,
    point)}) preceded by its F(4x4) dispatch and followed by the compare at its point; three per layer."""
    problems = []

    def need(ok, what):
        if not ok:
            problems.append(what)

    seen = {h: 0 for h in want_groups}
    for i, line in enumerate(lines):
        m = re.match(r'INTEL shader=(\S+) groups=(\S+) STATE (\w+)', line)
        if not m or m.group(1) not in want_groups:
            continue
        pso, intel, groups, point = want_groups[m.group(1)]
        need(m.group(2) == intel and m.group(3) == 'ok', f'{case}: runtime dispatch {line}')
        before = [x for x in lines[max(0, i - 10):i] if x.startswith(f'OWN pso={pso} ')]
        need(len(before) == 1 and before[0].startswith(f'OWN pso={pso} groups={groups} heap=intel RT ok'),
             f'{case}: F(4x4) dispatch before {m.group(1)}: {before}')
        after = [x for x in lines[i + 1:i + 12] if x.startswith('OWN pso=f4q-check-aux') and f4q_consts(x)[0] == 1]
        need(bool(after) and f4q_consts(after[0])[11] == point, f'{case}: compare point for {m.group(1)}: {after[:1]}')
        seen[m.group(1)] += 1
    need(all(v == 3 for v in seen.values()), f'{case}: compares per layer {seen} (want 3 each)')
    return problems


def compile_unit(config, xess, folder, output):
    """src/game/test_proxy_coexist.c (the multi-frame proxy's bookkeeping beside another module, with stand-ins for
    the rest of the add-on), linked with the committed COM thunks and a version resource whose product is OptiScaler."""
    resource = folder / (output.stem + '.res')
    resource.write_bytes(version_resource('OptiScaler'))
    wine = config.wine_include
    subprocess.run([config.clang, '--target=x86_64-w64-windows-gnu', '-fms-extensions', '-D__WINE_USE_MSVCRT',
                    '-DXEFG_PROXY_MFG=1', '-DXEFG_MFG_RETIRE=1', '-DXEFG_OWN_FRAME_SCALING=1',
                    '-isystem', str(wine / 'msvcrt'), '-isystem', str(wine / 'windows'),
                    '-I', str(xess / 'inc/xess_fg'), '-I', str(REPO / 'src'), '-I', str(REPO / 'src/game'),
                    '-I', str(build_proxy.common.COM_THUNKS), '-O2', '-Wall', '-Wextra', '-Wno-unused-function',
                    '-nostdlib', '-fuse-ld=lld', '-Wl,--entry,mainCRTStartup', '-Wl,--subsystem,console',
                    '-Wl,--no-insert-timestamp', '-L' + str(config.wine_lib), str(REPO / 'src/game/test_proxy_coexist.c'),
                    str(build_proxy.common.COM_THUNKS / 'com_thunks.S'), str(resource), '-lkernel32', '-lucrtbase',
                    '-o', str(output)], check=True, capture_output=True)


def compile_scale_history(config, output):
    """Compile the real cache-state helpers with opaque resource/list identities; no GPU."""
    wine = config.wine_include
    subprocess.run([config.clang, '--target=x86_64-w64-windows-gnu', '-fms-extensions', '-D__WINE_USE_MSVCRT',
                    '-DXEFG_SCALE_COPY_REUSE=1', '-isystem', str(wine / 'msvcrt'), '-isystem', str(wine / 'windows'),
                    '-O2', '-Wall', '-Wextra', '-Werror', '-nostdlib', '-fuse-ld=lld',
                    '-Wl,--entry,mainCRTStartup', '-Wl,--subsystem,console', '-Wl,--no-insert-timestamp',
                    '-L' + str(config.wine_lib), str(REPO / 'src/game/test_scale_history.c'),
                    '-lkernel32', '-lucrtbase', '-o', str(output)], check=True, capture_output=True)


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
    history = 'XEFG_SCALE_COPY_REUSE=1' in defines
    built = config.build / definition['addon']['output_dir']
    proxy, record = built / definition['addon']['output'], json.loads((built / 'build.json').read_text())
    if not proxy.is_file() or sha256(proxy) != record['sha256']:
        raise ReleaseError('No current proxy build: run release/build_proxy.py first')
    runtime = config.input_file(build_proxy.RUNTIME_GROUP, build_proxy.RUNTIME_FILE)
    xess = config.check_group('intel-xess')
    work = config.build / ('proxy-wine-check' if args.variant == build_proxy.DEFAULT_VARIANT else f'proxy-wine-check-{args.variant}')
    cases = ('pinned', 'altered', 'missing') + (('hooked',) if coexist else ())
    for name in cases + ('unit', 'history') + tuple(f'f4q-{case}' for case in F4Q_CASES):
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
    if history:
        history_program = work / 'test_scale_history.exe'
        compile_scale_history(config, history_program)
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
            if field(stdout, r'WRAPPED_AGAIN result=(-?\d+)') != (wrapped[0],):
                problems.append(f'pinned: a second call did not reach Intel\'s runtime as the first did')
            masks = ('3', '29') if 'XEFG_OWN_FRAME_SCALING=1' in defines else ('0', '0')
            if not settings or settings[0] != '1' or settings[3:] != masks:
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
            # the refusal is latched: the second call is refused without a second check (one line in the log)
            again, lines = field(stdout, r'WRAPPED_AGAIN result=(-?\d+)'), log.count('not the pinned Intel XeFG runtime')
            if again != (str(CANT_LOAD_LIBRARY),) or lines != 1:
                problems.append(f'{case}: a second call was not refused at once: {again}, {lines} log lines')
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
    if history:
        folder = work / 'history'
        folder.mkdir()
        env = {k: v for k, v in os.environ.items() if not k.startswith(('WINE', 'DISPLAY', 'WAYLAND', 'XEFG_', 'BC250_'))}
        env.update(WINEPREFIX=str(work / 'prefix'), WINEDEBUG='-all', WINEDLLOVERRIDES='mscoree,mshtml=')
        ran = subprocess.run(['wine', str(history_program)], cwd=folder, env=env, capture_output=True, text=True, timeout=600)
        stdout = ran.stdout.replace('\r', '')
        results['history'] = dict(returncode=ran.returncode, stdout=stdout, log=None)
        if ran.returncode or 'SCALE_HISTORY_UNIT failures=0' not in stdout or any(x.startswith('FAIL ') for x in stdout.splitlines()):
            problems.append(f'history: exit {ran.returncode}; cache lifecycle fixture did not pass')
    if f4q:
        f4q_results = {case: run_f4q(f4q_program, work, case) for case in F4Q_CASES}
        results.update({f'f4q-{case}': r for case, r in f4q_results.items()})
        problems += f4q_problems(f4q_results)
    report = dict(variant=args.variant, proxy_sha256=record['sha256'], runtime_sha256=sha256(runtime), program_sha256=sha256(program),
                  callers={name: sha256(path) for name, path in callers.items()},
                  unit_sha256=sha256(unit) if coexist else None, history_sha256=sha256(history_program) if history else None, f4q_sha256=sha256(f4q_program) if f4q else None,
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
