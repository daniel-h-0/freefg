#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""HelixSR as an optional upscaler: find, download and check an official HelixSR release on this computer.

HelixSR (https://github.com/lonewolf0622/HelixSR) is a separate project by lonewolf0622, closed source, under its own
licence (the HelixSR Freeware License). It runs NVIDIA's DLSS Model E upscaling network as Direct3D 12 compute shaders
and offers it through AMD's FidelityFX (FSR 3.1) upscaler interface, so OptiScaler loads it the way it loads the FSR 4
DLL: as OptiScaler/amd_fidelityfx_upscaler_dx12.dll (HelixSR's own "FSR drop-in" uses that file name too). The
release archive of this project contains no HelixSR file.

What this module does:
- download_release(): the complete, unmodified official release archive from HelixSR's GitHub releases, pinned by
  version and SHA-256 in dependencies.json ('inputs' and 'helixsr'), into the download cache, and unpack it there as it
  is (the folder HelixSR-<version>/). That is a download from the author's own release page on the user's request, the
  same as the user downloading it by hand; nothing is redistributed.
- check_release(): whether a HelixSR release folder holds an official HelixSR DLL this installer knows (its SHA-256 as
  shipped, pinned per version) and whether HelixSR's own setup has built the network into it on this computer. HelixSR's
  setup appends the network to the DLL behind a 32-byte footer (magic HXSRNET1, the sizes of its two parts and a format
  number; documented in HelixSR's setup/helixsr_setup.py); the check hashes the DLL without that appended part, so a
  DLL that is anything but the official file plus the locally built network is refused.
- find(): such a folder: the one given (--helixsr), the one remembered from an earlier --helixsr, the download cache,
  and HelixSR-* folders in the home folder and in its Downloads and Applications folders.

What it never does: download NVIDIA's files, build the network, run HelixSR's setup or uninstaller, or change, rename,
repackage or redistribute HelixSR's files. Only HelixSR's own setup asks the user before it downloads NVIDIA's DLSS DLL
and builds the network locally; the files it builds are NVIDIA's and stay on this computer (install.py copies the built
DLL into the user's own game folders, as HelixSR's own installer does, and Restore removes those copies).

Frame generation stays XeFG's: the installer writes helixsr.ini beside the DLL with [DlssFrameGeneration] Enabled =
false (HelixSR's documented switch: its DLSS frame generation is then never loaded) and never copies HelixSR's
helixsr-fg folder, which that frame generation needs. Changing settings through helixsr.ini is not a modification of
HelixSR under its licence (section 3).
"""
import hashlib
import json
import os
import shlex
import shutil
import struct
import tempfile
import zipfile
from pathlib import Path

AUTHOR = 'lonewolf0622'
PROJECT = 'https://github.com/lonewolf0622/HelixSR'
LABEL = 'HelixSR (by lonewolf0622)'
# In a release folder: HelixSR's DLL (upscaler; its setup appends the network to it), its setup script.
RELEASE_DLL = 'HelixSR-fsrfg/amd_fidelityfx_dx12.dll'
SETUP_SCRIPT = 'helixsr-setup.sh'
# Beside the DLL in a game: HelixSR's settings file and its log.
INI = 'helixsr.ini'
LOG = 'helixsr.log'
# The footer HelixSR's setup appends after the network: magic, u64 weights size, u64 kernel-pack size, u64 format.
FOOTER = 32
MAGIC = b'HXSRNET1'
# HelixSR's own installers leave this record beside a drop-in they placed (helixsr_games.py MARKER).
HELIXSR_MARKER = 'helixsr-install.json'
EXTRACT_LIMIT = 1 << 30
# helixsr.ini as the installer writes it when the folder has none. Every other HelixSR setting keeps its default.
INI_TEXT = ('; helixsr.ini, written by the frame-generation installer that placed HelixSR here; Restore removes it.\r\n'
            '; HelixSR is a separate project by lonewolf0622 under its own licence: ' + PROJECT + '\r\n'
            '; Frame generation in this game is XeFG\'s: HelixSR\'s own DLSS frame generation stays off.\r\n'
            '\r\n'
            '[DlssFrameGeneration]\r\n'
            'Enabled = false\r\n')


def pins(package):
    """dependencies.json's 'helixsr' entry with its download input, or None when the package pins no HelixSR."""
    try:
        data = json.loads((Path(package) / 'dependencies.json').read_text())
    except (OSError, ValueError):
        return None
    entry = data.get('helixsr')
    if not isinstance(entry, dict):
        return None
    item = data.get('inputs', {}).get(entry.get('Input'))
    releases = entry.get('Releases')
    if not isinstance(item, dict) or not isinstance(releases, dict) or not releases or not entry.get('Folder') or not entry.get('Version'):
        raise ValueError('dependencies.json: incomplete HelixSR pin')
    if Path(entry['Folder']).name != entry['Folder'] or entry['Folder'] in ('.', '..'):
        raise ValueError('dependencies.json: unsafe HelixSR folder name')
    return dict(entry, input=item)


def cache_root():
    """Where the downloaded HelixSR release is unpacked: the installer's download cache (dependencies.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('bc250_dependencies_helixsr', Path(__file__).resolve().parent / 'dependencies.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return Path(module.cache_dir()) / 'helixsr'


def _sha256(path, length=None):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        left = length
        while left is None or left > 0:
            chunk = stream.read(1 << 20 if left is None else min(1 << 20, left))
            if not chunk:
                break
            digest.update(chunk)
            if left is not None:
                left -= len(chunk)
    return digest.hexdigest()


def network_size(path):
    """The size of the network HelixSR's setup appended to the DLL at path (weights, kernels and footer), or None when
    there is none or its footer does not describe a plausible one."""
    size = path.stat().st_size
    if size < FOOTER + 2:
        return None
    with open(path, 'rb') as stream:
        stream.seek(size - FOOTER)
        tail = stream.read(FOOTER)
    if tail[:8] != MAGIC:
        return None
    weights, kernels, version = struct.unpack('<QQQ', tail[8:])
    if version != 1 or not (0 < weights < 1 << 31 and 0 < kernels < 1 << 31) or weights + kernels > size - FOOTER - 2:
        return None
    return weights + kernels + FOOTER


def check_release(folder, pinned):
    """What folder holds: dict(state, folder, dll, version, message). state is 'ready' (an official HelixSR DLL this
    installer knows, with the network HelixSR's setup built on this computer), 'unbuilt' (the official DLL as
    downloaded: HelixSR's setup has not run yet), 'unknown' (a DLL that is not an official release this installer pins)
    or 'missing'."""
    folder = Path(folder)
    dll = folder / RELEASE_DLL
    base = dict(folder=str(folder), dll=str(dll), version=None)
    try:
        regular = dll.is_file()
    except OSError:
        regular = False
    if not regular:
        return dict(base, state='missing', message='No HelixSR release in ' + str(folder) + ' (' + RELEASE_DLL + ' not found).')
    known = pinned['Releases']
    try:
        appended = network_size(dll)
        size = dll.stat().st_size
        digest = _sha256(dll, size - appended if appended else None)
    except OSError as error:
        return dict(base, state='missing', message='Cannot read ' + str(dll) + ': ' + str(error))
    version = known.get(digest)
    if version is None:
        return dict(base, state='unknown', message=str(dll) + ' is not an official HelixSR release this installer knows '
                    '(it knows HelixSR ' + ', '.join(sorted(set(known.values()))) + '). A newer HelixSR needs an updated '
                    'installer; a changed DLL is not used.')
    if not appended:
        return dict(base, state='unbuilt', version=version, message='HelixSR ' + version + ' is in ' + str(folder) +
                    ', but its setup has not built the network on this computer yet.')
    return dict(base, state='ready', version=version, message='HelixSR ' + version + ' is ready in ' + str(folder) +
                ' (network built on this computer by HelixSR\'s setup).')


def dll_bytes(found, pinned):
    """The bytes of a ready release's DLL (check_release state 'ready'), checked again as read: the official DLL of a
    pinned version with the network HelixSR's setup appended. These are what the installer copies into a game."""
    data = Path(found['dll']).read_bytes()
    tail = data[-FOOTER:]
    if len(data) < FOOTER + 2 or tail[:8] != MAGIC:
        raise ValueError('HelixSR\'s DLL changed while it was read: ' + found['dll'])
    weights, kernels, version = struct.unpack('<QQQ', tail[8:])
    end = len(data) - FOOTER - weights - kernels
    if version != 1 or end < 2 or pinned['Releases'].get(hashlib.sha256(data[:end]).hexdigest()) != found['version']:
        raise ValueError('HelixSR\'s DLL changed while it was read: ' + found['dll'])
    return data


def _remembered():
    try:
        value = json.loads((cache_root() / 'location.json').read_text()).get('folder')
        return Path(value) if isinstance(value, str) else None
    except (OSError, ValueError, AttributeError):
        return None


def remember(folder):
    """Remember a release folder the user named (--helixsr), so that Setup and later runs find it."""
    root = cache_root()
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / ('.location-' + os.urandom(4).hex())
    temporary.write_text(json.dumps({'folder': str(Path(folder).resolve())}) + '\n')
    os.replace(temporary, root / 'location.json')


def candidates(pinned, home=None, explicit=None):
    """Release folders to look at, in order: the one given, the one remembered, the download cache, then HelixSR-*
    folders (and HelixSR-* folders inside them) in the home folder and its Downloads and Applications folders."""
    home = Path(home or Path.home())
    found = []

    def add(path):
        if path is not None and path not in found:
            found.append(path)
    if explicit is not None:
        add(Path(explicit))
        return found
    add(_remembered())
    add(cache_root() / pinned['Folder'])
    for place in (home, home / 'Downloads', home / 'Applications'):
        try:
            tops = sorted(p for p in place.glob('HelixSR*') if p.is_dir())
        except OSError:
            continue
        for top in tops:
            add(top)
            try:
                for inner in sorted(p for p in top.glob('HelixSR-*') if p.is_dir()):
                    add(inner)
            except OSError:
                pass
    return found


def find(package, home=None, explicit=None):
    """The best HelixSR release on this computer: dict as check_release, plus 'pinned' (the version the package pins)
    and 'checked' (every folder looked at). A ready release of the pinned version comes first, then any ready one,
    then one waiting for HelixSR's setup."""
    pinned = pins(package)
    if pinned is None:
        return dict(state='unsupported', folder=None, dll=None, version=None, pinned=None, checked=[],
                    message='This package pins no HelixSR release.')
    results = [check_release(folder, pinned) for folder in candidates(pinned, home, explicit)]
    order = [lambda r: r['state'] == 'ready' and r['version'] == pinned['Version'], lambda r: r['state'] == 'ready',
             lambda r: r['state'] == 'unbuilt', lambda r: r['state'] == 'unknown']
    for test in order:
        match = next((r for r in results if test(r)), None)
        if match:
            return dict(match, pinned=pinned['Version'], checked=[r['folder'] for r in results])
    folder = str(Path(explicit)) if explicit is not None else None
    return dict(state='missing', folder=folder, dll=None, version=None, pinned=pinned['Version'],
                checked=[r['folder'] for r in results],
                message=('No HelixSR release in ' + folder + '.') if folder else 'HelixSR is not on this computer yet.')


def setup_command(folder):
    """The command that runs HelixSR's own setup in folder, building the upscaler only (no DLSS frame generation)."""
    return 'cd ' + shlex.quote(str(folder)) + ' && ./' + SETUP_SCRIPT + ' --no-fg'


def guidance(found):
    """What the user does next, for a find() result that is not ready."""
    credit = ('HelixSR is a separate project by ' + AUTHOR + ' (' + PROJECT + '), under its own licence (the HelixSR '
              'Freeware License). It runs NVIDIA\'s DLSS network; this project ships none of it.')
    state = found['state']
    if state == 'unbuilt':
        return '\n'.join([
            found['message'], credit, '',
            'Build it once with HelixSR\'s own setup, in a terminal:', '',
            '    ' + setup_command(found['folder']), '',
            'HelixSR\'s setup asks before it downloads NVIDIA\'s DLSS DLL (from NVIDIA\'s GitHub, under NVIDIA\'s licence)',
            'and builds the network on this computer; it may also offer to install Python\'s numpy and downloads Microsoft\'s',
            'shader compiler. --no-fg builds the upscaler only: frame generation here is XeFG\'s.',
            'When it then lists your games, press Ctrl+C at the first game question (or answer n for each): it changes',
            'no game until its last question. Do not press Enter there: Enter installs HelixSR its own way, and in a game',
            'set up by this installer that puts HelixSR Scaler in place of this installer\'s OptiScaler.',
            'Then choose HelixSR here again; this installer places HelixSR in the games you select.'])
    if state == 'unknown':
        return '\n'.join([found['message'], credit, '',
                          'Use the official HelixSR ' + str(found['pinned']) + ' release: install.py helixsr (without --helixsr) '
                          'or Setup downloads it; the folder above is not used.'])
    if state == 'unsupported':
        return found['message']
    return '\n'.join([found['message'], credit, '',
                      'install.py helixsr (or Setup) downloads the official HelixSR ' + str(found['pinned']) + ' release from ' +
                      PROJECT + '/releases, checked by SHA-256. A HelixSR you already extracted elsewhere: --helixsr FOLDER.'])


def _extract(archive, target, folder_name):
    """Unpack the release archive into target/folder_name as it is: regular files and folders only, every member below
    folder_name, executable bits as the archive has them (HelixSR's setup scripts), nothing outside target."""
    total = 0
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        for info in members:
            name = info.filename
            parts = Path(name).parts
            kind = (info.external_attr >> 16) & 0o170000
            if (name.startswith('/') or '\\' in name or '..' in parts or not parts or parts[0] != folder_name
                    or kind not in (0, 0o100000, 0o040000)):
                raise ValueError('Unexpected member in the HelixSR archive: ' + name)
            total += info.file_size
        if total > EXTRACT_LIMIT:
            raise ValueError('The HelixSR archive unpacks to more than expected')
        for info in members:
            dest = target.joinpath(*Path(info.filename).parts)
            if info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as source, open(dest, 'wb') as output:
                shutil.copyfileobj(source, output, 1 << 20)
            os.chmod(dest, 0o755 if (info.external_attr >> 16) & 0o100 else 0o644)


def download_release(package, download=None):
    """The official HelixSR release the package pins, downloaded (once) and unpacked into the download cache: returns
    check_release of that folder. download(item, cache) fetches and checks the archive (dependencies.download)."""
    pinned = pins(package)
    if pinned is None:
        raise ValueError('This package pins no HelixSR release')
    root = cache_root()
    folder = root / pinned['Folder']
    if folder.exists() or folder.is_symlink():
        found = check_release(folder, pinned)
        if found['state'] in ('ready', 'unbuilt'):
            return found
        raise ValueError(str(folder) + ' exists but does not hold the official HelixSR ' + pinned['Version'] +
                         '; remove that folder and run this again.')
    if download is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location('bc250_dependencies_helixsr', Path(__file__).resolve().parent / 'dependencies.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        download = module.download
    root.mkdir(parents=True, exist_ok=True)
    archive = Path(download(pinned['input'], root.parent))
    staging = Path(tempfile.mkdtemp(prefix='.helixsr-unpack-', dir=root))
    try:
        _extract(archive, staging, pinned['Folder'])
        found = check_release(staging / pinned['Folder'], pinned)
        if found['state'] != 'unbuilt':
            raise ValueError('The downloaded HelixSR archive does not hold the pinned DLL')
        os.replace(staging / pinned['Folder'], folder)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    # The archive matched its pin and is unpacked as it is: the unpacked release is the copy kept.
    archive.unlink(missing_ok=True)
    return check_release(folder, pinned)


def ini_bytes(existing=None):
    """helixsr.ini for a game: the installer's own when there is none, otherwise the same file with HelixSR's DLSS frame
    generation switched off (Restore puts the original bytes back)."""
    if existing is None:
        return INI_TEXT.encode('ascii')
    text = existing.decode('utf-8-sig')
    newline = '\r\n' if '\r\n' in text else '\n'
    lines = text.splitlines()
    section, out, done, header = '', [], False, None
    for line in lines:
        stripped = line.strip()
        # A section header, also with a comment after it ('[DlssFrameGeneration] ; DLSS FG').
        bare = stripped.split(';', 1)[0].split('#', 1)[0].strip()
        if bare.startswith('[') and bare.endswith(']'):
            if section == 'dlssframegeneration' and not done:
                out.append('Enabled = false')
                done = True
            section = bare[1:-1].strip().lower()
            if section == 'dlssframegeneration':
                header = True
            out.append(line)
            continue
        if section == 'dlssframegeneration' and not stripped.startswith((';', '#')) and '=' in stripped \
                and stripped.split('=', 1)[0].strip().lower() == 'enabled':
            if not done:
                out.append('Enabled = false')
                done = True
            continue
        out.append(line)
    if not done:  # no such section, or it is the last one and has no Enabled key
        if not header:
            out += ['', '[DlssFrameGeneration]']
        out.append('Enabled = false')
    return (newline.join(out) + newline).encode('utf-8')
