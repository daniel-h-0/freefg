#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Positive and negative controls of release/check_intel_free.py that need no private material, for CI.

`check_intel_free.py self-test` proves every detector on the locked v30 profile and on shaders captured from Intel's
runtime: private inputs that a public tree does not have, so CI skips it. This script proves the same detectors on
synthetic material instead, through the check's own code (check_tree), with DXC (XEMFG_DXC) compiling and
disassembling the samples:

  a synthetic 1280-byte "warp table" (deterministic bytes, not Intel's), registered in memory as a table to detect:
    table-constant.dxil  the table as a static const array of a shader model 6.6 compute shader
                         -> warp-table-constant (DXC disassembly + constant parser), not-own-shader
    table.bin            the table at an odd offset of a blob -> warp-table-bytes (raw window scan, with numpy and
                         with the pure-Python fallback)
  a synthetic shader model 6.4 compute shader, registered in memory as a "captured Intel shader":
    capture.dxil         -> intel-file, not-own-shader, shader-model-6.4
    capture-renamed.bin  the same bytes without the .dxil suffix -> intel-file, not-own-shader, shader-model-6.4
    capture-embedded.bin inside a blob -> embedded-capture, not-own-shader, shader-model-6.4
  negative controls, one of this project's own profile shaders (staged by release/ci/profile.py, XEMFG_PROFILE):
    own.dxil, own-embedded.bin   -> no finding

The registrations exist only in this process; release/intel_material.json and check_intel_free.py are not changed.
Exit status 1 when any sample is flagged differently from the list above.

  python3 release/ci/check_controls.py [--report FILE]
"""
import argparse
import builtins
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ReleaseError, annotate, build_config, step_summary, write_json  # noqa: E402
import check_intel_free as check  # noqa: E402  (release/check_intel_free.py)

OWN_SAMPLE = 'graph-matmul64.dxil'
TABLE_LABEL = 'synthetic control table (not Intel material)'
EXPECTED = {
    'table-constant.dxil': {'not-own-shader', 'warp-table-constant'},
    'table.bin': {'warp-table-bytes'},
    'capture.dxil': {'intel-file', 'not-own-shader', 'shader-model-6.4'},
    'capture-renamed.bin': {'intel-file', 'not-own-shader', 'shader-model-6.4'},
    'capture-embedded.bin': {'embedded-capture', 'not-own-shader', 'shader-model-6.4'},
    'own.dxil': set(),
    'own-embedded.bin': set(),
}


def synthetic_table():
    out = b''
    counter = 0
    while len(out) < check.TABLE_BYTES:
        out += hashlib.sha256(b'release-ci-control-table-%d' % counter).digest()
        counter += 1
    return out[:check.TABLE_BYTES]


def compile_shader(dxc, folder, name, model, source):
    hlsl, output = folder / f'{name}.hlsl', folder / f'{name}.dxil'
    hlsl.write_text(source)
    out = subprocess.run([str(dxc), '-T', f'cs_{model.replace(".", "_")}', '-E', 'main', '-Fo', str(output), str(hlsl)],
                         capture_output=True, text=True)
    if out.returncode:
        raise ReleaseError(f'dxc could not compile the {name} control shader: {out.stderr.strip()[-400:]}')
    data = output.read_bytes()
    if check.shader_model(data) != model:
        raise ReleaseError(f'the {name} control shader has shader model {check.shader_model(data)}, not {model}')
    return data


def table_shader_source(table):
    words = ', '.join(f'0x{int.from_bytes(table[i:i + 4], "little"):08x}' for i in range(0, len(table), 4))
    count = len(table) // 4
    return (f'static const uint T[{count}] = {{ {words} }};\n'
            'RWStructuredBuffer<uint> o : register(u0);\n'
            f'[numthreads(64, 1, 1)] void main(uint3 i : SV_DispatchThreadID) {{ o[i.x] = T[i.x % {count}]; }}\n')


SM64_SOURCE = ('RWStructuredBuffer<uint> o : register(u0);\n'
               '[numthreads(8, 8, 1)] void main(uint3 i : SV_DispatchThreadID) { o[i.y * 8 + i.x] = (i.x ^ i.y) * 7u; }\n')


def without_numpy(function, *arguments):
    """Run function with `import numpy` failing, so check_intel_free takes its pure-Python window scan."""
    real = builtins.__import__

    def refuse(name, *rest, **keywords):
        if name == 'numpy' or name.startswith('numpy.'):
            raise ImportError('numpy disabled for this control')
        return real(name, *rest, **keywords)

    builtins.__import__ = refuse
    try:
        return function(*arguments)
    finally:
        builtins.__import__ = real


def run(config):
    dxc = config.dxc()
    if dxc is None:
        raise ReleaseError('The controls need DXC: set XEMFG_DXC (release/ci/toolchain.py dxc)')
    own = config.input_file(check.PROFILE_GROUP, OWN_SAMPLE).read_bytes()
    table = synthetic_table()
    table_sha = hashlib.sha256(table).hexdigest()
    with tempfile.TemporaryDirectory(prefix='ci-controls-') as scratch_name:
        scratch = Path(scratch_name)
        build, samples = scratch / 'hlsl', scratch / 'samples'
        build.mkdir()
        samples.mkdir()
        table_shader = compile_shader(dxc, build, 'table', '6.6', table_shader_source(table))
        capture = compile_shader(dxc, build, 'capture', '6.4', SM64_SOURCE)
        (samples / 'table-constant.dxil').write_bytes(table_shader)
        (samples / 'table.bin').write_bytes(bytes(range(256)) * 2 + b'\x01' + table + bytes(77))
        (samples / 'capture.dxil').write_bytes(capture)
        (samples / 'capture-renamed.bin').write_bytes(capture)
        (samples / 'capture-embedded.bin').write_bytes(b'MZ' + bytes(1021) + capture + bytes(64))
        (samples / 'own.dxil').write_bytes(own)
        (samples / 'own-embedded.bin').write_bytes(b'MZ' + bytes(509) + own + bytes(33))

        real_material, real_tables = check.load_material, dict(check.WARP_TABLES)
        material = real_material()
        patched = dict(material)
        patched['captured_shaders'] = dict(material['captured_shaders'], **{
            hashlib.sha256(capture).hexdigest(): dict(names=['synthetic-sm64-control'], shader_model='6.4')})
        patched['warp_tables'] = dict(material['warp_tables'], **{table_sha: dict(zip(
            ('window_sum', 'window_moment'), check.window_checksums(table)))})
        check.WARP_TABLES[table_sha] = TABLE_LABEL
        check.load_material = lambda: patched
        try:
            findings, stats = check.check_tree(samples, config, dxc)
            blob = (samples / 'table.bin').read_bytes()
            tables = {table_sha: check.window_checksums(table)}
            fast = check.table_windows(blob, tables)
            slow = without_numpy(check.table_windows, blob, tables)
        finally:
            check.load_material = real_material
            check.WARP_TABLES.clear()
            check.WARP_TABLES.update(real_tables)
    flagged = {}
    for item in findings:
        flagged.setdefault(item['file'], set()).add(item['check'])
    problems = [f'{name}: flagged {sorted(flagged.get(name, set()))}, expected {sorted(wanted)}'
                for name, wanted in EXPECTED.items() if flagged.get(name, set()) != wanted]
    problems += [f'{name}: unexpected sample' for name in sorted(set(flagged) - set(EXPECTED))]
    if not fast or fast != slow:
        problems.append(f'raw window scan: numpy {fast}, pure Python {slow}')
    try:
        import numpy  # noqa: F401
        numpy_state = 'numpy and pure-Python scans agree'
    except ImportError:
        numpy_state = 'numpy not installed: both runs used the pure-Python scan'
    result = dict(
        dxc=subprocess.run([str(dxc), '--version'], capture_output=True, text=True).stdout.strip().splitlines()[:1],
        samples={name: sorted(flagged.get(name, set())) for name in EXPECTED}, window_scan=dict(hits=fast, note=numpy_state),
        constant_arrays=stats['constant_arrays'], own_sample=OWN_SAMPLE, synthetic_table_sha256=table_sha,
        problems=problems, result='pass' if not problems else 'fail')
    rows = '\n'.join(f'| {name} | {", ".join(sorted(EXPECTED[name])) or "none"} | '
                     f'{", ".join(result["samples"][name]) or "none"} |' for name in EXPECTED)
    step_summary('### check_intel_free.py controls (synthetic, public)\n\n| Sample | Expected | Flagged |\n'
                 f'| --- | --- | --- |\n{rows}\n\nResult: **{result["result"]}**')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--report', type=Path, help='also write the result as JSON')
    args = parser.parse_args()
    result = run(build_config())
    if args.report:
        write_json(args.report, result)
    print(json.dumps(result, indent=2))
    if result['problems']:
        raise ReleaseError('; '.join(result['problems']))


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        annotate('error', error, title='check_intel_free controls')
        sys.exit(1)
