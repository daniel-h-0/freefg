# SPDX-License-Identifier: MIT
"""Pure launcher migration plans and locks shared by all game transactions.

The install record retains its original fields. Generations additionally save the fields immediately before an
update, so undo never replaces an entire shared launcher file over another game's settings.
"""
import contextlib
import copy
import fcntl
import hashlib
import os
import shlex
import threading
from pathlib import Path

import freefg_library
import launcher_config as lc

POLICY_KEYS = frozenset(('WINEDLLOVERRIDES', 'VK_LAYER_PATH', 'VK_INSTANCE_LAYERS', 'XEFG_WAVE_CONFIG',
                         'VKD3D_CONFIG', 'VKD3D_DISABLE_EXTENSIONS', 'VKD3D_SHADER_CACHE_PATH',
                         'XEFG_GAME_PROFILE', 'BC250_XEFG_OWNER_MODULE', 'XEFG_FLOW_CAP'))
SEPARATORS = {'VK_LAYER_PATH': ':', 'VK_INSTANCE_LAYERS': ':', 'VKD3D_CONFIG': ',', 'VKD3D_DISABLE_EXTENSIONS': ','}
_mutex = threading.RLock()
_held = set()


@contextlib.contextmanager
def locked(rows):
    """Coordinate installers that edit different entries of the same launcher file; reentrant in one process."""
    paths = sorted({str(Path(row['path']).absolute()) for row in rows})
    opened = []
    with _mutex:
        try:
            for path in paths:
                if path in _held:
                    continue
                folder = freefg_library.location().parent / 'locks'
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                name = folder / (hashlib.sha256(path.encode()).hexdigest() + '.lock')
                fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    os.close(fd)
                    raise ValueError('Another installer is editing this launcher; retry: ' + path) from error
                opened.append((path, fd));_held.add(path)
            yield
        finally:
            for path, fd in reversed(opened):
                _held.remove(path);os.close(fd)


def environment(fields, launcher):
    if launcher == 'steam':
        return lc.split_steam(fields.get('LaunchOptions') or '')[0]
    if launcher == 'heroic':
        rows = fields.get('enviromentOptions') or []
        result = {row['key']: row['value'] for row in rows}
        if len(result) != len(rows):
            raise ValueError('Duplicate Heroic environment variables')
        return result
    return dict(fields.get('env') or {})


def _overrides(value):
    result = {}
    for part in filter(None, (value or '').split(';')):
        names, equal, setting = part.partition('=')
        if not equal:
            raise ValueError('Unrecognized Wine override: ' + part)
        for name in names.split(','):
            result[name.lower().removesuffix('.dll')] = setting
    return result


def merge_environment(current, old, new, keys=None, strict=True):
    """Apply only the old→new delta, preserving user additions to list variables and Wine DLL overrides."""
    result = dict(current)
    for key in sorted(set(old) | set(new)):
        if keys is not None and key not in keys:
            continue
        a, b, now = old.get(key), new.get(key), current.get(key)
        if a == b:
            continue
        if now == a:
            if b is None:result.pop(key, None)
            else:result[key] = b
            continue
        if now == b:continue
        if key == 'WINEDLLOVERRIDES':
            before, after, values = _overrides(a), _overrides(b), _overrides(now)
            for dll in sorted(set(before) | set(after)):
                if before.get(dll) == after.get(dll):
                    continue
                if values.get(dll) not in (before.get(dll), after.get(dll)):
                    if strict:
                        raise ValueError('Wine override changed since installation: ' + dll + '; keep it or reconcile before updating')
                    continue
                if dll in after:values[dll] = after[dll]
                else:values.pop(dll, None)
            value = ';'.join(name + '=' + setting for name, setting in values.items())
        elif key in SEPARATORS:
            sep = SEPARATORS[key]
            before, after = list(filter(None, (a or '').split(sep))), list(filter(None, (b or '').split(sep)))
            values = [v for v in (now or '').split(sep) if v and (v not in before or v in after)]
            additions = [v for v in after if v not in before and v not in values]
            value = sep.join([*additions, *values])
        elif now in (a, b):
            value = b
        else:
            if strict:
                raise ValueError('Launcher variable changed since installation: ' + key + '; reconcile it before updating')
            continue
        if value is None or (not value and b is None):result.pop(key, None)
        else:result[key] = value
    return result


def _arguments(current, old, new):
    if old == new:return current
    before, after, values = shlex.split(old or ''), shlex.split(new or ''), shlex.split(current or '')
    if before == after:return current
    removed = set(before) - set(after)
    values = [v for v in values if v not in removed]
    added = [v for v in after if v not in before and v not in values]
    return shlex.join(lc.with_args(values, added))


def merge_fields(row, current, old, new, keys=None, strict=True):
    result = copy.deepcopy(current)
    launcher = row['launcher']
    env = merge_environment(environment(current, launcher), environment(old, launcher), environment(new, launcher), keys, strict)
    if launcher == 'steam':
        _env, rest, written = lc.split_steam(current.get('LaunchOptions') or '')
        old_rest = lc.split_steam(old.get('LaunchOptions') or '')[1]
        new_rest = lc.split_steam(new.get('LaunchOptions') or '')[1]
        if env == _env and shlex.split(old_rest) == shlex.split(new_rest):return current
        rest = _arguments(rest, old_rest, new_rest)
        value = lc._join_steam(env, rest, {k: v for k, v in written.items() if env.get(k) == _env.get(k)})
        result['LaunchOptions'] = value if value.strip() not in ('', '%command%') or new.get('LaunchOptions') else new.get('LaunchOptions')
    elif launcher == 'heroic':
        result['enviromentOptions'] = [dict(key=k, value=v) for k, v in env.items()] or new.get('enviromentOptions')
        if 'launcherArgs' in new or 'launcherArgs' in old:
            result['launcherArgs'] = _arguments(current.get('launcherArgs'), old.get('launcherArgs'), new.get('launcherArgs'))
            if not result['launcherArgs'] and not new.get('launcherArgs'):result['launcherArgs']=new.get('launcherArgs')
        # Wrapper commands are not regenerated by an ordinary update.
    else:
        result['env'] = env or new.get('env')
    return current if result == current else result


def desired_fields(row, root, owner, runtime, route, args, extra, cache, previous_owner=None):
    before = copy.deepcopy(row['before'])
    if previous_owner and previous_owner != owner:
        env = environment(before,row['launcher'])
        overrides = _overrides(env.get('WINEDLLOVERRIDES'))
        overrides.pop(previous_owner.lower().removesuffix('.dll'),None)
        if overrides:env['WINEDLLOVERRIDES']=';'.join(k+'='+v for k,v in overrides.items())
        else:env.pop('WINEDLLOVERRIDES',None)
        if row['launcher']=='steam':
            _,rest,_=lc.split_steam(before.get('LaunchOptions') or '')
            before['LaunchOptions']=lc._join_steam(env,rest,{})
        elif row['launcher']=='heroic':before['enviromentOptions']=[dict(key=k,value=v) for k,v in env.items()]
        else:before['env']=env
    if row['launcher'] == 'steam':
        return {'LaunchOptions': lc.steam_options(before.get('LaunchOptions') or '', root, owner, runtime, route, args, extra, cache)}
    result = copy.deepcopy(row['after'])
    env = lc.environment(root, owner, environment(before, row['launcher']), runtime, route, extra, cache)
    if row['launcher'] == 'heroic':
        result['enviromentOptions'] = [dict(key=k, value=v) for k, v in env.items()]
        if 'launcherArgs' in before or args:
            values = lc.with_args(shlex.split(before.get('launcherArgs') or ''), args)
            result['launcherArgs'] = shlex.join(values) if values else before.get('launcherArgs')
    else:result['env'] = env
    return result


def plan(record, root, owner, *, runtime='xemfg-proxy', route=None, args=None, extra=None, cache=None, previous_owner=None):
    """Return per-entry migrations and the new ownership rows; no launcher or index is written."""
    operations, records = [], []
    keys = POLICY_KEYS | set((record.get('compat') or {}).get('extra_env') or {}) | set(extra or {})
    keys |= set(record.get('launcher_policy_keys') or [])
    keys |= set(lc.environment(root,owner,{},runtime,route or record.get('route','native'),extra,cache))
    for row in record.get('launchers') or []:
        target = dict(row)
        wanted = desired_fields(target, root, owner, runtime, route or record.get('route', 'native'),
                                record.get('launch_args', []) if args is None else args, extra, cache, previous_owner)
        unchanged = merge_fields(target, target['after'], target['after'], wanted, keys) == target['after']
        if unchanged and not (row['launcher'] == 'heroic' and args and 'launcherArgs' not in row['before']):
            records.append(copy.deepcopy(row));continue
        if row['launcher'] == 'heroic' and args and 'launcherArgs' not in row['before']:
            target['before'] = dict(row['before'], launcherArgs=None)
            target['after'] = dict(row['after'], launcherArgs=None)
        path = Path(target['path'])
        if path.is_symlink() or not path.is_file():
            raise ValueError('Launcher configuration is unavailable; reconnect or register its new location: ' + str(path))
        data = path.read_bytes();current = lc.fields(target, data)
        if target['launcher'] == 'heroic' and 'launcherArgs' not in row['before'] and 'launcherArgs' in target['before']:
            target['before']['launcherArgs'] = current['launcherArgs']
            target['after']['launcherArgs'] = current['launcherArgs']
        wanted = desired_fields(target, root, owner, runtime, route or record.get('route', 'native'),
                                record.get('launch_args', []) if args is None else args, extra, cache, previous_owner)
        updated = merge_fields(target, current, target['after'], wanted, keys)
        ownership = copy.deepcopy(target)
        ownership['after'] = merge_fields(target, target['after'], target['after'], wanted, keys)
        records.append(ownership)
        if updated != current:
            operations.append(dict(target={k:v for k,v in target.items() if k not in ('before','after')},
                                   before=current, after=updated, observed=hashlib.sha256(data).hexdigest()))
    return dict(operations=operations, records=records, policy_keys=sorted(keys))


def grouped(operations):
    result = {}
    for operation in operations:result.setdefault(operation['target']['path'], []).append(operation)
    return result


def check(operations):
    """All launcher preconditions before the game transaction's first write."""
    if operations:lc.require_stopped(op['target']['launcher'] for op in operations)
    for path, rows in grouped(operations).items():
        p = Path(path)
        if p.is_symlink() or not p.is_file():raise ValueError('Launcher configuration was replaced: ' + path)
        data = p.read_bytes()
        if any(hashlib.sha256(data).hexdigest() != row['observed'] for row in rows):
            raise ValueError('Launcher configuration changed since planning; retry: ' + path)


def prepare_apply(operations, reverse=False, strict=True):
    """Validate and prepare the entry patches without writing; rollback preflights every resource this way."""
    if operations:lc.require_stopped(op['target']['launcher'] for op in operations)
    prepared = []
    for path, rows in grouped(operations).items():
        p = Path(path)
        if p.is_symlink() or not p.is_file():raise ValueError('Launcher configuration was replaced: ' + path)
        data = p.read_bytes();start = data
        for row in rows:
            current = lc.fields(dict(row['target'], before=row['before']), data)
            old, new = (row['after'], row['before']) if reverse else (row['before'], row['after'])
            target = merge_fields(row['target'], current, old, new, strict=strict)
            data = lc.patch(row['target'], data, target)
        prepared.append((p, start, data))
    return prepared


def apply(operations, writer, reverse=False, strict=True):
    """Patch only selected entries. The caller holds locks and journals before invoking this function."""
    prepared = prepare_apply(operations, reverse, strict)
    for path, before, data in prepared:
        if path.read_bytes() != before:raise ValueError('Launcher configuration changed while applying: ' + str(path))
        if data != before:writer(path, data, path.stat().st_mode & 0o777)

