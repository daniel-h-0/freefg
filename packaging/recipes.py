# SPDX-License-Identifier: MIT
"""Per-game recipes (recipes/recipes.json; rules in the source tree's research/recipes/RULES.md).

A recipe is matched by launcher ID (Steam AppID, GOG/Epic app name), or by executable name together with the game's
title or folder. Only recipes verified on a BC-250 are applied: their OptiScaler keys (only where the INI still says
auto), frame-generation input, game-setting edits for the recipe's route (each key's original recorded, so Restore
undoes them even in a file the game rewrote since) and DX12 launch arguments. OptiScaler's own per-game quirks keep
working because keys they set are left at auto. OptiScaler wiki reports add DX12 launch arguments; everything
else from the wiki is shown as suggestions with the page link.
"""
import hashlib, html, json, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
FILE = HERE / 'recipes/recipes.json'
FG_SECTIONS = {'framegen', 'optifg', 'fsrfg', 'xefg', 'dlssg', 'fsrfginputs', 'nvngxfg'}
INPUT_NAMES = {'upscaler': 'OptiFG (upscaler input)', 'dlssg': 'DLSS FG', 'fsrfg': 'FSR 3.1 FG', 'fsrfg30': 'FSR 3.0 FG',
               'nukems': "Nukem's dlssg-to-fsr3", 'native-xefg': 'native XeSS FG', 'native-fsrfg': "the game's own FSR FG",
               'fsrfg30-native': "the game's FSR 3.0 FG"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load(path=FILE):
    """The recipe file, or None. Either form works: the full provenance file (research/recipes/build_recipes.py) or
    the compact runtime file built from it, whose wiki page links are relative to its wiki_url and which lists each
    OptiScaler.ini's keys once (optiscaler_ini_keys, by the INI's digest)."""
    if not Path(path).is_file():
        return None
    data = json.loads(Path(path).read_text())
    base = data.get('wiki_url')
    if base:
        for entry in data.get('wiki', []):
            if 'pages' in entry:
                entry['pages'] = [page if '://' in page else base + page for page in entry['pages']]
    keys = data.pop('optiscaler_ini_keys', {})
    for build in data.get('optiscaler_builds', {}).values():
        if 'keys' not in build and build.get('ini_sha256') in keys:
            build['keys'] = list(keys[build['ini_sha256']])
    return data


# Store editions of the same game: "Crimson Desert Enhanced", "The Witcher 3: Wild Hunt - Game of the Year Edition".
EDITION = re.compile(r'(\s+(game of the year|goty|enhanced|definitive|complete|deluxe|gold|ultimate|anniversary|remastered|'
                     r'directors cut|standard|premium)(\s+edition)?)+$')


def norm(title):
    t = re.sub(r'\([^)]*\)', '', title.lower()).replace('&', 'and').replace('’', "'").replace('‐', '-')
    t = re.sub(r"[^a-z0-9]+", ' ', t.replace("'", '')).strip()
    t = re.sub(r'\bii\b', '2', t)
    t = re.sub(r'\biii\b', '3', t)
    return EDITION.sub('', t).strip()


def _steam_manifest(exe):
    """The appmanifest of the Steam library folder holding exe: (appid, name) or None."""
    for parent in exe.parents:
        if parent.name == 'common' and parent.parent.name.lower() == 'steamapps':
            folder = exe.relative_to(parent).parts[0]
            for manifest in parent.parent.glob('appmanifest_*.acf'):
                text = manifest.read_text(errors='replace')
                installdir = re.search(r'"installdir"\s+"([^"]*)"', text)
                if installdir and installdir[1].lower() == folder.lower():
                    appid, name = re.search(r'"appid"\s+"(\d+)"', text), re.search(r'"name"\s+"([^"]*)"', text)
                    return (appid[1] if appid else None, name[1] if name else None)
    return None


def identity(exe, launchers=(), home=None):
    """What the game is called: exe name, launcher IDs and titles."""
    exe = Path(exe)
    ids = dict(exe=exe.name.lower(), steam=set(), gog=set(), epic=set(), titles=set(), folders=set())
    manifest = _steam_manifest(exe.resolve())
    if manifest:
        if manifest[0]:
            ids['steam'].add(manifest[0])
        if manifest[1]:
            ids['titles'].add(norm(manifest[1]))
    for target in launchers:
        if target.get('launcher') == 'steam' and target.get('format') != 'shortcuts' and target.get('id'):
            ids['steam'].add(target['id'])
        elif target.get('launcher') == 'heroic' and target.get('id'):
            # GOG ids are numeric; Legendary (Epic) app names are not.
            (ids['gog'] if str(target['id']).isdecimal() else ids['epic']).add(str(target['id']))
    # The game's own folders (<Game>/<Project>/Binaries/Win64): with no launcher ID they confirm an exe-name match.
    ids['folders'] = {norm(p.name) for p in list(exe.resolve().parents)[:4]} - {''}
    home = Path(home or Path.home())
    for index in (home/'.config/heroic/gog_store/installed.json', home/'.config/heroic/legendaryConfig/legendary/installed.json',
                  home/'.config/heroic/store_cache/gog_library.json', home/'.config/heroic/store_cache/legendary_library.json'):
        try:
            data = json.loads(index.read_text())
        except (OSError, ValueError):
            continue
        rows = data.get('installed', data.get('games', data.get('library', data))) if isinstance(data, dict) else data
        rows = rows.values() if isinstance(rows, dict) else rows
        for row in rows if isinstance(rows, list) or hasattr(rows, '__iter__') else []:
            if isinstance(row, dict):
                app = str(row.get('appName') or row.get('app_name') or row.get('app_id') or '')
                if app and app in ids['gog'] | ids['epic'] and row.get('title'):
                    ids['titles'].add(norm(row['title']))
    return ids


def match(data, ids):
    """(verified entry or None, wiki entries, leave-auto list, backports dict) for a game."""
    if not data:
        return None, [], [], {}

    def hit(entry):
        m = entry.get('match', {})
        return (ids['exe'] in m.get('exe', []) or ids['steam'] & set(m.get('steam', [])) or ids['gog'] & set(m.get('gog', []))
                or ids['epic'] & set(m.get('epic', [])) or ids['titles'] & set(m.get('title', [])))

    # An exe name alone is ambiguous (Game.exe, Launcher.exe, a shared Unreal project name): a verified recipe needs
    # the game's launcher ID. A game with no launcher ID (Lutris, a non-Steam shortcut) matches by exe name only when
    # its title or one of its folders also names the recipe's game; a game with other IDs (another store) does not.
    verified = None
    for entry in data.get('verified', []):
        m = entry['match']
        by_id = ids['steam'] & set(m.get('steam', [])) or ids['gog'] & set(m.get('gog', [])) or ids['epic'] & set(m.get('epic', []))
        known_ids = ids['steam'] or ids['gog'] or ids['epic']
        named = (({norm(entry.get('title', ''))} | set(m.get('title', []))) - {''}) & (ids['titles'] | ids.get('folders', set()))
        if by_id or (ids['exe'] in m.get('exe', []) and not known_ids and named):
            verified = entry
            break
    wiki = [w for w in data.get('wiki', []) if hit(w)]
    return verified, wiki, data.get('leave_auto', {}).get(ids['exe'], []), data.get('backports', {}).get(ids['exe'], {})


def split_key(key):
    section, name = key.split('.', 1)
    return section, name


def ini_changes(verified, backports, parsed, fg_input, recipe_input, route=None, upscaler=None):
    """OptiScaler keys to write: recipe keys and backported upstream quirks, each only where the INI still says auto.
    Frame-generation keys belong to the recipe's route and input: skipped when the user chose another. The other keys
    (upscaler inputs, spoofing, hotfixes) are about the game's upscaler, which OptiScaler hooks on both routes."""
    out = {}
    other_route = bool(route and (verified or {}).get('route') and route != verified['route'])
    for key, value in (verified or {}).get('ini', {}).items():
        section, name = split_key(key)
        if section.lower() in FG_SECTIONS and (other_route or (recipe_input and fg_input != recipe_input)):
            continue
        out[(section, name)] = str(value)
    for key, b in (backports or {}).items():
        out.setdefault(split_key(key), str(b['value']))
    for key, value in (verified or {}).get('upscaler_ini', {}).get(upscaler, {}).items():
        out[split_key(key)] = str(value)
    return {k: v for k, v in out.items() if parsed.get((k[0].lower(), k[1].lower()), 'auto').strip().lower() in ('', 'auto')}


def launch_args(verified, wiki):
    args = list((verified or {}).get('launch_args', []))
    if not verified:
        for w in wiki:
            args += [a for a in w.get('launch_args', []) if a not in args]
    # One DX12 switch is enough; the verified or first-listed spelling wins.
    return args[:1] if args else []


def prefix_user(exe, launchers, home=None):
    """drive_c/users/steamuser (or the Heroic prefix's user folder) of the game's Proton prefix, if it exists."""
    exe = Path(exe).resolve()
    for parent in exe.parents:
        if parent.name == 'common' and parent.parent.name.lower() == 'steamapps':
            manifest = _steam_manifest(exe)
            if manifest and manifest[0]:
                user = parent.parent/'compatdata'/manifest[0]/'pfx/drive_c/users/steamuser'
                return user if user.is_dir() else None
    for target in launchers:
        if target.get('launcher') == 'heroic':
            try:
                settings = json.loads(Path(target['path']).read_text())[target['id']]
            except (OSError, ValueError, KeyError):
                continue
            prefix = settings.get('winePrefix')
            if prefix:
                base = Path(prefix)/'pfx' if (Path(prefix)/'pfx').is_dir() else Path(prefix)
                for name in ('steamuser', Path.home().name):
                    user = base/'drive_c/users'/name
                    if user.is_dir():
                        return user
    return None


# Game settings files. Edits change only the characters of the values they set, in the file's own encoding, BOM,
# line endings and layout; a value already in effect is not rewritten at all. Each edit records every key's original
# value, so Restore can put back the keys even after the game rewrote the rest of the file.
FORMATS = ('json', 'json-options', 'xml-option', 'ini-replace', 'ini')
JSON_FORMATS = ('json', 'json-options')


class Unreadable(ValueError):
    """A game settings file this code cannot decode or parse. Its item is left alone with this message: never an
    exception that aborts an install, configure or restore."""


def decode(data):
    """(text, codec, bom). Unreal writes UTF-16 LE with a BOM once a file holds non-ASCII text; other games write
    UTF-8 with or without a BOM. Edits are encoded back the same way."""
    if data.startswith((b'\xff\xfe\0\0', b'\0\0\xfe\xff')):
        raise Unreadable('UTF-32 text is not supported')
    for bom, codec in ((b'\xef\xbb\xbf', 'utf-8'), (b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be')):
        if data.startswith(bom):
            break
    else:
        bom, codec = b'', 'utf-8'
        # BOM-less UTF-16 of ASCII text: every other byte is zero. Other NUL bytes mean this is no text file.
        if b'\0' in data and len(data) % 2 == 0:
            codec = 'utf-16-le' if not any(data[1::2]) else 'utf-16-be' if not any(data[::2]) else codec
    try:
        text = data[len(bom):].decode(codec)
    except UnicodeDecodeError:
        raise Unreadable('not UTF-8 or UTF-16 text') from None
    if '\0' in text:
        raise Unreadable('binary data, not a text settings file')
    return text, codec, bom


_LINE = re.compile(r'([^\r\n]*)(\r\n|\r|\n)?')
_HEADER = re.compile(r'[ \t]*\[([^\]]*)\][ \t]*')
_KEY = re.compile(r'([ \t]*)([^\s=;#\[][^=]*?)([ \t]*=[ \t]*)(.*)')


def _ini_lines(text):
    """(start, body, line ending, section, is header) per line; section is the lower-case name of the enclosing
    section, None before the first header."""
    lines, pos, section = [], 0, None
    while pos < len(text):
        m = _LINE.match(text, pos)
        header = _HEADER.fullmatch(m[1])
        if header:
            section = header[1].strip().lower()
        lines.append((pos, m[1], m[2] or '', section, bool(header)))
        pos = m.end()
    return lines


_WS = re.compile(r'[ \t\r\n]*')


def _json_tree(text):
    """The document as nodes (kind, start, end, children): kind '{' with [(key, node)], '[' with [node], 'v' for a
    scalar. The spans let an edit replace only the characters of the values it changes."""
    try:
        json.loads(text)
    except (ValueError, RecursionError) as error:
        raise Unreadable('not valid JSON (' + str(error) + ')') from None
    decoder = json.JSONDecoder()

    def skip(i):
        return _WS.match(text, i).end()

    def node(i):
        i = skip(i)
        if text[i:i+1] not in ('{', '['):
            end = decoder.raw_decode(text, i)[1]
            return ('v', i, end, None)
        kind, kids, j = text[i], [], skip(i+1)
        close = '}' if kind == '{' else ']'
        while text[j:j+1] != close:
            if kids:
                if text[j:j+1] != ',':
                    raise ValueError('expected a comma')
                j = skip(j+1)
            if kind == '{':
                key, j = decoder.raw_decode(text, j)
                j = skip(j)
                if not isinstance(key, str) or text[j:j+1] != ':':
                    raise ValueError('expected a member name')
                child = node(j+1)
                kids.append((key, child))
            else:
                child = node(j)
                kids.append(child)
            j = skip(child[2])
        return (kind, i, j+1, kids)
    try:
        root = node(0)
        if skip(root[2]) != len(text):
            raise ValueError('trailing data')
    except (ValueError, IndexError, RecursionError) as error:
        raise Unreadable('JSON layout not understood (' + str(error) + ')') from None
    return root


def _member(node, name):
    """An object's member (the last of duplicates, as json.loads reads it), or None."""
    found = [child for key, child in node[3] if key == name] if node and node[0] == '{' else []
    return found[-1] if found else None


def _xml_attr(tag, name):
    """(start, end, value) of an attribute's value inside a tag, or None."""
    m = re.search(r'\s' + name + r'\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', tag)
    if not m:
        return None
    group = 1 if m[1] is not None else 2
    return m.start(group), m.end(group), html.unescape(m[group])


def _occurrences(text, fmt, section, key):
    """Every place key's value is in effect: [dict(span=(start, end), value=current, line=(start, end) for INI)].
    Several places are possible: a key in two sections of an INI without a section, JSON options sharing a name."""
    out = []
    if fmt in ('ini', 'ini-replace'):
        for start, body, eol, sect, header in _ini_lines(text):
            m = None if header else _KEY.fullmatch(body)
            # INI keys and sections are case-insensitive (Unreal, OptiScaler); the file keeps its own spelling.
            if m and m[2].lower() == key.lower() and (section is None or sect == section.strip().lower()):
                # line: what removing it takes out; a last line without a line ending takes the one before it.
                cut = start - (0 if eol or not start else 2 if text[start-2:start] == '\r\n' else 1)
                out.append(dict(span=(start+m.start(4), start+m.end(4)), value=m[4], line=(cut, start+len(body)+len(eol))))
    elif fmt == 'xml-option':
        # An option without _value is treated as not saved yet (the game writes _value for every option it saves).
        for tag in re.finditer(r'<Option\w*\s[^>]*>', text):
            name, value = _xml_attr(tag[0], 'Name'), _xml_attr(tag[0], '_value')
            if name and name[2] == key and value:
                out.append(dict(span=(tag.start()+value[0], tag.start()+value[1]), value=value[2]))
    elif fmt in JSON_FORMATS:
        root = _json_tree(text)
        if root[0] != '{':
            raise Unreadable('expected a JSON object')
        nodes = [_member(root, key)] if fmt == 'json' else []
        if fmt == 'json-options':
            data = _member(root, 'data')
            for group in data[3] if data and data[0] == '[' else []:
                options = _member(group, 'options')
                for option in options[3] if options and options[0] == '[' else []:
                    name, value = _member(option, 'name'), _member(option, 'value')
                    if name and value and json.loads(text[name[1]:name[2]]) == key:
                        nodes.append(value)
        out = [dict(span=(n[1], n[2]), value=json.loads(text[n[1]:n[2]])) for n in nodes if n]
    else:
        raise Unreadable('unknown game settings format ' + str(fmt))
    return out


def _render(fmt, value):
    if fmt in JSON_FORMATS:
        return json.dumps(value, ensure_ascii=False)
    return html.escape(str(value), quote=True) if fmt == 'xml-option' else str(value)


def _same(fmt, current, wanted):
    # JSON compares types too (true is not 1); INI and XML values are text, compared without surrounding blanks.
    if fmt in JSON_FORMATS:
        return json.dumps(current, sort_keys=True) == json.dumps(wanted, sort_keys=True)
    return str(current).strip() == str(wanted).strip()


def _splice(text, edits):
    for (start, end), new in sorted(edits, key=lambda e: e[0][0], reverse=True):
        text = text[:start] + new + text[end:]
    return text


def _json_expected(text, fmt, values):
    """The document json.loads should read after a correct edit (checks the span edit before anything is written)."""
    doc = json.loads(text)
    if fmt == 'json':
        doc.update(values)
        return doc
    data = doc.get('data')
    for group in data if isinstance(data, list) else []:
        options = group.get('options') if isinstance(group, dict) else None
        for option in options if isinstance(options, list) else []:
            if isinstance(option, dict) and 'value' in option and isinstance(option.get('name'), str) and option['name'] in values:
                option['value'] = values[option['name']]
    return doc


def change(data, fmt, section, values, previous=None):
    """Plan a recipe edit of a game settings file:
    after      the edited bytes; data itself when every value is already in effect (nothing is rewritten); None when
               the edit cannot be made yet (reason says why)
    originals  {key: {'value': v}} or {key: {'absent': True}} (a key the 'ini' format inserts): what Restore puts back
    carried    keys whose original comes from previous = {key: dict(recipe=value an earlier installation wrote,
               original=its original)}: used while the file still holds that earlier recipe value (its Restore could
               not put it back), so a reinstall does not record the recipe's own value as the original
    created_section  the 'ini' format appended the section header
    A multi-key entry is all or nothing: its keys are one verified combination (DLSS FG on together with the other FG
    modes off, for instance), and a partial edit would leave the game in a state nobody tested. Missing keys are
    named in the reason, which install and configure print. Raises Unreadable for a file it cannot decode or parse."""
    if fmt not in FORMATS:
        raise Unreadable('unknown game settings format ' + str(fmt))
    text, codec, bom = decode(data)
    newline = '\r\n' if '\r\n' in text else '\n'
    originals, edits, inserts, missing, mixed = {}, [], [], [], []
    for key, wanted in values.items():
        found = _occurrences(text, fmt, section, key)
        if not found:
            originals[key] = {'absent': True}
            (inserts if fmt == 'ini' and section else missing).append(key)
        elif any(not _same(fmt, o['value'], found[0]['value']) for o in found[1:]):
            mixed.append(key)
        else:
            originals[key] = {'value': found[0]['value']}
            edits += [(o['span'], _render(fmt, wanted)) for o in found if not _same(fmt, o['value'], wanted)]
    carried = []
    for key, prev in (previous or {}).items():
        now = originals.get(key)
        if (key in values and now and 'value' in now and _same(fmt, now['value'], prev['recipe'])
                and json.dumps(prev['original'], sort_keys=True) != json.dumps(now, sort_keys=True)):
            originals[key] = prev['original']
            carried.append(key)
    result = dict(after=None, originals=originals, carried=carried, created_section=False, reason=None)
    if missing or mixed:
        result['reason'] = '; '.join(filter(None, (
            missing and 'not in the file yet: ' + ', '.join(missing) + " (start the game and save its settings once, or set "
                                                                      "them in the game's menu), then Settings",
            mixed and 'set differently in several places: ' + ', '.join(mixed))))
        return result
    if inserts:
        lines = [(s, b, e) for s, b, e, sect, header in _ini_lines(text) if header and sect == section.strip().lower()]
        added = [f'{k}={values[k]}' for k in inserts]
        if lines:
            # Right after the section header, with the header's own line ending (a CRLF file stays CRLF).
            start, body, eol = lines[0]
            at = start + len(body) + len(eol)
            edits.append(((at, at), ''.join(a + eol for a in added) if eol else ''.join(newline + a for a in added)))
        else:
            gap = '' if not text or text.endswith(('\n', '\r')) else newline
            edits.append(((len(text), len(text)), gap + f'[{section}]' + newline + ''.join(a + newline for a in added)))
            result['created_section'] = True
    if not edits:
        result['after'] = data
        return result
    new = _splice(text, edits)
    after = bom + new.encode(codec)
    # Prove the edit did what the recipe says (and, for JSON, nothing else) before anything is written.
    ok = values_in(after, fmt, section, values)
    if ok and fmt in JSON_FORMATS:
        ok = json.dumps(json.loads(new), sort_keys=True) == json.dumps(_json_expected(text, fmt, values), sort_keys=True)
    if not ok:
        raise Unreadable('the edit could not be verified')
    result['after'] = after
    return result


def edit(data, fmt, section, values):
    """Edited bytes of a game settings file (data itself when already in effect), or None when a key to change is not
    in the file yet. Raises Unreadable (a ValueError) for a file it cannot decode or parse."""
    return change(data, fmt, section, values)['after']


def values_in(data, fmt, section, values):
    """True when every recipe value is in effect in data."""
    try:
        text = decode(data)[0]
        return all((found := _occurrences(text, fmt, section, k)) and all(_same(fmt, o['value'], v) for o in found)
                   for k, v in values.items())
    except ValueError:
        return False


def revert(data, fmt, section, values, originals, created_section=False):
    """Put the originals back key by key in a file the game rewrote since installation: (bytes, {key: why left}).
    A key is reverted only while it still holds the recipe's value; a value the user or the game chose since is theirs.
    Why a key is left: 'changed' (it holds another value now), 'missing' (no longer in the file), 'kept' (still the
    recipe's value, but its original is unknown or cannot be written back). data itself when nothing changes."""
    text, codec, bom = decode(data)
    edits, left = [], {}
    for key, wanted in values.items():
        found, original = _occurrences(text, fmt, section, key), originals.get(key)
        at_recipe = found and all(_same(fmt, o['value'], wanted) for o in found)
        if not found:
            if original is None or 'value' in original:
                left[key] = 'missing'
        elif original is None:
            left[key] = 'kept' if at_recipe else 'changed'
        elif 'value' in original and all(_same(fmt, o['value'], original['value']) for o in found):
            continue  # already the original (the recipe's own value, or an interrupted Restore)
        elif not at_recipe:
            left[key] = 'changed'
        elif 'value' in original:
            edits += [(o['span'], _render(fmt, original['value'])) for o in found]
        elif fmt in ('ini', 'ini-replace'):
            edits += [(o['line'], '') for o in found]  # a line the recipe added
        else:
            left[key] = 'kept'
    if not edits:
        return data, left
    text = _splice(text, edits)
    if created_section and section:
        # Also the header the recipe appended, once nothing but blank lines is left under it. (A line ending added
        # before it, when the original file did not end with one, stays: the game has rewritten this file anyway.)
        lines = _ini_lines(text)
        mine = [l for l in lines if l[3] == section.strip().lower()]
        headers = [l for l in mine if l[4]]
        if len(headers) == 1 and all(not l[1].strip() for l in mine if not l[4]):
            start, body, eol = headers[0][:3]
            text = text[:start] + text[start+len(body)+len(eol):]
    return bom + text.encode(codec), left


def _slot(entry):
    return (entry['file'], entry['format'], entry.get('section'))


def settings_plan(verified, user, route, fg_input, previous=None, create_ini=False):
    """One dict per recipe game setting for the chosen route and input: file, entry, path, before (bytes or None),
    after (None = pending: file or key missing, or unreadable; reason says which), originals, carried,
    created_section, previous. A recipe's game settings belong to its route: a user who chose another route (or
    another input than an entry requires) gets none of them. previous: {(file, format, section): {key: dict(recipe,
    original)}} from an earlier installation (see change)."""
    plan = []
    if not verified or route != verified.get('route'):
        return plan
    for s in verified.get('game_settings', []):
        need = s.get('requires_fg_input', verified.get('fg_input'))
        if need and fg_input != need:
            continue
        path = user/s['file'] if user else None
        prev = (previous or {}).get(_slot(s))
        item = dict(file=s['file'], entry=s, path=path, before=None, after=None, originals={}, carried=[],
                    created_section=False, previous=prev, reason=None)
        plan.append(item)
        if path and path.is_symlink():
            item['reason'] = 'the file is a symlink; not changed'
            continue
        try:
            before = item['before'] = path.read_bytes() if path and path.is_file() else None
            if before is None and not (path and s['format'] == 'ini' and create_ini and path.parent.is_dir()):
                item['reason'] = 'not created yet: start the game once, then Settings' if path else None
                continue
            item.update(change(before or b'', s['format'], s.get('section'), s['values'], prev))
        except (OSError, Unreadable) as error:
            item['reason'] = 'cannot read it (' + str(error) + '); not changed'
    return plan


def suggestions(verified, wiki, fg_input, route):
    """Readable lines for the install output: what the recipe did not apply and where to read more."""
    lines = []
    if verified and verified.get('note'):
        lines.append('Known on BC-250: ' + verified['note'])
    here = 'native-xefg' if route == 'native' else fg_input
    if not wiki:
        return lines
    # One block per game, however many wiki pages mention it (a game page, the FG options list, the compatibility list).
    title = max((w['title'] for w in wiki), key=len)
    advice = [a for w in wiki for a in w.get('fg_advice', []) if 'nvidia' not in str(a.get('when', {}).get('gpu', '')).lower()]
    prefer = sorted({INPUT_NAMES.get(a['input'], a['input']) for a in advice if a['advice'] == 'prefer'})
    broken = sorted({INPUT_NAMES.get(a['input'], a['input']) for a in advice if a['advice'] in ('broken', 'avoid')})
    if here in {a['input'] for a in advice if a['advice'] in ('broken', 'avoid')}:
        lines.append(f"OptiScaler wiki ({title}): reports problems with {INPUT_NAMES.get(here, here)} here.")
    if prefer and not verified:
        lines.append(f"OptiScaler wiki ({title}) prefers: {', '.join(prefer)}" + (f"; avoid: {', '.join(broken)}" if broken else '') + '.')
    keys = []
    for w in wiki:
        for i in w.get('ini', []):
            if 'nvidia' in str(i.get('when', {}).get('gpu', '')).lower():
                continue
            text = f"{i['key']}={i['value']}" + (f" ({', '.join(f'{k} {v}' for k, v in i['when'].items())})" if i.get('when') else '')
            if text not in keys:
                keys.append(text)
    if keys and not verified:
        lines.append('  OptiScaler settings it lists (not applied): ' + '; '.join(keys[:6]) + ('; ...' if len(keys) > 6 else ''))
    other = sorted({a for w in wiki for a in w.get('other_launch_args', [])})
    if other and not verified:
        lines.append('  Launch options it lists (not applied): ' + ' '.join(other))
    pages = [p for w in sorted(wiki, key=lambda w: -len(w['title'])) for p in w.get('pages', [])]
    if pages:
        lines.append('  Read: ' + ' '.join(dict.fromkeys(pages)))
    return lines
