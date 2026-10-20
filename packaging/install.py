#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Local, reversible installation of the experimental BC250 game add-on."""
import argparse,collections,configparser,contextlib,fcntl,functools,hashlib,json,os,re,shutil,stat,struct,subprocess,sys,tempfile,uuid
from pathlib import Path

# This file imports its sibling modules by name (doctor, launcher_config, which imports steam_config and vendor). An
# isolated interpreter (python3 -I) does not put a script's own folder on sys.path, so put it there first.
if str(Path(__file__).resolve().parent) not in sys.path:sys.path.insert(0,str(Path(__file__).resolve().parent))
import helixsr

STATE='.bc250-xefg-experimental'
DLL='amd_fidelityfx_upscaler_dx12.dll'
# Packages whose add-on is a libxess_fg.dll proxy for Intel's unmodified XeFG runtime (manifest addon_entry; no XeSSMFG
# enabler, 2x only): the runtime goes beside the proxy as bc250_xefg_original.dll (dependencies.json runtime.ProxyPackage)
# and the proxy writes its logs beside it, in the game folder.
PROXY_ENTRY='libxess_fg-proxy'
PROXY_LOGS=['BC250-MFG.log','BC250-XeFG-fast.log']
# NVIDIA's DLSS helper (DLSS Super Resolution, dependencies.json 'dlss'): placed beside the game executable only in a fresh
# OptiScaler setup on a DLSS input, and only when OptiScaler's own search finds no copy of the game's (dlss_helper_plan).
DLSS_HELPER='nvngx_dlss.dll'
# The DirectX 12 upscaler OptiScaler runs through its FidelityFX (FSR 3.1) interface, from the file at Libraries.FfxDx12SRPath
# (OptiScaler/amd_fidelityfx_upscaler_dx12.dll in a fresh setup): the BC-250 build of FSR 4 (default) or HelixSR, a separate
# project by lonewolf0622 that the user's own HelixSR setup built on this computer (helixsr.py). Frame generation is XeFG
# either way.
UPSCALERS={'fsr4':'FSR 4 (BC-250 build RC11)','helixsr':helixsr.LABEL}
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

def idle(root):
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            maps=(proc/'maps').read_text(errors='replace')
            if str(root)+'/' in maps and re.search(r'(?i)\.(exe|dll)(?:\s|$)',maps):
                raise ValueError('Close the game before installing or restoring')
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
def upscaler_line(upscaler):
    """One line naming a game's upscaler (records of earlier builds have none: FSR 4)."""
    if (upscaler or {}).get('name')!='helixsr':return 'Upscaler: FSR 4 (BC-250 build RC11).'
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
    pending=[(i,item) for i,item in enumerate(record.get('game_settings',[])) if item['status']=='pending']
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

def compat_verdict(package,exe,route=None,fg_input=None,launcher_home=None,accept=()):
    """(verdict, scan, recipe data, identity) of exe from compat.py (packaging/compat.py, gamescan.py): read only, no
    network. route/fg_input are the user's explicit choice, None for Automatic. None when the package lacks the
    modules or the scan fails unexpectedly (the install then goes on as 0.9.0 did, and says so)."""
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
        return compat.decide(scan,data,ids,choice,None,accept,conflicts,launchers,verified=recipe[1] if recipe else None,setup=setup),scan,data,ids
    except Exception as error:  # noqa: BLE001 - the check is advice; an unexpected failure must not block an install
        print('Compatibility check skipped ('+type(error).__name__+': '+str(error)[:200]+').',file=sys.stderr)
        return None

def verdict_notes(verdict):
    """The lines Install prints about the verdict: the verdict, its notes and the user's numbered steps."""
    lines=['Compatibility: '+verdict['line']]
    lines+=['Note: '+w for w in verdict['warnings'] if not w.startswith('Known on BC-250: ')]
    lines+=['Accepted: '+r['code']+' ('+r['text']+')' for r in verdict['refusals'] if r['code'] in verdict['accepted']]
    if verdict['manual_steps']:lines+=['Your steps:']+['  '+str(n)+'. '+s for n,s in enumerate(verdict['manual_steps'],1)]
    return lines

# OptiScaler.ini keys a user sets for themselves (the MFG multiplier from OptiScaler's menu, the Reflex override), kept
# across Restore and Install of a fresh OptiScaler setup: (section, key, description).
CARRIED_INI=[('XeFG','InterpolationCount','multiplier'),('fakenvapi','ForceReflex','Reflex override')]

@locked
def install(package,exe,preview=False,route="native",fg_input="upscaler",dependency_dir=None,launcher_home=None,extra_args=(),dlss_helper='auto',
            upscaler='fsr4',helixsr_dir=None,accept=(),verdict=None):
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
        found=compat_verdict(package,exe,route,fg_input,launcher_home,accept)
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
    helix=None
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
    else:
        original_ini=ini.read_bytes()
        proxies=[name+'.dll' for name in ['dxgi','winmm','d3d12','wininet','version','winhttp','dbghelp','OptiScaler']]+['OptiScaler.asi']
        # The pinned nightly, and earlier pins whose installations this build still replaces cleanly.
        accepted_hashes={pins['payload']['ProxyHash'],*pins['payload'].get('CompatibleProxyHashes',[])}
        if custom_opti is not None:accepted_hashes.add(digest(custom_opti))
        matches=[name for name in proxies if (root/name).is_file() and digest(safe(root,name).read_bytes()) in accepted_hashes]
        if not matches:
            raise ValueError('Existing OptiScaler must be the 10.0.0-pre1 nightly of September 4 or 29. Restore/update its adapter separately first.')
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
        changes.update(rm.ini_changes(verified,backports,parsed,fg_input,recipe_input,route))
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
        changes[(section,key)]=value;kept.append('OptiScaler.ini '+section+'.'+key+'='+value)
    ini_after=patch_ini(original_ini,changes)
    # The launcher's own fields carry the loader overrides and the Vulkan layer: no wrapper script.
    import launcher_config
    launchers=launcher_config.plan(exe,owner_module,home=launcher_home,runtime='xemfg-proxy' if proxy else 'xemfg',route=route,args=launch_args,
                                   extra_env=(verdict or {}).get('extra_env'))
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
    upscaler_record=dict(name=upscaler,target=fsr_target)
    if helix:upscaler_record.update(version=helix['version'],release=helix['folder'],ini=helix_ini,log=helix_log,displaced_log=helix_displaced)
    if preview:
        print('\n'.join(item['path'] for item in plan))
        for name in displaced:print('Set aside until Restore: '+name+' (an earlier log by the same name)')
        for target in launchers:print('Configure '+target['launcher']+': '+target['path'])
        for item in settings_plan:print(('Game setting: ' if item['after'] is not None else 'Game setting (pending): ')+item['file'])
        if helper:print(helper_line(helper))
        print(upscaler_line(upscaler_record))
        for line in notes:print(line)
        return
    print('Installing '+('HelixSR' if helix else 'FSR 4')+', frame generation and launcher settings; saving original files.')
    if archive_state:state.rename(archive_state)
    # wrapper=None: records of wrapper-based builds named their run.sh here.
    record=dict(status='prepared',runtime='xemfg',route=route,fresh=fresh,wrapper=None,game=str(exe.resolve()),files=plan,package=package_record.get('name'),
                ini_changes=[dict(section=s,key=k,value=v) for (s,k),v in changes.items()],launchers=launchers,launch_args=launch_args,
                launch_args_added=launcher_config.added_args(launchers))
    record['created_dirs']=created_dirs
    record['upscaler']=upscaler_record
    # displaced_logs (also when empty) tells Restore that every proxy log in the game folder is this installation's.
    if proxy:record.update(addon_entry=PROXY_ENTRY,max_factor=package_record.get('max_factor',2),displaced_logs=displaced)
    if helper:record['dlss_helper']=helper
    if verdict:record['compat']=dict(tier=verdict['tier'],line=verdict['line'],choice=verdict['choice'],launch_source=verdict['launch_source'],
                                     ini_sources=verdict['ini_sources'],accepted=verdict['accepted'],extra_env=verdict['extra_env'])
    if recipe:
        entry=recipe[1] or community
        record['recipe']=dict(title=(entry or {}).get('title'),status='verified-bc250' if recipe[1] else 'community-bc250' if entry else None,
                              wiki=[w['title'] for w in recipe[2]],launch_args=launch_args)
        record['game_settings']=[settings_record(item) for item in settings_plan]
    staging=Path(tempfile.mkdtemp(prefix=STATE+'-preparing-',dir=root))
    try:
        (staging/'backups').mkdir()
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
    record['status']='installed';write(state/'state.json',(json.dumps(record,indent=2)+'\n').encode())
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
    print(upscaler_line(upscaler_record))
    for line in notes:print(line)
    print('In game: '+('select native XeSS Frame Generation.' if route=='native' else 'open OptiScaler with Insert; confirm FG Input / XeFG Output and Active. Save Settings and restart after changing the input.'))
    if proxy:print('This build generates 2× (one generated frame per real frame).')

@locked
def restore(exe):
    root=exe.parent.resolve();idle(root);state=root/STATE
    record=json.loads(safe(root,STATE+'/state.json').read_text())
    if record['status']=='restored':print('Already restored.');return
    pending=record.get('pending_update')
    if pending:
        for name,change in pending['files'].items():
            item=next(v for v in record['files'] if v['path']==name)
            if item['after']!=change['before']:raise ValueError('Invalid pending update')
            target=safe(root,name);now=digest(target.read_bytes()) if target.exists() else None
            if now==change['after']:item['after']=change['after']
        record.pop('pending_update')
    actions=[];preserve=[];kept=[]
    for i,item in enumerate(record['files']):
        target=safe(root,item['path']);current=target.read_bytes() if target.exists() else None
        original=safe(state,'backups/'+str(i)).read_bytes() if item['before'] is not None else None
        if original is not None and digest(original)!=item['before']:raise ValueError('Backup checksum mismatch: '+item['path'])
        backup=original;now=digest(current) if current is not None else None
        if now==item['before']:continue # Also recovers an interrupted install.
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
    if (record.get('upscaler') or {}).get('name')=='helixsr':put_back_helixsr_log(root,state,record['upscaler'],notes)
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
    # Folders the installation created, deepest first, once nothing else is in them.
    left_dirs=[]
    for relative in record.get('created_dirs') or []:
        folder=created_folder(root,relative)
        if folder is None:continue
        try:folder.rmdir()
        except OSError:left_dirs.append(relative)
    if left_dirs:notes.append('Kept folders the installation created that now hold other files: '+', '.join(left_dirs)+'.')
    if kept:record['kept_changed']=[path for path,_ in kept]
    record['status']='restored';write(state/'state.json',(json.dumps(record,indent=2)+'\n').encode())
    print(('Original files and launcher settings restored. ' if record.get('launchers') else 'Original files restored; later INI edits preserved. Remove the earlier build’s run.sh launch wrapper from the game’s launch options. ')+'Backups remain in '+str(state))
    if record.get('preserved_ini'):print('Settings from the removed fresh OptiScaler setup: '+str(state/record['preserved_ini']))
    if record.get('preserved_helixsr_ini') and any(Path(item['path']).name.lower()==helixsr.INI for item in record['files']):
        print('Your edited '+helixsr.INI+' is kept in '+str(state/record['preserved_helixsr_ini'])+' (the next HelixSR installation starts from it).')
    for path,i in kept:
        print('Kept '+path+': it changed after installation (a game update or another tool), so it is the game’s own now'+
              ('; the version from before installation is '+str(state/'backups'/str(i)) if i is not None else '')+'.')
    for line in launcher_notes+left+notes:print(line)

def upscaler_target(record,pins):
    """(installation's upscaler record, the managed file that holds the upscaler DLL). Records of earlier builds have no
    upscaler record: their FSR 4 DLL is the managed file installed with the pinned FSR 4 bytes."""
    upscaler=dict(record.get('upscaler') or {})
    if not upscaler:
        fsr4=pins['runtime']['Files'].get('fsr4/'+DLL)
        found=[item['path'] for item in record['files'] if item['after']==fsr4 and Path(item['path']).name.lower()==DLL]
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
    record['upscaler']=new_record;write(state/'state.json',(json.dumps(record,indent=2)+'\n').encode())
    messages.append('Upscaler switched. '+upscaler_line(new_record))
    return messages

@locked
def configure(exe,factor=None,resolution=None,percent=None,limit=None,downscale=None,upscale=None,upscaler=None,helixsr_dir=None,package=None,dependency_dir=None):
    """Change user settings for an installed package. Runtime files stay as they are, except the upscaler DLL (and HelixSR's
    helixsr.ini beside it) when upscaler names one: switch_upscaler runs first, so a settings error after it leaves the
    switch in place (each part is complete and recorded on its own)."""
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
    if record.get('status')=='installed' and record.get('runtime')!='xemfg':raise ValueError('This build is 2× only; it has no frame-generation settings to change')
    if record.get('status')!='installed' or record.get('runtime')!='xemfg':raise ValueError('Install this build first')
    proxy=record.get('addon_entry')==PROXY_ENTRY
    if factor is not None and factor>record.get('max_factor',4):
        raise ValueError('This build generates 2× only (one generated frame per real frame: the most Intel’s runtime generates on GPUs other than Intel’s)')
    switched=[]
    if upscaler is not None:switched=switch_upscaler(Path(package or Path(__file__).resolve().parent),root,record,upscaler,helixsr_dir,dependency_dir)
    for line in switched:print(line)
    done,waiting=apply_pending_settings(exe,root,record)
    for item in done:print(('Game setting applied: ' if item['status']=='applied' else 'Game setting already set: ')+setting_line(item))
    for line in waiting:print('Game setting pending: '+line)
    managed={item['path'] for item in record['files']}
    changes={}
    if factor is not None and not proxy:
        changes['XeSSMFG/settings.ini']={('XeSSMFG','Multiplier'):str(factor if record['route']=='native' else 0)}
    if factor is not None and record['route']=='opti':changes['OptiScaler.ini']={('XeFG','InterpolationCount'):str(factor-1)}
    modern='OptiScaler/plugins/BC250-XeFG/shaders/mfg-frame-settings.required' in managed
    setting_values={}
    if any(v is not None for v in [resolution,percent,limit,downscale,upscale]):
        if not modern:raise ValueError('These controls require the new scaling-controls build')
        if resolution is None:resolution='scale' if percent is not None else 'limit' if limit is not None else None
        if resolution is not None:setting_values[('BC250','ResolutionMode')]=str({'output':0,'scale':1,'limit':2}[resolution])
        if percent is not None:setting_values[('BC250','ResolutionPercent')]=str(percent)
        if limit is not None:setting_values[('BC250','ResolutionLimit')]=str(limit)
        if downscale is not None:
            if downscale=='area' and 'OptiScaler/plugins/BC250-XeFG/shaders/mfg-downscale-filters.required' not in managed:raise ValueError('This build does not include that downscale filter')
            setting_values[('BC250','DownscaleFilter')]=str(down_filters[downscale])
        if upscale is not None:
            if upscale!='bilinear' and 'OptiScaler/plugins/BC250-XeFG/shaders/mfg-upscale-filters.required' not in managed:raise ValueError('This build does not include enlargement filters')
            setting_values[('BC250','UpscaleFilter')]=str(up_filters[upscale])
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

def status(exe):
    root=exe.parent.resolve();record=json.loads(safe(root,STATE+'/state.json').read_text())
    print(record['status']+' — '+record.get('route','native'))
    if record.get('package'):print('Package: '+record['package'])
    if record.get('pending_update'):print('An update by an earlier build was interrupted: use Restore.')
    if record['status']=='prepared':print('The installation was interrupted after saving backups: use Restore, then Install again.')
    if record['status']!='installed':return
    changed=[]
    for item in record['files']:
        p=safe(root,item['path']);actual=digest(p.read_bytes()) if p.exists() else None
        if actual!=item['after']:changed.append(item['path'])
    print('Changed since installation: '+(', '.join(changed) if changed else 'none'))
    if record.get('compat'):print('Compatibility at installation: '+record['compat']['line'])
    # The launch option the installation actually added (records before launch_args_added name the recipe's).
    added=record.get('launch_args_added',record.get('recipe',{}).get('launch_args') or [])
    if record.get('recipe',{}).get('title'):print('Recipe: '+record['recipe']['title']+(' (launch option '+' '.join(added)+')' if added else ''))
    elif added:print('Launch option added: '+' '.join(added))
    for item in record.get('game_settings',[]):print('Game setting '+item['status']+': '+item['file']+(' ('+item['reason']+')' if item.get('reason') else ''))
    if record.get('dlss_helper'):print(helper_line(record['dlss_helper']))
    upscaler=record.get('upscaler') or {}
    print(upscaler_line(upscaler))
    if upscaler.get('name')=='helixsr':
        log=log_path(root,upscaler['log'])
        print('HelixSR log: '+(str(log) if log is not None and log.is_file() else
                               'not a regular file: '+upscaler['log'] if log is None else
                               'none yet (HelixSR writes '+upscaler['log']+' while the game runs)'))
    if record.get('launchers'):
        import launcher_config
        for target in record['launchers']:
            current=launcher_config.fields(target,Path(target['path']).read_bytes())
            print(target['launcher']+' launch settings: '+('installed' if current==target['after'] else 'changed since installation'))
    prefix='' if record.get('addon_entry')==PROXY_ENTRY else 'OptiScaler/plugins/' if record.get('runtime')=='xemfg' else 'OptiScaler/' if record.get('route')=='opti' else ''
    log=safe(root,prefix+'BC250-XeFG-fast.log')
    if log.exists():
        text=log.read_text(errors='replace')
        stages=set(re.findall(r'WINOGRAD_EXECUTE shader=([0-9a-f]+)',text))
        print('Last log: '+str(log))
        print('Accelerated graph stages observed: '+str(len(stages))+'/4; '+('FAIL marker present' if 'FAIL' in text else 'no FAIL marker'))
        decision=next((line for line in reversed(text.splitlines()) if line.startswith(('FRAME_CAP qualified','FRAME_CAP fallback:'))),None)
        if decision and decision.startswith('FRAME_CAP qualified'):print('Last scaling decision: '+decision)
        elif decision:print('Last scaling decision: '+decision.removeprefix('FRAME_CAP fallback: '))
        else:print('No generated-frame scaling recorded in this log.')
        print('Logs describe the last recorded session; they do not prove current frame generation or visual correctness.')
    else:print('No acceleration log yet. Launch normally with FG active.' if record.get('launchers') else 'No acceleration log yet. Launch through the installed wrapper with FG active.')
    try:
        import compat
        for line in compat.last_run_lines(compat.last_run(root)):print('Last run: '+line)
    except ImportError:pass

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
    if record:run=compat.last_run(root)
    lines=compat.check_lines(verdict,scan,compat.wiki_advice(data,ids,verdict),run,installed)
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
        print('\n'+compat.report(verdict,scan,versions,run,name))

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
        print(f'{game.get("name")} [{game.get("store")} {game.get("id")}]: {verdict["line"]}')
    print('\n'+', '.join(f'{k} {v}' for k,v in sorted(counts.items(),key=lambda kv:-kv[1])))

def zipfile_errors():
    import zipfile
    return zipfile.BadZipFile

def helixsr_command(package,folder=None,download=None):
    """install.py helixsr [--helixsr FOLDER]: where HelixSR is and whether it is ready. Without --helixsr and with no HelixSR
    on this computer, it downloads the official release the package pins from HelixSR's GitHub releases into the download
    cache (the user asked for it by running this command, or by choosing HelixSR in Setup). It never runs HelixSR's setup:
    it prints the command that does, which asks before downloading NVIDIA's DLSS DLL and builds the network."""
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
        if not path or Path(path).expanduser().absolute().resolve()==Path(exe).expanduser().absolute().resolve():out.append(code)
    return out

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['install','preview','restore','status','configure','doctor','helixsr','check']);parser.add_argument('exe',type=Path,nargs='*');parser.add_argument('--route',choices=['auto','native','opti'],default='auto');parser.add_argument('--fg-input',choices=['auto','upscaler','dlssg','fsrfg','fsrfg30'],default='auto')
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
    parser.add_argument('--accept',action='append',default=[],metavar='CODE[=EXE]',
                        help='install despite a soft refusal (install.py check names them: protonfix-api, wiki-not-working, '
                             'input-unconfirmed, and with an explicit --route/--fg-input no-input, no-dx12, api-*); CODE=EXE '
                             'accepts it for that game only (Setup passes one per game it listed)')
    parser.add_argument('--all',action='store_true',help='check: every installed Steam and Heroic game, one line each')
    parser.add_argument('--report',action='store_true',help='check: also print a redacted report for a GitHub issue')
    args=parser.parse_args()
    if args.command=='check' and args.all:return check_all(Path(__file__).resolve().parent)
    if args.command=='doctor':
        import doctor
        return doctor.main()
    if args.command=='helixsr':
        try:return helixsr_command(Path(__file__).resolve().parent,args.helixsr.absolute() if args.helixsr else None)
        except (ValueError,OSError,zipfile_errors()) as error:print(str(error),file=sys.stderr);return 1
    if not args.exe:parser.error('choose at least one game executable')
    failed=False
    for exe in args.exe:
        print('\n'+str(exe))
        try:
            if args.command=='restore':restore(exe.absolute())
            elif args.command=='status':status(exe.absolute())
            elif args.command=='configure':configure(exe.absolute(),args.factor,args.resolution,args.percent,args.limit,args.downscale,args.upscale,
                                                     upscaler=args.upscaler,helixsr_dir=args.helixsr.absolute() if args.helixsr else None)
            elif args.command=='check':check(Path(__file__).resolve().parent,exe.absolute(),accepted_for(args.accept,exe),args.report)
            else:
                route,fg_input=args.route,args.fg_input
                if route=='auto' and fg_input!='auto':route='opti'  # an explicit OptiScaler input names the route
                verdict=None
                if route=='auto' and fg_input=='auto':
                    # Automatic: the compatibility verdict picks the route and input (a verified recipe's, else detection's).
                    found=compat_verdict(Path(__file__).resolve().parent,exe.absolute(),None,None,None,accepted_for(args.accept,exe))
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
                install(Path(__file__).resolve().parent,exe.absolute(),args.command=='preview',route,fg_input,dlss_helper=args.dlss_helper,
                        upscaler=args.upscaler or 'fsr4',helixsr_dir=args.helixsr.absolute() if args.helixsr else None,accept=accepted_for(args.accept,exe),verdict=verdict)
        except (ValueError,OSError,configparser.Error,subprocess.SubprocessError) as error:print(str(error),file=sys.stderr);failed=True
        except Exception as error:  # noqa: BLE001 - one game's unexpected failure must not skip the others
            import traceback
            print('Unexpected error ('+type(error).__name__+'): '+str(error)+'\nPlease include this in a report:\n'+traceback.format_exc(),file=sys.stderr);failed=True
    return int(failed)
if __name__=='__main__':sys.exit(main())
