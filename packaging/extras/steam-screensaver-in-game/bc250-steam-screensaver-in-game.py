#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Keeps Steam's idle screensaver off while a game runs and puts the user's timeouts back afterwards.

Why: in Game Mode, Steam starts its screensaver after the idle time set under Settings (5 minutes on AC by default)
also while a game is running. Behind the game it is invisible, but its slideshow cross-fades for 2 s every 20 s and
takes GPU time from the game; with frame generation, VRR refresh intervals then alternate 8/21 ms, which shows as
flicker. Controller input in the game resets Steam's idle timer, so it hits long cutscenes, standing still to watch,
or leaving the game running. Measured on a BC-250 with CONTROL Resonant: 5-7% of the GPU during each fade.

How: through Steam's local CEF DevTools endpoint (127.0.0.1:8080, which Decky Loader enables, or the empty file
~/.steam/steam/.cef-enable-remote-debugging plus a Steam restart). Every few seconds it asks Steam whether a game runs
(SteamUIStore.RunningApps) and, while one does, sets system_idle_screensaver_ac_sec and _battery_sec to 0 with
SteamClient.Settings.SetSetting, as Steam's own settings page writes them. The values it replaced are kept in
$XDG_STATE_HOME/bc250-steam-screensaver-in-game.json and written back when no game runs (unless the user changed the
setting meanwhile). Nothing else in Steam is touched; with Steam not running, or without the endpoint, it just waits.

Commands: run (default; the loop), status, restore (write the saved timeouts back now and forget them)."""
import argparse, base64, json, os, socket, struct, sys, time, urllib.request
from pathlib import Path

DEVTOOLS = 'http://127.0.0.1:8080'
FIELDS = {'system_idle_screensaver_ac_sec': 24009, 'system_idle_screensaver_battery_sec': 24008}  # CMsgClientSettings int32
STATE = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'bc250-steam-screensaver-in-game.json'


class Unavailable(RuntimeError):
    pass


class DevTools:
    """Minimal CEF DevTools websocket client (Runtime.evaluate only)."""

    def __init__(self, url):
        hostport, path = url.removeprefix('ws://').split('/', 1)
        host, port = hostport.split(':', 1)
        try:
            self.sock = socket.create_connection((host, int(port)), timeout=5)
            key = base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall(f'GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                              f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n'.encode())
            reply = b''
            while b'\r\n\r\n' not in reply:
                chunk = self.sock.recv(4096)
                if not chunk:
                    raise Unavailable('DevTools closed the connection')
                reply += chunk
        except OSError as exc:
            raise Unavailable(f'DevTools connection failed: {exc}') from exc
        if b' 101 ' not in reply.split(b'\r\n', 1)[0]:
            raise Unavailable('DevTools refused the websocket')
        self.id = 0

    def close(self):
        self.sock.close()

    def _read(self, n):
        data = b''
        while len(data) < n:
            chunk = self.sock.recv(n - len(data))
            if not chunk:
                raise Unavailable('DevTools websocket closed')
            data += chunk
        return data

    def evaluate(self, expression):
        self.id += 1
        body = json.dumps({'id': self.id, 'method': 'Runtime.evaluate',
                           'params': {'expression': expression, 'returnByValue': True, 'awaitPromise': True}}).encode()
        mask = os.urandom(4)
        n = len(body)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else bytes([0x80 | 126]) + struct.pack('!H', n) if n < 65536
                                else bytes([0x80 | 127]) + struct.pack('!Q', n))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(body)))
        while True:
            first, second = self._read(2)
            n = second & 0x7F
            if n == 126:
                n = struct.unpack('!H', self._read(2))[0]
            elif n == 127:
                n = struct.unpack('!Q', self._read(8))[0]
            payload = self._read(n)
            if first & 0x0F == 8:
                raise Unavailable('DevTools websocket closed')
            if first & 0x0F != 1:
                continue
            message = json.loads(payload)
            if message.get('id') == self.id:
                result = message.get('result', {})
                if 'exceptionDetails' in result:
                    raise Unavailable('Steam UI script error: ' + json.dumps(result['exceptionDetails'])[:300])
                return result.get('result', {}).get('value')


def connect():
    try:
        with urllib.request.urlopen(DEVTOOLS + '/json/list', timeout=5) as response:
            targets = json.load(response)
    except (OSError, ValueError) as exc:
        raise Unavailable(f'Steam DevTools not reachable at {DEVTOOLS} (Steam not running, or remote debugging off)') from exc
    for target in targets:
        if target.get('title') == 'SharedJSContext' and target.get('webSocketDebuggerUrl'):
            return DevTools(target['webSocketDebuggerUrl'])
    raise Unavailable('Steam SharedJSContext not found (is Steam in Game Mode / Big Picture?)')


def read_state(client):
    names = json.dumps(list(FIELDS))
    value = client.evaluate(f"""JSON.stringify((() => {{
      const running = (window.SteamUIStore?.RunningApps ?? []).length > 0 ||
        !['', '0', '769', 'undefined', 'null'].includes(String(window.SystemPerfStore?.nCurrentGameID));
      const settings = window.settingsStore?.clientSettings ?? {{}};
      return {{running, settings: Object.fromEntries({names}.map(n => [n, settings[n] ?? null]))}};
    }})())""")
    if not isinstance(value, str):  # an error reply or a reloading UI
        raise Unavailable('Steam UI returned no state')
    return json.loads(value)


def write_setting(client, name, seconds):
    varint = lambda n: bytes(((n >> s) & 0x7F) | (0x80 if n >> (s + 7) else 0) for s in range(0, max(n.bit_length(), 1), 7))
    message = base64.b64encode(varint(FIELDS[name] << 3) + varint(int(seconds))).decode()
    if client.evaluate(f'(async () => {{ await SteamClient.Settings.SetSetting("{message}"); return "ok"; }})()') != 'ok':
        raise Unavailable(f'Steam did not accept {name}')


def saved():
    try:
        data = json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if k in FIELDS and isinstance(v, int)} if isinstance(data, dict) else {}


def save(values):
    """The user's values, written whole (temporary file, fsync, rename) before anything is changed in Steam."""
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix('.tmp')
    with open(temporary, 'w') as stream:
        stream.write(json.dumps(values) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, STATE)


def put_back(client, state, keep):
    """Writes the saved values back where the setting is still ours (0), then forgets them, only after every write
    succeeded. Nothing happens while Steam's settings cannot be read yet (a starting or reloading UI)."""
    if any(not isinstance(state['settings'].get(name), int) for name in keep):
        return []
    done = []
    for name, value in keep.items():
        if state['settings'].get(name) == 0:  # still ours; a value the user chose meanwhile stays
            write_setting(client, name, value)
            done.append((name, value))
    STATE.unlink(missing_ok=True)
    return done


def step(client):
    state = read_state(client)
    keep = saved()
    changes = []
    if state['running']:
        for name, value in state['settings'].items():
            if isinstance(value, int) and value != 0:
                keep[name] = value
                changes.append((name, 0))
        if changes:
            save(keep)
        for name, value in changes:
            write_setting(client, name, value)
    elif keep:
        changes = put_back(client, state, keep)
    for name, value in changes:
        print(f'{"game running" if state["running"] else "no game"}: {name} = {value}', flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('command', nargs='?', default='run', choices=['run', 'status', 'restore'])
    ap.add_argument('--interval', type=float, default=5.0)
    args = ap.parse_args()
    if args.command in ('status', 'restore'):
        client = connect()
        state = read_state(client)
        if args.command == 'restore':
            keep = saved()
            if keep and any(not isinstance(state['settings'].get(name), int) for name in keep):
                raise Unavailable("Steam's settings are not readable yet; nothing restored")
            for name, value in put_back(client, state, keep):
                print(f'restored {name} = {value}')
        else:
            print(json.dumps(dict(state, saved=saved(), state_file=str(STATE)), indent=1))
        client.close()
        return 0
    last = ''
    while True:
        try:
            client = connect()
            try:
                step(client)
            finally:
                client.close()
            last = ''
        except (Unavailable, OSError, ValueError, TypeError, KeyError) as exc:
            if str(exc) != last:
                print(f'waiting: {exc}', file=sys.stderr, flush=True)
                last = str(exc)
        time.sleep(args.interval)


if __name__ == '__main__':
    sys.exit(main())
