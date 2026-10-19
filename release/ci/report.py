#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Compare the CI build outputs with the reference hashes of release/inputs.lock.json "outputs" and summarise them.

  python3 release/ci/report.py [--toolchain pinned|current] [--report FILE]

For each reference output it reads the build record that release/build_*.py wrote under XEMFG_BUILD and reports
"match", "MISMATCH", "not built" or "not buildable here" (the maintainers' BC250-MFG.asi add-on builds need private
work-directory inputs). It also compares the toolchain digests the records hold (system
headers, Wine import libraries) with the lock's, which explain a mismatch. With the pinned toolchain a mismatch or a
missing build fails (exit 1); with the current one it is a warning. The build scripts themselves already fail on a
mismatch unless run with --no-reference-check; this report is the overview for the job summary and the artifact.
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ReleaseError, annotate, build_config, load_lock, sha256, step_summary, write_json  # noqa: E402

# Lock output key -> (build directory, file, toolchain key for the system-header digest), or None when CI cannot build it.
OUTPUTS = {
    'libxess_fg.dll (intel-free-2x)': ('addon-intel-free-2x', 'libxess_fg.dll', 'addon (intel-free-2x)'),
    'libxefg_wave.so': ('layer', 'libxefg_wave.so', 'layer'),
    'BC250-MFG.asi': None,
    'BC250-MFG.asi (intel-free)': None,
}
NOT_BUILDABLE = 'a maintainers\' build that needs private work-directory inputs'


def compare(config):
    lock = load_lock()
    rows, problems = [], []
    for key, reference in lock['outputs'].items():
        where = OUTPUTS.get(key)
        row = dict(output=key, reference=reference)
        if where is None:
            row.update(status='not buildable here', note=NOT_BUILDABLE if key in OUTPUTS else 'unknown output')
            rows.append(row)
            continue
        folder, name, toolchain_key = where
        record_path, binary = config.build / folder / 'build.json', config.build / folder / name
        if not record_path.is_file() or not binary.is_file():
            row.update(status='not built')
            problems.append(f'{key}: not built')
            rows.append(row)
            continue
        record = json.loads(record_path.read_text())
        actual = sha256(binary)
        if actual != record['sha256']:
            raise ReleaseError(f'{binary} differs from its build record')
        locked = lock['toolchain'].get(toolchain_key, {})
        headers_equal = locked.get('system_headers') == record.get('system_headers') if locked.get('system_headers') else None
        libraries = lock['toolchain'].get('addon', {}).get('import_libraries') if 'import_libraries' in record else None
        libraries_equal = libraries == record['import_libraries'] if libraries else None
        row.update(status='match' if actual == reference else 'MISMATCH', sha256=actual,
                   system_headers_equal_lock=headers_equal, import_libraries_equal_lock=libraries_equal,
                   unit_tests=len(record['unit_tests']) if isinstance(record.get('unit_tests'), list) else None,
                   toolchain=record.get('toolchain'))
        if actual != reference:
            problems.append(f'{key}: {actual[:16]}..., reference {reference[:16]}... (system headers equal to the lock: '
                            f'{headers_equal}, import libraries: {libraries_equal})')
        rows.append(row)
    return rows, problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--toolchain', choices=('pinned', 'current'), default=os.environ.get('TOOLCHAIN', 'pinned'))
    parser.add_argument('--report', type=Path, help='also write the comparison as JSON')
    args = parser.parse_args()
    rows, problems = compare(build_config())
    table = '\n'.join(f'| `{r["output"]}` | `{r["reference"][:16]}…` | {r["status"]} | '
                      f'{("`" + r["sha256"][:16] + "…`") if r.get("sha256") else r.get("note", "")} |' for r in rows)
    expectation = ('byte identity expected (pinned toolchain)' if args.toolchain == 'pinned'
                   else 'best effort (current toolchain): a mismatch is a warning')
    step_summary(f'### Reference outputs: {expectation}\n\n| Output | Reference | Status | Built |\n| --- | --- | --- | --- |\n'
                 f'{table}')
    if args.report:
        write_json(args.report, dict(toolchain=args.toolchain, outputs=rows, problems=problems))
    print(json.dumps(dict(toolchain=args.toolchain, outputs=rows, problems=problems), indent=2))
    for problem in problems:
        annotate('error' if args.toolchain == 'pinned' else 'warning', problem, title='reference output')
    if problems and args.toolchain == 'pinned':
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except ReleaseError as error:
        annotate('error', error, title='reference outputs')
        sys.exit(1)
