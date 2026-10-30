#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Setup's model: the games the desktop app lists, the state each one is in, and the install.py command behind every
choice (setup_app.py draws it; setup.py starts it).

It reads, in this process and without changing anything, what the installer records in each game folder (state.json in
the installation's state folder), the library index and launcher discovery (install.library_inventory), the last
session's logs (compat.last_run), update plans (install.update_plan), compatibility verdicts (install.compat_verdict)
and HLX preparation (hlx.find). Every change is an install.py command in its own process, exactly as on the command
line: the transactions, locks, refusals and messages stay the installer's. Nothing here needs GTK, so its tests run
anywhere.
"""
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

# Frame-generation inputs Install offers: id, label, what it is for. install.py's --route/--fg-input: input_args.
INPUTS = [
    ('auto', 'Automatic', 'Recommended. A verified recipe’s input, else the game’s own XeSS FG, else OptiFG. '
                          'Refuses games that cannot work.'),
    ('upscaler', 'OptiFG', 'For games without frame generation of their own: generated from the upscaler input. '
                           'HUD elements can be interpolated.'),
    ('dlssg', 'DLSS FG', 'For games with DLSS frame generation (Streamline 2 or newer).'),
    ('fsrfg', 'FSR 3.1 FG', 'For games with FSR 3.1 frame generation.'),
    ('fsrfg30', 'FSR 3.0 FG', 'For games with FSR 3.0 frame generation.'),
    ('native', 'Native XeSS FG', 'For games that ship XeSS frame generation beside their executable.'),
]
INPUT_NAMES = {key: label for key, label, _ in INPUTS}

# Generated-frame size: Match output, a percentage of it (Scale), or a height limit (install.py configure).
SIZES = [('output', 'Match output'), ('scale', 'Scale'), ('720', '720p limit'), ('1080', '1080p limit'),
         ('1440', '1440p limit'), ('2160', '2160p limit')]
DOWNSCALE = [('bilinear', 'Bilinear'), ('area', 'Area')]
UPSCALE = [('bilinear', 'Bilinear'), ('bicubic', 'Bicubic'), ('lanczos2', 'Lanczos2'), ('fsr1', 'FSR1 (EASU)')]
# BC250-XeFG/settings.ini's values for them (install.configure writes the same numbers).
INI_MODES = {'0': 'output', '1': 'scale', '2': 'limit'}
INI_DOWNSCALE = {'0': 'bilinear', '1': 'area'}
INI_UPSCALE = {'0': 'bilinear', '2': 'bicubic', '3': 'lanczos2', '4': 'fsr1'}
SETTINGS_INI = 'BC250-XeFG/settings.ini'

# A game's state, the most pressing first: the order of the sections and of the games in them.
STATES = ['recovery', 'attention', 'unavailable', 'update', 'outdated', 'newer', 'pinned', 'installed', 'available']
SECTIONS = [('attention', 'Needs attention', ('recovery', 'attention', 'unavailable')),
            ('installed', 'Installed', ('update', 'outdated', 'newer', 'pinned', 'installed')),
            ('available', 'Not installed', ('available',))]
# The last session's acceleration (compat.last_run): label and level.
ACCELERATION = {'full': ('Accelerated', 'success'), 'partial': ('Partly accelerated', 'warning'),
                'idle': ('No frame-generation context', 'warning'), 'not-running': ('Not accelerated', 'warning')}
# Update review groups: outcome statuses of install.update_plan (and Setup's own: running, unavailable, failed).
UPDATE_GROUPS = [('update', 'Will be updated', ('update',)),
                 ('running', 'Close these games to update them', ('running',)),
                 ('attention', 'Need attention', ('blocked', 'interrupted', 'deferred', 'unavailable', 'failed')),
                 ('pinned', 'Pinned', ('pinned',)),
                 ('current', 'Up to date', ('current',))]
# A probe that runs doctor.checks in a process of its own: it loads the Vulkan driver through ctypes, which must never
# take Setup's window down with it.
DOCTOR = ('import json,sys\nsys.path.insert(0,sys.argv[1])\nimport doctor\n'
          'print(json.dumps([list(row) for row in doctor.checks(package=sys.argv[1])]))')


class Context:
    """The package Setup runs from and its installer. root: the package folder (install.py beside setup.py); name: the
    product name; manifest: its manifest.json; installer: the install.py module, or None when it does not load
    (load_error says why); factors: the frame-generation factors the package offers ('2×', ...); scaling: whether it
    has generated-frame scaling; helix_about: the HelixSR credit Setup shows wherever HLX is chosen; blockers: Setup's
    running-game and launcher check (setup.blockers); home: the user's home for launcher lookups (tests)."""

    def __init__(self, root, name, manifest, installer=None, load_error=None, factors=('2×',), scaling=False,
                 helix_about='', blockers=None, home=None):
        self.root = Path(root)
        self.name = name
        self.manifest = manifest or {}
        self.installer = installer
        self.load_error = load_error
        self.factors = list(factors)
        self.scaling = scaling
        self.helix_about = helix_about
        self.blockers = blockers
        self.home = home

    @property
    def release(self):
        return self.manifest.get('name')

    @property
    def version(self):
        return version(self.release)

    def command(self, args):
        """The process that runs install.py with args (unbuffered, so its lines arrive as it prints them)."""
        return [sys.executable, '-u', str(self.root / 'install.py'), *map(str, args)]


def version(name):
    """'1.1.6' for a release named like 'freefg-1.1.6'; any other release name as it is."""
    if not name:
        return 'unknown release'
    found = re.fullmatch(r'[a-z][a-z0-9-]*?-(\d+(?:\.\d+)+)', str(name))
    return found[1] if found else str(name)


def release_number(name):
    found = re.fullmatch(r'[a-z][a-z0-9-]*?-(\d+(?:\.\d+)+)', str(name or ''))
    return tuple(int(part) for part in found[1].split('.')) if found else None


@dataclass
class Settings:
    """A game's frame-generation settings. size: 'output', 'scale' or a height limit ('720', '1080', '1440', '2160')."""
    size: str = 'output'
    percent: int = 75
    downscale: str = 'bilinear'
    upscale: str = 'bilinear'
    factor: int = 2


@dataclass
class Game:
    """One game Setup lists. record: its installation record (None: never installed here); reason: why it is
    unavailable or its record cannot be read; present: its executable is there; tracked: Update all finds it (the
    library index or a launcher entry); added: chosen in this session with Add Game; run: the last session's logs of an
    installed game; settings: its frame-generation settings; verdict: the compatibility verdict Install starts from, once
    checked (checked: the check ran; a None verdict then means it could not)."""
    exe: Path
    title: str = ''
    record: dict = None
    reason: str = None
    present: bool = True
    tracked: bool = False
    added: bool = False
    run: dict = None
    settings: Settings = None
    verdict: dict = None
    checked: bool = False
    integrity: dict = None

    @property
    def key(self):
        return str(self.exe)

    @property
    def folder(self):
        return self.exe.parent

    @property
    def installed(self):
        return (self.record or {}).get('status') == 'installed'


# ----------------------------------------------------------------------------------------------- reading the library
def read_record(installer, exe):
    """The installation record of the game at exe, None when there is none."""
    root = Path(exe).parent.resolve()
    try:
        record = json.loads(installer.safe(root, installer.STATE + '/state.json').read_text())
        if not isinstance(record, dict):
            raise ValueError('Installation record must be an object')
        for key in ('upscaler', 'recipe', 'pending_update', 'compat', 'components', 'update_pin'):
            if record.get(key) is not None and not isinstance(record[key], dict):
                raise ValueError('Invalid installation record field: ' + key)
        for key in ('files', 'launchers', 'ini_changes', 'generations'):
            if record.get(key) is not None and (not isinstance(record[key], list) or
                                               any(not isinstance(row, dict) for row in record[key])):
                raise ValueError('Invalid installation record field: ' + key)
        return record
    except FileNotFoundError:
        return None


def launcher_titles(home=None):
    """{game folder: title} of the installed Steam and Heroic games (gamescan.installed_games); {} when unreadable."""
    try:
        import gamescan
        games = gamescan.installed_games(home)
    except Exception:  # noqa: BLE001 - titles are a convenience; the executable's name stands in
        return {}
    out = {}
    for game in games:
        if game.get('path') and game.get('name'):
            try:
                out[Path(game['path']).resolve()] = str(game['name'])
            except OSError:
                continue
    return out


def title_for(exe, record=None, titles=None):
    """The launcher's title of the game whose folder holds exe, else its recipe's title, else the executable's name."""
    exe = Path(exe)
    if titles:
        try:
            folder = exe.parent.resolve()
        except OSError:
            folder = exe.parent
        for candidate in (folder, *folder.parents):
            if candidate in titles:
                return titles[candidate]
    recipe = ((record or {}).get('recipe') or {}).get('title')
    return str(recipe or exe.stem)


def read_settings(installer, exe):
    """The frame-generation settings in the game folder's BC250-XeFG/settings.ini, None when it has none."""
    root = Path(exe).parent.resolve()
    try:
        values = installer.read_ini(installer.safe(root, SETTINGS_INI).read_bytes())
    except (OSError, ValueError, UnicodeDecodeError):
        return None

    def value(key, default):
        return str(values.get(('bc250', key), default)).strip()
    settings = Settings()
    mode = INI_MODES.get(value('resolutionmode', '0'), 'output')
    try:
        settings.percent = min(100, max(50, int(value('resolutionpercent', '75'))))
    except ValueError:
        pass
    limit = value('resolutionlimit', '1080')
    settings.size = (limit if limit in ('720', '1080', '1440', '2160') else '1080') if mode == 'limit' else mode
    settings.downscale = INI_DOWNSCALE.get(value('downscalefilter', '0'), 'bilinear')
    settings.upscale = INI_UPSCALE.get(value('upscalefilter', '0'), 'bilinear')
    return settings


def read_factor(installer, exe, record):
    """The frame-generation factor an OptiScaler installation is set to (OptiScaler.ini [XeFG] InterpolationCount + 1)."""
    if (record or {}).get('route') != 'opti':
        return 2
    root = Path(exe).parent.resolve()
    try:
        values = installer.read_ini(installer.safe(root, 'OptiScaler.ini').read_bytes())
        return min(4, max(2, int(values.get(('xefg', 'interpolationcount'), '1')) + 1))
    except (OSError, ValueError, UnicodeDecodeError):
        return 2


def load_game(ctx, exe, titles=None, tracked=False, added=False, inventory=None):
    """One game as Setup shows it, read from its folder (record, settings, last session)."""
    installer = ctx.installer
    exe = Path(exe)
    game = Game(exe=exe, tracked=tracked, added=added)
    inventory = inventory or {}
    try:
        game.present = exe.is_file()
    except OSError:
        game.present = False
    try:
        game.record = read_record(installer, exe)
    except (OSError, ValueError) as error:
        game.reason = str(error)
    if not game.present:
        game.reason = 'The game’s executable is not there. Is its drive connected, or did the game move?'
    elif inventory.get('status') == 'unavailable' and inventory.get('reason'):
        game.reason = str(inventory['reason'])
    game.title = title_for(exe, game.record, titles)
    if game.installed and game.present:
        game.settings = read_settings(installer, exe)
        if game.settings:
            game.settings.factor = read_factor(installer, exe, game.record)
        try:
            import compat
            game.run = compat.last_run(exe.parent.resolve(), game.record.get('route'), **installer.run_scope(game.record))
        except Exception:  # noqa: BLE001 - the logs are evidence, not a requirement
            game.run = None
    return game


def load_library(ctx, added=(), titles=None):
    """Every game Setup lists: the installations the library index and launcher entries know (install.library_inventory),
    then the games added in this session. Returns (games, notes): notes about the library index."""
    installer = ctx.installer
    notes = []
    try:
        installer.freefg_library.entries(ctx.home)
    except (OSError, ValueError) as error:
        notes.append('The library index needs attention: ' + str(error) + ' Games their launchers start are still listed.')
    if titles is None:
        titles = launcher_titles(ctx.home)
    games, seen = [], set()
    for row in installer.library_inventory(ctx.home):
        game = load_game(ctx, row['exe'], titles, tracked=True, inventory=row)
        games.append(game)
        seen.add(same_path(game.exe))
    for exe in added:
        if same_path(exe) in seen:
            continue
        seen.add(same_path(exe))
        games.append(load_game(ctx, exe, titles, added=True))
    games.sort(key=lambda g: (STATES.index(state(g, ctx)), g.title.casefold()))
    return games, notes


def same_path(path):
    try:
        return str(Path(path).absolute().resolve())
    except OSError:
        return str(Path(path).absolute())


# ----------------------------------------------------------------------------------------------- states and words
def state(game, ctx):
    """What matters most about a game now (STATES)."""
    record = game.record or {}
    status = record.get('status')
    if status == 'prepared' or record.get('pending_update'):
        return 'unavailable' if not game.present else 'recovery'
    if not game.present:
        return 'unavailable'
    if game.reason:
        return 'attention'
    if status != 'installed':
        return 'available'
    if record.get('update_pin'):
        return 'pinned'
    if record.get('package') != ctx.release:
        old, new = release_number(record.get('package')), release_number(ctx.release)
        if old and new and old > new:
            return 'newer'
        return 'update' if update_blocker(ctx, record) is None else 'outdated'
    return 'installed'


def update_blocker(ctx, record):
    """Why this package cannot update the installation in place (install.update_compatibility), None when it can."""
    check = getattr(ctx.installer, 'update_compatibility', None)
    if check is None:
        return None
    try:
        return check(record, ctx.manifest, True)
    except Exception as error:  # noqa: BLE001 - a record this build cannot read is a reason, not a crash
        return str(error)


def section(game, ctx):
    current = state(game, ctx)
    return next(key for key, _, states in SECTIONS if current in states)


def badge(game, ctx):
    """The short label beside a game in the list and its style (accent, success, warning, error, dim), or None."""
    current = state(game, ctx)
    if current == 'available':
        if not game.checked:
            return None
        return verdict_badge(game.verdict)
    return {'recovery': ('Needs recovery', 'error'), 'attention': ('Needs attention', 'warning'),
            'unavailable': ('Unavailable', 'dim'), 'update': ('Update', 'accent'), 'outdated': ('Earlier build', 'warning'),
            'newer': ('Newer build', 'dim'), 'pinned': ('Pinned', 'dim')}.get(current)


def provider_label(record):
    """The upscaler of an installation: 'FSR 4', 'HLX DLSS 3.1.0', 'HelixSR 2.0.0'."""
    upscaler = (record or {}).get('upscaler') or {}
    name = upscaler.get('name') or 'fsr4'
    labels = {'fsr4': 'FSR 4', 'helixsr': 'HelixSR', 'hlx-dlss': 'HLX DLSS', 'hlx-fsr4': 'HLX FSR 4'}
    label = labels.get(name, name)
    return label + (' ' + str(upscaler['version']) if upscaler.get('version') and name != 'fsr4' else '')


def input_label(record):
    """The frame-generation input of an installation: 'Native XeSS FG', 'OptiFG', 'DLSS FG', ..."""
    record = record or {}
    if record.get('route') == 'native':
        return INPUT_NAMES['native']
    chosen = next((change.get('value') for change in record.get('ini_changes') or []
                   if str(change.get('section')).lower() == 'framegen' and str(change.get('key')).lower() == 'fginput'), None)
    return INPUT_NAMES.get(chosen, 'OptiScaler input')


def subtitle(game, ctx):
    """The line under a game's title in the list."""
    current = state(game, ctx)
    record = game.record or {}
    if current == 'available':
        return 'Not installed' + (' · ' + verdict_view(game.verdict)[1] if game.checked and game.verdict else '')
    if current in ('unavailable', 'attention'):
        return game.reason or 'Needs attention'
    if current == 'recovery':
        return 'Interrupted ' + ('update' if record.get('pending_update') else 'installation')
    return version(record.get('package')) + ' · ' + provider_label(record)


def headline(game, ctx):
    """(level, title, description) at the top of a game's page."""
    current = state(game, ctx)
    record = game.record or {}
    name, release = ctx.name, version(record.get('package'))
    if current == 'available':
        if not game.checked:
            return 'neutral', 'Checking compatibility…', 'Reading the game folder. Nothing is changed.'
        if record.get('status') == 'restored' and not refusals(game.verdict, 'hard', 'risk', 'soft'):
            return 'neutral', 'Original files restored', 'Install ' + name + ' again any time.'
        return ready_view(game.verdict)
    if current == 'installed':
        return 'success', name + ' ' + release + ' is installed', provider_label(record) + ' · ' + input_label(record)
    if current == 'update':
        return 'accent', 'Update available', release + ' → ' + ctx.version + '. Settings, launch options and backups are kept.'
    if current == 'pinned':
        newer = record.get('package') != ctx.release
        return 'neutral', 'Pinned to ' + release, ('Update All leaves this game on ' + release +
                                                    (', although ' + ctx.version + ' is available.' if newer else '.'))
    if current == 'outdated':
        return 'warning', 'Installed by an earlier build', (update_blocker(ctx, record) or '') + \
            ' Restore the original files, then install ' + ctx.version + '.'
    if current == 'newer':
        return 'neutral', 'Installed by a newer ' + name, (release + ' is newer than this package (' + ctx.version + '). Use '
                                                          'the newer package’s Setup to change it.')
    if current == 'recovery':
        pending = record.get('pending_update') or {}
        if pending.get('generation'):
            return 'error', 'An ' + pending.get('kind', 'update') + ' was interrupted', \
                'Finish it, or undo it to return to the release before it. Nothing else can change this game until then.'
        if record.get('status') == 'prepared':
            return 'error', 'The installation was interrupted', 'Its backups were saved before anything changed: Restore ' \
                'returns the original files. Then install again.'
        return 'error', 'An update by an earlier build was interrupted', 'Restore returns the original files. Then install again.'
    if current == 'unavailable':
        return 'neutral', 'Unavailable', game.reason or 'The game’s executable is not there.'
    return 'warning', 'Needs attention', game.reason or ''


def session_view(run):
    """(level, label, detail lines) of the last session's logs, for an installed game."""
    if not run or not run.get('found'):
        return 'neutral', 'No recorded session', ['No logs yet: start the game once with frame generation on.']
    try:
        import compat
        lines = compat.last_run_lines(run)
    except Exception:  # noqa: BLE001
        lines = []
    if run.get('acceleration') in ACCELERATION:
        label, level = ACCELERATION[run['acceleration']]
    elif run.get('xefg'):
        label, level = 'Frame generation started', 'success'
    else:
        label, level = 'Frame generation did not start', 'warning'
    if run.get('problems') and level == 'success':
        level = 'warning'
    return level, label, lines


# ----------------------------------------------------------------------------------------------- compatibility
def input_choice(input_id):
    """install.compat_verdict's (route, fg_input) for an input: (None, None) for Automatic."""
    if input_id == 'auto':
        return None, None
    if input_id == 'native':
        return 'native', None
    return 'opti', input_id


def input_args(input_id):
    if input_id == 'auto':
        return ['--route', 'auto', '--fg-input', 'auto']
    if input_id == 'native':
        return ['--route', 'native']
    return ['--route', 'opti', '--fg-input', input_id]


def check_game(ctx, exe, input_id='auto', accept_risk=()):
    """The compatibility verdict for Install with this input (install.compat_verdict; reads only, no network), or None
    when the check cannot run."""
    route, fg_input = input_choice(input_id)
    extra = {'accept_risk': list(accept_risk)} if accept_risk else {}
    try:
        found = ctx.installer.compat_verdict(ctx.root, Path(exe).absolute(), route, fg_input, **extra)
    except Exception:  # noqa: BLE001 - Install then goes on as the command line does, without a verdict
        return None
    return found[0] if found else None


def refusals(verdict, *kinds):
    return [r for r in (verdict or {}).get('blocking', []) if r['kind'] in kinds]


def anticheat(verdict):
    """The anti-cheat refusal of a verdict (kind risk), whether lifted or not; None when the game ships none."""
    return next((r for r in (verdict or {}).get('refusals', []) if r['code'] == 'anticheat'), None)


def detection_only(refusal):
    """A refusal that rests on detection alone (compat.refusals: no DirectX 12 path, no input found): hard for Automatic,
    soft once the player chooses the input."""
    return refusal['code'] in ('no-input', 'no-dx12') or refusal['code'].startswith('api-')


def override_available(verdict):
    """Whether Install despite anti-cheat can help this game: it ships anti-cheat, and nothing else refuses it except
    detection, which the input chosen in Install settles. The override never lifts another hard refusal."""
    if not refusals(verdict, 'risk') or anticheat(verdict) is None:
        return False
    return not [r for r in refusals(verdict, 'hard') if not detection_only(r)]


def joined(names):
    """'A', 'A and B', 'A, B and C'."""
    names = [str(n) for n in names]
    return ' and '.join(names) if len(names) < 3 else ', '.join(names[:-1]) + ' and ' + names[-1]


# ----------------------------------------------------------------------------------------------- adding games
def installed_games(home=None):
    """The installed Steam and Heroic games (gamescan.installed_games): name, store, id and folder of each."""
    import gamescan
    return [game for game in gamescan.installed_games(home) if game.get('path')]


def find_executable(game, home=None):
    """dict(candidates): the game's likely rendering executables (gamescan.scan_folder), the one it picks first, as paths
    relative to the game folder; dict(error) when the folder cannot be scanned."""
    import gamescan
    scan = gamescan.scan_folder(game, home=home)
    if scan.get('error'):
        return dict(error='The game folder cannot be read: ' + str(scan['error']) + '.')
    found = scan.get('exe') or {}
    candidates = [c['rel'] for c in found.get('candidates') or [] if c.get('rel')]
    selected = found.get('selected')
    if selected:
        candidates = [selected] + [c for c in candidates if c != selected]
    return dict(candidates=candidates)


def steam_common(home=None):
    """Steam's game folder (steamapps/common of its first library), where the executable chooser starts; None without
    Steam."""
    home = Path(home or Path.home())
    for steam in (home / '.local/share/Steam', home / '.steam/steam', home / '.var/app/com.valvesoftware.Steam/.local/share/Steam'):
        common = steam / 'steamapps/common'
        if common.is_dir():
            return common
    return None


def verdict_view(verdict):
    """(level, title, text) of a verdict: what Install would do, or why it refuses."""
    if verdict is None:
        return 'neutral', 'Not checked', 'The compatibility check did not run; Install still checks the game itself.'
    hard, risk, soft = refusals(verdict, 'hard'), refusals(verdict, 'risk'), refusals(verdict, 'soft')
    if hard:
        return 'error', 'Not supported', hard[0]['text'] + ' ' + hard[0]['way']
    if risk:
        return 'error', 'Ships anti-cheat', risk[0]['text']
    if soft:
        return 'warning', 'Needs your OK', soft[0]['text']
    return ('success' if verdict.get('tier') in ('A', 'B') else 'accent'), verdict.get('name', ''), verdict.get('line', '')


def ready_view(verdict):
    """(level, title, text) at the top of a game that is not installed: whether Install can run, and how."""
    if verdict is None:
        return 'neutral', 'Ready to install', 'The compatibility check did not run; Install still checks the game itself.'
    hard, risk, soft = refusals(verdict, 'hard'), refusals(verdict, 'risk'), refusals(verdict, 'soft')
    if hard:
        return 'error', 'Not supported', hard[0]['text']
    if risk:
        return 'error', 'Ships anti-cheat', 'Install refuses it: anti-cheat software can answer injected DLLs with an ' \
            'account ban.'
    if soft:
        return 'warning', 'Needs your OK', soft[0]['text']
    route = INPUT_NAMES['native'] if verdict.get('route') == 'native' else \
        INPUT_NAMES.get(verdict.get('fg_input'), 'OptiFG') + ' input'
    how = route + (' · needs one step from you' if verdict.get('needs_step') else '')
    if verdict.get('tier') == 'A':
        return 'success', 'Verified on BC-250', 'Ready to install · ' + how
    if verdict.get('tier') == 'B':
        return 'success', 'Reported working on BC-250', 'Ready to install · ' + how
    return 'accent', 'Ready to install', 'Automatic · ' + how


def verdict_badge(verdict):
    if verdict is None:
        return None
    if refusals(verdict, 'hard'):
        return 'Not supported', 'error'
    if refusals(verdict, 'risk'):
        return 'Anti-cheat', 'error'
    if refusals(verdict, 'soft'):
        return 'Needs your OK', 'warning'
    if verdict.get('tier') == 'A':
        return 'Verified', 'success'
    if verdict.get('tier') == 'B':
        return 'Reported', 'success'
    return None


# ----------------------------------------------------------------------------------------------- commands
@dataclass
class InstallChoice:
    """What Install runs for one game: the input, the upscaler (and its install.py arguments), the soft refusals the user
    accepted, and the anti-cheat sentence when the user overrode that refusal for this game."""
    input: str = 'auto'
    provider: str = 'fsr4'
    provider_args: list = field(default_factory=list)
    accept: list = field(default_factory=list)
    risk_sentence: str = None


def install_args(exe, choice):
    args = ['install', str(exe), *input_args(choice.input), '--upscaler', choice.provider, *choice.provider_args]
    for code in choice.accept:
        args += ['--accept', code + '=' + str(exe)]
    if choice.risk_sentence is not None:
        args += ['--accept-anticheat-risk=' + str(exe), '--confirm-anticheat-risk', choice.risk_sentence]
    return args


def settings_args(before, after):
    """install.py configure's options for what changed between two Settings ([] when nothing did)."""
    args = []
    if after.factor != before.factor:
        args += ['--factor', str(after.factor)]
    if after.size != before.size or (after.size == 'scale' and after.percent != before.percent):
        if after.size == 'output':
            args += ['--resolution', 'output']
        elif after.size == 'scale':
            args += ['--percent', str(after.percent)]
        else:
            args += ['--limit', after.size]
    if after.downscale != before.downscale:
        args += ['--downscale', after.downscale]
    if after.upscale != before.upscale:
        args += ['--upscale', after.upscale]
    return args


def settings_support(record, max_factor=2):
    """Which Settings an installation offers, as install.configure decides: generated-frame scaling, the area downscale
    filter, the enlargement filters, and the factors."""
    managed = {item.get('path') for item in (record or {}).get('files', [])}
    own = 'BC250-XeFG/shaders/freefg-scaling.required' in managed
    modern = own or 'OptiScaler/plugins/BC250-XeFG/shaders/mfg-frame-settings.required' in managed
    top = min(int((record or {}).get('max_factor', max_factor) or 2), max_factor)
    return dict(scaling=modern and SETTINGS_INI in managed,
                area=own or 'OptiScaler/plugins/BC250-XeFG/shaders/mfg-downscale-filters.required' in managed,
                upscale=own or 'OptiScaler/plugins/BC250-XeFG/shaders/mfg-upscale-filters.required' in managed,
                factors=list(range(2, top + 1)) if (record or {}).get('route') == 'opti' else [2])


def integrity(ctx, game):
    """What changed since installation, as Status reports it: program files whose bytes differ from the record (settings
    files are the user's to change and are left out) and launcher entries no longer as installed."""
    installer, record = ctx.installer, game.record or {}
    root = game.exe.parent.resolve()
    changed, launchers = [], []
    for item in record.get('files', []):
        path = item.get('path', '')
        if path.lower().endswith('.ini'):
            continue
        try:
            target = installer.safe(root, path)
            actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        except (OSError, ValueError):
            actual = 'unreadable'
        if actual != item.get('after'):
            changed.append(path)
    try:
        import launcher_config
        for target in record.get('launchers') or []:
            try:
                same = launcher_config.fields(target, Path(target['path']).read_bytes()) == target['after']
            except (OSError, ValueError, KeyError):
                same = False
            launchers.append((str(target.get('launcher', 'launcher')).capitalize(), same))
    except ImportError:
        pass
    return dict(changed=changed, launchers=launchers)


# ----------------------------------------------------------------------------------------------- updates
@dataclass
class PlanItem:
    """One game in the update review: install.update_plan's status (or Setup's running, unavailable, failed), its reason,
    the releases, the changes (line, detail lines) and notes, and the plan's own lines."""
    exe: Path
    title: str
    status: str
    reason: str = ''
    source: str = None
    target: str = None
    changes: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    lines: list = field(default_factory=list)

    @property
    def group(self):
        return next(key for key, _, statuses in UPDATE_GROUPS if self.status in statuses)


def split_plan(lines):
    """install.plan_lines' lines after the first, as [(change, [detail, ...])] and the notes that follow."""
    changes, notes = [], []
    for line in lines[1:]:
        if line.startswith('    ') and changes:
            changes[-1][1].append(line.strip())
        elif line.startswith('  '):
            changes.append((line.strip(), []))
        elif line.strip():
            notes.append(line.strip())
    return changes, notes


def plan_game(ctx, game, component='all', refresh=False):
    """What Update would do in one game (install.update_plan; reads only), and whether the game is running."""
    installer = ctx.installer
    item = PlanItem(game.exe, game.title, 'unavailable', reason=game.reason or 'The game’s executable is not there.')
    if not game.present:
        return item
    root = game.exe.parent.resolve()
    try:
        record = read_record(installer, game.exe)
        if record is None:
            return PlanItem(game.exe, game.title, 'failed', reason=ctx.name + ' is not installed in this game.')
        plan = installer.update_plan(ctx.root, root, record, component, refresh_recipe=refresh)
    except Exception as error:  # noqa: BLE001 - one game's unreadable state never hides the others
        return PlanItem(game.exe, game.title, 'failed', reason=str(error))
    item = PlanItem(game.exe, game.title, plan['status'], plan.get('reason') or '', plan.get('source'), plan.get('target'))
    item.lines = installer.plan_lines(plan)
    if plan['status'] == 'update':
        item.changes, item.notes = split_plan(item.lines)
        try:
            installer.idle(root)
        except ValueError:
            item.status = 'running'
    return item


def plan_reason(item, ctx):
    """The line under a game in the update review, in Setup's words where the installer's name its commands."""
    if item.status in ('update', 'running'):
        # A recipe refresh (or an upscaler repair) can change a game without changing its release.
        line = version(item.source) + ' → ' + version(item.target) if item.source != item.target else \
            'Changes within ' + version(item.target)
        return line + (' · close the game first' if item.status == 'running' else '')
    if item.status == 'current':
        return 'Up to date (' + version(item.target or item.source) + ')'
    if item.status == 'pinned':
        return 'Pinned. Turn off “Keep this release” on its page to update it.'
    if item.status == 'interrupted':
        return 'An update was interrupted. Open the game to finish or undo it.'
    if item.status == 'unavailable':
        return item.reason or 'Unavailable'
    return item.reason


def update_args(exe, component='all', refresh=False):
    return ['update', str(exe), *(['--component', component] if component != 'all' else []),
            *(['--refresh-recipe'] if refresh else [])]


# ----------------------------------------------------------------------------------------------- upscalers
@dataclass
class Provider:
    """An upscaler Setup offers. state: 'ready'; 'unprepared' (HLX not prepared on this computer); for HelixSR before
    HLX, 'missing', 'unknown' or 'unbuilt' (helixsr.find)."""
    id: str
    label: str
    about: str
    state: str = 'ready'
    detail: str = ''
    version: str = None
    folder: str = None

    @property
    def ready(self):
        return self.state == 'ready'


def hlx_catalog(ctx):
    hlx = getattr(ctx.installer, 'hlx', None)
    if hlx is None:
        return None
    try:
        return hlx.catalog(ctx.root)
    except (OSError, ValueError):
        return None


def providers(ctx):
    """The upscalers this package installs, each with whether it is ready on this computer. HLX preparation is checked
    by hashing the prepared files (hlx.find): call it off the window's thread."""
    installer = ctx.installer
    out = [Provider('fsr4', 'FSR 4', 'AMD FSR 4, BC-250 build. The default; downloaded by checked hash.', detail='Built in')]
    if hlx_catalog(ctx):
        about = {'hlx-dlss': 'Helix DLSS network, prepared on this computer',
                 'hlx-fsr4': 'Helix FSR 4 provider, prepared on this computer'}
        for name, label in installer.hlx.NAMES.items():
            try:
                spec, folder, _ = installer.hlx.find(ctx.root, name)
                out.append(Provider(name, label, about.get(name, label), 'ready', 'Ready: ' + label + ' ' + spec['version'],
                                    spec['version'], str(folder)))
            except (OSError, ValueError) as error:
                out.append(Provider(name, label, about.get(name, label), 'unprepared', str(error)))
        return out
    helixsr = getattr(installer, 'helixsr', None)
    if helixsr is not None:
        try:
            found = helixsr.find(ctx.root)
            state_ = found['state'] if found['state'] in ('ready', 'missing', 'unknown', 'unbuilt') else 'missing'
            out.append(Provider('helixsr', 'HelixSR', 'NVIDIA’s DLSS network as compute shaders, by lonewolf0622', state_,
                                found.get('message') or '', str(found.get('pinned') or '') or None, found.get('folder')))
        except Exception as error:  # noqa: BLE001 - a broken pin is shown, never a crash
            out.append(Provider('helixsr', 'HelixSR', 'NVIDIA’s DLSS network as compute shaders, by lonewolf0622', 'missing',
                                str(error)))
    return out


def game_providers(ctx, game, prepared):
    """Reuse only qualified HLX files owned by this installation when its shared preparation cache is gone."""
    result = list(prepared)
    catalog = hlx_catalog(ctx)
    if not catalog or not game.installed:
        return result
    record = read_record(ctx.installer, game.exe)
    current = record.get('upscaler') or {}
    legacy = current.get('legacy_target') or current.get('target')
    if not legacy:
        return result
    library = current.get('library_root') or str(Path(legacy).parent)
    owned = {row['path']: row.get('after') for row in record.get('files', [])}
    for i, provider in enumerate(result):
        if provider.ready or provider.id not in catalog['providers']:
            continue
        descriptor = catalog['providers'][provider.id]
        base = Path(library) / 'custom' / provider.id / descriptor['api']
        try:
            for name, entry in descriptor['files'].items():
                path = (base / name).as_posix()
                if owned.get(path) != entry['sha256'] or ctx.installer.file_digest(game.folder, path) != entry['sha256']:
                    raise ValueError('Missing or changed game-local provider')
        except (OSError, ValueError):
            continue
        result[i] = replace(provider, state='ready', version=catalog['version'],
                            detail='Checked files in this game', folder=None)
    return result


def wiki_settings_plan(ctx, game):
    """The shared installer planner, with the current record and INI context; reads only."""
    plan = ctx.installer.wiki_settings_plan(ctx.root, game.exe)
    if not isinstance(plan, dict) or plan.get('format') != 1 or not isinstance(plan.get('rows'), list) or not re.fullmatch(
            r'[0-9a-f]{64}', str(plan.get('digest') or '')):
        raise ValueError('This package returned an unsupported wiki settings plan')
    return plan


def wiki_settings_args(game, plan, selected, confirmed):
    """Send only explicitly selected rows and confirmations, bound to the displayed plan."""
    return ['wiki-apply', str(game.exe), '--wiki-plan-digest', plan['digest'],
            *[part for token in selected for part in ('--wiki-setting', token)],
            *[part for token in confirmed for part in ('--wiki-confirm', token)]]


def hlx_requirements(which=None, run=subprocess.run):
    """[(what, present, how to get it)] that Prepare HLX needs besides the two model inputs (hlx.prepare)."""
    import shutil
    which = which or shutil.which
    try:
        numpy = run([sys.executable, '-c', 'import numpy'], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        numpy = False
    return [('Wine', bool(which('wine')), 'Install Wine with your distribution’s package manager.'),
            ('bubblewrap', bool(which('bwrap')), 'Install bubblewrap (bwrap).'),
            ('Python numpy', numpy, 'Install numpy for ' + sys.executable + ' (python-numpy).')]


# ----------------------------------------------------------------------------------------------- system check
def system_checks(ctx, run=subprocess.run):
    """doctor.checks(): [(level, item, text)] with level OK, WARN or INFO, from a process of its own."""
    try:
        out = run([sys.executable, '-c', DOCTOR, str(ctx.root)], capture_output=True, text=True, timeout=180)
        rows = json.loads(out.stdout.strip().splitlines()[-1])
        return [(str(level), str(item), str(text)) for level, item, text in rows]
    except (OSError, ValueError, IndexError, TypeError, subprocess.SubprocessError) as error:
        return [('WARN', 'System check', 'The check did not run (' + type(error).__name__ + '). Run python3 install.py doctor.')]


def system_summary(rows, name):
    """(level, title, description) over the system check's rows."""
    warnings = [item for level, item, _ in rows if level == 'WARN']
    if warnings:
        return ('warning', str(len(warnings)) + (' item needs' if len(warnings) == 1 else ' items need') + ' attention',
                ', '.join(warnings))
    return 'success', 'Ready for ' + name, 'Every check passed. Information rows describe this system.'


# ----------------------------------------------------------------------------------------------- results
def failure_reason(lines):
    """The installer's reason for a failed command: its last error line ([(stream, line)], stream 'err' or 'out')."""
    errors = [line for stream, line in lines if stream == 'err' and line.strip()]
    if errors:
        return errors[-1].strip()
    out = [line for _, line in lines if line.strip()]
    return out[-1].strip() if out else 'The installer stopped without a message.'


def next_steps(lines):
    """What the installer asks of the player after a change: its 'In game:' and 'Game setting pending:' lines."""
    return [line.strip() for _, line in lines if line.strip().startswith(('In game:', 'Game setting pending:'))]


# The installer's lines that say what a change did (install, update, rollback, restore, configure), for its outcome.
SUMMARY = ('Frame-generation input:', 'Kept your settings', 'Launch option added:', 'Launch option not added:', 'Upscaler:',
           'DLSS helper:', 'Game setting applied:', 'Game setting already set:', 'vkd3d-proton', 'Provider selection saved',
           'Rolled back', 'Original files', 'Settings saved', 'HLX ')


def summary_lines(lines):
    """What a finished command changed, in the installer's words: an update's plan lines (indented as plan_lines writes
    them) and the lines that name what was set, kept or restored."""
    out = []
    for stream, line in lines:
        text = line.strip()
        if stream != 'out' or not text:
            continue
        if (line.startswith('  ') and not line.startswith('    ')) or text.startswith(SUMMARY):
            out.append(text)
    return list(dict.fromkeys(out))
