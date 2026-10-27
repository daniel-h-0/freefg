#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Copy the lean source tree listed in release/keep.txt (or, with --public, release/keep-public.txt) into a fresh directory.

keep.txt lists everything the release build needs: the add-on and layer sources with their unit tests, the installer
and its tests, the package's documents and static files, and the release tooling. Inputs that are not tracked come from
inputs.lock.json (fetched or read from XEMFG_WORK) at build time.

--public exports the public tree instead: keep-public.txt, a subset of keep.txt with only what the enabler-free build
(package.json variant intel-free-mfg: the libxess_fg.dll proxy over Intel's unmodified runtime), the present-pacing layer,
the installer and their tests need. It has no XeSSMFG enabler integration (src/game/mfg_addon.c, the enabler hook table,
the frame-start pacer, scaling and dispatch-guard code; the 2x-only build of 0.9.0, intel-free-2x, whose sources resolve
differently), no standalone measurement program, and no
research script besides the recipe builder the installer tests run. keep.txt is not exported, so in a public tree
read_keep() (and assemble.py through it) reads keep-public.txt, and this script exports the public list by default.

The public tree gets public versions of four kinds of file (written in place of a copy; exporting a public tree again
leaves them as they are):
  C sources (src/**/*.c, *.h)   in the one configuration the public builds compile (release/unifdef.py): conditionals on
                                the proxy's definitions (release/build_proxy.py) are resolved as defined, those on every
                                other project macro (XEFG_*, PACE_*, BC250_* that no public source #defines) as
                                undefined, so research, diagnostic and enabler code behind them is not published. The
                                probe-core text that release/proxy_common.py patches by its exact wording is kept whole.
                                A header the public copies still include but keep-public.txt does not list must resolve
                                to comments only (research code as a whole): it is left out together with its #include
                                lines.
  release/inputs.lock.json      without the XeSSMFG enabler's pins and the profile's Intel-derived files, with a public
                                description of the profile group, and the OptiScaler fork group with a public
                                description and without the maintainers' notes (PUBLIC_FORK: research record paths,
                                the note on the work checkout, the earlier build); its pins, tag, build route and
                                prepared release fetch group stay.
  release/intel_material.json   the check's reference data as digests by category and the weight tables' checksums,
                                without names, run folders or provenance (check_intel_free.public_material).
  release/package.json          the intel-free-mfg package only (public_package): package.json's variant with its
                                components swapped in, so release/assemble.py with no --variant builds that package
                                (no XeSSMFG enabler, default add-on or Intel-derived profile to miss). The documents
                                component is named "documents"; this project's licence text is packaging/public/LICENSE
                                (PUBLIC_SOURCES); the source companion lists only exported files. "variants" keeps an
                                intel-free-mfg entry that changes nothing, so --variant intel-free-mfg (CI, smoke_install.py,
                                check_public_docs.py) declares the same package.
The rebuilt proxy and layer are byte-identical to the private builds (the export's purpose; acceptance rebuilds them).

The public tree also gets the files GitHub shows for a repository (PUBLIC_ROOT, generated, never listed in
keep-public.txt): README.md, LICENSE and NOTICE.md at the top, SECURITY.md and CONTRIBUTING.md in .github/, copied from
packaging/public/ (which the package ships) with their relative links adjusted to where the copy sits. Every link of a
copy must reach an exported file.

When release/names.json "chosen" holds the decided public name and slug (release/rename.py chosen_name()), the public
export renames its copies (public_rename): release/rename.py's user-visible rewrites (its default families, the
documents' [PRODUCT], Setup's titles, the User-Agents, the MIT holder and the public package name, plus the families
"chosen" adds) are applied to every exported text file except names.json "exclude", after the public versions and the
top files above are made and before anything is checked or written. The public package.json's name then follows
names.json package-name public_template (today {slug}-1.0.0), which release/assemble.py accepts. This tree keeps the
internal names, and compatibility identifiers (folders, records, switches, file names compiled into the binaries) are
not rewritten. With "chosen" empty (until the name is decided) nothing is renamed and the export is the same as
without this step. --names FILE reads "chosen" from another copy of names.json (a trial; the export still copies this
tree's names.json).

Before copying, the list is checked against what the release build reads: every "repo:" source in package.json (with
--public: of the intel-free-mfg package), every installer test, and every source file recorded by a build under the build
directory (all four builds; with --public the libxess_fg.dll and libxefg_wave.so builds) must be listed; no entry may
lie in the build directory or the download cache. A build record whose sources no longer match this tree is stale: its
sources still count (as far as they are still files of this tree), it is named under "stale_build_records", and
--strict refuses it (rebuild before a public export). After copying, every exported release/*.py tool must import in
the export, which catches a module the list lacks, and the installer tests run in the exported directory, which catches
files they read that the list lacks (--no-tests skips both). A public export is then checked as exported: its
package.json declares only sources it has (exported files, inputs its lock pins, the proxy and layer builds), --variant
intel-free-mfg declares the same package, and the copies at the top reach their links. Then, from the exported directory:

  python3 release/export_tree.py /path/to/new-dir
  cd /path/to/new-dir && python3 release/build_addon.py && python3 release/build_layer.py

  python3 release/export_tree.py --public /path/to/public-dir
  cd /path/to/public-dir && python3 release/build_proxy.py && python3 release/build_layer.py
  python3 release/assemble.py --no-source-companion        # the intel-free-mfg package (--variant intel-free-mfg: same)

The source companion's extra files (package.json source_companion "files", research build drivers that hold host
paths) are not exported; assemble.py in an exported tree therefore needs --no-source-companion (a public tree's
package.json lists none of them, but the companion also needs the OptiScaler fork's checkout).

Exported text files that name a host path (release/host_paths.py, review mode: a home directory, a removable-media
mount, a named folder in a home directory, Wine's or Windows' view of a user folder, or this host's administration
repository by name) are listed under "host_paths" in the output and on stderr; binary files are not scanned. The export
still proceeds (the list is for review before an export is published); --strict refuses it instead, before anything is
copied.
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
from config import REPO, RELEASE, Config, ReleaseError, add_arguments, sha256  # noqa: E402
import host_paths  # noqa: E402
import unifdef  # noqa: E402

KEEP = RELEASE / 'keep.txt'
KEEP_PUBLIC = RELEASE / 'keep-public.txt'
# The package variant the public tree builds, and the build records (<build>/<kind>/build.json) each list must cover.
PUBLIC_VARIANT = 'intel-free-mfg'
BUILD_KINDS = ('addon', 'layer', 'addon-intel-free', 'addon-intel-free-2x', 'addon-intel-free-mfg')
PUBLIC_BUILD_KINDS = ('layer', 'addon-intel-free-mfg')
# Public versions of private files (see the module documentation).
C_SUFFIXES = ('.c', '.h')
PROJECT_MACROS = ('XEFG_', 'PACE_', 'BC250_')
PROBE_CORE = 'src/probe.c'
LOCK = 'release/inputs.lock.json'
MATERIAL = 'release/intel_material.json'
PROFILE_GROUP = 'profile-cl-wino-q33'
PRIVATE_WORK_GROUPS = ('xessmfg-enabler',)
FORK_GROUP = 'optiscaler-fork'
# The OptiScaler fork group in the public lock: this description, and its source record without these maintainers'
# notes (evidence files that are not exported, the work checkout, the build the private testers shipped before).
PUBLIC_FORK = {
    'description': 'OptiScaler fork build (GPL-3.0), shipped as opti/OptiScaler.dll: OptiScaler master of 19 October '
                   '2026 (c2e44a8b) with three commits. Its source is the commit below with the submodules that commit '
                   'pins; the tag commit adds only FORK.md, which documents the build, and tools/bc250-build.py, which '
                   'ran it. Until the fork\'s '
                   'release is public, release/assemble.py reads the DLL from XEMFG_OPTISCALER and the source companion '
                   'reads the fork\'s git checkout from XEMFG_OPTISCALER_SOURCE; release_fetch is the fetch group '
                   'prepared for that release.',
    'dropped_source_keys': ('research_record', 'source_in_work_note', 'previous_build'),
    # neutral folder names under XEMFG_WORK in place of the maintainers' work folders
    'path': 'OptiScaler-build',
    'source_in_work': 'OptiScaler',
}
PUBLIC_PROFILE = {
    'description': 'Shader profile cl-wino-q33, as far as this tree pins it: its files of this project\'s own origin '
                   '(origin "own"), the compute shaders compiled from src/kernels/ and the profile\'s tables and markers. '
                   'The add-on embeds the size and FNV-1a hash of each profile file it loads (profile_manifest.h).',
    'in_tree': 'release/profile: the 42 files the Intel-free builds read (release/intel_free.json keep + rewrite), '
               'byte-identical, with their HLSL recipes in release/profile/origin.json; release/build_profile.py '
               'compiles each shader again and compares. XEMFG_PROFILE=release/profile serves the build without a work '
               'directory.',
}
PACKAGE = 'release/package.json'
# The public package.json (public_package): package.json's intel-free-mfg package with these renames and source swaps.
# "documents": assemble.py's apply_variant() names a variant's documents component after what the variant puts in place
# of "documents"; the public package replaces nothing, so --variant intel-free-mfg keeps that name. The licence text of
# this project's code is the public one (standard MIT text, holder placeholder) that the repository root also shows.
PUBLIC_COMPONENT_NAMES = {'documents-public': 'documents'}
PUBLIC_DOCUMENTS = 'documents'
PUBLIC_SOURCES = {'repo:LICENSE.new-code': 'repo:packaging/public/LICENSE'}
PUBLIC_ABOUT = (
    'Declarative contents of the package that release/assemble.py builds in this tree: the enabler-free build '
    '(variant intel-free-mfg; how it works: packaging/public/ARCHITECTURE.md). Each component maps package paths to '
    'sources: "repo:<path>" (a file of this tree), "input:<lock group>/<file>" (a file pinned in inputs.lock.json) and '
    '"build:<kind>", "build:<kind>-record", "build:<kind>-profile/<file>" (outputs of release/build_proxy.py and '
    'release/build_layer.py, and their build.json). Its add-on is payload/libxess_fg.dll, a proxy for Intel\'s '
    'unmodified XeFG runtime, which the installer downloads by its pinned hash (dependencies.json runtime.ProxyPackage); '
    'release/check_intel_free.py must report "pass" with no allowed component. Written by release/export_tree.py --public '
    'from the maintainers\' package declaration; "variants" keeps the name intel-free-mfg for tools that pass '
    '--variant intel-free-mfg, and that entry changes nothing.')
# The public package.json's manifest text: assemble.py writes the public build's own text (PUBLIC_MANIFEST, with the
# product's name and version) into every manifest assembled in a public tree, so package.json's maintainers' wording
# (status, profile.research) is replaced by these neutral lines.
PUBLIC_PACKAGE_STATUS = ('The public build. release/assemble.py writes its status text (PUBLIC_MANIFEST, with the '
                         'product\'s name and version) into the manifest in place of this line.')
PUBLIC_VARIANT_ABOUT = ('The package above, under the name the maintainers\' tree gives it: release/assemble.py '
                        '--variant intel-free-mfg builds exactly what release/assemble.py builds.')
PUBLIC_COMPANION = ('<name>-source.zip beside the package (release/source_companion.py): under <name>-source/source/ '
                    'every keep-public.txt file, the files below, the OptiScaler fork tree at its locked commit with '
                    'FORK.md and tools/bc250-build.py of its locked tag commit (optiscaler_dir, read from its git '
                    'checkout) and its pins (optiscaler_pins); submodules are listed by public repository and commit, '
                    'not bundled (release/fork_source_archive.py bundles them for the fork\'s release).')
# Files GitHub shows for a repository, generated in a public export from the public documents (target: source). The
# copies at the top of the tree are what the other copies' links reach (README.md -> NOTICE.md); every other link
# reaches the document in packaging/public/.
PUBLIC_ROOT = {
    'README.md': 'packaging/public/README.md',
    'LICENSE': 'packaging/public/LICENSE',
    'NOTICE.md': 'packaging/public/NOTICE.md',
    '.github/SECURITY.md': 'packaging/public/SECURITY.md',
    '.github/CONTRIBUTING.md': 'packaging/public/CONTRIBUTING.md',
}
ROOT_NOTE = ('<!-- Copy of {source} for this folder of the repository, written by release/export_tree.py --public with '
             'its links adjusted; edit {source} instead. -->\n')
LINK = re.compile(r'(\]\()([^)\s]+)(\))')
PLACEHOLDERS = re.compile(r'\[[A-Z][A-Z0-9 -]*[A-Z0-9]\]')
# The identifier families and the decided public name ("chosen") that public_rename applies (release/rename.py).
NAMES = RELEASE / 'names.json'


def keep_entries(path):
    """The entries of a keep list, in order; a list naming a file twice is refused."""
    names = []
    for line in path.read_text().splitlines():
        line = line.split('#', 1)[0].strip()
        if line:
            names.append(line)
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ReleaseError(f'{path.name} lists files twice: ' + ', '.join(duplicates))
    return names


def is_public_tree():
    """A tree exported with --public carries keep-public.txt and no keep.txt."""
    return not KEEP.is_file() and KEEP_PUBLIC.is_file()


def read_keep(config=None, public=None):
    """The entries of keep.txt, or of keep-public.txt when public (default: in a tree exported with --public); each must
    be a file of this tree outside build/ (and outside the build directory and the download cache when config names
    them). The public list must be a subset of keep.txt where keep.txt exists, and must not list keep.txt itself."""
    if public is None:
        public = is_public_tree()
    path = KEEP_PUBLIC if public else KEEP
    if not path.is_file():
        raise ReleaseError(f'{path.relative_to(REPO)} is missing')
    names = keep_entries(path)
    excluded = [REPO / 'build'] + ([config.build, config.cache] if config else [])
    for name in names:
        file = REPO / name
        if name.startswith('/') or '..' in Path(name).parts or not file.is_file():
            raise ReleaseError(f'{path.name} entry is not a file of this tree: {name}')
        if any(file.resolve().is_relative_to(folder) for folder in excluded):
            raise ReleaseError(f'{path.name} entry lies in the build directory or the download cache: {name}')
    if public:
        if str(KEEP.relative_to(REPO)) in names:
            raise ReleaseError('keep-public.txt must not list keep.txt: a public tree reads keep-public.txt, and keep.txt '
                               'names files it does not have')
        if KEEP.is_file():
            outside = sorted(set(names) - set(keep_entries(KEEP)))
            if outside:
                raise ReleaseError('keep-public.txt lists files keep.txt does not (the public tree must be a subset of '
                                   'the release tree): ' + ', '.join(outside))
    return names


def package_spec(public, names=None):
    """package.json, or with public the public package.json (public_package: the intel-free-mfg package; names, the
    exported files, limit its source companion)."""
    spec = json.loads((REPO / PACKAGE).read_text())
    if public:
        spec, _report = public_package(spec, names)
    return spec


def build_records(config, kinds):
    """{kind: (sources the record lists, whether each is still a file of this tree with the recorded sha256)} of the
    build records among kinds that exist under the build directory."""
    records = {}
    for kind in kinds:
        record = config.build / kind / 'build.json'
        if record.is_file():
            sources = json.loads(record.read_text())['sources']
            current = all((REPO / name).is_file() and sha256(REPO / name) == digest for name, digest in sources.items())
            records[kind] = (set(sources), current)
    return records


def required(config, public=False, names=None):
    """(files the release build reads from this tree, as far as package.json (with public: the public package.json)
    and the build records show; stale build records; {file: kinds} of the files only stale records name). A stale
    record's sources count as long as they are still files of this tree: a build that no longer reads one has to be
    rebuilt to drop it."""
    spec = package_spec(public, names)
    needed = {source.removeprefix('repo:') for entry in spec['components'].values() for source in entry['files'].values()
              if source.startswith('repo:')}
    needed |= {f'scripts/{test}.py' for test in spec['installer_tests']}
    records = build_records(config, PUBLIC_BUILD_KINDS if public else BUILD_KINDS)
    current = set().union(*[sources for sources, ok in records.values() if ok])
    stale = sorted(kind for kind, (_sources, ok) in records.items() if not ok)
    only_stale = {}
    for kind in stale:
        for name in records[kind][0]:
            if (REPO / name).is_file():
                needed.add(name)
                if name not in current:
                    only_stale.setdefault(name, []).append(kind)
    return needed | current, stale, only_stale


def untracked(names):
    """keep.txt entries git does not track yet (informational: new files before their first commit)."""
    if not (REPO / '.git').exists():
        return []
    tracked = set(subprocess.run(['git', '-C', str(REPO), 'ls-files', '-z'], capture_output=True, text=True,
                                 check=True).stdout.split('\0'))
    return [n for n in names if n not in tracked]


def host_paths_in(contents):
    """Exported text files whose bytes name a host path (release/host_paths.py, review mode); binary files are skipped."""
    return [name for name, data in contents.items() if host_paths.in_file_bytes(data, review=True)]


# --------------------------------------------------------------------------------------------- public versions of files

def local_includes(name, available):
    """The tree files a C file includes with #include "…" (looked up beside it, then in src/ and src/game/)."""
    found = []
    for target in re.findall(r'^[ \t]*#[ \t]*include[ \t]*"([^"]+)"', source_text(name), re.M):
        for folder in (Path(name).parent, Path('src'), Path('src/game')):
            candidate = str(folder / target)
            if candidate in available:
                found.append(candidate)
                break
    return found


def reachable(roots, available):
    seen, todo = set(), [r for r in roots if r in available]
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo += local_includes(name, available)
    return seen


def proxy_definitions():
    """{name: value} of the proxy's preprocessor definitions (release/build_proxy.py)."""
    import build_proxy  # local import: it reads the build definitions
    out = {}
    for item in build_proxy.definitions()[2]:
        name, _, value = item.partition('=')
        out[name] = int(value or 1, 0)
    return out


def layer_files(available):
    """The C files of the layer build and its tests (release/build_layer.py) with what they include."""
    import build_layer  # local import
    roots = [str(build_layer.SOURCE.relative_to(REPO))] + [f'src/game/{test}.c' for test, _flags in build_layer.TESTS]
    return reachable(roots, available)


def source_text(name):
    """A source's text exactly as stored (UTF-8, line ends untranslated)."""
    return (REPO / name).read_bytes().decode('utf-8')


def quoted_includes(name, text):
    """The tree files a C source includes with #include "…" outside comments (looked up beside it, then in src/ and
    src/game/, the build's include folders); generated headers, which are no tree files, are not listed. Of the probe
    core only the part the game builds compile counts (up to release/proxy_common.py PROBE_SPLIT)."""
    if name == PROBE_CORE:
        from proxy_common import PROBE_SPLIT  # local import
        text = text.split(PROBE_SPLIT)[0]
    found, in_comment = [], False
    for line in text.splitlines():
        start = in_comment
        _code, in_comment = unifdef.scan(line, in_comment)
        match = None if start else re.match(r'^[ \t]*#[ \t]*include[ \t]*"([^"]+)"', line)
        if match:
            for folder in (Path(name).parent, Path('src'), Path('src/game')):
                candidate = (REPO / folder / match.group(1)).resolve()
                if candidate.is_relative_to(REPO.resolve()) and candidate.is_file():
                    found.append(str(candidate.relative_to(REPO.resolve())))
                    break
    return found


def public_sources(names):
    """({name: public text} of the exported C sources that change, information for the report, headers left out). A
    header the public copies still include but keep-public.txt does not list is left out when it resolves to comments
    only (its #include lines go too); otherwise the list lacks it. (main() checks the build records' sources against
    the list and the headers left out.)"""
    listed = [n for n in names if n.startswith('src/') and n.endswith(C_SUFFIXES)]
    texts = {n: source_text(n) for n in listed}
    generated = {n: source_text(n) for n in names if n.startswith('release/generated/') and n.endswith('.h')}
    macros, defined_in_sources = set(), set()
    for text in list(texts.values()) + list(generated.values()):
        macros |= unifdef.conditional_macros(text)
        defined_in_sources |= unifdef.defined_macros(text)
    defined = proxy_definitions()
    undefined = {m for m in macros if m.startswith(PROJECT_MACROS)} - set(defined) - defined_in_sources
    clash = sorted(set(defined) & defined_in_sources)
    if clash:
        raise ReleaseError(f'Public C sources #define macros the proxy build defines: {clash}')
    for name in sorted(layer_files(set(texts))):
        used = sorted(unifdef.conditional_macros(texts[name]) & set(defined))
        if used:
            raise ReleaseError(f'{name} (layer build) tests the proxy\'s definitions {used}: the public copy would '
                               'resolve them for the layer too')
    from proxy_common import PROBE_PATCHES, PROBE_SPLIT  # local import: the probe-core text it patches
    protected = [old for old, _new in PROBE_PATCHES] + [PROBE_SPLIT]
    out, report = {}, dict(defined=sorted(defined), undefined=sorted(undefined), resolved={}, kept_whole=[],
                           left_out=[], mentions=[])

    def resolve(name, text, unknown=frozenset()):
        try:
            result = unifdef.unifdef(text, defined, undefined | unknown, protected if name == PROBE_CORE else (), name)
        except unifdef.UnifdefError as error:
            raise ReleaseError(f'Public C source: {error}') from None
        out[name] = result.text
        if result.resolved:
            report['resolved'][name] = result.resolved
        report['kept_whole'] += [f'{name}:{line}' for line in result.protected]

    for name, text in texts.items():
        resolve(name, text)
    included = {i for name in listed for i in quoted_includes(name, out[name])}
    # Listed vendor headers are shipped verbatim; only this project's src/
    # files undergo conditional removal. They still satisfy include closure.
    candidates = sorted(included - set(names))
    for name in candidates:
        text = source_text(name)
        # its own project macros, beyond those of the listed files, are undefined too
        extra = {m for m in unifdef.conditional_macros(text) if m.startswith(PROJECT_MACROS)} - set(defined) - \
            defined_in_sources - unifdef.defined_macros(text)
        resolve(name, text, frozenset(extra))
    left_out = [n for n in candidates if not unifdef.has_code(out[n])]
    lacking = sorted(set(n for n in included if n not in names) - set(left_out))
    if lacking:
        raise ReleaseError('keep-public.txt lacks headers the public C sources include: ' + ', '.join(lacking))
    emptied_listed = [n for n in listed if not unifdef.has_code(out[n])]
    if emptied_listed:
        raise ReleaseError('keep-public.txt lists C files that hold nothing in the public configuration (drop them from '
                           'the list; the export then leaves out their #include lines): ' + ', '.join(emptied_listed))
    basenames = {Path(n).name for n in left_out}
    clash = sorted(basenames & {Path(n).name for n in listed})
    if clash:
        raise ReleaseError(f'Headers to leave out share a name with exported ones: {clash}')
    changed = {}
    for name in listed:
        text = unifdef.remove_includes(out[name], basenames)
        for line, macro, comment in unifdef.mentions(text, undefined):
            code_line = text.splitlines()[line - 1].lstrip()
            if not comment and not code_line.startswith('#'):
                raise ReleaseError(f'{name}:{line}: {macro} is used outside a conditional; the public copy cannot drop it')
            report['mentions'].append(f'{name}:{line} {macro}' + (' (comment)' if comment else ' (kept conditional)'))
        if text != texts[name]:
            changed[name] = text
    report['left_out'] = left_out
    return changed, report, set(left_out)


def public_lock(lock):
    """inputs.lock.json without the private work groups and the profile's Intel-derived files (see PUBLIC_PROFILE), with
    the public text of the OptiScaler fork group (PUBLIC_FORK)."""
    out = json.loads(json.dumps(lock))
    work = out['work']
    dropped = [group for group in PRIVATE_WORK_GROUPS if work.pop(group, None) is not None]
    profile = work[PROFILE_GROUP]
    files = profile['files']
    profile['files'] = {name: entry for name, entry in files.items() if entry['origin'] == 'own'}
    profile.update(PUBLIC_PROFILE)
    report = dict(dropped_groups=dropped, dropped_profile_files=len(files) - len(profile['files']))
    fork = work.get(FORK_GROUP)
    if fork is not None:
        fork['description'] = PUBLIC_FORK['description']
        fork['path'] = PUBLIC_FORK['path']
        source = fork.get('source', {})
        if 'source_in_work' in source:
            source['source_in_work'] = PUBLIC_FORK['source_in_work']
        report['dropped_fork_notes'] = [key for key in PUBLIC_FORK['dropped_source_keys']
                                        if source.pop(key, None) is not None]
    return out, report


def public_package(spec, names=None):
    """(the public package.json, report): the intel-free-mfg package of spec flattened into the top level (name,
    variant, documents_version, documents_component, package_dir, allowed_components, manifest, components and
    never_ship as release/assemble.py's apply_variant() gives them), with PUBLIC_COMPONENT_NAMES and PUBLIC_SOURCES
    applied and, when names are given, only the source companion files among them; "variants" holds an intel-free-mfg
    entry that replaces nothing. A public package.json projects to itself, so exporting a public tree again keeps it."""
    from assemble import apply_variant  # local import: assemble imports this module
    package = apply_variant(spec, PUBLIC_VARIANT)
    renamed, swapped = {}, []
    components = {}
    for name, component in package['components'].items():
        files = {}
        for target, source in component['files'].items():
            files[target] = PUBLIC_SOURCES.get(source, source)
            if files[target] != source:
                swapped.append(f'{target}: {source} -> {files[target]}')
        public_name = PUBLIC_COMPONENT_NAMES.get(name, name)
        if public_name in components:
            raise ReleaseError(f'The public package would have two components named {public_name}')
        if public_name != name:
            renamed[name] = public_name
        components[public_name] = dict(component, files=files)
    documents = PUBLIC_COMPONENT_NAMES.get(package['documents_component'], package['documents_component'])
    if documents != PUBLIC_DOCUMENTS:
        raise ReleaseError(f'The public package\'s documents component is {documents}, not {PUBLIC_DOCUMENTS} '
                           '(PUBLIC_COMPONENT_NAMES)')
    companion = dict(package['source_companion'], description=PUBLIC_COMPANION)
    listed = companion.get('files', {})
    companion['files'] = {target: source for target, source in listed.items()
                          if names is None or source.removeprefix('repo:') in names}
    from assemble import PUBLIC_MANIFEST  # local import (as above)
    manifest = dict(package['manifest'], status=PUBLIC_PACKAGE_STATUS)
    if isinstance(manifest.get('profile'), dict):
        manifest['profile'] = dict(manifest['profile'], research=PUBLIC_MANIFEST['profile.research'])
    out = dict(about=PUBLIC_ABOUT, name=package['name'], variant=PUBLIC_VARIANT,
               documents_version=package['documents_version'], documents_component=PUBLIC_DOCUMENTS,
               package_dir=package['package_dir'], allowed_components=package['allowed_components'],
               manifest=manifest, components=components, never_ship=package['never_ship'],
               source_companion=companion, installer_tests=package['installer_tests'])
    out.update({key: value for key, value in package.items() if key not in out})
    out['variants'] = {PUBLIC_VARIANT: dict(
        about=PUBLIC_VARIANT_ABOUT, name=out['name'], package_dir=out['package_dir'],
        documents_version=out['documents_version'], replace={}, components={}, manifest={},
        allowed_components=out['allowed_components'])}
    report = dict(variant=PUBLIC_VARIANT, components=len(components), renamed_components=renamed,
                  swapped_sources=swapped, dropped_companion_files=sorted(set(listed) - set(companion['files'])))
    return out, report


def package_sources(spec):
    """{source: [package paths]} of every source a package declaration names."""
    sources = {}
    for component in spec['components'].values():
        for target, source in component['files'].items():
            sources.setdefault(source, []).append(target)
    for source in spec.get('source_companion', {}).get('files', {}).values():
        sources.setdefault(source, []).append('source companion')
    return sources


def public_package_problems(spec, lock, has_file):
    """What makes spec (a public package.json) declare something a public tree cannot build: a "repo:" source that
    has_file(path) does not find, an "input:" source its lock (the public lock) does not pin, a "build:" source of a
    build other than the proxy and the layer (PUBLIC_BUILD_KINDS); and --variant intel-free-mfg must declare the same
    package as no variant."""
    from assemble import BUILD_OUTPUTS, apply_variant  # local import
    problems = []
    if spec.get('variant') != PUBLIC_VARIANT:
        problems.append(f'variant is {spec.get("variant")!r}, not {PUBLIC_VARIANT}')
    for source, targets in sorted(package_sources(spec).items()):
        scheme, _, rest = source.partition(':')
        if scheme == 'repo':
            ok = has_file(rest)
        elif scheme == 'input':
            group, _, name = rest.partition('/')
            entry = lock['fetch'].get(group) or lock['work'].get(group)
            ok = entry is not None and name in entry['files']
        elif scheme == 'build':
            target = rest.partition('/')[0]
            kind = target if target in BUILD_OUTPUTS else target.rpartition('-')[0]
            ok = kind in PUBLIC_BUILD_KINDS
        else:
            ok = False
        if not ok:
            problems.append(f'{source} ({", ".join(targets[:3])})')
    try:
        if apply_variant(spec, PUBLIC_VARIANT) != {k: v for k, v in spec.items() if k != 'variants'}:
            problems.append(f'--variant {PUBLIC_VARIANT} declares a different package')
    except (ReleaseError, KeyError) as error:
        problems.append(f'--variant {PUBLIC_VARIANT} fails: {error}')
    documents = spec['components'].get(spec.get('documents_component', 'documents'), {}).get('files', {})
    if not documents or any(not s.startswith(f'repo:packaging/{spec.get("documents_version")}/') for s in documents.values()):
        problems.append(f'the documents component does not come from packaging/{spec.get("documents_version")}/')
    return problems


def json_text(value):
    """JSON as release/package.json is written (indent 1, trailing newline)."""
    return json.dumps(value, indent=1) + '\n'


# ------------------------------------------------------------------------------------------- the repository's top files

def link_target(copy, source, target, available):
    """A relative link of source (a document in packaging/public/) as its copy at copy must write it: to a copy at the
    top of the tree when that copies the document linked to, else to the document itself. None when the document is
    not in available."""
    path, hash_, anchor = target.partition('#')
    if not path:
        return target
    # A link may climb out of packaging/public/ to another file of the tree (the figures in docs/assets/), never out of it.
    linked = os.path.normpath(Path(source).parent / path)
    if '..' in Path(linked).parts:
        return None
    top = [name for name, origin in PUBLIC_ROOT.items() if origin == linked and '/' not in name]
    destination = top[0] if top else linked
    if destination not in available:
        return None
    up = ['..'] * len(Path(copy).parent.parts)
    return str(Path(*up, destination)) + hash_ + anchor


def external(target):
    """A link that leaves the document set: a URL, mail address, absolute path or anchor."""
    return bool(re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', target)) or target.startswith(('#', '/'))


def root_copy(copy, source, text, available):
    """(text of the copy of a public document at copy, links that reach no exported file)."""
    missing = []

    def fix(match):
        target = match.group(2)
        if external(target):
            return match.group(0)
        rewritten = link_target(copy, source, target, available)
        if rewritten is None:
            missing.append(target)
            return match.group(0)
        return match.group(1) + rewritten + match.group(3)

    if not copy.endswith('.md'):
        return text, missing
    return ROOT_NOTE.format(source=source) + LINK.sub(fix, text), missing


def public_root(names):
    """({path: bytes} of the PUBLIC_ROOT copies, {path: source and placeholders})."""
    clash = sorted(set(PUBLIC_ROOT) & set(names))
    if clash:
        raise ReleaseError('keep-public.txt lists files the public export writes itself (PUBLIC_ROOT): ' + ', '.join(clash))
    lacking = sorted(source for source in PUBLIC_ROOT.values() if source not in names)
    if lacking:
        raise ReleaseError('keep-public.txt lacks the sources of the repository\'s top files: ' + ', '.join(lacking))
    available = set(names) | set(PUBLIC_ROOT)
    contents, report, broken = {}, {}, []
    for copy, source in PUBLIC_ROOT.items():
        text, missing = root_copy(copy, source, source_text(source), available)
        broken += [f'{copy}: {target}' for target in missing]
        contents[copy] = text.encode('utf-8')
        report[copy] = dict(source=source, placeholders=sorted(set(PLACEHOLDERS.findall(text))))
    if broken:
        raise ReleaseError('Links of the repository\'s top files reach no exported file: ' + ', '.join(broken))
    return contents, report


# ------------------------------------------------------------------------------------------------------- the public name

def public_rename(contents, names=None, source=None):
    """(contents with names.json's chosen public name applied, report). contents: {path: bytes, or None for a copy of
    this tree's file}, as main() exports them; the result maps the files the rename changes to their new bytes and
    leaves every other entry as it was (the input is not changed, and no file of this tree is written). names: a loaded
    names.json (release/rename.py load_names; default: this tree's). With no chosen name the contents come back
    unchanged; otherwise rename.py rename_texts() rewrites the user-visible families over the exported text files
    except names.json "exclude", and the public package name must be package-name's public_template. source: where
    names came from, for the messages (default: this tree's names.json)."""
    import rename  # local import: only the public export renames
    where = source or (NAMES.relative_to(REPO) if names is None else 'names.json')
    try:
        names = names or rename.load_names(NAMES)
        choice = rename.chosen_name(names)
    except rename.RenameError as error:
        raise ReleaseError(f'{where}: {error}') from None
    if choice is None:
        return contents, dict(chosen=None)
    texts = {}
    for name, data in contents.items():
        if name not in names['exclude']:
            text = rename.text_of(data if data is not None else (REPO / name).read_bytes())
            if text is not None:
                texts[name] = text
    try:
        changed, moves, warnings = rename.rename_texts(texts, choice['name'], choice['slug'], choice['holder'],
                                                       family_ids=choice['families'], names=names)
    except rename.RenameError as error:
        raise ReleaseError(f'Not exporting under the chosen name {choice["name"]!r}: {error}') from None
    if moves:
        raise ReleaseError('The chosen rename would move tracked files (' + ', '.join(f'{a} -> {b}' for a, b in moves.items())
                           + '); a public export does not rename files')
    out = dict(contents)
    out.update({name: text.encode('utf-8') for name, text in changed.items()})
    report = dict(chosen=dict(name=choice['name'], slug=choice['slug'], holder=choice['holder'],
                              families=choice['families']),
                  files=sorted(changed), warnings=choice['warnings'] + warnings)
    if PACKAGE in out:
        # The exported package is named by package-name public_template with the chosen slug, a name release/assemble.py
        # accepts (also when this tree was renamed before and nothing was left to rewrite).
        from assemble import package_naming  # local import: assemble imports this module
        spec = json.loads(out[PACKAGE] if out[PACKAGE] is not None else (REPO / PACKAGE).read_bytes())
        public_name = spec['name'] if spec.get('variant') == PUBLIC_VARIANT else spec['variants'][PUBLIC_VARIANT]['name']
        parsed = package_naming(public_name, names)
        if parsed['kind'] != 'public' or parsed['slug'] != choice['slug']:
            raise ReleaseError(f'The public package name {public_name!r} is not package-name public_template with the '
                               f'chosen slug {choice["slug"]!r} ({where})')
        report.update(public_package_name=public_name, version=parsed['version'],
                      receipt='qualification/' + parsed['receipt'])
    return out, report


def check_public_export(destination):
    """Problems of an exported public tree, read from the export itself: its package.json declares only what the tree
    can build (public_package_problems against its own files and lock) and projects to itself, and every relative link
    of the top files reaches a file of the export."""
    problems = []
    text = (destination / PACKAGE).read_text()
    spec = json.loads(text)
    lock = json.loads((destination / LOCK).read_text())
    problems += [f'{PACKAGE}: {p}' for p in public_package_problems(spec, lock, lambda n: (destination / n).is_file())]
    names = {str(p.relative_to(destination)) for p in destination.rglob('*') if p.is_file()}
    if json_text(public_package(spec, names)[0]) != text:
        problems.append(f'{PACKAGE} is not its own public projection')
    for copy in PUBLIC_ROOT:
        if not (destination / copy).is_file():
            problems.append(f'{copy} is missing')
            continue
        for match in LINK.finditer((destination / copy).read_text()):
            target = match.group(2).partition('#')[0]
            if target and not external(match.group(2)) and not (destination / copy).parent.joinpath(target).resolve().is_file():
                problems.append(f'{copy}: link to missing {target}')
    return problems


def public_files(names, config):
    """({name: bytes} of the public versions of exported files, report, headers left out)."""
    changed, report, left_out = public_sources(names)
    contents = {name: text.encode('utf-8') for name, text in changed.items()}
    lock = None
    if LOCK in names:
        lock, report['lock'] = public_lock(json.loads((REPO / LOCK).read_text()))
        text = json.dumps(lock, indent=1) + '\n'
        if text != (REPO / LOCK).read_text():
            contents[LOCK] = text.encode()
    if PACKAGE in names:
        package, report['package'] = public_package(json.loads((REPO / PACKAGE).read_text()), set(names))
        problems = public_package_problems(package, lock or json.loads((REPO / LOCK).read_text()),
                                           lambda name: name in names)
        if problems:
            raise ReleaseError('The public package.json declares what the public tree cannot build: ' + '; '.join(problems))
        text = json_text(package)
        if text != (REPO / PACKAGE).read_text():
            contents[PACKAGE] = text.encode()
    if MATERIAL in names:
        material = json.loads((REPO / MATERIAL).read_text())
        if 'refused' not in material:
            import check_intel_free  # local import
            public = check_intel_free.public_material(config)
            contents[MATERIAL] = (json.dumps(public, indent=2) + '\n').encode()
            report['material'] = dict(refused=len(public['refused']), warp_tables=len(public['warp_tables']))
    return contents, report, left_out


# ---------------------------------------------------------------------------------------------------------------- copy

def export(contents, destination, origins=None):
    """Write contents ({name: bytes, or None for a copy of this tree's file}) under destination; a written file takes
    the permissions of its tree file, or of origins[name] (the source of a generated file)."""
    origins = origins or {}
    if destination.exists() and any(destination.iterdir()):
        raise ReleaseError(f'{destination} exists and is not empty')
    if destination.resolve() == REPO:
        raise ReleaseError('The destination must be a new directory, not this tree')
    for name, data in contents.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if data is None:
            shutil.copy2(REPO / name, target)
            data = (REPO / name).read_bytes()
        else:
            target.write_bytes(data)
            shutil.copymode(REPO / origins.get(name, name), target)
        if target.read_bytes() != data:
            raise ReleaseError(f'Copy of {name} differs')


def import_tools(names, destination):
    """Import every exported release/*.py module inside the export (isolated interpreter, no bytecode written); returns
    their names. Fails when a module imports one the list lacks."""
    modules = sorted(Path(name).stem for name in names
                     if Path(name).parent == Path('release') and name.endswith('.py'))
    code = 'import importlib, sys; sys.path.insert(0, sys.argv[1]); [importlib.import_module(m) for m in sys.argv[2:]]'
    out = subprocess.run([sys.executable, '-I', '-B', '-c', code, str(destination / 'release'), *modules],
                         cwd=destination, capture_output=True, text=True)
    if out.returncode:
        raise ReleaseError(f'A release tool does not import in the export {destination} (the list lacks a module it '
                           f'imports?):\n{out.stderr[-3000:]}')
    return modules


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('destination', type=Path, help='new or empty directory')
    parser.add_argument('--public', action='store_true',
                        help='export the public tree (release/keep-public.txt: the intel-free-mfg build, the layer and the '
                             'installer); the default in a tree that was itself exported with --public')
    parser.add_argument('--strict', action='store_true',
                        help='refuse the export, before copying, when an exported file names a host path or a build '
                             'record is stale')
    parser.add_argument('--no-tests', action='store_true',
                        help='do not import the release tools or run the installer tests in the exported directory')
    parser.add_argument('--names', type=Path, metavar='FILE',
                        help='with --public: read the chosen public name from this copy of release/names.json (a trial '
                             'with a scratch copy; the export still copies this tree\'s names.json)')
    add_arguments(parser)
    args = parser.parse_args()
    config = Config.from_args(args)
    public = args.public or is_public_tree()
    if args.names and not public:
        parser.error('--names applies to a public export (--public) only')
    names = read_keep(config, public=public)
    listing = (KEEP_PUBLIC if public else KEEP).relative_to(REPO)
    needed, stale, only_stale = required(config, public, set(names))
    if stale and args.strict:
        raise ReleaseError(f'Not exporting (--strict): stale build records {", ".join(stale)} (rebuild them first)')
    transformed, report, left_out = public_files(names, config) if public else ({}, {}, set())
    missing = sorted(needed - set(names) - left_out)
    if missing:
        hint = [f'{name} (only in the stale record of {", ".join(only_stale[name])}: rebuild if the build no longer '
                'reads it)' for name in missing if name in only_stale]
        raise ReleaseError(f'{listing.name} lacks files the release build reads: ' + ', '.join(missing)
                           + ('; ' + '; '.join(hint) if hint else ''))
    contents = {name: transformed.get(name) for name in names}
    root, root_report = public_root(names) if public else ({}, {})
    contents.update(root)
    rename_report = None
    if public:
        loaded = None
        if args.names:
            import rename  # local import
            try:
                loaded = rename.load_names(args.names)
            except (OSError, ValueError, rename.RenameError) as error:
                raise ReleaseError(f'--names {args.names}: {error}') from None
        contents, rename_report = public_rename(contents, loaded, source=args.names)
        for copy in root:
            root_report[copy]['placeholders'] = sorted(set(PLACEHOLDERS.findall(contents[copy].decode('utf-8'))))
    named_host_paths = host_paths_in({name: data if data is not None else (REPO / name).read_bytes()
                                      for name, data in contents.items()})
    if named_host_paths and args.strict:
        raise ReleaseError('Not exporting (--strict): files name a host path: ' + ', '.join(named_host_paths))
    export(contents, args.destination, origins=PUBLIC_ROOT)
    if public:
        problems = check_public_export(args.destination)
        if problems:
            raise ReleaseError(f'The public export in {args.destination} is incomplete: ' + '; '.join(problems))
    if named_host_paths:
        print('warning: exported files name a host path: ' + ', '.join(named_host_paths), file=sys.stderr)
    if stale:
        print(f'note: stale build records (their sources still count; rebuild them): {", ".join(stale)}',
              file=sys.stderr)
    tests, tools = 'skipped', 'skipped'
    if not args.no_tests:
        tools = import_tools(names, args.destination.resolve())
        from assemble import installer_tests  # local import: assemble imports this module
        spec = package_spec(public, set(names))
        try:
            installer_tests(spec, args.destination.resolve())
        except ReleaseError as error:
            raise ReleaseError(f'The export in {args.destination} is incomplete ({listing.name} lacks a file the '
                               f'installer tests read?): {error}') from None
        tests = f'{len(spec["installer_tests"])} passed in the export'
    output = dict(destination=str(args.destination), tree='public' if public else 'release', list=str(listing),
                  files=len(names), release_tools_imported=tools, installer_tests=tests, stale_build_records=stale,
                  not_yet_tracked=untracked(names), host_paths=named_host_paths)
    if public:
        output['public_versions'] = dict(files=sorted(transformed), **report)
        output['public_root'] = root_report
        output['public_name'] = rename_report
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        sys.exit(f'error: {error}')
