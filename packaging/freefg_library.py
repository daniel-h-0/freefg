#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Optional, rebuildable installation index. Game files and recovery never depend on this cache."""
import contextlib
import fcntl
import json
import os
import tempfile
from pathlib import Path

FORMAT = 1


class Busy(ValueError):
    """Another process holds the index lock: nothing was changed; retry later."""


def location(home=None):
    if home is not None:
        return Path(home) / '.local/share/freefg/library.json'
    override = os.environ.get('FREEFG_LIBRARY')
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError('FREEFG_LIBRARY must name an absolute index file')
        return path
    root = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    if not root.is_absolute():
        raise ValueError('XDG_DATA_HOME must be absolute')
    return root / 'freefg/library.json'


def load(home=None):
    path = location(home)
    if path.is_symlink():
        raise ValueError('The FreeFG library index is a symlink')
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        return {'format': FORMAT, 'games': {}}
    if not isinstance(value, dict) or value.get('format') != FORMAT or not isinstance(value.get('games'), dict):
        raise ValueError('Unsupported FreeFG library index; the file was left unchanged')
    for key, row in value['games'].items():
        if not isinstance(row, dict) or not isinstance(row.get('exe'), str) or key != row['exe'] or not Path(key).is_absolute():
            raise ValueError('Invalid FreeFG library entry; the index was left unchanged')
    return value


def _write(path, value):
    fd, name = tempfile.mkstemp(prefix='.freefg-library-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            json.dump(value, out, indent=2)
            out.write('\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(name)


def _change(callback, home=None):
    path = location(home)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = path.with_suffix('.lock')
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Busy('Another process is updating the FreeFG library index; retry registration later') from error
        value = load(home)
        if callback(value['games']):
            _write(path, value)
    finally:
        os.close(descriptor)


def register(exe, record, home=None):
    exe = Path(exe).resolve()
    if record.get('status') != 'installed' or Path(record.get('game') or '').resolve() != exe:
        raise ValueError('Registration needs the installed executable at its recorded location')
    entry = {'exe': str(exe), 'installation_id': record.get('installation_id'), 'package': record.get('package')}

    def apply(games):
        if games.get(str(exe)) == entry:
            return False
        games[str(exe)] = entry
        return True

    _change(apply, home)


def unregister(exe, home=None):
    key = str(Path(exe).resolve())

    def apply(games):
        return games.pop(key, None) is not None

    # Removing an installation must not create an index that did not exist.
    if location(home).exists():
        _change(apply, home)


def entries(home=None):
    games = load(home)['games']
    return [games[key] for key in sorted(games)]
