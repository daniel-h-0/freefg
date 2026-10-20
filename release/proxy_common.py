#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""What the builds of this project's add-on share (release/build_proxy.py imports it): the preprocessor definitions
of the add-on configuration the Intel-free builds start from, the profile markers that configuration expects, the five
XeFG swap-chain entries the add-on wraps (Intel's API headers give their signatures), the slice of src/probe.c the
add-on compiles (probe_core.h) and the profile manifest header, the committed COM forwarding thunks and their
regeneration from Wine's d3d12.h, the Intel-free profile (release/intel_free.json) and its checks, and the helpers that
write location-independent build records.

Not runnable on its own.
"""
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import REPO, RELEASE, ReleaseError, fnv1a64, relative, sha256  # noqa: E402

# The committed COM forwarding thunks (com_thunks.h/.S), generated from Wine 11.16's d3d12.h.
COM_THUNKS = RELEASE / 'generated'

# q36's preprocessor definitions, in q36's order. The three *_RESEARCH macros keep their historical names but gate
# production code paths of the shipped add-on; renaming them changes the source, not this list.
DEFINES = [
    'XEFG_MFG_POOL=1', 'XEFG_MFG_RETIRE=1', 'XEFG_WINO_ENC16=1', 'XEFG_MODEL_OWN_225792=1',
    'XEFG_MFG_DOWN_FILTERS=1', 'XEFG_MFG_UP_FILTERS=1', 'XEFG_MFG_SETTINGS=1',
    'XEFG_MFG_GUARD_FULL=1', 'XEFG_MFG_LEAN_FULL_TRACKING=1', 'XEFG_MFG_GUARD_OPTI=1',
    'XEFG_MFG_GUARD_FULL_NATIVE2=1', 'XEFG_MFG_GUARD_FULL_PIXEL2=1', 'XEFG_MFG_DISPATCH_GUARD=1',
    'XEFG_MFG_XELL_PACE=1', 'XEFG_MFG_NO_ENABLER_UI=1', 'XEFG_GAME_CORE=1', 'XEFG_SCOPED_OBSERVER=1',
    'XEFG_MFG_RESEARCH=1', 'XEFG_FRAME_CAP_RESEARCH=1', 'XEFG_FLOW_CAP_RESEARCH=1',
]

# Profile marker files must agree with the build: present markers enable a code path the add-on is built with,
# absent ones belong to modes it is built without (q36's build_mfg_addon.py checks, for this configuration).
PRESENT_MARKERS = ['wino-enc16.required', 'mfg-dispatch-guard.required', 'mfg-dispatch-guard-opti.required',
                   'mfg-dispatch-guard-full.required', 'mfg-dispatch-guard-full-native2.required',
                   'mfg-dispatch-guard-full-pixel2.required', 'mfg-frame-settings.required',
                   'mfg-upscale-filters.required', 'mfg-downscale-filters.required']
ABSENT_MARKERS = ['warp-literal-diagnostic.required', 'mfg-dispatch-guard-native2.required',
                  'mfg-warp-group-x.required', 'mfg-warp-group-y.required', 'mfg-warp-factor3.required',
                  'mfg-warp-factor3.dxil']


# The XeFG swap-chain entries the add-on wraps, with the code around each original call. In the signature, the
# argument named in "replace" is passed as the given expression instead.
API_HOOKS = {
    'xefgSwapChainD3D12CreateContext': dict(
        before='AcquireSRWLockExclusive(&fast_lifecycle_lock);ID3D12Device*scoped=pDevice&&fast_candidate(pDevice,'
               '__builtin_return_address(0))?scoped_begin(pDevice):NULL;ReleaseSRWLockExclusive(&fast_lifecycle_lock);',
        replace=('pDevice', 'scoped?scoped:pDevice'),
        after='if(scoped){if(result==0&&phSwapChain)scoped_remember(*phSwapChain,scoped);else{scoped_remember((void*)scoped,'
              'scoped);scoped_destroy((void*)scoped);}}'
              'mfg_xell_pace_attach();'),
    'xefgSwapChainD3D12InitFromSwapChain': dict(
        before='fast_begin_init(hSwapChain);ID3D12CommandQueue*scoped=scoped_application_queue(hSwapChain,pCmdQueue);',
        replace=('pCmdQueue', 'scoped?scoped:pCmdQueue'),
        after='if(scoped)scoped_release((void*)scoped);if(result==0){fast_ready(hSwapChain);mfg_tag_capture(hSwapChain);}'
              'if(result==0)mfg_xell_pace_swapchain(hSwapChain);'
              'if(result==0&&fast_scope&&fast_context_scope(hSwapChain)==fast_scope)mfg_settings_note_context(hSwapChain);'),
    'xefgSwapChainD3D12InitFromSwapChainDesc': dict(
        before='fast_begin_init(hSwapChain);ID3D12CommandQueue*scoped=scoped_application_queue(hSwapChain,pCmdQueue);',
        replace=('pCmdQueue', 'scoped?scoped:pCmdQueue'),
        after='if(scoped)scoped_release((void*)scoped);if(result==0){fast_ready(hSwapChain);mfg_tag_capture(hSwapChain);}'
              'if(result==0)mfg_xell_pace_swapchain(hSwapChain);'
              'if(result==0&&fast_scope&&fast_context_scope(hSwapChain)==fast_scope)mfg_settings_note_context(hSwapChain);'),
    'xefgSwapChainDestroy': dict(
        # mfg_status_forget runs before the SDK frees the swap chain (mfg_xell_pace.h).
        before='mfg_status_forget(hSwapChain);int settings_owned=fast_scope&&fast_context_scope(hSwapChain)==fast_scope;'
               'fast_report(hSwapChain);',
        after='if(result==0){AcquireSRWLockExclusive(&fast_lifecycle_lock);fast_finish(hSwapChain);scoped_destroy(hSwapChain);'
              'ReleaseSRWLockExclusive(&fast_lifecycle_lock);}'
              'if(result==0&&settings_owned)mfg_settings_clear_context();'),
    'xefgSwapChainGetLastPresentStatus': dict(
        before='',
        after='if(result==0&&pPresentStatus&&(calls<=4||calls%300==0)){char line[160];snprintf(line,sizeof(line),'
              '"MFG_PRESENT enabled=%u status=%d presents=%u\\n",pPresentStatus->isFrameGenEnabled,'
              'pPresentStatus->frameGenResult,pPresentStatus->framesPresented);proxy_log(line);}'),
}
API_HEADERS = ['inc/xess_fg/xefg_swapchain.h', 'inc/xess_fg/xefg_swapchain_d3d12.h']

# The multi-frame proxy's wrapped entries (variant intel-free-mfg, release/intel_free_mfg.json "hooks": "MFG_PROXY_HOOKS";
# C side: src/game/mfg_proxy_coexist.h). "before", "replace" and "after" are the ordinary path, as API_HOOKS (without the
# enabler's frame-start pacer and status map). With "tail_when" true (another module hooks Intel's runtime) the entry
# runs "tail_before" and then tail-calls Intel's (musttail, so Intel's entry sees this entry's caller), passing the
# argument named in "tail_replace" as the given expression; work after the call moves to later calls (the first call
# that carries the handle afterwards runs it before reaching Intel: proxy_ready_first). "always_tail" entries do "before"
# and always tail-call. GetLastPresentStatus and SetNumInterpolatedFrames take the handle first and stay ordinary calls
# on both paths. The ordinary initialisation keeps the 2x build's one-frame gate (mfg_proxy_one_frame), so without
# another module the build accelerates what the 2x build accelerates.
MFG_PROXY_HOOKS = {
    'xefgSwapChainD3D12CreateContext': dict(
        before='proxy_finish_deferred(NULL);'
               'AcquireSRWLockExclusive(&fast_lifecycle_lock);ID3D12Device*scoped=pDevice&&fast_candidate(pDevice,'
               '__builtin_return_address(0))?scoped_begin(pDevice):NULL;ReleaseSRWLockExclusive(&fast_lifecycle_lock);',
        replace=('pDevice', 'scoped?scoped:pDevice'),
        after='if(scoped){if(result==0&&phSwapChain)scoped_remember(*phSwapChain,scoped);else{scoped_remember((void*)scoped,'
              'scoped);scoped_destroy((void*)scoped);}}',
        tail_when='proxy_foreign_hooks()',
        tail_before='ID3D12Device*tail=proxy_create_foreign(pDevice,phSwapChain,__builtin_return_address(0));',
        tail_replace=('pDevice', 'tail?tail:pDevice')),
    'xefgSwapChainD3D12InitFromSwapChain': dict(
        before='proxy_finish_deferred(hSwapChain);proxy_handle_alive(hSwapChain);proxy_claim(hSwapChain,pCmdQueue);'
               'if(mfg_proxy_one_frame(hSwapChain,pInitParams))fast_begin_init(hSwapChain);'
               'ID3D12CommandQueue*scoped=scoped_application_queue(hSwapChain,pCmdQueue);',
        replace=('pCmdQueue', 'scoped?scoped:pCmdQueue'),
        after='if(scoped)scoped_release((void*)scoped);if(result==0){proxy_frames_init(hSwapChain,pInitParams);'
              'fast_ready(hSwapChain);mfg_tag_capture(hSwapChain);}'
              'if(result==0&&fast_scope&&fast_context_scope(hSwapChain)==fast_scope)mfg_settings_note_context(hSwapChain);',
        tail_when='proxy_foreign_hooks()',
        tail_before='proxy_frames_init(hSwapChain,pInitParams);ID3D12CommandQueue*tail=proxy_init_foreign(hSwapChain,pCmdQueue);',
        tail_replace=('pCmdQueue', 'tail?tail:pCmdQueue')),
    'xefgSwapChainD3D12InitFromSwapChainDesc': dict(
        before='proxy_finish_deferred(hSwapChain);proxy_handle_alive(hSwapChain);proxy_claim(hSwapChain,pCmdQueue);'
               'if(mfg_proxy_one_frame(hSwapChain,pInitParams))fast_begin_init(hSwapChain);'
               'ID3D12CommandQueue*scoped=scoped_application_queue(hSwapChain,pCmdQueue);',
        replace=('pCmdQueue', 'scoped?scoped:pCmdQueue'),
        after='if(scoped)scoped_release((void*)scoped);if(result==0){proxy_frames_init(hSwapChain,pInitParams);'
              'fast_ready(hSwapChain);mfg_tag_capture(hSwapChain);}'
              'if(result==0&&fast_scope&&fast_context_scope(hSwapChain)==fast_scope)mfg_settings_note_context(hSwapChain);',
        tail_when='proxy_foreign_hooks()',
        tail_before='proxy_frames_init(hSwapChain,pInitParams);ID3D12CommandQueue*tail=proxy_init_foreign(hSwapChain,pCmdQueue);',
        tail_replace=('pCmdQueue', 'tail?tail:pCmdQueue')),
    'xefgSwapChainDestroy': dict(
        before='proxy_claim(hSwapChain,NULL);proxy_ready_drop(hSwapChain);proxy_frames_forget(hSwapChain);'
               'int settings_owned=fast_scope&&fast_context_scope(hSwapChain)==fast_scope;fast_report(hSwapChain);',
        after='if(result==0){AcquireSRWLockExclusive(&fast_lifecycle_lock);fast_finish(hSwapChain);scoped_destroy(hSwapChain);'
              'ReleaseSRWLockExclusive(&fast_lifecycle_lock);}'
              'if(result==0&&settings_owned)mfg_settings_clear_context();',
        tail_when='proxy_foreign_hooks()',
        tail_before='proxy_frames_forget(hSwapChain);proxy_destroy_foreign(hSwapChain);'),
    'xefgSwapChainGetLastPresentStatus': dict(
        before='proxy_ready_first(hSwapChain);',
        after='if(result==0&&pPresentStatus){proxy_status_from_caller(pPresentStatus);if(calls<=4||calls%300==0){'
              'char line[160];snprintf(line,sizeof(line),"MFG_PRESENT enabled=%u status=%d presents=%u\\n",'
              'pPresentStatus->isFrameGenEnabled,pPresentStatus->frameGenResult,pPresentStatus->framesPresented);'
              'proxy_log(line);}}'),
    'xefgSwapChainSetNumInterpolatedFrames': dict(
        before='proxy_ready_first(hSwapChain);',
        after='if(result==0)proxy_frames_changed(hSwapChain,numInterpolatedFrames);'),
    # Callers ask for the swap chain right after a successful initialisation, before any frame-count change: with the
    # initialisation tail-called, its deferred work (model census, network) runs here.
    'xefgSwapChainD3D12GetSwapChainPtr': dict(
        before='proxy_ready_first(hSwapChain);', always_tail=True),
    'xefgSwapChainTagFrameConstants': dict(
        before='proxy_frame_tick(hSwapChain);', always_tail=True),
}
HOOK_TABLES = {'MFG_PROXY_HOOKS': MFG_PROXY_HOOKS}

# The add-on's copy of the probe core: src/probe.c up to this include, with these replacements (each must match once).
PROBE_SPLIT = '#include "scene_motion.h"'
PROBE_PATCHES = [
    ('int _fltused;', ''),
    ('static void mfg_capture_dispatch(ID3D12GraphicsCommandList*,uint64_t);',
     'static void mfg_capture_dispatch(ID3D12GraphicsCommandList*l,uint64_t h){(void)l;(void)h;}'),
    ('static void mfg_note_queue(ID3D12CommandQueue*);', 'static void mfg_note_queue(ID3D12CommandQueue*q){(void)q;}'),
    # Fixed modes: model owner 7, Winograd 3, and the frame cap from the player's settings.
    ('static UINT env_uint(const char*k,UINT v){',
     'static UINT env_uint(const char*k,UINT v){if(!strcmp(k,"XEFG_MODEL_OWNER"))return 7;if(!strcmp(k,"XEFG_WINOGRAD"))'
     'return 3;if(!strcmp(k,"XEFG_FLOW_CAP"))return mfg_settings_cap_requested();'),
    # The replay lab's constant override and UAV tap are probe-only research.
    ('static void tap_dispatch(ID3D12GraphicsCommandList*,uint64_t);static void const_override(ID3D12GraphicsCommandList*,'
     'uint64_t);', ''),
    ('const_override(l,records[i].shader);', ''),
    ('tap_dispatch(l,records[i].shader);', ''),
]


# ---------------------------------------------------------------------------------------------------------- generation

def strip_comments(text):
    return re.sub(r'/\*.*?\*/', '', text, flags=re.S)


def probe_core_header(probe_source):
    if probe_source.count(PROBE_SPLIT) != 1:
        raise ReleaseError(f'src/probe.c must contain {PROBE_SPLIT} exactly once')
    core = probe_source.split(PROBE_SPLIT)[0]
    for old, new in PROBE_PATCHES:
        if core.count(old) != 1:
            raise ReleaseError('src/probe.c changed: patch target not found exactly once: ' + old[:70])
        core = core.replace(old, new)
    return core


def profile_manifest_header(files):
    rows = ''.join(f'{{"{path.name}",{path.stat().st_size},0x{fnv1a64(path.read_bytes())}ULL}},\n' for path in files)
    return 'static const struct{const char*name;UINT64 size;uint64_t hash;}fast_files[]={\n' + rows + '};\n'


def com_thunks(d3d12_header):
    """com_thunks.h and com_thunks.S from Wine's d3d12.h (what scripts/generate_com_thunks.py writes)."""
    interfaces = {'device': 'ID3D12Device10', 'list': 'ID3D12GraphicsCommandList7', 'queue': 'ID3D12CommandQueue'}
    methods = {}
    for kind, name in interfaces.items():
        body = re.search(r'typedef struct ' + name + r'Vtbl \{(.*?)\} ' + name + r'Vtbl;', d3d12_header, re.S)
        if not body:
            raise ReleaseError(f'{name}Vtbl not found in d3d12.h')
        slots = re.findall(r'\(STDMETHODCALLTYPE \*(\w+)\)\(\s*' + name + r' \*This', body[1])
        if len(slots) < 3 or slots[:3] != ['QueryInterface', 'AddRef', 'Release']:
            raise ReleaseError('Unexpected COM header layout in d3d12.h')
        methods[kind] = slots
    count = max(map(len, methods.values()))
    header, assembly = [], ['.text']
    for i in range(count):
        header.append(f'extern void bc250_com_forward_{i}(void);')
        assembly += [f'.globl bc250_com_forward_{i}', f'.def bc250_com_forward_{i}; .scl 2; .type 32; .endef', '.p2align 4',
                     f'bc250_com_forward_{i}:', 'movq 8(%rcx), %rcx', 'movq (%rcx), %rax', f'jmp *{i * 8}(%rax)']
    forwarders = ','.join(f'(void*)bc250_com_forward_{i}' for i in range(count))
    header.append('static void *const scoped_forwarders[]={' + forwarders + '};')
    for kind, slots in methods.items():
        header.append('enum {' + ','.join(f'SCOPED_{kind}_{name}={i}' for i, name in enumerate(slots))
                      + f',SCOPED_{kind}_COUNT={len(slots)}' + '};')
    return '\n'.join(header) + '\n', '\n'.join(assembly) + '\n'


# -------------------------------------------------------------------------------------------------- Intel-free variant

INTEL_FREE = RELEASE / 'intel_free.json'
# Profile files of the features the Intel-free variant compiles out: scaled warps, flow preprocessing, enlargement
# filters, literal-weight warps and dispatch guards.
INTEL_FREE_ABSENT_PREFIXES = ('frame-warp-', 'area-', 'flow-preprocess', 'frame-upsample', 'mfg-warp-',
                              'mfg-dispatch-guard')
INTEL_FREE_PRESENT_MARKERS = ['wino-enc16.required', 'winograd.required', 'wino-ref64.required']
INTEL_FREE_ABSENT_MARKERS = ([m for m in PRESENT_MARKERS if m not in INTEL_FREE_PRESENT_MARKERS] + ABSENT_MARKERS
                             + ['general-cap.required'])


def intel_free_definition():
    return json.loads(INTEL_FREE.read_text())


def intel_free_defines(definition):
    """q36's definitions without the dropped ones, plus XEFG_INTEL_FREE=1 (sources check the combination)."""
    dropped = definition['addon']['dropped_defines']
    unknown = sorted(set(dropped) - set(DEFINES))
    if unknown:
        raise ReleaseError('intel_free.json drops definitions the default build does not have: ' + ', '.join(unknown))
    return [d for d in DEFINES if d not in dropped] + [definition['addon']['define']]


def prepare_intel_free_profile(config, definition, folder):
    """Copy the kept own files of the locked profile into folder and write the rewritten ones; returns them by name.
    intel_free.json must place every own file of the locked profile in exactly one of keep, rewrite and left_out_own."""
    spec = definition['profile']
    locked = config.lock['work'][spec['base']]['files']
    lists = [set(spec['keep']), set(spec['rewrite']), set(spec['left_out_own'])]
    own = {name for name, entry in locked.items() if entry['origin'] == 'own'}
    classified = set().union(*lists)
    if sum(map(len, lists)) != len(classified) or classified != own:
        raise ReleaseError('intel_free.json must classify each own profile file once: unclassified '
                           f'{sorted(own - classified)}, not own {sorted(classified - own)}')
    folder.mkdir(parents=True)
    for name in spec['keep']:
        shutil.copyfile(config.input_file(spec['base'], name), folder / name)
    for name, rule in spec['rewrite'].items():
        kept, dropped = [], []
        for line in config.input_file(spec['base'], name).read_text().splitlines(keepends=True):
            fields = line.split()
            if fields and fields[0] in rule['drop_shaders']:
                dropped.append(fields[0])
            else:
                kept.append(line)
        if sorted(dropped) != sorted(rule['drop_shaders']):
            raise ReleaseError(f'{name}: expected one line for each of {sorted(rule["drop_shaders"])}, found {dropped}')
        (folder / name).write_text(''.join(kept))
    return sorted(folder.iterdir())


def check_intel_free_profile(definition, files):
    """The variant profile: no file of a compiled-out feature, the markers of its own features only, own shader models,
    and every dispatch-scale.txt shader paired with its replacement (a scaled dispatch of Intel's original shader would
    cover only part of its output)."""
    from check_intel_free import shader_model  # the same DXIL container parser as the static check
    names = {p.name for p in files}
    problems = sorted(n for n in names if n.startswith(INTEL_FREE_ABSENT_PREFIXES))
    problems += [f'missing {m}' for m in INTEL_FREE_PRESENT_MARKERS if m not in names]
    problems += [f'unexpected {m}' for m in INTEL_FREE_ABSENT_MARKERS if m in names]
    allowed = set(definition['profile']['allowed_shader_models'])
    models = {p.name: shader_model(p.read_bytes()) for p in files if p.suffix == '.dxil'}
    problems += [f'{n} has shader model {m}' for n, m in sorted(models.items()) if m not in allowed]
    folder = files[0].parent
    for line in (folder / 'dispatch-scale.txt').read_text().splitlines():
        if line.split() and f'{line.split()[0]}.dxil' not in names:
            problems.append(f'dispatch-scale.txt scales {line.split()[0]}, which has no replacement in this profile')
    if problems:
        raise ReleaseError('Intel-free profile: ' + '; '.join(problems))
    return dict(shader_models={m: sorted(n for n, v in models.items() if v == m) for m in sorted(set(models.values()))})


# ------------------------------------------------------------------------------------------------------- build records

def dependencies(command):
    """Every file the C sources of a compile command include, from clang -M (one run per source)."""
    flags, sources = [], []
    skip = {'-nostdlib', '-fuse-ld=lld', '-shared', '-lkernel32', '-lucrtbase'}
    i = 0
    while i < len(command):
        arg = command[i]
        if arg == '-o':
            i += 2
            continue
        if arg.endswith('.c'):
            sources.append(arg)
        elif not (arg in skip or arg.startswith('-Wl,') or arg.startswith('-L') or arg.endswith('.S')):
            flags.append(arg)
        i += 1
    found = set()
    for source in sources:
        out = subprocess.run(flags + ['-M', source], capture_output=True, text=True, check=True).stdout
        text = out.replace('\\\n', ' ').split(':', 1)[1]
        found.update(p.replace('\\ ', ' ') for p in re.split(r'(?<!\\)\s+', text) if p)
    return sorted(Path(p).resolve() for p in found)


def record_argument(argument, config):
    """A command-line argument for build records: paths become location-independent names."""
    if argument.startswith('/'):
        return relative(argument, config)
    if argument.startswith('-L/'):
        return '-L' + relative(argument[2:], config)
    return argument


def system_digest(paths, config):
    """sha256 over the sorted (location-independent name, sha256) list of headers outside this build's own inputs."""
    rows = sorted(f'{relative(p, config)}\t{sha256(p)}\n' for p in paths)
    return dict(count=len(rows), sha256=hashlib.sha256(''.join(rows).encode()).hexdigest())
