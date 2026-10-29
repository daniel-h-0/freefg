# SPDX-License-Identifier: MIT
"""Install game-specific environment settings in launchers, without a wrapper."""
import json
import os
import re
import shlex
import sys
from pathlib import Path

from steam_config import Document

APP = ['UserLocalConfigStore', 'Software', 'Valve', 'Steam', 'apps']
KEY = re.compile(r'^[A-Za-z_][A-Za-z_0-9]*$')


def shortcut_entries(data):
    """Parse Steam's binary shortcut fields while retaining byte edit locations."""
    index = 0

    def string():
        nonlocal index
        end = data.index(b'\0', index)
        value = data[index:end].decode('utf-8', errors='surrogateescape')
        index = end+1
        return value

    def node(depth=0):
        nonlocal index
        if depth > 16:
            raise ValueError('Shortcut nesting exceeds expected format')
        result = {}
        while index < len(data):
            start = index
            kind = data[index]
            index += 1
            if kind == 8:
                return result, start
            key = string().lower()
            if key in result:
                raise ValueError('Duplicate shortcut field')
            value_start = index
            if kind == 0:
                value, close = node(depth+1)
            elif kind == 1:
                value = string()
                close = None
            elif kind in (2, 7):
                size = 4 if kind == 2 else 8
                if index+size > len(data):
                    raise ValueError('Truncated shortcut integer')
                value = int.from_bytes(data[index:index+size], 'little')
                index += size
                close = None
            else:
                raise ValueError('Unsupported shortcut field type: '+str(kind))
            result[key] = dict(value=value, start=start, value_start=value_start,
                               end=index, close=close, kind=kind)
        raise ValueError('Truncated shortcut object')

    root, _ = node()
    if index != len(data) or 'shortcuts' not in root:
        raise ValueError('Unexpected shortcut file shape')
    return root['shortcuts']['value']


def shortcut(data, appid):
    matches = [r for r in shortcut_entries(data).values()
               if r['kind'] == 0 and str(r['value'].get('appid', {}).get('value')) == appid]
    if len(matches) != 1:
        raise ValueError('Shortcut AppID is missing or ambiguous')
    return matches[0]


# vkd3d-proton's disk cache, on a driver that offers shader module identifiers (RADV does), keeps an identifier for each
# pipeline's shaders instead of their SPIR-V and recreates a cached pipeline from it with no shader module. The layer
# then cannot name the shader, and the driver hands back the pipeline it compiled before that shader's waves.txt line
# existed (vkd3d-proton cache.c, state.c; Mesa vk_pipeline.c, radv_pipeline_compute.c). Measured 2026-10-20 in Cyberpunk
# 2077 at native 2x: the three of 1.1.0's new lines that route uses applied with empty caches, none with warm ones. With
# the extension disabled vkd3d-proton caches SPIR-V, so the layer names every pipeline on every start; a cache folder of
# the installation's own holds no identifier-only entries from earlier starts, which would be translated on every one.
IDENTIFIER_EXTENSION = 'VK_EXT_shader_module_identifier'
# vkd3d-proton (a Windows DLL under Proton) builds its cache file names in MAX_PATH (260) buffers: Z:\<folder with
# backslashes>\vkd3d-proton.<program>.cache plus .write or .merge, cut short when longer (cache.c, vkd3d_platform.h).
VKD3D_PATH_LIMIT = 259


def vkd3d_cache_fits(folder, program, margin=16):
    """Whether vkd3d-proton's longest cache file name in folder, for the game's program (its .exe name), fits its
    buffers with margin characters to spare (a game that runs under another program name)."""
    longest = 'Z:' + str(folder).replace('/', '\\') + '\\vkd3d-proton.' + program + '.cache.write'
    return len(longest) + margin <= VKD3D_PATH_LIMIT


def _with_member(value, member):
    """A vkd3d-proton list value (members separated by ',' or ';') with member at its end, unless it has it already."""
    if member in re.split(r'[,;]', value):
        return value
    return value + (',' if value and value[-1] not in ',;' else '') + member


def environment(root, owner, current, runtime='xemfg', route='opti', extra=None, vkd3d_cache=None):
    """Retain the wrapper's fast path using ordinary launcher environment fields.

    runtime 'xemfg' loads the multi-frame loader (version.dll) and its addon; runtime 'xemfg-proxy' is the add-on as a
    libxess_fg.dll proxy (no loader, 2x), with its shader profile beside it in BC250-XeFG/; runtime 'xefg' is Intel's
    own 2x frame generation with the BC250 proxy, whose files sit under OptiScaler/ on the OptiScaler route. extra: further
    variables the installation sets (PROTONFIXES_DISABLE=1 after an accepted protonfix-api refusal); Restore takes them
    out like the others. vkd3d_cache: the installation's vkd3d-proton cache folder; given, vkd3d-proton gets it as its
    cache path (unless the user set one: kept, as is VKD3D_SHADER_CACHE_PATH=0) and does not use shader module
    identifiers (IDENTIFIER_EXTENSION, added to the user's VKD3D_DISABLE_EXTENSIONS)."""
    if not isinstance(current, dict) or any(not isinstance(key, str) or not KEY.fullmatch(key)
           or not isinstance(value, str) or '\0' in value for key, value in current.items()):
        raise ValueError('Launcher environment keys and values must be strings with valid names')
    result = dict(current)
    overrides = current.get('WINEDLLOVERRIDES', '')
    required = {owner.removesuffix('.dll').lower()} | ({'version'} if runtime == 'xemfg' else set())
    pieces = []
    for part in overrides.split(';'):
        if not part:
            continue
        if '=' not in part:
            raise ValueError('Unrecognized Wine override: '+part)
        names, value = part.split('=', 1)
        kept = [n for n in names.split(',') if n.lower().removesuffix('.dll') not in required]
        if kept:
            pieces.append(','.join(kept)+'='+value)
    pieces.extend(n+'=n,b' for n in sorted(required))
    result['WINEDLLOVERRIDES'] = ';'.join(pieces)
    base = root/'OptiScaler' if runtime == 'xefg' and route == 'opti' else root
    for key, first, separator in (
        ('VK_LAYER_PATH', str(base/'BC250-XeFG/layer'), ':'),
        ('VK_INSTANCE_LAYERS', 'VK_LAYER_BC250_xefg_wave', ':'),
    ):
        result[key] = separator.join(dict.fromkeys([first, *filter(None, current.get(key, '').split(separator))]))
    result['XEFG_WAVE_CONFIG'] = str(root/'OptiScaler/plugins/BC250-XeFG/shaders/waves.txt' if runtime == 'xemfg'
                                     else base/'BC250-XeFG/shaders/waves.txt')
    if current.get('BC250_XEFG_NO_STAGGERED_SUBMIT') != '0':
        result['VKD3D_CONFIG'] = ','.join(dict.fromkeys([
            *filter(None, current.get('VKD3D_CONFIG', '').split(',')), 'no_staggered_submit']))
    if vkd3d_cache is not None:
        result['VKD3D_DISABLE_EXTENSIONS'] = _with_member(current.get('VKD3D_DISABLE_EXTENSIONS', ''), IDENTIFIER_EXTENSION)
        if not current.get('VKD3D_SHADER_CACHE_PATH'):
            result['VKD3D_SHADER_CACHE_PATH'] = str(vkd3d_cache)
    for key, value in (extra or {}).items():
        if not KEY.fullmatch(key) or not isinstance(value, str) or '\0' in value:
            raise ValueError('Invalid launcher environment setting: '+str(key))
        result[key] = value
    if runtime in ('xemfg', 'xemfg-proxy'):
        # The installed addon owns its local verified payload and saved settings.
        for key in ('XEFG_GAME_PROFILE', 'BC250_XEFG_OWNER_MODULE', 'XEFG_FLOW_CAP'):
            result.pop(key, None)
    else:
        # The proxy accelerates only the OptiScaler-owned context on that route; a user's XEFG_FLOW_CAP=1 (1080p
        # generated frames) is kept.
        result.pop('XEFG_GAME_PROFILE', None)
        if route == 'opti':
            result['BC250_XEFG_OWNER_MODULE'] = owner
        else:
            result.pop('BC250_XEFG_OWNER_MODULE', None)
    return result


API_ARGS = {'-dx11', '-d3d11', '-dx12', '-d3d12', '-force-d3d11', '-force-d3d12', '-vulkan', '-force-vulkan'}


def with_args(tokens, args):
    """Game arguments from a recipe (a DX12 switch), unless the user already chose a graphics API."""
    if not args or any(t.lower() in API_ARGS for t in tokens):
        return tokens
    return tokens + [a for a in args if a not in tokens]


# One shell word: quoted or unquoted parts, no unquoted whitespace.
WORD = r'''(?:'[^']*'|"(?:[^"\\]|\\.)*"|\\.|[^\s'"\\])+'''
ASSIGNMENT = re.compile(r'\s*([A-Za-z_][A-Za-z_0-9]*)=(' + WORD + r')?(?=\s|$)')
WHOLE_WORD = re.compile(r'\s*(' + WORD + r')(?=\s|$)')


def split_steam(value):
    """(environment assignments, the rest of the options verbatim, each assignment's value as written). The user's own
    text is never re-quoted, so ~, globs and quoting in it keep their meaning."""
    if any(c in value for c in ('\n', '\r', '`', '$', '|', '&', '<', '>')):
        raise ValueError('Complex Steam launch options need explicit reconciliation')
    rest = value
    prefix = re.match(r'\s*(?:/usr/bin/env|/bin/env|env)(?=\s|$)', rest)
    if prefix:
        rest = rest[prefix.end():]
        if rest.lstrip().startswith('-'):
            raise ValueError('Advanced env flags need explicit reconciliation')
    current, written = {}, {}
    while True:
        match = ASSIGNMENT.match(rest)
        if match:
            key, raw = match.group(1), match.group(2) or ''
            words = shlex.split(raw)
            value = words[0] if words else ''
        else:
            # A whole assignment in quotes ('KEY=a;b'), as env(1) takes it and host tooling writes it.
            match = WHOLE_WORD.match(rest)
            words = shlex.split(match.group(1)) if match else []
            if len(words) != 1 or '=' not in words[0] or not KEY.fullmatch(words[0].split('=', 1)[0]):
                break
            key, value = words[0].split('=', 1)
            raw = None
        if key in current:
            raise ValueError('Duplicate launch environment setting: '+key)
        current[key], written[key] = value, raw
        rest = rest[match.end():]
    return current, rest.strip(), written


def _drop_words(text, words):
    """Remove whole shell words (as written, or in shlex quoting) from option text, leaving the rest as it was."""
    for word in words:
        for form in dict.fromkeys((word, shlex.quote(word))):
            text = re.sub(r'(^|\s)' + re.escape(form) + r'(?=\s|$)', r'\1', text)
    return re.sub(r'\s{2,}', ' ', text).strip()


def _join_steam(env, rest, written=None):
    """Assignments (a value the user wrote and that is unchanged keeps its spelling), then the rest verbatim."""
    def spelled(key, value):
        raw = (written or {}).get(key)
        return raw if raw is not None and (shlex.split(raw) or [''])[0] == value else shlex.quote(value)
    return ' '.join([*(key+'='+spelled(key, val) for key, val in env.items()), *([rest] if rest else [])])


def steam_options(value, root, owner, runtime='xemfg', route='opti', args=(), extra_env=None, vkd3d_cache=None):
    """Transform ordinary launch options; never execute shell text while editing."""
    current, rest, written = split_steam(value)
    # Wrappers of earlier wrapper-based installs (either layout; the lib2x/XeFG route's lives under OptiScaler/).
    rest = _drop_words(rest, [str(root/'BC250-XeFG/run.sh'), str(root/'OptiScaler/BC250-XeFG/run.sh')])
    tokens = shlex.split(rest)
    if not tokens:
        rest, tokens = '%command%', ['%command%']
    elif '%command%' not in tokens:
        # Steam treats options without %command% as arguments to the game.
        rest, tokens = '%command% ' + rest, ['%command%'] + tokens
    if tokens.count('%command%') != 1:
        raise ValueError('Steam options must contain one %command%')
    if any('=' in token and KEY.fullmatch(token.split('=',1)[0])
           for token in tokens[:tokens.index('%command%')]):
        raise ValueError('Nested environment assignments need explicit reconciliation')
    if any(';' in token for token in tokens):
        raise ValueError('Shell commands in Steam launch options need explicit reconciliation')
    env = environment(root, owner, current, runtime, route, extra_env, vkd3d_cache)
    added = with_args(tokens, args)[len(tokens):]
    return _join_steam(env, ' '.join([rest, *map(shlex.quote, added)]), written)


def _json(path):
    return json.loads(path.read_text())


def _readable(path, parse):
    """A launcher file parsed, or None when it is missing or unreadable. Other games' broken files must not stop an
    installation, so they are reported and skipped."""
    if not path.is_file():
        return None
    try:
        return parse(path)
    except Exception as error:  # noqa: BLE001 - any parser failure (VDF, JSON, YAML, encoding) means "skip this file"
        print('Skipped an unreadable launcher file: '+str(path)+' ('+type(error).__name__+': '+str(error)[:120]+')', file=sys.stderr)
        return None


def _inside(exe, folder):
    return bool(folder) and Path(folder).is_absolute() and exe.is_relative_to(Path(folder).resolve())


def discover(exe, home=None):
    """Match installation records by path, never by game name or recipe."""
    home = Path(home or Path.home())
    exe = exe.resolve()
    found = []
    steam_roots = {p.resolve() for p in (home/'.steam/steam', home/'.local/share/Steam',
                   home/'.var/app/com.valvesoftware.Steam/.local/share/Steam') if p.is_dir()}
    for steam in sorted(steam_roots):
        libraries = {steam}
        index = steam/'steamapps/libraryfolders.vdf'
        doc = _readable(index, lambda p: Document(p.read_bytes()))
        if doc is not None:
            for key in doc.keys(['libraryfolders']):
                if doc.has_object(['libraryfolders', key]):
                    value = doc.get(['libraryfolders', key, 'path'])
                    if value:
                        libraries.add(Path(value).resolve())
        for library in sorted(libraries):
            for path in sorted((library/'steamapps').glob('appmanifest_*.acf')):
                doc = _readable(path, lambda p: Document(p.read_bytes()))
                if doc is None:
                    continue
                directory = doc.get(['AppState', 'installdir'])
                appid = doc.get(['AppState', 'appid'])
                if directory and appid and appid.isdecimal() and _inside(exe, library/'steamapps/common'/directory):
                    for config in sorted((steam/'userdata').glob('*/config/localconfig.vdf')):
                        found.append(dict(launcher='steam', path=str(config), id=appid))
        for config in sorted((steam/'userdata').glob('*/config/shortcuts.vdf')):
            for record in (_readable(config, lambda p: shortcut_entries(p.read_bytes())) or {}).values():
                if record['kind'] != 0:
                    continue
                values = record['value']
                value = values.get('exe', {}).get('value', '')
                # Heroic/Lutris URI shortcuts inherit their actual launcher's
                # environment; only direct Windows executable shortcuts belong here.
                try:
                    command = shlex.split(value) if isinstance(value, str) else []
                except ValueError:
                    continue
                if len(command) != 1 or not command[0].lower().endswith('.exe'):
                    continue
                game_exe = Path(command[0])
                if game_exe.is_absolute() and (game_exe.resolve() == exe or _inside(exe, game_exe.parent)):
                    appid = values.get('appid', {}).get('value')
                    if isinstance(appid, int):
                        found.append(dict(launcher='steam', format='shortcuts', path=str(config), id=str(appid)))
    heroic_roots = [home/'.config/heroic', home/'.var/app/com.heroicgameslauncher.hgl/config/heroic']
    for heroic in heroic_roots:
        indices = [heroic/'legendaryConfig/legendary/installed.json',
                   heroic/'gog_store/installed.json', heroic/'nile_config/installed.json',
                   heroic/'sideload_apps/library.json']
        for index in indices:
            data = _readable(index, _json)
            if data is None:
                continue
            records = data.get('installed', data.get('games', data)) if isinstance(data, dict) else data
            rows = records.items() if isinstance(records, dict) else [(None, row) for row in records]
            for key, record in rows:
                if not isinstance(record, dict):
                    continue
                install = record.get('install', record)
                if not isinstance(install, dict):
                    continue
                folder = install.get('install_path')
                folder = folder if isinstance(folder, str) else None
                executable = install.get('executable') or record.get('executable')
                executable = executable if isinstance(executable, str) else None
                if not (_inside(exe, folder) or (executable and Path(executable).is_absolute() and _inside(exe, Path(executable).parent))):
                    continue
                appid = record.get('appName') or record.get('app_name') or key
                if appid and '/' not in str(appid):
                    config = heroic/'GamesConfig'/(str(appid)+'.json')
                    if config.is_file():
                        found.append(dict(launcher='heroic', path=str(config), id=str(appid)))
    # Lutris owns YAML. Import its standard parser only when configurations exist.
    for lutris in (home/'.config/lutris', home/'.local/share/lutris',
                   home/'.var/app/net.lutris.Lutris/config/lutris', home/'.var/app/net.lutris.Lutris/data/lutris'):
        configs = sorted((lutris/'games').glob('*.yml'))
        if not configs:
            continue
        from vendor import yaml
        for config in configs:
            data = _readable(config, lambda p: yaml.safe_load(p.read_text()))
            game = data.get('game') if isinstance(data, dict) else None
            executable = game.get('exe') if isinstance(game, dict) else None
            if isinstance(executable, str) and Path(executable).is_absolute() and _inside(exe, Path(executable).parent):
                found.append(dict(launcher='lutris', path=str(config), id=''))
    unique = {(r['launcher'], str(Path(r['path']).resolve()), r['id']): r for r in found}
    return list(unique.values())


def installation_roots(home=None):
    """Game folders whose installation a launcher entry starts: the layer path in the environment of every Steam app's
    launch options and non-Steam shortcut, Heroic game configuration and Lutris game (layer_roots). Reads only; an
    entry that cannot be read is skipped. Install.py update --all finds the games it updates so."""
    home = Path(home or Path.home())
    envs = []

    def collect(read):
        try:
            env = read()
        except Exception:  # noqa: BLE001 - one unreadable entry never hides the others
            return
        if isinstance(env, dict):
            envs.append({str(k): str(v) for k, v in env.items()})
    for steam in sorted({p.resolve() for p in (home/'.steam/steam', home/'.local/share/Steam',
                         home/'.var/app/com.valvesoftware.Steam/.local/share/Steam') if p.is_dir()}):
        for config in sorted((steam/'userdata').glob('*/config/localconfig.vdf')):
            doc = _readable(config, lambda p: Document(p.read_bytes()))
            if doc is None or not doc.has_object(APP):
                continue
            for appid in doc.keys(APP):
                collect(lambda: split_steam(doc.get(APP+[appid, 'LaunchOptions']) or '')[0])
        for config in sorted((steam/'userdata').glob('*/config/shortcuts.vdf')):
            for record in (_readable(config, lambda p: shortcut_entries(p.read_bytes())) or {}).values():
                if record['kind'] == 0:
                    collect(lambda: split_steam(record['value'].get('launchoptions', {}).get('value') or '')[0])
    for heroic in (home/'.config/heroic', home/'.var/app/com.heroicgameslauncher.hgl/config/heroic'):
        for config in sorted((heroic/'GamesConfig').glob('*.json')):
            data = _readable(config, _json)
            for settings in data.values() if isinstance(data, dict) else []:
                if isinstance(settings, dict):
                    collect(lambda: {e['key']: e['value'] for e in settings.get('enviromentOptions') or []})
    for lutris in (home/'.config/lutris', home/'.local/share/lutris',
                   home/'.var/app/net.lutris.Lutris/config/lutris', home/'.var/app/net.lutris.Lutris/data/lutris'):
        configs = sorted((lutris/'games').glob('*.yml'))
        if configs:
            from vendor import yaml
        for config in configs:
            data = _readable(config, lambda p: yaml.safe_load(p.read_text()))
            collect(lambda: ((data.get('system') or {}).get('env') or {}) if isinstance(data, dict) else None)
    return sorted({root.resolve() for env in envs for root in layer_roots(env)})


def require_stopped(launchers):
    names = set(launchers)
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            comm = (proc/'comm').read_text().strip().lower()
            if comm in names:
                raise ValueError('Close '+comm+' before installing or restoring launcher settings')
        except OSError:
            continue


def fields(target, data):
    if target['launcher'] == 'steam':
        if target.get('format') == 'shortcuts':
            return {'LaunchOptions': shortcut(data, target['id'])['value'].get('launchoptions', {}).get('value')}
        return {'LaunchOptions': Document(data).get(APP+[target['id'], 'LaunchOptions'])}
    if target['launcher'] == 'heroic':
        settings = json.loads(data)[target['id']]
        # launcherArgs only when this installation manages them (records before recipes lack the field).
        keys = tuple(target['before']) if 'before' in target else ('enviromentOptions', 'wrapperOptions') + (
            ('launcherArgs',) if target.get('args') else ())
        return {key: settings.get(key) for key in keys}
    from vendor import yaml
    settings = (yaml.safe_load(data).get('system') or {})
    return {key: settings.get(key) for key in ('env', 'prefix_command')}


def _json_layout(data):
    """How a JSON launcher file is laid out, so an edit keeps it: Heroic writes JSON.stringify(settings, null, 2), a
    two-space indent with UTF-8 text as it is and no final line ending."""
    bom = data.startswith(b'\xef\xbb\xbf')
    body = data[3:] if bom else data
    if b'\n' in body.strip():
        first = re.search(rb'\n([ \t]+)\S', body)
        indent, separators = (first.group(1).decode() if first else ''), (',', ': ')
    else:
        indent, separators = None, ((', ', ': ') if re.search(rb'":\s', body) else (',', ':'))
    # \u escapes of non-ASCII characters and no raw ones: written by an ASCII-only writer (Python's default).
    escaped = body.isascii() and re.search(rb'\\u(?:00[89a-fA-F]|0[1-9a-fA-F]|[1-9a-fA-F])', body) is not None
    return dict(bom=bom, crlf=b'\r\n' in body, final=body.endswith(b'\n'), indent=indent, separators=separators,
                ensure_ascii=escaped)


def _dump_json(doc, layout):
    def dump(ensure_ascii):
        text = json.dumps(doc, indent=layout['indent'], separators=layout['separators'], ensure_ascii=ensure_ascii)
        text += '\n' if layout['final'] else ''
        return (b'\xef\xbb\xbf' if layout['bom'] else b'') + (text.replace('\n', '\r\n') if layout['crlf'] else text).encode()
    try:
        return dump(layout['ensure_ascii'])
    except UnicodeEncodeError:  # a lone surrogate (an escape the file held) has no UTF-8 form
        return dump(True)


# Launchers whose per-game file the installer rewrites whole (JSON, YAML): the installation keeps a copy of the file as
# it found it, and Restore writes that copy back when the restored file holds the same settings (only the layout of a
# rewrite would differ). Steam's files are edited in place, byte for byte, and need no copy.
WHOLE_FILE = ('heroic', 'lutris')


def _ordered(value):
    """value with dict order and scalar types made part of equality (True is not 1, {a, b} is not {b, a})."""
    if isinstance(value, dict):
        return ['{', *[(key, _ordered(item)) for key, item in value.items()]]
    if isinstance(value, list):
        return ['[', *[_ordered(item) for item in value]]
    return (type(value).__name__, value)


def same_settings(target, first, second):
    """Whether two versions of a launcher file hold the same settings in the same order; only their layout (spacing,
    escapes, final line ending) may differ."""
    if first == second:
        return True
    try:
        if target['launcher'] == 'heroic':
            return _ordered(json.loads(first)) == _ordered(json.loads(second))
        if target['launcher'] == 'lutris':
            from vendor import yaml
            return _ordered(yaml.safe_load(first)) == _ordered(yaml.safe_load(second))
    except Exception:  # noqa: BLE001 - an unreadable copy means "not the same"
        return False
    return False


def patch(target, data, values):
    if target['launcher'] == 'steam':
        if target.get('format') == 'shortcuts':
            record = shortcut(data, target['id'])
            entry = record['value'].get('launchoptions')
            value = values['LaunchOptions']
            if value is not None and '\0' in value:
                raise ValueError('Shortcut value contains NUL')
            replacement = b'' if value is None else b'\x01LaunchOptions\0'+value.encode('utf-8', errors='surrogateescape')+b'\0'
            start = entry['start'] if entry else record['close']
            end = entry['end'] if entry else start
            return data[:start]+replacement+data[end:]
        return Document(data).set(APP+[target['id'], 'LaunchOptions'], values['LaunchOptions'])
    if target['launcher'] == 'heroic':
        doc = json.loads(data)
        settings = doc[target['id']]
    else:
        from vendor import yaml
        doc = yaml.safe_load(data)
        settings = doc.setdefault('system', {})
    for key, value in values.items():
        if value is None:
            settings.pop(key, None)
        else:
            settings[key] = value
    if target['launcher'] == 'heroic':
        return _dump_json(doc, _json_layout(data))
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True).encode()


# GE-Proton variables that make Proton copy its own OptiScaler or upscaler DLLs into the game (GE-Proton11-7: USE_OPTISCALER,
# DLSS/FSR3/FSR4/FSR4_RDNA3/MLFG/XESS_UPGRADE); they would collide with this installation's files.
GE_UPSCALER = re.compile(r'PROTON_(USE_OPTISCALER|[A-Z0-9_]+_UPGRADE)')
# The layer folder an installation names in VK_LAYER_PATH (environment() above), relative to its game folder.
LAYER_TAIL = ('BC250-XeFG', 'layer')


def entry_environment(target, data):
    """The environment variables a launcher entry sets for the game (Steam: the assignments before %command%)."""
    values = fields({k: v for k, v in target.items() if k not in ('before', 'args')}, data)
    if target['launcher'] == 'steam':
        return split_steam(values['LaunchOptions'] or '')[0]
    if target['launcher'] == 'heroic':
        return {e.get('key'): e.get('value') for e in values.get('enviromentOptions') or [] if isinstance(e, dict)}
    env = values.get('env') or {}
    return {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}


def planned_environment(row):
    """The environment variables a planned or recorded launcher operation sets (its 'after' fields)."""
    after = row['after']
    if row['launcher'] == 'steam':
        return split_steam(after['LaunchOptions'] or '')[0]
    if row['launcher'] == 'heroic':
        return {e['key']: e['value'] for e in after['enviromentOptions']}
    return {str(k): str(v) for k, v in (after.get('env') or {}).items()}


def layer_roots(env):
    """Game folders whose installation this environment loads the layer from (VK_LAYER_PATH entries ending in the
    layer folder; the lib2x OptiScaler-route layout keeps it under OptiScaler/)."""
    roots = []
    for entry in filter(None, (env.get('VK_LAYER_PATH') or '').split(':')):
        path = Path(entry)
        if tuple(path.parts[-2:]) == LAYER_TAIL:
            root = path.parent.parent
            roots.append(root.parent if root.name == 'OptiScaler' else root)
    return roots


def _ge_variables(env):
    return sorted(str(k) for k, v in env.items() if GE_UPSCALER.fullmatch(str(k)) and str(v).strip() not in ('', '0'))


def conflicts(exe, targets, environ=None):
    """Refusals that the launcher entries of exe call for, found before anything is downloaded or written:
    [dict(code, kind, text, way)]. shared-entry: an entry already loads an installation from another folder (two
    installations on one entry cannot both be restored exactly). ge-optiscaler: GE-Proton is told to place its own
    OptiScaler or upscaler DLLs (in the entry, or in environ: the environment Setup runs in). An entry that cannot be
    read is left to plan(), which reports it."""
    root = Path(exe).parent.resolve()
    found = []
    for target in targets:
        try:
            env = entry_environment(target, Path(target['path']).read_bytes())
        except Exception:  # noqa: BLE001 - plan() reports an unreadable entry
            continue
        others = sorted({str(r) for r in layer_roots(env) if r.resolve() != root})
        if others:
            found.append(dict(code='shared-entry', kind='hard',
                              text=f'This {target["launcher"].capitalize()} entry already starts an installation in {others[0]}.',
                              way='Restore that installation first (install.py restore on its executable), then install here.'))
        ge = _ge_variables(env)
        if ge:
            found.append(dict(code='ge-optiscaler', kind='hard',
                              text='GE-Proton is set to place its own OptiScaler or upscaler DLLs in this game (' + ', '.join(ge) +
                                   '), which would collide with the installed files.',
                              way='Remove ' + ', '.join(ge) + ' from the game\'s launch options.'))
    ge = _ge_variables(environ or {})
    if ge and not any(c['code'] == 'ge-optiscaler' for c in found):
        found.append(dict(code='ge-optiscaler', kind='hard',
                          text='GE-Proton is set to place its own OptiScaler or upscaler DLLs (' + ', '.join(ge) +
                               ' in your environment), which would collide with the installed files.',
                          way='Unset ' + ', '.join(ge) + ' for this game.'))
    unique = {}
    for c in found:
        unique.setdefault((c['code'], c['text']), c)
    return list(unique.values())


def plan(exe, owner, home=None, runtime='xemfg', route='opti', args=(), extra_env=None, vkd3d_cache=None):
    targets = discover(exe, home)
    if not targets:
        raise ValueError('No launcher entry found for this executable. Add the game to Steam, Heroic or Lutris first.')
    require_stopped(t['launcher'] for t in targets)
    root = exe.parent.resolve()
    # The checks Install also runs before its downloads (compat.preflight); here they guard every other caller.
    for refusal in conflicts(exe, targets):
        raise ValueError(f'{refusal["text"]} {refusal["way"]} [{refusal["code"]}]')
    # Wrappers of earlier wrapper-based installs (either layout) give way to the launcher fields.
    wrappers = {str(root/'BC250-XeFG/run.sh'), str(root/'OptiScaler/BC250-XeFG/run.sh')}
    operations = []
    for target in targets:
        path = Path(target['path'])
        if path.is_symlink() or not path.is_file():
            raise ValueError('Expected a regular launcher configuration: '+str(path))
        if args and target['launcher'] == 'heroic':
            target = dict(target, args=list(args))
        data = path.read_bytes()
        before = fields(target, data)
        if target['launcher'] == 'steam' and target.get('format') != 'shortcuts':
            target = dict(target, created_app=not Document(data).has_object(APP+[target['id']]))
        if target['launcher'] == 'steam':
            after = {'LaunchOptions': steam_options(before['LaunchOptions'] or '', root, owner, runtime, route, args, extra_env,
                                                    vkd3d_cache)}
        elif target['launcher'] == 'heroic':
            entries = before['enviromentOptions'] or []
            current = {e['key']: e['value'] for e in entries}
            if len(current) != len(entries):
                raise ValueError('Duplicate Heroic environment variables')
            after = dict(enviromentOptions=[dict(key=k, value=v) for k, v in
                                            environment(root, owner, current, runtime, route, extra_env, vkd3d_cache).items()],
                         wrapperOptions=[r for r in (before['wrapperOptions'] or []) if r.get('exe') not in wrappers])
            if 'launcherArgs' in before:
                tokens = with_args(shlex.split(before['launcherArgs'] or ''), args)
                after['launcherArgs'] = shlex.join(tokens) if tokens else before['launcherArgs']
        else:
            prefix = before['prefix_command'] or ''
            # Remove only this installation's old wrapper, preserving other tools.
            tokens = shlex.split(prefix)
            after = dict(env=environment(root, owner, before['env'] or {}, runtime, route, extra_env, vkd3d_cache),
                         prefix_command=shlex.join(t for t in tokens if t not in wrappers))
        operations.append(dict({k: v for k, v in target.items() if k != 'args'}, before=before, after=after))
    return operations


def added_args(operations):
    """Game arguments the planned launcher fields add (Steam LaunchOptions after %command%, Heroic launcherArgs), in
    order and once each: with_args adds none where the user's options already choose a graphics API, and Lutris's
    arguments are not managed."""
    added = []
    for row in operations:
        if row['launcher'] == 'steam':
            before = shlex.split(split_steam(row['before'].get('LaunchOptions') or '')[1])
            after = shlex.split(split_steam(row['after'].get('LaunchOptions') or '')[1])
        elif row['launcher'] == 'heroic' and 'launcherArgs' in row['after']:
            before = shlex.split(row['before'].get('launcherArgs') or '')
            after = shlex.split(row['after'].get('launcherArgs') or '')
        else:
            continue
        added += [t for t in after if t not in before and t != '%command%' and t not in added]
    return added


def reverse(row, current):
    """Take out only what the installation put in, keeping the user's later changes to the same fields."""
    before, after = row['before'], row['after']
    if row['launcher'] == 'steam':
        if current['LaunchOptions'] is None:
            return current
        benv, brest, bwritten = split_steam(before['LaunchOptions'] or '')
        aenv, arest, _ = split_steam(after['LaunchOptions'])
        env, rest, written = split_steam(current['LaunchOptions'])
        env = _unset(env, aenv, benv)
        added = [t for t in shlex.split(arest) if t not in shlex.split(brest) and t != '%command%']
        rest = _drop_words(rest, added)
        value = _join_steam(env, rest, {**bwritten, **{k: v for k, v in written.items() if k not in aenv or env.get(k) != aenv[k]}})
        return {'LaunchOptions': before['LaunchOptions'] if value.strip() in ('', '%command%') and not before['LaunchOptions'] else value}
    if row['launcher'] == 'heroic':
        result = dict(current)
        entries = current.get('enviromentOptions') or []
        env = _unset({e['key']: e['value'] for e in entries},
                     {e['key']: e['value'] for e in after['enviromentOptions']},
                     {e['key']: e['value'] for e in (before['enviromentOptions'] or [])})
        result['enviromentOptions'] = [dict(key=k, value=v) for k, v in env.items()] or before['enviromentOptions']
        if current.get('wrapperOptions') == after.get('wrapperOptions'):
            result['wrapperOptions'] = before.get('wrapperOptions')
        if 'launcherArgs' in after:
            added = [t for t in shlex.split(after['launcherArgs'] or '') if t not in shlex.split(before.get('launcherArgs') or '')]
            left = _drop_words(current.get('launcherArgs') or '', added)
            result['launcherArgs'] = left if left or before.get('launcherArgs') is not None else None
        return result
    result = dict(current)
    result['env'] = _unset(dict(current.get('env') or {}), after['env'], before['env'] or {}) or before['env']
    if current.get('prefix_command') == after['prefix_command']:
        result['prefix_command'] = before['prefix_command']
    return result


def _unset(env, installed, original):
    """Each variable still holding the installed value goes back to its original (or away); others are the user's."""
    env = dict(env)
    for key, value in installed.items():
        if env.get(key) == value:
            if key in original:
                env[key] = original[key]
            else:
                env.pop(key)
    return env


def apply(operations, writer, restore=False, originals=None):
    """Change only owned fields; the caller journals operations before this call.

    Installing requires every entry to be as planned. Restoring never blocks the rest of a Restore: an entry that is
    gone is reported, one the user changed since installation loses only what the installation added, and the lines
    returned say what happened. originals ({index in operations: bytes, or (bytes, modification time in ns)}, Restore
    only) are the WHOLE_FILE launcher files as the installation found them: one is written back as it was (with its
    modification time) when the restored file holds the same settings."""
    require_stopped(row['launcher'] for row in operations)
    messages = []
    for row in operations:
        path = Path(row['path'])
        if path.is_symlink() or not path.is_file():
            if restore:
                continue
            raise ValueError('Launcher configuration was replaced: '+str(path))
        current = fields(row, path.read_bytes())
        if current != row['before'] and current != row['after'] and not restore:
            raise ValueError('Launcher settings changed; preserving '+row['path'])
    for index, row in enumerate(operations):
        path = Path(row['path'])
        if path.is_symlink() or not path.is_file():
            messages.append('Launcher entry no longer present, nothing to undo: '+row['path'])
            continue
        data = path.read_bytes()
        current = fields(row, data)
        if not restore:
            if current != row['before'] and current != row['after']:
                raise ValueError('Launcher settings changed during installation')
            writer(path, patch(row, data, row['after']), path.stat().st_mode & 0o777)
            continue
        original = (originals or {}).get(index)
        original, mtime = original if isinstance(original, tuple) else (original, None)

        def write_original():
            writer(path, original, path.stat().st_mode & 0o777)
            if mtime is not None:
                os.utime(path, ns=(path.stat().st_atime_ns, mtime))
        if current == row['before']:
            # Already the original values (an interrupted installation or Restore): only its layout may be ours.
            if original is not None and data != original and same_settings(row, data, original):
                write_original()
            continue
        values = row['before'] if current == row['after'] else reverse(row, current)
        if current != row['after']:
            messages.append('Launcher settings changed since installation: removed only what the installation added, '
                            'kept the rest ('+row['path']+')')
        data = patch(row, data, values)
        if row.get('created_app') and values.get('LaunchOptions') is None:
            data = Document(data).remove_empty(APP+[row['id']])
        if original is not None and same_settings(row, data, original):
            write_original()  # the same settings as found: the launcher's own bytes, not a rewrite
            continue
        writer(path, data, path.stat().st_mode & 0o777)
    return messages
