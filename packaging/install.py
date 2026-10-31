#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Local, reversible installation of the experimental BC250 game add-on."""
import argparse,collections,configparser,contextlib,fcntl,functools,hashlib,json,os,re,shutil,stat,struct,subprocess,sys,tempfile,time,uuid
from pathlib import Path

# This file imports its sibling modules by name (doctor, launcher_config, which imports steam_config and vendor). An
# isolated interpreter (python3 -I) does not put a script's own folder on sys.path, so put it there first.
if str(Path(__file__).resolve().parent) not in sys.path:sys.path.insert(0,str(Path(__file__).resolve().parent))
import helixsr
import freefg_library
import upscaler_updates
import launcher_migrations
import hlx

STATE='.bc250-xefg-experimental'
DLL='amd_fidelityfx_upscaler_dx12.dll'
# Packages whose add-on is a libxess_fg.dll proxy for Intel's unmodified XeFG runtime (manifest addon_entry; no XeSSMFG
# enabler, 2x only): the runtime goes beside the proxy as bc250_xefg_original.dll (dependencies.json runtime.ProxyPackage)
# and the proxy writes its logs beside it, in the game folder.
PROXY_ENTRY='libxess_fg-proxy'
PROXY_LOGS=['BC250-MFG.log','BC250-XeFG-fast.log']
# vkd3d-proton's shader cache for the installed game, a folder in the installation's state folder: new with each
# installation, named in the launch environment with vkd3d-proton's shader module identifiers off, so the layer sees every
# pipeline's shader on every start (launcher_config.IDENTIFIER_EXTENSION), and deleted by Restore.
VKD3D_CACHE='vkd3d-cache'
# NVIDIA's DLSS helper (DLSS Super Resolution, dependencies.json 'dlss'): placed beside the game executable only in a fresh
# OptiScaler setup on a DLSS input, and only when OptiScaler's own search finds no copy of the game's (dlss_helper_plan).
DLSS_HELPER='nvngx_dlss.dll'
# The DirectX 12 upscaler OptiScaler runs through its FidelityFX (FSR 3.1) interface, from the file at Libraries.FfxDx12SRPath
# (OptiScaler/amd_fidelityfx_upscaler_dx12.dll in a fresh setup): the BC-250 build of FSR 4 (default) or HelixSR, a separate
# project by lonewolf0622 that the user's own HelixSR setup built on this computer (helixsr.py). Frame generation is XeFG
# either way.
UPSCALERS={'fsr4':'FSR 4 (BC-250 build RC12)','helixsr':helixsr.LABEL,**hlx.NAMES}
# BC-250 builds of the FSR 4 DLL by SHA-256: the one dependencies.json pins (RC12, since 1.1.2) and the one earlier builds
# installed (RC11), so Status names the build a game has and records of earlier builds stay readable.
FSR4_BUILDS={'4b0df27761d7ced52c30dcbd1641c55bdcf4d2ae10d59f7e5b4b2f895b6bba79':'RC12',
             '8192ea97620f8e6407bff346bf905f0d555ff73d89fe14616eb1fa5e41ab3175':'RC11'}
CHANGES={('Upscalers','Dx12Upscaler'):'ffx',('FSR','UpscalerIndex'):'0',
         ('FSR','Fsr4ForceModel'):'2',('FSR','Fsr4EnableWatermark'):'auto',
         ('FrameGen','Enabled'):'false',('fakenvapi','UseFakenvapi'):'false'}

def digest(data):return hashlib.sha256(data).hexdigest()
def read_ini(data):
    text=data.decode('utf-8-sig');parser=configparser.ConfigParser(interpolation=None,strict=True)
    parser.read_string(text)
    # ConfigParser's section names are case-sensitive; OptiScaler's are not.
    if len({s.lower() for s in parser.sections()})!=len(parser.sections()):raise ValueError('Duplicate INI section')
    return {(s.lower(),k.lower()):v for s in parser.sections() for k,v in parser.items(s)}

def ini_names(data):
    """Original spelling of each (section, key), keyed like read_ini."""
    parser=configparser.ConfigParser(interpolation=None,strict=True);parser.optionxform=str
    parser.read_string(data.decode('utf-8-sig'))
    return {(s.lower(),k.lower()):(s,k) for s in parser.sections() for k in parser[s]}

def carry_settings(default,previous,skip=()):
    """The package's settings file with the user's earlier values for the keys it still has."""
    names=ini_names(default);known=read_ini(default)
    kept={names[key]:value for key,value in read_ini(previous).items() if key in known and key not in skip and value!=known[key]}
    return (patch_ini(default,kept) if kept else default),kept

def xess_library_repair(data):
    """Repair the saved path alias from the older OptiScaler config reader; keep real SR overrides."""
    value=read_ini(data).get(('libraries','xesspath'),'auto').strip().replace('\\','/')
    if value.rsplit('/',1)[-1].lower() in ['libxess_fg.dll','libxell.dll']:
        return {('Libraries','XeSSPath'):'auto'}
    return {}

# A key line: (indent)(key as written)(the '=' with the blanks around it); the value follows.
KEY_LINE=re.compile(r'(\s*)([^;#=]+?)(\s*=\s*)')

def patch_ini(data,changes):
    """data with changes ({(section, key): value, or None to remove the key}). A key already in the file keeps its own
    spelling and the blanks around its '=' (OptiScaler saves 'key = value', the installers wrote 'key=value'), so an
    edit and its undo touch only the value; a key added takes the spacing most of the file's keys have. A key line's
    indent goes, as it always did."""
    read_ini(data);bom=data.startswith(b'\xef\xbb\xbf');text=data.decode('utf-8-sig')
    newline='\r\n' if '\r\n' in text else '\n';lines=text.splitlines();section='';seen=set();result=[]
    pending={(s.lower(),k.lower()):(s,k,v) for (s,k),v in changes.items()}
    sections=set();spacing=collections.Counter()
    for line in lines:
        match=re.match(r'\s*\[([^]]+)\]\s*$',line)
        if match:section=match[1].lower();sections.add(section)
        key=KEY_LINE.match(line)
        rest=line[key.end():] if key else ''
        if key and rest.strip():spacing[key[3]]+=1
        entry=(section,key[2].lower()) if key else None
        if entry in pending:
            _,name,value=pending[entry];seen.add(entry)
            # Blanks after the old value stay too. An indent does not (as before): configparser reads an indented line
            # after a key as part of that key's value.
            if value is not None:result.append(key[2]+key[3]+value+(rest[len(rest.rstrip()):] if rest.strip() else ''))
        else:result.append(line)
    equals=spacing.most_common(1)[0][0] if spacing else '='
    for entry,(name,key,value) in pending.items():
        if entry in seen or value is None:continue
        # Insert into an existing section before its next header.
        header=next((i for i,line in enumerate(result) if re.fullmatch(r'\s*\['+re.escape(name)+r'\]\s*',line,re.I)),None)
        if header is None:result.extend(['','['+name+']',key+equals+value])
        else:
            end=next((i for i in range(header+1,len(result)) if re.match(r'\s*\[',result[i])),len(result))
            result.insert(end,key+equals+value)
    output=('\ufeff' if bom else '')+newline.join(result)+newline
    read_ini(output.encode());return output.encode()

def ini_content(data):
    """An INI's content without its layout: per non-blank line ('[', section) for a header, ('=', section, key,
    value) for a key and ('#', text) for anything else (comments), with section and key in lower case. Two files with
    the same content differ only in the blanks around '=', key and section case, blank lines, line endings, a
    byte-order mark and empty sections (a header with nothing under it holds no value: Restore leaves the headers an
    installation added once their keys are gone)."""
    section='';out=[]
    for line in data.decode('utf-8-sig').splitlines():
        if not line.strip():continue
        header=re.match(r'\s*\[([^]]+)\]\s*$',line)
        if header:
            if out and out[-1][0]=='[':out.pop()
            section=header[1].lower();out.append(('[',section));continue
        key=KEY_LINE.match(line)
        out.append(('=',section,key[2].lower(),line[key.end():].strip()) if key else ('#',line.strip()))
    if out and out[-1][0]=='[':out.pop()
    return out

def same_ini(first,second):
    try:return ini_content(first)==ini_content(second)
    except (UnicodeDecodeError,ValueError):return False

def safe(root,relative):
    rel=Path(relative)
    if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe relative path')
    current=root
    for part in rel.parts:
        current=current/part
        if current.is_symlink():raise ValueError(f'Symlink needs a manual installation: {current}')
    if current.exists() and not current.is_file():raise ValueError(f'Expected a file: {current}')
    return current

def write(path,data,mode=0o644):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.bc250-xefg-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(name,mode);os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def created_folders(root,paths):
    """The folders below root that writing paths (relative to root) creates, deepest first."""
    created=set()
    for relative in paths:
        folder=(root/relative).parent
        while folder!=root and not folder.exists():created.add(folder.relative_to(root).as_posix());folder=folder.parent
    return sorted(created,key=lambda name:(-name.count('/'),name))

def created_folder(root,relative):
    """A recorded folder of an installation inside root, reached without a symlink and still a folder, or None."""
    rel=Path(relative)
    if not relative or rel.is_absolute() or '..' in rel.parts:return None
    current=root
    for part in rel.parts:
        current=current/part
        if current.is_symlink():return None
    return current if current.is_dir() else None

class GameRunningError(ValueError):
    """The game's mapped binaries must be released before a file transaction starts."""

def idle(root):
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            maps=(proc/'maps').read_text(errors='replace')
            if str(root)+'/' in maps and re.search(r'(?i)\.(exe|dll)(?:\s|$)',maps):
                raise GameRunningError('Close the game before installing, updating or restoring')
        except (OSError,PermissionError):pass

def payload(package):
    """The package's own files by package path, each checked against its manifest, plus its shared copies."""
    manifest=json.loads((package/'manifest.json').read_text());files={}
    for name,expected in manifest['files'].items():
        path=safe(package,name);data=path.read_bytes()
        if digest(data)!=expected:raise ValueError('Package checksum mismatch: '+name)
        files[name]=data
    for target,source in manifest.get('payload_copies',{}).items():
        safe(package,target)
        if not target.startswith('payload/') or not source.startswith('payload/') or target in files or source not in manifest['files']:
            raise ValueError('Invalid shared payload entry')
        files[target]=files[source]
    return files

def setup_target(name):
    """Where a file of a fresh OptiScaler setup goes in the game folder: OptiScaler.dll becomes the dxgi.dll proxy and
    its licences go under OptiScaler/Licenses."""
    return 'dxgi.dll' if name=='OptiScaler.dll' else 'OptiScaler/'+name if name.startswith('Licenses/') else name

# The dependencies.py interface this installer calls (its FORMAT): prepare(package, groups) with the runtime group.
DEPENDENCIES_FORMAT=2

def check_pins(pins):
    """The package's dependency pins (dependencies.json): a fresh setup's files ('payload'), the Intel runtime and FSR4
    DLL every installation takes from their upstream downloads ('runtime', with 'Package': package path -> pinned file)
    and NVIDIA's DLSS helper with its licence ('dlss', placed only where a DLSS input needs it). Pins from an earlier
    build, or that contradict each other, are refused before anything is fetched or changed."""
    runtime=pins.get('runtime')
    if not isinstance(runtime,dict) or not isinstance(runtime.get('Package'),dict) or 'Files' not in pins.get('payload',{}):
        raise ValueError('install.py and dependencies.json come from different builds (no runtime downloads pinned); use one package’s files')
    dlss=pins.get('dlss')
    # Earlier builds pinned the helper in the fresh setup, which placed it in every fresh setup.
    if (not isinstance(dlss,dict) or not isinstance(dlss.get('Files'),dict) or DLSS_HELPER not in dlss['Files'] or DLSS_HELPER in pins['payload']['Files']
            or any(name!=DLSS_HELPER and not name.startswith('Licenses/') for name in dlss['Files'])):
        raise ValueError('install.py and dependencies.json come from different builds (no separate DLSS helper pins); use one package’s files')
    expected={}
    for group in ['payload','runtime','dlss']:
        for name,value in pins[group]['Files'].items():
            if expected.setdefault(name,value)!=value:raise ValueError('Conflicting dependency pins: '+name)
    for layout in ['Package','ProxyPackage']:
        if layout not in runtime:continue
        if not isinstance(runtime[layout],dict):raise ValueError('Invalid runtime download layout: '+layout)
        for name,source in runtime[layout].items():
            if source not in runtime['Files'] or not (name=='fsr4/'+DLL or name.startswith('payload/')):raise ValueError('Invalid runtime download entry: '+name)
        if 'fsr4/'+DLL not in runtime[layout]:raise ValueError('Invalid runtime download entry: fsr4/'+DLL)
    return pins

def prepare_dependencies(package,groups):
    """Directory with the pinned upstream files of groups, downloaded once into the user's cache (dependencies.py)."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('bc250_dependencies',Path(__file__).resolve().parent/'dependencies.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if getattr(module,'FORMAT',None)!=DEPENDENCIES_FORMAT:
        # An earlier build's dependencies.py (prepare(package), no runtime group) beside this installer.
        raise ValueError('install.py and dependencies.py come from different builds; use one package’s files')
    return module.prepare(package,groups)

class Upstream:
    """A pinned upstream file not fetched yet: its name and SHA-256 in dependencies.json. install() holds these while it
    checks the game and fetches the bytes only after every check has passed (a preview too)."""
    def __init__(self,name,sha256):self.name,self.sha256=name,sha256

def pinned(package,pins,groups,dependency_dir=None,fetch=True):
    """{name: bytes} of every file of groups in dependencies.json, each checked against its pin. They come from
    dependency_dir when it holds them all with their pinned bytes (a caller that prepared them), otherwise from
    prepare_dependencies, which fetches what is missing or different (a caller's directory from an earlier pin, or one
    prepared for other groups, is not refused for that). Without fetch nothing is read or downloaded: each name maps to
    its Upstream."""
    expected={}
    for group in groups:
        for name,value in pins[group]['Files'].items():
            if expected.setdefault(name,value)!=value:raise ValueError('Conflicting dependency pins: '+name)
    if not fetch:return {name:Upstream(name,value) for name,value in expected.items()}
    def read(directory,strict):
        found={}
        for name,value in expected.items():
            try:
                path=safe(Path(directory),name);data=path.read_bytes() if path.is_file() else None
            except (OSError,ValueError):
                if strict:raise
                return None
            if data is None or digest(data)!=value:
                if strict:raise ValueError(('Dependency missing: ' if data is None else 'Dependency checksum mismatch: ')+name)
                return None
            found[name]=data
        return found
    found=read(dependency_dir,False) if dependency_dir is not None else None
    return found if found is not None else read(prepare_dependencies(package,groups),True)

def check_exe(exe):
    with exe.open('rb') as stream:
        header=stream.read(64)
        if len(header)!=64 or header[:2]!=b'MZ':raise ValueError('Choose a 64-bit Windows game executable')
        stream.seek(struct.unpack_from('<I',header,60)[0]);pe=stream.read(26)
        if len(pe)!=26 or pe[:6]!=b'PE\0\0d\x86' or struct.unpack_from('<H',pe,24)[0]!=0x20b or struct.unpack_from('<H',pe,22)[0]&0x2000:
            raise ValueError('Choose the 64-bit game executable, not a DLL or launcher shortcut')

def relative_library(root,parsed,key,default):
    value=parsed.get(('libraries',key),'auto')
    relative=default if value.lower() in ['', 'auto'] else value.replace('\\','/')
    if ':' in relative:raise ValueError('Shared/absolute DLL paths need the manual route')
    # Check directory components before testing whether this is a directory.
    safe(root,relative+'/.bc250-path-check')
    if (root/relative).is_dir():relative+='/'+DLL
    safe(root,relative)
    return relative

def locked(function):
    @functools.wraps(function)
    def call(*args,**kwargs):
        exe=kwargs.get('exe',args[1] if function.__name__=='install' else args[0])
        descriptor=os.open(exe.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:
            try:fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('Another installer is working on this game')
            return function(*args,**kwargs)
        finally:os.close(descriptor)
    return call

def launcher_locked(function):
    @functools.wraps(function)
    def call(exe,*args,**kwargs):
        path=safe(exe.parent.resolve(),STATE+'/state.json')
        record=json.loads(path.read_text()) if path.is_file() else {}
        with launcher_migrations.locked(record.get('launchers') or []):
            return function(exe,*args,**kwargs)
    return call

# Automatic input: the game's own XeSS FG when it ships it beside the executable (measured best on this runtime, and
# OptiScaler's frame-generation hooks stay out of it); otherwise OptiScaler's upscaler input, which needs no in-game
# frame-generation toggle and no GPU spoofing. Other inputs the game appears to ship are reported, not chosen: DLSS FG
# needs OptiScaler's NVIDIA spoofing and the game's DLSS FG setting, and FSR 3.1's amd_fidelityfx_dx12.dll also ships in
# upscaler-only games. Folders created by installers are ignored (OptiScaler brings its own FidelityFX DLLs).
IGNORED_DIRS={'optiscaler','.bc250-xefg-experimental','bc250-xefg','xessmfg'}
FG_SIGNS=[('dlssg',{'sl.dlss_g.dll','nvngx_dlssg.dll'},'DLSS FG'),
          ('fsrfg',{'amd_fidelityfx_framegeneration_dx12.dll','amd_fidelityfx_dx12.dll'},'FSR 3.1 (FG possible)'),
          ('fsrfg30',{'ffx_frameinterpolation_x64.dll','ffx_fsr3_x64.dll'},'FSR 3.0 FG')]
def game_root(exe,platform_dirs=False):
    """The game's own folder above its executable. platform_dirs also climbs out of the GDK and KCD2 executable folders
    that OptiScaler's own search knows (WinGDK, Win64MasterMasterSteamPGO; dlss_copies)."""
    names={'win64','x64','binaries','bin','bin64'}|({'wingdk','win64mastermastersteampgo'} if platform_dirs else set())
    root=exe.parent;climbed_binaries=False
    while root.name.lower() in names and root.parent!=root:
        climbed_binaries|=root.name.lower()=='binaries';root=root.parent
    # Unreal: <Game>/<Project>/Binaries/Win64 — the game root holds Engine/ beside the project. A folder laid out as
    # <Game>/Binaries/Win64 is itself the game root (climbing further would reach steamapps/common).
    return root.parent if climbed_binaries and root.parent!=root and (root.parent/'Engine').is_dir() else root
def game_files(exe,limit=50000):
    """{lower-case file name: first path found} of the game's files (from game_root), without the folders installers
    create (OptiScaler's, this installer's state and its archived states)."""
    found={};seen=0
    for dirpath,dirnames,filenames in os.walk(game_root(exe)):
        dirnames[:]=[d for d in dirnames if d.lower() not in IGNORED_DIRS and not d.lower().startswith(STATE)]
        for name in filenames:found.setdefault(name.lower(),os.path.join(dirpath,name))
        seen+=len(filenames)
        if seen>limit:break
    return found
def detect_input(exe,limit=50000):
    """(route, fg_input, description) for --route auto/--fg-input auto, the description naming other inputs found."""
    found=game_files(exe,limit)
    others=[label for fg_input,names,label in FG_SIGNS if names&found.keys()]
    also=('; the game also ships '+', '.join(others)+' (choose that input explicitly to use it)') if others else ''
    if (exe.parent/'libxess_fg.dll').is_file() and not (exe.parent/'XeSSMFG').exists():
        return 'native','upscaler','native XeSS FG (libxess_fg.dll beside the executable)'+also
    return 'opti','upscaler','OptiFG (OptiScaler generates from the upscaler input)'+also
# OptiScaler's search for nvngx_dlss.dll (Util::FindFilePath of the shipped fork 2c103878, as upstream), the NVIDIA-signed
# file its DXGI and Streamline GPU spoofing needs (State::nvngxReplacement, set in Config::CheckUpscalerFiles). It starts
# in its own folder, here the executable's (dxgi.dll beside it): (1) that folder, in any case (Wine opens files so);
# (2) breadth-first below it, by exact name (skipping OptiScaler/streamline, inside OptiScaler's own folder, which this
# installer's walk skips as a whole); (3) only when the folder above it holds Win64, WinGDK or Win64MasterMasterSteamPGO
# (the first of these found), breadth-first below an engine root (optiscaler_fallback_root), by exact name. Nothing else
# is searched: a copy in a sibling folder of the executable's (Game/sl beside Game/bin/x64) stays unseen.
OPTI_FALLBACK=['Win64','WinGDK','Win64MasterMasterSteamPGO']
def has_dir(folder,name):
    """folder holds a folder called name, in any case (as Wine finds it)."""
    try:
        with os.scandir(folder) as entries:return any(e.name.lower()==name.lower() and e.is_dir() for e in entries)
    except OSError:return False
def optiscaler_fallback_root(exe):
    """Step (3)'s engine root, or None: for Win64/WinGDK the folder two levels above the executable's, or its parent when
    it holds Binaries, otherwise the next one up, or its parent when that holds Binaries (an older Unreal layout,
    <Game>/Binaries/Win64, reaches the library folder that holds the game); for Win64MasterMasterSteamPGO (KCD2) the
    folder two levels above the executable's."""
    above=exe.parent.parent
    for name in OPTI_FALLBACK:
        if not has_dir(above,name):continue
        root=above.parent
        if name=='Win64MasterMasterSteamPGO':return root
        if has_dir(root,'Binaries'):return root.parent
        root=root.parent
        return root.parent if has_dir(root,'Binaries') else root
    return None
def dlss_copies(exe,limit=50000):
    """The game's own nvngx_dlss.dll copies as OptiScaler's search meets them: dict(found, other, complete), paths relative
    to the executable's folder. found is the copy OptiScaler takes, or None; other is a copy in the game folder that its
    search does not reach (in a sibling folder of the executable's, or named in another case below it), or None;
    complete is False when the walk stopped after limit files. The executable's folder is checked first, so no limit
    hides a copy there. The walk stays in the game folder (game_root, also above GDK/KCD2 executable folders) even where
    OptiScaler's engine root lies above it; folders installers create are not the game's (game_files)."""
    start=exe.parent;relative=lambda path:os.path.relpath(path,start)
    try:
        with os.scandir(start) as entries:direct=sorted(e.path for e in entries if e.name.lower()==DLSS_HELPER and e.is_file())
    except OSError:direct=[]
    if direct:return dict(found=relative(direct[0]),other=None,complete=True)
    fallback=optiscaler_fallback_root(exe);tree=game_root(exe,platform_dirs=True)
    def under(path,folder):
        try:Path(path).relative_to(folder);return True
        except ValueError:return False
    def reached(path):
        return Path(path).name==DLSS_HELPER and (under(path,start) or (fallback is not None and under(path,fallback)))
    # Breadth-first, as OptiScaler: below the executable's folder first, then the rest of the game folder.
    copies=[];seen=0;complete=True
    for top,skip in [(start,None),(tree,start)]:
        queue=collections.deque([top] if top!=skip else [])
        while queue and complete:
            folder=queue.popleft()
            try:
                with os.scandir(folder) as iterator:entries=sorted(iterator,key=lambda e:e.name)
            except OSError:continue
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    name=entry.name.lower()
                    if name not in IGNORED_DIRS and not name.startswith(STATE) and entry.path!=str(skip):queue.append(entry.path)
                    continue
                seen+=1
                if seen>limit:complete=False;break
                if entry.name.lower()==DLSS_HELPER and entry.is_file():copies.append(entry.path)
    found=[p for p in copies if reached(p)];other=[p for p in copies if not reached(p)]
    return dict(found=relative(found[0]) if found else None,other=relative(other[0]) if other else None,complete=complete)
def dlss_helper_plan(exe,route,fg_input,ini,choice='auto'):
    """Whether a fresh OptiScaler setup gets NVIDIA's DLSS helper beside the executable: dict(placed, reason, game_copy,
    game_copy_found, searched_all, dlss_input, dxgi_spoofing). A copy of the game's own that OptiScaler's search finds
    (dlss_copies) is used as it is: no helper, whatever the input or choice. Otherwise the helper is placed for a DLSS
    input: DLSS FG input on the OptiScaler route or OptiScaler's DLSS inputs set to true (Inputs.EnableDlssInputs, from a
    recipe or the INI), or for choice 'yes'; choice 'no' never places it. A copy the search does not reach stays where the
    game put it (the helper goes beside the executable, never over a game file), and so does every copy when the walk
    stopped at its file limit. OptiFG from an FSR or XeSS upscaler input needs no NVIDIA file.
    GPU spoofing: with neither a helper nor a copy OptiScaler finds, Spoofing.Dxgi=auto (the fresh setup's default)
    turns OptiScaler's DXGI spoofing off at start-up (dllmain: "nvngx.dll not found! - disabling spoofing"), so the game
    sees the AMD GPU, not an NVIDIA one; that can change which upscalers and Reflex options a game offers, and
    fakenvapi.ForceReflex and XeLL frame-start pacing need Reflex calls, which some games make only on NVIDIA. This is upstream
    OptiScaler's own default in a game without DLSS. Tester v30 placed the helper in every fresh setup, which kept DXGI
    spoofing on; --dlss-helper yes still does. dxgi_spoofing is 'off' in that case (a recipe or INI value of
    Spoofing.Dxgi, or nvngx.dll/_nvngx.dll beside the executable, leaves it alone), otherwise None. Not yet measured in a
    game without DLSS and without a recipe."""
    copies=dlss_copies(exe);found=copies['found']
    base=dict(game_copy=found or copies['other'],game_copy_found=bool(found),searched_all=copies['complete'])
    dlss_input=(route=='opti' and fg_input=='dlssg') or ini.get(('inputs','enabledlssinputs'),'auto').strip().lower()=='true'
    if found:return dict(base,placed=False,reason='OptiScaler finds the game’s own nvngx_dlss.dll',dlss_input=dlss_input,dxgi_spoofing=None)
    if choice=='no':placed,reason=False,'not requested (--dlss-helper no)'
    elif choice=='yes':placed,reason=True,'requested (--dlss-helper yes)'
    elif choice=='detected':placed,reason=True,'DLSS is the game’s only upscaler and it ships no copy (detection)'
    elif route=='opti' and fg_input=='dlssg':placed,reason=True,'DLSS FG input'
    elif dlss_input:placed,reason=True,'OptiScaler’s DLSS inputs are on (Inputs.EnableDlssInputs=true)'
    else:placed,reason=False,'not a DLSS input'
    try:
        with os.scandir(exe.parent) as entries:nvngx=any(e.name.lower() in ['nvngx.dll','_nvngx.dll'] for e in entries)
    except OSError:nvngx=False
    spoofing='off' if not placed and not nvngx and ini.get(('spoofing','dxgi'),'auto').strip().lower() in ['','auto'] else None
    return dict(base,placed=placed,reason=reason,dlss_input=dlss_input,dxgi_spoofing=spoofing)
def helper_line(helper):
    """One line about the DLSS helper decision (dlss_helper_plan; records of earlier builds lack the later keys)."""
    copy=helper.get('game_copy');reached=helper.get('game_copy_found',bool(copy) and not helper['placed'])
    outside='the game’s own copy ('+str(copy)+') is outside the folders OptiScaler searches and stays where it is'
    if helper['placed']:
        detail=outside if copy else 'the game ships none' if helper.get('searched_all',True) else 'none found in the first 50,000 files of the game folder'
        return 'DLSS helper: NVIDIA’s nvngx_dlss.dll beside the game executable ('+helper['reason']+'; '+detail+').'
    if copy and reached:return 'DLSS helper: none needed; OptiScaler finds the game’s own nvngx_dlss.dll ('+copy+').'
    line='DLSS helper: none placed ('+helper['reason']+')'+('; '+outside if copy else '')+'.'
    if helper.get('dlss_input'):line+=' Without a copy OptiScaler finds, the game’s DLSS input may not work.'
    if helper.get('dxgi_spoofing')=='off':
        line+=(' GPU spoofing: OptiScaler finds no nvngx_dlss.dll, so with Spoofing.Dxgi=auto it shows the game the AMD GPU, not '
               'an NVIDIA one (OptiScaler’s own default in a game without DLSS); --dlss-helper yes places the helper and keeps '
               'NVIDIA spoofing on.')
    return line
def upscaler_line(upscaler,dll=None):
    """One line naming a game's upscaler (records of earlier builds have none: FSR 4); dll, the SHA-256 of the FSR 4 DLL
    placed, names its build."""
    if (upscaler or {}).get('name') in hlx.NAMES:return 'Upscaler: '+hlx.NAMES[upscaler['name']]+' '+str(upscaler.get('version'))+'; frame generation: FreeFG/XeFG.'
    if (upscaler or {}).get('name')!='helixsr':return 'Upscaler: FSR 4 (BC-250 build'+(' '+FSR4_BUILDS[dll] if dll in FSR4_BUILDS else '')+').'
    return ('Upscaler: HelixSR '+str(upscaler.get('version'))+', a separate project by '+helixsr.AUTHOR+' ('+helixsr.PROJECT+') under its '
            'own licence, running NVIDIA’s DLSS network; built on this computer by HelixSR’s own setup. In the game, choose the '
            'upscaler as for FSR 4. Frame generation stays XeFG (HelixSR’s own frame generation is off in '+upscaler['ini']+').')

def log_path(root,relative):
    """A log's path in the game folder, or None when it (or a folder above it) is a symlink or not a file: such a log is
    left alone, never followed or moved."""
    try:return safe(root,relative)
    except ValueError:return None

def put_back_helixsr_log(root,state,upscaler,notes):
    """HelixSR's log out of the game, kept with the backups; an earlier one that was set aside goes back. Returns notes."""
    log=log_path(root,upscaler['log']);held=state/'displaced-logs'/helixsr.LOG
    if log is None:
        notes.append('Left '+upscaler['log']+' as it is: a symlink or folder by that name'+(' (the earlier log stays in '+str(held)+')' if held.is_file() else '')+'.')
        return notes
    # Every helixsr.log there is this installation's, except an earlier one an interrupted installation never set aside.
    if log.is_file() and not log.is_symlink() and not (upscaler.get('displaced_log') and not held.is_file()):
        folder=state/('runtime-logs-'+uuid.uuid4().hex[:12]);folder.mkdir();os.replace(log,folder/helixsr.LOG)
    if upscaler.get('displaced_log') and held.is_file():
        if log.exists() or log.is_symlink():notes.append('Left the earlier '+upscaler['log']+' in '+str(held)+': the game folder has another one.')
        else:os.replace(held,log)
        with contextlib.suppress(OSError):held.parent.rmdir()
    return notes

def recipes_module():
    import importlib.util
    spec=importlib.util.spec_from_file_location('bc250_recipes',Path(__file__).resolve().parent/'recipes.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def recipe_for(package,exe,launcher_home=None):
    """(recipes module, verified recipe, wiki entries, leave-auto list, backports, launcher records) for a game; None
    when the package has no recipe file."""
    if not (package/'recipes/recipes.json').is_file():return None
    rm=recipes_module();data=rm.load(package/'recipes/recipes.json')
    try:
        import launcher_config
        found=launcher_config.discover(exe,launcher_home)
    except Exception:found=[]
    verified,wiki,leave,backports=rm.match(data,rm.identity(exe,found,launcher_home))
    return rm,verified,wiki,leave,backports,found

def settings_record(item):
    """The installation record of one planned recipe game setting (recipes.settings_plan). originals marks records
    that Restore can revert key by key; v26 records lack it."""
    entry,before,after=item['entry'],item['before'],item['after']
    record=dict(file=item['file'],path=str(item['path']) if item['path'] else None,format=entry['format'],section=entry.get('section'),values=entry['values'],
                status='pending' if after is None else 'applied' if after!=before or item['carried'] else 'unchanged',
                before=digest(before) if before is not None else None,after=digest(after) if after is not None else None)
    if after is not None:record.update(originals=item['originals'],carried=item['carried'],created_section=item['created_section'])
    else:
        if item.get('previous'):record['previous']=item['previous']
        if item.get('reason'):record['reason']=item['reason']
    return record

def setting_line(item):
    return item['file']+' '+', '.join(f'{k}={v}' for k,v in item['values'].items())

def write_setting(path,before,after):
    """Write a game settings file only if it still holds the bytes the plan was made from."""
    if path.is_symlink():raise ValueError('Game settings file is a symlink: '+str(path))
    current=path.read_bytes() if path.exists() else None
    if current!=before:raise ValueError('Game settings file changed during installation: '+str(path))
    write(path,after,stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644)

def apply_pending_settings(exe,root,record,launcher_home=None):
    """Apply recipe game settings that were waiting for the game to create its settings file (or the recipe's keys in
    it): (items applied or found already set, messages about the ones still waiting). A game's file never makes this
    fail: configure must keep working whatever the game wrote."""
    pending=[(i,item) for i,item in enumerate(record.get('game_settings',[])) if item['status']=='pending' and item.get('active',True)]
    if not pending:return [],[]
    rm=recipes_module();done=[];waiting=[];state=root/STATE
    try:user=rm.prefix_user(exe,record.get('launchers') or [],launcher_home)
    except (OSError,ValueError):user=None
    for i,item in pending:
        path=Path(item['path']) if item['path'] else (user/item['file'] if user else None)
        if not path or not path.is_file():
            waiting.append(setting_line(item)+(' (not created yet: start the game once, then Settings)' if path else ' (no Proton prefix yet: start the game once, then Settings)'));continue
        try:
            if path.is_symlink():raise rm.Unreadable('the file is a symlink')
            before=path.read_bytes();plan=rm.change(before,item['format'],item.get('section'),item['values'],item.get('previous'))
        except (OSError,ValueError) as error:
            waiting.append(setting_line(item)+' (cannot read it: '+str(error)+'; not changed)');continue
        if plan['after'] is None:waiting.append(setting_line(item)+' ('+plan['reason']+')');continue
        after=plan['after'];saved=dict(item)
        item.update(status='applied' if after!=before or plan['carried'] else 'unchanged',path=str(path),before=digest(before),after=digest(after),
                    originals=plan['originals'],carried=plan['carried'],created_section=plan['created_section'])
        item.pop('reason',None);item.pop('previous',None)
        try:
            # Backup and record first: an interrupted write leaves a file Restore recognizes as the original.
            if after!=before:write(state/'game-settings'/str(i),before)
            write(state/'state.json',(json.dumps(record,indent=2)+'\n').encode())
            if after!=before:write_setting(path,before,after)
        except (OSError,ValueError) as error:
            item.clear();item.update(saved);waiting.append(setting_line(item)+' (not written: '+str(error)+')')
            try:write(state/'state.json',(json.dumps(record,indent=2)+'\n').encode())
            except OSError:pass
            continue
        done.append(item)
    return done,waiting

def left_message(item,left,why=None):
    names={'changed':'changed since installation; kept','missing':'no longer in the file','kept':'still the recipe value; its original could not be written back'}
    return 'Left '+item['file']+' '+', '.join(f'{k}={item["values"][k]} ({names[w]})' for k,w in left.items())+(' ('+why+')' if why else '')

def plan_restore_settings(root,record):
    """Check and plan putting recipe-edited game settings back, before Restore changes anything: ([(path, the bytes it was
    planned from, bytes or None to delete, mode)], messages). A file still as installed gets its backup back byte for
    byte. A file the game rewrote since is reverted key by key: a key still holding the recipe's value gets its original
    back, one set to something else is the user's and stays (reported). Entries are undone newest first and chained per
    file, so two entries on one file both come back. A game's file never makes this fail: what cannot be read or put
    back is left and reported. Item statuses become restored or left (with the keys)."""
    rm=None;messages=[];files={}
    applied=[(i,item) for i,item in enumerate(record.get('game_settings',[])) if item['status']=='applied']
    for i,item in reversed(applied):
        path=Path(item['path']);values=item['values'];new='originals' in item
        def leave(why,how='kept'):
            item.update(status='left',left={k:how for k in values});messages.append(left_message(item,item['left'],why))
        backup=root/STATE/'game-settings'/str(i);original=None
        try:
            if item['before'] is not None and backup.is_file():
                original=backup.read_bytes()
                if digest(original)!=item['before']:original=None
        except OSError:original=None
        if path.is_symlink():leave('the file is now a symlink');continue
        if path not in files:
            try:
                current=path.read_bytes() if path.is_file() else None
                files[path]=[current,current,stat.S_IMODE(path.stat().st_mode) if current is not None else None]
            except OSError as error:leave('cannot read it: '+str(error));continue
        current=files[path][1]
        now=digest(current) if current is not None else None
        if current is None:
            if item['before'] is None:item['status']='restored'
            else:item.update(status='left',left={k:'missing' for k in values});messages.append('Left '+item['file']+': the game removed it since installation.')
            continue
        # Carried originals come from an earlier installation: this one's backup and digests do not hold them.
        if not item.get('carried'):
            if now==item['before']:item['status']='restored';continue
            if now==item['after']:
                if item['before'] is None:files[path][1]=None;item['status']='restored';continue # created by the recipe, untouched
                if original is not None:files[path][1]=original;item['status']='restored';continue
                if not new:leave('its backup is missing or damaged; set these back by hand');continue
        rm=rm or recipes_module()
        originals=item.get('originals')
        if originals is None and original is not None:
            # v26 records: the backed-up file holds the originals.
            try:originals=rm.change(original,item['format'],item.get('section'),values)['originals']
            except ValueError:originals=None
        if originals is None:
            item.update(status='left',left={k:'kept' for k in values})
            messages.append('Left '+item['file']+' as it is (changed since installation); the recipe set '+', '.join(f'{k}={v}' for k,v in values.items()));continue
        try:data,left=rm.revert(current,item['format'],item.get('section'),values,originals,item.get('created_section'))
        except ValueError as error:
            data,left=current,{k:'kept' for k in values};messages.append(left_message(item,left,'cannot read it: '+str(error)))
        else:
            if left:messages.append(left_message(item,left))
        files[path][1]=data
        item['status']='left' if left else 'restored'
        if left:item['left']=left
    return [(path,start,data,mode) for path,(start,data,mode) in files.items() if data!=start],messages

def write_restored_settings(writes):
    """Write the planned settings back, each only if its file still holds the bytes it was planned from (the game may be
    writing it); returns messages for the ones left."""
    messages=[]
    for path,start,data,mode in writes:
        try:
            if (path.read_bytes() if path.is_file() else None)!=start:messages.append('Left '+str(path)+': it changed while Restore ran; check it by hand');continue
            if data is None:path.unlink(missing_ok=True)
            else:write(path,data,mode)
        except OSError as error:messages.append('Left '+str(path)+': '+str(error))
    return messages

def restore_settings(root,record):
    """Put recipe-edited game settings back (plan_restore_settings, then write); returns the messages."""
    writes,messages=plan_restore_settings(root,record);return messages+write_restored_settings(writes)

def previous_settings(state,record,rm):
    """Recipe values an earlier installation's Restore left in place, with their true originals: {(file, format,
    section): {key: dict(recipe=value, original=...)}}. A v26 Restore left a whole file the game had rewritten (its
    backup holds the originals); later ones leave only keys they could not write back; a setting that was still
    pending carries what it had carried. A reinstall then records these originals instead of the recipe's own values."""
    out={}
    for i,item in enumerate(record.get('game_settings') or []):
        slot=out.setdefault((item['file'],item['format'],item.get('section')),{})
        if item.get('status')=='pending':slot.update(item.get('previous') or {});continue
        if item.get('status')=='applied':keys=list(item['values'])
        elif item.get('status')=='left':keys=[k for k,why in item.get('left',{}).items() if why=='kept']
        else:continue
        originals=item.get('originals')
        if originals is None:
            try:
                data=safe(state,'game-settings/'+str(i)).read_bytes()
                if digest(data)!=item.get('before'):continue
                originals=rm.change(data,item['format'],item.get('section'),item['values'])['originals']
            except (OSError,ValueError):continue
        slot.update({k:dict(recipe=item['values'][k],original=originals[k]) for k in keys if k in originals})
    return {slot:keys for slot,keys in out.items() if keys}

def preconditions(package,exe,recipe=None):
    """What in the game folder makes install() refuse before it changes anything, as compatibility refusals (code, kind
    'hard', text, way) for Check and Setup: an installation not restored, a folder path that is not ASCII, another
    mod's version.dll or XeSSMFG folder, the files of a fresh OptiScaler setup already there, an OptiScaler setup this
    package does not take over, HelixSR's own installation where the upscaler DLL goes, a verified game's other
    executable. Reads only (no hashes of package files, no network);
    install() keeps its own checks of the same conditions, which test_compat_install compares with these."""
    out=[];root=exe.parent.resolve()
    def add(code,text,way):out.append(dict(code=code,kind='hard',text=text,way=way))
    def helixsr_installed(target):
        # install(): HelixSR's own installer keeps its record beside a drop-in it placed where the upscaler DLL goes.
        if (root/Path(target).parent/helixsr.HELIXSR_MARKER).exists():
            add('helixsr-installer','HelixSR’s own installer placed HelixSR beside '+target+' ('+helixsr.HELIXSR_MARKER+').',
                'Remove it with HelixSR’s uninstaller or HelixSR Desktop first; then choose HelixSR in Setup instead.')
    expected=((recipe[1] or {}).get('match',{}).get('exe') or []) if recipe else []
    if expected and exe.name.lower() not in expected:
        add('recipe-exe','For '+recipe[1]['title']+' choose the game’s own executable ('+' or '.join(expected)+'), not '+exe.name+'.','Choose that executable.')
    if not str(root).isascii():add('ascii-path','This build’s shader loader needs an ASCII-only game folder path.','Move the game to a library whose path is ASCII only.')
    state=root/STATE
    if state.is_symlink():add('installed','The installation state folder is a symlink.','Remove it, then Check again.')
    elif state.exists():
        try:status=json.loads(safe(root,STATE+'/state.json').read_text()).get('status')
        except (OSError,ValueError,AttributeError):status=None
        if status!='restored':
            # The rest of the folder (OptiScaler, an enabler) is that installation's until its Restore: nothing more to say.
            add('installed','An installation record already exists in this game folder.','Restore it first (Setup: Restore), then Install again.');return out
    try:
        manifest=json.loads((package/'manifest.json').read_text())
        pins=json.loads(safe(package,'dependencies.json').read_bytes()) if (package/'dependencies.json').is_file() else None
        custom=safe(package,'opti/OptiScaler.dll').read_bytes() if (package/'opti/OptiScaler.dll').is_file() else None
    except (OSError,ValueError):return out
    proxy=manifest.get('addon_entry')==PROXY_ENTRY
    if not proxy and (root/'version.dll').exists():add('version-dll','version.dll is occupied by another mod (this package loads its enabler as version.dll).','Restore or remove that mod first.')
    if (root/'XeSSMFG').exists():add('xessmfg','An existing XeSSMFG folder (another frame-generation mod) is in the game folder.','Remove or restore that mod first.')
    if not pins or 'Files' not in pins.get('payload',{}):return out
    if not (root/'OptiScaler.ini').exists():
        taken=[setup_target(n) for n in pins['payload']['Files'] if (setup_target(n)=='dxgi.dll' or setup_target(n).startswith('OptiScaler/')) and (root/setup_target(n)).exists()]
        if taken:add('existing-files','Existing file needs manual mod chaining: '+taken[0]+' (another mod, or an OptiScaler setup without its OptiScaler.ini).','Remove or restore it first.')
        else:helixsr_installed('OptiScaler/'+DLL)
        return out
    accepted={pins['payload'].get('ProxyHash'),*pins['payload'].get('CompatibleProxyHashes',[])}
    if custom is not None:accepted.add(digest(custom))
    proxies=[name+'.dll' for name in ['dxgi','winmm','d3d12','wininet','version','winhttp','dbghelp','OptiScaler']]+['OptiScaler.asi']
    # A setup linked in from outside the game folder (a shared payload): install() reads it through safe(), which
    # refuses symlinks, whatever build it is.
    linked=[n for n in proxies+['OptiScaler'] if (root/n).is_symlink()]
    if linked:
        add('existing-optiscaler','Existing OptiScaler here is linked from outside the game folder ('+', '.join(linked)+(' is a symlink' if len(linked)==1 else ' are symlinks')+'); a symlink needs a manual installation.',
            'Restore or remove that OptiScaler setup first (with the tool that linked it).')
        return out
    try:found=[n for n in proxies if (root/n).is_file() and digest((root/n).read_bytes()) in accepted]
    except OSError:found=[]
    if not found:
        add('existing-optiscaler','Existing OptiScaler in the game folder is another build than the ones this package installs over (its OptiScaler.ini is there, a matching proxy DLL is not).',
            'Restore or remove that OptiScaler setup first (OptiScaler.ini, its proxy DLL and the OptiScaler folder).')
        return out
    try:parsed=read_ini(safe(root,'OptiScaler.ini').read_bytes())
    except (OSError,ValueError,UnicodeDecodeError,configparser.Error):
        add('existing-optiscaler','Existing OptiScaler.ini in the game folder cannot be read.','Fix or remove it first.');return out
    if any(section=='libraries' and key in ['ffxdx12path','xefgpath','xellpath'] and value.lower() not in ['','auto'] for (section,key),value in parsed.items()):
        add('optiscaler-paths','OptiScaler here uses a custom DLL path.','Use its normal local DLL layout first (those paths back to auto in OptiScaler.ini).')
        return out
    # install(): the existing setup's FSR4 DLL (OptiScaler's folder, or beside the executable) must be where it says.
    opti=parsed.get(('libraries','optidllpath'),'auto')
    default=('OptiScaler' if opti.lower() in ['','auto'] else opti.replace('\\','/'))+'/'+DLL
    if opti.lower() in ['','auto'] and not (root/default).is_file() and (root/DLL).is_file():default=DLL
    try:
        target=relative_library(root,parsed,'ffxdx12srpath',default)
        if not (root/target).is_file():raise ValueError
    except ValueError:add('optiscaler-paths','Cannot find OptiScaler’s configured local FSR4 DLL.','Repair or remove that OptiScaler setup first.');return out
    helixsr_installed(target)
    return out

def compat_verdict(package,exe,route=None,fg_input=None,launcher_home=None,accept=(),accept_risk=()):
    """(verdict, scan, recipe data, identity) of exe from compat.py (packaging/compat.py, gamescan.py): read only, no
    network. route/fg_input are the user's explicit choice, None for Automatic. accept: soft refusal codes accepted;
    accept_risk: the anti-cheat override, confirmed for this game (confirm_anticheat_risk). None when the package lacks
    the modules or the scan fails unexpectedly (the install then goes on as 0.9.0 did, and says so)."""
    here=Path(__file__).resolve().parent
    if not all((here/name).is_file() for name in ['compat.py','gamescan.py','recipes.py']):return None
    try:
        import compat,gamescan,launcher_config
    except ImportError:
        return None
    try:
        rm=recipes_module()
        data=rm.load(package/'recipes/recipes.json') if (package/'recipes/recipes.json').is_file() else None
        try:launchers=launcher_config.discover(exe,launcher_home)
        except Exception:launchers=[]  # noqa: BLE001 - discover reports unreadable files itself
        ids=rm.identity(exe,launchers,launcher_home)
        # One matcher for verified recipes: the one the installer applies them with (recipe_for, recipes.match).
        recipe=recipe_for(package,exe,launcher_home)
        scan=gamescan.scan_exe(exe,Path(launcher_home) if launcher_home else Path.home())
        conflicts=launcher_config.conflicts(exe,launchers,os.environ)
        choice=dict(route=route,fg_input=fg_input) if route else None
        setup=preconditions(package,exe,recipe)
        return compat.decide(scan,data,ids,choice,None,accept,conflicts,launchers,verified=recipe[1] if recipe else None,setup=setup,
                             accept_risk=accept_risk),scan,data,ids
    except Exception as error:  # noqa: BLE001 - the check is advice; an unexpected failure must not block an install
        print('Compatibility check skipped ('+type(error).__name__+': '+str(error)[:200]+').',file=sys.stderr)
        return None

def verdict_notes(verdict):
    """The lines Install prints about the verdict: the verdict, its notes and the user's numbered steps."""
    lines=['Compatibility: '+verdict['line']]
    lines+=['Note: '+w for w in verdict['warnings'] if not w.startswith('Known on BC-250: ')]
    lines+=['Accepted: '+r['code']+' ('+r['text']+')' for r in verdict['refusals'] if r['code'] in verdict['accepted']]
    lines+=['Anti-cheat refusal overridden at your request (risk accepted): '+r['text'] for r in verdict['refusals']
            if r['code'] in verdict.get('risk_accepted',())]
    if verdict['manual_steps']:lines+=['Your steps:']+['  '+str(n)+'. '+s for n,s in enumerate(verdict['manual_steps'],1)]
    return lines

# The anti-cheat override (compat.py's risk refusal 'anticheat'): per game, after the warning below, confirmed by typing
# this sentence (install.py --accept-anticheat-risk; Setup's Override anti-cheat refusal...). At a terminal it is always
# typed; without one (a script, output piped elsewhere, Setup) it is given with --confirm-anticheat-risk, so a script
# spells it out. Neither --accept nor Install anyway lifts it. The acceptance is recorded with one installation
# (risk_accepted) and never carried: Restore clears it, and the next Install of the game asks again.
RISK_SENTENCE='I accept that my account may be banned'
def risk_confirmed(text):
    """True when text is the confirmation sentence: case and punctuation as written, blanks around it ignored."""
    return isinstance(text,str) and text.strip()==RISK_SENTENCE

def joined(names):
    """'A', 'A and B', 'A, B and C' (compat.names_text, without needing compat.py)."""
    names=[str(n) for n in names]
    return ' and '.join(names) if len(names)<3 else ', '.join(names[:-1])+' and '+names[-1]

def anticheat_warning(game,names,product=None):
    """The facts shown before the anti-cheat override is confirmed: on the command line (product None: 'this build') and
    in Setup, which names the product (a dialog shows the text on its own)."""
    name=product or 'This build'
    return '\n'.join([game+' ships anti-cheat: '+joined(names)+'.',
                      name+' loads DLLs into the game process. Anti-cheat software can treat that as tampering and answer with a ban '
                      'of your account or a refusal to start the game.',
                      name+' does not hide itself from anti-cheat and will not try to.',
                      'Use it at most in offline or single-player modes; the anti-cheat can run in those modes too.',
                      'The maintainers cannot help with bans.',
                      'Restore removes the DLLs and launch settings '+(product or 'this build')+' added; its backup folder '+STATE+
                      ' (with its logs) stays in the game folder. Restore cannot undo a ban.'])

def anticheat_names(verdict):
    """The anti-cheat names of verdict's risk refusal, or [] when the game has none."""
    return next((list(r.get('names') or []) for r in (verdict or {}).get('refusals',[]) if r['code']=='anticheat'),[])

def risk_record(verdict,package=None,now=None):
    """The installation record's risk_accepted: one entry per risk refusal overridden for this installation, with its
    code, the anti-cheat names, the local time of the installation and the package (its name carries the version)."""
    import datetime
    when=(now or datetime.datetime.now().astimezone()).isoformat(timespec='seconds')
    return [dict(code=r['code'],anticheat=list(r.get('names') or []),accepted_at=when,package=package)
            for r in verdict.get('refusals',[]) if r['code'] in verdict.get('risk_accepted',())]

def risk_lines(record):
    """What Status and Check say about an installation made despite anti-cheat, also an interrupted one (its DLLs may be in
    place); nothing once it is restored."""
    status=(record or {}).get('status')
    if status not in ('installed','prepared'):return []
    what='Installed' if status=='installed' else 'Interrupted installation'
    return [what+' despite anti-cheat ('+joined(item.get('anticheat') or ['unknown'])+'), risk accepted on '+
            str(item.get('accepted_at') or '?')[:10]+'.' for item in record.get('risk_accepted') or []]

def same_exe(first,second):
    return Path(first).expanduser().absolute().resolve()==Path(second).expanduser().absolute().resolve()

def anticheat_override(values,exe,games):
    """True when --accept-anticheat-risk names exe: =EXE for that executable, or the bare option when exe is the only game
    of the command (main() refuses a bare option for several games)."""
    return any((value=='' and len(games)==1) or (value and same_exe(value,exe)) for value in values)

def terminal():
    """True when the sentence can be asked for: stdin and stdout are a terminal."""
    return sys.stdin.isatty() and sys.stdout.isatty()

def confirm_anticheat_risk(exe,names,sentence=None):
    """The anti-cheat override's confirmation for one game: the warning is printed, then the sentence is asked for at a
    terminal (also when --confirm-anticheat-risk gave it: a pasted command does not skip it), or, without a terminal,
    taken from --confirm-anticheat-risk. Raises ValueError (nothing is changed) on a mismatch, at an end of input or
    Ctrl+C, or without a terminal and the option."""
    print('\n'+anticheat_warning(exe.name,names)+'\n',flush=True)
    if terminal():
        if sentence is not None:print('At a terminal the sentence is typed; --confirm-anticheat-risk is for runs without one.')
        print('To override the refusal for '+exe.name+', type this sentence exactly (anything else cancels):\n  '+RISK_SENTENCE,flush=True)
        try:typed=input('> ')
        except (EOFError,KeyboardInterrupt):print();typed=''
        if not risk_confirmed(typed):raise ValueError('Anti-cheat override cancelled: what you typed does not match the sentence. Nothing was changed.')
        return
    if sentence is None:
        raise ValueError('Anti-cheat override not confirmed: without a terminal, give the sentence as --confirm-anticheat-risk "'+RISK_SENTENCE+'". Nothing was changed.')
    if not risk_confirmed(sentence):raise ValueError('Anti-cheat override cancelled: --confirm-anticheat-risk does not match the sentence "'+RISK_SENTENCE+'". Nothing was changed.')

def override_anticheat(package,exe,route,fg_input,accept,verdict=None,sentence=None):
    """--accept-anticheat-risk for one game: ['anticheat'] once the warning is shown and the sentence confirmed, [] when
    the check finds no anti-cheat refusal. verdict: main()'s Automatic verdict, else the one for the route and input chosen
    (as install() makes it). A game refused for another reason too is refused for that one, without asking. Without a
    compatibility check (compat_verdict None) nothing tells whether the game ships anti-cheat: refused."""
    if verdict is None:
        found=compat_verdict(package,exe,route,fg_input,None,accept);verdict=found[0] if found else None
    if verdict is None:
        raise ValueError('Anti-cheat override not confirmed: the compatibility check did not run, so anti-cheat was not checked. Nothing was changed.')
    names=anticheat_names(verdict)
    if not names:
        print('No anti-cheat found in this game: --accept-anticheat-risk changes nothing here.');return []
    others=[r for r in verdict['blocking'] if r['kind']!='risk']
    if others:
        import compat
        raise compat.Refused(others[0])
    confirm_anticheat_risk(exe,names,sentence)
    return ['anticheat']

# OptiScaler.ini keys a user sets for themselves (the MFG multiplier from OptiScaler's menu, the Reflex override, MFG
# Unlocker's model), kept across Restore and Install of a fresh OptiScaler setup: (section, key, description).
CARRIED_INI=[('XeFG','InterpolationCount','multiplier'),('fakenvapi','ForceReflex','Reflex override'),('XeFG','XeFGModel','MFG Unlocker model')]

@locked
def install(package,exe,preview=False,route="native",fg_input="upscaler",dependency_dir=None,launcher_home=None,extra_args=(),dlss_helper='auto',
            upscaler='fsr4',helixsr_dir=None,accept=(),verdict=None,accept_risk=()):
    """Install the package into the game of exe. accept: soft refusal codes the user accepted for this game; accept_risk:
    risk refusal codes (anticheat) the user overrode for it after the warning and the typed sentence (main(),
    override_anticheat), recorded with this installation only. verdict: main()'s Automatic verdict for route and fg_input,
    used as it is."""
    if route not in ["native","opti"] or fg_input not in ["upscaler","dlssg","fsrfg","fsrfg30"]:raise ValueError("Unknown integration route")
    if dlss_helper not in ['auto','yes','no']:raise ValueError('Unknown DLSS helper choice (auto, yes or no)')
    if upscaler not in UPSCALERS:raise ValueError('Unknown upscaler (fsr4 or helixsr)')
    if exe.is_symlink() or not exe.is_file() or exe.suffix.lower()!='.exe':raise ValueError('Choose the actual game .exe, not a symlink')
    check_exe(exe)
    root=exe.parent.resolve();idle(root);state=root/STATE
    if not str(root).isascii():raise ValueError('This checkpoint’s shader loader needs an ASCII-only game folder path; use an ASCII library path before installing.')
    if state.is_symlink():raise ValueError('Installation state is a symlink')
    archive_state=None
    if state.exists():
        record=json.loads(safe(root,STATE+'/state.json').read_text())
        if record.get('status')!='restored':raise ValueError('An installation record already exists; use restore before installing again')
        archive_state=root/(STATE+'-restored-'+uuid.uuid4().hex[:12])
    # Settings the user changed in the previous installation, saved by its Restore. Reinstalling keeps them.
    carried={};previous_helixsr_ini=None
    if archive_state and record.get('preserved_helixsr_ini'):
        try:previous_helixsr_ini=safe(state,record['preserved_helixsr_ini']).read_bytes()
        except (OSError,ValueError):previous_helixsr_ini=None
    if archive_state:
        for path,relative in (record.get('preserved_settings') or {}).items():
            carried[path]=safe(state,relative).read_bytes()
        if not carried and (state/'preserved-ini').is_dir():
            # Restores before preserved_settings existed: tell the two files apart by their sections.
            for copy in sorted((state/'preserved-ini').glob('xemfg-*.ini'),key=lambda p:p.stat().st_mtime):
                data=copy.read_bytes();sections={section for section,_ in read_ini(data)}
                if 'xessmfg' in sections:carried['XeSSMFG/settings.ini']=data
                elif 'bc250' in sections:carried['BC250-XeFG/settings.ini']=data
    # A removed fresh OptiScaler setup's INI (saved by that Restore): the choices this README promises to keep.
    carried_ini={}
    if archive_state and record.get('preserved_ini'):
        try:
            previous_ini=read_ini(safe(state,record['preserved_ini']).read_bytes())
            for section,key,name in CARRIED_INI:
                value=previous_ini.get((section.lower(),key.lower()),'').strip()
                if value and value.lower()!='auto':carried_ini[(section,key)]=value
        except (OSError,ValueError,configparser.Error):carried_ini={}
    if route=='native' and not (root/'libxess_fg.dll').is_file():raise ValueError('This build needs a game with native XeSS Frame Generation (libxess_fg.dll beside its .exe)')
    # Per-game recipe (recipes.py) and compatibility verdict (compat.py): both read only, and every refusal comes before
    # the first download or write. A verdict main() made for Automatic is used as it is; otherwise the route and input
    # given here are the user's explicit choice.
    recipe=recipe_for(package,exe,launcher_home)
    expected=((recipe[1] or {}).get('match',{}).get('exe') or []) if recipe else []
    if expected and exe.name.lower() not in expected:
        # The launcher ID matched a verified game, but this .exe is not the one it renders from (a launcher or
        # bootstrap stub in the game root): the DLLs would sit beside a process that never loads them.
        found=sorted({str(p.relative_to(root)) for p in root.rglob('*') if p.name.lower() in expected and p.is_file()})[:3]
        raise ValueError('For '+recipe[1]['title']+' choose the game’s own executable ('+' or '.join(found or expected)+'), not '+exe.name+'.')
    if verdict is None or (verdict['route'],verdict['fg_input'])!=(route,fg_input):
        found=compat_verdict(package,exe,route,fg_input,launcher_home,accept,accept_risk)
        verdict=found[0] if found else None
    if verdict:
        import compat
        compat.preflight(verdict)
    package_record=json.loads((package/'manifest.json').read_text())
    if package_record.get('runtime')!='xemfg' or package_record.get('launcher_setup')!='automatic':
        raise ValueError('This installer installs only frame-generation packages with automatic launcher setup; use the installer of the package being installed')
    proxy=package_record.get('addon_entry')==PROXY_ENTRY
    if package_record.get('addon_entry') not in [None,PROXY_ENTRY]:raise ValueError('Unknown add-on entry; use the installer of the package being installed')
    # Only the XeSSMFG enabler is loaded as version.dll; a proxy package leaves another mod's version.dll alone.
    if not proxy and (root/'version.dll').exists():raise ValueError('version.dll is occupied; restore the previous proxy mod before installing this build')
    if (root/'XeSSMFG').exists():raise ValueError('An existing XeSSMFG folder needs removal or restoration before installing')
    ini=safe(root,'OptiScaler.ini')
    fresh=not ini.exists();files=payload(package);owner_module='dxgi.dll'
    if 'dependencies.json' not in files:raise ValueError('Package lacks its pinned dependency list (dependencies.json)')
    pins=check_pins(json.loads(files['dependencies.json']));runtime=pins['runtime']
    # HelixSR: a release on this computer whose network HelixSR's own setup has built, checked before anything is fetched.
    helix=None;modern_provider=None
    if upscaler=='helixsr' and pins.get('hlx'):upscaler='hlx-dlss'
    if upscaler in hlx.NAMES and not custom_hlx_supported(files,pins):raise ValueError('Package lacks the qualified OptiScaler integration required by HLX')
    if upscaler=='helixsr':
        helix=helixsr.find(package,explicit=helixsr_dir)
        if helix['state']!='ready':raise ValueError(helixsr.guidance(helix))
        # A folder named with --helixsr is remembered, so later runs and Setup find it without the option.
        if helixsr_dir is not None and not preview:helixsr.remember(helixsr_dir)
    if proxy and 'ProxyPackage' not in runtime:raise ValueError('install.py and dependencies.json come from different builds (no proxy runtime layout); use one package’s files')
    layout=runtime['ProxyPackage' if proxy else 'Package']
    custom_opti=files.get('opti/OptiScaler.dll')
    # Every installation takes Intel's XeFG/XeLL runtime and the FSR4 DLL from their pinned upstream downloads
    # (dependencies.json 'runtime', in the layout of the package's add-on). A package that still carries one of these
    # files must carry the pinned bytes.
    for name,source in layout.items():
        if name in files and digest(files[name])!=runtime['Files'][source]:raise ValueError('Package file differs from its pinned upstream download: '+name)
    dependencies={}
    if fresh:
        # A fresh setup brings OptiScaler's own files and OptiPatcher from their pinned upstreams (dependencies.json
        # 'payload'). NVIDIA's DLSS helper is decided below, once the INI is known (dlss_helper_plan): earlier test builds
        # placed it in every fresh setup, over a game's own copy.
        for name in pins['payload']['Files']:
            target=setup_target(name)
            # A proxy or partial OptiScaler tree belongs to another installer.
            if safe(root,target).exists() and (target=='dxgi.dll' or target.startswith('OptiScaler/')):raise ValueError('Existing file needs manual mod chaining: '+target)
        # Its OptiScaler.ini decides the checks below, so these downloads come first (also for a preview).
        dependencies={setup_target(name):data for name,data in pinned(package,pins,['payload'],dependency_dir).items()}
        original_ini=dependencies.pop('OptiScaler.ini')
        if files.get('opti/OptiScaler.ini') is not None:original_ini=merge_update_settings(files['opti/OptiScaler.ini'],original_ini)[0]
    else:
        original_ini=ini.read_bytes()
        proxies=[name+'.dll' for name in ['dxgi','winmm','d3d12','wininet','version','winhttp','dbghelp','OptiScaler']]+['OptiScaler.asi']
        # The pinned nightly, and earlier pins whose installations this build still replaces cleanly.
        accepted_hashes={pins['payload']['ProxyHash'],*pins['payload'].get('CompatibleProxyHashes',[])}
        if custom_opti is not None:accepted_hashes.add(digest(custom_opti))
        matches=[name for name in proxies if (root/name).is_file() and digest(safe(root,name).read_bytes()) in accepted_hashes]
        if not matches:
            raise ValueError('Existing OptiScaler must be a supported pinned build. Restore/update its adapter separately first.')
        owner_module=matches[0]
    parsed=read_ini(original_ini)
    # A configured external FFX library would bypass the file being installed.
    for (section,key),value in parsed.items():
        if section=='libraries' and key in ['ffxdx12path','xefgpath','xellpath'] and value.lower() not in ['', 'auto']:
            raise ValueError('OptiScaler uses a custom DLL path; use its normal local DLL layout first')
    opti=parsed.get(('libraries','optidllpath'),'auto')
    default=('OptiScaler' if opti.lower() in ['', 'auto'] else opti.replace('\\','/'))+'/'+DLL
    # Fresh setup supplies OptiScaler's local library directory. Its DLL wins
    # over a native game DLL beside the executable once dependencies are placed.
    if not fresh and opti.lower() in ['', 'auto'] and not (root/default).is_file() and (root/DLL).is_file():default=DLL
    fsr_target=relative_library(root,parsed,'ffxdx12srpath',default)
    if not fresh and not (root/fsr_target).is_file():raise ValueError('Cannot find OptiScaler’s configured local FSR4 DLL')
    # HelixSR's own installers keep a record beside a drop-in they placed: that file is theirs to update and remove.
    helix_ini=(Path(fsr_target).parent/helixsr.INI).as_posix();helix_log=(Path(fsr_target).parent/helixsr.LOG).as_posix()
    if safe(root,(Path(fsr_target).parent/helixsr.HELIXSR_MARKER).as_posix()).exists():
        raise ValueError('HelixSR’s own installer placed HelixSR beside '+fsr_target+' ('+helixsr.HELIXSR_MARKER+'): remove it with HelixSR’s uninstaller or HelixSR Desktop first')
    changes=dict(CHANGES)
    if route=='opti':
        changes.update({('FrameGen','Enabled'):'true',('FrameGen','FGInput'):fg_input,('FrameGen','FGOutput'):'xefg',('fakenvapi','UseFakenvapi'):'true',('Libraries','XeFGPath'):'OptiScaler',('Libraries','XeLLPath'):'OptiScaler'})
        # XeFG does not interpolate in exclusive fullscreen ("Interpolation is not supported in fullscreen mode"): a game
        # that asks for it presents only real frames. OptiScaler then keeps the swap chain borderless (upstream sets this
        # per game through quirks); under Proton the exclusive mode brings nothing, so every OptiScaler route gets it.
        # Measured 2026-09-28 in Echo Point Nova: 1.0 presents per game frame at 2x without it, 2.0 with it. A value the
        # user wrote is kept.
        if parsed.get(('xefg','forceborderless'),'auto').strip().lower() in ['','auto']:changes[('XeFG','ForceBorderless')]='true'
    # MFG Unlocker (a separate tool for 3x/4x, placed by the user) reads [XeFG] XeFGModel from OptiScaler.ini; no
    # OptiScaler build reads the key, so it changes nothing without MFG Unlocker. Unset, on MFG Unlocker's own model this build's
    # shaders run on 7 of their 13 programs (Cyberpunk 2077 at 3840x2160, measured 2026-10-21: 42.6 instead of 53.2
    # frames shown per second at 2x, 50.7 instead of 63.7 at 3x); 'default' keeps Intel's model, which this build
    # accelerates. Both routes, so a later switch or MFG Unlocker added later finds it. A value the user wrote is kept.
    if parsed.get(('xefg','xefgmodel'),'auto').strip().lower() in ['','auto']:changes[('XeFG','XeFGModel')]='default'
    if not proxy:changes[('Plugins','LoadAsiPlugins')]='true'  # the add-on is OptiScaler's BC250-MFG.asi plugin
    # A fresh setup places OptiPatcher (OptiScaler/plugins/OptiPatcher.asi, dependencies.json 'payload'), which unlocks
    # the DLSS/XeSS inputs of about 200 games on GPUs other than NVIDIA's; OptiScaler loads ASI plugins only with
    # LoadAsiPlugins=true (the pinned INI's auto means false), so a proxy package's fresh setup turns it on too. An
    # existing OptiScaler setup keeps its own plugin choice.
    elif fresh and any(setup_target(n).lower().endswith('.asi') for n in pins['payload']['Files']) and \
            parsed.get(('plugins','loadasiplugins'),'auto').strip().lower() in ['','auto']:changes[('Plugins','LoadAsiPlugins')]='true'
    changes.update({('Libraries','XeFGPath'):r'.\libxess_fg.dll',('Libraries','XeLLPath'):r'.\libxell.dll'})
    if route=='opti':
        # OptiScaler's MFG menu owns the multiplier: default to 2x, but keep a count the user already chose. Without the
        # enabler (proxy packages) Intel's runtime generates one frame per real frame on this GPU: always 2x.
        if proxy:changes[('XeFG','InterpolationCount')]='1'
        elif parsed.get(('xefg','interpolationcount'),'auto').lower() in ['','auto']:changes[('XeFG','InterpolationCount')]='1'
        # With the enabler, the HUD-less image from FSR 3 frame-generation input makes each generated frame show the
        # next real frame (measured 2026-09-27); without it XeFG interpolates the HUD with the scene.
        if fg_input in ['fsrfg','fsrfg30']:changes[('FrameGen','DisableHudless')]='true'
        # With XeFG output OptiScaler forwards a game's Reflex sleep and markers to XeLL only while Reflex is on in the
        # game, and some games turn it off for non-DLSS frame generation. Forced on, XeLL paces frame starts: in
        # Cyberpunk the median time from simulation start to the end of Present fell from 64 to 24 ms at 2x (same frame
        # rate; smaller gains at 3x/4x), and the frame-start pacer then acts in XeLL's sleep (measured 2026-09-27).
        # DLSS FG input needs the game's own Reflex anyway, and forcing it there would also override OptiScaler's
        # guards for DLSS multi-frame input, so it is left alone. A value the user wrote (0 = follow the game,
        # 1 = force off) is kept.
        if fg_input in ['upscaler','fsrfg','fsrfg30'] and parsed.get(('fakenvapi','forcereflex'),'auto').strip().lower() in ['','auto']:changes[('fakenvapi','ForceReflex')]='2'
    # Per-game recipe (recipes.py): verified keys where the INI says auto, OptiScaler quirks left free, game settings.
    settings_plan=[];launch_args=[];notes=[];community=None
    if recipe:
        rm,verified,wiki,leave,backports,_=recipe
        recipe_input=(verified or {}).get('fg_input')
        for item in leave:
            key=tuple(item['key'].split('.',1))
            if parsed.get((key[0].lower(),key[1].lower()),'auto').strip().lower() in ['','auto']:
                changes.pop(key,None);notes.append('Left '+item['key']+' to OptiScaler’s own setting for this game ('+item['quirk']+').')
        changes.update(rm.ini_changes(verified,backports,parsed,fg_input,recipe_input,route,'helixsr' if upscaler=='hlx-dlss' else upscaler))
        user=rm.prefix_user(exe,recipe[5],launcher_home)
        # Recipe values a previous installation's Restore could not put back keep their true originals.
        earlier=previous_settings(state,record,rm) if archive_state else {}
        if archive_state and not record.get('game_settings'):
            # A different installer's record (the maintainers' library tool moving a game between two builds) archived
            # this installer's last record: its Restore may have left recipe values in place, so take their originals
            # from there.
            for old in sorted(root.glob(STATE+'-restored-*'),key=lambda d:d.stat().st_mtime,reverse=True):
                try:
                    older=json.loads(safe(old,'state.json').read_text())
                    if older.get('game_settings'):earlier=previous_settings(old,older,rm);break
                except (OSError,ValueError):continue
        # The recipe whose game settings apply: the verified one, else a community recipe the verdict found (tier B).
        community=None if verified else ((verdict or {}).get('recipe_entry') if (verdict or {}).get('tier')=='B' else None)
        settings_plan=rm.settings_plan(verified or community,user,route,fg_input if route=='opti' else None,earlier)
        # A verified game keeps 0.9.0's argument; any other game takes the verdict's (community recipe, the wiki's DX12
        # argument from a strong match or a title match detection confirms, or detection's own switch).
        launch_args=rm.launch_args(verified,wiki) if verified or verdict is None else list(verdict['launch_args'])
        notes+=rm.suggestions(verified,wiki,fg_input,route)
        if verified:notes.insert(0,'Recipe (verified on BC-250): '+verified['title'])
        if (verified or community) and not user and (verified or community).get('game_settings'):notes.append('Game settings not changed: no Proton prefix found for this game yet. Start it once, then use Settings (configure) to apply them.')
    elif verdict:launch_args=list(verdict['launch_args'])
    if verdict:
        # Community-recipe and reviewed wiki keys (never a key a quirk sets for the exe), only where the INI says auto.
        for (section,key),value in verdict['ini'].items():
            if parsed.get((section.lower(),key.lower()),'auto').strip().lower() in ['','auto']:changes[(section,key)]=value
        # DLSS is the game's only upscaler and it ships no copy: the helper keeps DLSS (and so OptiFG's input) visible.
        if dlss_helper=='auto' and verdict['dlss_helper']=='yes':dlss_helper='detected'
        notes=verdict_notes(verdict)+notes
    # Game arguments a caller asks for (such as the maintainers' library tool's DX12 switches), after the recipe's. A graphics API
    # switch replaces the recipe's own: a game gets one API switch.
    if extra_args:
        import launcher_config
        for arg in extra_args:
            if arg.lower() in launcher_config.API_ARGS:launch_args=[a for a in launch_args if a.lower() not in launcher_config.API_ARGS]
            if arg not in launch_args:launch_args.append(arg)
    kept=[]
    if not fresh:carried_ini={}  # an existing OptiScaler INI stays as the user left it anyway
    for (section,key),value in carried_ini.items():
        if (section,key)==('XeFG','InterpolationCount') and (route!='opti' or proxy):continue
        if changes.get((section,key))==value:continue  # the installer writes this value anyway: nothing of the user's to keep
        changes[(section,key)]=value;kept.append('OptiScaler.ini '+section+'.'+key+'='+value)
    # Older OptiScaler read XeFGPath/XeLLPath into XeSSLibrary and then saved the FG/latency DLL as XeSSPath.
    # The fixed DLL reads each key independently; remove that invalid inherited SR override on upgrade as well.
    changes.update(xess_library_repair(patch_ini(original_ini,changes)))
    ini_after=patch_ini(original_ini,changes)
    # The launcher's own fields carry the loader overrides and the Vulkan layer: no wrapper script.
    import launcher_config
    # vkd3d-proton's own cache folder, unless the game folder's path is too long for its cache file names: then neither
    # vkd3d-proton setting is written (1.1.0's behaviour; identifiers off with the game's old cache would translate its
    # entries again on every start).
    vkd3d_cache=state/VKD3D_CACHE if launcher_config.vkd3d_cache_fits(state/VKD3D_CACHE,exe.name) else None
    if vkd3d_cache is None:notes.append('Game folder path too long for vkd3d-proton’s cache file names: its shader cache stays the game’s own, and '
                                        'wave sizes apply only to pipelines Mesa’s cache does not already hold.')
    launchers=launcher_config.plan(exe,owner_module,home=launcher_home,runtime='xemfg-proxy' if proxy else 'xemfg',route=route,args=launch_args,
                                   extra_env=(verdict or {}).get('extra_env'),vkd3d_cache=vkd3d_cache)
    # The runtime: the package's own copies when it carries them all (checked above), otherwise the pinned downloads,
    # fetched below once every check has passed.
    packaged_runtime={source:files[name] for name,source in layout.items() if name in files}
    downloads=set(packaged_runtime)!=set(layout.values())
    runtime_files=pinned(package,pins,['runtime'],fetch=False) if downloads else packaged_runtime
    for name,source in layout.items():files[name]=runtime_files[source]
    replacements=dict(dependencies)
    # NVIDIA's DLSS helper: only a fresh setup on a DLSS input where OptiScaler's search finds no copy of the game's
    # (fetched with the runtime below). An existing OptiScaler setup keeps its own files.
    helper=dlss_helper_plan(exe,route,fg_input,read_ini(ini_after),dlss_helper) if fresh else None
    if helper and helper['placed']:
        replacements.update({setup_target(name):data for name,data in pinned(package,pins,['dlss'],fetch=False).items()})
    if not fresh and dlss_helper=='yes':notes.append('DLSS helper not placed: an existing OptiScaler setup keeps its own files (nvngx_dlss.dll is placed only in a fresh setup).')
    if custom_opti is not None:replacements[owner_module]=custom_opti
    replacements.update({name.removeprefix('payload/'):data for name,data in files.items() if name.startswith('payload/')})
    # On the OptiScaler route its MFG menu owns the multiplier (InterpolationCount above): the loader's own stays 0.
    if route=='opti' and 'XeSSMFG/settings.ini' in replacements:replacements['XeSSMFG/settings.ini']=patch_ini(replacements['XeSSMFG/settings.ini'],{('XeSSMFG','Multiplier'):'0'})
    # The runtime sits beside the game (XeFGPath/XeLLPath above); a fresh setup's OptiScaler copies are not placed and
    # existing ones are set aside in the backups.
    for old in ['OptiScaler/libxess_fg.dll','OptiScaler/libxell.dll']:
        replacements.pop(old,None)
        if (root/old).exists():replacements[old]=None
    for path,previous in carried.items():
        if path in replacements and replacements[path] is not None:
            # On the OptiScaler route the loader's own multiplier must stay 0 (OptiScaler sets the count).
            skip={('xessmfg','multiplier')} if path=='XeSSMFG/settings.ini' and route=='opti' else set()
            # ...and a 0 kept from an OptiScaler-route install means "follow the game" on the native route: keep the default.
            if path=='XeSSMFG/settings.ini' and route=='native' and read_ini(previous).get(('xessmfg','multiplier'),'').strip()=='0':skip={('xessmfg','multiplier')}
            replacements[path],values=carry_settings(replacements[path],previous,skip)
            kept+=[path+' '+section+'.'+key+'='+value for (section,key),value in values.items()]
    if helix:
        # HelixSR's DLL as its setup built it (checked again as read), and helixsr.ini beside it with HelixSR's own DLSS
        # frame generation off. Nothing else of HelixSR's goes into the game (no helixsr-fg folder).
        replacements[fsr_target]=helixsr.dll_bytes(helix,helixsr.pins(package))
        # The game's own helixsr.ini when it has one; otherwise the user's edited copy an earlier Restore kept, if any.
        existing=safe(root,helix_ini);base=existing.read_bytes() if existing.is_file() else previous_helixsr_ini
        replacements[helix_ini]=helixsr.ini_bytes(base)
    else:replacements[fsr_target]=files['fsr4/'+DLL]
    if upscaler in hlx.NAMES:
        modern_provider=hlx.layout(package,upscaler,str(Path(fsr_target).parent),helixsr_dir)
        modern_provider['metadata']['legacy_target']=fsr_target
        for name in modern_provider['files']:
            if safe(root,name).exists():raise ValueError('Provider target is already occupied: '+name)
        if safe(root,modern_provider['metadata']['log']).exists():raise ValueError('Provider log already exists outside this installation: '+modern_provider['metadata']['log'])
        replacements.update(modern_provider['files'])
        if modern_provider['metadata'].get('ini'):
            name=modern_provider['metadata']['ini']
            if safe(root,name).exists():raise ValueError('Provider settings are already occupied: '+name)
            replacements[name]=helixsr.ini_bytes(previous_helixsr_ini)
        changes.update(modern_provider['ini_changes']);ini_after=patch_ini(ini_after,modern_provider['ini_changes'])
    replacements['OptiScaler.ini']=ini_after
    # Last refusals (a symlink or folder where a file goes), then the runtime downloads: no check waits on the network.
    # A preview fetches them too, so a preview that succeeds proves the install has every byte it needs: the
    # maintainers' library tool checks a move with a preview before it changes anything, and its install then reads
    # the cache.
    for name in replacements:safe(root,name)
    fetch=(['runtime'] if downloads else [])+(['dlss'] if helper and helper['placed'] else [])
    if fetch:
        fetched=pinned(package,pins,fetch,dependency_dir)
        replacements={name:fetched[data.name] if isinstance(data,Upstream) else data for name,data in replacements.items()}
    plan=[]
    for name,data in replacements.items():
        target=safe(root,name);before=target.read_bytes() if target.exists() else None
        after=digest(data) if data is not None else None
        plan.append(dict(path=name,before=digest(before) if before is not None else None,
                         after=after,mode=stat.S_IMODE(target.stat().st_mode) if target.exists() else (0o755 if name.endswith('.sh') else 0o644)))
        # The original's modification time: Restore sets it again on the bytes it puts back.
        if before is not None:plan[-1]['mtime_ns']=target.stat().st_mtime_ns
    # Folders the files go into that the game does not have yet: Restore removes them again once they are empty.
    created_dirs=created_folders(root,[item['path'] for item in plan])
    # The proxy writes its logs beside it, under the names an earlier build's add-on (lib2x) used: a log of that name
    # already in the game folder is set aside until Restore, so the proxy's log never overwrites it and Restore puts
    # it back as it was.
    displaced=[name for name in PROXY_LOGS if proxy and (root/name).is_file() and not (root/name).is_symlink()]
    # HelixSR writes helixsr.log beside its DLL: one there already (an earlier HelixSR) is set aside until Restore.
    helix_displaced=bool(helix) and safe(root,helix_log).is_file()
    upscaler_record=modern_provider['metadata'] if modern_provider else dict(name=upscaler,target=fsr_target)
    if helix:upscaler_record.update(version=helix['version'],release=helix['folder'],ini=helix_ini,log=helix_log,displaced_log=helix_displaced)
    if preview:
        print('\n'.join(item['path'] for item in plan))
        for name in displaced:print('Set aside until Restore: '+name+' (an earlier log by the same name)')
        for target in launchers:print('Configure '+target['launcher']+': '+target['path'])
        if vkd3d_cache is not None:print('vkd3d-proton shader cache: '+str(vkd3d_cache))
        for item in settings_plan:print(('Game setting: ' if item['after'] is not None else 'Game setting (pending): ')+item['file'])
        if helper:print(helper_line(helper))
        print(upscaler_line(upscaler_record,runtime['Files'].get('fsr4/'+DLL)))
        for line in notes:print(line)
        return
    print('Installing '+('HelixSR' if helix else 'FSR 4')+', frame generation and launcher settings; saving original files.')
    if archive_state:state.rename(archive_state)
    # wrapper=None: records of wrapper-based builds named their run.sh here.
    record=dict(status='prepared',runtime='xemfg',route=route,fresh=fresh,wrapper=None,game=str(exe.resolve()),files=plan,package=package_record.get('name'),
                ini_changes=[dict(section=s,key=k,value=v) for (s,k),v in changes.items()],launchers=launchers,launch_args=launch_args,
                launch_args_added=launcher_config.added_args(launchers))
    record['installation_id']=uuid.uuid4().hex
    record['created_dirs']=created_dirs
    if vkd3d_cache is not None:record['vkd3d_cache']=VKD3D_CACHE
    record['upscaler']=upscaler_record
    # displaced_logs (also when empty) tells Restore that every proxy log in the game folder is this installation's.
    # installed_at: Status and Check read only logs written after it (a log left from before the installation is not this build's).
    if proxy:record.update(addon_entry=PROXY_ENTRY,max_factor=package_record.get('max_factor',2),displaced_logs=displaced,installed_at=time.time())
    if helper:record['dlss_helper']=helper
    if verdict:record['compat']=dict(tier=verdict['tier'],line=verdict['line'],choice=verdict['choice'],launch_source=verdict['launch_source'],
                                     ini_sources=verdict['ini_sources'],accepted=verdict['accepted'],extra_env=verdict['extra_env'])
    # The anti-cheat override, for this installation only: Status and Check show it, Restore clears it.
    if verdict and verdict.get('risk_accepted'):record['risk_accepted']=risk_record(verdict,package_record.get('name'))
    if recipe:
        entry=recipe[1] or community
        record['recipe']=dict(title=(entry or {}).get('title'),status='verified-bc250' if recipe[1] else 'community-bc250' if entry else None,
                              wiki=[w['title'] for w in recipe[2]],launch_args=launch_args)
        if (recipe[1] or {}).get('upscaler_ini'):record['recipe']['upscaler_ini']=recipe[1]['upscaler_ini']
        record['game_settings']=[settings_record(item) for item in settings_plan]
    staging=Path(tempfile.mkdtemp(prefix=STATE+'-preparing-',dir=root))
    try:
        (staging/'backups').mkdir()
        if vkd3d_cache is not None:(staging/VKD3D_CACHE).mkdir()  # vkd3d-proton does not create its cache folder
        for i,item in enumerate(plan):
            if item['before'] is not None:write(staging/'backups'/str(i),(root/item['path']).read_bytes(),item['mode'])
        for i,item in enumerate(settings_plan):
            if item['before'] is not None and item['after'] is not None:write(staging/'game-settings'/str(i),item['before'])
        # Launcher files rewritten whole (Heroic's JSON, Lutris's YAML): a copy as found, which Restore writes back
        # when the restored file holds the same settings (launcher_config.apply).
        for i,target in enumerate(launchers):
            if target['launcher'] in launcher_config.WHOLE_FILE:
                path=Path(target['path']);data=path.read_bytes();write(staging/'launcher-files'/str(i),data,0o600)
                target['file_backup']=dict(path='launcher-files/'+str(i),sha256=digest(data),mtime_ns=path.stat().st_mtime_ns)
        if displaced or helix_displaced:(staging/'displaced-logs').mkdir()
        write(staging/'state.json',(json.dumps(record,indent=2)+'\n').encode())
        os.replace(staging,state)
    finally:
        if staging.exists():shutil.rmtree(staging)
    for name in displaced:os.replace(root/name,state/'displaced-logs'/name)
    if helix_displaced:os.replace(root/helix_log,state/'displaced-logs'/helixsr.LOG)
    for item in plan:
        # A file that already holds the bytes it gets (the package's OptiScaler where it is installed) stays as it is.
        if item['before'] is not None and item['before']==item['after']:continue
        target=safe(root,item['path']);data=replacements[item['path']]
        if data is None:target.unlink()
        else:write(target,data,item['mode'])
    if launchers:launcher_config.apply(launchers,write)
    for i,item in enumerate(settings_plan):
        if item['after'] is None or item['after']==item['before']:continue
        try:write_setting(item['path'],item['before'],item['after'])
        except (OSError,ValueError) as error:
            # The file is as it was: leave the setting to configure rather than fail an installed game.
            entry=record['game_settings'][i];entry.update(status='pending',after=None,reason='not written: '+str(error))
            for key in ['originals','carried','created_section']:entry.pop(key,None)
            if item.get('previous'):entry['previous']=item['previous']
    record['status']='installed'
    if package_record.get('update_contract')==UPDATE_CONTRACT:
        record['update_contract']=dict(UPDATE_CONTRACT)
        record['components']=component_state(record,digest((package/'manifest.json').read_bytes()))
    write(state/'state.json',(json.dumps(record,indent=2)+'\n').encode())
    remember_installation(exe,record,home=launcher_home)
    if upscaler in hlx.NAMES:remember_prepared(package,helixsr_dir)
    print('\nInstalled. Open your launcher and play normally. No wrapper command is needed.')
    if kept:print('Kept your settings from the previous installation: '+', '.join(kept))
    for item in record.get('game_settings',[]):
        if item['status']=='pending':print('Game setting pending: '+setting_line(item)+' ('+(item.get('reason') or 'start the game once, then Settings')+')')
        else:print({'applied':'Game setting applied: ','unchanged':'Game setting already set: '}[item['status']]+setting_line(item))
    if displaced:print('Set aside until Restore: '+', '.join(displaced)+' (an earlier log by the same name; in '+str(state/'displaced-logs')+')')
    added=launcher_config.added_args(launchers)
    if added:print('Launch option added: '+' '.join(added))
    skipped=[a for a in launch_args if a not in added]
    if skipped and launchers:print('Launch option not added: '+' '.join(skipped)+' (the launch options already choose a graphics API, or the launcher’s arguments are not managed)')
    if helper and (helper['placed'] or helper['game_copy'] or helper.get('dxgi_spoofing') or dlss_helper!='auto'):print(helper_line(helper))
    print(upscaler_line(upscaler_record,runtime['Files'].get('fsr4/'+DLL)))
    if vkd3d_cache is not None and any(launcher_config.planned_environment(row).get('VKD3D_SHADER_CACHE_PATH')==str(vkd3d_cache) for row in launchers):
        print('vkd3d-proton keeps this game’s shader cache in '+str(vkd3d_cache)+': the first start fills it and takes longer.')
    for line in notes:print(line)
    print('In game: '+('select native XeSS Frame Generation.' if route=='native' else 'open OptiScaler with Insert; confirm FG Input / XeFG Output and Active. Save Settings and restart after changing the input.'))
    if proxy:print('This build generates 2× (one generated frame per real frame).')

@locked
@launcher_locked
def restore(exe):
    root=exe.parent.resolve();idle(root);state=root/STATE
    record=json.loads(safe(root,STATE+'/state.json').read_text())
    if record['status']=='restored':print('Already restored.');return
    pending=record.get('pending_update')
    if pending and pending.get('generation'):
        for line in settle_interrupted(root,record)[1]:print(line)
        pending=record.get('pending_update')
    if pending:
        for name,change in pending['files'].items():
            item=next(v for v in record['files'] if v['path']==name)
            if item['after']!=change['before']:raise ValueError('Invalid pending update')
            target=safe(root,name);now=digest(target.read_bytes()) if target.exists() else None
            if now==change['after']:item['after']=change['after']
        record.pop('pending_update')
    actions=[];preserve=[];kept=[];timestamps=[];provider_logs=[]
    for i,item in enumerate(record['files']):
        target=safe(root,item['path']);current=target.read_bytes() if target.exists() else None
        original=safe(state,'backups/'+str(i)).read_bytes() if item['before'] is not None else None
        if original is not None and digest(original)!=item['before']:raise ValueError('Backup checksum mismatch: '+item['path'])
        backup=original;now=digest(current) if current is not None else None
        if now is not None and now==item['after']:
            for tail,logname in [('custom/hlx-dlss/dlss/helixsr.dll','helixsr.log'),('custom/hlx-fsr4/ffx/'+DLL,'HLX_FSR.log')]:
                if item['path'].endswith(tail):provider_logs.append((Path(item['path']).parent/logname).as_posix())
        if now==item['before']:
            # A switch or interrupted Restore may already have put the original
            # bytes back with a new timestamp. Restore metadata without rewriting.
            if original is not None and isinstance(item.get('mtime_ns'),int):
                timestamps.append((target,item['mtime_ns']))
            continue
        if item['path']=='OptiScaler.ini' and current is not None and original is None and now!=item['after']:
            # Fresh setup owned the whole INI. Keep post-install preferences in
            # the backup tree before removing it, so a clean reinstall works.
            read_ini(current)
            relative='preserved-ini/'+digest(current)+'.ini'
            preserve.append((safe(state,relative),current))
            record['preserved_ini']=relative
        elif Path(item['path']).name.lower()==helixsr.INI and current is not None and now!=item['after']:
            # HelixSR's settings file, edited since installation (its documented settings): the edited copy is kept with
            # the backups (and carried into the next HelixSR installation), and the file goes back to what it was.
            relative='preserved-ini/helixsr-'+digest(current)+'.ini'
            preserve.append((safe(state,relative),current))
            record['preserved_helixsr_ini']=relative
        elif item['path'] in ['XeSSMFG/settings.ini','BC250-XeFG/settings.ini'] and current is not None:
            # Keep every settings file, edited since install or carried into it, for the next Install.
            read_ini(current)
            relative='preserved-ini/xemfg-'+digest(current)+'.ini'
            preserve.append((safe(state,relative),current))
            record.setdefault('preserved_settings',{})[item['path']]=relative
        elif item['path']=='OptiScaler.ini' and current is not None and original is not None:
            old=read_ini(original);present=read_ini(current);changes={}
            for change in record['ini_changes']:
                key=(change['section'].lower(),change['key'].lower())
                if present.get(key)==change['value']:changes[(change['section'],change['key'])]=old.get(key)
            # Restore exact bytes when untouched; otherwise preserve unrelated edits. When the edits since installation
            # were only a re-save of the same content (OptiScaler writes every line as 'key = value'), the original
            # bytes too: the result would differ from them only in layout.
            if now!=item['after']:
                reverted=patch_ini(current,changes)
                original=original if same_ini(reverted,original) else reverted
        elif now!=item['after']:
            # Changed since installation by something else: a game update (its own DLSS/XeSS/XeLL files), the user or
            # another tool. That version belongs to the game now; keep it and restore everything else. The original
            # stays in the backups.
            kept.append((item['path'],i if item['before'] is not None else None));continue
        # The original bytes get their modification time back too (records of earlier builds have none).
        mtime=item.get('mtime_ns') if original is not None and original is backup and isinstance(item.get('mtime_ns'),int) else None
        actions.append((target,original,item['mode'],mtime))
    # Everything is checked before the first change: game settings (backups, per-key reverts), then launchers.
    settings,left=plan_restore_settings(root,record)
    launcher_notes=[]
    if record.get('launchers'):
        import launcher_config
        # The launcher files as found (records of earlier builds have none); a damaged copy is not used.
        originals={}
        for i,target in enumerate(record['launchers']):
            copy=target.get('file_backup')
            try:
                data=safe(state,copy['path']).read_bytes() if copy else None
                if data is not None and digest(data)==copy['sha256']:originals[i]=data
                if i in originals and isinstance(copy.get('mtime_ns'),int):originals[i]=(data,copy['mtime_ns'])
            except (OSError,ValueError,KeyError,TypeError):pass
        launcher_notes=launcher_config.apply(record['launchers'],write,restore=True,originals=originals) or []
    left+=write_restored_settings(settings)
    for target,mtime in timestamps:
        if target.stat().st_mtime_ns!=mtime:os.utime(target,ns=(target.stat().st_atime_ns,mtime))
    for path,data in preserve:write(path,data)
    for target,data,mode,mtime in actions:
        if data is None:target.unlink(missing_ok=True)
        else:
            write(target,data,mode)
            if mtime is not None:os.utime(target,ns=(target.stat().st_atime_ns,mtime))
    # The enabler's folder only when this installation created it (it refuses a game that has one): a proxy
    # installation places nothing there, so an XeSSMFG folder there now belongs to someone else.
    enabler=('XeSSMFG' in record['created_dirs']) if 'created_dirs' in record else any(item['path'].startswith('XeSSMFG/') for item in record['files'])
    if record.get('runtime')=='xemfg' and enabler and (root/'XeSSMFG').is_dir() and not (root/'XeSSMFG').is_symlink():
        # This installer created the directory; keep runtime logs and edited settings.
        os.replace(root/'XeSSMFG',state/('runtime-logs-'+uuid.uuid4().hex[:12]))
    # The proxy's logs: every one in the game folder is this installation's, except one that was there before it and
    # was never set aside (an interrupted installation). Records of earlier builds set nothing aside.
    displaced=record.get('displaced_logs');held=state/'displaced-logs';notes=[]
    provider=record.get('upscaler') or {}
    if provider.get('name')=='helixsr':put_back_helixsr_log(root,state,provider,notes)
    elif provider.get('legacy_helixsr'):put_back_helixsr_log(root,state,provider['legacy_helixsr'],notes)
    for relative in provider_logs:
        log=log_path(root,relative)
        if log is not None and log.is_file():
            write(state/'runtime-logs'/Path(relative).name,log.read_bytes());log.unlink()
    logs=[name for name in PROXY_LOGS if record.get('addon_entry')==PROXY_ENTRY and (root/name).is_file() and not (root/name).is_symlink()
          and not (displaced is not None and name in displaced and not (held/name).is_file())]
    if logs:
        # The proxy's logs in the game folder: kept with the backups, out of the game.
        folder=state/('runtime-logs-'+uuid.uuid4().hex[:12]);folder.mkdir()
        for name in logs:os.replace(root/name,folder/name)
    for name in displaced or []:
        if not (held/name).is_file():continue
        if (root/name).exists() or (root/name).is_symlink():notes.append('Left the earlier '+name+' in '+str(held/name)+': the game folder has another one.');continue
        os.replace(held/name,root/name)
    if displaced is not None and held.is_dir():
        with contextlib.suppress(OSError):held.rmdir()
    # vkd3d-proton's shader cache of this installation (records of earlier builds have none): the restored launch options
    # no longer name it, and the next installation starts a new one.
    cache=state/VKD3D_CACHE
    if record.get('vkd3d_cache')==VKD3D_CACHE and cache.is_dir() and not cache.is_symlink():
        try:shutil.rmtree(cache)
        except OSError as error:notes.append('Could not delete vkd3d-proton’s shader cache '+str(cache)+' ('+str(error)+'); it is not used any more.')
    # Folders the installation created, deepest first, once nothing else is in them.
    left_dirs=[]
    for relative in record.get('created_dirs') or []:
        folder=created_folder(root,relative)
        if folder is None:continue
        try:folder.rmdir()
        except OSError:left_dirs.append(relative)
    if left_dirs:notes.append('Kept folders the installation created that now hold other files: '+', '.join(left_dirs)+'.')
    if kept:record['kept_changed']=[path for path,_ in kept]
    # An anti-cheat override belonged to this installation: a new Install asks for it again.
    overridden=record.pop('risk_accepted',None)
    # The releases in-place updates saved for rollback: nothing returns to them once the originals are back.
    record.pop('generations',None)
    record['status']='restored';write(state/'state.json',(json.dumps(record,indent=2)+'\n').encode())
    try:freefg_library.unregister(exe)
    except (OSError,ValueError) as error:print('Library index was left unchanged: '+str(error))
    if (state/GENERATIONS).is_dir() and not (state/GENERATIONS).is_symlink():shutil.rmtree(state/GENERATIONS)
    print(('Original files and launcher settings restored. ' if record.get('launchers') else 'Original files restored; later INI edits preserved. Remove the earlier build’s run.sh launch wrapper from the game’s launch options. ')+'Backups remain in '+str(state))
    if record.get('preserved_ini'):print('Settings from the removed fresh OptiScaler setup: '+str(state/record['preserved_ini']))
    if record.get('preserved_helixsr_ini') and any(Path(item['path']).name.lower()==helixsr.INI for item in record['files']):
        print('Your edited '+helixsr.INI+' is kept in '+str(state/record['preserved_helixsr_ini'])+' (the next HelixSR installation starts from it).')
    for path,i in kept:
        print('Kept '+path+': it changed after installation (a game update or another tool), so it is the game’s own now'+
              ('; the version from before installation is '+str(state/'backups'/str(i)) if i is not None else '')+'.')
    for line in launcher_notes+left+notes:print(line)
    if overridden:print('The anti-cheat override ended with this installation; a new Install asks for it again.')

def upscaler_target(record,pins):
    """(installation's upscaler record, the managed file that holds the upscaler DLL). Records of earlier builds have no
    upscaler record: their FSR 4 DLL is the managed file installed with the pinned FSR 4 bytes or an earlier pin's
    (FSR4_BUILDS)."""
    upscaler=dict(record.get('upscaler') or {})
    if not upscaler:
        fsr4={pins['runtime']['Files'].get('fsr4/'+DLL),*FSR4_BUILDS}
        found=[item['path'] for item in record['files'] if item['after'] in fsr4 and Path(item['path']).name.lower()==DLL]
        if len(found)!=1:raise ValueError('This installation’s upscaler DLL cannot be identified; Restore, then Install with --upscaler')
        upscaler=dict(name='fsr4',target=found[0])
    if upscaler['target'] not in {item['path'] for item in record['files']}:raise ValueError('This installation does not manage the upscaler DLL; Restore, then Install with --upscaler')
    return upscaler

def switch_upscaler(package,root,record,upscaler,helixsr_dir=None,dependency_dir=None):
    """Switch an installed game between FSR 4 and HelixSR in place (configure --upscaler); returns its messages. Only the
    upscaler DLL and HelixSR's helixsr.ini beside it change. Each stays a managed file of the installation, so Restore still
    puts back exactly what was there before installation. The record names the new bytes in a pending update before any
    file changes (as earlier builds' updates did): an interrupted switch is resolved by Restore."""
    if upscaler not in UPSCALERS:raise ValueError('Unknown upscaler (fsr4 or helixsr)')
    state=root/STATE;files=payload(package);pins=check_pins(json.loads(files['dependencies.json']))
    current=upscaler_target(record,pins);target=current['target'];items={item['path']:item for item in record['files']}
    path=safe(root,target);now=digest(path.read_bytes()) if path.is_file() else None
    if now!=items[target]['after']:raise ValueError(target+' changed since installation (a game update or another tool): Restore, then Install again')
    ini_rel=(Path(target).parent/helixsr.INI).as_posix();log_rel=(Path(target).parent/helixsr.LOG).as_posix()
    ini_path=safe(root,ini_rel);ini_item=items.get(ini_rel)
    ini_now=digest(ini_path.read_bytes()) if ini_path.is_file() else None
    # helixsr.ini is HelixSR's settings file: the user may have edited it (HelixSR documents its settings there). An edit
    # never blocks a switch. Going to FSR 4, the edited copy is kept with the backups and the original goes back; going to
    # HelixSR, the file is built from what is there now (or from that kept copy), with HelixSR's frame generation off.
    edited=ini_item is not None and ini_now!=ini_item['after']
    def kept_ini():
        try:return safe(state,record['preserved_helixsr_ini']).read_bytes() if record.get('preserved_helixsr_ini') else None
        except (OSError,ValueError):return None
    def original_ini():
        """helixsr.ini's bytes from before installation (None when there was none)."""
        if ini_item is None:return ini_path.read_bytes() if ini_path.is_file() else None
        if ini_item['before'] is None:return None
        data=safe(state,'backups/'+str(record['files'].index(ini_item))).read_bytes()
        if digest(data)!=ini_item['before']:raise ValueError('Backup checksum mismatch: '+ini_rel)
        return data
    messages=[];found=None
    if upscaler=='helixsr':
        found=helixsr.find(package,explicit=helixsr_dir)
        if found['state']!='ready':raise ValueError(helixsr.guidance(found))
        new=helixsr.dll_bytes(found,helixsr.pins(package))
        base=ini_path.read_bytes() if ini_path.is_file() else None
        # Back from FSR 4 with the original helixsr.ini in place (or none): start from the user's kept edits, if any.
        if current['name']!='helixsr' and not edited and kept_ini() is not None:base=kept_ini()
        ini_new=helixsr.ini_bytes(base)
        if helixsr_dir is not None:helixsr.remember(helixsr_dir)
        if current['name']=='helixsr' and digest(new)==now and digest(ini_new)==ini_now:return ['The game already uses HelixSR '+found['version']+'.']
    else:
        if current['name']=='fsr4':return ['The game already uses FSR 4.']
        layout=pins['runtime']['ProxyPackage' if record.get('addon_entry')==PROXY_ENTRY else 'Package']
        new=pinned(package,pins,['runtime'],dependency_dir)[layout['fsr4/'+DLL]];ini_new=original_ini()
        if edited and ini_path.is_file():
            data=ini_path.read_bytes();relative='preserved-ini/helixsr-'+digest(data)+'.ini'
            write(safe(state,relative),data);record['preserved_helixsr_ini']=relative
            messages.append('Your edited '+ini_rel+' is kept in '+str(state/relative)+' (switching back to HelixSR starts from it).')
    # helixsr.ini becomes a managed file the first time HelixSR comes in: its state before installation is backed up now.
    if ini_item is None and upscaler=='helixsr':
        before=ini_path.read_bytes() if ini_path.is_file() else None
        ini_item=dict(path=ini_rel,before=digest(before) if before is not None else None,after=digest(before) if before is not None else None,
                      mode=stat.S_IMODE(ini_path.stat().st_mode) if before is not None else 0o644)
        if before is not None:
            ini_item['mtime_ns']=ini_path.stat().st_mtime_ns;write(state/'backups'/str(len(record['files'])),before,ini_item['mode'])
        record['files'].append(ini_item)
    pending={target:dict(before=items[target]['after'],after=digest(new))}
    if ini_item is not None:pending[ini_rel]=dict(before=ini_item['after'],after=digest(ini_new) if ini_new is not None else None)
    record['pending_update']=dict(files=pending);write(state/'state.json',(json.dumps(record,indent=2)+'\n').encode())
    write(path,new,items[target]['mode'])
    if ini_item is not None:
        if ini_new is None:ini_path.unlink(missing_ok=True)
        else:write(ini_path,ini_new,ini_item['mode'])
    for item in record['files']:
        if item['path'] in pending:item['after']=pending[item['path']]['after']
    record.pop('pending_update')
    log=log_path(root,log_rel);held=state/'displaced-logs'/helixsr.LOG
    if upscaler=='helixsr':
        new_record=dict(name='helixsr',target=target,version=found['version'],release=found['folder'],ini=ini_rel,log=log_rel,
                        displaced_log=bool(current.get('displaced_log')))
        # A helixsr.log there now is not this installation's (the FSR 4 side moves HelixSR's away): set aside until Restore.
        if current['name']!='helixsr' and log is not None and log.is_file() and not held.exists():
            held.parent.mkdir(exist_ok=True);os.replace(log,held);new_record['displaced_log']=True
    else:
        notes=put_back_helixsr_log(root,state,dict(current,log=log_rel),[]) if current['name']=='helixsr' else []
        new_record=dict(name='fsr4',target=target,displaced_log=False);messages+=notes
    record['upscaler']=new_record
    if 'components' in record:
        record['components']=component_state(record,record['components'].get('core',{}).get('manifest_sha256'))
    write(state/'state.json',(json.dumps(record,indent=2)+'\n').encode())
    messages.append('Upscaler switched. '+upscaler_line(new_record,digest(new)))
    return messages

def upscaler_recipe_changes(package,exe,record,upscaler):
    """Apply a verified upscaler-specific workaround, or return its owned value to the original on a switch.
    Explicit settings before installation and edits since installation remain the user's choice."""
    recipe=recipe_for(package,exe)
    rules=((recipe[1] or {}).get('upscaler_ini', {}) if recipe else {})
    if not recipe or recipe[1] is None:rules=record.get('recipe',{}).get('upscaler_ini',{})
    if not rules:return {}
    root=exe.parent.resolve()
    item_index,item=next((i,item) for i,item in enumerate(record['files']) if item['path']=='OptiScaler.ini')
    original={}
    if item['before'] is not None:
        data=safe(root,STATE+'/backups/'+str(item_index)).read_bytes()
        if digest(data)!=item['before']:raise ValueError('Backup checksum mismatch: OptiScaler.ini')
        original=read_ini(data)
    parsed=read_ini(safe(root,'OptiScaler.ini').read_bytes())
    owned={(c['section'].lower(),c['key'].lower()):str(c['value']) for c in record['ini_changes']}
    normalize=lambda value:str(value).strip().lower()
    out={}
    for name in sorted({key for values in rules.values() for key in values}):
        section,key=name.split('.',1);pair=(section.lower(),key.lower())
        before=original.get(pair,'auto');now=parsed.get(pair,'auto')
        if normalize(before) not in ('','auto'):continue
        previous=owned.get(pair)
        if normalize(now) not in ('','auto') and (previous is None or normalize(now)!=normalize(previous)):continue
        want=str(rules.get(upscaler,{}).get(name,before))
        if normalize(now)!=normalize(want):out[(section,key)]=want
    return out

@locked
def configure(exe,factor=None,resolution=None,percent=None,limit=None,downscale=None,upscale=None,upscaler=None,helixsr_dir=None,package=None,dependency_dir=None):
    """Change user settings. Modern provider selections use the shared generation transaction; legacy packages
    retain their original switch protocol. Scaling/factor choices follow a completed provider selection."""
    if factor not in [None,2,3,4]:raise ValueError('Invalid setting')
    if resolution not in [None,'output','scale','limit'] or (percent is not None and not 50<=percent<=100) or limit not in [None,720,1080,1440,2160]:raise ValueError('Invalid resolution setting')
    down_filters={'bilinear':0,'area':1}
    up_filters={'bilinear':0,'bicubic':2,'lanczos2':3,'fsr1':4}
    if (downscale is not None and downscale not in down_filters) or (upscale is not None and upscale not in up_filters):raise ValueError('Invalid filter')
    if percent is not None and resolution not in [None,'scale']:raise ValueError('--percent requires scale mode')
    if limit is not None and resolution not in [None,'limit']:raise ValueError('--limit requires limit mode')
    if percent is not None and limit is not None:raise ValueError('Choose a percentage or a limit')
    root=exe.parent.resolve();idle(root)
    record=json.loads(safe(root,STATE+'/state.json').read_text())
    if (record.get('pending_update') or {}).get('generation'):raise ValueError('An update was interrupted: run install.py update again (or install.py rollback) first')
    if record.get('status')=='installed' and record.get('runtime')!='xemfg':raise ValueError('This build is 2× only; it has no frame-generation settings to change')
    if record.get('status')!='installed' or record.get('runtime')!='xemfg':raise ValueError('Install this build first')
    proxy=record.get('addon_entry')==PROXY_ENTRY
    if factor is not None and factor>record.get('max_factor',4):
        raise ValueError('This build generates 2× only (one generated frame per real frame: the most Intel’s runtime generates on GPUs other than Intel’s)')
    managed={item['path'] for item in record['files']}
    own='BC250-XeFG/shaders/freefg-scaling.required' in managed
    modern=own or 'OptiScaler/plugins/BC250-XeFG/shaders/mfg-frame-settings.required' in managed
    setting_values={}
    if any(v is not None for v in [resolution,percent,limit,downscale,upscale]):
        if not modern:raise ValueError('These controls require the new scaling-controls build')
        if resolution is None:resolution='scale' if percent is not None else 'limit' if limit is not None else None
        if resolution is not None:setting_values[('BC250','ResolutionMode')]=str({'output':0,'scale':1,'limit':2}[resolution])
        if percent is not None:setting_values[('BC250','ResolutionPercent')]=str(percent)
        if limit is not None:setting_values[('BC250','ResolutionLimit')]=str(limit)
        if downscale is not None:
            if downscale=='area' and not own and 'OptiScaler/plugins/BC250-XeFG/shaders/mfg-downscale-filters.required' not in managed:raise ValueError('This build does not include that downscale filter')
            setting_values[('BC250','DownscaleFilter')]=str(down_filters[downscale])
        if upscale is not None:
            if upscale!='bilinear' and not own and 'OptiScaler/plugins/BC250-XeFG/shaders/mfg-upscale-filters.required' not in managed:raise ValueError('This build does not include enlargement filters')
            setting_values[('BC250','UpscaleFilter')]=str(up_filters[upscale])
    switched=[]
    upscaler_changes=upscaler_recipe_changes(Path(package or Path(__file__).resolve().parent),exe,record,upscaler) if upscaler is not None else {}
    if upscaler is not None:
        chosen_package=Path(package or Path(__file__).resolve().parent)
        if hlx.catalog(chosen_package) or record.get('update_contract')==UPDATE_CONTRACT:
            outcome=update.__wrapped__(exe,chosen_package,dependency_dir,component='upscaler',helixsr_dir=helixsr_dir,upscaler=upscaler)
            if outcome not in ('update','current'):raise ValueError('Provider selection was not applied: '+outcome)
            record=json.loads(safe(root,STATE+'/state.json').read_text());managed={item['path'] for item in record['files']}
            switched=['Provider selection saved.'];upscaler_changes={}
        else:switched=switch_upscaler(chosen_package,root,record,upscaler,helixsr_dir,dependency_dir)
    for line in switched:print(line)
    done,waiting=apply_pending_settings(exe,root,record)
    for item in done:print(('Game setting applied: ' if item['status']=='applied' else 'Game setting already set: ')+setting_line(item))
    for line in waiting:print('Game setting pending: '+line)
    changes={'OptiScaler.ini':upscaler_changes} if upscaler_changes else {}
    repair=xess_library_repair(safe(root,'OptiScaler.ini').read_bytes())
    if repair:changes.setdefault('OptiScaler.ini',{}).update(repair)
    if factor is not None and not proxy:
        changes['XeSSMFG/settings.ini']={('XeSSMFG','Multiplier'):str(factor if record['route']=='native' else 0)}
    if factor is not None and record['route']=='opti':changes.setdefault('OptiScaler.ini',{})[('XeFG','InterpolationCount')]=str(factor-1)
    if setting_values:changes['BC250-XeFG/settings.ini']=setting_values
    plan=[]
    for name,values in changes.items():
        if name not in managed:raise ValueError('Settings need the updated installer; Restore then Install this build')
        path=safe(root,name);plan.append((path,patch_ini(path.read_bytes(),values)))
    if not plan and not done:
        if not switched:print('Nothing to change.')
        return
    if 'OptiScaler.ini' in changes:
        # Restore reverts a key only while it still holds the value recorded for it: record the user's choice.
        recorded={(c['section'].lower(),c['key'].lower()):c for c in record['ini_changes']}
        for (section,key),value in changes['OptiScaler.ini'].items():
            entry=recorded.get((section.lower(),key.lower()))
            if entry:entry['value']=value
            else:record['ini_changes'].append(dict(section=section,key=key,value=value))
    for path,data in plan:write(path,data)
    if 'OptiScaler.ini' in changes:write(root/STATE/'state.json',(json.dumps(record,indent=2)+'\n').encode())
    print('Settings saved. Launch the game to apply them.')
    if record['route']=='opti':print('In game: Insert → Frame Generation → MFG also changes the multiplier. Save Settings to retain it.')

# One generation covers the coherent runtime, integration, selected provider and owned launcher deltas.
# Original backups remain independent of generations: Rollback undoes the latest operation, Restore uninstalls.
# Older known releases and format 1 records are imported into the explicit format 2 contract.
UPDATES_FROM={'freefg-1.1.3.1','freefg-1.1.4','freefg-1.1.5'}
LEGACY_UPDATE_TARGETS=frozenset(UPDATES_FROM)
UPDATE_CONTRACT={'format':2,'layout':'game-local-xemfg-proxy','configuration':1}
LEGACY_CONTRACT={'format':1,'layout':'game-local-xemfg-proxy','configuration':1}
RELEASE_FIELDS=('package','max_factor','update_contract','components','upscaler','ini_changes','launchers',
                'launcher_policy_keys','opti_owner','launch_args','launch_args_added','recipe','game_settings','route','fg_input','wiki_settings')
# Generations kept for rollback: the release before the last update.
GENERATIONS='generations'
GENERATIONS_KEPT=1
# The add-on's files beside the executable (the rest are under BC250-XeFG/), and the settings files whose values are the user's.
ADDON_FILES=('libxess_fg.dll','bc250_xefg_original.dll','libxell.dll')
SETTINGS_FILES=('BC250-XeFG/settings.ini','XeSSMFG/settings.ini')
# The modules OptiScaler can be loaded as: the one the launcher's DLL override names is the installation's owner module.
OPTI_PROXIES=[name+'.dll' for name in ['dxgi','winmm','d3d12','wininet','version','winhttp','dbghelp','OptiScaler']]+['OptiScaler.asi']
COMPONENTS={'addon':'frame generation add-on','runtime':'Intel XeFG runtime','integration':'OptiScaler integration',
            'fsr4':'FSR 4','helixsr':'HelixSR','hlx-dlss':'HLX DLSS','hlx-fsr4':'HLX FSR 4'}

def save_record(state,record):
    write(state/'state.json',(json.dumps(record,indent=2)+'\n').encode())
    sync_folder(state)

def sync_folder(folder):
    """fsync a folder: the names os.replace created or replaced in it are on disk before the next step depends on them."""
    descriptor=os.open(folder,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)

def file_digest(root,relative):
    """SHA-256 of a file in the game folder, or None when there is none (safe() refuses a symlink or a folder)."""
    path=safe(root,relative);return digest(path.read_bytes()) if path.is_file() else None

def validate_update_state(root,record):
    """Validate ownership and original backups before an update can create any recovery state."""
    state=root/STATE
    for folder in ('backups',GENERATIONS):safe(state,folder+'/.path-check')
    seen=set()
    for index,item in enumerate(record.get('files') or []):
        path=item.get('path')
        if not isinstance(path,str) or not path or path.casefold() in seen:raise ValueError('Invalid or duplicate installation file')
        seen.add(path.casefold());safe(root,path)
        for key in ('before','after'):
            value=item.get(key)
            if value is not None and (not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value)):
                raise ValueError('Invalid installation checksum: '+path)
        if not isinstance(item.get('mode'),int) or isinstance(item['mode'],bool) or not 0<=item['mode']<=0o7777:
            raise ValueError('Invalid installation mode: '+path)
        if item['before'] is not None:
            backup=safe(state,'backups/'+str(index))
            if not backup.is_file() or digest(backup.read_bytes())!=item['before']:
                raise ValueError('Original backup is missing or damaged: '+path)

def restore_generation_metadata(path,entry):
    """Recover the metadata of exact saved bytes; original-game metadata remains a separate ledger."""
    if not path.is_file():return
    if isinstance(entry.get('mode'),int):os.chmod(path,entry['mode'])
    if isinstance(entry.get('mtime_ns'),int):os.utime(path,ns=(path.stat().st_atime_ns,entry['mtime_ns']))

def merge_update_settings(default,current):
    """Add new defaults to the current file, retaining user values, unknown keys, comments and layout."""
    want=read_ini(default);have=read_ini(current);names=ini_names(default)
    additions={names[key]:value for key,value in want.items() if key not in have}
    current_names=ini_names(current)
    kept={current_names[key]:value for key,value in have.items() if want.get(key)!=value}
    return (patch_ini(current,additions) if additions else current),kept

def rollback_settings(original,applied,current):
    """Undo only update-owned settings; edits since the update win, including new user keys and comments."""
    old=read_ini(original);base=read_ini(applied);now=read_ini(current)
    if current==applied:return original
    names={**ini_names(original),**ini_names(applied),**ini_names(current)}
    changes={names[key]:old.get(key) for key in set(old)|set(base)
             if now.get(key)==base.get(key) and now.get(key)!=old.get(key)}
    return patch_ini(current,changes) if changes else current

def release_number(name):
    found=re.fullmatch(r'freefg-([0-9]+(?:\.[0-9]+){1,3})(-preview)?',str(name))
    if not found:return None
    numbers=tuple(int(part) for part in found[1].split('.'))
    # A preview precedes the final release with the same numeric version.
    return numbers+(0,)*(4-len(numbers))+(0 if found[2] else 1,)

def update_compatibility(record,manifest,core=True):
    """Legacy versions are imported explicitly; later releases negotiate the stored layout/configuration contract."""
    target=manifest.get('update_contract')
    if target is None:
        if manifest.get('name') not in LEGACY_UPDATE_TARGETS:return 'The selected package has no supported update contract; use its matching installer.'
        target=UPDATE_CONTRACT
    if target not in (UPDATE_CONTRACT,LEGACY_CONTRACT):return 'This package requires a different update format or integration layout; use a compatible installer.'
    source=record.get('update_contract')
    if source is not None and source not in (UPDATE_CONTRACT,LEGACY_CONTRACT):return 'This installation requires a different update format or integration layout; use a compatible installer.'
    old,new=release_number(record.get('package')),release_number(manifest.get('name'))
    if core and old is not None and new is not None and new<old:return 'The selected package is older than this installation. Use Rollback for a saved earlier release.'
    if source is None and record.get('package')!=manifest.get('name') and record.get('package') not in UPDATES_FROM:
        return str(record.get('package') or 'This installation')+' is not a release this build updates in place: use Restore, then Install.'
    return None

def component_state(record,manifest_hash=None,core_paths=None):
    """Game-local identities for independently updated components; settings remain owned by their existing records."""
    files={row['path']:row['after'] for row in record['files']}
    core={name:value for name,value in files.items() if value is not None and (core_paths is None or name in core_paths) and
          (name=='libxess_fg.dll' or (name.startswith('BC250-XeFG/') and name not in SETTINGS_FILES))}
    out={'core':{'package':record.get('package'),'files':core},
         'runtime':{'files':{name:files[name] for name in ('bc250_xefg_original.dll','libxell.dll') if name in files}},
         'integration':{'files':{name:files[name] for name in OPTI_PROXIES if name in files}}}
    if manifest_hash:out['core']['manifest_sha256']=manifest_hash
    upscaler=record.get('upscaler') or {}
    if upscaler.get('target') in files:
        out['upscaler']={'provider':upscaler.get('name'),'version':upscaler.get('version'),
                         'target':upscaler['target'],'sha256':files[upscaler['target']]}
    return out

def release_metadata(record):
    return json.loads(json.dumps({key:record[key] for key in RELEASE_FIELDS if key in record}))

def restore_release_metadata(record,generation):
    previous=generation.get('metadata_before')
    if previous is None:return
    if not isinstance(previous,dict) or set(previous)-set(RELEASE_FIELDS):raise ValueError('Invalid recovery component metadata')
    after=generation.get('metadata_after',{})
    fields=generation.get('metadata_fields',RELEASE_FIELDS)
    core_manifest=(record.get('components') or {}).get('core',{}).get('manifest_sha256')
    for key in fields:
        # Component choices made after an update belong to the user. File rollback already refuses if a changed
        # component's bytes no longer match, while a core-only rollback must leave a later provider switch intact.
        if key=='upscaler' and key in after and record.get(key)!=after[key]:continue
        if key=='ini_changes':
            old={(x['section'].lower(),x['key'].lower()):x for x in previous.get(key,[])}
            applied={(x['section'].lower(),x['key'].lower()):x for x in after.get(key,[])}
            now={(x['section'].lower(),x['key'].lower()):x for x in record.get(key,[])}
            for pair in set(old)|set(applied):
                if now.get(pair)==applied.get(pair):
                    if pair in old:now[pair]=old[pair]
                    else:now.pop(pair,None)
            record[key]=list(now.values());continue
        if key in previous:record[key]=previous[key]
        else:record.pop(key,None)
    if generation.get('core_updated',True):
        core_manifest=(previous.get('components') or {}).get('core',{}).get('manifest_sha256')
    record['components']=component_state(record,core_manifest)

def remember_prepared(package,folder):
    if folder is None:return
    try:hlx.remember(package,folder)
    except (OSError,ValueError) as error:print('Prepared HLX folder was not remembered: '+str(error))

def remember_installation(exe,record,home=None,strict=False):
    """The index is optional: an unavailable index never invalidates a completed game transaction."""
    try:freefg_library.register(exe,record,home)
    except (OSError,ValueError) as error:
        if strict:raise
        print('The game is installed; library registration needs attention: '+str(error))

@locked
def register_installation(exe):
    root=exe.parent.resolve();state=root/STATE
    record=json.loads(safe(root,STATE+'/state.json').read_text())
    if record.get('status')!='installed' or Path(record.get('game') or '').resolve()!=exe.resolve():
        raise ValueError('Choose the installed executable at its recorded location; moved installations need their launcher paths reconciled first')
    if record.get('pending_update'):raise ValueError('Recover the interrupted operation before registering this installation')
    validate_update_state(root,record)
    if not record.get('installation_id'):
        record['installation_id']=uuid.uuid4().hex;save_record(state,record)
    remember_installation(exe,record,strict=True)
    print('Registered '+str(exe)+' for Update all; its runtime and settings are unchanged.')

def integration_plan(root,record,pins,files,loader=None):
    """Qualified OptiScaler files and additive defaults, retaining the original installation ledger."""
    items={item['path']:item for item in record['files']}
    owned=[name for name in OPTI_PROXIES if name in items and items[name]['after'] is not None]
    accepted={pins['payload']['ProxyHash'],*pins['payload'].get('CompatibleProxyHashes',[])}
    if files.get('opti/OptiScaler.dll') is not None:accepted.add(digest(files['opti/OptiScaler.dll']))
    existing=[name for name in OPTI_PROXIES if file_digest(root,name) in accepted]
    available=list(dict.fromkeys([*owned,*existing]))
    owner=record.get('opti_owner') or (available[0] if len(available)==1 else None)
    if owner not in available:raise ValueError('OptiScaler bytes changed or its loader ownership is ambiguous; reconcile before updating')
    selected=loader or owner
    if selected not in OPTI_PROXIES:raise ValueError('Unsupported OptiScaler loader: '+str(selected))
    if selected!=owner and selected not in items and file_digest(root,selected) is not None:
        raise ValueError('The requested loader filename belongs to another file: '+selected+'; choose a free loader name')
    desired={};retired=[]
    custom=files.get('opti/OptiScaler.dll')
    expected=pins['payload']['Files'].get('OptiScaler.dll')
    if custom is None and expected!=pins['payload']['ProxyHash']:
        raise ValueError('OptiScaler proxy and dependency pins disagree')
    proxy=custom if custom is not None else Upstream('OptiScaler.dll',expected)
    wanted=digest(custom) if custom is not None else expected
    # Do not claim an existing external OptiScaler solely because it already matches. A real version migration
    # backs up and enrolls the accepted original immediately before replacing it.
    if selected in items or selected!=owner or file_digest(root,selected)!=wanted:desired[selected]=('integration',proxy)
    if selected!=owner:retired.append(owner)
    if record.get('fresh'):
        for name,value in pins['payload']['Files'].items():
            target=setup_target(name)
            if target in ('OptiScaler.ini','dxgi.dll') or target in {owner,selected,(record.get('upscaler') or {}).get('target'),(record.get('upscaler') or {}).get('legacy_target')}:
                continue
            # These SDK copies were deliberately removed by the proxy layout; do not put them back.
            if target in ('OptiScaler/libxess_fg.dll','OptiScaler/libxell.dll'):continue
            desired[target]=('integration',Upstream(name,value))
    metadata={'opti_owner':selected}
    edits={}
    if 'opti/OptiScaler.ini' in files:
        path=safe(root,'OptiScaler.ini');current=path.read_bytes()
        merged,_=merge_update_settings(files['opti/OptiScaler.ini'],current)
        if merged!=current:
            edits['OptiScaler.ini']=merged
            before=read_ini(current);after=read_ini(merged);names=ini_names(merged)
            changes=json.loads(json.dumps(record.get('ini_changes') or []))
            present={(row['section'].lower(),row['key'].lower()) for row in changes}
            for pair,value in after.items():
                if pair not in before and pair not in present:
                    section,key=names[pair];changes.append(dict(section=section,key=key,value=value))
            metadata['ini_changes']=changes
    return dict(owner=selected,previous_owner=owner,desired=desired,retired=retired,edits=edits,metadata=metadata)


def custom_hlx_supported(files,pins):
    return bool(pins.get('hlx') and files.get('opti/OptiScaler.dll'))


def provider_plan(package,root,record,pins,files,prepared=None,selection=None):
    """One selected provider, its files and configuration. Legacy HelixSR advances to its HLX DLSS successor."""
    current=dict(record.get('upscaler') or {})
    name=selection or current.get('name')
    modern=bool(pins.get('hlx'))
    if name=='helixsr' and modern:name='hlx-dlss'
    legacy=current.get('legacy_target') or current.get('target')
    if not legacy:raise ValueError('The installation has no recorded upscaler target')
    library=current.get('library_root') or str(Path(legacy).parent)
    if name in hlx.NAMES:
        plan=hlx.layout(package,name,library,prepared,current,root)
        plan['metadata']['legacy_target']=legacy
        # The standard FFX slot becomes AMD's provider when legacy HelixSR moves to its own custom slot.
        # Its former bytes remain in the generation and original-backup ledger for exact rollback/Restore.
        amd=upscaler_updates.plan(package,dict(record,upscaler=dict(name='fsr4',target=legacy)),pins,files,installed=safe(root,legacy))
        if amd.get('deferred'):raise ValueError(amd['deferred'])
        plan['files'][legacy]=amd['data'] if amd['data'] is not None else Upstream(amd['dependency'],amd['sha256'])
        if current.get('name')=='helixsr':
            plan['metadata']['legacy_helixsr']=current
        elif current.get('legacy_helixsr'):
            plan['metadata']['legacy_helixsr']=current['legacy_helixsr']
        ini=plan['metadata'].get('ini')
        if ini:
            source=safe(root,ini)
            old=safe(root,current['ini']) if current.get('ini') else None
            value=source.read_bytes() if source.is_file() else old.read_bytes() if old and old.is_file() else None
            plan['files'][ini]=helixsr.ini_bytes(value)
            plan['config_paths']=[ini]
        return plan
    selected=dict(record,upscaler=dict(name=name,target=legacy)) if selection or current.get('name') in hlx.NAMES else record
    plan=upscaler_updates.plan(package,selected,pins,files,prepared,safe(root,legacy))
    if plan.get('deferred'):return plan
    plan['files']={plan['target']:plan['data'] if plan['data'] is not None else Upstream(plan['dependency'],plan['sha256'])}
    plan['ini_changes']={('Upscalers','Dx12Upscaler'):'ffx',('FSR','UpscalerIndex'):'0'} if selection else {}
    if current.get('legacy_helixsr'):plan['metadata']['legacy_helixsr']=current['legacy_helixsr']
    return plan


def own_ini_changes(record,changes):
    rows=json.loads(json.dumps(record.get('ini_changes') or []))
    index={(row['section'].lower(),row['key'].lower()):row for row in rows}
    for (section,key),value in changes.items():
        pair=(section.lower(),key.lower())
        if pair in index:index[pair]['value']=value
        else:rows.append(dict(section=section,key=key,value=value))
    return rows


def recipe_migration(package,root,record,ini):
    """Explicitly refresh a tested input/launcher recipe, never silently rewrite game quality or save files."""
    found=recipe_for(package,Path(record['game']))
    verified=found[1] if found else None
    if not verified or verified.get('evidence') not in ('gameplay','generates'):
        raise ValueError('No gameplay-qualified recipe refresh is available for this game; its compatibility check names its current limitations')
    rm=found[0];route=verified['route'];fg=verified.get('fg_input') or 'upscaler'
    changes={('FrameGen','Enabled'):'true' if route=='opti' else 'false',
             ('fakenvapi','UseFakenvapi'):'true' if route=='opti' else 'false'}
    if route=='opti':changes.update({('FrameGen','FGInput'):fg,('FrameGen','FGOutput'):'xefg'})
    parsed=read_ini(ini)
    changes.update(rm.ini_changes(verified,found[4],parsed,fg,fg,route,(record.get('upscaler') or {}).get('name')))
    if route=='opti' and fg in ('fsrfg','fsrfg30'):changes[('FrameGen','DisableHudless')]='true'
    if route=='opti' and fg in ('upscaler','fsrfg','fsrfg30') and parsed.get(('fakenvapi','forcereflex'),'auto').strip().lower() in ('','auto'):
        changes[('fakenvapi','ForceReflex')]='2'
    old_args=set((record.get('recipe') or {}).get('launch_args') or [])
    args=list(rm.launch_args(verified,found[2]))
    args.extend(x for x in record.get('launch_args',[]) if x not in old_args and x not in args)
    recipe=dict(title=verified['title'],status='verified-bc250',wiki=[w['title'] for w in found[2]],
                launch_args=list(rm.launch_args(verified,found[2])),evidence=verified.get('evidence'),observed=verified.get('observed'))
    if verified.get('upscaler_ini'):recipe['upscaler_ini']=verified['upscaler_ini']
    # Original game-setting ownership stays available for Restore. Obsolete pending settings are never reasserted.
    settings=json.loads(json.dumps(record.get('game_settings') or []))
    for row in settings:
        if not any(all(row.get(k)==entry.get(k) for k in ('file','format','section','values')) for entry in verified.get('game_settings',[])):
            row['active']=False
    metadata=dict(route=route,fg_input=fg,launch_args=args,recipe=recipe,game_settings=settings,
                  ini_changes=own_ini_changes(record,changes))
    notes=['Recipe refresh: '+verified['title']+'; '+route+'/'+fg+'. Game settings and saves are not written.']
    notes+=['After update: '+step for step in verified.get('manual_steps',[])]
    if verified.get('note'):notes.append(verified['note'])
    if verified.get('game_settings'):notes.append('Review the game’s graphics settings for this recipe; this refresh changes only the integration and launcher.')
    return patch_ini(ini,changes),metadata,notes



def wiki_settings_plan(package, exe):
    """Read-only, JSON-serializable INI proposals for a managed game (API format 1).

    The GUI can display rows directly, initially unselected, and pass row IDs to
    apply_wiki_settings. The digest binds the choice to the current context and
    values. Runtime files, graphics quality files and saves are not changed here.
    """
    import compat, recipes
    package, exe = Path(package), Path(exe)
    root = exe.parent.resolve()
    record = json.loads(safe(root, STATE + '/state.json').read_text())
    if record.get('status') != 'installed' or record.get('pending_update'):
        raise ValueError('Finish installation/recovery before reviewing wiki settings')
    data = recipes.load(package / 'recipes/recipes.json')
    if not data:
        raise ValueError('This package has no compatibility catalogue')
    ini = safe(root, 'OptiScaler.ini').read_bytes()
    names, parsed = ini_names(ini), read_ini(ini)
    ids = recipes.identity(exe, record.get('launchers', []))
    verified, _, _, _ = recipes.match(data, ids)
    provider = (record.get('upscaler') or {}).get('name', 'fsr4')
    upscaler = 'helixsr' if provider in ('hlx-dlss', 'helixsr') else 'fsr4'
    fg_input = 'native-xefg' if record.get('route') == 'native' else parsed.get(('framegen', 'fginput'), record.get('fg_input', 'upscaler'))
    ctx = dict(compat.DEFAULT_CONTEXT, fg_input=fg_input, upscaler=upscaler,
               fg_output=parsed.get(('framegen', 'fgoutput'), 'xefg'),
               proxy=record.get('opti_owner', 'dxgi.dll'))
    # Auto in the INI means the integration's selected value for these fields.
    if ctx['fg_input'] == 'auto': ctx['fg_input'] = record.get('fg_input', 'upscaler')
    if ctx['fg_output'] == 'auto': ctx['fg_output'] = 'xefg'
    protected = dict((verified or {}).get('ini') or {})
    protected.update((verified or {}).get('upscaler_ini', {}).get('helixsr' if provider == 'hlx-dlss' else provider, {}))
    required = {str(item.get('when', {}).get('required_file')) for row in data.get('wiki', []) for item in row.get('ini', []) if item.get('when', {}).get('required_file')}
    ctx['files'] = sorted(name for name in required if safe(root, name).is_file())
    if record.get('route') == 'native':ctx['fg_output'] = 'xefg'
    supported = ['.'.join(key) for key in names.values()]
    opti_commit = None
    owner = record.get('opti_owner')
    owner_hash = file_digest(root, owner) if owner else None
    for commit, build in data.get('optiscaler_builds', {}).items():
        if owner_hash and build['dll_sha256'] == owner_hash:
            opti_commit, supported = commit, build['keys']
            break
    plan = compat.wiki_plan(data, ids, ctx, supported_keys=supported,
                            current={'.'.join(key): value for key, value in parsed.items()}, recipe_ini=protected,
                            optiscaler_commit=opti_commit)
    return plan


def _wiki_update_plan(package, root, record, selected, confirmed, expected):
    import compat
    if record.get('addon_entry') != PROXY_ENTRY or record.get('runtime') != 'xemfg':
        raise ValueError('Wiki INI transactions require a current FreeFG proxy installation')
    if record.get('update_contract', LEGACY_CONTRACT) not in (UPDATE_CONTRACT, LEGACY_CONTRACT):
        raise ValueError('Unsupported installation contract; use its matching installer')
    plan = wiki_settings_plan(package, Path(record.get('game') or root / 'unknown.exe'))
    if expected != plan['digest']:
        raise ValueError('Wiki settings preview changed; review the current plan before applying')
    choice = compat.select_wiki_settings(plan, selected, confirmed)
    changes = {tuple(key.split('.', 1)): value for key, value in choice['settings'].items()}
    before = safe(root, 'OptiScaler.ini').read_bytes()
    after = patch_ini(before, changes)
    index = next((n for n, item in enumerate(record['files']) if item['path'] == 'OptiScaler.ini'), None)
    if index is None:
        raise ValueError('This installation does not own OptiScaler.ini')
    item = record['files'][index]
    action = dict(path='OptiScaler.ini', index=index, component='integration', kind='merge',
                  old=item['after'], observed=digest(before), new=digest(after), data=after,
                  mode=stat.S_IMODE(safe(root, 'OptiScaler.ini').stat().st_mode), kept={}, setting_changes=[dict(section=section, key=key,
                      before=read_ini(before).get((section.lower(), key.lower())), after=value)
                      for (section, key), value in changes.items()])
    return dict(status='update' if before != after else 'current', reason='Selected wiki values are already set.',
                operation='wiki-settings', actions=[action] if before != after else [],
                notes=['Selected wiki settings applied; runtime, provider and game configuration stay as installed.'],
                source=record['package'], target=record['package'], max_factor=record.get('max_factor', 2), pins=None,
                observed={'OptiScaler.ini': digest(before)}, component='integration', core=False, deferred=[],
                metadata=dict(ini_changes=own_ini_changes(record, changes), wiki_settings=choice),
                launcher_ops=[], config_paths={'OptiScaler.ini'}, core_paths=None)


def apply_wiki_settings(exe, selected, confirmed=(), *, package=None, expected=None):
    """Apply selected prefilled INI values through the normal recoverable generation.

    expected is the digest of wiki_settings_plan displayed to the player.
    confirmed contains only selected row IDs whose displayed conditions/match
    were explicitly confirmed. Rollback/Restore retain their normal merge rules.
    """
    if not expected:
        raise ValueError('Review wiki_settings_plan and supply its digest before applying')
    return update(exe, package=package, _planner=lambda p, r, record:
                  _wiki_update_plan(p, r, record, selected, confirmed, expected))


def update_plan(package,root,record,component='all',helixsr_dir=None,loader=None,upscaler=None,refresh_recipe=False):
    """What install.py update would change in the installation at root, read only: dict(status, reason, actions, notes,
    source, target, max_factor, pins). status: 'update' (apply actions; none when only the record names a new release),
    'current', 'pinned', 'interrupted' (an update or rollback stopped part way: update and rollback resolve it first) or
    'blocked'; reason says why and what to do instead. An action: path, index in record['files'] (None: a file new in this
    release), component (COMPONENTS), kind ('replace'; 'add': new in this release; 'merge': a settings file with the user's
    values kept in this release's file; 'retire': a file this release no longer has, which goes back to what was there
    before installation), old (the record's SHA-256, None for none), new, data (bytes, None to delete, or an Upstream the
    update fetches), mode, kept (merge: the user's values kept)."""
    if component not in ('all','core','upscaler'):raise ValueError('Choose component all, core or upscaler')
    core=component in ('all','core')
    manifest=json.loads((package/'manifest.json').read_text());target=manifest.get('name') if core else record.get('package')
    out=dict(status='blocked',reason=None,actions=[],notes=[],source=record.get('package'),target=target,
             max_factor=manifest.get('max_factor',2) if core else record.get('max_factor',2),pins=None,observed={},
             component=component,core=core,deferred=[],metadata={},launcher_ops=[],config_paths=set(SETTINGS_FILES))
    def stop(status,reason):
        out.update(status=status,reason=reason);return out
    if record.get('status')=='restored':return stop('blocked','Restored: install this build with Install.')
    if record.get('status')!='installed':return stop('blocked','The installation was interrupted after saving backups: use Restore, then Install again.')
    pending=record.get('pending_update')
    if pending and not pending.get('generation'):return stop('blocked','An update by an earlier build was interrupted: use Restore, then Install.')
    if pending:return stop('interrupted','An '+pending.get('kind','update')+' was interrupted: install.py update or install.py rollback resolves it first.')
    if record.get('runtime')!='xemfg' or record.get('addon_entry')!=PROXY_ENTRY:
        return stop('blocked','Installed by an earlier add-on build: use Restore, then Install this build.')
    if manifest.get('runtime')!='xemfg' or manifest.get('launcher_setup')!='automatic' or manifest.get('addon_entry')!=PROXY_ENTRY:
        return stop('blocked','This package is not an enabler-free frame-generation package with automatic launcher setup; use its own installer.')
    if record.get('update_pin'):
        return stop('pinned','Pinned to '+str(record['update_pin'].get('package'))+': update leaves it as it is (install.py unpin to update it).')
    reason=update_compatibility(record,manifest,core)
    if reason:return stop('blocked',reason)
    validate_update_state(root,record)
    files=payload(package)
    if 'dependencies.json' not in files:raise ValueError('Package lacks its pinned dependency list (dependencies.json)')
    pins=out['pins']=check_pins(json.loads(files['dependencies.json']));runtime=pins['runtime']
    if 'ProxyPackage' not in runtime:raise ValueError('install.py and dependencies.json come from different builds (no proxy runtime layout); use one package’s files')
    layout=runtime['ProxyPackage']
    for name,source in layout.items():
        if name in files and digest(files[name])!=runtime['Files'][source]:raise ValueError('Package file differs from its pinned upstream download: '+name)
    for path in OPTI_PROXIES:
        if (root/path).exists():out['observed'][path]=file_digest(root,path)
    try:integration=integration_plan(root,record,pins,files,loader)
    except ValueError as error:return stop('blocked',str(error))
    policy_record=record
    if refresh_recipe:
        try:
            ini=integration['edits'].get('OptiScaler.ini',safe(root,'OptiScaler.ini').read_bytes())
            base=dict(record,ini_changes=integration['metadata'].get('ini_changes',record.get('ini_changes',[])))
            changed,metadata,notes=recipe_migration(package,root,base,ini)
        except ValueError as error:return stop('blocked',str(error))
        integration['edits']['OptiScaler.ini']=changed;integration['metadata'].update(metadata);out['notes']+=notes
        policy_record=dict(record,**metadata)
    migrations=launcher_migrations.plan(record,root,integration['owner'],
                 route=policy_record.get('route'),args=policy_record.get('launch_args'),
                 extra=(record.get('compat') or {}).get('extra_env'),
                 cache=root/STATE/VKD3D_CACHE if record.get('vkd3d_cache')==VKD3D_CACHE else None,
                 previous_owner=integration['previous_owner'])
    out['launcher_ops']=migrations['operations']
    if migrations['records']!=record.get('launchers',[]):out['metadata']['launchers']=migrations['records']
    if migrations['operations']:out['metadata']['launcher_policy_keys']=migrations['policy_keys']
    out['metadata'].update({key:value for key,value in integration['metadata'].items() if record.get(key)!=value})
    edits=integration['edits']
    # What the package places, as install() places it: its own payload files, and the pinned runtime (the package's copy
    # when it carries one, checked above).
    desired={name.removeprefix('payload/'):('addon',files[name]) for name in files if core and name.startswith('payload/') and name not in layout}
    for name,source in layout.items():
        if core and name.startswith('payload/'):
            desired[name.removeprefix('payload/')]=('runtime',files.get(name) or Upstream(source,runtime['Files'][source]))
    desired.update(integration['desired'])
    desired.update({path:('integration',data) for path,data in edits.items()})
    out['config_paths'].update(edits)
    if component in ('all','upscaler') or upscaler:
        current_provider=record.get('upscaler') or {}
        current_paths=current_provider.get('files') or [current_provider.get('target')]
        owned={row['path']:row['after'] for row in record['files']}
        for path in filter(None,current_paths):
            now=file_digest(root,path);out['observed'][path]=now
            if path not in owned or now!=owned[path]:return stop('blocked','Selected provider changed since installation: '+path+'; reconcile before updating')
        try:provider=provider_plan(package,root,record,pins,files,helixsr_dir,upscaler)
        except ValueError as error:provider={'deferred':str(error)}
        if provider.get('deferred'):
            out['deferred'].append('upscaler');out['notes'].append(provider['deferred'])
            if upscaler or not core:return stop('deferred',provider['deferred'])
        else:
            for path,data in provider['files'].items():
                # New providers live in their own folders; do not take over another mod's files.
                if path not in {item['path'] for item in record['files']} and safe(root,path).exists():
                    return stop('blocked','Provider target already exists outside this installation: '+path)
                desired[path]=(provider['component'],data)
            log=provider['metadata'].get('log')
            if log and safe(root,log).exists() and not any(Path(row['path']).parent==Path(log).parent for row in record['files']):
                return stop('blocked','Provider log already exists outside this installation: '+log)
            out['config_paths'].update(provider.get('config_paths',[]))
            changes=dict(provider.get('ini_changes') or {})
            recipe_name='helixsr' if provider['metadata']['name']=='hlx-dlss' else provider['metadata']['name']
            changes.update(upscaler_recipe_changes(package,Path(record['game']),record,recipe_name))
            if changes:
                data=edits.get('OptiScaler.ini',safe(root,'OptiScaler.ini').read_bytes())
                changed=patch_ini(data,changes)
                desired['OptiScaler.ini']=('integration',changed);edits['OptiScaler.ini']=changed
                out['config_paths'].add('OptiScaler.ini')
                base=dict(record,ini_changes=out['metadata'].get('ini_changes',record.get('ini_changes',[])))
                owned_changes=own_ini_changes(base,changes)
                if owned_changes!=record.get('ini_changes',[]):out['metadata']['ini_changes']=owned_changes
            recipe=recipe_for(package,Path(record['game']))
            rules=((recipe[1] or {}).get('upscaler_ini',{}) if recipe else record.get('recipe',{}).get('upscaler_ini',{}))
            proposed=read_ini(edits.get('OptiScaler.ini',safe(root,'OptiScaler.ini').read_bytes()))
            for key,wanted in rules.get(recipe_name,{}).items():
                section,name=key.split('.',1);actual=proposed.get((section.lower(),name.lower()),'auto')
                if actual.strip().lower()!=str(wanted).strip().lower():
                    out['notes'].append('Recipe recommends '+key+'='+str(wanted)+'; your explicit '+actual+' is preserved. Review the game-specific compatibility note before playing.')
            if provider['metadata']!=(record.get('upscaler') or {}):out['metadata']['upscaler']=provider['metadata']
    items={item['path']:(i,item) for i,item in enumerate(record['files'])}
    actions=[];conflicts=[]
    for path,(component,data) in sorted(desired.items()):
        new=data.sha256 if isinstance(data,Upstream) else digest(data)
        index,item=items.get(path,(None,None));now=file_digest(root,path)
        out['observed'][path]=now
        action=dict(path=path,index=index,component=component,old=item['after'] if item else now,new=new,data=data,
                    observed=now,mode=stat.S_IMODE(safe(root,path).stat().st_mode) if now is not None else item['mode'] if item else 0o644)
        if item is None:actions.append(dict(action,kind='add'));continue
        if path in out['config_paths'] and now is None and item['after'] is None:
            actions.append(dict(action,kind='replace'));continue
        if path in out['config_paths']:
            # This release's file with the user's values: every value that differs from its default, as Install carries
            # them across Restore (the installed file may itself hold values an earlier Install carried, or configure's).
            if now is None:return stop('blocked',path+' is missing: repair the settings before updating; no defaults were written.')
            try:
                merged,kept=(data,{}) if path in edits else merge_update_settings(data,safe(root,path).read_bytes())
            except (UnicodeDecodeError,ValueError,configparser.Error) as error:
                return stop('blocked',path+' could not be read ('+str(error)+'): repair the settings before updating; no defaults were written.')
            if digest(merged)!=now:
                before_values=read_ini(safe(root,path).read_bytes());after_values=read_ini(merged)
                keys=sorted(set(before_values)|set(after_values),key=lambda pair:(pair not in before_values,pair))
                differences=[dict(section=k[0],key=k[1],before=before_values.get(k),after=after_values.get(k))
                             for k in keys if before_values.get(k)!=after_values.get(k)]
                actions.append(dict(action,kind='merge',data=merged,new=digest(merged),kept=kept,setting_changes=differences))
            continue
        if now!=item['after']:
            # The add-on and its runtime only work as one set; the upscaler DLL is another component, left as it is.
            if component in ('fsr4','helixsr','hlx-dlss','hlx-fsr4'):
                return stop('blocked','Selected provider changed since installation: '+path+'; reconcile before updating')
            else:conflicts.append(path)
            continue
        if item['after']==new:continue
        actions.append(dict(action,kind='replace'))
    for index,item in enumerate(record['files']):
        path=item['path']
        integration_retired=path in integration['retired']
        if (not core and not integration_retired) or path in desired or item['after'] is None or item['after']==item['before'] or not (integration_retired or path.startswith('BC250-XeFG/') or path in ADDON_FILES):continue
        out['observed'][path]=file_digest(root,path)
        if out['observed'][path]!=item['after']:conflicts.append(path);continue
        original=None
        if item['before'] is not None:
            original=safe(root,STATE+'/backups/'+str(index)).read_bytes()
            if digest(original)!=item['before']:raise ValueError('Backup checksum mismatch: '+path)
        actions.append(dict(path=path,index=index,component='integration' if integration_retired else 'addon',kind='retire',old=item['after'],new=item['before'],data=original,
                            observed=item['after'],mode=stat.S_IMODE(safe(root,path).stat().st_mode)))
    if conflicts:
        return stop('blocked','Changed since installation (a game update or another tool): '+', '.join(conflicts[:3])+(' and '+str(len(conflicts)-3)+' more' if len(conflicts)>3 else '')+
                    '. Use Restore, then Install (Restore keeps the changed files as the game’s own).')
    out['actions']=actions
    out['core_paths']=set(desired) if core else None
    if not core and not actions and not out['metadata'] and out['deferred']:
        return stop('deferred','No changes applied: '+out['notes'][0])
    if not actions and not out['metadata'] and not out['launcher_ops'] and out['source']==target and record.get('update_contract')==UPDATE_CONTRACT:
        if out['deferred']:return stop('deferred','No changes applied: '+out['notes'][0])
        return stop('current','Up to date ('+str(target)+').')
    out['status']='update';return out

def plan_lines(plan):
    """What an update plan changes, one line each."""
    if plan['status']!='update':return [plan['reason']]
    lines=['Apply selected wiki INI settings:' if plan.get('operation')=='wiki-settings' else
           'Update '+str(plan['source'])+' → '+str(plan['target'])+':' if plan.get('core',True) else
           'Update selected upscaler; FreeFG core stays '+str(plan['source'])+':']
    for component,label in COMPONENTS.items():
        counts=collections.Counter(a['kind'] for a in plan['actions'] if a['component']==component and a['kind']!='merge')
        words=[str(counts[kind])+' '+what for kind,what in (('replace','replaced'),('add','new'),('retire','no longer used')) if counts[kind]]
        if words:lines.append('  '+label+': '+', '.join(words)+' file'+('s' if sum(counts.values())>1 else ''))
    for action in plan['actions']:
        if action['kind']=='merge':
            lines.append('  '+action['path']+': update owned settings and add missing defaults')
            changes=action.get('setting_changes',[])
            for value in changes[:12]:
                lines.append('    '+value['section']+'.'+value['key']+': '+str(value['before'] if value['before'] is not None else '(unset)')+' → '+str(value['after'] if value['after'] is not None else '(unset)'))
            if len(changes)>12:lines.append('    and '+str(len(changes)-12)+' other new defaults/settings')
    if not plan['actions']:lines.append('  no file changes (update the release/component record)')
    downloads=sorted({a['data'].name for a in plan['actions'] if isinstance(a['data'],Upstream)})
    if downloads:lines.append('  downloads (pinned upstream files): '+', '.join(downloads))
    if plan.get('launcher_ops'):lines.append('  launcher entries migrated: '+', '.join(op['target']['launcher']+'/'+str(op['target'].get('id','game')) for op in plan['launcher_ops']))
    if plan.get('metadata',{}).get('opti_owner'):lines.append('  OptiScaler loader: '+plan['metadata']['opti_owner'])
    if plan.get('metadata',{}).get('upscaler'):lines.append('  '+upscaler_line(plan['metadata']['upscaler']))
    lines.append('  original-file backups and user settings are retained')
    return lines+plan['notes']

def load_generation(state,generation):
    """A saved generation's description (generation.json), or None when its folder is missing or not readable."""
    if not isinstance(generation,str) or not re.fullmatch(r'[0-9TZ]+-[0-9a-f]{8}',generation):
        raise ValueError('Invalid recovery generation identifier')
    try:description=json.loads(safe(state,GENERATIONS+'/'+generation+'/generation.json').read_text())
    except FileNotFoundError:return None
    except (OSError,ValueError) as error:raise ValueError('Recovery generation cannot be read: '+str(error)) from error
    if not isinstance(description,dict) or description.get('id')!=generation or not isinstance(description.get('files'),list):
        raise ValueError('Invalid recovery generation description')
    return description

def validate_generation(record,generation):
    """Check every saved entry against its owned record before any recovery writes occur."""
    for name in ('metadata_before','metadata_after'):
        metadata=generation.get(name)
        if metadata is not None and (not isinstance(metadata,dict) or set(metadata)-set(RELEASE_FIELDS)):
            raise ValueError('Invalid recovery component metadata')
        if metadata is not None:
            for key in ('upscaler','components','update_contract'):
                if key in metadata and not isinstance(metadata[key],dict):raise ValueError('Invalid recovery component metadata: '+key)
            components=metadata.get('components',{})
            if any(not isinstance(value,dict) for value in components.values()):raise ValueError('Invalid recovery component metadata entries')
    fields=generation.get('metadata_fields')
    if fields is not None and (not isinstance(fields,list) or any(key not in RELEASE_FIELDS for key in fields)):
        raise ValueError('Invalid recovery component metadata fields')
    for name in ('from','to'):
        part=generation.get(name)
        if not isinstance(part,dict) or not isinstance(part.get('package'),str):raise ValueError('Invalid recovery release metadata')
        if part.get('max_factor') is not None and part['max_factor'] not in (2,3,4):raise ValueError('Invalid recovery factor metadata')
    seen=set()
    for entry in generation['files']:
        index=entry.get('index');path=entry.get('path')
        if not isinstance(index,int) or isinstance(index,bool) or not 0<=index<len(record['files']):
            raise ValueError('Invalid recovery generation file index')
        if not isinstance(path,str) or path in seen or record['files'][index]['path']!=path:
            raise ValueError('Recovery generation does not match the installation record')
        seen.add(path)
        if entry.get('saved') is not None and not re.fullmatch(r'files/[0-9]+',str(entry['saved'])):
            raise ValueError('Invalid saved generation path')
        if entry.get('applied') is not None and not re.fullmatch(r'applied/[0-9]+',str(entry['applied'])):
            raise ValueError('Invalid applied generation path')
        for key in ('old','new','saved_sha256'):
            value=entry.get(key)
            if value is not None and (not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value)):
                raise ValueError('Invalid recovery generation checksum')
        if (entry.get('saved') is None)!=(entry.get('saved_sha256') is None):raise ValueError('Incomplete saved generation file')
        if 'mode' in entry and (not isinstance(entry['mode'],int) or not 0<=entry['mode']<=0o7777):
            raise ValueError('Invalid recovery generation mode')

def saved_bytes(state,generation,entry):
    """The bytes a generation saved for one of its files (None: there was no file), checked against their digest."""
    if entry['saved'] is None:return None
    data=safe(state,GENERATIONS+'/'+generation['id']+'/'+entry['saved']).read_bytes()
    if digest(data)!=entry['saved_sha256']:raise ValueError('Saved file checksum mismatch: '+entry['path'])
    return data

def applied_bytes(state,generation,entry):
    if not entry.get('applied'):raise ValueError('Recovery generation lacks the applied settings needed to preserve later edits')
    data=safe(state,GENERATIONS+'/'+generation['id']+'/'+entry['applied']).read_bytes()
    if digest(data)!=entry['new']:raise ValueError('Applied settings checksum mismatch: '+entry['path'])
    return data

def validate_external_generation(root,record,generation):
    operations=generation.get('launcher_ops') or []
    entries=generation.get('external_files') or []
    known={row['path'] for row in record.get('launchers') or []}
    known|={row['path'] for row in (generation.get('metadata_before') or {}).get('launchers',[])}
    paths={op['target']['path'] for op in operations}
    if paths!={entry.get('path') for entry in entries} or len(entries)!=len(paths) or not paths<=known:
        raise ValueError('Recovery launcher files do not match the installation record')
    snapshots={}
    for entry in entries:
        if not re.fullmatch(r'external/[0-9]+',str(entry.get('saved'))):raise ValueError('Invalid saved launcher path')
        path=Path(entry['path'])
        if not path.is_absolute() or path.is_symlink():raise ValueError('Invalid launcher recovery target')
        data=safe(root/STATE,GENERATIONS+'/'+generation['id']+'/'+entry['saved']).read_bytes()
        if digest(data)!=entry.get('saved_sha256'):raise ValueError('Saved launcher checksum mismatch: '+str(path))
        snapshots[str(path)]=data
    for path,rows in launcher_migrations.grouped(operations).items():
        import launcher_config
        data=snapshots[path]
        for row in rows:
            if row['target'].get('launcher') not in ('steam','heroic','lutris'):raise ValueError('Unknown recovery launcher')
            current=launcher_config.fields(dict(row['target'],before=row['before']),data)
            if current!=row['before']:raise ValueError('Saved launcher fields differ from their recovery plan')
            data=launcher_config.patch(row['target'],data,row['after'])
        entry=next(row for row in entries if row['path']==path)
        if digest(data)!=entry.get('applied_sha256'):raise ValueError('Saved launcher migration is inconsistent')
    return snapshots

def restore_external_generation(root,record,generation):
    """Undo owned entry changes, restoring exact file layout/metadata only when no other edits would be lost."""
    snapshots=validate_external_generation(root,record,generation)
    operations=generation.get('launcher_ops') or []
    launcher_migrations.apply(operations,write,reverse=True)
    import launcher_config
    for entry in generation.get('external_files') or []:
        path=Path(entry['path']);data=path.read_bytes();original=snapshots[str(path)]
        row=next(op['target'] for op in operations if op['target']['path']==str(path))
        if data==original or launcher_config.same_settings(row,data,original):
            if data!=original:write(path,original,entry['mode'])
            restore_generation_metadata(path,entry)
        sync_folder(path.parent)

def forget_folders(root,record,folders):
    """Folders an update created that its undoing left empty: removed, and no longer named in the record."""
    created=record.get('created_dirs') or []
    for relative in folders:
        folder=created_folder(root,relative)
        if folder is not None:
            with contextlib.suppress(OSError):folder.rmdir()
        if created_folder(root,relative) is None and relative in created:created.remove(relative)

def reset_vkd3d_cache(state,record,paths):
    """Empty the installation's vkd3d-proton cache when paths (files an update or rollback changed) include the shader
    profile or the layer: a new installation starts with an empty cache, and a changed profile is qualified so. Returns
    whether it was emptied."""
    cache=state/VKD3D_CACHE
    if record.get('vkd3d_cache')!=VKD3D_CACHE or not cache.is_dir() or cache.is_symlink():return False
    if not any(path.startswith(('BC250-XeFG/shaders/','BC250-XeFG/layer/')) for path in paths):return False
    for child in list(cache.iterdir()):
        if child.is_dir() and not child.is_symlink():shutil.rmtree(child)
        else:child.unlink()
    return True

def prune_generations(state,record):
    """Only the newest GENERATIONS_KEPT generations the record names stay; every other generation folder is deleted (also
    one an interrupted update left half written). The record is saved first."""
    history=record.get('generations') or []
    del history[:max(0,len(history)-GENERATIONS_KEPT)]
    save_record(state,record);sync_folder(state)
    keep={item['id'] for item in history};folder=state/GENERATIONS
    for child in sorted(folder.iterdir()) if folder.is_dir() and not folder.is_symlink() else []:
        if child.name not in keep:
            if child.is_dir() and not child.is_symlink():shutil.rmtree(child)
            else:child.unlink()

def settle_interrupted(root,record):
    """Undo an interrupted update or finish an interrupted rollback before accepting a new operation.
    Missing or inconsistent recovery data leaves the journal intact. Returns (operation recovered, messages)."""
    state=root/STATE;pending=record['pending_update'];generation=load_generation(state,pending['generation'])
    if generation is None:raise ValueError('Recovery generation is missing: pending journal and game files were kept. Restore its saved files before recovery.')
    validate_generation(record,generation)
    validate_external_generation(root,record,generation)
    launcher_migrations.prepare_apply(generation.get('launcher_ops') or [],reverse=True)
    if set(pending.get('files') or {})!={entry['path'] for entry in generation['files']}:
        raise ValueError('Recovery generation does not match the pending file set')
    if pending.get('kind','update')=='update':
        actions=[]
        for entry in generation['files']:
            change=pending['files'].get(entry['path'])
            if change is None:raise ValueError('Recovery generation does not match the pending update')
            item=record['files'][entry['index']];now=file_digest(root,entry['path'])
            data=saved_bytes(state,generation,entry)
            if now not in (change['after'],entry['saved_sha256']):raise ValueError(entry['path']+' changed during the interrupted update: use Restore.')
            actions.append((entry,change,item,now,data))
        touched=set()
        for entry,change,item,now,data in actions:
            target=safe(root,entry['path'])
            if now!=entry['saved_sha256']:
                if data is None:target.unlink()
                else:write(target,data,entry.get('mode',item['mode']))
            if data is not None:restore_generation_metadata(target,entry)
            touched.add(target.parent)
            item['after']=change['before']
        for parent in touched:
            if parent.is_dir():sync_folder(parent)
        restore_external_generation(root,record,generation)
        restore_release_metadata(record,generation)
        record.pop('pending_update');forget_folders(root,record,generation.get('created_dirs') or []);save_record(state,record)
        shutil.rmtree(state/GENERATIONS/generation['id'])
        sync_folder(state/GENERATIONS)
        return True,['An update to '+str(generation['to']['package'])+' was interrupted: undone, back to '+str(generation['from']['package'])+'.']
    if pending.get('kind')!='rollback':raise ValueError('Unknown pending update operation')
    rollback_generation(root,record,generation)
    return True,['An interrupted rollback was completed: back to '+str(generation['from']['package'])+'.']

@locked
@launcher_locked
def update(exe,package=None,dependency_dir=None,component='all',helixsr_dir=None,loader=None,upscaler=None,refresh_recipe=False,_planner=None):
    """install.py update: replace the installed game's frame generation with this package's in place (update_plan says
    what changes), recoverably and without Restore. Returns the plan's status ('update' once applied)."""
    package=Path(package or Path(__file__).resolve().parent)
    root=exe.parent.resolve();idle(root);state=root/STATE
    if state.is_symlink():raise ValueError('Installation state is a symlink')
    raw_record=safe(root,STATE+'/state.json').read_bytes();record=json.loads(raw_record);expected_record=digest(raw_record)
    validate_update_state(root,record)
    if (record.get('pending_update') or {}).get('generation'):
        for line in settle_interrupted(root,record)[1]:print(line)
        expected_record=file_digest(state,'state.json')
    plan=_planner(package,root,record) if _planner else update_plan(package,root,record,component,helixsr_dir,loader,upscaler,refresh_recipe)
    if plan['status']!='update':
        if plan['status'] in ('current','pinned'):remember_installation(exe,record)
        print(plan['reason']);return plan['status']
    actions=plan['actions']
    if any(isinstance(a['data'],Upstream) for a in actions):
        needed={a['data'].name for a in actions if isinstance(a['data'],Upstream)}
        groups=[]
        for group in ('runtime','payload','dlss'):
            names=set(plan['pins'].get(group,{}).get('Files',{}))
            if needed & names:groups.append(group);needed-=names
        if needed:raise ValueError('Unresolved component dependencies: '+', '.join(sorted(needed)))
        fetched=pinned(package,plan['pins'],groups,dependency_dir)
        for action in actions:
            if isinstance(action['data'],Upstream):action['data']=fetched[action['data'].name]
    # New files of this release become managed files: what was there is their original, backed up as install() does.
    for action in actions:
        if action['kind']!='add':continue
        target=safe(root,action['path']);action['index']=len(record['files'])
        item=dict(path=action['path'],before=action['old'],after=action['old'],mode=action['mode'])
        if action['old'] is not None:
            item['mtime_ns']=target.stat().st_mtime_ns
            write(safe(state,'backups/'+str(action['index'])),target.read_bytes(),action['mode']);sync_folder(state/'backups')
        record['files'].append(item)
    created=created_folders(root,[a['path'] for a in actions if a['data'] is not None])
    # The generation: the bytes each changed file has now, so rollback (or undoing an interrupted update) gets them back.
    generation=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+uuid.uuid4().hex[:8]
    folder=state/GENERATIONS;folder.mkdir(exist_ok=True)
    staging=folder/('.'+generation);staging.mkdir()
    entries=[]
    for n,action in enumerate(actions):
        target=safe(root,action['path']);data=target.read_bytes() if target.is_file() else None
        if (digest(data) if data is not None else None)!=action['observed']:raise ValueError(action['path']+' changed during the update; no game files were changed')
        if data is not None:write(staging/'files'/str(n),data,0o600)
        applied='applied/'+str(n) if action['kind']=='merge' and action['data'] is not None else None
        if applied:write(staging/applied,action['data'],0o600)
        entries.append(dict(path=action['path'],index=action['index'],component=action['component'],kind=action['kind'],old=action['old'],new=action['new'],
                            saved='files/'+str(n) if data is not None else None,saved_sha256=digest(data) if data is not None else None,
                            applied=applied,
                            mode=stat.S_IMODE(target.stat().st_mode) if data is not None else action['mode'],
                            mtime_ns=target.stat().st_mtime_ns if data is not None else None))
    previous=dict(package=record.get('package'),max_factor=record.get('max_factor'))
    external=[]
    for n,(path,before,after) in enumerate(launcher_migrations.prepare_apply(plan['launcher_ops'])):
        relative='external/'+str(n);write(staging/relative,before,0o600)
        external.append(dict(path=str(path),saved=relative,saved_sha256=digest(before),applied_sha256=digest(after),
                             mode=stat.S_IMODE(path.stat().st_mode),mtime_ns=path.stat().st_mtime_ns))
    description=dict(id=generation,created_at=time.time(),**{'from':previous},to=dict(package=plan['target'],max_factor=plan['max_factor']),
                     metadata_before=release_metadata(record),metadata_after=plan['metadata'],
                     metadata_fields=['update_contract','components',*plan['metadata']],core_updated=plan['core'],
                     files=entries,created_dirs=created,launcher_ops=plan['launcher_ops'],external_files=external)
    write(staging/'generation.json',(json.dumps(description,indent=2)+'\n').encode())
    if (staging/'files').is_dir():sync_folder(staging/'files')
    if (staging/'applied').is_dir():sync_folder(staging/'applied')
    if (staging/'external').is_dir():sync_folder(staging/'external')
    sync_folder(staging);os.replace(staging,folder/generation);sync_folder(folder)
    # Preparation may include downloads or a long copy. Recheck every coupled file, not just replacement targets.
    idle(root)
    if file_digest(state,'state.json')!=expected_record:raise ValueError('Installation record changed since planning; no game files were changed')
    drift=[path for path,expected in plan['observed'].items() if file_digest(root,path)!=expected]
    if drift:raise ValueError('Files changed since planning: '+', '.join(drift[:3])+'; no game files were changed')
    launcher_migrations.check(plan['launcher_ops'])
    # The journal, then the files: an interruption from here on is undone by the next update or rollback, or settled by
    # Restore (also an earlier build's).
    record['created_dirs']=sorted(set(record.get('created_dirs') or [])|set(created),key=lambda name:(-name.count('/'),name))
    record['pending_update']=dict(generation=generation,kind='update',files={a['path']:dict(before=a['old'],after=a['new']) for a in actions})
    # Restore needs the new ownership information even if an interruption happens between resource writes.
    for key in ('ini_changes','launchers','launcher_policy_keys'):
        if key in plan['metadata']:record[key]=plan['metadata'][key]
    save_record(state,record);sync_folder(state)
    journal_hash=file_digest(state,'state.json')
    touched=set()
    for action in actions:
        target=safe(root,action['path'])
        if action['data'] is None:target.unlink(missing_ok=True)
        else:
            write(target,action['data'],action['mode'])
            # A file that goes back to its original also gets the original's modification time back (as Restore does).
            item=record['files'][action['index']]
            if action['kind']=='retire' and isinstance(item.get('mtime_ns'),int):os.utime(target,ns=(target.stat().st_atime_ns,item['mtime_ns']))
        touched.add(target.parent)
    for parent in touched:sync_folder(parent)
    for relative in created:
        parent=(root/relative).parent
        if parent.is_dir():sync_folder(parent)
    launcher_migrations.apply(plan['launcher_ops'],write)
    for row in external:sync_folder(Path(row['path']).parent)
    expected_files=dict(plan['observed']);expected_files.update({a['path']:a['new'] for a in actions})
    changed=[path for path,expected in expected_files.items() if file_digest(root,path)!=expected]
    if changed:raise ValueError('Update verification failed for '+', '.join(changed[:3])+': recovery journal retained')
    if file_digest(state,'state.json')!=journal_hash:raise ValueError('Installation record changed during the update; recovery required')
    emptied=reset_vkd3d_cache(state,record,[a['path'] for a in actions])
    for action in actions:record['files'][action['index']]['after']=action['new']
    record.pop('pending_update')
    # installed_at: Status and Check read only logs written after it; a log of the release before is not this one's.
    record.update(package=plan['target'],max_factor=plan['max_factor'],installed_at=time.time(),**plan['metadata'])
    record.setdefault('installation_id',uuid.uuid4().hex)
    record['update_contract']=dict(UPDATE_CONTRACT)
    core_manifest=digest((package/'manifest.json').read_bytes()) if plan['core'] else (record.get('components') or {}).get('core',{}).get('manifest_sha256')
    record['components']=component_state(record,core_manifest,plan['core_paths'])
    record.setdefault('generations',[]).append(dict(id=generation,**{'from':previous['package']},to=plan['target'],at=time.strftime('%Y-%m-%dT%H:%M:%S%z')))
    prune_generations(state,record)
    remember_installation(exe,record)
    if (record.get('upscaler') or {}).get('name') in hlx.NAMES:remember_prepared(package,helixsr_dir)
    for line in plan_lines(plan)[1:]:print(line)
    if emptied:print('vkd3d-proton’s shader cache for this game was emptied: the first start rebuilds it and takes longer.')
    print('Updated to '+str(plan['target'])+'. Launch the game as before; install.py rollback returns to '+str(previous['package'])+'.')
    return 'partial' if plan['deferred'] else 'update'

def rollback_generation(root,record,generation):
    """Complete a validated rollback, including retries; called with the game's installer lock held."""
    state=root/STATE
    history=record.get('generations') or []
    if not history or history[-1]['id']!=generation['id']:raise ValueError('Rollback generation does not match history')
    validate_generation(record,generation)
    validate_external_generation(root,record,generation)
    launcher_migrations.prepare_apply(generation.get('launcher_ops') or [],reverse=True)
    actions=[];conflicts=[]
    for entry in generation['files']:
        item=record['files'][entry['index']];now=file_digest(root,entry['path'])
        data=saved_bytes(state,generation,entry);goal=entry['saved_sha256']
        if entry['kind']=='merge':
            # Settings changed since the update: the earlier file with the user's present values.
            if data is not None and now not in (entry['new'],goal):
                if now is None:raise ValueError(entry['path']+' was removed after the update; no settings were overwritten')
                data=rollback_settings(data,applied_bytes(state,generation,entry),safe(root,entry['path']).read_bytes())
        elif now not in (entry['new'],goal):conflicts.append(entry['path']);continue
        actions.append(dict(entry=entry,item=item,data=data,new=digest(data) if data is not None else None))
    if conflicts:raise ValueError('Changed since the update (a game update or another tool): '+', '.join(conflicts[:3])+'. Nothing was rolled back; Restore keeps them as the game’s own.')
    record['pending_update']=dict(generation=generation['id'],kind='rollback',files={a['entry']['path']:dict(before=a['item']['after'],after=a['new']) for a in actions})
    save_record(state,record);sync_folder(state)
    touched=set()
    for action in actions:
        target=safe(root,action['entry']['path'])
        if action['data'] is None:target.unlink(missing_ok=True)
        elif file_digest(root,action['entry']['path'])!=action['new']:write(target,action['data'],action['entry'].get('mode',action['item']['mode']))
        if action['data'] is not None and action['new']==action['entry']['saved_sha256']:
            restore_generation_metadata(target,action['entry'])
        touched.add(target.parent)
    for parent in touched:
        if parent.is_dir():sync_folder(parent)
    restore_external_generation(root,record,generation)
    emptied=reset_vkd3d_cache(state,record,[a['entry']['path'] for a in actions])
    for action in actions:action['item']['after']=action['entry']['old']
    record.pop('pending_update');forget_folders(root,record,generation.get('created_dirs') or [])
    record.update(package=generation['from']['package'],installed_at=time.time())
    if generation['from'].get('max_factor') is None:record.pop('max_factor',None)
    else:record['max_factor']=generation['from']['max_factor']
    restore_release_metadata(record,generation)
    history=record.get('generations') or []
    if not history or history[-1]['id']!=generation['id']:raise ValueError('Rollback generation does not match history')
    history.pop();prune_generations(state,record)
    remember_installation(Path(record['game']),record)
    print('Rolled back from '+str(generation['to']['package'])+' to '+str(generation['from']['package'])+': '+str(len(actions))+' file'+('s' if len(actions)!=1 else '')+
          ' put back as they were. Launch the game as before.')
    if emptied:print('vkd3d-proton’s shader cache for this game was emptied: the first start rebuilds it and takes longer.')

@locked
@launcher_locked
def rollback(exe):
    """install.py rollback: back to the release before the last update, byte for byte (the generation that update saved),
    keeping the user's values in the settings files; or, after an interrupted update, undo it."""
    root=exe.parent.resolve();idle(root);state=root/STATE
    record=json.loads(safe(root,STATE+'/state.json').read_text())
    validate_update_state(root,record)
    if record.get('status')!='installed':raise ValueError('Not installed: nothing to roll back')
    pending=record.get('pending_update')
    if pending and not pending.get('generation'):raise ValueError('An update by an earlier build was interrupted: use Restore.')
    if pending:
        undone,lines=settle_interrupted(root,record)
        for line in lines:print(line)
        if undone:return
    history=record.get('generations') or []
    if not history:raise ValueError('No update to roll back: this installation was not updated in place since it was installed or rolled back.')
    generation=load_generation(state,history[-1]['id'])
    if generation is None:raise ValueError('The files of '+str(history[-1]['from'])+' saved by the last update are missing: use Restore, then Install that release.')
    validate_generation(record,generation)
    rollback_generation(root,record,generation)

@locked
def pin(exe,on=True):
    """install.py pin / unpin: whether update (also update --all) leaves this game on its installed release."""
    root=exe.parent.resolve();state=root/STATE
    record=json.loads(safe(root,STATE+'/state.json').read_text())
    if record.get('status')!='installed':raise ValueError('Install this build first')
    if on:
        record['update_pin']=dict(package=record.get('package'),at=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
        print('Pinned to '+str(record.get('package'))+': update leaves this game as it is (install.py unpin to update it again).')
    else:
        if not record.pop('update_pin',None):print('Not pinned.');return
        print('Unpinned: install.py update updates this game again.')
    save_record(state,record)

def library_inventory(home=None):
    """Read the index and launcher discoveries without writing either; retain unavailable registered games in reports."""
    import launcher_config
    roots={root:None for root in launcher_config.installation_roots(home)}
    try:
        for row in freefg_library.entries(home):roots[Path(row['exe']).parent]=Path(row['exe'])
    except (OSError,ValueError) as error:print('Library index needs attention; launcher discovery is still available: '+str(error),file=sys.stderr)
    found=[]
    for root,registered in sorted(roots.items()):
        try:
            record=json.loads(safe(root,STATE+'/state.json').read_text())
            if not isinstance(record,dict) or (record.get('upscaler') is not None and not isinstance(record['upscaler'],dict)):
                raise ValueError('Malformed installation record')
        except (OSError,ValueError) as error:
            if registered is not None:found.append(dict(exe=registered,status='unavailable',reason=str(error),package=None,pinned=False,upscaler=None))
            continue
        exe=Path(str(record.get('game') or ''))
        if record.get('status')=='restored':continue
        if registered is not None and exe!=registered:
            found.append(dict(exe=registered,status='unavailable',reason='The recorded executable moved; reconcile its launcher paths before registration.',package=record.get('package'),pinned=bool(record.get('update_pin')),upscaler=None));continue
        if not exe.is_absolute() or exe.parent.resolve()!=root:continue
        # Old launcher options can survive an uninstall. Discovery alone enrolls only a currently registered game;
        # an explicit index entry remains useful even after a launcher entry is removed.
        if registered is None and not launcher_config.discover(exe,home):continue
        status='installed' if record.get('status')=='installed' and exe.is_file() else 'unavailable'
        found.append(dict(exe=exe,status=status,reason=None if status=='installed' else 'Executable unavailable or installation incomplete',
                          package=record.get('package'),pinned=bool(record.get('update_pin')),upscaler=(record.get('upscaler') or {}).get('name')))
    return found

def library(home=None):
    return sorted({row['exe'] for row in library_inventory(home) if row['status']=='installed'})

def show_library():
    rows=library_inventory()
    if not rows:print('No installed games found. Use Register on an existing FreeFG installation or Install for a new game.')
    for row in rows:
        print(str(row['exe'])+' — '+str(row['package'] or 'unknown release')+'; '+row['status']+
              ('; pinned' if row['pinned'] else '')+('; '+row['upscaler'] if row['upscaler'] else '')+
              ('; '+row['reason'] if row['reason'] else ''))
    return rows

def show_plan(package,exe,component='all',helixsr_dir=None,loader=None,refresh_recipe=False):
    """install.py plan: what update would do in one game (changes nothing). Returns the plan's status."""
    root=exe.parent.resolve();record=json.loads(safe(root,STATE+'/state.json').read_text())
    plan=update_plan(package,root,record,component,helixsr_dir,loader,refresh_recipe=refresh_recipe)
    for line in plan_lines(plan):print(line)
    if plan['status']=='update':
        try:idle(root)
        except ValueError:print('The game is running: close it before updating.')
    return plan['status']

def run_scope(record):
    """compat.last_run's scope for an installation of this build: only the logs beside the executable, written since it
    was installed. Records of other entries (add-on builds) and records from before installed_at keep the full search."""
    if record.get('addon_entry')!=PROXY_ENTRY:return {}
    return dict(beside_exe=True,since=record.get('installed_at'))

def status(exe):
    root=exe.parent.resolve();record=json.loads(safe(root,STATE+'/state.json').read_text())
    print(record['status']+' — '+record.get('route','native'))
    if record.get('package'):print('Package: '+record['package'])
    if record.get('pending_update'):
        print('An update was interrupted: run install.py update again, or install.py rollback.' if record['pending_update'].get('generation') else
              'An update by an earlier build was interrupted: use Restore.')
    if record.get('generations') and record['status']=='installed':
        last=record['generations'][-1]
        print('Updated in place from '+str(last['from'])+' ('+str(last['at'])[:10]+'); install.py rollback returns to it.')
    if record.get('update_pin') and record['status']=='installed':
        print('Pinned to '+str(record['update_pin'].get('package'))+': install.py update leaves it as it is (install.py unpin).')
    if record['status']=='prepared':print('The installation was interrupted after saving backups: use Restore, then Install again.')
    if record['status']!='installed':
        for line in risk_lines(record):print(line)
        return
    changed=[]
    for item in record['files']:
        p=safe(root,item['path']);actual=digest(p.read_bytes()) if p.exists() else None
        if actual!=item['after']:changed.append(item['path'])
    print('Changed since installation: '+(', '.join(changed) if changed else 'none'))
    if record.get('compat'):print('Compatibility at installation: '+record['compat']['line'])
    for line in risk_lines(record):print(line)
    # The launch option the installation actually added (records before launch_args_added name the recipe's).
    added=record.get('launch_args_added',record.get('recipe',{}).get('launch_args') or [])
    if record.get('recipe',{}).get('title'):print('Recipe: '+record['recipe']['title']+(' (launch option '+' '.join(added)+')' if added else ''))
    elif added:print('Launch option added: '+' '.join(added))
    for item in record.get('game_settings',[]):print('Game setting '+item['status']+': '+item['file']+(' ('+item['reason']+')' if item.get('reason') else ''))
    if record.get('dlss_helper'):print(helper_line(record['dlss_helper']))
    upscaler=record.get('upscaler') or {}
    placed=[item['after'] for item in record['files'] if item['path']==upscaler['target']] if upscaler.get('target') else \
        [item['after'] for item in record['files'] if Path(item['path']).name.lower()==DLL and item['after'] in FSR4_BUILDS]
    print(upscaler_line(upscaler,placed[0] if len(placed)==1 else None))
    if upscaler.get('name') in ('helixsr',*hlx.NAMES) and upscaler.get('log'):
        log=log_path(root,upscaler['log'])
        print(hlx.NAMES.get(upscaler['name'],'HelixSR')+' log: '+(str(log) if log is not None and log.is_file() else
                               'not a regular file: '+upscaler['log'] if log is None else
                               'none yet (HelixSR writes '+upscaler['log']+' while the game runs)'))
    if record.get('launchers'):
        import launcher_config
        for target in record['launchers']:
            current=launcher_config.fields(target,Path(target['path']).read_bytes())
            print(target['launcher']+' launch settings: '+('installed' if current==target['after'] else 'changed since installation'))
    if record.get('vkd3d_cache')==VKD3D_CACHE:
        cache=root/STATE/VKD3D_CACHE
        size=sum(p.stat().st_size for p in cache.rglob('*') if p.is_file() and not p.is_symlink()) if cache.is_dir() else 0
        print('vkd3d-proton shader cache: '+str(cache)+(' ('+format(size/1e6,'.1f')+' MB)' if size else ' (empty)'))
    route=record.get('route','native')
    try:
        import compat
        run=compat.last_run(root,route,**run_scope(record))
    except ImportError:compat=run=None
    prefix='' if record.get('addon_entry')==PROXY_ENTRY else 'OptiScaler/plugins/' if record.get('runtime')=='xemfg' else 'OptiScaler/' if record.get('route')=='opti' else ''
    log=safe(root,prefix+'BC250-XeFG-fast.log')
    # A fast log last written before this installation (installed_at) is not this build's: as if there were none.
    before=record.get('installed_at') and log.exists() and log.stat().st_mtime<record['installed_at']
    # BC250-XeFG-fast.log is written only in a session that accelerated; BC250-MFG.log (new at every start) says so.
    if before:pass
    elif log.exists() and run and run.get('fast_stale'):
        print('Last log: '+str(log)+' (from an earlier session: the last session accelerated nothing)')
    elif log.exists():
        text=log.read_text(errors='replace')
        # How much of the session ran on this build's shaders is the Last run's Acceleration line (compat.last_run).
        print('Last log: '+str(log)+' ('+('FAIL marker present' if 'FAIL' in text else 'no FAIL marker')+')')
        decision=next((line for line in reversed(text.splitlines()) if line.startswith(('FRAME_CAP qualified','FRAME_CAP fallback:','FREEFG_SCALE active ','FREEFG_SCALE full ','FREEFG_SCALE fallback:'))),None)
        if decision and decision.startswith(('FRAME_CAP qualified','FREEFG_SCALE active ','FREEFG_SCALE full ')):print('Last scaling decision: '+decision)
        elif decision:print('Last scaling decision: '+decision.removeprefix('FRAME_CAP fallback: ').removeprefix('FREEFG_SCALE fallback: '))
        else:print('No generated-frame scaling recorded in this log.')
        print('Logs describe the last recorded session; they do not prove current frame generation or visual correctness.')
    else:print('No acceleration log yet. Launch normally with FG active.' if record.get('launchers') else 'No acceleration log yet. Launch through the installed wrapper with FG active.')
    if compat:
        for line in compat.setup_notes(root,route,True,run):print(line)
        for line in compat.last_run_lines(run):print('Last run: '+line)

def check(package,exe,accept=(),report=False):
    """install.py check: the compatibility verdict of one game, what the OptiScaler wiki says about it with every
    condition evaluated, and what the logs say after a run. Reads only; writes nothing, starts nothing, no network."""
    import compat
    found=compat_verdict(package,exe,None,None,None,accept)
    if not found:raise ValueError('The compatibility check needs compat.py and gamescan.py beside install.py')
    verdict,scan,data,ids=found
    root=exe.parent.resolve();installed=None;run=None
    try:
        record=json.loads(safe(root,STATE+'/state.json').read_text())
        installed=record['status']+' ('+('native XeSS FG' if record.get('route')=='native' else 'OptiScaler route')+')'
    except (OSError,ValueError,KeyError):record=None
    # The logs describe this installer's last run only where it installed (a record, restored or not); an OptiScaler log
    # without one comes from another setup (an earlier OptiScaler, Luma, another tool) and says nothing about this one.
    if record:run=compat.last_run(root,record.get('route','native'),**run_scope(record))
    # An installation made despite anti-cheat says so; the verdict stays what a new Install would meet (refused).
    notes=risk_lines(record)
    # MFG Unlocker in the game folder: the installation's route, or the route a new Install would take.
    notes+=compat.setup_notes(root,record.get('route','native') if record else verdict['route'],bool(record) and record.get('status')=='installed',run)
    lines=compat.check_lines(verdict,scan,compat.wiki_advice(data,ids,verdict),run,installed,notes)
    if not record and any((root/n).is_file() for n in ['OptiScaler.log',*PROXY_LOGS]):lines+=['','Logs from another setup are in the game folder (not read: no installation of this build is recorded here).']
    print('\n'.join(lines))
    if report:
        versions={}
        try:
            import doctor
            versions={item:text for _,item,text in doctor.checks(package=package) if item in ('GPU','Kernel','gamescope','Proton')}
        except Exception:pass  # noqa: BLE001 - the report is still useful without them
        name=None
        try:name=json.loads((package/'manifest.json').read_text()).get('name')
        except (OSError,ValueError):pass
        print('\n'+compat.report(verdict,scan,versions,run,name,installed_notes=notes))

def check_all(package,home=None):
    """install.py check --all: one verdict line per installed Steam and Heroic game (no launcher edits, no network)."""
    import compat,gamescan
    rm=recipes_module();data=rm.load(package/'recipes/recipes.json') if (package/'recipes/recipes.json').is_file() else None
    counts={}
    for game in gamescan.installed_games(home):
        try:scan=gamescan.scan_folder(game,home=home)
        except Exception as error:print(f'{game.get("name")}: not checked ({type(error).__name__})');continue  # noqa: BLE001
        exe=((scan.get('exe') or {}).get('selected') or '')
        ids=dict(exe=exe.rsplit('/',1)[-1].lower(),steam=set(),gog=set(),epic=set(),titles={rm.norm(game.get('name') or '')},
                 folders={rm.norm(p) for p in Path(exe).parts[:-1]}-{''})
        if game.get('store') in ('steam','gog','epic'):ids[game['store']].add(str(game['id']))
        verdict=compat.decide(scan,data,ids)
        key=verdict['blocking'][0]['code'] if verdict['blocking'] else verdict['tier']
        counts[key]=counts.get(key,0)+1
        # An installation made despite anti-cheat says so beside the verdict (which stays the refusal).
        notes=[]
        if exe and game.get('path'):
            try:notes=risk_lines(json.loads(safe((Path(game['path'])/exe).parent.resolve(),STATE+'/state.json').read_text()))
            except (OSError,ValueError):notes=[]
        print(f'{game.get("name")} [{game.get("store")} {game.get("id")}]: {verdict["line"]}'+''.join(' '+n for n in notes))
    print('\n'+', '.join(f'{k} {v}' for k,v in sorted(counts.items(),key=lambda kv:-kv[1])))

def zipfile_errors():
    import zipfile
    return zipfile.BadZipFile

def helixsr_command(package,folder=None,download=None):
    """install.py helixsr [--helixsr FOLDER]: where HelixSR is and whether it is ready. Without --helixsr and with no HelixSR
    on this computer, it downloads the official release the package pins from HelixSR's GitHub releases into the download
    cache (the user asked for it by running this command, or by choosing HelixSR in Setup). It never runs HelixSR's setup:
    it prints the command that does, which asks before downloading NVIDIA's DLSS DLL and builds the network."""
    if hlx.catalog(package):
        ready=True
        for provider in hlx.NAMES:
            try:
                spec,location,_=hlx.find(package,provider,folder)
                print(hlx.NAMES[provider]+' '+spec['version']+' ready: '+str(location))
            except (OSError,ValueError) as error:ready=False;print(str(error))
        if ready and folder:hlx.remember(package,folder)
        if not ready:print('Use Prepare HLX with Setup’s upscalers, or install.py hlx --dlss-input FILE --amd-input FILE.')
        return 0 if ready else 1
    found=helixsr.find(package,explicit=folder)
    # Nothing usable on this computer: no release, or only one this installer does not know (another version, or a
    # changed DLL). The official release the package pins is downloaded; an unknown folder found is left as it is.
    if folder is None and found['state'] in ('missing','unknown'):
        if found['state']=='unknown':print('Not used: '+found['message'],flush=True)
        print('Downloading the official HelixSR '+str(found['pinned'])+' release from '+helixsr.PROJECT+'/releases (complete and '
              'unmodified, checked by SHA-256). HelixSR is a separate project by '+helixsr.AUTHOR+' under its own licence.',flush=True)
        helixsr.download_release(package,download)
        found=helixsr.find(package)
    if folder is not None and found['state'] in ('ready','unbuilt'):helixsr.remember(folder)
    if found['state']=='ready':
        print(found['message']+'\nChoose it with Install (Upscaler: HelixSR) in Setup, install.py install GAME.exe --upscaler helixsr, '
              'or, for an installed game, Upscaler in Setup or install.py configure GAME.exe --upscaler helixsr.')
        return 0
    print(helixsr.guidance(found))
    return 0 if found['state']=='unbuilt' else 1

def accepted_for(accept,exe):
    """The soft-refusal codes --accept gives one game: CODE for every game, CODE=EXE for that executable only."""
    out=[]
    for item in accept:
        code,_,path=item.partition('=')
        if not path or same_exe(path,exe):out.append(code)
    return out

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['install','preview','restore','status','configure','doctor','helixsr','check','plan','update','rollback','pin','unpin','register','library','hlx','wiki-plan','wiki-apply']);parser.add_argument('exe',type=Path,nargs='*');parser.add_argument('--route',choices=['auto','native','opti'],default='auto');parser.add_argument('--fg-input',choices=['auto','upscaler','dlssg','fsrfg','fsrfg30'],default='auto')
    parser.add_argument('--factor',type=int,choices=[2,3,4])
    parser.add_argument('--resolution',choices=['output','scale','limit']);parser.add_argument('--percent',type=int);parser.add_argument('--limit',type=int,choices=[720,1080,1440,2160])
    parser.add_argument('--downscale',choices=['bilinear','area']);parser.add_argument('--upscale',choices=['bilinear','bicubic','lanczos2','fsr1'])
    parser.add_argument('--dlss-helper',choices=['auto','yes','no'],default='auto',
                        help='NVIDIA’s nvngx_dlss.dll beside the executable in a fresh OptiScaler setup: auto = for DLSS FG input or '
                             'OptiScaler’s DLSS inputs set to true, yes = also otherwise (a DLSS upscaler input on OptiFG; keeps '
                             'OptiScaler’s NVIDIA GPU spoofing on), no = never; never where OptiScaler finds the game’s own copy, '
                             'never over a game file')
    parser.add_argument('--upscaler',choices=list(UPSCALERS),
                        help='install: the upscaler (default fsr4); configure: switch an installed game. helixsr = HelixSR, a separate '
                             'project by lonewolf0622 that its own setup builds on this computer (see install.py helixsr)')
    parser.add_argument('--helixsr',type=Path,metavar='FOLDER',help='a HelixSR release folder (the one with helixsr-setup.sh); '
                        'default: the one found on this computer')
    parser.add_argument('--refresh-recipe',action='store_true',help='plan/update: apply the latest gameplay-qualified integration and launcher recipe; game settings remain manual')
    parser.add_argument('--loader',choices=OPTI_PROXIES,help='plan/update: migrate the OptiScaler loader and its launcher override')
    parser.add_argument('--dlss-input',type=Path,help='hlx: local NVIDIA DLSS model input')
    parser.add_argument('--amd-input',type=Path,help='hlx: local AMD model input')
    parser.add_argument('--component',choices=['all','core','upscaler'],default='all',
                        help='plan/update: update the whole compatible set, only FreeFG/Intel, or only the selected upscaler; never switches providers')
    parser.add_argument('--accept',action='append',default=[],metavar='CODE[=EXE]',
                        help='install despite a soft refusal (install.py check names them: protonfix-api, wiki-not-working, '
                             'input-unconfirmed, and with an explicit --route/--fg-input no-input, no-dx12, api-*); CODE=EXE '
                             'accepts it for that game only (Setup passes one per game it listed)')
    parser.add_argument('--accept-anticheat-risk',action='append',nargs='?',const='',default=[],metavar='EXE',
                        help='install or preview despite the game’s anti-cheat, at the risk of an account ban (COMPATIBILITY.md); '
                             '--accept never lifts this refusal. =EXE names the game; without it, only when one game is given. '
                             'It shows the risks, then asks for the sentence "'+RISK_SENTENCE+'", typed at a terminal')
    parser.add_argument('--confirm-anticheat-risk',metavar='SENTENCE',
                        help='the sentence "'+RISK_SENTENCE+'" for --accept-anticheat-risk where there is no terminal to type it '
                             '(Setup, a script, output piped elsewhere); at a terminal it is typed all the same')
    parser.add_argument('--all',action='store_true',help='check: every installed Steam and Heroic game, one line each; plan, update: '
                        'every game with this build installed that a Steam, Heroic or Lutris entry starts (and the games named)')
    parser.add_argument('--report',action='store_true',help='check: also print a redacted report for a GitHub issue')
    parser.add_argument('--wiki-setting', action='append', default=[], metavar='ID', help='wiki-apply: a selected row ID from wiki-plan')
    parser.add_argument('--wiki-confirm', action='append', default=[], metavar='ID', help='wiki-apply: confirm a selected row’s displayed game/conditions')
    parser.add_argument('--wiki-plan-digest', help='wiki-apply: digest of the preview shown before selection')
    args=parser.parse_args()
    if (args.wiki_setting or args.wiki_confirm or args.wiki_plan_digest) and args.command != 'wiki-apply':
        parser.error('Wiki selection options apply only to wiki-apply')
    if args.command == 'wiki-apply' and (len(args.exe) != 1 or not args.wiki_setting or not args.wiki_plan_digest):
        parser.error('wiki-apply needs one game, selected IDs and the preview digest')
    if args.refresh_recipe and args.command not in ('plan','update'):parser.error('--refresh-recipe applies to plan and update')
    if args.loader and args.command not in ('plan','update'):parser.error('--loader applies to plan and update')
    if args.command=='hlx':
        try:hlx.prepare(Path(__file__).resolve().parent,args.dlss_input,args.amd_input);return 0
        except (OSError,ValueError,subprocess.SubprocessError) as error:print(str(error),file=sys.stderr);return 1
    if args.component!='all' and args.command not in ('plan','update'):parser.error('--component applies to plan and update')
    if args.command in ('plan','update') and any(getattr(args,key) is not None for key in ('upscaler','factor','resolution','percent','limit','downscale','upscale')):
        parser.error('Update preserves settings and provider selection; use configure for those changes')
    risk_values=args.accept_anticheat_risk
    if risk_values or args.confirm_anticheat_risk is not None:
        # The override is per game and needs both its options; nothing is lifted for games the command does not name.
        if args.command not in ['install','preview']:parser.error('--accept-anticheat-risk and --confirm-anticheat-risk apply to install and preview only')
        if not risk_values:parser.error('--confirm-anticheat-risk confirms --accept-anticheat-risk; give both')
        if not args.exe:parser.error('name the game before the option: install.py '+args.command+' GAME.exe --accept-anticheat-risk[=GAME.exe]')
        if '' in risk_values and len(args.exe)!=1:parser.error('--accept-anticheat-risk without =EXE needs exactly one game; name each game with --accept-anticheat-risk=EXE')
        for value in risk_values:
            if value and not any(same_exe(value,exe) for exe in args.exe):parser.error('--accept-anticheat-risk='+value+' names none of the games of this command')
    if args.command=='check' and args.all:return check_all(Path(__file__).resolve().parent)
    if args.command=='doctor':
        import doctor
        return doctor.main()
    if args.command=='helixsr':
        try:return helixsr_command(Path(__file__).resolve().parent,args.helixsr.absolute() if args.helixsr else None)
        except (ValueError,OSError,zipfile_errors()) as error:print(str(error),file=sys.stderr);return 1
    if args.command=='library':show_library();return 0
    games=list(dict.fromkeys(exe.absolute().resolve() for exe in args.exe));unavailable={}
    if args.all and args.command in ('plan','update'):
        named={exe.absolute().resolve() for exe in games}
        inventory=library_inventory()
        unavailable={row['exe'].resolve():row['reason'] for row in inventory if row['status']=='unavailable'}
        games+=[row['exe'] for row in inventory if row['exe'].resolve() not in named]
        if not games:print('No game with this build installed was found in Steam, Heroic or Lutris.');return 0
    elif args.all and args.command!='check':parser.error('--all applies to check, plan and update')
    if not games:parser.error('choose at least one game executable')
    failed=False;outcomes=[]
    for exe in games:
        print('\n'+str(exe))
        try:
            if args.command in ('plan','update') and (not exe.is_file() or exe.resolve() in unavailable):
                print('Unavailable: '+str(exe)+'; '+str(unavailable.get(exe.resolve()) or 'executable not found')+'; this game was deferred.')
                outcomes.append((exe,'unavailable'));failed=failed or args.command=='update';continue
            if args.command=='restore':restore(exe.absolute())
            elif args.command=='status':status(exe.absolute())
            elif args.command=='plan':outcomes.append((exe,show_plan(Path(__file__).resolve().parent,exe.absolute(),args.component,args.helixsr,args.loader,args.refresh_recipe)))
            elif args.command=='update':
                outcome=update(exe.absolute(),component=args.component,helixsr_dir=args.helixsr,loader=args.loader,refresh_recipe=args.refresh_recipe);outcomes.append((exe,outcome))
                # A game left as it is for a reason (blocked) needs attention; up to date and pinned do not.
                if outcome in ('blocked','partial','deferred'):failed=True
            elif args.command=='rollback':rollback(exe.absolute())
            elif args.command in ('pin','unpin'):pin(exe.absolute(),args.command=='pin')
            elif args.command=='register':register_installation(exe.absolute())
            elif args.command=='wiki-plan':print(json.dumps(wiki_settings_plan(Path(__file__).resolve().parent,exe.absolute()),indent=2))
            elif args.command=='wiki-apply':apply_wiki_settings(exe.absolute(),args.wiki_setting,args.wiki_confirm,expected=args.wiki_plan_digest)
            elif args.command=='configure':configure(exe.absolute(),args.factor,args.resolution,args.percent,args.limit,args.downscale,args.upscale,
                                                     upscaler=args.upscaler,helixsr_dir=args.helixsr.absolute() if args.helixsr else None)
            elif args.command=='check':check(Path(__file__).resolve().parent,exe.absolute(),accepted_for(args.accept,exe),args.report)
            else:
                route,fg_input=args.route,args.fg_input
                if route=='auto' and fg_input!='auto':route='opti'  # an explicit OptiScaler input names the route
                verdict=None;accepted=accepted_for(args.accept,exe)
                if route=='auto' and fg_input=='auto':
                    # Automatic: the compatibility verdict picks the route and input (a verified recipe's, else detection's).
                    found=compat_verdict(Path(__file__).resolve().parent,exe.absolute(),None,None,None,accepted)
                    if found:
                        verdict=found[0];route,fg_input=verdict['route'],verdict['fg_input']
                        print('Frame-generation input: '+('native XeSS FG' if route=='native' else {'upscaler':'OptiFG','dlssg':'DLSS FG','fsrfg':'FSR 3.1 FG','fsrfg30':'FSR 3.0 FG'}[fg_input])+' ('+verdict['reason']+')')
                if route=='auto' and fg_input=='auto':
                    # A recipe verified on BC-250 chooses the input (it may differ from what the game ships: Crimson Desert).
                    found=recipe_for(Path(__file__).resolve().parent,exe.absolute())
                    verified=found[1] if found else None
                    if verified and (verified['route']=='opti' or (exe.absolute().parent/'libxess_fg.dll').is_file()):
                        route=verified['route'];fg_input=verified.get('fg_input') or 'upscaler'
                        print('Frame-generation input: '+('native XeSS FG' if route=='native' else {'upscaler':'OptiFG','dlssg':'DLSS FG','fsrfg':'FSR 3.1 FG','fsrfg30':'FSR 3.0 FG'}[fg_input])+' (recipe verified on BC-250: '+verified['title']+')')
                if route=='auto' or (route=='opti' and fg_input=='auto'):
                    detected=detect_input(exe.absolute())
                    if route=='auto':route=detected[0]
                    fg_input=detected[1] if fg_input=='auto' else fg_input
                    print('Frame-generation input: '+detected[2]+('' if (route,fg_input)==detected[:2] else ' (overridden: '+route+'/'+fg_input+')'))
                if fg_input=='auto':fg_input='upscaler'
                risk=[]
                if anticheat_override(risk_values,exe,args.exe):
                    # The warning, then the sentence; only then is the anti-cheat refusal lifted, for this game alone. A running
                    # game is named first, as install() would, so the sentence is not typed for an install that cannot start.
                    idle(exe.absolute().parent.resolve())
                    risk=override_anticheat(Path(__file__).resolve().parent,exe.absolute(),route,fg_input,accepted,verdict,args.confirm_anticheat_risk)
                    if risk and verdict is not None:
                        found=compat_verdict(Path(__file__).resolve().parent,exe.absolute(),None,None,None,accepted,risk)
                        verdict=found[0] if found else None
                install(Path(__file__).resolve().parent,exe.absolute(),args.command=='preview',route,fg_input,dlss_helper=args.dlss_helper,
                        upscaler=args.upscaler or 'fsr4',helixsr_dir=args.helixsr.absolute() if args.helixsr else None,accept=accepted,verdict=verdict,
                        accept_risk=risk)
        except GameRunningError as error:
            print(str(error),file=sys.stderr);failed=True;outcomes.append((exe,'running'))
        except (ValueError,OSError,configparser.Error,subprocess.SubprocessError) as error:
            print(str(error),file=sys.stderr);failed=True;outcomes.append((exe,'failed'))
        except Exception as error:  # noqa: BLE001 - one game's unexpected failure must not skip the others
            import traceback
            print('Unexpected error ('+type(error).__name__+'): '+str(error)+'\nPlease include this in a report:\n'+traceback.format_exc(),file=sys.stderr)
            failed=True;outcomes.append((exe,'failed'))
    if args.command in ('plan','update') and len(games)>1:print('\n'+batch_summary(args.command,outcomes))
    return int(failed)

def batch_summary(command,outcomes):
    """One line about plan or update across several games: how many of each outcome, naming the games that need attention."""
    words={'plan':{'update':'to update','current':'up to date','pinned':'pinned','deferred':'deferred','interrupted':'interrupted','blocked':'need attention','unavailable':'unavailable','running':'running','failed':'failed'},
           'update':{'update':'updated','partial':'partly updated','current':'up to date','pinned':'pinned','deferred':'deferred','blocked':'need attention','unavailable':'unavailable','running':'running','failed':'failed'}}[command]
    parts=[]
    for status,word in words.items():
        names=[exe.name for exe,outcome in outcomes if outcome==status]
        if names:parts.append(str(len(names))+' '+word+(' ('+', '.join(names)+')' if status in ('partial','pinned','deferred','interrupted','blocked','unavailable','running','failed') else ''))
    return ('Plan: ' if command=='plan' else 'Update: ')+'; '.join(parts)+'.'
if __name__=='__main__':sys.exit(main())
