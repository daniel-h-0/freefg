#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pinned, game-independent Helix (HLX) preparation and provider layouts. Built model files remain local.

HelixSR 3.3.0 offers four upscalers. Two are built on this computer from NVIDIA's DLSS DLL (HLX DLSS Model E and,
optionally, Preset K: descriptor key "build"); two come built in the official archive (HLX FSR 4 and HLX FSR 4 Full)
and only need that archive downloaded, checked and unpacked."""
import hashlib
import fcntl
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import helixsr

NAMES = {'hlx-dlss': 'HLX DLSS Model E', 'hlx-dlss-k': 'HLX DLSS Preset K', 'hlx-fsr4': 'HLX FSR 4',
         'hlx-fsr4-full': 'HLX FSR 4 Full'}
# The upscaler Setup and install suggest when it is prepared on this computer.
SUGGESTED = 'hlx-dlss'
# A recipe's upscaler rules are written per family: both HLX DLSS networks take HelixSR's, both HLX FSR 4 forms theirs.
RECIPE = {'hlx-dlss': 'helixsr', 'hlx-dlss-k': 'helixsr', 'hlx-fsr4': 'hlx-fsr4', 'hlx-fsr4-full': 'hlx-fsr4'}
FORMAT = 2
# Upscalers nothing asks for: a long build of their own, never a problem when they are not there.
OPTIONAL = ('hlx-dlss-k',)
NVIDIA_LICENSE = 'https://github.com/NVIDIA/DLSS/blob/main/LICENSE.txt'


class Busy(ValueError):
    """Another HLX preparation is running: nothing was changed; wait for it."""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def catalog(package):
    value = json.loads((Path(package) / 'dependencies.json').read_text()).get('hlx')
    if value is not None and (value.get('format') != FORMAT or set(value.get('providers', {})) != set(NAMES)):
        raise ValueError('Unsupported HLX catalog; use its matching installer')
    return value


def recipe_name(provider):
    """The name a recipe's upscaler rules use for a provider (RECIPE; any other upscaler's own name)."""
    return RECIPE.get(provider, provider)


def built(spec, provider):
    """What HelixSR's setup builds for a provider on this computer ('network' or 'preset-k'), None when it comes built."""
    return spec['providers'][provider].get('build')


def cache(catalog):
    return helixsr.cache_root().parent / 'hlx' / catalog['archive']['sha256']


def member(root, relative):
    path = Path(relative)
    if path.is_absolute() or '..' in path.parts or '\\' in relative or not path.parts:
        raise ValueError('Unsafe HLX path: ' + relative)
    dest = Path(root)
    for part in path.parts:
        dest /= part
        if dest.is_symlink():
            raise ValueError('HLX paths cannot contain symlinks: ' + str(dest))
    return dest


def check(folder, spec, provider):
    """Validate the whole provider, including locally built model data, against the qualified build."""
    result = {}
    for relative, item in spec['providers'][provider]['files'].items():
        path = member(folder, item['source'])
        if not path.is_file():
            how = ('Prepare Helix ' + spec['version'] + ' once (' + NAMES[provider] + '; install.py hlx' +
                   (' --preset-k' if provider in OPTIONAL else '') + ')' if built(spec, provider) else
                   'Download HelixSR ' + spec['version'] + ' once (' + NAMES[provider] + ' comes built in it; install.py hlx --no-build)')
            raise ValueError(how + ': missing ' + str(path))
        data = path.read_bytes()
        if sha(data) != item['sha256']:
            raise ValueError(NAMES[provider] + ' file is not the qualified build: ' + str(path) +
                             '. Run Prepare Helix or select its prepared release folder.')
        result[relative] = data
    return result


def settings(folder, spec, provider):
    """The provider's settings template from a prepared folder (bytes), None when it has none or it is not there."""
    template = spec['providers'][provider].get('settings') or {}
    if not template.get('source'):
        return None
    try:
        data = member(folder, template['source']).read_bytes()
    except (OSError, ValueError):
        return None
    return data if sha(data) == template['sha256'] else None


def folders(spec, explicit=None):
    """Where a prepared release may be: the folder given, else the remembered one, then the cache's own."""
    if explicit:
        return [Path(explicit)]
    found = []
    try:
        saved = json.loads((cache(spec) / 'location.json').read_text())['folder']
        if isinstance(saved, str) and Path(saved).is_absolute():
            found.append(Path(saved))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    found.append(cache(spec) / spec['folder'])
    return found


def find(package, provider, explicit=None):
    spec = catalog(package)
    if not spec:
        raise ValueError('This package has no qualified HLX providers')
    error = None
    for folder in folders(spec, explicit):
        try:
            return spec, folder, check(folder, spec, provider)
        except (OSError, ValueError) as caught:
            error = caught
    raise ValueError(str(error))


def remember(package, folder):
    spec = catalog(package)
    if not spec:
        return
    path = cache(spec)
    path.mkdir(parents=True, exist_ok=True)
    temp = path / ('.location-' + os.urandom(8).hex())
    try:
        temp.write_text(json.dumps({'folder': str(Path(folder).resolve())}) + '\n')
        os.replace(temp, path / 'location.json')
    finally:
        temp.unlink(missing_ok=True)


def layout(package, provider, library_root, explicit=None, current=None, root=None):
    spec = catalog(package)
    if not spec or provider not in spec['providers']:
        raise ValueError('This package has no qualified ' + provider + ' provider')
    descriptor = spec['providers'][provider]
    base = Path(library_root) / 'custom' / provider / descriptor['api']
    # A current portable install need not retain its preparation cache.
    data = None
    template = None
    if explicit is None and current and root is not None:
        try:
            data = {name: member(root, (base / name).as_posix()).read_bytes() for name in descriptor['files']}
            if any(sha(data[name]) != entry['sha256'] for name, entry in descriptor['files'].items()):
                data = None
        except OSError:
            data = None
    if data is None:
        _, folder, data = find(package, provider, explicit)
        template = settings(folder, spec, provider)
    else:
        for folder in folders(spec):
            template = template or settings(folder, spec, provider)
    files = {(base / name).as_posix(): value for name, value in data.items()}
    target = (base / descriptor['entry']).as_posix()
    metadata = dict(name=provider, target=target, version=spec['version'], library_root=str(library_root),
                    source_archive_sha256=spec['archive']['sha256'], adapter='hlx-custom-v1', files=list(files),
                    log=(base / descriptor['log']).as_posix())
    changes = {('Upscalers', 'Dx12Upscaler'): provider, (provider, 'UpscalerIndex'): '0'}
    if descriptor.get('settings'):
        metadata['ini'] = (base / descriptor['settings']['name']).as_posix()
    return dict(component=provider, files=files, metadata=metadata, ini_changes=changes, settings=template)


def settings_bytes(provider, existing=None, template=None):
    """The settings file a provider gets in a game: the game's own (or the one an earlier Restore kept) when there is
    one, else HelixSR's template. An NGX provider's helixsr.ini always has HelixSR's own frame generation off."""
    if provider in ('hlx-dlss', 'hlx-dlss-k'):
        return helixsr.ini_bytes(existing if existing is not None else template)
    return existing if existing is not None else template


def unpack(archive, target, folder=None, compiler=False):
    """Validate all members before extracting; preserve upstream executable bits."""
    with zipfile.ZipFile(archive) as z:
        members = z.infolist()
        seen = set()
        total = 0
        for item in members:
            name = item.filename.replace('\\', '/') if compiler else item.filename
            path = member(target, name)
            kind = (item.external_attr >> 16) & 0o170000
            if kind not in (0, 0o100000, 0o040000) or ':' in name or name.casefold() in seen:
                raise ValueError('Unsafe or duplicate archive member: ' + name)
            if folder and Path(name).parts[0] != folder:
                raise ValueError('Unexpected HLX archive root')
            seen.add(name.casefold());total += item.file_size
        if total > 2 << 30:
            raise ValueError('HLX preparation archive exceeds its extraction limit')
        for item in members:
            name = item.filename.replace('\\', '/') if compiler else item.filename
            if compiler:
                if not name.startswith('bin/x64/') or item.is_dir():continue
                path = target / Path(name).name
            else:path = member(target, name)
            if item.is_dir():path.mkdir(parents=True, exist_ok=True);continue
            path.parent.mkdir(parents=True, exist_ok=True)
            with z.open(item) as source, path.open('wb') as output:
                shutil.copyfileobj(source, output)
            path.chmod(0o755 if (item.external_attr >> 16) & 0o111 else 0o644)


def sandbox(staging, readable=(), environ=None, home=None, uid=None):
    """The bubblewrap command prefix Prepare Helix runs upstream's build in: namespaces of its own (no network, no other
    processes or abstract sockets), a session of its own (no input into this terminal), ended with this process, and an
    empty environment but for what the build needs. The host is read-only and /dev holds only the standard devices. The
    home folder, the session's runtime folder (D-Bus, PipeWire, Wayland and agent sockets) and the system bus folder are
    empty in it, /tmp is staging's tmp folder, and readable paths inside those (the model input, Python, numpy or Wine
    where they live there) are seen read-only. Only staging is writable."""
    environ = os.environ if environ is None else environ
    home, uid, staging = Path(home or Path.home()), os.getuid() if uid is None else uid, Path(staging)
    command = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session', '--clearenv',
               '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc']
    hidden = [folder for folder in (home, Path('/run/user') / str(uid), Path('/run/dbus')) if folder.is_dir()]
    for folder in hidden:
        command += ['--tmpfs', str(folder)]
    command += ['--bind', str(staging / 'tmp'), '/tmp']
    for path in sorted({Path(path) for path in readable}):
        if any(folder in path.parents for folder in [*hidden, Path('/tmp')]):
            command += ['--ro-bind', str(path), str(path)]
    command += ['--bind', str(staging), str(staging), '--chdir', str(staging)]
    for key, value in dict(PATH=environ.get('PATH') or '/usr/local/bin:/usr/bin:/bin', HOME=str(home), LANG='C.UTF-8',
                           TMPDIR='/tmp', XDG_CACHE_HOME=str(staging / 'cache'), PYTHONDONTWRITEBYTECODE='1',
                           HELIXSR_SETUP_JOBS='4', WINEDEBUG='-all').items():
        command += ['--setenv', key, value]
    return command + ['--']


def requirements(which=shutil.which):
    """What building HLX DLSS needs on this computer besides its model input: the names of what is missing."""
    missing = [binary for binary in ('bwrap', 'wine') if which(binary) is None]
    try:
        import numpy  # noqa: F401 - upstream builder dependency, no package installation side effects
    except ImportError:
        missing.append('Python numpy')
    return missing


def dlss_input(package, explicit=None, fetch=False, download=None):
    """NVIDIA's DLSS DLL that HLX DLSS is built from, as a local file with the pinned SHA-256: the file given, else the
    copy this installer's download cache already holds (the DLSS input helper of an earlier installation), else, only
    with fetch (the user agreed to the download), the pinned file from NVIDIA's own repository."""
    spec = catalog(package)
    wanted = spec['model_inputs']['dlss']
    named = 'NVIDIA’s DLSS ' + spec['model_inputs']['dlss_version'] + ' DLL' if spec['model_inputs'].get('dlss_version') \
        else 'NVIDIA’s DLSS DLL'
    if explicit:
        if not Path(explicit).is_file() or sha(Path(explicit).read_bytes()) != wanted:
            raise ValueError('Select ' + named + ' (nvngx_dlss.dll with SHA-256 ' + wanted + ') as the local DLSS input.')
        return Path(explicit).resolve()
    import dependencies
    pins = json.loads((Path(package) / 'dependencies.json').read_text())
    pin = next((item for item in (pins.get('inputs') or {}).values() if item.get('sha256') == wanted), None)
    if pin:
        held = Path(dependencies.cache_dir()) / pin['file']
        if held.is_file() and sha(held.read_bytes()) == wanted:
            return held
        if fetch:
            Path(dependencies.cache_dir()).mkdir(parents=True, exist_ok=True)
            return Path((download or dependencies.download)(pin, Path(dependencies.cache_dir())))
    raise ValueError('HLX DLSS is built on this computer from ' + named + ' (SHA-256 ' + wanted + '). Give a local copy '
                     '(install.py hlx --dlss-input FILE), or agree to its download from NVIDIA’s repository under '
                     'NVIDIA’s licence (install.py hlx --download-dlss; ' + NVIDIA_LICENSE + ').')


def _reuse(spec, release, previous, provider):
    """Copy a provider's files an earlier preparation built into release; whether they were there and qualified."""
    try:
        data = check(previous, spec, provider)
    except (OSError, ValueError):
        return False
    descriptor = spec['providers'][provider]
    for name, item in descriptor['files'].items():
        path = member(release, item['source'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data[name])
    template = descriptor.get('settings') or {}
    if template.get('source') and not member(release, template['source']).is_file():
        kept = settings(previous, spec, provider)
        if kept is not None:
            member(release, template['source']).write_bytes(kept)
    return True


def prepare(package, dlss=None, wine='wine', download=None, report=print, preset_k=False, build=True, fetch_dlss=False):
    """Download, check and unpack the official archive, then (build) run upstream's build-only Python entry point for
    HLX DLSS Model E and, with preset_k, Preset K; never its game setup script. Network access is disabled for builds.
    What an earlier preparation built is kept, not built again. report prints the lines that say what was prepared
    (install.py: with its event). Returns the prepared folder; a Preset K that did not build leaves the rest prepared
    and raises."""
    spec = catalog(package)
    if not spec:raise ValueError('This package has no HLX catalog')
    if download is None:
        import dependencies
        download = dependencies.download
    work = cache(spec);work.mkdir(parents=True, exist_ok=True)
    target = work / spec['folder']
    # What is built already (also in a folder prepared elsewhere and remembered) needs no second build.
    wanted = [name for name in NAMES if built(spec, name) and (name != 'hlx-dlss-k' or preset_k)] if build else []
    have = set()
    for name in [name for name in NAMES if built(spec, name)]:
        for folder in folders(spec):
            try:check(folder, spec, name);have.add(name);break
            except (OSError, ValueError):pass
    todo = [name for name in wanted if name not in have]
    if todo:
        missing = requirements()
        if missing:raise ValueError('Building HLX DLSS requires ' + ', '.join(missing))
        dlss = dlss_input(package, dlss, fetch_dlss, download)
    # Rebuild into a fresh folder; interrupted output never replaces the last qualified preparation.
    descriptor=os.open(work/'.prepare.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(descriptor);raise Busy('HLX preparation is already running; wait for it to finish') from error
    staging=None
    try:
        staging = Path(tempfile.mkdtemp(prefix='.prepare-', dir=work))
        archive = Path(download(spec['archive'], work))
        unpack(archive, staging, spec['folder'])
        release = staging / spec['folder']
        for name in sorted(have):
            if not any(_reuse(spec, release, folder, name) for folder in folders(spec)):
                raise ValueError('The earlier ' + NAMES[name] + ' build changed while it was read; run Prepare Helix again')
        failed = None
        if todo:
            for name, pin in spec['compilers'].items():
                compiler = staging / name;compiler.mkdir()
                unpack(Path(download(pin, work)), compiler, compiler=True)
            wrapper = staging / 'dxc-wine.py';prefix = staging / 'wineprefix'
            wine_path = shutil.which(wine)
            wrapper.write_text('#!' + sys.executable + '\nimport os,sys\nos.environ["WINEDEBUG"]="-all"\nos.environ["WINEPREFIX"]=' + repr(str(prefix)) + '\nargs=["Z:"+x.replace("/",chr(92)) if x.startswith("/") else x for x in sys.argv[1:]]\nos.execv(' + repr(wine_path) + ',["wine",' + repr(str(staging / 'dxc2607/dxc.exe')) + ',*args])\n')
            wrapper.chmod(0o755)
            # --no-hlx: HLX FSR 4 comes built; --no-cache: nothing is read from or kept in HelixSR's own build cache
            # (the sandbox's home is empty); --fg-only: the network is there already, only Preset K is built.
            command = [sys.executable, str(release / 'setup/helixsr_setup.py'), str(release), '--no-fg', '--yes', '--no-hlx',
                       '--no-cache', '--dlss', str(Path(dlss).resolve()), '--dxc', str(wrapper)]
            if 'hlx-dlss' not in todo:command.append('--fg-only')
            if 'hlx-dlss-k' in todo:command.append('--preset-k')
            (staging / 'tmp').mkdir()
            import numpy
            # What the build reads that may live in a folder the sandbox empties: the input, Python, numpy and Wine.
            readable = [Path(dlss).resolve(), Path(sys.executable).resolve().parent,
                        *{Path(folder).resolve() for folder in (sys.prefix, sys.base_prefix, sys.exec_prefix)},
                        Path(numpy.__file__).resolve().parents[1], Path(wine_path).resolve().parent]
            # 5: the network is built and Preset K is not (upstream prints why): the rest is kept.
            result = subprocess.run(sandbox(staging, readable) + command)
            if result.returncode not in (0, 5):
                raise subprocess.CalledProcessError(result.returncode, command)
            if result.returncode == 5:failed = 'hlx-dlss-k'
        ready = []
        for name in NAMES:
            if built(spec, name) and name not in have and name not in todo:continue
            if name == failed:continue
            check(release, spec, name);ready.append(name)
        if (staging / 'wineprefix').exists():shutil.rmtree(staging / 'wineprefix', ignore_errors=True)
        old = work / ('.previous-' + os.urandom(4).hex())
        if target.exists():os.replace(target, old)
        os.replace(release, target)
        if old.exists():shutil.rmtree(old)
        remember(package,target)
        report('Helix ' + spec['version'] + ' prepared for all enrolled games (' + ', '.join(NAMES[name] for name in ready) + '): ' + str(target))
        if failed:raise ValueError(NAMES[failed] + ' was not built (the lines above say why); the other Helix upscalers are prepared.')
        return target
    finally:
        if staging is not None:shutil.rmtree(staging, ignore_errors=True)
        os.close(descriptor)
