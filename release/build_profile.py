#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Rebuild the committed shader profile (release/profile/) from this tree's HLSL and compare it byte for byte.

release/profile/ holds the shader-profile files of this project's own origin that the Intel-free builds read (every
file of release/intel_free.json "keep" and "rewrite"): 33 compute shaders (DXIL) and 9 tables and markers. Their
recipes are in release/profile/origin.json: the HLSL source under src/kernels/, entry point, target, compiler options
and preprocessor definitions of each shader, and for two of them a short IR pass after compilation (below).

  python3 release/build_profile.py check [--out DIR] [--only NAME ...] [--no-rebuild] [--report FILE]
  python3 release/build_profile.py show

check runs, in order:
  files       release/profile holds exactly the profile-type files (.dxil, .txt, .required, .rs) origin.json lists;
              each has the recorded sha256 and size and the sha256 that inputs.lock.json pins for the profile (work
              group "profile-cl-wino-q33", origin "own"); the set is intel_free.json keep + rewrite, so
              XEMFG_PROFILE=release/profile serves the Intel-free builds unchanged
  shaders     each DXIL has the recorded shader model; waves.txt names each shader's module hash (FNV-1a 64 of its
              bytes, as the add-on computes it) with the recorded wave size; dispatch-scale.txt scales only shaders of
              this profile or the line intel_free.json drops
  sources     every file under src/kernels/ starts with an SPDX-License-Identifier line and names no host path
  toolchain   the DXC files against inputs.lock.json toolchain "profile" (Microsoft's DirectX Shader Compiler release
              v1.9.2607 for Linux); a different DXC is reported, and byte identity is then not expected
  rebuild     each shader is compiled again (into a temporary directory, or --out) and compared with the committed file

Pipelines (origin.json "build.pipeline"):
  dxc            dxc -T <target> -E <entry> <options> -D <definition>... <source> -Fo <file>
  dxc+packed16   dxc as above with -Fc (the module's LLVM IR as text); then packed16() below; then the DXC release's own
                 tools: opt -S -early-cse -dce -strip-dead-prototypes, dxa (IR to DXIL container), dxv (validate, sign)

A recipe whose rebuild cannot be reproduced is marked in origin.json "rebuild" as "committed-binary, rebuild
unverified: <reason>"; check reports it and does not compile it. Today every shader rebuilds byte for byte.

XEMFG_DXC (or --dxc) names the DXC directory (bin/dxc, bin/opt, bin/dxa, bin/dxv, lib/libdxcompiler.so). Without it,
check runs every step but the rebuild and says so; --no-rebuild skips the rebuild on purpose.

Exit status 0 when every check passes (and every shader was rebuilt byte-identical, unless --no-rebuild), 1 otherwise.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import REPO, RELEASE, Config, ReleaseError, add_arguments, fnv1a64, sha256  # noqa: E402
import host_paths  # noqa: E402

PROFILE = RELEASE / 'profile'
ORIGIN = PROFILE / 'origin.json'
KERNELS = REPO / 'src' / 'kernels'
LOCK_GROUP = 'profile-cl-wino-q33'
TOOLCHAIN_KEY = 'profile'
TOOLS = ('bin/dxc', 'bin/opt', 'bin/dxa', 'bin/dxv', 'lib/libdxcompiler.so', 'lib/libdxil.so')
PROFILE_SUFFIXES = ('.dxil', '.txt', '.required', '.rs')  # the file types the add-on and the builds read from a profile
UNVERIFIED = 'committed-binary, rebuild unverified'


# ------------------------------------------------------------------------------------------------------- packed16 pass

DOT = re.compile(r'^(  )(%[\w.]+) = call i32 @dx.op.dot4AddPacked.i32\(i32 163, i32 ([%\w.-]+), i32 ([%\w.-]+), '
                 r'i32 ([%\w.-]+)\).*$')
WEIGHT_LOAD = re.compile(r'  (%[\w.]+) = call %dx.types.ResRet.i32 @dx.op.rawBufferLoad.i32\(i32 139, %dx.types.Handle '
                         r'(%[\w.]+), i32 ([%\w.-]+), i32 0, i8 15, i32 4\)')
EXTRACT = re.compile(r'  (%[\w.]+) = extractvalue %dx.types.ResRet.i32 (%[\w.]+), ([0-3])')


def prepared_weights(source, prefix):
    """Point every coefficient load of the structured buffer at t1 (16-byte elements) at its prepared form: element i of
    the packed int8 weights has two prepared elements at prefix + 2i (even) and prefix + 2i + 1 (odd), each word a pair of
    signed 16-bit coefficients. Returns the IR and {packed word: [even pair, odd pair]}."""
    definitions = dict(re.findall(r'^  (%[\w.]+) = (.*)$', source, re.M))
    handles = set()
    for name, rhs in definitions.items():
        m = re.match(r'call %dx.types.Handle @dx.op.annotateHandle\(i32 216, %dx.types.Handle (%[\w.]+), '
                     r'%dx.types.ResourceProperties \{ i32 12, i32 16 \}', rhs)
        if m and 'i32 1, i32 1, i32 0, i8 0' in definitions.get(m[1], ''):
            handles.add(name)
    if not handles:
        raise ReleaseError('packed16: no structured coefficient buffer at t1')
    out, loads, mapping, serial = [], {}, {}, 0
    for line in source.splitlines():
        out.append(line)
        m = WEIGHT_LOAD.match(line)
        if m and m[2] in handles:
            serial += 1
            n = f'%bc250_preweight{serial}'
            loads[m[1]] = n
            out.extend([f'  {n}scaled = shl i32 {m[3]}, 1', f'  {n}index = add i32 {n}scaled, {prefix}',
                        f'  {n}oddindex = add i32 {n}index, 1',
                        f'  {n}even = call %dx.types.ResRet.i32 @dx.op.rawBufferLoad.i32(i32 139, %dx.types.Handle {m[2]}, '
                        f'i32 {n}index, i32 0, i8 15, i32 4)',
                        f'  {n}odd = call %dx.types.ResRet.i32 @dx.op.rawBufferLoad.i32(i32 139, %dx.types.Handle {m[2]}, '
                        f'i32 {n}oddindex, i32 0, i8 15, i32 4)'])
        m = EXTRACT.match(line)
        if m and m[2] in loads:
            n, lane, values = loads[m[2]], int(m[3]), []
            for part in ('even', 'odd'):
                value = n + part + str(lane)
                out.extend([f'  {value}word = extractvalue %dx.types.ResRet.i32 {n}{part}, {lane}',
                            f'  {value} = bitcast i32 {value}word to <2 x i16>'])
                values.append(value)
            mapping[m[1]] = values
    if not mapping:
        raise ReleaseError('packed16: no coefficient word mapped')
    return '\n'.join(out) + '\n', mapping


def packed_dots(source, prepared):
    """Replace each dot4AddPacked (four int8 products added to an int32) by two <2 x i16> multiplies and adds: the
    activation word's bytes sign-extended into even/odd i16 lanes, the coefficients from prepared_weights(). Exact when
    every 16-bit partial stays in range, which the model owner proves for each model before it binds the prepared
    coefficients. The module becomes shader model 6.9 with native 16-bit operations enabled. Returns (IR, dot count)."""
    out, cache, count = [], {}, 0

    def unpack(value):
        if value in prepared:
            return prepared[value]
        if value in cache:
            return cache[value]
        n = f'%bc250_bound_unpack{count}_{len(cache)}'
        out.extend([f'  {n}packed = bitcast i32 {value} to <2 x i16>', f'  {n}shift = shl <2 x i16> {n}packed, <i16 8, i16 8>',
                    f'  {n}even = ashr <2 x i16> {n}shift, <i16 8, i16 8>', f'  {n}odd = ashr <2 x i16> {n}packed, <i16 8, i16 8>'])
        cache[value] = [n + 'even', n + 'odd']
        return cache[value]

    for line in source.splitlines():
        if re.match(r'\s*(?:; <label>:|[\w.]+:)', line):
            cache = {}  # an unpacked activation is reused only inside its basic block
        m = DOT.match(line)
        if not m:
            out.append(line)
            continue
        _indent, dest, base, a, b = m.groups()
        count += 1
        n = f'%bc250_bound_dot{count}'
        av, bv = unpack(a), unpack(b)
        out.extend([f'  {n}p0 = mul <2 x i16> {av[0]}, {bv[0]}', f'  {n}p1 = mul <2 x i16> {av[1]}, {bv[1]}',
                    f'  {n}first = add <2 x i16> zeroinitializer, {n}p0', f'  {n}partial = add <2 x i16> {n}first, {n}p1'])
        for lane in range(2):
            out.extend([f'  {n}lane{lane} = extractelement <2 x i16> {n}partial, i32 {lane}',
                        f'  {n}wide{lane} = sext i16 {n}lane{lane} to i32'])
        out.extend([f'  {n}delta = add i32 {n}wide0, {n}wide1', f'  {dest} = add i32 {base}, {n}delta'])
    text = '\n'.join(out) + '\n'
    if count:
        text = re.sub(r'^declare i32 @dx.op.dot4AddPacked.i32.*\n', '', text, flags=re.M)
    text = re.sub(r'(!\d+ = !\{i32 0, i64 )(\d+)(, i32 4,)', lambda m: m[1] + str(int(m[2]) | 0x800020) + m[3], text)
    for key in ('dx.version', 'dx.valver'):
        node = re.search(r'!' + re.escape(key) + r' = !\{!(\d+)\}', text)[1]
        text = re.sub('!' + node + r' = !\{i32 1, i32 \d+\}', '!' + node + ' = !{i32 1, i32 9}', text)
    text = re.sub(r'!\{!"cs", i32 6, i32 \d+\}', '!{!"cs", i32 6, i32 9}', text)
    return text, count


def packed16(source, prefix, expected_dots):
    text, prepared = prepared_weights(source, prefix)
    text, count = packed_dots(text, prepared)
    if count != expected_dots:
        raise ReleaseError(f'packed16: {count} dot products rewritten, the recipe expects {expected_dots}')
    return text


# -------------------------------------------------------------------------------------------------------------- compile

class Dxc:
    """The DXC release directory: bin/dxc and, for the packed16 pipeline, bin/opt, bin/dxa and bin/dxv."""

    def __init__(self, binary):
        self.dxc = binary
        self.root = binary.parent.parent
        lib = self.root / 'lib'
        self.env = dict(os.environ, LD_LIBRARY_PATH=str(lib) + (':' + os.environ['LD_LIBRARY_PATH']
                                                                 if os.environ.get('LD_LIBRARY_PATH') else ''))

    def tool(self, name):
        path = self.root / 'bin' / name
        if not path.is_file():
            raise ReleaseError(f'DXC directory has no bin/{name} (the packed16 pipeline needs opt, dxa and dxv)')
        return path

    def run(self, command):
        result = subprocess.run([str(c) for c in command], capture_output=True, text=True, env=self.env)
        if result.returncode:
            raise ReleaseError(f'{Path(str(command[0])).name} failed ({result.returncode}): '
                               + (result.stderr or result.stdout)[-1500:])
        return result

    def version(self):
        return self.run([self.dxc, '--version']).stdout.strip()


def compile_command(dxc, recipe, source, output, extra=()):
    return [dxc.dxc, '-T', recipe['target'], '-E', recipe['entry'], *recipe.get('options', []),
            *[v for d in recipe.get('defines', []) for v in ('-D', d)], source, '-Fo', output, *extra]


def rebuild(dxc, name, recipe, folder):
    """Compile one shader from its recipe into folder; returns the output file."""
    source = REPO / recipe['source']
    if not source.is_file():
        raise ReleaseError(f'{name}: source {recipe["source"]} is missing')
    stem = folder / Path(name).stem
    pipeline = recipe['pipeline']
    if pipeline == 'dxc':
        output = folder / name
        dxc.run(compile_command(dxc, recipe, source, output))
        return output
    if pipeline == 'dxc+packed16':
        listing = stem.with_suffix('.source.ll')
        dxc.run(compile_command(dxc, recipe, source, stem.with_suffix('.source.dxil'), ('-Fc', listing)))
        spec = recipe['packed16']
        rewritten = stem.with_suffix('.ll')
        rewritten.write_text(packed16(listing.read_text(), spec['prefix_vectors'], spec['dot_products']))
        optimized = stem.with_suffix('.optimized.ll')
        dxc.run([dxc.tool('opt'), '-S', '-early-cse', '-dce', '-strip-dead-prototypes', rewritten, '-o', optimized])
        raw = stem.with_suffix('.raw.dxil')
        dxc.run([dxc.tool('dxa'), optimized, '-o', raw])
        output = folder / name
        dxc.run([dxc.tool('dxv'), raw, '-o', output])
        return output
    raise ReleaseError(f'{name}: unknown pipeline {pipeline!r}')


# --------------------------------------------------------------------------------------------------------------- checks

def load_origin():
    origin = json.loads(ORIGIN.read_text())
    if origin.get('schema') != 1:
        raise ReleaseError('release/profile/origin.json: unknown schema')
    return origin


def check_files(origin, lock, findings):
    files = origin['files']
    present = {p.name for p in PROFILE.iterdir() if p.is_file() and p.suffix in PROFILE_SUFFIXES}
    for name in sorted(present - set(files)):
        findings.append(f'files: {name} is in release/profile but not in origin.json')
    for name in sorted(set(files) - present):
        findings.append(f'files: {name} is missing from release/profile')
    locked = lock.get('work', {}).get(LOCK_GROUP, {}).get('files', {})
    for name, entry in sorted(files.items()):
        path = PROFILE / name
        if not path.is_file():
            continue
        digest = sha256(path)
        if digest != entry['sha256'] or path.stat().st_size != entry['bytes']:
            findings.append(f'files: {name} differs from origin.json')
        pin = locked.get(name)
        if pin is None:
            findings.append(f'files: {name} is not in inputs.lock.json {LOCK_GROUP}')
        elif pin['sha256'] != digest or pin.get('origin') != 'own':
            findings.append(f'files: {name} differs from inputs.lock.json {LOCK_GROUP} (or its origin is not "own")')
    definition = json.loads((RELEASE / 'intel_free.json').read_text())['profile']
    wanted = set(definition['keep']) | set(definition['rewrite'])
    if set(files) != wanted:
        findings.append('files: origin.json does not list exactly intel_free.json keep + rewrite (missing '
                        f'{sorted(wanted - set(files))}, extra {sorted(set(files) - wanted)})')
    return wanted


def check_shaders(origin, findings):
    from check_intel_free import shader_model  # the static check's DXIL container parser
    files = origin['files']
    waves = {}
    for line in (PROFILE / 'waves.txt').read_text().splitlines():
        fields = line.split()
        if fields:
            waves[fields[0]] = int(fields[1])
    shaders = {name: entry for name, entry in files.items() if entry['kind'] == 'shader'}
    for name, entry in sorted(shaders.items()):
        path = PROFILE / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        model = shader_model(data)
        if model != entry['shader_model']:
            findings.append(f'shaders: {name} is shader model {model}, origin.json says {entry["shader_model"]}')
        module = fnv1a64(data)
        if waves.get(module) != entry['wave']:
            findings.append(f'shaders: waves.txt gives module {module} ({name}) wave {waves.get(module)}, '
                            f'origin.json says {entry["wave"]}')
    dropped = set()
    for rule in json.loads((RELEASE / 'intel_free.json').read_text())['profile']['rewrite'].values():
        dropped |= set(rule['drop_shaders'])
    for line in (PROFILE / 'dispatch-scale.txt').read_text().splitlines():
        fields = line.split()
        if fields and f'{fields[0]}.dxil' not in shaders and fields[0] not in dropped:
            findings.append(f'shaders: dispatch-scale.txt scales {fields[0]}, which is neither a shader of this profile '
                            'nor dropped by intel_free.json')
    return shaders


def check_sources(origin, findings):
    names = sorted(p for p in KERNELS.iterdir() if p.is_file())
    for path in names:
        data = path.read_bytes()
        if not data.startswith(b'// SPDX-License-Identifier: '):
            findings.append(f'sources: {path.relative_to(REPO)} has no SPDX-License-Identifier first line')
        if host_paths.in_file_bytes(data, review=True):  # the detector export_tree.py reviews exports with
            findings.append(f'sources: {path.relative_to(REPO)} names a host path')
    used = {entry['build']['source'] for entry in origin['files'].values() if entry.get('build')}
    for source in sorted(used):
        if not (REPO / source).is_file():
            findings.append(f'sources: {source} (named by origin.json) is missing')
    return [str(p.relative_to(REPO)) for p in names]


def check_toolchain(dxc, lock):
    pin = lock.get('toolchain', {}).get(TOOLCHAIN_KEY)
    if dxc is None:
        return dict(dxc=None, matches_pin=None)
    files = {name: sha256(dxc.root / name) for name in TOOLS if (dxc.root / name).is_file()}
    expected = (pin or {}).get('files', {})
    same = bool(expected) and all(files.get(name) == digest for name, digest in expected.items())
    return dict(dxc=dxc.version(), files=files, matches_pin=same,
                pin=dict(release=pin.get('release'), version=pin.get('version')) if pin else None)


def check(config, out=None, only=(), no_rebuild=False):
    origin, lock = load_origin(), config.lock
    findings = []
    check_files(origin, lock, findings)
    shaders = check_shaders(origin, findings)
    sources = check_sources(origin, findings)
    if only:
        unknown = sorted(set(only) - set(shaders))
        if unknown:
            raise ReleaseError('--only names no shader of the profile: ' + ', '.join(unknown))
        shaders = {name: shaders[name] for name in only}
    binary = None if no_rebuild else config.dxc()
    dxc = Dxc(binary) if binary else None
    toolchain = check_toolchain(dxc, lock)
    rows = {}
    if dxc is None:
        for name in shaders:
            rows[name] = 'skipped (--no-rebuild)' if no_rebuild else 'not rebuilt (no XEMFG_DXC)'
    else:
        with tempfile.TemporaryDirectory(prefix='build-profile-') as scratch:
            folder = Path(out).resolve() if out else Path(scratch)
            folder.mkdir(parents=True, exist_ok=True)
            for name, entry in sorted(shaders.items()):
                if entry['rebuild'].startswith(UNVERIFIED):
                    rows[name] = entry['rebuild']
                    continue
                work = folder / Path(name).stem
                work.mkdir(exist_ok=True)
                try:
                    output = rebuild(dxc, name, entry['build'], work)
                except ReleaseError as error:
                    rows[name] = f'failed: {error}'
                    findings.append(f'rebuild: {name} failed: {error}')
                    continue
                # Compared with the committed file (check_files compares that with origin.json and the lock).
                committed = PROFILE / name
                expected = sha256(committed) if committed.is_file() else entry['sha256']
                digest = sha256(output)
                if digest == expected:
                    rows[name] = 'byte-identical'
                else:
                    rows[name] = f'differs ({digest})'
                    findings.append(f'rebuild: {name} rebuilt as {digest[:16]}…, committed {expected[:16]}…'
                                    + ('' if toolchain['matches_pin'] else ' (DXC is not the pinned release)'))
    identical = sum(1 for status in rows.values() if status == 'byte-identical')
    unverified = sorted(name for name, status in rows.items() if status.startswith(UNVERIFIED))
    complete = dxc is not None and identical == len(shaders) - len(unverified)
    report = dict(
        result='pass' if not findings and (complete or no_rebuild) else 'fail',
        files=len(origin['files']), shaders=len(shaders), rebuilt_byte_identical=identical, unverified=unverified,
        rebuild=rows, sources=sources, toolchain=toolchain, findings=findings,
        rebuilt_into=str(Path(out).resolve()) if out and dxc else None,
    )
    if dxc is None and not no_rebuild:
        report['note'] = 'XEMFG_DXC is not set: nothing was compiled, so byte identity was not checked'
    return report


def show():
    for name, entry in sorted(load_origin()['files'].items()):
        build = entry.get('build')
        recipe = (f'{build["source"]} {build["pipeline"]} {" ".join(build.get("defines", []))}' if build
                  else 'data file')
        print(f'{name:34} {entry["kind"]:7} {entry["rebuild"][:24]:24} {recipe}')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    run = commands.add_parser('check', help='check release/profile and rebuild its shaders')
    add_arguments(run)
    run.add_argument('--out', type=Path, help='keep the rebuilt files (and the packed16 intermediates) in this directory')
    run.add_argument('--only', nargs='+', default=(), metavar='NAME', help='rebuild only these shaders')
    run.add_argument('--no-rebuild', action='store_true', help='run every check but the rebuild')
    run.add_argument('--report', type=Path, help='also write the report as JSON')
    commands.add_parser('show', help='list the profile files and their recipes')
    args = parser.parse_args()
    if args.command == 'show':
        show()
        return
    report = check(Config.from_args(args), args.out, args.only, args.no_rebuild)
    text = json.dumps(report, indent=2)
    if args.report:
        args.report.write_text(text + '\n')
    print(text)
    if report['result'] != 'pass':
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        sys.exit(f'error: {error}')
