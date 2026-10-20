#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build packaging/recipes/recipes.json, the per-game recipe file with its provenance (rules: RULES.md), and from it
packaging/recipes/recipes-runtime.json, the compact file a package ships as recipes/recipes.json.

- verified-bc250: this host's library games (local-library.json), minus the installer's generic keys. Applied.
- community-bc250: reviewed recipes from other BC-250 owners (community/*.json, CONTRIBUTING.md), validated against the
  rules RULES.md sets for recipes. Applied, labelled as community reports.
- quirks: OptiScaler exes whose runtime quirk sets a key the installer writes by default (rule Q3), every key a quirk
  sets per exe (quirk_keys: nothing below a verified recipe writes those, Q3 generalised), and upstream quirks newer
  than the shipped build (Q2), all from quirks.json (research/recipes/quirks2.py).
- wiki-reported: one entry per wiki title (drafts/ at the commit sources.lock.json pins): facts only (page link, tested
  versions, inputs, INI keys with every condition the page states, launch arguments, FG advice, proxy names, the
  compatibility list's verdict, game-setting keys), no copied prose. DX12 launch arguments are applied (L1), broken FG
  inputs veto the automatic choice (V1), the reviewed INI items of wiki_promote.json are applied where their conditions
  hold (P1); the rest is shown (packaging/compat.py evaluates every condition against the install).

--compact rebuilds only the compact file from the existing full file (no research inputs needed).
"""
import argparse, hashlib, json, os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'packaging/recipes/recipes.json'
COMPACT = ROOT / 'packaging/recipes/recipes-runtime.json'
WIKI = 'https://github.com/optiscaler/OptiScaler/wiki/'
DX12_ARGS = {'-dx12', '-d3d12', '-force-d3d12'}
# What the drafts record beside a condition (SCHEMA.md): explanations, never limits on where an item applies.
NOTE_KEYS = {'reason', 'purpose', 'note', 'autoapplied_since', 'value', 'feature'}
# The pinned sources of a recipes build (wiki commit, OptiScaler builds): RULES.md "Wiki refresh".
LOCK = HERE / 'sources.lock.json'
PROMOTE = HERE / 'wiki_promote.json'
COMMUNITY = HERE / 'community'

INSTALLER_KEYS = {'Upscalers.Dx12Upscaler', 'FSR.UpscalerIndex', 'FSR.Fsr4ForceModel', 'FSR.Fsr4EnableWatermark',
                  'FrameGen.Enabled', 'fakenvapi.UseFakenvapi', 'FrameGen.FGInput', 'FrameGen.FGOutput',
                  'Libraries.XeFGPath', 'Libraries.XeLLPath', 'XeFG.ForceBorderless', 'Plugins.LoadAsiPlugins',
                  'XeFG.InterpolationCount', 'FrameGen.DisableHudless', 'fakenvapi.ForceReflex'}
# Values only this host's FSR4 owner or logging uses: not part of a game's recipe.
HOST_ONLY = {'Log.LogToFile', 'Log.LogLevel', 'Log.LogToConsole', 'Log.LogToNGX', 'Log.LogToDebug', 'BC250.Managed',
             'BC250.AppId', 'BC250.Version'}
# Why each verified game's non-generic values exist (the maintainers' BC-250 reports; kept short, shown in Setup).
NOTES = {
    '3669870': 'Hangs at the Remedy logo while the XeFG swap chain is created unless the game\'s DLSS Frame Generation '
               'is on: DLSS FG input plus m_eDLSSFGMode 1 in renderer.ini (created by the game on first start).',
    '1771300': 'OptiFG input; HUDLimit 1 is kept for the OptiScaler menu\'s HUDFix toggle (HUDFix itself stays off).',
    '3321460': 'FSR 3.1 FG input with the game\'s frame generation on (native Anti-Lag 2), although the game also ships '
               'XeSS FG.',
    '3156770': 'DLSS FG input; the game\'s DLSS_FG setting is turned on.',
    '1681430': 'FSR FG input needs the game\'s AMD frame generation; the game\'s FSR 3.0 FG may not reach OptiScaler.',
    '3404260': 'FSR FG input generates only with the game\'s own frame generation on (FrameGenerationMode).',
    '1343240': 'Needs an in-game resolution scale above 100% for the upscaler to run; DX12 via -dx12.',
    '482400': 'DX12 via -dx12 (the default DX11 path does not reach the upscaler).',
}


# What each verified game showed on a BC-250 (public COMPATIBILITY.md "Supported games"): the evidence level
# packaging/compat.py shows (gameplay: generated in gameplay; generates: 2.0 presents per game frame, context not
# recorded; startup: at start-up or in the menu; installed: generation not checked; fails: a known open problem) and the
# observation.
EVIDENCE = {
    '3669870': ('generates', '2.0 presents per game frame'), '3321460': ('gameplay', 'played at 2x'),
    '1423049311': ('gameplay', 'played at 2x'), '3404260': ('generates', '2.0'), '1836730': ('generates', '2.0'),
    '1771300': ('gameplay', '2.0 in gameplay'), '1681430': ('generates', '2.0'), '482400': ('startup', '2.0 at start-up'),
    '731040': ('gameplay', '2.0 in gameplay'), '2464530': ('generates', '2.0'), '3156770': ('gameplay', '2.0; played at 2x'),
    '3751950': ('installed', 'installed; generation not checked'), 'fa4240e57a3c46b39f169041b7811293': ('installed', 'installed; generation not checked'),
    'Heather': ('installed', 'installed; generation not checked'), '1466060': ('installed', 'installed; generation not checked'),
    '1343240': ('installed', 'installed; generation not checked'), '1881200': ('installed', 'installed; generation not checked'),
    '3228590': ('fails', 'does not generate yet'), '548430': ('fails', 'did not generate: choose an upscaler once in the game\'s Video menu'),
}


# Store editions of the same game: "Crimson Desert Enhanced", "The Witcher 3: Wild Hunt - Game of the Year Edition".
EDITION = re.compile(r'(\s+(game of the year|goty|enhanced|definitive|complete|deluxe|gold|ultimate|anniversary|remastered|'
                     r'directors cut|standard|premium)(\s+edition)?)+$')


def norm(title):
    t = re.sub(r'\([^)]*\)', '', title.lower()).replace('&', 'and').replace('’', "'").replace('‐', '-')
    t = re.sub(r"[^a-z0-9]+", ' ', t.replace("'", '')).strip()
    t = re.sub(r'\b(ii)\b', '2', t)
    t = re.sub(r'\b(iii)\b', '3', t)
    return EDITION.sub('', t).strip()


def verified(local):
    out = []
    for g in local['games']:
        ini = {k: v['value'] for k, v in g['ini'].items()
               if k not in INSTALLER_KEYS and k not in HOST_ONLY and 'fsr4-baseline' not in v['origin']
               and v['origin'] != ['installer']}
        match = dict(exe=[g['exe']])
        if g['appid'].isdecimal():
            match['steam'] = [g['appid']]
        elif g['appid'].startswith('gog-'):
            match['gog'] = [g['appid'][4:]]
        elif g['appid'].startswith('epic-'):
            match['epic'] = [g['appid'][5:]]
        settings = []
        for s in g['game_side']:
            # Only what is in effect on this host counts as local (VOIN and TRYP FPV delete the Engine.ini the owner wrote).
            if not s.get('values') or not s.get('in_effect'):
                continue
            fmt = s.get('format') or ('xml-option' if s['file'].endswith('.xml') else 'ini')
            # Engine.ini motion-vector tweaks help XeFG output whatever the input; the rest are FG toggles for the recipe's input.
            general = fmt == 'ini' and s.get('section') == 'SystemSettings'
            settings.append(dict(file=s['file'], base='steamuser', format=fmt, section=s.get('section'), values=s['values'],
                                 why=s.get('why'), requires_fg_input=None if general or g['route'] == 'native' else g['fg_input']))
        key = g['appid'].split('-', 1)[1] if g['appid'].startswith(('gog-', 'epic-')) else g['appid']
        level, observed = EVIDENCE.get(key, (None, None))
        entry = dict(title=g['title'], match=match, status='verified-bc250', route=g['route'],
                     fg_input=None if g['route'] == 'native' else g['fg_input'], ini=ini, game_settings=settings,
                     launch_args=[a for a in g['launch_args'] if a in DX12_ARGS], note=NOTES.get(g['appid']),
                     evidence=level, observed=observed)
        out.append(entry)
    return out


# C constants in quirk values, as the integers OptiScaler reads from its INI (d3d12.h).
CONSTANTS = {'D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE': '64'}


# The OptiScaler build backports are checked against (quirks.json's pinned side is the same build). Tester v26 ships
# nightly-20260929 (upstream 92337ebf): re-derive against that build before the next recipes build (RULES.md Q2).
# Its source tree: XEMFG_OPTISCALER_SOURCE, else the fork checkout in XEMFG_WORK (release/inputs.lock.json
# work.optiscaler-fork.source.source_in_work), else --optiscaler. Only a full build reads it (not --compact).
def _pinned_optiscaler():
    if os.environ.get('XEMFG_OPTISCALER_SOURCE'):
        return Path(os.environ['XEMFG_OPTISCALER_SOURCE'])
    if os.environ.get('XEMFG_WORK'):
        return Path(os.environ['XEMFG_WORK']) / 'fg-controls/OptiScaler'
    return None


PINNED_OPTISCALER = _pinned_optiscaler()


def pinned_keys(source=PINNED_OPTISCALER):
    """INI keys an OptiScaler build reads; a backport of any other key would do nothing. source: its Config.cpp, a
    source tree holding it (OptiScaler/Config.cpp or Config.cpp), or the OptiScaler.ini the build ships."""
    if source is None:
        raise SystemExit('No OptiScaler source for the backport check: set XEMFG_OPTISCALER_SOURCE or XEMFG_WORK, or pass '
                         '--optiscaler')
    source = Path(source)
    if source.is_dir():
        source = next((p for p in (source/'OptiScaler/Config.cpp', source/'Config.cpp') if p.is_file()), source/'Config.cpp')
    text = source.read_text(errors='replace')
    if source.suffix.lower() == '.ini':
        keys, section = set(), None
        for line in text.splitlines():
            header = re.fullmatch(r'\s*\[([^\]]+)\]\s*', line)
            key = re.match(r'\s*([^;#=\s][^=]*?)\s*=', line)
            if header:
                section = header[1].strip()
            elif key and section:
                keys.add(f'{section}.{key[1]}')
        return keys
    return {f'{s}.{k}' for s, k in re.findall(r'set_from_config\(\s*read\w+\(\s*"([^"]+)"\s*,\s*"([^"]+)"', text)}


def apply_changes(ver, changes):
    """Curated changes (verified-changes.json) on top of the host's in-effect values: input moves, game settings."""
    by_id = {}
    for entry in ver:
        for key in ('steam', 'gog', 'epic'):
            for i in entry['match'].get(key, []):
                by_id[{'steam': '', 'gog': 'gog-', 'epic': 'epic-'}[key] + i] = entry
    for appid, change in changes['games'].items():
        entry = by_id[appid]
        if 'fg_input' in change:
            entry['fg_input'] = change['fg_input']
            # Settings tied to the old input no longer apply.
            entry['game_settings'] = [s for s in entry['game_settings'] if s.get('requires_fg_input') is None]
            entry['ini'] = {k: v for k, v in entry['ini'].items() if k.split('.')[0].lower() not in ('framegen', 'fsrfg', 'optifg', 'dlssg')}
        for s in change.get('game_settings', []):
            entry['game_settings'] = [x for x in entry['game_settings'] if x['file'] != s['file']]
            entry['game_settings'].append(dict(file=s['file'], base='steamuser', format=s['format'], section=s.get('section'),
                                               values=s['values'], why=change['why'], requires_fg_input=entry['fg_input']))
        if not change.get('verified', True):
            entry['pending_verification'] = change['why']
        entry['note'] = ((entry.get('note') or '') + ' ' + change['why']).strip()


def quirk_rules(quirks, verified_exes, optiscaler=PINNED_OPTISCALER):
    pinned, upstream = quirks['pinned'], quirks['upstream']
    readable = pinned_keys(optiscaler)
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
                    if s['respects_user'] and not s['condition'] and s['ini'] in readable and s['ini'] not in INSTALLER_KEYS:
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


def readable_keys(source):
    """INI keys (lower case) the shipped OptiScaler build reads: its Config.cpp read*() calls and its OptiScaler.ini."""
    sys.path.insert(0, str(HERE))
    import check_drafts
    # Without its OptiScaler.ini, keys only the INI lists would be dropped silently and recipes.json would differ.
    root = Path(source) if Path(source).is_dir() else Path(source).parent
    if check_drafts.ini_path(source) is None or not any(p.is_file() for p in (root/'OptiScaler/Config.cpp', root/'Config.cpp')):
        raise SystemExit(f'No OptiScaler.ini and Config.cpp found with {source}: pass the OptiScaler source tree (or the '
                         'Config.cpp inside it)')
    return set(check_drafts.config_keys(source))


def wiki(drafts, readable=None, dropped=None):
    """One entry per wiki title. readable: the INI keys the shipped build reads (others are dropped and named in
    dropped, a list)."""
    by = {}
    for f in sorted(drafts.glob('*.json')):
        for e in json.loads(f.read_text())['entries']:
            key = norm(e['title'])
            if not key:
                continue
            w = by.setdefault(key, dict(title=re.sub(r'\s*\((FG Options page|Fakenvapi page|OptiFG page)\)', '', e['title']),
                                        match=dict(title=[key]), status='wiki-reported', pages=[], tested={}, upscaler_inputs=[],
                                        fg_inputs=[], fg_advice=[], ini=[], launch_args=[], other_launch_args=[], proxy=[],
                                        game_settings=[], counts={}))
            page = e['source'].get('page')
            if page:
                url = WIKI + page
                if url not in w['pages']:
                    w['pages'].append(url)
            elif e['source']['kind'] == 'compat-list' and WIKI + 'Compatibility-List' not in w['pages']:
                w['pages'].append(WIKI + 'Compatibility-List')
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
            if e.get('optipatcher'):
                w['optipatcher'] = True
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
                conditions = {k for k in when if k not in NOTE_KEYS}
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
                elif i['type'] == 'launch':
                    for arg in i.get('args') or []:
                        target = w['launch_args'] if arg.lower() in DX12_ARGS and i.get('confidence') == 'high' and not conditions else w['other_launch_args']
                        if arg not in target:
                            target.append(arg)
    for w in by.values():
        for k in [k for k, v in w.items() if v in ([], {})]:
            del w[k]
    return sorted(by.values(), key=lambda w: w['match']['title'][0])


def promote(wk, path=PROMOTE):
    """Attach the reviewed wiki INI items of wiki_promote.json (decision "promote") to their wiki entries as
    "promoted" (RULES.md P1). Each must be an INI item of that entry in the drafts (same key and value) and a key no rule
    keeps out of automatic writes; a reviewed item that is not refuses the build."""
    sys.path.insert(0, str(ROOT / 'packaging'))
    import compat
    review = json.loads(Path(path).read_text())
    by = {w['match']['title'][0]: w for w in wk}
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


# What a community recipe may hold (CONTRIBUTING.md "Game recipes"; RULES.md C1).
COMMUNITY_KEYS = {'title', 'match', 'status', 'route', 'fg_input', 'ini', 'game_settings', 'launch_args', 'manual_steps',
                  'known_problems', 'reports', 'reviewed_by', 'reviewed', 'note'}
REPORT_KEYS = {'issue', 'freefg', 'package_sha256', 'proton', 'mesa', 'kernel', 'gamescope', 'hdr', 'vrr', 'resolution',
               'upscaler_mode', 'ratio', 'minutes', 'starts', 'restore_checked', 'date'}
SETTING_FORMATS = ('json', 'json-options', 'xml-option', 'ini-replace', 'ini')


def check_community(entry, quirk_keys=None, readable=None):
    """Problems with one community recipe (an empty list when it may be built in)."""
    sys.path.insert(0, str(ROOT / 'packaging'))
    import compat
    problems = [f'unknown field {k}' for k in sorted(set(entry) - COMMUNITY_KEYS)]
    for k in ('title', 'match', 'status', 'route', 'reports', 'reviewed_by', 'reviewed'):
        if not entry.get(k):
            problems.append(f'missing {k}')
    m = entry.get('match') or {}
    if not any(m.get(k) for k in ('steam', 'gog', 'epic')) and not (m.get('exe') and (m.get('title') or entry.get('title'))):
        problems.append('match needs a launcher ID (steam, gog, epic) or exe names with the title')
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
        entry = json.loads(f.read_text())
        problems = check_community(entry, quirk_keys, readable)
        if problems:
            raise SystemExit(f'{f.name}: ' + '; '.join(problems))
        out.append(entry)
    return out


def exe_titles(quirks):
    """exe -> normalized title from the first comment line of its quirk entry (links a game exe to its wiki page)."""
    out = {}
    for e in quirks['upstream']['entries']:
        if e['comment'] and len(e['exes']) <= 2:
            out.update({exe: norm(e['comment'][0]) for exe in e['exes']})
    return out


# What packaging/recipes.py and install.py read from each part of the file; the compact runtime file keeps only these.
# Keep in step with them: test_recipes.py proves the full and compact files resolve every game alike.
VERIFIED_FIELDS = ('title', 'match', 'route', 'fg_input', 'ini', 'game_settings', 'launch_args', 'note', 'evidence', 'observed')
COMMUNITY_FIELDS = VERIFIED_FIELDS + ('status', 'manual_steps', 'known_problems')
# requires_fg_input is kept whenever present, even as null: a missing key means "the recipe's own input".
SETTING_FIELDS = ('file', 'format', 'section', 'values', 'requires_fg_input')
WIKI_FIELDS = ('title', 'match', 'pages', 'launch_args', 'other_launch_args', 'tested', 'proxy', 'compat', 'optipatcher',
               'game_settings', 'promoted', 'counts')
SHOWN_ADVICE = ('prefer', 'broken', 'avoid')  # recipes.suggestions lists only these


def _pick(entry, fields):
    return {k: entry[k] for k in fields if k in entry}


def _nvidia_only(item):
    """Wiki advice and settings recipes.suggestions never shows (it skips NVIDIA-only conditions)."""
    return 'nvidia' in str(item.get('when', {}).get('gpu', '')).lower()


def compact(data, full_sha256):
    """The runtime recipe file: the fields the installer reads, wiki advice and settings it can show, and wiki page
    links relative to wiki_url (recipes.load restores them). sources and the full file's digest say where it came from."""
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
    return dict(schema=data['schema'], generated_by='research/recipes/build_recipes.py --compact',
                full=dict(file='packaging/recipes/recipes.json', sha256=full_sha256), sources=data['sources'], wiki_url=base,
                verified=verified, community=community,
                leave_auto={exe: [_pick(i, ('key', 'quirk')) for i in items] for exe, items in data['leave_auto'].items()},
                backports={exe: {key: _pick(b, ('value',)) for key, b in keys.items()} for exe, keys in data['backports'].items()},
                quirk_keys=data.get('quirk_keys', {}), wiki=wiki)


def write_compact(full=OUT, out=COMPACT):
    raw = full.read_bytes()
    text = json.dumps(compact(json.loads(raw), hashlib.sha256(raw).hexdigest()), ensure_ascii=False, separators=(',', ':')) + '\n'
    out.write_text(text)
    print(f'{out}: {len(text) // 1024} KiB from {full} ({len(raw) // 1024} KiB)')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--optiscaler', type=Path, default=PINNED_OPTISCALER,
                    help='the shipped OptiScaler build: its source tree, or the Config.cpp inside it (backport check and the INI keys it reads)')
    ap.add_argument('--compact', action='store_true', help='only rebuild the compact runtime file from the full file')
    a = ap.parse_args()
    if a.compact:
        write_compact()
        return
    local = json.loads((HERE / 'local-library.json').read_text())
    quirks = json.loads((HERE / 'quirks.json').read_text())
    lock = json.loads(LOCK.read_text())
    if quirks['pinned']['commit'] != lock['optiscaler_shipped']['commit']:
        raise SystemExit('quirks.json was not derived from the shipped OptiScaler build (sources.lock.json); run quirks2.py')
    ver = verified(local)
    apply_changes(ver, json.loads((HERE / 'verified-changes.json').read_text()))
    leave_auto, backports, quirk_keys, commits = quirk_rules(quirks, {exe for v in ver for exe in v['match']['exe']}, a.optiscaler)
    readable, dropped = readable_keys(a.optiscaler), []
    wk = wiki(HERE / 'drafts', readable, dropped)
    titles = exe_titles(quirks)
    for w in wk:
        mine = w['match']['title'][0]
        # A quirk comment names the game ("The Witcher 3"); link its exe to the one wiki title it is the start of.
        # "the witcher 3 wild hunt" extends "the witcher 3"; "red dead redemption 2" is another game than "red dead redemption".
        exes = sorted(exe for exe, t in titles.items() if t == mine or (
            len(t.split()) >= 2 and mine.startswith(t + ' ') and not re.match(r'\d|[ivx]+\b', mine[len(t) + 1:])))
        if exes:
            w['match']['exe'] = exes
    promoted = promote(wk)
    comm = community(COMMUNITY, quirk_keys, readable)
    wiki_lock = lock['wiki']
    data = dict(schema=1, generated_by='research/recipes/build_recipes.py',
                sources=dict(optiscaler_pinned=commits['pinned'], optiscaler_upstream=commits['upstream'],
                             wiki=f'{wiki_lock["commit"][:7]} ({wiki_lock["date"]})', wiki_url=WIKI,
                             host='maintainers\' BC-250 library, 2026-09-29'),
                rules='research/recipes/RULES.md', verified=ver, community=comm, leave_auto=leave_auto, backports=backports,
                quirk_keys=quirk_keys, wiki=wk)
    OUT.parent.mkdir(exist_ok=True)
    text = json.dumps(data, indent=1, ensure_ascii=False) + '\n'
    OUT.write_text(text)
    print(f'{OUT}: {len(text) // 1024} KiB; verified {len(ver)}, wiki {len(wk)} '
          f'({sum(1 for w in wk if w.get("launch_args"))} with DX12 launch args, {sum(1 for w in wk if "exe" in w["match"])} with exe), '
          f'leave_auto {len(leave_auto)} exes, backports {len(backports)} exes, quirk_keys {len(quirk_keys)} exes, '
          f'promoted {promoted} items, community {len(comm)} recipes; dropped {len(dropped)} wiki INI items no shipped key reads: '
          + '; '.join(dropped))
    write_compact()


if __name__ == '__main__':
    main()
