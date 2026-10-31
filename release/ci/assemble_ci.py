#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Assemble a package variant in CI with release/assemble.py and require a clean Intel-free result.

The package is assembled exactly as `release/assemble.py --variant NAME --no-source-companion` would (the same
functions, run in this process), with one CI difference: a component whose files are private work-directory inputs
that this tree cannot supply is left out, and only the components named in OMITTABLE may be. Today none is: the
OptiScaler fork build is the fetch group "optiscaler-fork" (its public release, by pinned hash), so every component
(installer, documents, add-on, layer, profile, OptiScaler, licences, notices) must assemble. assemble.py then runs release/check_intel_free.py on the package (DXC needed, XEMFG_DXC) and removes
the package when it fails; this script additionally requires the result "pass" with intel_free_complete true and no
allowed component, that the package's add-on is the build output and equals the lock's reference, and that no
shipped file differs from the checked-out commit (manifest git_dirty). --allow-reference-mismatch turns the reference
comparison into a warning; the CI workflow passes it because release/ci/report.py, its last step, is the one place
that decides about hash mismatches (failure with the pinned toolchain, warning with the current one). The source
companion is skipped (it needs the fork's git checkout); nothing is archived.

  python3 release/ci/assemble_ci.py [--variant intel-free-mfg] [--summary FILE] [--allow-reference-mismatch]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RELEASE, ReleaseError, annotate, build_config, sha256, step_summary, write_json  # noqa: E402
import assemble  # noqa: E402  (release/assemble.py, on the path through common)

# Components CI may leave out, and why; any other component with an unavailable input fails the job.
OMITTABLE = {}


def available(config, source):
    """True when a package.json source can be resolved here without the private work directory."""
    scheme, _, rest = source.partition(':')
    if scheme != 'input':
        return True
    group, _, name = rest.partition('/')
    if group in config.lock['fetch']:
        return True
    try:
        config.input_file(group, name)
    except ReleaseError:
        return False
    return True


def ci_spec(config, variant):
    spec = json.loads((RELEASE / 'package.json').read_text())
    if variant:
        spec = assemble.apply_variant(spec, variant)
    omitted = {}
    for component, entry in list(spec['components'].items()):
        missing = sorted(source for source in entry['files'].values() if not available(config, source))
        if not missing:
            continue
        if component not in OMITTABLE:
            raise ReleaseError(f'Component {component} needs inputs this tree cannot supply: {", ".join(missing[:4])}')
        omitted[component] = dict(reason=OMITTABLE[component], files=sorted(entry['files']))
        del spec['components'][component]
    return spec, omitted


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--variant', default='intel-free-mfg', help='package.json variant (default intel-free-mfg)')
    parser.add_argument('--summary', type=Path, help='write the CI summary as JSON')
    parser.add_argument('--allow-reference-mismatch', action='store_true',
                        help='report an add-on that differs from the lock as a warning (unpinned toolchain)')
    args = parser.parse_args()
    config = build_config()
    spec, omitted = ci_spec(config, args.variant)
    out, manifest, receipt = assemble.assemble(config, spec, companion=False)
    check = manifest.get('intel_free')
    problems = []
    if check is None:
        problems.append('the package was not checked by check_intel_free.py (not a variant?)')
    elif check['result'] != 'pass' or not check['intel_free_complete'] or check['allowed_components']:
        problems.append(f'check_intel_free.py result {check["result"]!r} (intel_free_complete '
                        f'{check["intel_free_complete"]}, allowed components {sorted(check["allowed_components"])})')
    addon_kind = 'addon-' + args.variant if args.variant else 'addon'
    record, binary, _ = assemble.Sources(config).record(addon_kind)
    if manifest['addon_sha256'] != sha256(binary):
        problems.append('the packaged add-on is not the current build output')
    elif not record['matches_reference']:
        message = (f'the packaged add-on {manifest["addon_sha256"][:12]}... differs from the reference in '
                   f'inputs.lock.json ({str(record["reference_sha256"])[:12]}...)')
        if args.allow_reference_mismatch:
            annotate('warning', message, title='package assembly')
        else:
            problems.append(message)
    if manifest.get('git_dirty'):
        problems.append('shipped files differ from the checked-out commit: ' + ', '.join(manifest['git_dirty'][:8]))
    summary = dict(
        package=manifest['name'], directory=str(out.relative_to(config.build)), files=len(manifest['files']),
        payload_files=len(receipt['payload']), components={k: len(v) for k, v in manifest['components'].items()},
        omitted_components=omitted, addon_sha256=manifest['addon_sha256'],
        layer_sha256=manifest['present_pacing']['layer_sha256'], git_head=manifest.get('git_head'),
        git_dirty=manifest.get('git_dirty'), intel_free=check, manifest_sha256=sha256(out / 'manifest.json'),
        receipt_status=receipt['status'], problems=problems,
    )
    if args.summary:
        write_json(args.summary, summary)
    step_summary(f'### Package `{manifest["name"]}` (CI assembly)\n\n'
                 f'- {summary["files"]} files, {summary["payload_files"]} in payload/\n'
                 f'- check_intel_free.py: **{check["result"] if check else "not run"}**'
                 f' (intel_free_complete {check["intel_free_complete"] if check else "-"})\n'
                 + ''.join(f'- left out: `{c}` ({o["reason"]})\n' for c, o in omitted.items())
                 + f'- git_dirty: {summary["git_dirty"]}')
    print(json.dumps(summary, indent=2))
    if problems:
        raise ReleaseError('; '.join(problems))


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        annotate('error', error, title='package assembly')
        sys.exit(1)
