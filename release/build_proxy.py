#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the enabler-free add-on: libxess_fg.dll, a proxy for Intel's unmodified XeFG runtime with the Intel-free add-on
inside, so a package needs no XeSSMFG enabler. --variant picks the build:

  intel-free-mfg  (default, release/intel_free_mfg.json; the released build since 1.0.0) the frame count Intel's
                  runtime runs, including the multi-frame network when another module the user installed has lifted
                  Intel's limit, beside which it keeps its callers' view and steps aside rather than end the game
                  (src/game/mfg_proxy_coexist.h)
  intel-free-2x   (release/intel_free_2x.json; the 0.9.0 build, maintainers' tree only) one generated frame per real
                  frame (2x)

Steps:
  1. Check the inputs against release/inputs.lock.json: Intel's XeSS SDK headers (intel-xess), Intel's runtime DLL at the
     same commit (intel-xess-runtime; never shipped) and the locked shader profile. The runtime must also be the file
     packaging/dependencies.json makes installations download as bc250_xefg_original.dll.
  2. Assemble the profile into <build>/<output_dir>/profile: the Intel-free profile of release/intel_free.json
     (prepared and checked by release/proxy_common.py) without the files the variant drops (2x: the multi-frame kernels),
     with the variant's own files (mfg: "replace", nine U-Net shaders in their XU-1 form from the lock's tree group
     profile-intel-free-mfg = release/profile-mfg, each waves.txt line rewritten in place to the new module) and with
     the waves.txt lines it appends (mfg: "append_waves", wave 32 for five of Intel's pipelines; 128 entries).
     waves.txt must be a table the pacing layer reads in full (proxy_common.wave_table).
  3. Generate into <build>/<output_dir>/generated:
       probe_core.h          src/probe.c up to its scene_motion.h include, fixed modes patched in (proxy_common.py)
       profile_manifest.h    size and FNV-1a hash of every profile file
       original_manifest.h   size and FNV-1a hash of Intel's runtime (the proxy loads nothing else)
       mfg_proxy_exports.h   the wrapped XeFG entries as this DLL's own exports calling Intel's: 2x, the five of
                             proxy_common.py API_HOOKS with intel_free_2x.json's changes; mfg, the seven of
                             proxy_common.py MFG_PROXY_HOOKS, each with a tail-calling path
       proxy.def             Intel's 57 exports at their ordinals (wrapped ones here, the rest forwarded to
                             bc250_xefg_original) and the add-on's settings exports after them
  4. Compile src/game/mfg_proxy.c with clang for x86_64-w64-windows-gnu against Wine's headers and import libraries,
     twice, and require identical output. No MinHook: nothing is hooked.
  5. Check the DLL: Intel's export table reproduced ordinal for ordinal, wrapped entries implemented here, every other
     one a forwarder to bc250_xefg_original, no other exports than the settings interface; imports only from the
     allowed DLLs; no reference to the XeSSMFG enabler or version.dll.
  6. Write <build>/<output_dir>/build.json (no absolute paths) and compare with the lock's reference
     ("libxess_fg.dll (<variant>)").

Exit status 0 when the build matches the reference (or there is none yet, or --no-reference-check), 1 otherwise.
"""
import argparse
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import REPO, RELEASE, Config, ReleaseError, add_arguments, fnv1a64, relative, sha256, tool_version  # noqa: E402
import proxy_common as common  # noqa: E402

VARIANTS = {'intel-free-2x': RELEASE / 'intel_free_2x.json', 'intel-free-mfg': RELEASE / 'intel_free_mfg.json'}
DEFAULT_VARIANT = 'intel-free-mfg'
DEFINITION = VARIANTS[DEFAULT_VARIANT]
RUNTIME_GROUP, RUNTIME_FILE = 'intel-xess-runtime', 'bin/libxess_fg.dll'
DEPENDENCIES = REPO / 'packaging' / 'dependencies.json'
ENABLER_MARKERS = (b'XeSSMFG', b'version.dll', b'v\0e\0r\0s\0i\0o\0n\0.\0d\0l\0l\0', b'X\0e\0S\0S\0M\0F\0G\0')


# ---------------------------------------------------------------------------------------------------- PE export tables

def _sections(data):
    if data[:2] != b'MZ':
        raise ReleaseError('not a PE file')
    pe = struct.unpack_from('<I', data, 0x3c)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        raise ReleaseError('not a PE file')
    count, optional_size = struct.unpack_from('<H', data, pe + 6)[0], struct.unpack_from('<H', data, pe + 20)[0]
    optional = pe + 24
    if struct.unpack_from('<H', data, optional)[0] != 0x20b:
        raise ReleaseError('not a PE32+ (x86-64) file')
    sections = [struct.unpack_from('<8sIIII', data, optional + optional_size + 40 * i) for i in range(count)]
    return optional, sections


def _offset(sections, rva):
    for _name, virtual_size, address, raw_size, raw in sections:
        if address <= rva < address + max(virtual_size, raw_size):
            return raw + rva - address
    raise ReleaseError(f'RVA {rva:#x} lies in no section')


def _string(data, sections, rva):
    at = _offset(sections, rva)
    return data[at:data.index(b'\0', at)].decode('ascii')


def pe_exports(data):
    """[(ordinal, name or None, forwarder or None)] of a PE32+ DLL's export table, by ordinal."""
    optional, sections = _sections(data)
    export_rva, export_size = struct.unpack_from('<II', data, optional + 112)
    if not export_rva:
        return []
    fields = struct.unpack_from('<IIHHIIIIIII', data, _offset(sections, export_rva))
    base, functions, names, function_rva, name_rva, ordinal_rva = fields[5], fields[6], fields[7], *fields[8:11]
    addresses = struct.unpack_from(f'<{functions}I', data, _offset(sections, function_rva))
    name_rvas = struct.unpack_from(f'<{names}I', data, _offset(sections, name_rva)) if names else ()
    indices = struct.unpack_from(f'<{names}H', data, _offset(sections, ordinal_rva)) if names else ()
    named = {index: _string(data, sections, rva) for index, rva in zip(indices, name_rvas)}
    rows = []
    for index, rva in enumerate(addresses):
        if rva:
            forwarder = _string(data, sections, rva) if export_rva <= rva < export_rva + export_size else None
            rows.append((base + index, named.get(index), forwarder))
    return rows


def pe_imports(data):
    """Names of the DLLs a PE32+ file imports from (its import directory)."""
    optional, sections = _sections(data)
    import_rva = struct.unpack_from('<I', data, optional + 120)[0]
    names, at = [], _offset(sections, import_rva) if import_rva else None
    while at is not None:
        descriptor = struct.unpack_from('<IIIII', data, at)
        if not any(descriptor):
            break
        names.append(_string(data, sections, descriptor[3]))
        at += 20
    return names


# ---------------------------------------------------------------------------------------------------------- generation

def proxy_hooks(definition):
    """The variant's wrapped entries: a named table of proxy_common.py (HOOK_TABLES), or proxy_common.API_HOOKS with the
    definition's replacements (each must match its hook's code once)."""
    spec = definition['addon']['hooks']
    if isinstance(spec, str):
        if spec not in common.HOOK_TABLES:
            raise ReleaseError(f'{definition["variant"]}: proxy_common.py has no hook table {spec}')
        hooks = {name: dict(hook) for name, hook in common.HOOK_TABLES[spec].items()}
        for name, hook in hooks.items():
            code = ''.join(hook.get(key, '') for key in ('before', 'after', 'tail_before'))
            for leftover in ('mfg_xell_pace', 'mfg_status_', 'mfg_enabler'):
                if leftover in code:
                    raise ReleaseError(f'{name}: the proxy has no {leftover}* (frame-start pacer or enabler) to call')
        return hooks
    if set(spec) - {'about'} != set(common.API_HOOKS):
        raise ReleaseError('intel_free_2x.json hooks must name exactly the entries proxy_common.py API_HOOKS wraps')
    hooks = {}
    for name, original in common.API_HOOKS.items():
        hook = dict(original)
        for old, new in spec[name]:
            matches = [key for key in ('before', 'after') if old in hook[key]]
            if len(matches) != 1 or hook[matches[0]].count(old) != 1:
                raise ReleaseError(f'proxy_common.py API_HOOKS changed: {old!r} is not in the {name} hook exactly once')
            hook[matches[0]] = hook[matches[0]].replace(old, new)
        for leftover in ('mfg_xell_pace', 'mfg_status_', 'mfg_enabler'):
            if leftover in hook['before'] + hook['after']:
                raise ReleaseError(f'{name}: the proxy has no {leftover}* (frame-start pacer or enabler) to call')
        hooks[name] = hook
    return hooks


def _arguments(name, arguments, replace):
    if not replace:
        return list(arguments)
    original, replacement = replace
    if original not in arguments:
        raise ReleaseError(f'{name}: Intel header has no parameter {original}')
    out = list(arguments)
    out[out.index(original)] = replacement
    return out


def tail_wrapper(result_type, name, signature, arguments, spec):
    """An entry with a tail-calling path (MFG_PROXY_HOOKS): Intel's entry is resolved once; "always_tail" entries run
    "before" and tail-call; the others tail-call when "tail_when" holds and otherwise take the ordinary path."""
    head = (f'XEFG_SWAPCHAIN_API {result_type} {name}({signature}){{static __typeof__(&{name}) original;static LONG calls;'
            f'if(!original&&!(original=(void*)resolve("{name}")))return XEFG_SWAPCHAIN_RESULT_ERROR_CANT_LOAD_LIBRARY;'
            f'InterlockedIncrement(&calls);')
    if spec.get('always_tail'):
        return (head + f'{spec["before"]}__attribute__((musttail)) return original({", ".join(arguments)});}}\n')
    body = ''
    if 'tail_when' in spec:
        tail = _arguments(name, arguments, spec.get('tail_replace'))
        body += (f'if({spec["tail_when"]}){{{spec.get("tail_before", "")}'
                 f'__attribute__((musttail)) return original({", ".join(tail)});}}')
    ordinary = _arguments(name, arguments, spec.get('replace'))
    body += (f'{spec["before"]}{result_type} result=original({", ".join(ordinary)});{spec["after"]}(void)calls;'
             f'return result;}}\n')
    return head + body


def exports_header(headers_text, hooks):
    """mfg_proxy_exports.h: each wrapped entry as an export of this DLL that calls Intel's through resolve()."""
    code = []
    declarations = re.findall(r'XEFG_SWAPCHAIN_API\s+(xefg_swapchain_result_t)\s+(xefg\w+)\s*\((.*?)\)\s*;',
                              common.strip_comments(headers_text), re.S)
    for result_type, name, params in declarations:
        if name not in hooks:
            continue
        spec = hooks[name]
        signature = ' '.join(params.split())
        arguments = [re.search(r'(\w+)\s*$', parameter)[1] for parameter in signature.split(',')]
        if 'tail_when' in spec or spec.get('always_tail'):
            code.append(tail_wrapper(result_type, name, signature, arguments, spec))
            continue
        if 'replace' in spec:
            original, replacement = spec['replace']
            if original not in arguments:
                raise ReleaseError(f'{name}: Intel header has no parameter {original}')
            arguments[arguments.index(original)] = replacement
        code.append(f'XEFG_SWAPCHAIN_API {result_type} {name}({signature}){{static LONG calls;'
                    f'__typeof__(&{name}) original=(void*)resolve("{name}");'
                    f'if(!original)return XEFG_SWAPCHAIN_RESULT_ERROR_CANT_LOAD_LIBRARY;InterlockedIncrement(&calls);'
                    f'{spec["before"]}{result_type} result=original({", ".join(arguments)});{spec["after"]}'
                    f'return result;}}\n')
    if len(code) != len(hooks):
        raise ReleaseError(f'Intel headers do not declare all {len(hooks)} wrapped XeFG entries')
    return ''.join(code)


def module_definition(intel_exports, wrapped, extra, original):
    """proxy.def: Intel's exports at their ordinals, then the extra exports at the following ordinals."""
    base = original.removesuffix('.dll')
    lines = ['LIBRARY libxess_fg', 'EXPORTS']
    for ordinal, name, _forwarder in intel_exports:
        if name in wrapped:
            lines.append(f' {name} @{ordinal}')
        elif name:
            lines.append(f' {name}={base}.{name} @{ordinal}')
        else:
            lines.append(f' bc250_ordinal_{ordinal}={base}.#{ordinal} @{ordinal} NONAME')
    last = max(ordinal for ordinal, _name, _forwarder in intel_exports)
    lines += [f' {name} @{last + 1 + i}' for i, name in enumerate(extra)]
    return '\n'.join(lines) + '\n'


def original_manifest_header(data):
    return f'#define ORIGINAL_BYTES {len(data)}ULL\n#define ORIGINAL_HASH 0x{fnv1a64(data)}ULL\n'


# -------------------------------------------------------------------------------------------------------------- checks

def check_runtime_pin(runtime_sha256, original):
    """Intel's runtime must be what installations download and place as the proxy's original."""
    pins = json.loads(DEPENDENCIES.read_text())['runtime']
    layout = pins.get('ProxyPackage', {})
    source = layout.get('payload/' + original)
    if source is None or pins['Files'].get(source) != runtime_sha256:
        raise ReleaseError(f'packaging/dependencies.json must place Intel\'s runtime {runtime_sha256[:12]}… as payload/{original} '
                           '(runtime.ProxyPackage): the proxy verifies and loads exactly that file')


def check_proxy(data, intel_exports, wrapped, extra, original, allowed_imports):
    """The built DLL's ABI: Intel's export table reproduced, wrapped entries implemented here, forwarders for the rest."""
    base = original.removesuffix('.dll')
    exports = pe_exports(data)
    last = max(ordinal for ordinal, _name, _forwarder in intel_exports)
    mine = [row for row in exports if row[0] <= last]
    if [(o, n) for o, n, _f in mine] != [(o, n) for o, n, _f in intel_exports]:
        raise ReleaseError('The proxy does not reproduce Intel\'s export names and ordinals')
    for ordinal, name, forwarder in mine:
        expected = None if name in wrapped else f'{base}.{name}' if name else f'{base}.#{ordinal}'
        if forwarder != expected:
            raise ReleaseError(f'Export {name or ordinal}: forwarder {forwarder!r}, expected {expected!r}')
    others = [row for row in exports if row[0] > last]
    if sorted(n for _o, n, _f in others) != sorted(extra) or any(f for _o, _n, f in others):
        raise ReleaseError(f'Unexpected extra exports: {others}')
    imports = pe_imports(data)
    unexpected = sorted({name.lower() for name in imports} - {name.lower() for name in allowed_imports})
    if unexpected:
        raise ReleaseError(f'The proxy imports from {unexpected}')
    found = [marker for marker in ENABLER_MARKERS if marker in data]
    if found:
        raise ReleaseError(f'The proxy refers to the enabler or its loader: {found}')
    return dict(intel=len(intel_exports), wrapped=sorted(wrapped), forwarded=len(mine) - len(wrapped), extra=sorted(extra),
                imports=imports)


# --------------------------------------------------------------------------------------------------------------- build

def definition_path(variant=DEFAULT_VARIANT):
    if variant not in VARIANTS:
        raise ReleaseError(f'Unknown proxy variant {variant!r} (known: {", ".join(VARIANTS)})')
    return VARIANTS[variant]


def definitions(variant=DEFAULT_VARIANT):
    """(intel_free.json, the variant's definition, the proxy's preprocessor definitions): the Intel-free add-on's
    definitions without the ones the variant drops, plus the variant's own "define" if it has one and its
    "added_defines" (mfg: XEFG_F4Q=1)."""
    path = definition_path(variant)
    base, definition = common.intel_free_definition(), json.loads(path.read_text())
    if definition['variant'] != variant:
        raise ReleaseError(f'{path.name} defines variant {definition["variant"]!r}, not {variant!r}')
    inherited = common.intel_free_defines(base)
    dropped = definition['addon']['dropped_defines']
    unknown = sorted(set(dropped) - set(inherited))
    if unknown:
        raise ReleaseError(f'{path.name} drops definitions the Intel-free build does not have: ' + ', '.join(unknown))
    added = [definition['addon']['define']] if definition['addon'].get('define') else []
    added += [d for d in definition['addon'].get('added_defines', {}) if d not in added]  # features of this variant only
    return base, definition, [d for d in inherited if d not in dropped] + added


def own_files(definition):
    """(lock tree group, {name: description} replaced, {name: entry} added) of a variant's own profile files (mfg:
    "replace" and "add", from the inputs.lock.json tree group "own_files")."""
    spec = definition['profile']
    replaced, added = spec.get('replace', {}), spec.get('add', {})
    if (replaced or added) and not spec.get('own_files'):
        raise ReleaseError(f'{definition["variant"]} replaces or adds profile files without naming their lock group (own_files)')
    overlap = sorted(set(replaced) & set(added))
    if overlap:
        raise ReleaseError(f'{definition["variant"]} both replaces and adds {overlap}')
    return spec.get('own_files'), replaced, added


def prepare_profile(config, base, definition, folder):
    """The Intel-free profile without the files the variant drops (2x: the multi-frame kernels), with the variant's own
    files (mfg: "replace": another form of a profile file, its waves.txt line naming the new module in place; "add": a
    file beside them, with its waves.txt line when it has a wave size) and the waves.txt lines it appends (mfg:
    "append_waves", then the added files' lines) and the dispatch-scale.txt rows it appends (mfg: "append_dispatch_scale");
    returns its files. waves.txt must stay a table the pacing layer reads in full."""
    common.prepare_intel_free_profile(config, base, folder)
    for name in definition['profile']['drop']:
        if not (folder / name).is_file():
            raise ReleaseError(f'{definition["variant"]} drops {name}, which the Intel-free profile does not have')
        (folder / name).unlink()
    group, replaced, added = own_files(definition)
    for name in replaced:
        if not (folder / name).is_file():
            raise ReleaseError(f'{definition["variant"]} replaces {name}, which the Intel-free profile does not have')
        data = config.input_file(group, name).read_bytes()
        common.replace_wave_module(folder / 'waves.txt', fnv1a64((folder / name).read_bytes()), fnv1a64(data))
        (folder / name).write_bytes(data)
    appended = definition['profile'].get('append_waves', {})
    if appended:
        common.append_waves(folder / 'waves.txt', appended)
    lines = {}
    for name, entry in added.items():
        if (folder / name).exists():
            raise ReleaseError(f'{definition["variant"]} adds {name}, which the Intel-free profile already has')
        data = config.input_file(group, name).read_bytes()
        (folder / name).write_bytes(data)
        if entry.get('wave') is not None:
            lines[fnv1a64(data)] = dict(wave=entry['wave'])
    if lines:
        common.append_waves(folder / 'waves.txt', lines)
    rows = definition['profile'].get('append_dispatch_scale', {})
    if rows:
        common.append_dispatch_scale(folder / 'dispatch-scale.txt', rows)
    common.wave_table((folder / 'waves.txt').read_text())
    files = sorted(folder.iterdir())
    multi_frame = 'XEFG_MFG_RESEARCH=1' not in definition['addon']['dropped_defines']
    kernels = sorted(p.name for p in files if p.name.startswith('mfg-finish'))
    if not multi_frame and kernels:
        raise ReleaseError('Multi-frame kernels left in the 2x profile: ' + ', '.join(kernels))
    if multi_frame and len(kernels) != 5:
        raise ReleaseError(f'The multi-frame build needs the five mfg-finish kernels; the profile has {kernels}')
    return files


def compile_command(config, xess, generated, output, defines, source):
    wine = config.wine_include
    return [config.clang, '--target=x86_64-w64-windows-gnu', '-fms-extensions', '-D__WINE_USE_MSVCRT',
            *('-D' + d for d in defines),
            '-isystem', str(wine / 'msvcrt'), '-isystem', str(wine / 'windows'),
            '-I', str(xess / 'inc/xess_fg'), '-I', str(xess / 'inc/xell'), '-I', str(generated),
            '-I', str(REPO / 'src'), '-I', str(REPO / 'src/game'), '-I', str(common.COM_THUNKS),
            '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-O2', '-Wall', '-Wextra', '-nostdlib',
            '-fuse-ld=lld', '-shared', '-Wl,--entry,DllMain', '-Wl,--no-insert-timestamp', '-L' + str(config.wine_lib),
            str(REPO / source), str(common.COM_THUNKS / 'com_thunks.S'), str(generated / 'proxy.def'),
            '-lkernel32', '-lucrtbase', '-o', str(output)]


def build(config, check_com_thunks=True, variant=DEFAULT_VARIANT):
    base, definition, defines = definitions(variant)
    spec = definition['addon']
    xess = config.check_group('intel-xess')
    runtime = config.input_file(RUNTIME_GROUP, RUNTIME_FILE)
    runtime_data = runtime.read_bytes()
    runtime_sha256 = hashlib.sha256(runtime_data).hexdigest()
    check_runtime_pin(runtime_sha256, spec['original'])
    intel_exports = pe_exports(runtime_data)
    if len(intel_exports) != 57 or any(f for _o, _n, f in intel_exports):
        raise ReleaseError('Intel\'s runtime does not have the 57 exports (none forwarded) this proxy was written for')
    hooks = proxy_hooks(definition)
    wrapped = set(hooks)
    if not wrapped <= {n for _o, n, _f in intel_exports if n}:
        raise ReleaseError('Intel\'s runtime does not export every wrapped entry')

    out = config.build / spec['output_dir']
    staged = out.with_name(out.name + '.profile-partial')
    if staged.exists():
        shutil.rmtree(staged)
    profile_files = prepare_profile(config, base, definition, staged)
    profile_check = common.check_intel_free_profile(base, profile_files)
    generated = out / 'generated'
    if out.exists():
        shutil.rmtree(out)
    generated.mkdir(parents=True)
    staged.rename(out / 'profile')
    profile_files = sorted((out / 'profile').iterdir())

    headers = '\n'.join((xess / name).read_text() for name in common.API_HEADERS)
    texts = {
        'probe_core.h': common.probe_core_header((REPO / 'src/probe.c').read_text()),
        'profile_manifest.h': common.profile_manifest_header(profile_files),
        'original_manifest.h': original_manifest_header(runtime_data),
        'mfg_proxy_exports.h': exports_header(headers, hooks),
        'proxy.def': module_definition(intel_exports, wrapped, spec['extra_exports'], spec['original']),
    }
    for name, text in texts.items():
        (generated / name).write_text(text)

    com_status = 'not checked'
    if check_com_thunks:
        header, assembly = common.com_thunks((config.wine_include / 'windows/d3d12.h').read_text())
        same = (header == (common.COM_THUNKS / 'com_thunks.h').read_text()
                and assembly == (common.COM_THUNKS / 'com_thunks.S').read_text())
        com_status = ('equal to' if same else 'DIFFERENT from') + " a regeneration from Wine's d3d12.h"
        if not same:
            print('warning: Wine\'s d3d12.h now yields different COM thunks; the committed ones are used', file=sys.stderr)

    output = out / spec['output']
    command = compile_command(config, xess, generated, output, defines, spec['source'])
    subprocess.run(command, check=True, capture_output=True)
    repeat = out / 'repeat' / spec['output']
    repeat.parent.mkdir()
    subprocess.run(compile_command(config, xess, generated, repeat, defines, spec['source']), check=True, capture_output=True)
    if sha256(output) != sha256(repeat):
        raise ReleaseError('Two builds of the proxy differ')
    shutil.rmtree(repeat.parent)
    abi = check_proxy(output.read_bytes(), intel_exports, wrapped, spec['extra_exports'], spec['original'],
                      spec['allowed_imports'])

    depends = common.dependencies([a for a in command if not a.endswith('.def')])
    system = [p for p in depends if config.in_toolchain(p)
              or not (p.is_relative_to(REPO) or p.is_relative_to(config.build) or p.is_relative_to(config.cache))]
    tracked = {p for p in depends if p.is_relative_to(REPO) and not config.in_toolchain(p)
               and not (p.is_relative_to(config.build) or p.is_relative_to(config.cache))}
    tracked |= {REPO / 'src/probe.c', common.COM_THUNKS / 'com_thunks.S', common.INTEL_FREE, definition_path(variant), DEPENDENCIES,
                Path(__file__).resolve(), Path(common.__file__).resolve(), RELEASE / 'config.py',
                RELEASE / 'check_intel_free.py'}

    digest = sha256(output)
    reference = config.lock.get('outputs', {}).get(f'{spec["output"]} ({definition["variant"]})')
    locked_profile = config.lock['work'][base['profile']['base']]['files']
    appended = definition['profile'].get('append_waves', {})
    group, replaced, added = own_files(definition)
    tree = config.lock.get('tree', {}).get(group, {}).get('files', {}) if group else {}
    # each rewritten file with the locked sha256 of the base file it was derived from (assemble.py checks that base)
    rewritten = sorted(set(base['profile']['rewrite']) | ({'waves.txt'} if appended or replaced or added else set()))
    record = dict(
        output=spec['output'], sha256=digest, reference_sha256=reference,
        matches_reference=digest == reference if reference else None, variant=definition['variant'],
        configuration=definition['configuration'],
        defines=defines, dropped_defines=sorted(base['addon']['dropped_defines']) + sorted(spec['dropped_defines']),
        command=[common.record_argument(a, config) for a in command],
        sources={str(p.relative_to(REPO)): sha256(p) for p in sorted(tracked)},
        generated={name: hashlib.sha256(text.encode()).hexdigest() for name, text in texts.items()},
        fetched={group: config.lock['fetch'][group]['commit'] for group in ('intel-xess', RUNTIME_GROUP)},
        original=dict(file=spec['original'], group=RUNTIME_GROUP, source=RUNTIME_FILE, sha256=runtime_sha256,
                      bytes=len(runtime_data), fnv1a64=fnv1a64(runtime_data)),
        exports=abi,
        profile=dict(name=definition['profile']['name'], files=len(profile_files), directory='profile',
                     sha256=hashlib.sha256(''.join(f'{p.name}\t{sha256(p)}\n' for p in profile_files).encode()).hexdigest(),
                     file_sha256={p.name: sha256(p) for p in profile_files},
                     rewritten={name: locked_profile[name]['sha256'] for name in rewritten},
                     dropped=sorted(definition['profile']['drop']),
                     own_group=group,
                     # each of the variant's own files with its locked sha256 (assemble.py checks that pin)
                     replaced={name: tree[name]['sha256'] for name in sorted(replaced)},
                     added={name: tree[name]['sha256'] for name in sorted(added)},
                     appended_waves={module: entry['wave'] for module, entry in appended.items()},
                     wave_choices=len(common.wave_table((out / 'profile' / 'waves.txt').read_text())), **profile_check),
        com_thunks=com_status,
        system_headers=common.system_digest(system, config),
        import_libraries={name: sha256(config.wine_lib / name) for name in ('libkernel32.a', 'libucrtbase.a')},
        toolchain=common.toolchain_record(config),
        api_hooks=sorted(wrapped),
    )
    (out / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
    common.require_pinned_toolchain(config, record, f'addon ({definition["variant"]})')
    return output, record


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    parser.add_argument('--no-com-thunk-check', action='store_true', help="skip regenerating the COM thunks from Wine's d3d12.h")
    parser.add_argument('--no-reference-check', action='store_true', help='exit 0 even when the output differs from the lock')
    parser.add_argument('--variant', choices=sorted(VARIANTS), default=DEFAULT_VARIANT,
                        help=f'the proxy build (default {DEFAULT_VARIANT})')
    args = parser.parse_args()
    config = Config.from_args(args)
    output, record = build(config, check_com_thunks=not args.no_com_thunk_check, variant=args.variant)
    locked = config.lock.get('toolchain', {})
    toolchain = dict(locked.get('addon', {}))
    toolchain['system_headers'] = locked.get(f'addon ({record["variant"]})', {}).get('system_headers')
    for key in ('system_headers', 'import_libraries'):
        if toolchain.get(key) and toolchain[key] != record[key]:
            print(f'warning: {key} differ from the locked toolchain; byte identity is not expected', file=sys.stderr)
    print(json.dumps(dict(output=relative(output, config), sha256=record['sha256'], reference=record['reference_sha256'],
                          matches_reference=record['matches_reference'], variant=record['variant'],
                          profile_files=record['profile']['files'], exports=record['exports'],
                          com_thunks=record['com_thunks']), indent=2))
    if record['matches_reference'] is None:
        print('note: inputs.lock.json has no reference for this variant; the output is a new build to qualify',
              file=sys.stderr)
    elif not record['matches_reference'] and not args.no_reference_check:
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        sys.exit(f'error: {error}')
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode(errors='replace') if isinstance(error.stderr, bytes) else (error.stderr or '')
        sys.exit(f'error: command failed ({error.returncode}): {" ".join(map(str, error.cmd))[:300]}\n{detail[-3000:]}')
