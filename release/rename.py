#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Survey and rename the identifiers of the public tree that carry the internal name (release/names.json).

  python3 release/rename.py scan [--root DIR] [--family ID ...] [--class CLASS ...] [--summary] [--json]
  python3 release/rename.py apply --name "Product Name" --slug product-name [--holder TEXT] [--root DIR]
                                  [--include-compat] [--family ID ...] [--no-defaults] [--write [--allow-private-tree]]
                                  [--all-lines] [--json]

The files are those release/keep-public.txt lists in the tree at --root (default: this tree), less names.json
"exclude", and in a public export also the top files export_tree.py writes (README.md, LICENSE, NOTICE.md, .github/);
binary files are skipped. Run it on a public export (release/export_tree.py --public DIR, then --root DIR or
the export's own copy) for the exact public lines: in this tree the C sources are the private versions, with the
research code a public export leaves out.

scan lists every occurrence (file:line) grouped by family. Each family's patterns are tried in names.json order and a
span belongs to the first family that matches it, so an occurrence is listed once; the last family (old-name) catches
whatever still carries the internal name. Files whose own path carries it are listed under "paths".

apply rewrites the selected families with their replacements and is a dry run unless --write is given:
  - by default the user-visible families marked default (the documents' [PRODUCT] placeholder, Setup's window titles,
    the public package name, the User-Agents and the MIT holder line, "<name> contributors" unless --holder);
  - --include-compat adds the compatibility families that need neither an alias nor a rebuild (names.json
    alias_required false, rebuild empty: the layer name, the download cache, the build settings, temporary names);
  - --family ID adds one family by name: a user-visible family that is not a default (launcher-script, licence-file,
    layer-description) or any compatibility family, including those that need a rebuild (apply lists it) or an alias
    (apply says which code must keep reading the old name); --no-defaults leaves out the defaults. Internal and review families are never
    rewritten.
Tracked files whose keep-list entry the rewrite renames are moved with it (extras-hook renames the .hook file).
It refuses a name or slug with one of Intel's, AMD's or NVIDIA's marks as a word of its own (names.json name_rules:
Xe, XeSS, Intel, FSR, DLSS, ...); nominative use in the documents is not affected. --write refuses a tree that has
release/keep.txt (the private tree, whose setup.py and package.json also serve the private builds) unless
--allow-private-tree. Before writing, changed JSON files must parse, changed Python files must compile, the private
package names in release/package.json must be unchanged (the private library owner matches private-test-NN) and the
public variant's new name must not match the owner's pattern; apply also reports whether release/assemble.py accepts
that name, and that the new name is package-name's public_template (today {slug}-0.9.0). rename_texts() is the same
rewrite as a library function (texts in, changed texts out), for a tool that writes the public tree itself:
release/export_tree.py --public applies it to its copies when names.json "chosen" holds the decided name and slug
(chosen_name() reads and checks that block; empty, the export renames nothing).

Exit status: 0, or 1 when a name is refused or a check fails (nothing is written then).
"""
import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
NAMES = HERE / 'names.json'
CLASSES = ('user-visible', 'compat', 'internal', 'review')
FAMILY_KEYS = ('id', 'class', 'current', 'appears_in', 'patterns', 'compatibility', 'rebuild', 'alias_required', 'policy',
               'recommendation')
TEMPLATE_KEYS = {'name', 'slug', 'slug_', 'SLUG', 'holder'}
PACKAGE = 'release/package.json'
CHOSEN_KEYS = ('about', 'name', 'slug', 'holder', 'families')


class RenameError(Exception):
    pass


# ------------------------------------------------------------------------------------------------------------ names.json

def load_names(path=NAMES):
    """names.json, checked: every family has the documented keys, a known class, patterns that compile and templates
    that use only the known fields."""
    names = json.loads(Path(path).read_text(encoding='utf-8'))
    seen = set()
    for family in names['families']:
        missing = [key for key in FAMILY_KEYS if key not in family]
        if missing:
            raise RenameError(f'names.json family {family.get("id")!r} lacks {missing}')
        if family['id'] in seen:
            raise RenameError(f'names.json lists family {family["id"]} twice')
        seen.add(family['id'])
        if family['class'] not in CLASSES:
            raise RenameError(f'names.json family {family["id"]}: unknown class {family["class"]!r}')
        if family['class'] in ('internal', 'review') and family.get('replacements'):
            raise RenameError(f'names.json family {family["id"]}: {family["class"]} families have no replacements')
        if family['class'] == 'compat' and family['alias_required'] and not family.get('alias'):
            raise RenameError(f'names.json family {family["id"]}: alias_required without "alias"')
        try:
            family['_patterns'] = [re.compile(p) for p in family['patterns']]
            for item in family.get('replacements', []):
                item['_pattern'] = re.compile(item['pattern'])
                used = set(re.findall(r'\{(\w+)\}', item['template']))
                if used - TEMPLATE_KEYS:
                    raise RenameError(f'names.json family {family["id"]}: unknown template fields {sorted(used - TEMPLATE_KEYS)}')
        except re.error as error:
            raise RenameError(f'names.json family {family["id"]}: {error}') from None
    names['_by_id'] = {family['id']: family for family in names['families']}
    return names


def scoped(pattern):
    """A pattern with a leading global flag as a scoped group, so that patterns can be joined into one alternation."""
    match = re.match(r'\(\?([aiLmsux]+)\)', pattern)
    return f'(?{match[1]}:{pattern[match.end():]})' if match else f'(?:{pattern})'


# ----------------------------------------------------------------------------------------------------------- the tree

def keep_entries_of(text):
    """The entries of a keep list's text ("#" starts a comment)."""
    return [line.split('#', 1)[0].strip() for line in text.splitlines() if line.split('#', 1)[0].strip()]


def keep_entries(path):
    return keep_entries_of(path.read_text(encoding='utf-8'))


def text_of(data):
    """The text of a file, or None when it is binary (a NUL byte) or not UTF-8."""
    if b'\0' in data:
        return None
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return None


def tree_files(root, names):
    """({relative path: text} of the listed text files, binary or missing entries, excluded entries). In a public tree
    the files export_tree.py writes at the top (names.json public_root_files) count too."""
    listing = root / names['file_list']
    if not listing.is_file():
        raise RenameError(f'{listing} is missing: --root must be this tree or a public export')
    entries = keep_entries(listing)
    if not is_private_tree(root):
        entries += [n for n in names['public_root_files']['files'] if (root / n).is_file() and n not in entries]
    texts, skipped, excluded = {}, [], []
    for name in entries:
        if name in names['exclude']:
            excluded.append(name)
            continue
        path = root / name
        text = text_of(path.read_bytes()) if path.is_file() else None
        if text is None:
            skipped.append(name)
        else:
            texts[name] = text
    return texts, skipped, excluded


def is_private_tree(root):
    return (root / 'release' / 'keep.txt').is_file()


# ---------------------------------------------------------------------------------------------------------------- scan

def scan(root, names, family_ids=None, classes=None):
    """{"families": [{id, class, policy, count, occurrences: [{file, line, text}]}], "paths": [...], ...}."""
    families = names['families']
    unknown = sorted(set(family_ids or ()) - {f['id'] for f in families})
    if unknown:
        raise RenameError(f'Unknown families: {unknown}')
    texts, skipped, excluded = tree_files(root, names)
    quick = re.compile('|'.join(scoped(p) for f in families for p in f['patterns']))
    found = {f['id']: [] for f in families}
    for name, text in sorted(texts.items()):
        for number, line in enumerate(text.splitlines(), 1):
            if not quick.search(line):
                continue
            claimed = []
            for family in families:
                for pattern in family['_patterns']:
                    for match in pattern.finditer(line):
                        span = match.span()
                        if span[0] == span[1] or any(a < span[1] and span[0] < b for a, b in claimed):
                            continue
                        claimed.append(span)
                        found[family['id']].append(dict(file=name, line=number, text=match.group(0)))
    wanted = [f for f in families if (not family_ids or f['id'] in family_ids) and (not classes or f['class'] in classes)]
    paths = sorted(name for name in keep_entries(root / names['file_list'])
                   if re.search(r'(?i)bc250[-_ ]?xem?fg|(?<![a-z])xemfg', name))
    return dict(root=str(root), tree='private' if is_private_tree(root) else 'public', files=len(texts),
                binary_or_missing=skipped, excluded=excluded, paths=paths,
                families=[dict(id=f['id'], **{'class': f['class']}, policy=f['policy'], count=len(found[f['id']]),
                               occurrences=found[f['id']]) for f in wanted])


def print_scan(result, summary=False):
    note = ' (private tree: its C sources are the private versions; scan a public export for the public lines)' \
        if result['tree'] == 'private' else ''
    print(f'scan of {result["root"]}: {result["files"]} text files{note}')
    if result['excluded']:
        print('excluded (names.json "exclude"): ' + ', '.join(result['excluded']))
    width = max(len(f['id']) for f in result['families'])
    policy = max(len(f['policy']) for f in result['families'])
    for family in result['families']:
        print(('' if summary else '\n') +
              f'{family["id"]:<{width}}  {family["class"]:<12}  {family["policy"]:<{policy}}  {family["count"]:>5}')
        if not summary:
            for item in family['occurrences']:
                print(f'  {item["file"]}:{item["line"]}: {item["text"]}')
    if result['paths']:
        print('\npaths that carry the internal name (a text rename does not move files):')
        for path in result['paths']:
            print('  ' + path)


# --------------------------------------------------------------------------------------------------------------- names

def words(text):
    """The words of a name: split at non-alphanumerics, camel-case boundaries and digits, lower case."""
    out = []
    for chunk in re.split(r'[^A-Za-z0-9]+', text):
        out += re.findall(r'[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+', chunk)
    return [w.lower() for w in out]


def check_name(name, slug, names):
    """Warnings for a usable name and slug; RenameError for one that is refused."""
    rules = names['name_rules']
    if not re.fullmatch(rules['name'], name or ''):
        raise RenameError(f'--name {name!r}: 2 to 40 letters, digits, spaces, dots or hyphens, starting and ending '
                          'with a letter or digit')
    if not re.fullmatch(rules['slug'], slug or ''):
        raise RenameError(f'--slug {slug!r}: 2 to 40 lower-case letters, digits or hyphens, starting and ending with a '
                          'letter or digit')
    refused = set(rules['refused_words'])
    warnings = []
    for label, value in (('--name', name), ('--slug', slug)):
        chunks = [c.lower() for c in re.split(r'[^A-Za-z0-9]+', value) if c]
        hits = sorted({w for w in words(value) if w in refused} | {c for c in chunks if c in refused})
        if hits:
            raise RenameError(f'{label} {value!r}: carries a mark of Intel, AMD or NVIDIA as a word of its own '
                              f'({", ".join(hits)}); nominative use belongs in the documents, not in the name')
        inside = sorted({mark for chunk in chunks for mark in refused
                         if (chunk.startswith(mark) if len(mark) < 3 else mark in chunk)})
        if inside:
            warnings.append(f'{label} {value!r}: contains {", ".join(inside)} inside a word; check that it does not '
                            'read as the mark')
    for pattern, why in rules.get('warned_patterns', {}).items():
        if re.search(pattern, name) or re.search(pattern, slug):
            warnings.append(f'{name!r} / {slug!r}: {why}')
    return warnings


def check_holder(holder):
    """A copyright holder for the MIT line: a name, optionally with an address ("Jane Doe <jane@example.org>")."""
    if not re.fullmatch(r"[^\W_][\w .,'&()@<>+-]{0,78}[\w.)>]", holder or ''):
        raise RenameError(f'--holder {holder!r}: 2 to 80 letters, digits, spaces and . , \' & ( ) @ < > + -')


def template_fields(name, slug, holder=None):
    return dict(name=name, slug=slug, slug_=slug.replace('-', '_'), SLUG=slug.replace('-', '_').upper(),
                holder=holder or f'{name} contributors')


def chosen_name(names):
    """The public name names.json "chosen" declares: None while none is decided (name and slug null or empty), else
    dict(name, slug, holder (None: '<name> contributors'), families (user-visible families besides the defaults),
    warnings). Checked like apply's arguments; RenameError for a half-filled block, a refused name or holder, an
    unknown key, or a family that is not user-visible (the export never rewrites compatibility families)."""
    block = names.get('chosen') or {}
    if not isinstance(block, dict):
        raise RenameError('names.json "chosen" must be an object')
    unknown = sorted(set(block) - set(CHOSEN_KEYS))
    if unknown:
        raise RenameError(f'names.json "chosen" has unknown keys {unknown} (known: {", ".join(CHOSEN_KEYS)})')
    name, slug, holder = (block.get(key) or None for key in ('name', 'slug', 'holder'))
    if not all(value is None or isinstance(value, str) for value in (name, slug, holder)):
        raise RenameError('names.json "chosen" name, slug and holder must be text or null')
    families = block.get('families') or []
    if not isinstance(families, list) or not all(isinstance(f, str) for f in families):
        raise RenameError('names.json "chosen" families must be a list of family ids')
    if name is None and slug is None:
        if holder is not None or families:
            raise RenameError('names.json "chosen" names a holder or families but no name and slug')
        return None
    if name is None or slug is None:
        raise RenameError('names.json "chosen" needs both name and slug (or neither, while the name is undecided)')
    warnings = check_name(name, slug, names)
    if holder is not None:
        check_holder(holder)
    by_id = names['_by_id']
    for family_id in families:
        if family_id not in by_id:
            raise RenameError(f'names.json "chosen" families: unknown family {family_id!r}')
        if by_id[family_id]['class'] != 'user-visible':
            raise RenameError(f'names.json "chosen" families: {family_id} is {by_id[family_id]["class"]}; the export '
                              'rewrites user-visible families only (compatibility families: rename.py apply in an '
                              'export)')
    return dict(name=name, slug=slug, holder=holder, families=list(families), warnings=warnings)


def public_package_name(names, fields, number):
    """The public package name package-name's public_template gives for the private build number."""
    return names['_by_id']['package-name']['public_template'].format(number=number, **fields)


# --------------------------------------------------------------------------------------------------------------- apply

def select(names, include_compat=False, family_ids=(), defaults=True):
    """(families to rewrite, in names.json order; warnings)."""
    by_id = names['_by_id']
    unknown = sorted(set(family_ids) - set(by_id))
    if unknown:
        raise RenameError(f'Unknown families: {unknown}')
    for family_id in family_ids:
        if by_id[family_id]['class'] in ('internal', 'review'):
            raise RenameError(f'{family_id} (class {by_id[family_id]["class"]}): apply never rewrites it '
                              f'({by_id[family_id]["recommendation"]})')
    chosen, warnings = [], []
    for family in names['families']:
        if family['id'] in family_ids:
            chosen.append(family)
            if family['class'] == 'compat' and family['alias_required']:
                warnings.append(f'{family["id"]}: earlier installations need the old name; before this ships: '
                                f'{family["alias"]}')
        elif family['class'] == 'user-visible' and family.get('default') and defaults:
            chosen.append(family)
        elif family['class'] == 'compat' and include_compat and not family['alias_required'] and not family['rebuild']:
            chosen.append(family)
    return chosen, warnings


def rewrite(texts, families, fields):
    """({file: new text}, {family id: {file: replacements}})."""
    changed, counts = {}, {f['id']: {} for f in families}
    for name, text in texts.items():
        new = text
        for family in families:
            for item in family.get('replacements', []):
                if item.get('files') and not any(fnmatch.fnmatchcase(name, glob) for glob in item['files']):
                    continue
                new, count = item['_pattern'].subn(item['template'].format(**fields), new)
                if count:
                    counts[family['id']][name] = counts[family['id']].get(name, 0) + count
        if new != text:
            if len(new.splitlines()) != len(text.splitlines()):
                raise RenameError(f'{name}: a replacement changed the number of lines')
            changed[name] = new
    return changed, counts


def changed_lines(old, new):
    return [(number, a, b) for number, (a, b) in enumerate(zip(old.splitlines(), new.splitlines()), 1) if a != b]


def package_names(spec):
    return dict([('', spec.get('name'))] + [(k, v.get('name')) for k, v in spec.get('variants', {}).items()])


def check_result(texts, changed, names):
    """Problems of the rewritten tree (JSON that no longer parses, Python that no longer compiles, a private package
    name that changed or a public name the library owner would take); and the new public package name."""
    problems, public_name = [], None
    for name, text in changed.items():
        if name.endswith('.json'):
            try:
                json.loads(text)
            except ValueError as error:
                problems.append(f'{name}: no longer JSON ({error})')
        elif name.endswith('.py'):
            try:
                compile(text, name, 'exec')
            except SyntaxError as error:
                problems.append(f'{name}: no longer compiles ({error})')
    if PACKAGE in texts and not any(p.startswith(PACKAGE) for p in problems):
        old_spec = json.loads(texts[PACKAGE])
        before, after = package_names(old_spec), package_names(json.loads(changed.get(PACKAGE, texts[PACKAGE])))
        owner = re.compile(names['library_owner']['pattern'])
        public = names['public_variant']
        # A public tree's package.json (export_tree.py --public) declares the public package at the top level too.
        public_keys = {public} | ({''} if old_spec.get('variant') == public else set())
        for key, value in before.items():
            if key not in public_keys and after.get(key) != value:
                problems.append(f'{PACKAGE}: private package name {value!r} changed to {after.get(key)!r}')
        public_names = {key: after[key] for key in public_keys if after.get(key)}
        if len(set(public_names.values())) > 1:
            problems.append(f'{PACKAGE}: the public package names differ: {sorted(set(public_names.values()))}')
        for key, value in sorted(public_names.items()):
            if value != before.get(key) and owner.search(value):
                problems.append(f'{PACKAGE}: the public name {value!r} matches the library owner\'s pattern')
        public_name = after.get(public)
    return problems, public_name


def assemble_accepts(root, package_name):
    """Whether release/assemble.py in root accepts the package name (version_of), or None without assemble.py."""
    if not (root / 'release' / 'assemble.py').is_file():
        return None, 'no release/assemble.py in this tree'
    code = 'import sys; sys.path.insert(0, "release"); import assemble; print(assemble.version_of(sys.argv[1]))'
    out = subprocess.run([sys.executable, '-I', '-B', '-c', code, package_name], cwd=root, capture_output=True,
                         text=True, timeout=60)
    lines = (out.stdout if out.returncode == 0 else out.stderr).strip().splitlines()
    return out.returncode == 0, lines[-1] if lines else ''


def plan(texts, names, name, slug, holder=None, include_compat=False, family_ids=(), defaults=True):
    """The rewrite of texts ({tree path: text}): a dict with the selected families, the changed texts, the replacement
    counts, the tracked files whose keep-list entry the rewrite renames, the checks' problems, the public package name
    and warnings. Raises RenameError for a refused name or selection."""
    warnings = check_name(name, slug, names)
    if holder is not None:
        check_holder(holder)
    families, notes = select(names, include_compat, family_ids, defaults)
    fields = template_fields(name, slug, holder)
    changed, counts = rewrite(texts, families, fields)
    problems, public_name = check_result(texts, changed, names)
    if counts.get('package-name', {}).get(PACKAGE) and PACKAGE in changed and not problems:
        # The rewritten public name must be the one package-name's public_template names (release/assemble.py parses
        # public names by that template).
        old = package_names(json.loads(texts[PACKAGE])).get(names['public_variant']) or ''
        number = re.search(r'private-test-(\d+)', old)
        expected = public_package_name(names, fields, number[1]) if number else None
        if public_name != expected:
            problems.append(f'{PACKAGE}: the public name {public_name!r} is not package-name public_template '
                            f'({expected!r}); change the package-name replacement with the template')
    listing = names['file_list']
    moves = {}
    if listing in changed:
        old, new = keep_entries_of(texts[listing]), keep_entries_of(changed[listing])
        if len(old) != len(new):
            problems.append(f'{listing}: the rewrite changed the number of entries')
        else:
            moves = {a: b for a, b in zip(old, new) if a != b}
    for family in families:
        if not counts[family['id']]:
            warnings.append(f'{family["id"]}: nothing to rewrite (already renamed, or its patterns no longer match this '
                            'tree)')
    return dict(families=families, changed=changed, counts=counts, moves=moves, problems=problems,
                public_name=public_name, warnings=warnings + notes)


def rename_texts(texts, name, slug, holder=None, include_compat=False, family_ids=(), defaults=True, names=None):
    """The library form of apply, for a tool that writes the public tree itself (release/export_tree.py --public
    renames its copies with it when names.json "chosen" names the public name): ({tree path: new text} of the texts
    that change, {old path: new path} of the files the keep list now names differently, warnings). Raises RenameError
    for a refused name or a result that fails the checks."""
    result = plan(texts, names or load_names(), name, slug, holder, include_compat, family_ids, defaults)
    if result['problems']:
        raise RenameError('; '.join(result['problems']))
    return result['changed'], result['moves'], result['warnings']


def apply(root, names, name, slug, include_compat=False, family_ids=(), defaults=True, write=False,
          allow_private_tree=False, holder=None):
    """The planned (or, with write, written) rewrite of the tree at root as a report; RenameError when refused (then
    nothing is written)."""
    if write and is_private_tree(root) and not allow_private_tree:
        raise RenameError(f'{root} is the private tree (it has release/keep.txt): its setup.py and package.json also '
                          'serve the private builds. Apply in a public export, or pass --allow-private-tree.')
    texts, _skipped, _excluded = tree_files(root, names)
    result = plan(texts, names, name, slug, holder, include_compat, family_ids, defaults)
    families, changed, counts, moves = result['families'], result['changed'], result['counts'], result['moves']
    problems, public_name = result['problems'], result['public_name']
    for old, new in moves.items():
        if not (root / old).is_file():
            problems.append(f'{old}: the keep list names it but it is not a file')
        elif (root / new).exists():
            problems.append(f'{new}: exists already (the rewrite would move {old} there)')
    follow_ups = []
    for family in families:
        if family['rebuild'] and counts[family['id']]:
            follow_ups.append(f'{family["id"]}: rebuild {", ".join(family["rebuild"])}, record the new reference hashes '
                              'and qualify the new build')
    accepted = None
    if public_name and counts.get('package-name'):
        accepted, detail = assemble_accepts(root, public_name)
        if accepted is False:
            follow_ups.append(f'package-name: release/assemble.py does not accept {public_name!r} ({detail}); '
                              'its package_naming() parses public names by names.json package-name public_template')
    if problems:
        raise RenameError('Not applying: ' + '; '.join(problems))
    if write:
        for file, text in changed.items():
            (root / file).write_text(text, encoding='utf-8')
        for old, new in moves.items():
            (root / new).parent.mkdir(parents=True, exist_ok=True)
            (root / old).rename(root / new)
    return dict(root=str(root), name=name, slug=slug, written=bool(write and (changed or moves)),
                families={f['id']: dict(replacements=sum(counts[f['id']].values()), files=counts[f['id']])
                          for f in families},
                changes=[dict(file=file, line=n, old=a, new=b) for file in sorted(changed)
                         for n, a, b in changed_lines(texts[file], changed[file])],
                moves=moves, public_package_name=public_name, assemble_accepts_public_name=accepted,
                warnings=result['warnings'], follow_ups=follow_ups)


def print_apply(result, limit):
    mode = 'written' if result['written'] else 'dry run, nothing written (--write applies it)'
    print(f'apply to {result["root"]}: name {result["name"]!r}, slug {result["slug"]!r} ({mode})')
    for family, entry in result['families'].items():
        print(f'  {family}: {entry["replacements"]} replacements in {len(entry["files"])} files')
    shown = result['changes'] if limit is None else result['changes'][:limit]
    for change in shown:
        print(f'\n{change["file"]}:{change["line"]}\n  - {change["old"].strip()}\n  + {change["new"].strip()}')
    if len(shown) < len(result['changes']):
        print(f'\n… {len(result["changes"]) - len(shown)} more changed lines (--all-lines lists every one)')
    for old, new in result['moves'].items():
        print(f'\nmove {old} -> {new}')
    if result['public_package_name']:
        print(f'\npublic package name: {result["public_package_name"]} (assemble.py accepts it: '
              f'{result["assemble_accepts_public_name"]})')
    for line in result['warnings']:
        print('WARN  ' + line)
    for line in result['follow_ups']:
        print('TODO  ' + line)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('scan', 'apply'):
        sub = commands.add_parser(command)
        sub.add_argument('--root', type=Path, default=REPO, help='the tree (default: this one; a public export)')
        sub.add_argument('--names', type=Path, default=NAMES, help=argparse.SUPPRESS)
        sub.add_argument('--family', action='append', default=[], metavar='ID',
                         help='scan: only this family; apply: also rewrite this family')
        sub.add_argument('--json', action='store_true', help='print the result as JSON')
        if command == 'scan':
            sub.add_argument('--class', dest='classes', action='append', choices=CLASSES, help='only this class')
            sub.add_argument('--summary', action='store_true', help='counts only')
        else:
            sub.add_argument('--name', required=True, help='the product name (documents, Setup, licence)')
            sub.add_argument('--slug', required=True, help='its lower-case, hyphenated form (package, User-Agent, files)')
            sub.add_argument('--holder', help='the MIT copyright holder (default: "<name> contributors")')
            sub.add_argument('--include-compat', action='store_true',
                             help='also rewrite the compatibility families that need neither an alias nor a rebuild')
            sub.add_argument('--no-defaults', action='store_true', help='only the families named with --family')
            sub.add_argument('--write', action='store_true', help='write the changes (default: dry run)')
            sub.add_argument('--allow-private-tree', action='store_true', help='allow --write in a tree with keep.txt')
            sub.add_argument('--all-lines', action='store_true', help='list every changed line')
    args = parser.parse_args(argv)
    try:
        names = load_names(args.names)
        root = args.root.resolve()
        if args.command == 'scan':
            result = scan(root, names, args.family, args.classes)
        else:
            result = apply(root, names, args.name, args.slug, args.include_compat, args.family, not args.no_defaults,
                           args.write, args.allow_private_tree, args.holder)
        if args.json:
            print(json.dumps(result, indent=1, ensure_ascii=False))
        elif args.command == 'scan':
            print_scan(result, args.summary)
        else:
            print_apply(result, None if args.all_lines else 40)
    except RenameError as error:
        print(f'error: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
