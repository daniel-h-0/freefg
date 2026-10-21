#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Static check that a package (or any directory) ships no Intel-derived shader material.

  python3 release/check_intel_free.py check PATH [--allow-component NAME ...] [--report FILE]

PATH is an assembled package directory (its manifest.json names each file's component) or any other directory, for
example a shader profile. Every file below it is read; nothing is executed except DXC's disassembler.

A file fails the check when:
  intel-file          its sha256 is that of a file the reference data refuses: an Intel runtime library (also
                      package.json never_ship), a shader program of Intel's runtime, or a shader derived from Intel's
                      (release/intel_material.json; where inputs.lock.json pins them, also its profile files of origin
                      "intel-derived" and the XeSSMFG enabler's shader programs and libraries)
  not-own-shader      it is a .dxil file, or any file that is a whole DXIL container, that is not one of the profile
                      shaders compiled from this project's HLSL (inputs.lock.json origin "own", in the profile's work
                      group or a "tree" group such as the multi-frame build's release/profile-mfg); or it embeds a DXIL
                      container that is not one of them, unless the file is a pinned third-party binary (the files of
                      the lock's "optiscaler-fork" group: OptiScaler's own shaders, still subject to every other check)
  shader-model-6.4    it is, or embeds, a DXIL container of shader model 6.4 (the model of every Intel-lineage profile
                      shader; this project's own shaders are 6.0, 6.6 and 6.9)
  embedded-capture    it embeds a DXBC/DXIL container byte-identical to a refused shader
  warp-table-bytes    some 1280-byte window of it equals one of the two weight tables of Intel's runtime the reference
                      data describes
  warp-table-constant a constant array of one of its DXIL containers (read from DXC's disassembly; LLVM bitcode does not
                      store constants byte-aligned, so the raw scan cannot see them) contains such a table

The weight tables are identified by sha256 plus two window checksums (byte sum and position-weighted byte sum) used
as a pre-filter, so neither this script nor its data holds Intel's bytes. The constant scan needs DXC (XEMFG_DXC or
--dxc); without it the check fails unless --skip-constant-scan is given, which the report then records.

--allow-component NAME reports findings in that manifest component without failing (a private measurement build that
still carries the XeSSMFG enabler, whose shader programs are Intel's). The report always lists them.

The report's result is "pass" when nothing was found at all (intel_free_complete true), "pass-with-allowed-components"
when every finding lies in an allowed component (the package is then not Intel-free as a whole: intel_free_complete
false), and "fail" otherwise.

Exit status: 0 for either pass result, 1 for "fail".

The maintainers' tree also has the commands record (rewrites intel_material.json) and self-test (positive controls on
the full locked profile), from release/record_intel_material.py; both read private inputs.
"""
import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import RELEASE, Config, ReleaseError, add_arguments  # noqa: E402

MATERIAL = RELEASE / 'intel_material.json'
DEFINITION = RELEASE / 'intel_free.json'
PACKAGE_SPEC = RELEASE / 'package.json'
PROFILE_GROUP = 'profile-cl-wino-q33'
ENABLER_GROUP = 'xessmfg-enabler'
TABLE_BYTES = 1280
INTEL_SHADER_MODEL = '6.4'

# The two 1280-byte weight tables of Intel's runtime the check looks for, by the sha256 of their bytes.
WARP_TABLES = {
    '0bc540f40daae1ca3331a6d1931cbec0bcee5bdaa80a2e87d91f1e68e70cd008': 'MFG (3x/4x) warp coefficients',
    'f4f06dca711a307beb9b838394f37ccd4dbe5d600a5bea39649ee7f26fabd9ca': 'native 2x warp coefficients',
}
# Pinned third-party binaries whose embedded DXIL containers are their own shaders rather than this project's: every
# file of these lock groups (by sha256). Their containers still get the shader-model, capture and table checks.
THIRD_PARTY_GROUPS = ('optiscaler-fork',)
PASS, PASS_ALLOWED, FAIL = 'pass', 'pass-with-allowed-components', 'fail'
# The categories of refused files (the labels the public reference data keeps; see public_material).
INTEL_LIBRARY = 'Intel runtime library'
INTEL_SHADER = "shader program of Intel's runtime"
INTEL_DERIVED = "shader derived from Intel's"
PUBLIC_ABOUT = ('Reference data of release/check_intel_free.py check: the sha256 of every file an Intel-free package '
                'must not contain, each with its category (Intel runtime libraries, shader programs of Intel\'s XeFG '
                'runtime, shaders derived from them), and the sha256 and two window checksums (byte sum, '
                'position-weighted byte sum) of two 1280-byte weight tables of Intel\'s runtime. It holds no Intel bytes '
                'and no file names. release/export_tree.py --public writes it from the maintainers\' reference data, '
                'which refuses the same digests.')


# ------------------------------------------------------------------------------------------------- DXBC/DXIL containers

def container_parts(data, offset=0):
    """(container size, {fourcc: [(start, length)]}) of the DXBC container at offset, or None when it is not one."""
    if data[offset:offset + 4] != b'DXBC' or len(data) < offset + 32:
        return None
    size, count = struct.unpack_from('<II', data, offset + 24)
    if size < 32 + 4 * count or offset + size > len(data) or count > 64:
        return None
    parts = {}
    for part_offset in struct.unpack_from(f'<{count}I', data, offset + 32):
        start = offset + part_offset
        if part_offset + 8 > size:
            return None
        length = struct.unpack_from('<I', data, start + 4)[0]
        if part_offset + 8 + length > size:
            return None
        parts.setdefault(data[start:start + 4].decode('latin-1'), []).append((start + 8, length))
    return size, parts


def shader_model(data, offset=0):
    """'major.minor' of a DXIL container (its program header), or None for anything else."""
    found = container_parts(data, offset)
    if not found or 'DXIL' not in found[1]:
        return None
    start, length = found[1]['DXIL'][0]
    if length < 4:
        return None
    version = struct.unpack_from('<I', data, start)[0]
    return f'{(version >> 4) & 0xf}.{version & 0xf}'


def embedded_containers(data):
    """(offset, size) of every well-formed DXBC container in data."""
    found, at = [], data.find(b'DXBC')
    while at >= 0:
        parsed = container_parts(data, at)
        if parsed:
            found.append((at, parsed[0]))
        at = data.find(b'DXBC', at + 4)
    return found


# ------------------------------------------------------------------------------------------------ weight-table windows

def window_checksums(window):
    """(byte sum, position-weighted byte sum) of one window: the pre-filter recorded for each table."""
    return sum(window), sum(i * b for i, b in enumerate(window))


def table_windows(data, tables):
    """[(offset, table sha256)] of every TABLE_BYTES window of data equal to one of tables ({sha256: (sum, moment)})."""
    if len(data) < TABLE_BYTES or not tables:
        return []
    wanted = {}
    for digest, checksums in tables.items():
        wanted.setdefault(tuple(checksums), []).append(digest)
    try:
        import numpy
    except ImportError:
        numpy = None
    candidates = []
    if numpy is not None:
        values = numpy.frombuffer(data, dtype=numpy.uint8).astype(numpy.int64)
        positions = numpy.arange(len(values), dtype=numpy.int64)
        first = numpy.concatenate(([0], numpy.cumsum(values)))
        second = numpy.concatenate(([0], numpy.cumsum(values * positions)))
        starts = numpy.arange(len(values) - TABLE_BYTES + 1, dtype=numpy.int64)
        sums = first[TABLE_BYTES:] - first[:-TABLE_BYTES]
        moments = second[TABLE_BYTES:] - second[:-TABLE_BYTES] - starts * sums
        for total, moment in wanted:
            candidates += numpy.nonzero((sums == total) & (moments == moment))[0].tolist()
    else:
        total, moment = window_checksums(data[:TABLE_BYTES])
        for start in range(len(data) - TABLE_BYTES + 1):
            if start:
                leaving, entering = data[start - 1], data[start + TABLE_BYTES - 1]
                moment += entering * (TABLE_BYTES - 1) - (total - leaving)
                total += entering - leaving
            if (total, moment) in wanted:
                candidates.append(start)
    hits = []
    for start in sorted(set(candidates)):
        digest = hashlib.sha256(data[start:start + TABLE_BYTES]).hexdigest()
        if digest in tables:
            hits.append((start, digest))
    return hits


# ---------------------------------------------------------------------------------------- DXIL constant arrays (DXC)

ELEMENT = re.compile(r'\b(i8|i16|i32|i64|half|float|double) (0xH[0-9A-Fa-f]{4}|0x[0-9A-Fa-f]{16}|-?[0-9.]+(?:e[+-]?\d+)?'
                     r'|true|false)')
STRING = re.compile(r'c"((?:[^"\\]|\\[0-9A-Fa-f]{2}|\\\\)*)"')
CONSTANT = re.compile(r'^@\S+ = .*\bconstant\b(.*)$')


def element_bytes(kind, text):
    """Little-endian bytes of one constant element as LLVM's assembly prints it."""
    if kind in ('i8', 'i16', 'i32', 'i64'):
        width = {'i8': 1, 'i16': 2, 'i32': 4, 'i64': 8}[kind]
        value = 1 if text == 'true' else 0 if text == 'false' else int(text)
        return (value & ((1 << (8 * width)) - 1)).to_bytes(width, 'little')
    if text.startswith('0xH'):
        return int(text[3:], 16).to_bytes(2, 'little')
    value = struct.unpack('>d', bytes.fromhex(text[2:]))[0] if text.startswith('0x') else float(text)
    return struct.pack('<e' if kind == 'half' else '<f' if kind == 'float' else '<d', value)


def unescape(text):
    out, i = bytearray(), 0
    while i < len(text):
        if text[i] == '\\':
            if text[i + 1] == '\\':
                out.append(0x5c)
                i += 2
            else:
                out.append(int(text[i + 1:i + 3], 16))
                i += 3
        else:
            out += text[i].encode('latin-1')
            i += 1
    return bytes(out)


def constant_arrays(assembly):
    """The bytes of every global constant in a DXIL disassembly, one bytes object per global."""
    arrays = []
    for line in assembly.splitlines():
        match = CONSTANT.match(line)
        if not match:
            continue
        initializer = match[1]
        data = b''.join(unescape(s) for s in STRING.findall(initializer))
        data += b''.join(element_bytes(kind, text) for kind, text in ELEMENT.findall(STRING.sub('', initializer)))
        if data:
            arrays.append(data)
    return arrays


def disassemble(dxc, data, scratch):
    """DXC's disassembly of one DXIL container."""
    path = scratch / 'container.dxil'
    path.write_bytes(data)
    out = subprocess.run([str(dxc), '-dumpbin', str(path)], capture_output=True, text=True)
    if out.returncode:
        raise ReleaseError(f'dxc -dumpbin failed: {out.stderr.strip()[-300:]}')
    return out.stdout


# ------------------------------------------------------------------------------------------------------ reference data

def load_material():
    """intel_material.json as {'captured_shaders': {sha256: entry}, 'warp_tables': {sha256: entry}}. The maintainers'
    file names the shader programs of Intel's runtime (entries with names and shader model); the public one holds every
    refused digest with its category (entries with a category), see public_material."""
    if not MATERIAL.is_file():
        raise ReleaseError(f'{MATERIAL.name} is missing')
    material = json.loads(MATERIAL.read_text())
    if 'refused' in material:
        material = dict(material, captured_shaders={digest: dict(category=category)
                                                    for digest, category in material['refused'].items()})
    if set(material['warp_tables']) != set(WARP_TABLES):
        raise ReleaseError(f'{MATERIAL.name} does not describe the two weight tables of WARP_TABLES')
    return material


def third_party(config):
    """{sha256: label} of the pinned third-party binaries whose embedded shaders are their own (THIRD_PARTY_GROUPS)."""
    return {entry['sha256']: f'{group}/{name}' for group in THIRD_PARTY_GROUPS
            for name, entry in config.lock['work'][group]['files'].items()}


def refused_files(config, material):
    """{sha256: (category, label)} of every file the check refuses as Intel material: the lock's profile files of origin
    "intel-derived" and the XeSSMFG enabler's shader programs and libraries (where the lock pins them), package.json's
    never_ship Intel libraries, and the reference data's digests."""
    lock = config.lock['work']
    refused = {}
    for name, entry in lock[PROFILE_GROUP]['files'].items():
        if entry['origin'] == 'intel-derived':
            refused[entry['sha256']] = (INTEL_DERIVED, f'Intel-derived profile file {name}')
    for name, entry in lock.get(ENABLER_GROUP, {}).get('files', {}).items():
        if name.endswith(('.dxil', '.dll')) and name != 'XeSSMFG.dll':
            refused.setdefault(entry['sha256'], (INTEL_SHADER if name.endswith('.dxil') else INTEL_LIBRARY,
                                                 f'XeSSMFG enabler {name} (Intel shader program or runtime)'))
    for digest, label in json.loads(PACKAGE_SPEC.read_text())['never_ship']['sha256'].items():
        if 'Intel' in label:
            refused.setdefault(digest, (INTEL_LIBRARY, label))
    for digest, entry in material['captured_shaders'].items():
        if 'category' in entry:
            refused.setdefault(digest, (entry['category'], entry['category']))
        else:
            refused.setdefault(digest, (INTEL_SHADER, f'shader captured from Intel\'s runtime ({", ".join(entry["names"])}, '
                                                      f'shader model {entry["shader_model"]})'))
    return refused


def reference(config, material):
    """({sha256: label} of Intel and Intel-derived files, {sha256: label} of own profile files, {table: checksums})."""
    intel = {digest: label for digest, (_category, label) in refused_files(config, material).items()}
    own = {entry['sha256']: name for name, entry in config.lock['work'][PROFILE_GROUP]['files'].items()
           if entry['origin'] == 'own' and name.endswith('.dxil')}
    # the own shader files a variant ships beside or in place of the profile's (inputs.lock.json "tree" groups)
    for group, spec in config.lock.get('tree', {}).items():
        if isinstance(spec, dict) and 'files' in spec:
            own.update({entry['sha256']: f'{group}/{name}' for name, entry in spec['files'].items()
                        if entry.get('origin') == 'own' and name.endswith('.dxil')})
    tables = {digest: (entry['window_sum'], entry['window_moment']) for digest, entry in material['warp_tables'].items()}
    return intel, own, tables


def public_material(config):
    """The public form of intel_material.json: every refused sha256 with its category only, and the weight tables'
    checksums (no names, run folders or provenance). check refuses the same files with either form."""
    material = load_material()
    return dict(
        about=PUBLIC_ABOUT,
        refused={digest: category for digest, (category, _label) in sorted(refused_files(config, material).items())},
        warp_tables={digest: dict(role=WARP_TABLES[digest], bytes=TABLE_BYTES, window_sum=entry['window_sum'],
                                  window_moment=entry['window_moment'])
                     for digest, entry in sorted(material['warp_tables'].items())},
    )


# --------------------------------------------------------------------------------------------------------------- check

def components_of(root):
    """{relative path: component} from an assembled package's manifest, else every file in 'unlisted'."""
    manifest = root / 'manifest.json'
    if not manifest.is_file():
        return {}
    out = {}
    for component, names in json.loads(manifest.read_text()).get('components', {}).items():
        for name in names:
            out[name] = component
    return out


def check_tree(root, config, dxc, detectors=None):
    """Findings for every file below root: [{file, check, detail}] plus scan statistics."""
    material = load_material()
    intel, own, tables = reference(config, material)
    foreign = third_party(config)
    detectors = detectors or {'intel-file', 'not-own-shader', 'shader-model-6.4', 'embedded-capture', 'warp-table-bytes',
                              'warp-table-constant'}
    findings, stats = [], dict(files=0, bytes=0, dxil_files=0, containers=0, embedded_dxil=0,
                               embedded_dxil_third_party=0, constant_arrays=0, shader_models={})
    with tempfile.TemporaryDirectory(prefix='intel-free-') as scratch_name:
        scratch = Path(scratch_name)
        for path in sorted(p for p in root.rglob('*') if p.is_file()):
            name = str(path.relative_to(root))
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            stats['files'] += 1
            stats['bytes'] += len(data)

            def found(check, detail):
                if check in detectors:
                    findings.append(dict(file=name, check=check, detail=detail))

            if digest in intel:
                found('intel-file', intel[digest])
            whole = container_parts(data)
            model = shader_model(data)
            if path.suffix == '.dxil' or whole:
                stats['dxil_files'] += 1
                stats['shader_models'][model or 'none'] = stats['shader_models'].get(model or 'none', 0) + 1
                if model == INTEL_SHADER_MODEL:
                    found('shader-model-6.4', 'DXIL shader model 6.4')
                if (path.suffix == '.dxil' or model is not None) and digest not in own:
                    found('not-own-shader', 'not a profile shader compiled from this project\'s HLSL')
            for offset, size in embedded_containers(data):
                stats['containers'] += 1
                container = data[offset:offset + size]
                inner = hashlib.sha256(container).hexdigest()
                embedded = not (offset == 0 and size == len(data))
                if inner in intel and embedded:
                    found('embedded-capture', f'container at {offset}: {intel[inner]}')
                inner_model = shader_model(container)
                if embedded and inner_model is not None:
                    stats['embedded_dxil'] += 1
                    if inner_model == INTEL_SHADER_MODEL:
                        found('shader-model-6.4', f'container at {offset}: DXIL shader model 6.4')
                    if digest in foreign:
                        stats['embedded_dxil_third_party'] += 1
                    elif inner not in own:
                        found('not-own-shader', f'container at {offset}: DXIL (shader model {inner_model}) that is '
                                                'neither this project\'s nor in a pinned third-party binary')
                if dxc is not None and shader_model(container) is not None and 'warp-table-constant' in detectors:
                    arrays = constant_arrays(disassemble(dxc, container, scratch))
                    stats['constant_arrays'] += len(arrays)
                    for array in arrays:
                        for start, table in table_windows(array, tables):
                            found('warp-table-constant', f'container at {offset}: constant array holds the '
                                                         f'{WARP_TABLES[table]} ({table[:8]}) at byte {start}')
            if 'warp-table-bytes' in detectors:
                for start, table in table_windows(data, tables):
                    found('warp-table-bytes', f'{WARP_TABLES[table]} ({table[:8]}) at byte {start}')
    return findings, stats


def check(config, root, allowed=(), skip_constant_scan=False):
    """The report of one tree: result 'pass' when every finding lies in an allowed component."""
    root = root.resolve()
    if not root.is_dir():
        raise ReleaseError(f'Not a directory: {root}')
    dxc = config.dxc()
    if dxc is None and not skip_constant_scan:
        raise ReleaseError('The constant-array scan needs DXC: set XEMFG_DXC (or --dxc), or pass --skip-constant-scan')
    findings, stats = check_tree(root, config, None if skip_constant_scan else dxc)
    components = components_of(root)
    unknown_allowed = sorted(set(allowed) - set(components.values())) if components else sorted(allowed)
    if unknown_allowed:
        raise ReleaseError(f'--allow-component names no component of this package: {", ".join(unknown_allowed)}')
    failing, tolerated = [], {}
    for item in findings:
        item['component'] = components.get(item['file'], 'unlisted' if components else None)
        if item['component'] in allowed:
            tolerated.setdefault(item['component'], []).append(item)
        else:
            failing.append(item)
    by_component = {}
    for item in findings:
        by_component.setdefault(item['component'] or '-', {}).setdefault(item['check'], 0)
        by_component[item['component'] or '-'][item['check']] += 1
    return dict(
        checked=root.name, result=FAIL if failing else PASS_ALLOWED if findings else PASS,
        intel_free_complete=not findings,
        third_party_binaries=sorted({label for label in third_party(config).values()}),
        constant_scan='skipped (no DXC)' if skip_constant_scan else 'dxc -dumpbin of every DXIL container',
        statistics=stats, findings_by_component=by_component,
        allowed_components={c: f'{len(v)} findings reported, not failing' for c, v in tolerated.items()},
        failing=failing, allowed=[i for v in tolerated.values() for i in v],
        reference=dict(material=MATERIAL.name, refused_sha256=len(refused_files(config, load_material())),
                       warp_tables=sorted(t[:8] for t in WARP_TABLES)),
    )


def maintainer_commands():
    """release/record_intel_material.py (record, self-test), or None in a tree without it (the public tree)."""
    try:
        import record_intel_material
    except ModuleNotFoundError as error:
        if error.name != 'record_intel_material':
            raise
        return None
    return record_intel_material


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('check', help='check a package or any directory')
    run.add_argument('path', type=Path)
    run.add_argument('--allow-component', action='append', default=[], metavar='NAME',
                     help='report findings in this manifest component without failing (repeatable)')
    run.add_argument('--skip-constant-scan', action='store_true', help='do not read DXIL constant arrays (no DXC)')
    run.add_argument('--report', type=Path, help='also write the full report to this JSON file')
    maintainers = maintainer_commands()
    if maintainers:
        maintainers.add_commands(commands)
    args = parser.parse_args()
    config = Config.from_args(args)
    if args.command != 'check':
        print(json.dumps(maintainers.run(args.command, config), indent=2))
        return
    report = check(config, args.path, tuple(args.allow_component), args.skip_constant_scan)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + '\n')
    shown = {k: v for k, v in report.items() if k not in ('failing', 'allowed')}
    shown['failing'] = report['failing'][:20]
    print(json.dumps(shown, indent=2))
    if report['result'] == PASS_ALLOWED:
        print(f'note: passes only through --allow-component ({", ".join(report["allowed_components"])}); '
              'the tree is not Intel-free as a whole', file=sys.stderr)
    if report['result'] == FAIL:
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        sys.exit(f'error: {error}')
