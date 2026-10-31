#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build packaging/recipes/recipes.json, the per-game recipe file with its provenance, from the inputs committed in
research/recipes/ (offline: the same inputs give the same bytes), and from it packaging/recipes/recipes-runtime.json,
the compact file a package ships as recipes/recipes.json.

- verified-bc250 (verified/*.json, one per game): recipes the maintainers qualified on a BC-250. Applied.
- community-bc250 (community/*.json, community/README.md): reviewed recipes from other BC-250 owners, validated against
  the rules for recipes. Applied, labelled as community reports.
- quirks (optiscaler.json "quirks"): OptiScaler exes whose runtime quirk sets a key the installer writes by default (rule
  Q3), every key a quirk sets per exe (quirk_keys: nothing below a verified recipe writes those, Q3 generalised), and
  upstream quirks newer than the shipped build (Q2), derived from the research quirk extraction (--quirks).
- wiki-reported (wiki.json, at the wiki commit it names): one entry per wiki title, facts only (page links, tested
  versions, inputs, INI keys with every condition the page states, launch items, FG advice, proxy names, the
  compatibility list's verdict, game-setting keys), no copied prose. wiki-curation.json adds the maintainers' launcher
  IDs (with their sources), extra titles and requirements; an exe joins an entry when an OptiScaler quirk names the game.
  DX12 launch arguments are applied (L1), broken FG inputs veto the automatic choice (V1), the reviewed INI items of
  wiki_promote.json are applied where their conditions hold (P1); the rest is shown (packaging/compat.py evaluates every
  condition against the install).
- optiscaler.json also records each OptiScaler build a package may carry (DLL and OptiScaler.ini digests) and the keys
  each OptiScaler.ini defines (once per digest): the wiki settings planner tells supported keys apart with them.

  build_recipes.py            both files from the inputs
  build_recipes.py --check    exit status 1, writing nothing, when either file is not what the inputs build
  build_recipes.py --compact  only the compact file, from the full file

A refresh rewrites one input and rebuilds; the other inputs (curated identities, promotions, builds) stay as they are.
The research drafts, the quirk extraction and the OptiScaler sources these read live outside this tree:
  --wiki-drafts DIR --wiki-commit SHA --wiki-date DATE   wiki.json from research drafts (one entry per page section)
  --add-build COMMIT DLL_SHA256 OPTISCALER_INI           a build's digests and the keys its OptiScaler.ini defines
  --quirks QUIRKS_JSON                                   the quirk tables, from a quirk extraction of the pinned build
"""
import argparse, configparser, hashlib, json, re, shlex, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'packaging/recipes/recipes.json'
COMPACT = ROOT / 'packaging/recipes/recipes-runtime.json'
VERIFIED = HERE / 'verified'
COMMUNITY = HERE / 'community'
DX12_ARGS = {'-dx12', '-d3d12', '-force-d3d12'}
# What the drafts record beside a condition (SCHEMA.md): explanations, never limits on where an item applies.
NOTE_KEYS = {'reason', 'purpose', 'note', 'autoapplied_since', 'value', 'feature'}

INSTALLER_KEYS = {'Upscalers.Dx12Upscaler', 'FSR.UpscalerIndex', 'FSR.Fsr4ForceModel', 'FSR.Fsr4EnableWatermark',
                  'FrameGen.Enabled', 'fakenvapi.UseFakenvapi', 'FrameGen.FGInput', 'FrameGen.FGOutput',
                  'Libraries.XeFGPath', 'Libraries.XeLLPath', 'XeFG.ForceBorderless', 'Plugins.LoadAsiPlugins',
                  'XeFG.InterpolationCount', 'FrameGen.DisableHudless', 'fakenvapi.ForceReflex', 'XeFG.XeFGModel',
                  'FSR.Fsr4GpuSupport'}


def read(path):
    return json.loads(Path(path).read_text())


def dumps(data):
    """The full file's one format: two-space indentation, text as is (the build and its tests use this alone)."""
    return json.dumps(data, indent=2, ensure_ascii=False) + '\n'


def dumps_compact(data):
    return json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n'


def dumps_rows(doc, key):
    """An input whose list under key (its last field) holds one item per line: a refresh's diff names the items it
    changed."""
    head = json.dumps({k: v for k, v in doc.items() if k != key}, indent=2, ensure_ascii=False)
    rows = ',\n'.join('    ' + json.dumps(row, ensure_ascii=False) for row in doc[key])
    return head[:-2] + f',\n  "{key}": [\n{rows}\n  ]\n}}\n'


# Store editions: "Crimson Desert Enhanced", "The Witcher 3: Wild Hunt - Game of the Year Edition". A title without its
# edition is a loose alias, sometimes another game (GTA V Legacy and Enhanced, Crysis and Crysis Remastered): the recipe
# file lists it apart (match.alias), and FreeFG never matches by it.
EDITION = re.compile(r'(\s+(the\s+)?(game of the year|goty|enhanced|definitive|complete|deluxe|gold|ultimate|anniversary|remastered|'
                     r'directors cut|standard|premium)(\s+edition)?)+$')


def norm(title):
    """A title as packaging/recipes.py matches it (recipes.norm)."""
    t = re.sub(r'\([^)]*\)', '', title.lower()).replace('&', 'and').replace('’', "'").replace('‐', '-')
    t = re.sub(r"[^a-z0-9]+", ' ', t.replace("'", '')).strip()
    t = re.sub(r'\b(ii)\b', '2', t)
    return re.sub(r'\b(iii)\b', '3', t)


def loose(title):
    """The title without its store edition (recipes.loose)."""
    return EDITION.sub('', norm(title)).strip()


def _compat():
    """packaging/compat.py: the installer's own key rules and shared exe names, which the build follows."""
    if str(ROOT / 'packaging') not in sys.path:
        sys.path.insert(0, str(ROOT / 'packaging'))
    import compat
    return compat


def generic(exe):
    """True for an exe name many games share (packaging/compat.py GENERIC_EXES, also as its WinGDK build): never a
    game's identity."""
    names = _compat().GENERIC_EXES
    return exe in names or exe.replace('-wingdk-', '-win64-') in names


# ---------------------------------------------------------------------------------------------------- the build
# Field order of a wiki entry in the recipe file (every entry alike, whichever input added a field).
WIKI_ORDER = ('title', 'match', 'status', 'pages', 'tested', 'upscaler_inputs', 'fg_inputs', 'fg_advice', 'ini', 'launch_args',
              'launch', 'proxy', 'game_settings', 'counts', 'compat', 'optipatcher', 'promoted', 'requirements',
              'identity_sources')
# What wiki.json holds per entry (the wiki's facts), in its order.
WIKI_FACTS = ('title', 'pages', 'tested', 'upscaler_inputs', 'fg_inputs', 'fg_advice', 'ini', 'launch', 'proxy', 'game_settings',
              'counts', 'compat', 'optipatcher')
# What wiki-curation.json may add to an entry: a complete title list, launcher IDs, requirements and the IDs' sources.
CURATED = ('title', 'steam', 'gog', 'epic', 'requirements', 'identity_sources')


def build_keys(opti, commit=None):
    """The INI keys (lower case) the OptiScaler.ini of a build defines: the pinned build's by default."""
    return {k.lower() for k in opti['ini_keys'][opti['builds'][commit or opti['pinned']]['ini_sha256']]}


def exe_links(key, titles):
    """The exes an OptiScaler quirk entry links to the wiki title key (both without edition, loose; titles: exe ->
    game name). A quirk comment names the game ("The Witcher 3"); it links to the one wiki title it is the start of:
    "the witcher 3 wild hunt" extends "the witcher 3"; "red dead redemption 2" is another game than "red dead
    redemption"."""
    return sorted(exe for exe, t in titles.items() if t == key or (
        len(t.split()) >= 2 and key.startswith(t + ' ') and not re.match(r'\d|[ivx]+\b', key[len(t) + 1:])))


# A wiki launch item's tokens: environment assignments, %command% (Steam's place for the game), programs that wrap the
# game, game flags.
ASSIGN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*=.*')
FLAG = re.compile(r'[-+/]?[A-Za-z0-9][A-Za-z0-9_.:=,+-]*')
WRAPPERS = {'bash', 'sh', 'env', 'exec', 'gamescope', 'gamemoderun', 'mangohud', 'taskset', 'nice', 'wine', 'proton', 'prime-run'}
# What FreeFG's own launch settings set or its checks refuse (packaging/launcher_config.py environment() and GE_UPSCALER),
# and API switches that leave DirectX 12 (packaging/compat.py OFF_DX12_ARGS): a wiki item touching one cannot be used
# beside FreeFG as it stands.
FREEFG_OWNED = re.compile(r'WINEDLLOVERRIDES|VK_\w+|VKD3D_\w+|XEFG_\w+|BC250_\w+|PROTON_(USE_OPTISCALER|\w+_UPGRADE)')
OFF_DX12_ARGS = {'-dx11', '-d3d11', '-force-d3d11', '-vulkan', '-force-vulkan', '-opengl', '-force-glcore'}


def launch_text(args):
    """A launch item as one line, its tokens in order; a token with blanks is quoted for the shell unless it is."""
    return ' '.join(shlex.quote(a) if re.search(r'\s', a) and a[:1] + a[-1:] not in ('""', "''") else a for a in args)


def launch_kind(args):
    """args: game flags only; env: environment assignments only; steam: a Steam launch-options line (assignments,
    %command%, then game flags); wrapper: another program around the game (a shell, an executable path...)."""
    n = next((i for i, a in enumerate(args) if not ASSIGN.fullmatch(a)), len(args))
    rest = args[n:]
    if not rest:
        return 'env'
    if any(a.lower() in WRAPPERS for a in rest):
        return 'wrapper'
    if rest[0] == '%command%' and all(FLAG.fullmatch(a) for a in rest[1:]):
        return 'steam'
    return 'args' if not n and all(FLAG.fullmatch(a) for a in rest) else 'wrapper'


def launch_items(items):
    """(L1 arguments, shown items) of an entry's launch items (wiki.json). The DX12 switch of an unconditional item is
    applied (L1); every other item is shown whole, as the page gives it (one line, never token by token), with its
    kind, its condition and the FreeFG settings it would collide with. Low-confidence items are left out, as INI items
    are: the extraction doubts what the page says."""
    l1, shown = [], []
    for i in items:
        if i.get('confidence') != 'high':
            continue
        conditions = {k for k in i.get('when') or {} if k not in NOTE_KEYS}
        if not conditions:
            l1 += [a for a in i['args'] if a.lower() in DX12_ARGS and a not in l1]
            if all(a.lower() in DX12_ARGS for a in i['args']):
                continue
        item = dict(text=launch_text(i['args']), kind=launch_kind(i['args']), **({'when': i['when']} if i.get('when') else {}))
        clash = [a.split('=', 1)[0] for a in i['args'] if ASSIGN.fullmatch(a) and FREEFG_OWNED.fullmatch(a.split('=', 1)[0])]
        clash += [a for a in i['args'] if a.lower() in OFF_DX12_ARGS]
        if clash:
            item['conflicts'] = list(dict.fromkeys(clash))
        if item not in shown:
            shown.append(item)
    return l1, shown


# The wiki's topic pages (FSR4 on Linux, Resource Barriers, Unreal Engine...): advice for many games, no game's
# identity. wiki.json keeps their facts; the recipe file has game entries only, and nothing shows topic advice.
TOPIC = re.compile(r'\(general\)$', re.I)


def wiki_entries(doc, curation, titles):
    """The wiki part of the recipe file: wiki.json's facts per game title (not the topic pages), its exes from the
    quirk titles, the maintainers' additions (wiki-curation.json)."""
    known = {e['title'] for e in doc['entries'] if not TOPIC.search(e['title'])}
    for title, extra in curation.items():
        if title not in known:
            raise SystemExit(f'wiki-curation.json: no wiki game entry is titled {title!r}')
        if set(extra) - set(CURATED):
            raise SystemExit(f'wiki-curation.json {title!r}: unknown fields {sorted(set(extra) - set(CURATED))}')
    out = []
    for e in doc['entries']:
        if set(e) - set(WIKI_FACTS):
            raise SystemExit(f'wiki.json {e["title"]!r}: unknown fields {sorted(set(e) - set(WIKI_FACTS))}')
        if TOPIC.search(e['title']):
            continue
        extra = curation.get(e['title'], {})
        # Identity strength as data: exact titles, then the loose aliases and the shared exe names nothing matches by.
        match = dict(title=list(extra.get('title') or [norm(e['title'])]))
        aliases = [a for a in dict.fromkeys(loose(t) for t in [e['title'], *match['title']]) if a not in match['title']]
        if aliases:
            match['alias'] = aliases
        exes = exe_links(loose(e['title']), titles)
        if [x for x in exes if not generic(x)]:
            match['exe'] = [x for x in exes if not generic(x)]
        if [x for x in exes if generic(x)]:
            match['generic_exe'] = [x for x in exes if generic(x)]
        for store in ('steam', 'gog', 'epic'):
            if extra.get(store):
                match[store] = list(extra[store])
        w = dict(title=e['title'], match=match, status='wiki-reported',
                 pages=[p if '://' in p else doc['wiki']['url'] + p for p in e['pages']])
        w.update({k: v for k, v in e.items() if k not in ('title', 'pages', 'launch')})
        l1, shown = launch_items(e.get('launch', []))
        if l1:
            w['launch_args'] = l1
        if shown:
            w['launch'] = shown
        w.update({k: extra[k] for k in ('requirements', 'identity_sources') if extra.get(k)})
        out.append(w)
    return out


def promote(wk, path):
    """Attach the reviewed wiki INI items of wiki_promote.json (decision "promote") to their wiki entries as
    "promoted" (RULES.md P1). Each must be an INI item of that entry (same key and value) and a key no rule keeps out
    of automatic writes; a reviewed item that is not refuses the build."""
    compat = _compat()
    review = read(path)
    by = {norm(w['title']): w for w in wk}
    count = 0
    for item in review['items']:
        if item['decision'] != 'promote':
            continue
        w = by.get(norm(item['title']))
        found = [i for i in (w or {}).get('ini', []) if i['key'] == item['key'] and i['value'] == str(item['value'])]
        if not found:
            raise SystemExit(f'wiki_promote.json: {item["title"]} {item["key"]}={item["value"]} is not an INI item of that wiki entry')
        rule, why = compat.key_rule(item['key'], item['value'])
        if rule:
            raise SystemExit(f'wiki_promote.json: {item["title"]} {item["key"]}: {why}')
        w.setdefault('promoted', []).append(dict(key=item['key'], value=str(item['value']), **({'when': found[0]['when']} if found[0].get('when') else {})))
        count += 1
    return count


SETTING_FORMATS = ('json', 'json-options', 'xml-option', 'ini-replace', 'ini')
GAME_INPUTS = ('upscaler', 'dlssg', 'fsrfg')  # the FG inputs a recipe may choose (FSR 3.0 FG never reached OptiScaler; F0)
EVIDENCE_LEVELS = ('gameplay', 'generates', 'startup', 'installed', 'fails')  # packaging/compat.py EVIDENCE
VERIFIED_KEYS = {'title', 'match', 'status', 'route', 'fg_input', 'ini', 'upscaler_ini', 'game_settings', 'launch_args', 'required_args',
                 'manual_steps', 'note', 'evidence', 'observed', 'pending_verification', 'qualification', 'replaces'}
SETTING_KEYS = {'file', 'base', 'format', 'section', 'values', 'why', 'requires_fg_input'}
INI_KEY = re.compile(r'[A-Za-z0-9_-]+\.[A-Za-z0-9_]+')  # what packaging/compat.py's wiki planner accepts
# Graphics-API switches (launcher_config.API_ARGS, compat.OFF_DX12_ARGS): the installer adds a recipe's only where the
# user's own options choose none.
API_ARGS = DX12_ARGS | {'-dx11', '-d3d11', '-force-d3d11', '-vulkan', '-force-vulkan', '-opengl', '-force-glcore'}


def _strings(value):
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def check_verified(entry):
    """Problems with one verified recipe (an empty list when it may be built in): the fields packaging/recipes.py and
    install.py read, in the types they read them."""
    problems = [f'unknown field {k}' for k in sorted(set(entry) - VERIFIED_KEYS)]
    for k in ('title', 'match', 'route', 'evidence', 'observed'):
        if not entry.get(k):
            problems.append(f'missing {k}')
    if entry.get('status') != 'verified-bc250':
        problems.append('status must be verified-bc250')
    m = entry.get('match') or {}
    if set(m) - {'steam', 'gog', 'epic', 'exe', 'title'} or not all(_strings(v) for v in m.values()):
        problems.append('match holds lists of steam, gog, epic, exe and title names only')
    elif not any(m.get(k) for k in ('steam', 'gog', 'epic')) and not m.get('exe'):
        problems.append('match needs a launcher ID (steam, gog, epic) or exe names')
    if any(generic(e) for e in m.get('exe') or []):
        problems.append('match exe: a name many games share is no game\'s identity (use a launcher ID, or the game\'s own exe)')
    # recipes.identity lower-cases the exe and normalizes titles (lower-case words of letters and digits): anything else
    # never matches.
    if any(e != e.lower() for e in m.get('exe') or []) or not all(re.fullmatch(r'[a-z0-9]+( [a-z0-9]+)*', t) for t in m.get('title') or []):
        problems.append('match exe names are lower case and titles normalized (recipes.norm)')
    if entry.get('route') not in ('native', 'opti'):
        problems.append('route must be native or opti')
    elif (entry.get('fg_input') not in GAME_INPUTS) if entry['route'] == 'opti' else entry.get('fg_input') is not None:
        problems.append('fg_input must be upscaler, dlssg or fsrfg on the opti route, null on the native route')
    for name, ini in [('ini', entry.get('ini', {}))] + [(f'upscaler_ini {u}', v) for u, v in (entry.get('upscaler_ini') or {}).items()]:
        if not isinstance(ini, dict) or not all(isinstance(k, str) and INI_KEY.fullmatch(k) and isinstance(v, str) for k, v in ini.items()):
            problems.append(f'{name}: Section.Key names with text values')
    for s in entry.get('game_settings', []):
        if not isinstance(s, dict) or set(s) - SETTING_KEYS or s.get('format') not in SETTING_FORMATS or not s.get('file') \
                or not isinstance(s.get('values'), dict) or not s['values'] or s.get('requires_fg_input') not in GAME_INPUTS + (None,):
            problems.append(f'game setting {s.get("file") if isinstance(s, dict) else s}: file, format, values and the fields of '
                            f'{", ".join(sorted(SETTING_KEYS))} only')
        elif Path(s['file']).is_absolute() or '..' in Path(s['file']).parts:
            problems.append(f'game setting {s["file"]}: a path relative to the prefix user folder (drive_c/users/steamuser)')
    args = entry.get('launch_args')
    if not isinstance(args, list) or len(args) > 1 or any(a.lower() not in DX12_ARGS for a in args):
        problems.append(f'launch_args: at most one DX12 switch ({", ".join(sorted(DX12_ARGS))})')
    for k in ('manual_steps', 'replaces', 'required_args'):
        if k in entry and not _strings(entry[k]):
            problems.append(f'{k}: a list of texts')
    # A required argument is added whatever the user's API choice, so it never is one (that is launch_args').
    if any(a.lower() in API_ARGS or a != a.strip() for a in entry.get('required_args') or []):
        problems.append('required_args: game arguments without blanks around them, no graphics-API switch')
    if entry.get('evidence') and entry['evidence'] not in EVIDENCE_LEVELS:
        problems.append(f'evidence must be one of {", ".join(EVIDENCE_LEVELS)}')
    return problems


def overlaps(a, b):
    """True when one game identity would match both recipes: a launcher ID of the same store, or an exe name together
    with a title (recipes.match takes the first verified recipe that matches, so the other would never apply)."""
    ma, mb = a['match'], b['match']
    if any(set(ma.get(k, [])) & set(mb.get(k, [])) for k in ('steam', 'gog', 'epic')):
        return True
    named = [{norm(e['title'])} | set(e['match'].get('title', [])) for e in (a, b)]
    return bool(set(ma.get('exe', [])) & set(mb.get('exe', [])) and named[0] & named[1])


def verified_recipes(folder=VERIFIED):
    """verified/*.json, one recipe per game, in title order. A recipe whose identity overlaps another's refuses the
    build, unless it names that file in "replaces" (which then leaves the build)."""
    files = {f.stem: read(f) for f in sorted(Path(folder).glob('*.json'))}
    for stem, entry in files.items():
        problems = check_verified(entry)
        if problems:
            raise SystemExit(f'verified/{stem}.json: ' + '; '.join(problems))
    replaced = set()
    for stem, entry in files.items():
        for old in entry.get('replaces', []):
            if old not in files or not overlaps(entry, files[old]):
                raise SystemExit(f'verified/{stem}.json replaces {old}.json, which is no recipe for the same game')
            replaced.add(old)
    kept = sorted(stem for stem in files if stem not in replaced)
    for n, a in enumerate(kept):
        for b in kept[n + 1:]:
            if overlaps(files[a], files[b]):
                raise SystemExit(f'verified/{a}.json and verified/{b}.json claim the same game (a launcher ID, or an exe and '
                                 f'a title): merge them, or name the older one in the newer one\'s "replaces"')
    return sorted(({k: v for k, v in files[s].items() if k != 'replaces'} for s in kept), key=lambda v: (v['title'].casefold(), v['title']))


def text_problems(data):
    """Strings in the recipe file that are not one printable line (a control, line- or paragraph-separator character
    would split an INI line the installer writes, or a line Check prints), and INI keys, INI values and game-setting
    values with blanks around them (packaging/compat.py and install.py apply the same rule to what they write)."""
    out = []

    def walk(value, where):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(k, where)
                walk(v, f'{where}.{k}')
        elif isinstance(value, list):
            for n, v in enumerate(value):
                walk(v, f'{where}[{n}]')
        elif isinstance(value, str) and not value.isprintable():
            out.append(f'{where}: {value[:60]!r} has a control or separator character')

    walk(data, '')
    recipes = data['verified'] + data.get('community', [])
    ini = [(v['title'], v.get('ini', {})) for v in recipes] + [(v['title'], i) for v in recipes for i in v.get('upscaler_ini', {}).values()]
    ini += [(w['title'], {i['key']: i['value'] for i in w.get('ini', []) + w.get('promoted', [])}) for w in data['wiki']]
    for where, values in ini:
        out += [f'{where}: INI key {key!r} is no Section.Key name' for key in values if not INI_KEY.fullmatch(key)]
    for where, values in ini + [(f'{v["title"]} {s["file"]}', s['values']) for v in recipes for s in v.get('game_settings', [])]:
        for key, value in values.items():
            if isinstance(value, str) and value != value.strip() or key != key.strip():
                out.append(f'{where}: {key}={value!r} has blanks around it')
    return out


def build(folder=HERE):
    """The full recipe file from the inputs in folder (research/recipes/)."""
    folder = Path(folder)
    catalogue, opti, doc = read(folder / 'catalogue.json'), read(folder / 'optiscaler.json'), read(folder / 'wiki.json')
    if opti['pinned'] not in opti['builds'] or set(opti['compatible_commits']) - set(opti['builds']):
        raise SystemExit('optiscaler.json: the pinned and compatible commits each need a build (--add-build)')
    quirks = opti['quirks']
    wk = wiki_entries(doc, read(folder / 'wiki-curation.json')['entries'], quirks['titles'])
    promote(wk, folder / 'wiki_promote.json')
    sources = dict(optiscaler_pinned=opti['pinned'], optiscaler_upstream=opti['upstream'],
                   optiscaler_compatible_commits=opti['compatible_commits'], wiki=f'{doc["wiki"]["commit"]} ({doc["wiki"]["date"]})',
                   wiki_url=doc['wiki']['url'], **catalogue['notes'])
    data = dict(schema=catalogue['schema'], generated_by='research/recipes/build_recipes.py', sources=sources,
                rules=catalogue['rules'], verified=verified_recipes(folder / 'verified'),
                community=community(folder / 'community', quirks['quirk_keys'], build_keys(opti)),
                leave_auto=quirks['leave_auto'], backports=quirks['backports'], quirk_keys=quirks['quirk_keys'],
                wiki=[{k: w[k] for k in WIKI_ORDER if k in w} for w in sorted(wk, key=lambda w: (w['title'].casefold(), w['title']))],
                optiscaler_builds={c: dict(b, keys=opti['ini_keys'][b['ini_sha256']]) for c, b in opti['builds'].items()})
    problems = text_problems(data)
    if problems:
        raise SystemExit('The recipe file would carry text the installer cannot write or show as one line:\n  ' + '\n  '.join(problems[:20]))
    return data


# ------------------------------------------------------------------------------------------------ community recipes
# What a community recipe may hold (CONTRIBUTING.md "Game recipes"; RULES.md C1).
COMMUNITY_KEYS = {'title', 'match', 'status', 'route', 'fg_input', 'ini', 'game_settings', 'launch_args', 'manual_steps',
                  'known_problems', 'reports', 'reviewed_by', 'reviewed', 'note'}
REPORT_KEYS = {'issue', 'freefg', 'package_sha256', 'proton', 'mesa', 'kernel', 'gamescope', 'hdr', 'vrr', 'resolution',
               'upscaler_mode', 'ratio', 'minutes', 'starts', 'restore_checked', 'date'}


def check_community(entry, quirk_keys=None, readable=None):
    """Problems with one community recipe (an empty list when it may be built in)."""
    compat = _compat()
    problems = [f'unknown field {k}' for k in sorted(set(entry) - COMMUNITY_KEYS)]
    for k in ('title', 'match', 'status', 'route', 'reports', 'reviewed_by', 'reviewed'):
        if not entry.get(k):
            problems.append(f'missing {k}')
    m = entry.get('match') or {}
    if not any(m.get(k) for k in ('steam', 'gog', 'epic')) and not (m.get('exe') and (m.get('title') or entry.get('title'))):
        problems.append('match needs a launcher ID (steam, gog, epic) or exe names with the title')
    if any(generic(e) for e in m.get('exe') or []):
        problems.append('match exe: a name many games share is no game\'s identity (use a launcher ID, or the game\'s own exe)')
    if entry.get('status') != 'community-bc250':
        problems.append('status must be community-bc250')
    if entry.get('route') not in ('native', 'opti'):
        problems.append('route must be native or opti')
    if entry.get('route') == 'opti' and entry.get('fg_input') not in ('upscaler', 'dlssg', 'fsrfg'):
        problems.append('fg_input must be upscaler, dlssg or fsrfg (FSR 3.0 FG never reached OptiScaler; F0)')
    if entry.get('fg_input') in ('dlssg', 'fsrfg') and not entry.get('game_settings') and not entry.get('manual_steps'):
        problems.append('a game FG input needs the game setting that turns the game\'s FG on, or a manual step that says so (F2)')
    exes = [e.lower() for e in m.get('exe', [])]
    for key, value in (entry.get('ini') or {}).items():
        rule, why = compat.key_rule(key, value)
        if rule:
            problems.append(f'ini {key}: {why}')
        if readable is not None and key.lower() not in readable:
            problems.append(f'ini {key}: not read by the shipped OptiScaler build')
        for exe in exes:
            if key in (quirk_keys or {}).get(exe, {}):
                problems.append(f'ini {key}: OptiScaler\'s own fix for {exe} sets it (Q1)')
    for s in entry.get('game_settings') or []:
        if s.get('format') not in SETTING_FORMATS or not s.get('file') or not isinstance(s.get('values'), dict) or not s['values']:
            problems.append(f'game setting {s.get("file")}: needs file, format ({", ".join(SETTING_FORMATS)}) and values')
        elif Path(s['file']).is_absolute() or '..' in Path(s['file']).parts:
            problems.append(f'game setting {s["file"]}: a path relative to the prefix user folder (drive_c/users/steamuser)')
        if any('dilatemotionvectors' in str(k).lower() for k in (s.get('values') or {})):
            problems.append(f'game setting {s.get("file")}: E1 Engine.ini motion-vector tweaks need a maintainer\'s evidence')
    for arg in entry.get('launch_args') or []:
        if arg.lower() not in DX12_ARGS:
            problems.append(f'launch argument {arg}: only DX12 switches ({", ".join(sorted(DX12_ARGS))})')
    for n, r in enumerate(entry.get('reports') or []):
        missing = [k for k in ('issue', 'freefg', 'proton', 'ratio', 'minutes', 'starts', 'restore_checked', 'date') if k not in r]
        if missing or set(r) - REPORT_KEYS:
            problems.append(f'report {n}: missing {missing}' + (f', unknown {sorted(set(r) - REPORT_KEYS)}' if set(r) - REPORT_KEYS else ''))
        elif not (r['ratio'] >= 1.95 and r['minutes'] >= 10 and r['starts'] >= 3 and r['restore_checked'] is True):
            problems.append(f'report {n}: below the bar (ratio >= 1.95 over >= 10 minutes, 3 starts, Restore checked)')
    return problems


def community(folder=COMMUNITY, quirk_keys=None, readable=None):
    out = []
    for f in sorted(Path(folder).glob('*.json')):
        entry = read(f)
        problems = check_community(entry, quirk_keys, readable)
        if problems:
            raise SystemExit(f'{f.name}: ' + '; '.join(problems))
        out.append(entry)
    return out


# ---------------------------------------------------------------------------------------------- the compact file
# What packaging/recipes.py and install.py read from each part of the file; the compact runtime file keeps only these.
# Keep in step with them: test_recipes.py proves the full and compact files resolve every game alike.
VERIFIED_FIELDS = ('manual_steps', 'title', 'match', 'route', 'fg_input', 'ini', 'upscaler_ini', 'game_settings', 'launch_args', 'required_args',
                   'note', 'evidence', 'observed')
COMMUNITY_FIELDS = VERIFIED_FIELDS + ('status', 'manual_steps', 'known_problems')
# requires_fg_input is kept whenever present, even as null: a missing key means "the recipe's own input".
SETTING_FIELDS = ('file', 'format', 'section', 'values', 'requires_fg_input')
WIKI_FIELDS = ('requirements', 'identity_sources', 'title', 'match', 'pages', 'launch_args', 'tested', 'proxy', 'compat', 'optipatcher',
               'game_settings', 'promoted', 'counts')
SHOWN_ADVICE = ('prefer', 'broken', 'avoid')  # recipes.suggestions lists only these


def _pick(entry, fields):
    return {k: entry[k] for k in fields if k in entry}


def _nvidia_only(item):
    """Wiki advice and settings for NVIDIA GPUs alone, which recipes.suggestions never shows (recipes.nvidia_only)."""
    gpu = str(item.get('when', {}).get('gpu', '')).lower()
    return bool(re.search(r'nvidia|gtx|rtx', gpu)) and not re.search(r'non[- ]?nvidia|not nvidia|amd|radeon|rdna|intel|steam deck|dp4a', gpu)


def compact(data, full_sha256):
    """The runtime recipe file: the fields the installer reads, wiki advice and settings it can show, wiki page links
    relative to wiki_url and each OptiScaler.ini's key list once (recipes.load restores both). sources and the full
    file's digest say where it came from."""
    base = data['sources']['wiki_url']
    wiki = []
    for w in data['wiki']:
        entry = _pick(w, WIKI_FIELDS)
        if 'pages' in entry:
            # Relative only where recipes.load can tell: the rest of the link is no URL itself.
            entry['pages'] = [p[len(base):] if p.startswith(base) and '://' not in p[len(base):] else p for p in entry['pages']]
        advice = [_pick(a, ('advice', 'input', 'when')) for a in w.get('fg_advice', []) if a['advice'] in SHOWN_ADVICE and not _nvidia_only(a)]
        if advice:
            entry['fg_advice'] = advice
        ini = [_pick(i, ('key', 'value', 'when')) for i in w.get('ini', []) if not _nvidia_only(i)]
        if ini:
            entry['ini'] = ini
        launch = [i for i in w.get('launch', []) if not _nvidia_only(i)]
        if launch:
            entry['launch'] = launch
        wiki.append(entry)
    verified = []
    for v in data['verified']:
        entry = _pick(v, VERIFIED_FIELDS)
        entry['game_settings'] = [_pick(s, SETTING_FIELDS) for s in v.get('game_settings', [])]
        verified.append(entry)
    community = []
    for c in data.get('community', []):
        entry = _pick(c, COMMUNITY_FIELDS)
        entry['game_settings'] = [_pick(s, SETTING_FIELDS) for s in c.get('game_settings', [])]
        entry['reports'] = len(c.get('reports', []))
        community.append(entry)
    builds = data.get('optiscaler_builds', {})
    return dict(schema=data['schema'], generated_by='research/recipes/build_recipes.py --compact',
                full=dict(file='packaging/recipes/recipes.json', sha256=full_sha256), sources=data['sources'], wiki_url=base,
                verified=verified, community=community,
                leave_auto={exe: [_pick(i, ('key', 'quirk')) for i in items] for exe, items in data['leave_auto'].items()},
                backports={exe: {key: _pick(b, ('value',)) for key, b in keys.items()} for exe, keys in data['backports'].items()},
                quirk_keys=data.get('quirk_keys', {}),
                optiscaler_builds={c: _pick(b, ('dll_sha256', 'ini_sha256')) for c, b in builds.items()},
                optiscaler_ini_keys={b['ini_sha256']: b['keys'] for b in builds.values() if 'keys' in b}, wiki=wiki)


def compact_text(full_text):
    return dumps_compact(compact(json.loads(full_text), hashlib.sha256(full_text.encode()).hexdigest()))


def write_compact(full=OUT, out=COMPACT):
    raw = Path(full).read_text()
    text = compact_text(raw)
    Path(out).write_text(text)
    print(f'{out}: {len(text.encode()) / 1024:.1f} KiB from {full} ({len(raw.encode()) / 1024:.1f} KiB)')


# --------------------------------------------------------------------------------------------- refreshing inputs
def wiki(drafts, readable=None, dropped=None):
    """wiki.json's entries from research drafts (SCHEMA.md): one entry per wiki title, facts only. readable: the INI
    keys (lower case) the shipped build reads (others are dropped and named in dropped, a list)."""
    by = {}
    for f in sorted(Path(drafts).glob('*.json')):
        for e in read(f)['entries']:
            key = norm(e['title'])
            if not key:
                continue
            w = by.setdefault(key, dict(title=re.sub(r'\s*\((FG Options page|Fakenvapi page|OptiFG page)\)', '', e['title']),
                                        pages=[], tested={}, upscaler_inputs=[], fg_inputs=[], fg_advice=[], ini=[], launch=[],
                                        proxy=[], game_settings=[], counts={}))
            page = e['source'].get('page') or ('Compatibility-List' if e['source']['kind'] == 'compat-list' else None)
            if page and page not in w['pages']:
                w['pages'].append(page)
            for k in ('optiscaler', 'os', 'gpu'):
                for v in (e.get('tested') or {}).get(k, []) or []:
                    w['tested'].setdefault(k, [])
                    if v not in w['tested'][k]:
                        w['tested'][k].append(v)
            if (e.get('tested') or {}).get('linux'):
                w['tested']['linux'] = True
            # The compatibility list's verdict (working, not-working, single-os) and its OptiPatcher column.
            if e.get('compat'):
                w['compat'] = e['compat']
            if e.get('optipatcher') is not None:
                w['optipatcher'] = w.get('optipatcher', False) or bool(e['optipatcher'])
            for name in e.get('proxy') or []:
                if name not in w['proxy']:
                    w['proxy'].append(name)
            for k in ('upscaler_inputs', 'fg_inputs'):
                for v in e.get(k) or []:
                    if v not in w[k]:
                        w[k].append(v)
            for i in e['items']:
                if i.get('struck'):
                    continue
                w['counts'][i['type']] = w['counts'].get(i['type'], 0) + 1
                # Every condition the page states (packaging/compat.py evaluates them; unknown ones are never applied).
                when = dict(i.get('when') or {})
                if i['type'] == 'fg-input' and i.get('input') and i.get('advice'):
                    a = dict(advice=i['advice'], input=i['input'], **({'when': when} if when else {}))
                    if a not in w['fg_advice']:
                        w['fg_advice'].append(a)
                elif i['type'] == 'ini' and i.get('key') and i.get('value') is not None and i.get('confidence') == 'high':
                    if readable is not None and i['key'].lower() not in readable:
                        if dropped is not None:
                            dropped.append(f"{e['title']}: {i['key']}")
                        continue
                    a = dict(key=i['key'], value=str(i['value']), **({'when': when} if when else {}))
                    if a not in w['ini']:
                        w['ini'].append(a)
                elif i['type'] == 'proxy' and i.get('name'):
                    if i['name'] not in w['proxy']:
                        w['proxy'].append(i['name'])
                elif i['type'] == 'game-setting' and i.get('key') and i.get('value') is not None and i.get('confidence') == 'high':
                    a = dict(file=i.get('file'), key=i['key'], value=str(i['value']))
                    if a not in w['game_settings']:
                        w['game_settings'].append(a)
                elif i['type'] == 'launch' and i.get('args'):
                    # One item as the page gives it: its tokens in order, its condition and the extraction's confidence.
                    a = dict(args=[str(a) for a in i['args']], **({'when': when} if when else {}), confidence=i.get('confidence'))
                    if a not in w['launch']:
                        w['launch'].append(a)
    out = []
    for w in by.values():
        out.append({k: w[k] for k in WIKI_FACTS if k in w and w[k] not in ([], {})})
    return sorted(out, key=lambda w: (w['title'].casefold(), w['title']))


def refresh_wiki(drafts, commit, date, folder=HERE):
    """wiki.json from research drafts at a wiki commit; the dropped INI items (keys the pinned build does not define)
    are printed."""
    path = Path(folder) / 'wiki.json'
    doc, dropped = read(path), []
    if not re.fullmatch(r'[0-9a-f]{40}', commit or '') or not re.fullmatch(r'\d{4}-\d\d-\d\d', date or ''):
        raise SystemExit('--wiki-drafts needs --wiki-commit (the full commit) and --wiki-date (YYYY-MM-DD)')
    doc['entries'] = wiki(drafts, build_keys(read(Path(folder) / 'optiscaler.json')), dropped)
    doc['wiki'] = dict(doc['wiki'], commit=commit, date=date)
    path.write_text(dumps_rows(doc, 'entries'))
    print(f'{path}: {len(doc["entries"])} entries; dropped {len(dropped)} INI items no shipped key reads: ' + '; '.join(dropped))


def ini_keys(data):
    """The keys an OptiScaler.ini defines, as Section.key (configparser's lower-case key, as the installer reads it)."""
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.read_string(data.decode('utf-8-sig'))
    return sorted(f'{s}.{k}' for s in parser.sections() for k in parser[s])


def add_build(commit, dll_sha256, ini, folder=HERE):
    """Record an OptiScaler build in optiscaler.json: its DLL digest, its OptiScaler.ini's digest and that INI's keys
    (one list per digest; a list no build uses any more goes)."""
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or not re.fullmatch(r'[0-9a-f]{64}', dll_sha256):
        raise SystemExit('--add-build needs the full commit and the DLL\'s SHA-256 (lower-case hex)')
    path, data = Path(folder) / 'optiscaler.json', Path(ini).read_bytes()
    opti, sha = read(path), hashlib.sha256(data).hexdigest()
    opti['builds'][commit] = dict(dll_sha256=dll_sha256, ini_sha256=sha)
    opti['ini_keys'][sha] = ini_keys(data)
    opti['ini_keys'] = {k: v for k, v in opti['ini_keys'].items() if any(b['ini_sha256'] == k for b in opti['builds'].values())}
    path.write_text(dumps(opti))
    print(f'{path}: build {commit[:8]}, {len(opti["ini_keys"][sha])} INI keys')


# C constants in quirk values, as the integers OptiScaler reads from its INI (d3d12.h).
CONSTANTS = {'D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE': '64'}


def quirk_rules(quirks, verified_exes, readable):
    """(leave_auto, backports, quirk_keys, commits) from a quirk extraction (quirks2.py: pinned and upstream entries
    and config-level effects). readable: the INI keys (lower case) the pinned build reads; a backport of any other key
    would do nothing."""
    pinned, upstream = quirks['pinned'], quirks['upstream']
    # Q3: installer defaults that a runtime quirk for the exe would set otherwise.
    leave_auto = {}
    for name, sets in pinned['config_level'].items():
        for s in sets:
            if s['ini'] in INSTALLER_KEYS and s['respects_user'] and s['ini'] != 'XeFG.ForceBorderless':
                for e in pinned['entries']:
                    if name in e['quirks']:
                        for exe in e['exes']:
                            leave_auto.setdefault(exe, []).append(dict(key=s['ini'], quirk=name, value=s['value']))
    # Q2: config-level quirks upstream has and the pin lacks, per exe (key set only where auto).
    # OptiScaler ORs every table entry naming the exe (getQuirksForExe / ApplyGameConfigs), so merge them (a dict
    # comprehension kept only the last entry: horizonforbiddenwest.exe's AllowedFrameAhead2 looked new).
    old = {}
    for e in pinned['entries']:
        for exe in e['exes']:
            old.setdefault(exe, set()).update(e['quirks'])
    backports = {}
    for e in upstream['entries']:
        for exe in e['exes']:
            if exe in verified_exes:
                continue  # a local recipe decides (RULES.md Q2: CONTROL Resonant keeps its preserved swap chain)
            for name in sorted(set(e['quirks']) - old.get(exe, set())):  # sorted: the same file on every build
                for s in upstream['config_level'].get(name, []):
                    if s['respects_user'] and not s['condition'] and s['ini'].lower() in readable and s['ini'] not in INSTALLER_KEYS:
                        backports.setdefault(exe, {})[s['ini']] = dict(value=CONSTANTS.get(s['value'], s['value']), quirk=name,
                                                                       comment=e['comment'][:1])
    # Q3 generalised: every INI key a runtime quirk of the shipped build sets for the exe ("value@condition" when the
    # quirk applies only under a condition). Community recipes, promoted wiki items and detection never write these.
    quirk_keys = {}
    for e in pinned['entries']:
        for name in e['quirks']:
            for s in pinned['config_level'].get(name, []):
                if s.get('ini'):
                    value = str(CONSTANTS.get(s['value'], s['value'])) + ('@' + s['condition'] if s.get('condition') else '')
                    for exe in e['exes']:
                        quirk_keys.setdefault(exe.lower(), {})[s['ini']] = value
    quirk_keys = {exe: dict(sorted(keys.items())) for exe, keys in sorted(quirk_keys.items())}
    return leave_auto, backports, quirk_keys, dict(pinned=pinned['commit'], upstream=upstream['commit'])


def exe_titles(quirks):
    """exe -> normalized title from the first comment line of its quirk entry (links a game exe to its wiki page)."""
    out = {}
    for e in quirks['upstream']['entries']:
        if e['comment'] and len(e['exes']) <= 2:
            out.update({exe: loose(e['comment'][0]) for exe in e['exes']})
    return out


def refresh_quirks(path, folder=HERE):
    """optiscaler.json's quirk tables from a quirk extraction whose pinned side is a build with the shipped quirks."""
    quirks, target = read(path), Path(folder) / 'optiscaler.json'
    opti = read(target)
    if quirks['pinned']['commit'] not in {opti['pinned'], *opti['compatible_commits']}:
        raise SystemExit('the quirk extraction\'s pinned side is no build optiscaler.json lists as pinned or compatible')
    exes = {exe for v in verified_recipes(Path(folder) / 'verified') for exe in v['match'].get('exe', [])}
    leave_auto, backports, quirk_keys, commits = quirk_rules(quirks, exes, build_keys(opti, quirks['pinned']['commit']))
    opti['quirks'] = dict(about=opti['quirks']['about'], pinned=commits['pinned'], upstream=commits['upstream'],
                          leave_auto=leave_auto, backports=backports, quirk_keys=quirk_keys, titles=dict(sorted(exe_titles(quirks).items())))
    target.write_text(dumps(opti))
    print(f'{target}: leave_auto {len(leave_auto)} exes, backports {len(backports)} exes, quirk_keys {len(quirk_keys)} exes')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--check', action='store_true', help='compare instead of writing; exit status 1 when a file is stale')
    ap.add_argument('--compact', action='store_true', help='only rebuild the compact runtime file from the full file')
    ap.add_argument('--wiki-drafts', type=Path, help='rewrite wiki.json from research drafts (SCHEMA.md), then rebuild')
    ap.add_argument('--wiki-commit', help='the wiki commit the drafts were read at (with --wiki-drafts)')
    ap.add_argument('--wiki-date', help='its date, YYYY-MM-DD (with --wiki-drafts)')
    ap.add_argument('--add-build', nargs=3, metavar=('COMMIT', 'DLL_SHA256', 'OPTISCALER_INI'),
                    help='record an OptiScaler build\'s digests and INI keys in optiscaler.json, then rebuild')
    ap.add_argument('--quirks', type=Path, help='rewrite optiscaler.json\'s quirk tables from a quirk extraction, then rebuild')
    a = ap.parse_args()
    if a.compact:
        write_compact()
        return
    if a.wiki_drafts:
        refresh_wiki(a.wiki_drafts, a.wiki_commit, a.wiki_date)
    if a.add_build:
        add_build(*a.add_build)
    if a.quirks:
        refresh_quirks(a.quirks)
    data = build()
    full = dumps(data)
    small = compact_text(full)
    if a.check:
        stale = [str(p) for p, text in ((OUT, full), (COMPACT, small)) if not p.is_file() or p.read_text() != text]
        if stale:
            sys.exit('stale (run research/recipes/build_recipes.py): ' + ', '.join(stale))
        print('up to date')
        return
    OUT.write_text(full)
    COMPACT.write_text(small)
    print(f'{OUT}: {len(full.encode()) / 1024:.1f} KiB; verified {len(data["verified"])}, wiki {len(data["wiki"])} '
          f'({sum(1 for w in data["wiki"] if w.get("launch_args"))} with DX12 launch args, '
          f'{sum(1 for w in data["wiki"] if "exe" in w["match"])} with exe), leave_auto {len(data["leave_auto"])} exes, '
          f'backports {len(data["backports"])} exes, quirk_keys {len(data["quirk_keys"])} exes, '
          f'promoted {sum(len(w.get("promoted", [])) for w in data["wiki"])} items, community {len(data["community"])} recipes')
    print(f'{COMPACT}: {len(small.encode()) / 1024:.1f} KiB')


if __name__ == '__main__':
    main()
