#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check the public document set in packaging/public/ against the tree it describes. Reads only; changes nothing.

Errors (exit status 1):
  - a host-specific path (a home directory, a removable-media mount, the host's administration repository);
  - the old internal product name, or with --name a candidate name that carries Intel's Xe mark;
  - PRIVACY.md's download table differs from packaging/dependencies.json "inputs" (URL, SHA-256 or size);
  - BUILDING.md lacks a fetch group or commit of release/inputs.lock.json, or a released output's reference hash;
  - MEASUREMENTS.md lacks the measured binaries' reference hashes;
  - a relative link to a missing document or to a heading that does not exist;
  - with --release: any [DRAFT] marker or placeholder ([PRODUCT], [VERSION], [PENDING-…], …), also in LICENSE
    ([COPYRIGHT HOLDER]).
Warnings: placeholders and [DRAFT] markers (without --release); licence files the intel-free-2x package ships for code
this build does not compile in, or that NOTICE.md does not describe; identifiers that still carry the internal name and
must follow the rename.

  python3 packaging/public/check_public_docs.py [--release] [--name CANDIDATE] [--json]
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DOCS = sorted(HERE.glob('*.md'))
VARIANT = 'intel-free-2x'
RELEASED_OUTPUTS = ('libxess_fg.dll (intel-free-2x)', 'libxefg_wave.so')
# Written in pieces so that this file does not match its own patterns.
HOST_PATHS = [re.compile(p) for p in (r'/' + r'home/[A-Za-z0-9_.-]+', r'/var' + r'/home/', r'/run' + r'/media/',
                                       r'bc250' + r'-admin', r'~' + r'/bc250' + r'-', r'Steam' + r'Roms')]
# The old name as a word on its own (a product name); inside identifiers such as bc250-xemfg-… it is a rename item.
OLD_NAMES = re.compile(r'(?<![\w-])' + 'Xe' + r'MFG(?![\w-])', re.I)
PLACEHOLDER = re.compile(r'\[(PRODUCT|VERSION|REPO-URL|RELEASE-DATE|SECURITY-CONTACT|CONTACT|COPYRIGHT HOLDER|'
                         r'OPTISCALER-FORK-[A-Z-]+|PENDING-[A-Z-]+)\]')
# This project's licence text (shipped as licenses/BC250-XeFG.txt, the public repository's LICENSE): placeholders only.
LICENSE = HERE / 'LICENSE'
RENAME = re.compile(r'BC250-XeFG|BC250_XEFG_\w*|bc250_xefg_original|bc250-xefg[\w-]*|bc250-xe' + r'mfg[\w-]*|BC250-MFG\.log|'
                    r'Start-BC250-XeFG\.sh')
# Licence texts that only code outside this build needs: the proxy links no MinHook and compiles no FSR1 filter.
NOT_COMPILED = {'licenses/MinHook.txt': 'MinHook (the proxy installs no hooks)',
                'licenses/AMD-FSR1.txt': 'FSR1 EASU (the Intel-free builds have no generated-frame scaling)'}


def slug(heading):
    """GitHub's anchor for a Markdown heading."""
    text = re.sub(r'[`*_\[\]()]', '', heading.strip().lower())
    return re.sub(r'\s', '-', re.sub(r'[^\w\- ]', '', text))


def headings(text):
    return {slug(m[1]) for m in re.finditer(r'^#{1,6}\s+(.*)$', text, re.M)}


def package_files():
    """{package path: source} of the intel-free-2x package as release/package.json declares it."""
    package = json.loads((REPO / 'release/package.json').read_text())
    variant = package['variants'][VARIANT]
    components = dict(package['components'])
    for old, new in variant.get('replace', {}).items():
        components.pop(old, None)
        if new:
            components[new] = variant['components'][new]
    for name, component in variant.get('components', {}).items():
        components.setdefault(name, component)
    return {path: source for component in components.values() for path, source in component.get('files', {}).items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--release', action='store_true', help='placeholders and [DRAFT] markers are errors')
    parser.add_argument('--name', help='candidate product name to check for Intel\'s Xe mark')
    parser.add_argument('--json', action='store_true', help='print the result as JSON')
    args = parser.parse_args()
    errors, warnings, info = [], [], {}
    texts = {doc.name: doc.read_text(encoding='utf-8') for doc in DOCS}

    for name, text in texts.items():
        for number, line in enumerate(text.splitlines(), 1):
            for pattern in HOST_PATHS:
                if pattern.search(line):
                    errors.append(f'{name}:{number}: host-specific path ({pattern.pattern})')
            if OLD_NAMES.search(line):
                errors.append(f'{name}:{number}: old internal product name')
        found = PLACEHOLDER.findall(text)
        if found:
            counts = {f'[{p}]': found.count(p) for p in sorted(set(found))}
            info.setdefault('placeholders', {})[name] = counts
            (errors if args.release else warnings).append(f'{name}: placeholders {counts}')
        if '[DRAFT]' in text:
            (errors if args.release else warnings).append(f'{name}: [DRAFT] marker')
        renamed = sorted(set(RENAME.findall(text)))
        if renamed:
            info.setdefault('rename_dependent', {})[name] = renamed
        for target, anchor in re.findall(r'\]\((?!https?:|mailto:)([^)#\s]*)(?:#([^)\s]+))?\)', text):
            document = target or name
            if target and not (HERE / target).is_file():
                errors.append(f'{name}: link to missing {target}')
            elif anchor and document in texts and anchor not in headings(texts[document]):
                errors.append(f'{name}: link to missing heading {document}#{anchor}')

    if LICENSE.is_file():
        found = PLACEHOLDER.findall(LICENSE.read_text(encoding='utf-8'))
        if found:
            counts = {f'[{p}]': found.count(p) for p in sorted(set(found))}
            info.setdefault('placeholders', {})[LICENSE.name] = counts
            (errors if args.release else warnings).append(f'{LICENSE.name}: placeholders {counts}')
    else:
        errors.append(f'{LICENSE.name} is missing (this project\'s licence text)')

    if args.name:
        if re.search(r'(?i)(^|[^a-z])xe', args.name) or re.search(r'(?i)xess|xefg|xell', args.name):
            errors.append(f'--name {args.name!r}: carries Intel\'s Xe mark')
        elif 'xe' in args.name.lower():
            warnings.append(f'--name {args.name!r}: contains "xe" inside a word; check that it does not read as Xe')

    # PRIVACY.md download table against the installer's pins.
    pins = json.loads((REPO / 'packaging/dependencies.json').read_text())['inputs']
    privacy = texts.get('PRIVACY.md', '')
    rows = [line for line in privacy.splitlines() if line.startswith('|') and 'https://' in line]
    listed = {url for line in rows for url in re.findall(r'https://[^\s|)]+', line)}
    for key, item in pins.items():
        row = next((line for line in rows if item['url'] in line.split('|')[3]), None)
        if row is None:
            errors.append(f'PRIVACY.md: dependencies.json input {key} ({item["url"]}) is not in the download table')
            continue
        if item['sha256'] not in row:
            errors.append(f'PRIVACY.md: {key}: SHA-256 differs from dependencies.json')
        if 'size' in item and f'{item["size"]:,}' not in row:
            errors.append(f'PRIVACY.md: {key}: size differs from dependencies.json ({item["size"]:,})')
    for url in sorted(listed - {item['url'] for item in pins.values()}):
        errors.append(f'PRIVACY.md: {url} is in the download table but not in dependencies.json')
    info['privacy_inputs'] = len(pins)

    # BUILDING.md and MEASUREMENTS.md against the build lock.
    lock = json.loads((REPO / 'release/inputs.lock.json').read_text())
    building = texts.get('BUILDING.md', '')
    for group, entry in lock['fetch'].items():
        if f'`{group}`' not in building or entry['commit'] not in building:
            errors.append(f'BUILDING.md: fetch group {group} at {entry["commit"]} is not listed')
    for output in RELEASED_OUTPUTS:
        digest = lock['outputs'].get(output)
        for name in ('BUILDING.md', 'MEASUREMENTS.md'):
            if digest and digest not in texts.get(name, ''):
                errors.append(f'{name}: reference hash of {output} ({digest[:16]}…) is missing')

    # Licence texts of the intel-free-2x package against NOTICE.md and this build.
    notice = texts.get('NOTICE.md', '')
    shipped = sorted(p for p in package_files() if p.startswith('licenses/'))
    for path in shipped:
        if path in NOT_COMPILED:
            warnings.append(f'package.json ships {path}, but this build does not compile in {NOT_COMPILED[path]}')
        elif Path(path).name not in notice and not any(part + '/' in notice for part in Path(path).parent.parts[1:]):
            warnings.append(f'NOTICE.md does not describe shipped {path}')
    info['shipped_licence_files'] = shipped

    result = {'errors': errors, 'warnings': warnings, 'info': info}
    if args.json:
        print(json.dumps(result, indent=1))
    else:
        for line in errors:
            print('ERROR ' + line)
        for line in warnings:
            print('WARN  ' + line)
        for name, found in info.get('rename_dependent', {}).items():
            print(f'INFO  {name}: identifiers to follow the rename: {", ".join(found)}')
        print(f'{len(DOCS)} documents, {len(errors)} errors, {len(warnings)} warnings')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
