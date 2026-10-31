#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pinned, game-independent HLX preparation and provider layouts. Built model files remain local."""
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

NAMES = {'hlx-dlss': 'HLX DLSS', 'hlx-fsr4': 'HLX FSR 4'}


class Busy(ValueError):
    """Another HLX preparation is running: nothing was changed; wait for it."""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def catalog(package):
    value = json.loads((Path(package) / 'dependencies.json').read_text()).get('hlx')
    if value is not None and (value.get('format') != 1 or set(value.get('providers', {})) != set(NAMES)):
        raise ValueError('Unsupported HLX catalog; use its matching installer')
    return value


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
    """Validate the whole locally prepared output, including model data, against the qualified build."""
    result = {}
    for relative, item in spec['providers'][provider]['files'].items():
        path = member(folder, item['source'])
        if not path.is_file():
            raise ValueError('Prepare HLX ' + spec['version'] + ' once: missing ' + str(path))
        data = path.read_bytes()
        if sha(data) != item['sha256']:
            raise ValueError('HLX file is not the qualified prepared build: ' + str(path) + '. Run Prepare HLX or select its prepared release folder.')
        result[relative] = data
    return result


def find(package, provider, explicit=None):
    spec = catalog(package)
    if not spec:
        raise ValueError('This package has no qualified HLX providers')
    folders=[Path(explicit)] if explicit else []
    if not explicit:
        try:
            saved=json.loads((cache(spec)/'location.json').read_text())['folder']
            if isinstance(saved,str) and Path(saved).is_absolute():folders.append(Path(saved))
        except (OSError,ValueError,KeyError,TypeError):pass
        folders.append(cache(spec)/spec['folder'])
    error=None
    for folder in folders:
        try:return spec,folder,check(folder,spec,provider)
        except (OSError,ValueError) as caught:error=caught
    raise ValueError(str(error))


def remember(package,folder):
    spec=catalog(package)
    if not spec:return
    path=cache(spec);path.mkdir(parents=True,exist_ok=True)
    temp=path/('.location-'+os.urandom(8).hex())
    try:
        temp.write_text(json.dumps({'folder':str(Path(folder).resolve())})+'\n')
        os.replace(temp,path/'location.json')
    finally:temp.unlink(missing_ok=True)


def layout(package, provider, library_root, explicit=None, current=None, root=None):
    spec = catalog(package)
    if not spec or provider not in spec['providers']:
        raise ValueError('This package has no qualified ' + provider + ' provider')
    descriptor = spec['providers'][provider]
    base = Path(library_root) / 'custom' / provider / descriptor['api']
    # A current portable install need not retain its preparation cache.
    data = None
    if explicit is None and current and root is not None:
        try:
            data = {name: member(root, (base / name).as_posix()).read_bytes() for name in descriptor['files']}
            if any(sha(data[name]) != entry['sha256'] for name, entry in descriptor['files'].items()):
                data = None
        except OSError:
            data = None
    if data is None:
        _, _, data = find(package, provider, explicit)
    files = {(base / name).as_posix(): value for name, value in data.items()}
    target = (base / descriptor['entry']).as_posix()
    metadata = dict(name=provider, target=target, version=spec['version'], library_root=str(library_root),
                    source_archive_sha256=spec['archive']['sha256'], adapter='hlx-custom-v1', files=list(files))
    changes = {('Upscalers', 'Dx12Upscaler'): provider, (provider, 'UpscalerIndex'): '0'}
    if provider == 'hlx-dlss':
        ini = (base / 'helixsr.ini').as_posix()
        metadata.update(ini=ini, log=(base / 'helixsr.log').as_posix())
    else:metadata['log']=(base/'HLX_FSR.log').as_posix()
    return dict(component=provider, files=files, metadata=metadata, ini_changes=changes)


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
    """The bubblewrap command prefix Prepare HLX runs upstream's build in: namespaces of its own (no network, no other
    processes or abstract sockets), a session of its own (no input into this terminal), ended with this process, and an
    empty environment but for what the build needs. The host is read-only and /dev holds only the standard devices. The
    home folder, the session's runtime folder (D-Bus, PipeWire, Wayland and agent sockets) and the system bus folder are
    empty in it, /tmp is staging's tmp folder, and readable paths inside those (the model inputs, Python, numpy or Wine
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


def prepare(package, dlss, amd, wine='wine', download=None, report=print):
    """Run upstream's build-only Python entry point, never its game setup script. Network access is disabled for builds.
    report prints the line that says what was prepared (install.py: with its event)."""
    spec = catalog(package)
    if not spec:raise ValueError('This package has no HLX catalog')
    for name, path in [('dlss', dlss), ('amd', amd)]:
        if not path or not Path(path).is_file() or sha(Path(path).read_bytes()) != spec['model_inputs'][name]:
            raise ValueError('Select the qualified local ' + name.upper() + ' input (SHA-256 ' + spec['model_inputs'][name] + '). See the HLX preparation guide.')
    for binary in ('bwrap', wine):
        if shutil.which(binary) is None:raise ValueError('HLX preparation requires ' + binary)
    try:import numpy  # upstream builder dependency, no package installation side effects
    except ImportError as error:raise ValueError('HLX preparation requires Python numpy') from error
    if download is None:
        import dependencies
        download = dependencies.download
    work = cache(spec);work.mkdir(parents=True, exist_ok=True)
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
        for name, pin in spec['compilers'].items():
            compiler = staging / name;compiler.mkdir()
            unpack(Path(download(pin, work)), compiler, compiler=True)
        wrapper = staging / 'dxc-wine.py';prefix = staging / 'wineprefix'
        wine_path = shutil.which(wine)
        wrapper.write_text('#!' + sys.executable + '\nimport os,sys\nos.environ["WINEDEBUG"]="-all"\nos.environ["WINEPREFIX"]=' + repr(str(prefix)) + '\nargs=["Z:"+x.replace("/",chr(92)) if x.startswith("/") else x for x in sys.argv[1:]]\nos.execv(' + repr(wine_path) + ',["wine",' + repr(str(staging / 'dxc2607/dxc.exe')) + ',*args])\n')
        wrapper.chmod(0o755)
        release = staging / spec['folder']
        command = [sys.executable, str(release / 'setup/helixsr_setup.py'), str(release), '--no-fg', '--yes',
                   '--dlss', str(Path(dlss).resolve()), '--amd', str(Path(amd).resolve()), '--dxc', str(wrapper),
                   '--dxc-dir', str(staging / 'dxc2607'), '--dxc2609-dir', str(staging / 'dxc2609'),
                   '--wine', wine_path, '--wineprefix', str(prefix)]
        (staging / 'tmp').mkdir()
        # What the build reads that may live in a folder the sandbox empties: the inputs, Python, numpy and Wine.
        readable = [Path(dlss).resolve(), Path(amd).resolve(), Path(sys.executable).resolve().parent,
                    *{Path(folder).resolve() for folder in (sys.prefix, sys.base_prefix, sys.exec_prefix)},
                    Path(numpy.__file__).resolve().parents[1], Path(wine_path).resolve().parent]
        subprocess.run(sandbox(staging, readable) + command, check=True)
        for provider in NAMES:check(release, spec, provider)
        target = work / spec['folder']
        old = work / ('.previous-' + os.urandom(4).hex())
        if target.exists():os.replace(target, old)
        os.replace(release, target)
        if old.exists():shutil.rmtree(old)
        remember(package,target)
        report('HLX ' + spec['version'] + ' prepared for all enrolled games: ' + str(target))
        return target
    finally:
        if staging is not None:shutil.rmtree(staging, ignore_errors=True)
        os.close(descriptor)
