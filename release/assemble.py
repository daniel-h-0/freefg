#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Assemble a tester package directory from tracked files, pinned inputs and freshly built binaries.

Contents come only from release/package.json: tracked files of this repository, files pinned in inputs.lock.json
(work directory or fetch cache, each checked by sha256) and the outputs of build_addon.py and build_layer.py (checked
against their build records, and the records against the current sources and lock). No earlier package or candidate
is read. The result is written to <build>/package/<name>/ (a variant: <build>/<its package_dir>/<name>/) with:

  manifest.json                         the schema the installer and the library owner read: runtime, launcher_setup,
                                        name, files (sha256 of every other file), plus provenance; no absolute paths
  qualification/xemfg-vNN-package.json  a receipt skeleton with status "pending" and the payload/components it
                                        covers; qualification fills in its results and sets status "pass" (a package
                                        under a public name: qualification/<slug>-v<NN>-2x-package.json, see below)
  SOURCE.md, SOURCE.json                name and sha256 of the source companion <name>-source.zip, written beside the
                                        directory by source_companion.py (deterministic, so a receipt covers them)

Checks before anything is written: the documents come from packaging/<version>/ (a variant may name another folder in
its documents_version: intel-free-mfg and intel-free-2x ship the public set of packaging/public/); no evidence/xemfg-<version>-package.json
of an earlier build with a different payload exists (a version number is never reused); every file the package must
not carry (package.json never_ship) is pinned as a 'runtime' download in the packaged dependencies.json with the bytes
the package used to carry, so the installer still gets it; the add-on and layer builds are current.

Typical use:
  python3 release/build_addon.py && python3 release/build_layer.py
  python3 release/assemble.py                                   # pending package for qualification
  python3 release/assemble.py --receipt <passed receipt> --archive
                                                                # after qualification: same contents, qualified receipt,
                                                                # <name>.zip and <name>.zip.sha256 beside the directory

--archive also needs a clean git checkout (every shipped file and build source equal to HEAD), a source companion
for components that require a source offer, and documents without the [DRAFT] marker. A package that ships the public
documents (documents_version "public": the intel-free-mfg variant, and intel-free-2x) passes the public gate besides: it is archived only
when packaging/public/check_public_docs.py --release reports no error (run as that tool: no placeholder such as
[PRODUCT] or [VERSION] and no [DRAFT] marker left in the documents and LICENSE, and nothing its normal check reports),
when the manifest's text, the generated SOURCE.md and SOURCE.json, the OptiScaler fork's build route files that the
source companion carries (FORK.md and the build script at the locked tag) and the receipt to be staged carry no
placeholder or [DRAFT] marker, when the receipt is a finished one (receipt_draft_problems(): no "draft" or "proposed_*"
field, no bracketed upper-case token such as [PACKAGE-NAME], no DRAFT), and when neither written zip, <name>.zip and
the source companion <name>-source.zip, names a host path (release/host_paths.py in review mode, the way export_tree.py
reviews an export). On a host path both zips and their .sha256 files are deleted again. This tree's public documents
keep [PRODUCT], so the public package is archived from a public export renamed under the decided name
(release/export_tree.py --public).

The host-path scan reads the member names and every text member; it does not scan binary members, whose strings a
generic detector cannot tell from data (the upstream OptiScaler tree in the source companion has third-party build paths
in its prebuilt libraries). The maintainers make the public archive with release/publish_local.py, which also scans the
ASCII and UTF-16 strings of every binary member for this machine's own names; an archive made with assemble.py alone
has not had that scan.

--variant intel-free assembles the package that package.json "variants" defines instead: the Intel-free add-on and
profile (release/build_addon.py --variant intel-free) in place of the default ones, under its own name. The result is
then checked by release/check_intel_free.py (findings in the variant's allowed components are reported, not failing)
and the manifest records the outcome (intel_free.result "pass", or "pass-with-allowed-components" with
intel_free_complete false when only the allowed components carry findings); the package is removed again when the
check fails. --variant intel-free-mfg (the released build) and intel-free-2x are the enabler-free ones (release/build_proxy.py): its add-on is a libxess_fg.dll
proxy (manifest addon_entry "libxess_fg-proxy"), it has no XeSSMFG component and no allowed component, its own
never_ship rules, and its runtime downloads follow dependencies.json runtime.ProxyPackage. The maintainers' library
tooling does not deploy a variant package: its name has no plain private-test-NN number, so that tooling finds no
qualification receipt for it.

Package names (package_naming()): bc250-fsr4-xemfg-private-test-NN[-variant] (version vNN[-variant], receipt
xemfg-vNN[-variant]-package.json), and in a public tree renamed under the chosen public name (release/names.json
"chosen", release/export_tree.py --public) the name release/names.json package-name public_template gives: today
{slug}-1.0.0, the decided version as fixed text (<slug>-1.0.0, version v1.0.0, receipt public_receipt_template:
<slug>-v1.0.0-package.json), which the rename's package-name replacement writes too. A public version is a build
number (an integer) or a dotted version MAJOR.MINOR.PATCH[.REVISION], as fixed text or as {number}, which matches either:
{slug}-{number}-2x, the template before the version was decided, gives <slug>-NN-2x with the private build number
(version vNN-2x, receipt <slug>-vNN-2x-package.json) or <slug>-0.1.0-2x (v0.1.0-2x). The receipt name is the same
under qualification/ in the package and under evidence/ for the version check.

The public build (public_build(): the variant that ships the public documents, assembled in a public export or under
a public name) carries neutral manifest text (PUBLIC_MANIFEST: status and profile.research) in place of package.json's,
which describes the maintainers' builds; its [PRODUCT] is names.json "chosen" name once decided. Its runtime stays
"xemfg" (the value install.py and Setup read) and candidate stays true until a passed receipt is staged. Assembled in
this tree under its private name, the intel-free-mfg and intel-free-2x variants keep package.json's text.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import string
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import REPO, RELEASE, Config, ReleaseError, add_arguments, sha256  # noqa: E402
import host_paths  # noqa: E402
import source_companion  # noqa: E402
from export_tree import is_public_tree, read_keep  # noqa: E402

PACKAGE_SPEC = RELEASE / 'package.json'
EVIDENCE = REPO / 'evidence'
# Package names (package_naming()): the private builds' (the library owner deploys private-test-NN), and the public pattern of
# release/names.json package-name (a public tree renamed under the chosen name, release/export_tree.py --public).
PRIVATE_NAME = re.compile(r'bc250-fsr4-xemfg-private-test-(\d+)(-[a-z][a-z0-9-]*)?')
NAMES = RELEASE / 'names.json'
# A public version (package_naming()): a build number (an integer, as the private builds count) or a dotted semantic
# version MAJOR.MINOR.PATCH, optionally followed by a maintenance revision (1.1.3.1).
# No component may have a leading zero.
SEMVER = r'(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)'
PUBLIC_NUMBER = rf'{SEMVER}(?:\.(?:0|[1-9]\d*))?|\d+'
# A fixed version in public_template's text after {slug} (once decided: {slug}-0.1.0, {slug}-32-2x): text without
# digits, the version, then text that does not continue it (-2x, or nothing).
FIXED_VERSION = re.compile(rf'(?P<lead>\D*?)(?P<number>{PUBLIC_NUMBER})(?P<suffix>(?![0-9A-Za-z.]).*)', re.S)
# The public build (public_build()): the package that ships the public documents (documents_version "public", the
# intel-free-mfg variant), its document check, and the manifest text it carries in place of package.json's (which
# describes the maintainers' builds). {product} is names.json "chosen" name, [PRODUCT] while undecided.
PUBLIC_DOCUMENTS = 'public'
PUBLIC_DOCS_CHECK = 'packaging/public/check_public_docs.py'
PRODUCT = '[PRODUCT]'
PUBLIC_MANIFEST = {
    'status': "{product} {version}: frame generation through Intel's unmodified XeFG runtime (downloaded by the "
              "installer) behind a libxess_fg.dll proxy that runs part of the runtime's GPU work with this project's "
              "own shaders at the frame count the runtime runs (2x on its own; 3x and 4x only beside a separate tool "
              "the user adds that lifts Intel's limit), paces presents for VRR displays and optionally generates at a smaller "
              'resolution before enlarging generated frames. Match output is the default. See README.md and ARCHITECTURE.md',
    'profile.research': "this project's own shaders only, built from its HLSL sources (src/kernels), for the "
                        'one-frame and multi-frame networks',
}
# The archives of a package directory, beside it (archive(), source_companion.py).
ARCHIVES = ('{name}.zip', '{name}.zip.sha256', '{name}-source.zip', '{name}-source.zip.sha256')
BUILD_OUTPUTS = {'addon': ('addon', 'BC250-MFG.asi'), 'layer': ('layer', 'libxefg_wave.so'),
                 'addon-intel-free': ('addon-intel-free', 'BC250-MFG.asi'),
                 'addon-intel-free-2x': ('addon-intel-free-2x', 'libxess_fg.dll'),
                 'addon-intel-free-mfg': ('addon-intel-free-mfg', 'libxess_fg.dll')}
BUILD_COMMANDS = {'addon-intel-free': 'build_addon.py --variant intel-free', 'addon-intel-free-2x': 'build_proxy.py',
                  'addon-intel-free-mfg': 'build_proxy.py --variant intel-free-mfg'}
# manifest addon_entry of packages whose add-on is a libxess_fg.dll proxy (no XeSSMFG enabler): their runtime downloads
# follow dependencies.json runtime.ProxyPackage instead of runtime.Package.
PROXY_ENTRY = 'libxess_fg-proxy'
LAYER_BUILD = 'gcc -O2 -shared -fPIC -Wall -Wextra src/game/wave_layer.c -o libxefg_wave.so -lpthread'
# Absolute system paths in emitted and shipped JSON (with value.startswith('/') below); host paths (home directories,
# removable media, named home folders, Wine's and Windows' user folders, this host's administration repository as a
# path component) come from release/host_paths.py, the detector release/export_tree.py uses too. Hidden per-user
# folders such as ~/.steam and ~/.config are not host paths.
ABSOLUTE = re.compile(r'(^|[\s"\'(=:,])/(home|run|usr|tmp|mnt|media|opt|var|etc|root|srv)/')
DRAFT_MARKER = '[DRAFT]'
SOURCE_OFFER = ('SOURCE.json', 'SOURCE.md')
# The package's integration contract (install.py contract --json, docs/INTEGRATION.md), generated by integration_json().
INTEGRATION = 'integration.json'


def load_names(path=NAMES):
    """release/names.json as JSON, or None when this tree has none (then only private names are accepted)."""
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


def public_naming(names):
    """dict(template, pattern (regex with group slug, and number for a template with {number}), fixed (the version
    written in the template, or None), suffix (the version's text after the number), receipt (template)) from names.json
    package-name public_template and public_receipt_template; None without names.json.

    public_template is {slug}<text>{number}<text> ({slug}-{number}-2x: the number in the name, version
    v<number>-2x), or, once the version is decided, {slug}<text> with that version as fixed text ({slug}-0.1.0:
    version v0.1.0; {slug}-32-2x: v32-2x). A version, in a name or in the template, is a build number (an integer) or
    a dotted version MAJOR.MINOR.PATCH[.REVISION] (PUBLIC_NUMBER)."""
    if names is None:
        return None
    family = next(f for f in names['families'] if f['id'] == 'package-name')
    template, receipt = family.get('public_template'), family.get('public_receipt_template')
    if not isinstance(template, str) or not isinstance(receipt, str):
        raise ReleaseError('names.json package-name lacks public_template or public_receipt_template')
    parts = list(string.Formatter().parse(template))
    fields = [field for _text, field, _spec, _conv in parts if field is not None]
    tail = parts[-1][0] if parts[-1][1] is None else ''  # the text after the last field
    fixed = FIXED_VERSION.fullmatch(tail) if fields == ['slug'] else None
    if not (fields == ['slug', 'number'] or fixed) or any(s or c for _t, _f, s, c in parts):
        raise ReleaseError(f'names.json package-name public_template must name {{slug}}, then {{number}} or a fixed '
                           f'version (a build number or MAJOR.MINOR.PATCH[.REVISION]): {template!r}')
    unknown = {f for _t, f, _s, _c in string.Formatter().parse(receipt) if f is not None} - {'slug', 'version', 'number'}
    if unknown or '/' in receipt or not receipt.endswith('.json'):
        raise ReleaseError(f'names.json package-name public_receipt_template must be a .json file name using {{slug}}, '
                           f'{{version}} and {{number}}: {receipt!r}')
    slug = names['name_rules']['slug'].removeprefix('^').removesuffix('$')
    groups = {'slug': f'(?P<slug>{slug})', 'number': f'(?P<number>{PUBLIC_NUMBER})', None: ''}
    pattern = ''.join(re.escape(text) + groups[field] for text, field, _spec, _conv in parts)
    return dict(template=template, pattern=re.compile(pattern), fixed=fixed['number'] if fixed else None,
                suffix=fixed['suffix'] if fixed else tail, receipt=receipt)


def package_naming(name, names=None):
    """How a package name names its version and receipt: dict(kind, version, receipt (the receipt's file name under
    qualification/ and evidence/), and for a public name slug and number).

    Private: bc250-fsr4-xemfg-private-test-NN[-variant] -> vNN[-variant], xemfg-vNN[-variant]-package.json (the private
    library owner reads that receipt of private-test-NN builds). Public (a renamed public tree): a name of names.json
    package-name public_template, {slug}-{number}-2x -> v<number>-2x (<number> a build number or MAJOR.MINOR.PATCH[.REVISION]),
    or a template's fixed version ({slug}-0.1.0 -> v0.1.0), and public_receipt_template ({slug}-{version}-package.json).
    A public name must not match the library owner's pattern and its slug must not carry a refused word
    (release/rename.py check_name). names: names.json (default: this tree's)."""
    match = PRIVATE_NAME.fullmatch(name)
    if match:
        version = 'v' + match[1] + (match[2] or '')
        return dict(kind='private', version=version, receipt=f'xemfg-{version}-package.json')
    names = load_names() if names is None else names
    public = public_naming(names)
    match = public['pattern'].fullmatch(name) if public else None
    if not match:
        expected = f' or {public["template"]} (release/names.json package-name public_template)' if public else ''
        raise ReleaseError(f'Package name must be bc250-fsr4-xemfg-private-test-NN[-variant]{expected}: {name}')
    if re.search(names['library_owner']['pattern'], name):
        raise ReleaseError(f'Public package name {name} matches the private library owner\'s pattern')
    import rename  # local import: the name rules
    try:
        rename.check_name(match['slug'], match['slug'], names)
    except rename.RenameError as error:
        raise ReleaseError(f'Public package name {name}: its slug {match["slug"]!r} is refused by names.json '
                           f'name_rules ({error})') from None
    number = public['fixed'] or match['number']
    version = 'v' + number + public['suffix']
    receipt = public['receipt'].format(slug=match['slug'], version=version, number=number)
    return dict(kind='public', version=version, receipt=receipt, slug=match['slug'], number=number)


def version_of(name):
    """vNN for bc250-fsr4-xemfg-private-test-NN, vNN-<variant> for bc250-fsr4-xemfg-private-test-NN-<variant>, and the
    public version of a name of names.json's public_template (package_naming())."""
    return package_naming(name)['version']


def receipt_file(name):
    """The receipt's file name (under qualification/ in the package, under evidence/ for earlier builds) (package_naming())."""
    return package_naming(name)['receipt']


def apply_variant(spec, variant):
    """The package declaration of a variant: package.json with the variant's components, name and manifest fields."""
    entry = spec.get('variants', {}).get(variant)
    if entry is None:
        raise ReleaseError(f'package.json defines no variant {variant!r}')
    components = {}
    for name, component in spec['components'].items():
        replacement = entry['replace'].get(name, name)
        if replacement is not None:
            components[replacement] = component if replacement == name else entry['components'][replacement]
    for name, component in entry['components'].items():
        components.setdefault(name, component)
    unused = sorted(set(entry['replace']) - set(spec['components']))
    if unused:
        raise ReleaseError(f'Variant {variant} replaces unknown components: {", ".join(unused)}')
    out = {k: v for k, v in spec.items() if k != 'variants'}
    out.update(name=entry['name'], components=components, manifest=dict(spec['manifest'], **entry['manifest']),
               variant=variant, documents_version=entry['documents_version'],
               documents_component=entry['replace'].get('documents', 'documents'),
               package_dir=entry.get('package_dir', 'package'),
               allowed_components=entry.get('allowed_components', {}),
               never_ship=entry.get('never_ship', spec['never_ship']))
    if 'documents_base' in entry:
        out['documents_base'] = entry['documents_base']
    return out


def runtime_layout(spec):
    """The dependencies.json runtime mapping (package path -> pinned file) that supplies this package's never-ship files."""
    return 'ProxyPackage' if spec['manifest'].get('addon_entry') == PROXY_ENTRY else 'Package'


def profile_digest(names_and_digests):
    """The add-on build record's profile digest: sha256 over sorted 'name<TAB>sha256' lines."""
    return hashlib.sha256(''.join(f'{n}\t{d}\n' for n, d in sorted(names_and_digests)).encode()).hexdigest()


class Sources:
    """Resolves the source strings of package.json to checked files."""

    def __init__(self, config):
        self.config = config
        self.records = {}

    def record(self, kind):
        """(build record, binary, record path) of a current build: the binary matches its record, and the record's
        sources, profile, loader, fetched inputs and reference still match this tree and the lock."""
        if kind not in self.records:
            folder, output = BUILD_OUTPUTS[kind]
            path = self.config.build / folder / 'build.json'
            if not path.is_file():
                raise ReleaseError(f'No {kind} build: run release/{build_command(kind)} first ({path} is missing)')
            record = json.loads(path.read_text())
            binary = self.config.build / folder / output
            if not binary.is_file() or sha256(binary) != record['sha256']:
                raise ReleaseError(f'{binary} differs from its build record; rebuild it')
            stale = sorted(name for name, digest in record['sources'].items()
                           if not (REPO / name).is_file() or sha256(REPO / name) != digest)
            lock = self.config.lock
            reference_key = f'{output} ({record["variant"]})' if 'variant' in record else output
            if record.get('reference_sha256') != lock.get('outputs', {}).get(reference_key):
                stale.append('inputs.lock.json outputs')
            if kind == 'addon':
                profile = lock['work']['profile-cl-wino-q33']['files']
                if record['profile']['sha256'] != profile_digest((n, e['sha256']) for n, e in profile.items()):
                    stale.append('shader profile (inputs.lock.json)')
            if kind.startswith('addon-'):
                stale += self.variant_profile_changes(record, path.parent)
            if kind.startswith('addon') and 'loader' in record:
                if record['loader']['sha256'] != lock['work']['xessmfg-enabler']['files'][record['loader']['file']]['sha256']:
                    stale.append('XeSSMFG loader (inputs.lock.json)')
            if kind.startswith('addon') and 'original' in record:  # the proxy's Intel runtime (build_proxy.py)
                original = record['original']
                if lock['fetch'][original['group']]['files'][original['source']]['sha256'] != original['sha256']:
                    stale.append('Intel runtime (inputs.lock.json)')
                stale += [f'{group} commit' for group, commit in record['fetched'].items()
                          if lock['fetch'][group]['commit'] != commit]
            if stale:
                raise ReleaseError(f'The {kind} build is stale ({", ".join(stale[:8])} changed since it was built): '
                                   f'run release/{build_command(kind)} again')
            self.records[kind] = (record, binary, path)
        return self.records[kind]

    def variant_profile_changes(self, record, folder):
        """What changed since a variant add-on build assembled its profile: each file must still be in the build's
        profile directory with the recorded bytes, each one copied from the locked profile must still be locked with
        those bytes, each of the variant's own files (replaced or added) must still be pinned with those bytes in the
        lock's tree group, and each rewritten one must still have the locked base file it was derived from (the rewrite rule
        itself is intel_free.json, one of the record's sources)."""
        changes = []
        locked = self.config.lock['work']['profile-cl-wino-q33']['files']
        rewritten = record['profile']['rewritten']
        if not isinstance(rewritten, dict):  # records before the base digests were kept
            return ['profile record format (rewritten base files)']
        # the variant's own files (build_proxy.py "replace" / "add"), pinned in the lock's tree group
        own = dict(record['profile'].get('replaced', {}), **record['profile'].get('added', {}))
        tree = self.config.lock.get('tree', {}).get(record['profile'].get('own_group') or '', {}).get('files', {})
        for name, digest in record['profile']['file_sha256'].items():
            path = folder / record['profile']['directory'] / name
            if not path.is_file() or sha256(path) != digest:
                changes.append(f'profile file {name} (build directory)')
            elif name in own:
                if own[name] != digest or name not in tree or tree[name]['sha256'] != digest:
                    changes.append(f'own profile file {name} (inputs.lock.json tree)')
            elif name in rewritten:
                if name not in locked or locked[name]['sha256'] != rewritten[name]:
                    changes.append(f'base of rewritten profile file {name} (inputs.lock.json)')
            elif name in locked and locked[name]['sha256'] != digest:
                changes.append(f'profile file {name} (inputs.lock.json)')
        if profile_digest(record['profile']['file_sha256'].items()) != record['profile']['sha256']:
            changes.append('profile digest')
        return changes

    def profile_file(self, kind, name):
        """A profile file of a variant add-on build, checked against the build record."""
        record, _binary, path = self.record(kind)
        digest = record.get('profile', {}).get('file_sha256', {}).get(name)
        if digest is None:
            raise ReleaseError(f'The {kind} build has no profile file {name}')
        return path.parent / record['profile']['directory'] / name

    def resolve(self, source):
        scheme, _, rest = source.partition(':')
        if scheme == 'repo':
            path = REPO / rest
            if not path.is_file():
                raise ReleaseError(f'Missing tracked file {rest}')
            return path
        if scheme == 'input':
            group, _, name = rest.partition('/')
            return self.config.input_file(group, name)
        if scheme == 'build':
            target, _, name = rest.partition('/')
            kind = target if target in BUILD_OUTPUTS else target.rpartition('-')[0]
            part = target[len(kind) + 1:]
            if kind not in BUILD_OUTPUTS or part not in ('', 'record', 'profile') or bool(name) != (part == 'profile'):
                raise ReleaseError(f'Unknown build source {source}')
            if part == 'profile':
                return self.profile_file(kind, name)
            _record, binary, record_path = self.record(kind)
            return record_path if part else binary
        raise ReleaseError(f'Unknown source {source}')


def build_command(kind):
    """The release/ command that writes a build output."""
    return BUILD_COMMANDS.get(kind, f'build_{kind}.py')


# HelixSR's setup appends the network it builds from NVIDIA's DLSS DLL behind a 32-byte footer that starts with this magic
# (packaging/helixsr.py). Such a DLL is NVIDIA's network on the user's computer and is never shipped, whatever its hash.
HELIXSR_NETWORK_MAGIC = b'HXSRNET1'


def built_helixsr(path):
    """True when the file ends in HelixSR's network footer (a HelixSR DLL its setup has built)."""
    try:
        size = path.stat().st_size
        if size < 32:
            return False
        with open(path, 'rb') as stream:
            stream.seek(size - 32)
            tail=stream.read(32)
            return tail[:8] == HELIXSR_NETWORK_MAGIC or tail[8:16] == b'HLXFSR4D'
    except OSError:
        return False


def plan(spec, sources):
    """{package path: (component, source file)} after the never-ship rules."""
    rules = spec['never_ship']
    files = {}
    for component, entry in spec['components'].items():
        for target, source in entry['files'].items():
            if target in files:
                raise ReleaseError(f'{target} is listed by both {files[target][0]} and {component}')
            if target == 'manifest.json' or target in SOURCE_OFFER or target.startswith('/') or '..' in Path(target).parts:
                raise ReleaseError(f'Invalid package path {target}')
            if target in rules['paths'] or target.startswith(tuple(rules['prefixes'])):
                raise ReleaseError(f'{target} must not be shipped (package.json never_ship)')
            path = sources.resolve(source)
            digest = sha256(path)
            if digest in rules['sha256']:
                raise ReleaseError(f'{target} is {rules["sha256"][digest]}, which must not be shipped')
            if built_helixsr(path):
                raise ReleaseError(f'{target} is an HLX DLL containing locally built model data, '
                                   'which must not be shipped')
            files[target] = (component, path)
    return dict(sorted(files.items()))


def check_runtime_supply(spec, files):
    """Every never-ship path must still reach installations: the packaged dependencies.json pins it as a 'runtime'
    download (runtime.Package: package path -> pinned file) with bytes the never-ship rules identify (the bytes the
    package used to carry)."""
    if 'dependencies.json' not in files:
        raise ReleaseError('The package has no dependencies.json, so nothing supplies the files it must not carry')
    pins = json.loads(files['dependencies.json'][1].read_text())
    runtime = pins.get('runtime', {})
    layout = runtime_layout(spec)
    supplied, pinned = runtime.get(layout, {}), runtime.get('Files', {})
    rules = spec['never_ship']
    for path in rules['paths']:
        if path not in supplied:
            raise ReleaseError(f'{path} is not shipped and the packaged dependencies.json does not supply it '
                               f'(runtime.{layout}): installations would lack it. Use an installer that downloads it.')
        digest = pinned.get(supplied[path])
        if digest is None:
            raise ReleaseError(f'dependencies.json maps {path} to {supplied[path]}, which runtime.Files does not pin')
        if digest not in rules['sha256']:
            raise ReleaseError(f'dependencies.json pins {supplied[path]} as {digest}, not the bytes of {path} '
                               '(package.json never_ship sha256)')


def check_documents(spec, version, files):
    """Documents come from packaging/<version>/ (a variant's documents_version, e.g. "public" for packaging/public/; its
    documents component may replace "documents"), or from packaging/<documents_base>/ where the variant names one (none
    does since 1.0.0, when the multi-frame build's README.md and ARCHITECTURE.md replaced packaging/public/'s).
    Returns (documents naming SOURCE.md/.json, documents marked draft)."""
    documents = spec['components'][spec.get('documents_component', 'documents')]['files']
    folders = tuple(f'repo:packaging/{name}/' for name in (version, spec.get('documents_base')) if name)
    wrong = sorted(f'{target} <- {source}' for target, source in documents.items() if not source.startswith(folders))
    if wrong:
        where = ' or '.join(folder.removeprefix('repo:') for folder in folders)
        raise ReleaseError(f'Documents of {version} must come from {where}: ' + ', '.join(wrong))
    texts = {target: files[target][1].read_text() for target in documents}
    naming = sorted(t for t, text in texts.items() if any(name in text for name in SOURCE_OFFER))
    drafts = sorted(t for t, text in texts.items() if DRAFT_MARKER in text)
    return naming, drafts


def ships_public_documents(spec):
    """Whether the package ships the public document set of packaging/public/ (the intel-free-mfg variant, here or in a
    public export): its --archive passes the public gate (public_archive_problems(), write_archives())."""
    return spec.get('documents_version') == PUBLIC_DOCUMENTS


def public_build(spec, named):
    """Whether the package is the public build, which carries PUBLIC_MANIFEST's text: it ships the public documents and
    is assembled in a public export (release/export_tree.py --public) or under a public name (package_naming())."""
    return ships_public_documents(spec) and (named['kind'] == 'public' or is_public_tree())


def chosen_product(names, slug):
    """The product name of names.json "chosen" (release/rename.py chosen_name()) when it is decided and its slug is the
    public package's slug; None otherwise, and then the public manifest keeps [PRODUCT] (which --archive refuses)."""
    if names is None or slug is None:
        return None
    import rename  # local import: the name rules
    if '_by_id' not in names:
        names = dict(names, _by_id={family['id']: family for family in names['families']})
    try:
        choice = rename.chosen_name(names)
    except rename.RenameError as error:
        raise ReleaseError(f'release/names.json "chosen": {error}') from None
    return choice['name'] if choice and choice['slug'] == slug else None


def public_manifest(manifest, version, product=None):
    """package.json's manifest fields with the public build's text (PUBLIC_MANIFEST) in status and profile.research;
    every other field as package.json declares it. Without a product name the status names [PRODUCT]."""
    out = copy.deepcopy(manifest)
    out['status'] = PUBLIC_MANIFEST['status'].format(product=product or PRODUCT, version=version)
    out['profile'] = dict(out['profile'], research=PUBLIC_MANIFEST['profile.research'])
    return out


def public_docs_errors(root=REPO):
    """The errors packaging/public/check_public_docs.py --release reports in root: the public documents and LICENSE the
    package ships, with every placeholder and [DRAFT] marker an error besides what its normal check reports. Runs that
    tool itself (python3 -I), so the gate and the documents' own check cannot drift apart."""
    checker = root / PUBLIC_DOCS_CHECK
    if not checker.is_file():
        return [f'{PUBLIC_DOCS_CHECK} is missing, so the public documents cannot be checked']
    out = subprocess.run([sys.executable, '-I', '-B', str(checker), '--release', '--json'], cwd=root,
                         capture_output=True, text=True, timeout=300)
    try:
        errors = json.loads(out.stdout)['errors']
    except (ValueError, KeyError, TypeError):
        errors = None
    if not isinstance(errors, list) or out.returncode != (1 if errors else 0):
        detail = (out.stderr.strip() or out.stdout.strip())[-300:]
        return [f'{PUBLIC_DOCS_CHECK} --release did not complete (exit status {out.returncode}): {detail}']
    return errors


def placeholder_pattern(root=REPO):
    """check_public_docs.py's PLACEHOLDER pattern ([PRODUCT], [VERSION], [CONTACT], ...), or None without the tool."""
    path = root / PUBLIC_DOCS_CHECK
    if not path.is_file():
        return None
    loader = importlib.util.spec_from_file_location('check_public_docs', path)
    module = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(module)
    return module.PLACEHOLDER


# Fields of a receipt draft (build/…/public-receipt-DRAFT.json style) that a finished receipt no longer has, and the
# tokens of a template still to be filled ([PACKAGE-NAME], [VERSION], ...).
RECEIPT_DRAFT_KEYS = re.compile(r'draft|proposed_\w+|public_delta', re.I)
BRACKET_TOKEN = re.compile(r'\[[A-Z][A-Z0-9 -]*[A-Z0-9]\]')
DRAFT_WORD = re.compile(r'\bDRAFT\b')


def receipt_draft_problems(receipt, text=None):
    """Why a receipt is not finished, [] when it is: a field of a draft ("draft", "proposed_status", any "proposed_*",
    "public_delta", at any depth), a bracketed upper-case token ([PRODUCT], [PACKAGE-NAME], [DRAFT], ...) or the word
    DRAFT in upper case anywhere in its text."""
    text = json.dumps(receipt, ensure_ascii=False) if text is None else text
    keys = set()

    def walk(value, where):
        if isinstance(value, dict):
            for key, item in value.items():
                if RECEIPT_DRAFT_KEYS.fullmatch(str(key)):
                    keys.add(f'{where}{key}')
                walk(item, f'{where}{key}.')
        elif isinstance(value, list):
            for item in value:
                walk(item, where)
    walk(receipt, '')
    problems = []
    if keys:
        problems.append('draft fields ' + ', '.join(sorted(keys)))
    tokens = sorted(set(BRACKET_TOKEN.findall(text)))
    if tokens:
        problems.append('unfilled tokens ' + ', '.join(tokens))
    if DRAFT_WORD.search(BRACKET_TOKEN.sub('', text)):
        problems.append('the word DRAFT')
    return problems


def public_archive_problems(static, receipt_path=None, root=REPO, texts=()):
    """Why the public package may not be archived yet, [] when nothing stops it: the errors of check_public_docs.py
    --release (public_docs_errors()), placeholders or [DRAFT] markers in the manifest's text (static: the manifest
    fields from package.json, public_manifest() applied), in further texts [(label, text)] such as the generated
    SOURCE.md, or in the receipt to be staged, and a receipt that is not finished (receipt_draft_problems())."""
    problems = []
    errors = public_docs_errors(root)
    if errors:
        problems.append(f'{PUBLIC_DOCS_CHECK} --release reports {len(errors)} error(s): ' + '; '.join(errors[:8])
                        + (f' and {len(errors) - 8} more' if len(errors) > 8 else ''))
    texts = [('manifest.json', json.dumps(static, ensure_ascii=False)), *texts]
    if receipt_path is not None and Path(receipt_path).is_file():
        text = Path(receipt_path).read_text(errors='replace')
        texts.append((f'the receipt {Path(receipt_path).name}', text))
        try:
            unfinished = receipt_draft_problems(json.loads(text), text)
        except ValueError:
            unfinished = ['not JSON']
        if unfinished:
            problems.append(f'the receipt {Path(receipt_path).name} is not finished: ' + '; '.join(unfinished))
    return problems + text_problems(texts, root)


def text_problems(texts, root=REPO):
    """[problem] for each (label, text) that carries a placeholder of check_public_docs.py or the [DRAFT] marker."""
    pattern = placeholder_pattern(root)
    problems = []
    for label, text in texts:
        found = sorted({m.group(0) for m in pattern.finditer(text)} if pattern else set())
        found += [DRAFT_MARKER] if DRAFT_MARKER in text else []
        if found:
            undecided = ' (release/names.json "chosen" names no product for this package)' \
                if label == 'manifest.json' and PRODUCT in found else ''
            problems.append(f'{label} still carries {", ".join(found)}{undecided}')
    return problems


def check_version_unused(version, payload, receipt=None):
    """A version number names one build: an earlier receipt of it in evidence/ (receipt: its file name, package_naming();
    default the private xemfg-<version>-package.json) must carry the same payload."""
    earlier = EVIDENCE / (receipt or f'xemfg-{version}-package.json')
    if earlier.is_file() and json.loads(earlier.read_text()).get('payload') != payload:
        shown = earlier.relative_to(REPO) if earlier.is_relative_to(REPO) else earlier
        raise ReleaseError(f'{version} already names a different build ({shown}): '
                           'give this package the next version number (package.json name and documents)')


def check_receipt(receipt, version, name, payload, components):
    if receipt.get('status') != 'pass':
        raise ReleaseError(f'The receipt is not a passed qualification (status {receipt.get("status")!r})')
    if receipt.get('version') != version or receipt.get('package') != name:
        raise ReleaseError(f'The receipt qualifies {receipt.get("package")!r} ({receipt.get("version")!r}), not {name} '
                           f'({version})')
    for label, qualified, assembled in (('payload', receipt.get('payload'), payload),
                                        ('components', receipt.get('components'), components)):
        if not isinstance(qualified, dict):
            raise ReleaseError(f'The receipt has no {label} map')
        if qualified != assembled:
            differing = sorted(k for k in set(qualified) | set(assembled) if qualified.get(k) != assembled.get(k))
            raise ReleaseError(f'The qualified {label} differs from the assembled one: ' + ', '.join(differing[:6]))


def check_no_absolute_paths(value, where):
    if isinstance(value, dict):
        for key, item in value.items():
            check_no_absolute_paths(key, where)
            check_no_absolute_paths(item, where)
    elif isinstance(value, list):
        for item in value:
            check_no_absolute_paths(item, where)
    elif isinstance(value, str) and (value.startswith('/') or ABSOLUTE.search(value) or host_paths.find(value)):
        raise ReleaseError(f'Absolute path in {where}: {value[:120]}')


def recipes_summary(path):
    recipes = json.loads(path.read_text())
    summary = {key: len(recipes[key]) for key in ('verified', 'wiki') if key in recipes}
    for key in ('leave_auto', 'backports'):
        if key in recipes:
            summary[key] = sorted(recipes[key])
    if 'sources' in recipes:
        summary['sources'] = recipes['sources']
    summary['sha256'] = sha256(path)
    return summary


def git_state(paths):
    """(HEAD, sorted paths among the given ones that are modified, staged or untracked); (None, None) without git."""
    if not (REPO / '.git').exists():
        return None, None
    env = dict(os.environ, GIT_OPTIONAL_LOCKS='0')  # read-only: no index refresh

    def git(*arguments):
        out = subprocess.run(['git', '-C', str(REPO), *arguments], capture_output=True, text=True, env=env)
        if out.returncode:
            raise ReleaseError(f'git {arguments[0]} failed: {out.stderr.strip()[-300:]}')
        return out.stdout

    head = git('rev-parse', 'HEAD').strip()
    status = git('status', '--porcelain=v1', '-z', '--untracked-files=all', '--', *sorted(paths)).split('\0')
    dirty, i = set(), 0
    while i < len(status):
        entry = status[i]
        i += 1
        if not entry:
            continue
        dirty.add(entry[3:])
        if entry[0] in 'RC':
            i += 1  # the rename's original path follows
    return head, sorted(dirty)


def integration_json(spec, static, files, digests):
    """integration.json's bytes: install.py's integration_text() (this tree's installer, the one the package ships) for the
    package's name, add-on entry, OptiScaler build, host requirements, dependencies.json and files: the same text
    install.py contract --json prints in the assembled package, whose manifest carries those fields. Generated before the
    receipt, so the receipt's components cover it."""
    loader = importlib.util.spec_from_file_location('freefg_integration_contract', REPO / 'packaging/install.py')
    module = importlib.util.module_from_spec(loader)
    saved = list(sys.path)  # install.py puts its own folder first on sys.path for its sibling modules
    try:
        loader.loader.exec_module(module)
        manifest = dict(name=spec['name'], addon_entry=static.get('addon_entry'), host_requirements=static.get('host_requirements'))
        if 'opti/OptiScaler.dll' in files:
            manifest['optiscaler'] = dict(sha256=digests['opti/OptiScaler.dll'], **static['optiscaler'])
        dependencies = json.loads(files['dependencies.json'][1].read_text()) if 'dependencies.json' in files else {}
        text = module.integration_text(manifest, dependencies, sorted(files))
    finally:
        sys.path[:] = saved
    check_no_absolute_paths(json.loads(text), INTEGRATION)
    return text.encode()


def installer_tests(spec, root=REPO):
    """Run the installer unit tests of package.json in root/scripts (this tree, or an exported one)."""
    for test in spec['installer_tests']:
        out = subprocess.run([sys.executable, '-m', 'unittest', test], cwd=root / 'scripts', capture_output=True, text=True)
        if out.returncode:
            raise ReleaseError(f'Installer test {test} failed in {root}:\n{out.stderr[-3000:]}')


def write_json(path, value):
    check_no_absolute_paths(value, path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def assemble(config, spec, receipt_path=None, companion=True, archive_requested=False):
    name = spec['name']
    named = package_naming(name)
    version = named['version']
    variant = spec.get('variant')
    static = spec['manifest']
    if public_build(spec, named):
        static = public_manifest(static, version, chosen_product(load_names(), named.get('slug')))
    sources = Sources(config)
    files = plan(spec, sources)
    addon_record, _addon, _ = sources.record('addon-' + variant if variant else 'addon')
    layer_record, _layer, _ = sources.record('layer')
    if 'glibc' in layer_record:
        # The oldest glibc the built layer loads on joins the package's host requirements: the manifest and
        # integration.json (install.py contract) state it alike, and doctor.py warns below it.
        static = dict(static, host_requirements={'glibc': layer_record['glibc']['minimum'], **(static.get('host_requirements') or {})})
    if variant:
        check_variant_profile(spec, addon_record)
    check_runtime_supply(spec, files)
    naming_source, drafts = check_documents(spec, spec.get('documents_version', version), files)
    digests = {target: sha256(path) for target, (_component, path) in files.items()}
    payload = {t: d for t, d in digests.items() if t.startswith('payload/')}
    check_version_unused(version, payload, named['receipt'])

    keep = read_keep()
    shipped = {source.removeprefix('repo:') for entry in spec['components'].values() for source in entry['files'].values()
               if source.startswith('repo:')}
    shipped |= set(addon_record['sources']) | set(layer_record['sources']) | set(keep)
    shipped |= {s.removeprefix('repo:') for s in spec['source_companion'].get('files', {}).values()}
    head, dirty = git_state(shipped)

    needs_source = sorted(c for c, entry in spec['components'].items() if entry.get('source_offer'))
    if archive_requested:
        problems = []
        if head is None:
            problems.append('this tree is not a git checkout, so its sources cannot be tied to a commit')
        elif dirty:
            problems.append('shipped files differ from HEAD (commit them first): ' + ', '.join(dirty[:8])
                            + (f' and {len(dirty) - 8} more' if len(dirty) > 8 else ''))
        if needs_source and not companion:
            problems.append(f'{", ".join(needs_source)} require a source offer: build the source companion')
        if drafts:
            problems.append(f'documents still marked {DRAFT_MARKER}: ' + ', '.join(drafts))
        if ships_public_documents(spec):
            problems += public_archive_problems(static, receipt_path)
            pattern = placeholder_pattern()
            if companion and pattern is not None:
                problems += source_companion.route_placeholders(config, pattern, DRAFT_MARKER)
        if problems:
            raise ReleaseError('Not archiving: ' + '; '.join(problems))
    if naming_source and not companion:
        print(f'warning: {", ".join(naming_source)} name SOURCE.md/SOURCE.json, which this package lacks '
              '(--no-source-companion)', file=sys.stderr)

    folder = spec.get('package_dir', 'package')
    out = config.build / folder / name
    out.parent.mkdir(parents=True, exist_ok=True)
    integration = {INTEGRATION: integration_json(spec, static, files, digests)}
    source_record, generated = None, {}
    partial = out.with_name(f'{name}-source.zip.partial')
    if companion:
        source_record = source_companion.build(config, spec, name, keep, partial)
        generated = {'SOURCE.json': (json.dumps(source_record, indent=2) + '\n').encode(),
                     'SOURCE.md': source_companion.source_md(source_record).encode()}
        check_no_absolute_paths(source_record, 'SOURCE.json')
        if archive_requested and ships_public_documents(spec):
            # The gate's text checks (placeholders, [DRAFT]) on what the companion generated.
            late = text_problems([(name, data.decode()) for name, data in sorted(generated.items())])
            if late:
                partial.unlink(missing_ok=True)
                raise ReleaseError('Not archiving: ' + '; '.join(late))
    digests.update({target: hashlib.sha256(data).hexdigest() for target, data in {**generated, **integration}.items()})
    components = {t: d for t, d in sorted(digests.items()) if not t.startswith(('payload/', 'qualification/'))}
    receipt_name = f'qualification/{named["receipt"]}'
    try:
        if receipt_path:
            # Read before the output directory is replaced (the receipt may live inside it).
            receipt_bytes = Path(receipt_path).read_bytes()
            receipt = json.loads(receipt_bytes)
            check_no_absolute_paths(receipt, Path(receipt_path).name)
            check_receipt(receipt, version, name, payload, components)
        else:
            receipt = dict(
                status='pending', version=version, package=name,
                note='Skeleton written by release/assemble.py. Qualification records its results here and sets status '
                     '"pass"; then assemble.py --receipt <this file> --archive stages it and writes the archive.',
                payload=payload, components=components,
                addon=dict(sha256=addon_record['sha256'], profile=static['profile']['name']),
                layer_sha256=layer_record['sha256'],
            )
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    # Everything checked: replace the package and drop archives of any earlier assembly, which could disagree with it.
    for stale in archive_files(out):
        stale.unlink(missing_ok=True)
    if out.exists():
        shutil.rmtree(out)
    if companion:
        target = source_companion.archive_path(config, name, folder)
        partial.rename(target)
        target.with_name(target.name + '.sha256').write_text(f'{source_record["sha256"]}  {target.name}\n')
    out.mkdir(parents=True)
    for target, (_component, path) in files.items():
        (out / target).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out / target)
        if sha256(out / target) != digests[target]:
            raise ReleaseError(f'Copy of {target} differs from its source')
        if target.endswith('.json'):
            check_no_absolute_paths(json.loads((out / target).read_text()), target)
    for target, data in {**generated, **integration}.items():
        (out / target).write_bytes(data)
    if receipt_path:
        (out / receipt_name).parent.mkdir(parents=True, exist_ok=True)
        (out / receipt_name).write_bytes(receipt_bytes)  # verbatim: the shipped receipt hashes like the qualified one
    else:
        write_json(out / receipt_name, receipt)

    installer = spec['components']['installer']['files']
    component_lists = {component: sorted(entry['files']) for component, entry in spec['components'].items()}
    if generated:
        component_lists['source-offer'] = sorted(generated)
    component_lists['integration'] = sorted(integration)
    manifest = dict(
        name=name, runtime=static['runtime'], candidate=receipt['status'] != 'pass', launcher_setup=static['launcher_setup'],
        addon_entry=static.get('addon_entry'), profile=static['profile'], addon_sha256=addon_record['sha256'],
        update_contract=static.get('update_contract'), host_requirements=static.get('host_requirements'),
        default_factor=static['default_factor'], max_factor=static.get('max_factor'), default_cap=static['default_cap'],
        fsr4=static['fsr4'],
        enabler=static['enabler'], status=static['status'], git_head=head,
        git_dirty=dirty,
        # glibc: the oldest glibc the layer loads on (build_layer.py's check; doctor.py warns below it)
        present_pacing=dict(layer_sha256=layer_record['sha256'], build=LAYER_BUILD,
                            **({'glibc': layer_record['glibc']['minimum']} if 'glibc' in layer_record else {})),
        frame_start_pacing=dict(addon_sha256=addon_record['sha256'], **static['frame_start_pacing']),
        installer={target: sha256(out / target) for target in installer},
        enabler_overlay=static['enabler_overlay'], extras=static['extras'],
        optiscaler=dict(sha256=sha256(out / 'opti/OptiScaler.dll'), **static['optiscaler'])
        if 'opti/OptiScaler.dll' in files else None,
        recipes=recipes_summary(out / 'recipes/recipes.json') if 'recipes/recipes.json' in files else None,
        runtime_downloads=static['runtime_downloads'],
        source_archive=source_record,
        components=component_lists,
        builds=dict(addon_matches_reference=addon_record['matches_reference'],
                    layer_matches_reference=layer_record['matches_reference']),
    )
    if any(name.endswith('/freefg-scaling.required') for name in files):
        manifest['generated_frame_scaling'] = dict(modes=['output','scale','limit'],percent=[50,100],limits=[720,1080,1440,2160],downscale=['bilinear','area'],upscale=['bilinear','bicubic','lanczos2','fsr1'],default='output',apply='restart')
    if variant:
        manifest['variant'] = variant
    manifest = {k: v for k, v in manifest.items() if v is not None or k == 'git_dirty'}
    manifest['files'] = {str(p.relative_to(out)): sha256(p) for p in sorted(out.rglob('*')) if p.is_file()}
    write_json(out / 'manifest.json', manifest)
    if variant:
        manifest['intel_free'] = intel_free_check(config, spec, out)
        write_json(out / 'manifest.json', manifest)
    return out, manifest, receipt


def check_variant_profile(spec, record):
    """The variant's profile component ships exactly the profile its add-on build embedded in the binary's manifest."""
    shipped = {Path(t).name for c in spec['components'].values() for t, src in c['files'].items()
               if src.startswith('build:addon-' + spec['variant'] + '-profile/')}
    built = set(record['profile']['file_sha256'])
    if shipped != built:
        raise ReleaseError(f'package.json variant {spec["variant"]} ships profile files {sorted(shipped ^ built)} '
                           'differently from its add-on build (release/intel_free.json)')


def intel_free_check(config, spec, out):
    """release/check_intel_free.py on the assembled package; a failing package is removed again."""
    import check_intel_free
    allowed = spec['allowed_components']
    try:
        report = check_intel_free.check(config, out, tuple(allowed))
    except ReleaseError:
        shutil.rmtree(out)
        raise
    if report['result'] == check_intel_free.FAIL:
        shutil.rmtree(out)
        shown = '; '.join(f'{f["file"]}: {f["check"]}' for f in report['failing'][:6])
        raise ReleaseError(f'The {spec["variant"]} package carries Intel-derived material outside its allowed '
                           f'components ({len(report["failing"])} findings: {shown}); package removed')
    # "pass-with-allowed-components" (intel_free_complete false) when the allowed components carry findings: the
    # package is then not Intel-free as a whole, only outside those components.
    return dict(
        result=report['result'], intel_free_complete=report['intel_free_complete'],
        checked_by='release/check_intel_free.py', constant_scan=report['constant_scan'],
        findings_by_component=report['findings_by_component'],
        allowed_components={c: dict(reason=reason, findings=len([f for f in report['allowed'] if f['component'] == c]))
                            for c, reason in allowed.items()},
        statistics={k: v for k, v in report['statistics'].items() if k != 'bytes'},
    )


def archive(package):
    """<name>.zip beside the package directory (files sorted, paths relative to its parent) and <name>.zip.sha256."""
    target = package.with_name(package.name + '.zip')
    if target.exists():
        target.unlink()
    names = sorted(p for p in package.rglob('*') if p.is_file())
    with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in names:
            z.write(path, str(path.relative_to(package.parent)))
    with zipfile.ZipFile(target) as z:
        if z.testzip():
            raise ReleaseError('CRC failure in the archive')
        if sorted(z.namelist()) != sorted(str(p.relative_to(package.parent)) for p in names):
            raise ReleaseError('Archive contents differ from the package directory')
    digest = sha256(target)
    target.with_name(target.name + '.sha256').write_text(f'{digest}  {target.name}\n')
    return target, digest


def archive_files(package):
    """The archives beside a package directory: <name>.zip, the source companion <name>-source.zip, their .sha256."""
    return [package.with_name(pattern.format(name=package.name)) for pattern in ARCHIVES]


def zip_host_paths(path):
    """Host paths in a written zip (release/host_paths.py in review mode, the way export_tree.py reviews an export):
    [(member, what matched)] over the member names and the text of every member; binary members are not scanned."""
    hits = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            match = host_paths.find(info.filename, review=True)
            if match:
                hits.append((info.filename, f'member name: {match.group(0)}'))
            if not info.is_dir():
                match = host_paths.in_file_bytes(z.read(info), review=True)
                if match:
                    hits.append((info.filename, match.group(0)))
    return hits


def write_archives(package, scan=False):
    """archive() the package directory: (zip, sha256, names of the zips scanned). With scan (a package that ships the
    public documents) both written zips, <name>.zip and the source companion <name>-source.zip, are checked for host
    paths (zip_host_paths()); on a hit both are deleted with their .sha256 files and the archive is refused."""
    target, digest = archive(package)
    scanned, hits = [], {}
    for path in ((target, package.with_name(package.name + '-source.zip')) if scan else ()):
        if path.is_file():
            scanned.append(path.name)
            hits[path.name] = zip_host_paths(path)
    if any(hits.values()):
        removed = [path.name for path in archive_files(package) if path.exists()]
        for path in archive_files(package):
            path.unlink(missing_ok=True)
        shown = '; '.join(f'{name}: {member} ({what})' for name, found in hits.items() for member, what in found[:4])
        count = sum(len(found) for found in hits.values())
        raise ReleaseError(f'Not archiving: {count} host path(s) in the written archives ({shown}); deleted again: '
                           + ', '.join(removed))
    return target, digest, scanned


def compare_payload(payload, reference_path, spec):
    """Differences between the assembled payload and a reference receipt's, ignoring never-ship files."""
    reference = json.loads(Path(reference_path).read_text())['payload']
    rules = spec['never_ship']
    expected = {k: v for k, v in reference.items() if k not in rules['paths'] and v not in rules['sha256']}
    return dict(
        reference=Path(reference_path).name, reference_files=len(reference), compared_files=len(expected),
        assembled_files=len(payload),
        excluded_from_reference=sorted(set(reference) - set(expected)),
        only_in_reference=sorted(set(expected) - set(payload)),
        only_assembled=sorted(set(payload) - set(expected)),
        different=sorted(k for k in set(payload) & set(expected) if payload[k] != expected[k]),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    parser.add_argument('--receipt', type=Path, help='a passed qualification receipt to stage instead of the skeleton')
    parser.add_argument('--archive', action='store_true',
                        help='write <name>.zip and .zip.sha256 (needs --receipt; the public package also passes the '
                             'public gate: check_public_docs.py --release, placeholders in the manifest, SOURCE.md, the '
                             'fork\'s FORK.md and the receipt, a finished receipt, a host-path scan of the text members '
                             'and member names of both zips. Binary members are not scanned: the maintainers archive '
                             'the public package with release/publish_local.py, which also scans their strings)')
    parser.add_argument('--compare-payload', type=Path, metavar='RECEIPT',
                        help='report how the assembled payload differs from a reference receipt '
                             '(e.g. evidence/xemfg-v30-package.json)')
    parser.add_argument('--skip-installer-tests', action='store_true', help='do not run the installer unit tests first')
    parser.add_argument('--no-source-companion', action='store_true',
                        help='skip the source companion (and SOURCE.md/.json); --archive then refuses')
    parser.add_argument('--variant', metavar='NAME',
                        help='assemble a package.json variant (intel-free: the Intel-free add-on and profile)')
    args = parser.parse_args()
    if args.archive and not args.receipt:
        parser.error('--archive needs --receipt: only a qualified package is archived')
    config = Config.from_args(args)
    spec = json.loads(PACKAGE_SPEC.read_text())
    if args.variant:
        spec = apply_variant(spec, args.variant)
    if not args.skip_installer_tests:
        installer_tests(spec)
    out, manifest, receipt = assemble(config, spec, args.receipt, companion=not args.no_source_companion,
                                      archive_requested=args.archive)
    summary = dict(package=str(out.relative_to(config.build)), files=len(manifest['files']) + 1,
                   payload_files=len(receipt['payload']), receipt_status=receipt['status'],
                   manifest_sha256=sha256(out / 'manifest.json'),
                   git_dirty=len(manifest['git_dirty']) if manifest['git_dirty'] is not None else 'no git checkout',
                   components={k: len(v) for k, v in manifest['components'].items()})
    if 'intel_free' in manifest:
        summary['intel_free'] = {k: manifest['intel_free'][k] for k in ('result', 'intel_free_complete',
                                                                          'findings_by_component', 'allowed_components')}
    if 'source_archive' in manifest:
        summary['source_archive'] = {k: manifest['source_archive'][k] for k in ('archive', 'sha256', 'bytes', 'files')}
    if args.compare_payload:
        summary['payload_comparison'] = compare_payload(receipt['payload'], args.compare_payload, spec)
    if args.archive:
        target, digest, scanned = write_archives(out, scan=ships_public_documents(spec))
        summary['archive'] = dict(name=target.name, sha256=digest, bytes=target.stat().st_size)
        if scanned:
            summary['archive']['host_paths'] = dict(scanned=scanned, found=0, binary_members='not scanned (see --help)')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        sys.exit(f'error: {error}')
