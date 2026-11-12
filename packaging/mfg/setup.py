#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Small desktop front end for the installer beside it (install.py)."""
import json,os,shutil,subprocess,sys,tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parent
# Packages of runtime 'xemfg' offer 2x/3x/4x and generated-frame resolution (an enabler-free one 2x only, below);
# 'xefg' packages are Intel's 2x frame generation only.
MANIFEST=json.loads((ROOT/'manifest.json').read_text())
MFG=MANIFEST.get('runtime')=='xemfg'
SCALING=bool(MANIFEST.get('generated_frame_scaling')) or any(name.endswith('/freefg-scaling.required') or name.endswith('/mfg-frame-settings.required') for name in MANIFEST.get('files',{}))
# A package without the XeSSMFG enabler (its add-on a libxess_fg.dll proxy) generates 2x only: max_factor 2.
FACTORS=[f'{n}×' for n in range(2,int(MANIFEST.get('max_factor',4))+1)]
NAME='FreeFG'

def dialog(*args):
    """The dialog's answer, or None when it was cancelled or closed (callers go back to the menu)."""
    result=subprocess.run(['zenity','--title='+NAME,*args],text=True,capture_output=True)
    if result.returncode:return None
    return result.stdout.rstrip('\n')

def load_installer():
    import importlib.util
    spec=importlib.util.spec_from_file_location('bc250_install',ROOT/'install.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

LAUNCHERS={'steam':'Steam','heroic':'Heroic','lutris':'Lutris'}
def blockers(installer,selected,launchers):
    """What is still running and would make the installer refuse: the selected games, and (for launcher edits) launchers."""
    names=[]
    for exe in selected:
        # /proc maps list resolved paths (a game chosen through ~/.steam/steam is a symlinked path).
        try:installer.idle(Path(exe).resolve().parent)
        except ValueError:names.append(Path(exe).name)
    if launchers:
        # Only the launchers that hold these games' entries (all three if that lookup fails).
        owners=set(LAUNCHERS)
        try:
            if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
            import launcher_config
            owners={t['launcher'] for exe in selected for t in launcher_config.discover(Path(exe))}
        except Exception:pass
        for proc in Path('/proc').glob('[0-9]*'):
            try:comm=(proc/'comm').read_text().strip().lower()
            except OSError:continue
            if comm in owners and comm in LAUNCHERS and LAUNCHERS[comm] not in names:names.append(LAUNCHERS[comm])
    return names

def wait_closed(installer,selected,launchers):
    """Asks until nothing blocks the operation; False when the user goes back."""
    while installer and (names:=blockers(installer,selected,launchers)):
        result=subprocess.run(['zenity','--question','--title='+NAME,'--width=560','--ok-label=Check again','--cancel-label=Back',
            '--text=Close '+', '.join(names)+' first.'+('\nA running launcher can overwrite the launch settings Setup writes.' if launchers else '')],capture_output=True)
        if result.returncode:return False
    return True

# The upscaler choice (install.py --upscaler). HelixSR is a separate project by lonewolf0622. A package with its catalog
# (dependencies.json "hlx") offers HelixSR's four upscalers beside FSR 4: one line about each (setup_model.UPSCALER_ABOUT
# says the same). The suggested one is listed first and is the default of a new installation when it is ready on this
# computer or install.py can make it ready there first (it prepares a HelixSR upscaler named to it); where its build
# cannot run, the default is FSR 4, which needs no preparation.
UPSCALER_ABOUT={'fsr4':'AMD FSR 4, BC-250 build: built in, always ready',
                'hlx-dlss':'DLSS Model E network, built on this computer',
                'hlx-dlss-k':'DLSS 4 Preset K network: sharper, a little slower; optional long build',
                'hlx-fsr4':'HelixSR’s fast FSR 4-class upscaler; comes built',
                'hlx-fsr4-full':'Full FSR 4.1.2 network on HelixSR’s kernels: sharper, slower; comes built'}
# A package without that catalog: Setup downloads HelixSR's official release from its GitHub releases when the user asks,
# and the user builds it once with HelixSR's own setup.
UPSCALER_ROWS=['FSR 4','Default: the BC-250 build of AMD FSR 4, downloaded by checked hash',
               'HelixSR (by lonewolf0622)','NVIDIA’s DLSS network as compute shaders: a separate project by lonewolf0622, under its own licence']
HELIXSR_ABOUT=('HelixSR is a separate project by lonewolf0622 (github.com/lonewolf0622/HelixSR), under its own licence (the '
               'HelixSR Freeware License). Its upscalers run DLSS and FSR 4 networks as compute shaders. This package ships none of it.')

def question(text,ok,cancel,extra=None,width=760):
    """A question with its two buttons and, with extra, a third: True for ok, the extra button's label for that one, None
    when the user goes back or closes it."""
    result=subprocess.run(['zenity','--question','--title='+NAME,'--width='+str(width),'--ok-label='+ok,'--cancel-label='+cancel,
                           *(['--extra-button='+extra] if extra else []),'--text='+text],text=True,capture_output=True)
    if not result.returncode:return True
    return extra if extra and (result.stdout or '').strip()==extra else None

def run_installer(args,text,output):
    """Run install.py with args under a pulsating progress window and write what it prints to the file output. The window
    shows text and, under it, the installer's last line as it arrives: a download or a build of many minutes is seen to
    be running. Nothing ends the command for taking long. Returns its exit status."""
    with output.open('w') as stream:
        process=subprocess.Popen([sys.executable,'-u',str(ROOT/'install.py'),*args],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                 text=True,encoding='utf-8',errors='replace')
        progress=subprocess.Popen(['zenity','--progress','--pulsate','--no-cancel','--auto-close','--width=720','--title='+NAME,'--text='+text],
                                  stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        for line in process.stdout or ():
            stream.write(line);stream.flush()
            if not line.strip():continue
            # zenity reads a line that starts with # as the window's new text (\n in it as a line break; the characters
            # of its markup are left out of the installer's line).
            shown=''.join(' ' if c in '<>&' else c for c in line.strip()[:160]).replace('\\','\\\\')
            try:progress.stdin.write(('# '+text+'\\n'+shown+'\n').encode());progress.stdin.flush()
            except (OSError,ValueError):pass
        result=process.wait()
        try:progress.communicate(b'100\n',timeout=10)
        except (subprocess.TimeoutExpired,OSError,ValueError):progress.terminate();progress.wait()
    return result

def run_and_show(args,text):
    """Run install.py with args under a progress window, then show what it printed."""
    with tempfile.TemporaryDirectory(prefix='bc250-xefg-setup-') as temporary:
        output=Path(temporary)/'result.txt'
        run_installer(args,text,output)
        dialog('--text-info','--width=1000','--height=520','--filename='+str(output))

def helixsr_ready(installer):
    """True when a HelixSR release built by its own setup is on this computer. Otherwise, on the user's go, Setup
    downloads the official release and shows how to build it once with HelixSR's own setup (False: back to the menu)."""
    if installer is None:
        dialog('--error','--text=Setup cannot read install.py; use the command line (README.md).');return False
    try:found=installer.helixsr.find(ROOT)
    except Exception as error:  # noqa: BLE001 - a broken pin or folder is shown, never a crash
        dialog('--error','--text='+str(error));return False
    if found['state']=='ready':return True
    if found['state'] in ('missing','unknown'):
        # No HelixSR here, or only one this package does not know (another version or a changed DLL): offer the official one.
        size=installer.helixsr.pins(ROOT)['input']['size']
        ignored=('Not used: '+found['message']+'\n\n') if found['state']=='unknown' else ''
        if dialog('--question','--width=700','--text='+ignored+HELIXSR_ABOUT+'\n\nDownload the official HelixSR '+str(found['pinned'])+
                  ' release from its GitHub releases ('+str(round(size/1e6))+' MB, complete and unmodified, checked by SHA-256)?\n'
                  'Setup then shows how to build it once with HelixSR’s own setup, which asks you before it downloads NVIDIA’s DLSS DLL.') is None:
            return False
        run_and_show(['helixsr'],'Downloading HelixSR from github.com/lonewolf0622/HelixSR.')
        return False
    with tempfile.TemporaryDirectory(prefix='bc250-xefg-setup-') as temporary:
        note=Path(temporary)/'helixsr.txt';note.write_text(installer.helixsr.guidance(found)+'\n')
        dialog('--text-info','--width=1000','--height=520','--filename='+str(note))
    return False

def helix_ready(installer,name):
    """Whether a Helix upscaler is ready on this computer (hlx.find hashes the prepared files)."""
    try:installer.hlx.find(ROOT,name);return True
    except (OSError,ValueError):return False

def build_missing(installer):
    """What building HLX DLSS needs and this computer lacks (hlx.requirements' names); [] also when that cannot be asked:
    install.py checks again before it changes a game, and says what is missing."""
    try:return list(installer.hlx.requirements())
    except Exception:return []  # noqa: BLE001

def upscalers(installer):
    """[(id, name, state, about, ready, preparable)] of the upscalers a package with HelixSR's catalog offers: the
    suggested one first and marked, then FSR 4, then the others (hlx.NAMES' order). state says where each stands on this
    computer: Ready, or what it still needs (and what its build lacks here). preparable: not ready, and install.py can
    make it ready before it changes a game: one that comes built always, one that is built when nothing its build needs
    is missing."""
    hlx=installer.hlx;spec=hlx.catalog(ROOT);rows=[];missing=None
    for name,label in hlx.NAMES.items():
        ready=helix_ready(installer,name);built=bool(hlx.built(spec,name));lacks=[]
        if built and not ready:
            missing=build_missing(installer) if missing is None else missing;lacks=missing
        state='Ready' if ready else ('Not built yet' if built else 'Not downloaded yet')+('; its build needs '+', '.join(lacks) if lacks else '')
        rows.append((name,label+(' (suggested)' if name==hlx.SUGGESTED else ''),state,UPSCALER_ABOUT.get(name,label),ready,not ready and not lacks))
    first=[row for row in rows if row[0]==hlx.SUGGESTED]
    return first+[('fsr4','FSR 4','Ready',UPSCALER_ABOUT['fsr4'],True,False)]+[row for row in rows if row not in first]

def megabytes(size,step=1):
    """'59 MB' for a size in bytes, rounded to step megabytes; '' without a size."""
    return str(round(size/(step*1e6))*step)+' MB' if isinstance(size,(int,float)) and size>0 else ''

def joined(names):
    """'A', 'A and B', 'A, B and C'."""
    names=[str(n) for n in names]
    return ' and '.join(names) if len(names)<3 else ', '.join(names[:-1])+' and '+names[-1]

def archive_size(installer):
    """'about 280 MB': the size of HelixSR's official archive as the package pins it ('' when it pins none)."""
    size=megabytes((installer.hlx.catalog(ROOT).get('archive') or {}).get('size'),10)
    return 'about '+size if size else ''

# About how long HelixSR's build takes on a BC-250, by what is built: Model E, Preset K after it, or both
# (setup_model.BUILD_TIME says the same).
BUILD_TIME={('hlx-dlss',):'about 15 minutes',('hlx-dlss-k',):'about 30 minutes',('hlx-dlss','hlx-dlss-k'):'about 45 minutes'}

def prepare_build(installer,names):
    """The Helix upscalers install.py builds to make names ready (hlx.prepare): Model E, also for Preset K, and Preset K
    when it is among them; what is built already is kept. [] when all of names come built."""
    hlx=installer.hlx;spec=hlx.catalog(ROOT)
    if not any(hlx.built(spec,name) for name in names):return []
    return [name for name in hlx.NAMES if hlx.built(spec,name) and (name not in hlx.OPTIONAL or name in names) and not helix_ready(installer,name)]

def build_sentence(installer,names):
    """'The build takes about 15 minutes on a BC-250.' for what making names ready builds ('' when nothing is)."""
    time=BUILD_TIME.get(tuple(prepare_build(installer,names)))
    return 'The build takes '+time+' on a BC-250.' if time else ''

def prepare_lines(installer,names):
    """What install.py does first for Helix upscalers that are not ready, a sentence per line, as Setup's window says it
    (setup_model.prepare_lines): what is downloaded and from where (NVIDIA's DLSS DLL under NVIDIA's licence, unless a
    copy is on this computer), then what is built here and about how long that takes on a BC-250. A download counts as
    held by its pinned size in the installer's cache (install.py checks its hash)."""
    hlx=installer.hlx;spec=hlx.catalog(ROOT);build=prepare_build(installer,names);held=None
    def cached(pin):
        try:return (hlx.cache(spec)/pin['file']).stat().st_size==pin['size']
        except (OSError,ValueError,KeyError,TypeError,AttributeError):return False
    def sized(what,size):return what+(' ('+size+')' if size else '')
    github=[] if cached(spec.get('archive')) else [sized('HelixSR’s official archive',archive_size(installer))]
    version=(spec.get('model_inputs') or {}).get('dlss_version');named='NVIDIA’s DLSS '+(version+' ' if version else '')+'DLL'
    if build:
        compilers=[pin for pin in (spec.get('compilers') or {}).values() if isinstance(pin,dict)]
        if not (compilers and all(cached(pin) for pin in compilers)):
            github.append(sized('Microsoft’s shader compiler',megabytes(sum(pin.get('size') or 0 for pin in compilers))))
        try:held=hlx.dlss_input(ROOT)
        except Exception:held=None  # noqa: BLE001 - no copy on this computer: install.py downloads it
    downloads=[joined(github)+' from '+('their' if len(github)>1 else 'its')+' GitHub releases'] if github else []
    if build and held is None:
        try:
            pins=json.loads((ROOT/'dependencies.json').read_text()).get('inputs') or {}
            size=megabytes(next((pin.get('size') for pin in pins.values() if pin.get('sha256')==spec['model_inputs']['dlss']),None))
        except (OSError,ValueError,KeyError,TypeError,AttributeError):size=''
        downloads.append(sized(named,size)+' from NVIDIA’s repository under NVIDIA’s licence ('+hlx.NVIDIA_LICENSE+')')
    lines=['Downloads '+', and '.join(downloads)+'. Each file is checked by SHA-256.' if downloads else
           'Nothing is downloaded: the files it takes are on this computer already.']
    if build:
        if held is not None:lines.append('The build takes the copy of '+named+' on this computer.')
        lines.append('Builds '+joined(hlx.NAMES[name] for name in build)+' on this computer with networking off. That takes '+
                     BUILD_TIME[tuple(build)]+' on a BC-250.')
    else:lines.append('Nothing is built: '+joined(hlx.NAMES[name] for name in names)+(' comes' if len(names)==1 else ' come')+' built in the archive.')
    return lines

def prepare_first(installer,names):
    """(the Helix upscalers among names that install.py hlx can make ready on this computer, its arguments for them), None
    when none can be: those that come built always (hlx --no-build when only they are named), those that are built when
    nothing their build needs is missing (--preset-k when Preset K is among them)."""
    hlx=installer.hlx;spec=hlx.catalog(ROOT)
    built=[name for name in names if hlx.built(spec,name)]
    if built and build_missing(installer):built=[]
    can=[name for name in names if name in built or not hlx.built(spec,name)]
    if not can:return None
    return can,(['hlx',*(['--preset-k'] if any(name in hlx.OPTIONAL for name in built) else [])] if built else ['hlx','--no-build'])

def other_ways(installer,provider,installed,local):
    """install.py's extra options for a Helix upscaler made ready another way than install.py's own preparation, None when
    the user goes back: the selected games' own checked copies (installed: --no-prepare), a release folder prepared
    before (--helixsr), or (local) install.py's preparation from a local copy of NVIDIA's DLSS DLL instead of its
    download (--dlss-input)."""
    hlx=installer.hlx
    choice=dialog('--list','--width=900','--height=290','--column=Action','--column=Description',
        *(['Use game copies','Reuse the checked upscaler files the selected games already hold'] if installed else []),
        'Use prepared folder','Select a HelixSR release folder already prepared on this computer',
        *(['Use a local copy of NVIDIA’s DLL','Build from nvngx_dlss.dll on this computer instead of its download; Setup checks it by SHA-256'] if local else []),
        '--text=Other ways to make '+hlx.NAMES[provider]+' ready. Built model files stay on this computer.')
    if choice=='Use game copies':return ['--no-prepare']
    if choice=='Use prepared folder':
        folder=dialog('--file-selection','--directory','--title=Prepared HelixSR release folder')
        if not folder:return None
        try:hlx.find(ROOT,provider,folder);return ['--helixsr',folder]
        except (OSError,ValueError) as error:dialog('--error','--text='+str(error));return None
    if choice=='Use a local copy of NVIDIA’s DLL':
        dlss=dialog('--file-selection','--title=NVIDIA’s DLSS DLL (nvngx_dlss.dll)')
        if not dlss:return None
        try:hlx.dlss_input(ROOT,dlss)
        except (OSError,ValueError) as error:dialog('--error','--width=680','--text='+str(error));return None
        return ['--dlss-input',dlss]
    return None

def hlx_ready(installer,provider,installed=False):
    """install.py's extra options ([]: none) for the Helix upscaler chosen, None when the user goes back. One that is
    ready needs none. One that is not ready is prepared by install.py itself, before it changes a game and once for
    every game (install and configure with a HelixSR upscaler named): one confirmation says what that downloads, what is
    built on this computer and about how long it takes. Its Other ways… lead to the games' own copies, a prepared folder
    or a local copy of NVIDIA's DLSS DLL (other_ways). Where the build cannot run on this computer, the confirmation
    names what is missing and offers the other ways alone."""
    hlx=installer.hlx
    if helix_ready(installer,provider):return []
    name=hlx.NAMES[provider];built=bool(hlx.built(hlx.catalog(ROOT),provider))
    missing=build_missing(installer) if built else []
    if missing:
        answer=question(name+' cannot be built on this computer yet: its build needs '+', '.join(missing)+'. Install '+
                        ('it' if len(missing)==1 else 'them')+' with your distribution’s package manager, then choose '+name+' again.\n'
                        'FSR 4, HLX FSR 4 and HLX FSR 4 Full need none of it.','Other ways…','Back')
        return other_ways(installer,provider,installed,False) if answer is True else None
    try:hlx.dlss_input(ROOT);held=True
    except Exception:held=False  # noqa: BLE001
    answer=question(name+' is not ready on this computer yet. Setup prepares it first, once for every game, then '+
                    ('switches' if installed else 'installs')+':\n\n'+'\n'.join(prepare_lines(installer,[provider]))+
                    '\n\nNo game is changed until it is ready.','Prepare and '+('switch' if installed else 'install'),'Back','Other ways…')
    if answer is True:return []
    return other_ways(installer,provider,installed,built and not held) if answer else None

def preparing(installer,extra):
    """The Helix upscaler (its id) that install.py prepares before a command with these options changes a game: one named
    with --upscaler that is not ready, unless a prepared folder or the games' own copies serve it. None otherwise."""
    if not installer or not hasattr(installer,'hlx') or '--upscaler' not in extra or '--helixsr' in extra or '--no-prepare' in extra:return None
    name=extra[extra.index('--upscaler')+1]
    return name if name in installer.hlx.NAMES and not helix_ready(installer,name) else None

def deferred_helix(installer,games,component='all',refresh=False):
    """The Helix upscalers (ids) the update plans of games defer only because this release's HelixSR is not prepared on
    this computer. Read from the plans themselves, not from their wording (install.game_plan: the deferred list names
    the upscaler, the installation's one is a Helix upscaler, and hlx.find's reason for it is among the plan's notes)."""
    found=[]
    if not installer or not hasattr(installer,'game_plan') or not hasattr(installer,'hlx') or not installer.hlx.catalog(ROOT):return found
    for exe in games:
        try:
            exe=Path(exe).absolute();plan=installer.game_plan(ROOT,exe,component,None,None,refresh)
            if 'upscaler' not in (plan.get('deferred') or []):continue
            record=json.loads(installer.safe(exe.parent.resolve(),installer.STATE+'/state.json').read_text())
            name=(record.get('upscaler') or {}).get('name');name='hlx-dlss' if name=='helixsr' else name
            if name not in installer.hlx.NAMES or name in found:continue
            try:installer.hlx.find(ROOT,name)
            except (OSError,ValueError) as error:
                if str(error) in (plan.get('notes') or []):found.append(name)
        except Exception:continue  # noqa: BLE001 - a game whose plan cannot be read says so in the plan shown
    return [name for name in installer.hlx.NAMES if name in found]


def select_library(installer,selected):
    """A native table selects enrolled games; later actions use the existing installer commands."""
    if installer is None:return selected
    from library_view import rows
    try:items=rows(installer)
    except (OSError,ValueError) as error:dialog('--error','--text='+str(error));return selected
    if not items:
        dialog('--info','--text=No enrolled games. Add a game to install it, or Register an existing FreeFG installation.');return selected
    values=[]
    for row in items:
        values.extend(['TRUE' if Path(row['exe']) in selected else 'FALSE',row['exe'],row['title'],row['release'],
                       row['provider'],row['files'],row['runtime'],row['recovery'],row['pin']])
    choice=dialog('--list','--checklist','--width=1200','--height=600','--hide-column=2','--print-column=2','--separator=\n',
        '--column=Select','--column=Executable','--column=Game','--column=FreeFG','--column=Upscaler',
        '--column=Files','--column=Last session','--column=Recovery','--column=Updates',*values,
        '--ok-label=Use selection','--text=Choose games for Settings, Upscaler, Update selected, Rollback or Status.\nLast-session logs describe that run; they do not certify gameplay or settings persistence.')
    return selected if choice is None else [Path(x) for x in choice.splitlines() if x]


def choose_upscaler(installer,text,installed=False):
    """install.py arguments for the upscaler the user picks, or None (cancelled, or the one picked cannot be made ready
    here). A new installation (installed False) starts on the suggested upscaler when it is ready on this computer or
    install.py can make it ready there first, else on FSR 4. One picked that is not ready gets one confirmation of what
    its preparation takes (hlx_ready)."""
    if hasattr(installer,'hlx') and bool(installer.hlx.catalog(ROOT)):
        rows=upscalers(installer)
        default=None if installed else next((row[0] for row in rows if row[0]==installer.hlx.SUGGESTED and (row[4] or row[5])),'fsr4')
        choice=dialog('--list','--radiolist','--width=1100','--height=360','--hide-column=2','--print-column=2',
            '--column=Use','--column=ID','--column=Upscaler','--column=On this computer','--column=About',
            *[value for row in rows for value in ('TRUE' if row[0]==default else 'FALSE',*row[:4])],'--text='+text)
        if not choice:return None
        if choice=='fsr4':return ['--upscaler','fsr4']
        extra=hlx_ready(installer,choice,installed)
        return ['--upscaler',choice,*extra] if extra is not None else None
    choice=dialog('--list','--width=900','--height=300','--column=Upscaler','--column=About',*UPSCALER_ROWS,'--text='+text)
    if not choice:return None
    if choice=='FSR 4':return ['--upscaler','fsr4']
    return ['--upscaler','helixsr'] if helixsr_ready(installer) else None


def verdicts(installer,selected,route=None,fg_input=None,accept_risk=()):
    """[(game, exe, compatibility verdict or None)] for every selected game (install.py compat_verdict: read only, no
    network), for Automatic (route None) or the route and input chosen for the batch. accept_risk: the anti-cheat override,
    only for the one game it was confirmed for (override_anticheat)."""
    out=[]
    for exe in selected:
        try:found=installer.compat_verdict(ROOT,Path(exe).absolute(),route,fg_input,**({'accept_risk':list(accept_risk)} if accept_risk else {}))
        except Exception:found=None
        out.append((Path(exe).name,exe,found[0] if found else None))
    return out

def soft_refusals(found_verdicts):
    """[(exe, code, line)]: every soft refusal of every game, one line each (a code shared by two games is listed and
    accepted once per game, never for a game that was not listed). Install anyway never lists a hard or risk refusal
    (anti-cheat: Override anti-cheat refusal... in the menu), nor the soft ones of a game such a refusal keeps out."""
    return [(exe,r['code'],name+': '+r['text']+' '+r['way']) for name,exe,v in found_verdicts
            if v and not any(x['kind'] in ('hard','risk') for x in v['blocking']) for r in v['blocking'] if r['kind']=='soft']

# Refusals that rest on detection alone (compat.refusals: no DirectX 12, no input): hard for Automatic, soft once the user
# chooses the input. The override's first check leaves them to the input chosen in its Install dialogs.
def detection_only(refusal):
    return refusal['code'] in ('no-input','no-dx12') or refusal['code'].startswith('api-')

def refused_for_another_reason(name,refusal,automatic=False):
    """The error for a game the anti-cheat override cannot help: another refusal remains, with what to do about it."""
    way=('If you know the game has what this check missed, choose its input instead of Automatic.' if automatic and detection_only(refusal)
         else refusal['way'])
    dialog('--error','--width=700','--text='+name+' is also refused for another reason: '+refusal['text']+' '+way+'\n\nNothing was installed.')

# The anti-cheat override (install.py --accept-anticheat-risk): a menu entry of its own, never part of Install or Install
# anyway. One game at a time; the warning's default button is Cancel; then the sentence must be typed exactly.
RISK_ACTION='Override anti-cheat refusal...'
def override_anticheat(installer,selected):
    """(exe, the sentence as typed) for one selected game whose only refusal is its anti-cheat, once the user has read the
    warning and typed the sentence; None when cancelled, on any mismatch, or when no selected game ships anti-cheat."""
    if installer is None:
        dialog('--error','--text=Setup cannot read install.py; use the command line (README.md).');return None
    found=[(name,exe,v,installer.anticheat_names(v)) for name,exe,v in verdicts(installer,selected) if v and installer.anticheat_names(v)]
    if not found:
        dialog('--info','--width=560','--text=Check finds no anti-cheat in the selected games. Use Install.');return None
    if len(found)>1:
        rows=[x for _,exe,_,names in found for x in (str(exe),', '.join(names))]
        choice=dialog('--list','--width=900','--height=360','--column=Game','--column=Anti-cheat',*rows,
                      '--text=The override applies to one game at a time. Choose the game:')
        found=[f for f in found if str(f[1])==choice]
        if not found:return None
    name,exe,verdict,names=found[0]
    # Another hard refusal is shown before the warning. Soft ones are offered by the Install dialogs that follow (Install
    # anyway), and detection's are left to the input chosen there (soft for an explicit input, refused for Automatic).
    others=[r for r in verdict['blocking'] if r['kind']=='hard' and not detection_only(r)]
    if others:
        refused_for_another_reason(name,others[0]);return None
    if dialog('--question','--default-cancel','--width=700','--ok-label=Continue','--cancel-label=Cancel',
              '--text='+installer.anticheat_warning(name,names,NAME)+'\n\nContinue only if you accept that risk for this game.') is None:return None
    typed=dialog('--entry','--width=700','--text=To install '+name+' anyway, type this sentence exactly (anything else cancels):\n\n'+installer.RISK_SENTENCE)
    if typed is None:return None
    if not installer.risk_confirmed(typed):
        dialog('--info','--width=560','--text=The sentence does not match. Nothing was installed.');return None
    return exe,typed.strip()

def wiki_choices(installer,selected):
    """The wiki INI checklist for one selected game (install.py's wiki settings plan, each row source-backed): the
    wiki-apply options for the rows the user selects and the conditions they confirm, or None when they go back. One
    value per setting: a selection that sets a key twice is refused here, as the installer refuses it."""
    if installer is None or not hasattr(installer,'wiki_settings_plan'):
        dialog('--error','--text=Setup cannot read install.py; use the command line (README.md).');return None
    if len(selected)!=1:dialog('--info','--width=560','--text=Select one installed game for Wiki settings.');return None
    try:plan=installer.wiki_settings_plan(ROOT,Path(selected[0]).absolute())
    except Exception as error:  # noqa: BLE001 - a plan that cannot be read is shown, never a crash
        dialog('--error','--width=700','--text='+str(error));return None
    rows=[r for r in plan.get('rows',[]) if r.get('action') in ('automatic','prefill','conditional')
          and not (r.get('current') is not None and str(r['current'])==str(r['value']))]
    if not rows:dialog('--info','--width=560','--text=The bundled wiki catalogue has no settings to apply for this game.');return None
    values=[]
    for r in rows:
        values+=['FALSE',r['id'],r['key']+' = '+str(r['value']),'not set' if r.get('current') is None else str(r['current']),
                 str(r.get('reason') or ''),'; '.join(map(str,r.get('confirmations') or []))]
    choice=dialog('--list','--checklist','--width=1100','--height=520','--hide-column=2','--print-column=2','--separator=\n',
        '--column=Apply','--column=ID','--column=Setting','--column=Current','--column=Why','--column=Confirm first',*values,
        '--text=OptiScaler settings from the wiki for '+Path(selected[0]).name+'. Select only the settings you want; Rollback undoes them.')
    chosen=[x for x in (choice or '').splitlines() if x]
    if not chosen:return None
    by_id={r['id']:r for r in rows};picked={}
    for token in chosen:
        key=by_id[token]['key'].lower()
        if key in picked and picked[key]!=str(by_id[token]['value']):
            dialog('--error','--width=560','--text=Choose one value for '+by_id[token]['key']+': one value per setting is applied.');return None
        picked[key]=str(by_id[token]['value'])
    confirm=[t for t in chosen if by_id[t].get('confirmations')]
    if confirm and dialog('--question','--width=700','--ok-label=They apply','--cancel-label=Back',
                          '--text=Confirm that these conditions apply to this game:\n\n'+'\n'.join(
                              by_id[t]['key']+': '+'; '.join(map(str,by_id[t]['confirmations'])) for t in confirm)) is None:return None
    return ['--wiki-plan-digest',plan['digest'],*[x for t in chosen for x in ('--wiki-setting',t)],*[x for t in confirm for x in ('--wiki-confirm',t)]]

def update_candidates(installer,selected):
    """The games Update all goes through: every game with this build installed that a Steam, Heroic or Lutris entry starts
    (install.py library), and the selected games."""
    try:found=([row['exe'] for row in installer.library_inventory()] if hasattr(installer,'library_inventory') else list(installer.library())) if installer else []
    except Exception:found=[]  # noqa: BLE001 - the selected games are still offered
    return sorted({Path(p).absolute() for p in [*found,*selected]})

def show_text(command,selected):
    """Run install.py command on the selected games and show its output (Check system, Check, an update's plan)."""
    with tempfile.TemporaryDirectory(prefix='bc250-xefg-setup-') as temporary:
        output=Path(temporary)/'result.txt'
        with output.open('w') as stream:subprocess.run([sys.executable,'-u',str(ROOT/'install.py'),*command,*map(str,selected)],stdout=stream,stderr=subprocess.STDOUT)
        dialog('--text-info','--width=1000','--height=600','--filename='+str(output))

def prepare_before_update(installer,games,scope,action):
    """After an update's plan was shown: where it defers a Helix upscaler only because this release's HelixSR is not
    prepared on this computer and install.py hlx can make it ready here, offer to prepare it first (the default
    button), then show the plan again. False when the user goes back; True to go on to the plan's confirmation, with the
    upscaler prepared or, when the user declined that, deferred as the plan says."""
    try:
        waiting=deferred_helix(installer,games,'upscaler' if action=='Update upscalers' else 'all',action=='Refresh recipe')
        first=prepare_first(installer,waiting) if waiting else None
    except Exception:first=None  # noqa: BLE001 - the plan shown stands as it is
    if not first:return True
    names,args=first;labels=joined(installer.hlx.NAMES[name] for name in names)
    answer=question('The plan defers '+labels+': this release’s HelixSR is not prepared on this computer yet.\n\n'
                    'Prepare first, once for every game, then update with it? Setup shows the plan again before it updates.\n\n'+
                    '\n'.join(prepare_lines(installer,names))+'\n\n'+HELIXSR_ABOUT,'Prepare first','Back','Update without it',width=800)
    if answer is None:return False
    if answer is True:
        run_and_show(args,' '.join(filter(None,('Preparing '+labels+' for every game.',build_sentence(installer,names)))))
        show_text(['plan',*scope],games)
    return True

def install_choices(installer,games,risk=False):
    """The Install dialogs for games (input, upscaler, steps, soft refusals, confirmation): the install.py arguments, or
    None when the user goes back. risk: games is the one game the anti-cheat override was confirmed for."""
    accept_risk=['anticheat'] if risk else []
    # Each game's compatibility verdict (install.py check), so the input can be chosen per batch.
    found_verdicts=verdicts(installer,games,accept_risk=accept_risk) if installer else []
    lines=[name+': '+v['line'] for name,_,v in found_verdicts if v]
    found='\n'.join(lines[:12]+([f'... and {len(lines)-12} more (Check lists every game)'] if len(lines)>12 else []))
    if installer and not found:
        try:found='\n'.join(Path(exe).name+': '+installer.detect_input(Path(exe))[2] for exe in games[:8])
        except Exception:found=''
    route=dialog('--list','--width=850','--height=420','--column=Route','--column=Use',
        'Automatic per game','A verified recipe\'s input, else native XeSS FG where the game ships it, else OptiFG; refuses games that cannot work',
        'OptiFG','Games without native FG: uses the upscaler input; may affect HUDs',
        'DLSS FG','Games with supported DLSS FG (Streamline 2+)',
        'FSR 3.1 FG','Games with native FSR 3.1 frame generation',
        'FSR 3.0 FG','Games with native FSR 3.0 frame generation',
        'Native XeSS FG','Games with native XeSS FG DLL beside the executable',
        '--text=Choose the same input for these games, or Automatic. Prefer a native FG input when available.\nAll OptiScaler routes use XeFG output. '+('Frame generation defaults to 2×.' if MFG and len(FACTORS)>1 else 'Frame generation is 2×.')+' Per-game recipes verified on a BC-250 are applied (Automatic also takes their input); OptiScaler wiki notes are listed.'+('\n\nFound:\n'+found if found else ''))
    source={'OptiFG':'upscaler','DLSS FG':'dlssg','FSR 3.1 FG':'fsrfg','FSR 3.0 FG':'fsrfg30'}
    if not route:return None
    extra=['--route','auto','--fg-input','auto'] if route.startswith('Automatic') else ['--route','native'] if route=='Native XeSS FG' else ['--route','opti','--fg-input',source[route]]
    upscaler=choose_upscaler(installer,'Choose the upscaler for these games. Frame generation is XeFG with each of them; Upscaler switches it later.\n'
                             'Install prepares one that is not ready yet, once for every game, and says first what that takes.\n'+HELIXSR_ABOUT)
    if not upscaler:return None
    extra+=upscaler
    # An explicit input changes the verdicts (the user's choice wins; refusals that rest on detection alone become
    # soft): ask them again for that choice.
    if installer and not route.startswith('Automatic'):
        found_verdicts=verdicts(installer,games,'native' if route=='Native XeSS FG' else 'opti',source.get(route),accept_risk)
    if risk:
        # The override lifts the anti-cheat refusal only: a hard refusal for the input chosen still refuses the game.
        hard=[(name,r) for name,_,v in found_verdicts if v for r in v['blocking'] if r['kind'] in ('hard','risk')]
        if hard:
            refused_for_another_reason(*hard[0],automatic=route.startswith('Automatic'));return None
    # The steps a game needs from the user beyond choosing its upscaler, before anything is confirmed.
    steps=''.join('\n\n'+name+':\n'+'\n'.join(f'  {n}. {s}' for n,s in enumerate(v['manual_steps'],1)) for name,_,v in found_verdicts
                  if v and v['needs_step'] and not any(r['kind'] in ('hard','risk') for r in v['blocking']))
    steps=('\n\nYour steps:'+steps) if steps else ''
    # Soft refusals (a GE-Proton fix that leaves DirectX 12, the wiki's "not working") need an explicit yes.
    soft=soft_refusals(found_verdicts)
    if soft and dialog('--question','--width=760','--ok-label=Install anyway','--cancel-label=Skip those games',
                       '--text=These games would be refused unless you accept:\n\n'+'\n'.join(line for _,_,line in soft)) is not None:
        # Each accept names its game: install.py applies CODE=EXE to that executable only.
        for exe,code,_ in soft:extra+=['--accept',code+'='+str(exe)]
    override=('\n\nThe anti-cheat refusal is overridden for this game only, at the risk of a ban; Status and Check show it until Restore.' if risk else '')
    if dialog('--question','--width=680','--text=Setup will configure '+NAME+' and each game’s launch settings.\nThe first installation downloads checked upstream files (FSR4 and Intel’s XeFG runtime);\na fresh OptiScaler setup also fetches OptiScaler and OptiPatcher, and NVIDIA’s DLSS helper only for a DLSS input\nwhere OptiScaler finds no copy of the game’s own.\nAfter installation, reopen your launcher and play normally.'+steps+override) is None:return None
    return extra

def desktop_app(installer,load_error):
    """Setup's window (setup_app.py, on GTK 4 and libadwaita 1.5+) as a function that runs it, or None where it cannot
    run: then the Zenity dialogs below are Setup. FREEFG_SETUP_UI=zenity chooses the dialogs."""
    if os.environ.get('FREEFG_SETUP_UI','').lower()=='zenity' or not (ROOT/'setup_app.py').is_file():return None
    if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
    try:
        import setup_app,setup_model
    # No PyGObject, no GTK 4 or libadwaita typelib (ImportError, ValueError), a typelib that does not load (gi's
    # RepositoryError, an Exception of its own), or libadwaita before 1.5: the dialogs are Setup.
    except Exception as error:  # noqa: BLE001
        print('Setup’s window needs PyGObject with GTK 4 and libadwaita 1.5 ('+type(error).__name__+': '+str(error)+'); using its dialogs.',file=sys.stderr)
        return None
    context=setup_model.Context(ROOT,NAME,MANIFEST,installer,load_error,FACTORS,SCALING,HELIXSR_ABOUT,blockers)
    def run():
        try:return setup_app.run(context)
        except setup_app.StartupError as error:
            print('Setup’s window did not start; using its dialogs.\n'+str(error),file=sys.stderr);return None
    return run

def main():
    selected=[]
    try:installer=load_installer();load_error=None
    except Exception as error:installer=None;load_error=type(error).__name__+': '+str(error)
    app=desktop_app(installer,load_error)
    if app is not None:
        status=app()
        if status is not None:return status
    if not shutil.which('zenity'):
        print('The desktop installer needs PyGObject with GTK 4 and libadwaita, or zenity. The command-line route is in README.md.',file=sys.stderr);return 1
    while True:
        action=dialog('--list','--width=740','--height=420','--column=Action','--column=Description',
            'Add games','Choose actual game .exe files; repeat to add another folder',
            'Install','Install '+NAME+' into selected games',
            # A 2×-only package (no 3×/4×, no generated-frame scaling) has nothing for Settings to change.
            *(['Settings','Choose '+'/'.join(FACTORS)+(' and generated-frame resolution' if SCALING else ' frame generation')] if MFG and (len(FACTORS)>1 or SCALING) else []),
            'Upscaler','Choose FSR 4 or one of HelixSR’s upscalers (HLX DLSS, HLX FSR 4) for selected games',
            'Update all','Update '+NAME+' in every installed game to this package, keeping settings (shows the plan first)',
            'Update upscalers','Update each selected compatible upscaler across the library, keeping FreeFG and provider selection',
            'Library','Select enrolled games; view versions, last-session logs and recovery'
            ,'Update selected','Preview and update the selected games in place',
            'Refresh recipe','Apply a tested input and launcher recipe in place; game settings stay manual',
            'Wiki settings','Review OptiScaler wiki INI suggestions for one selected game and apply the ones you choose',
            'Register','Remember selected existing installations for Update all',
            'Pin','Keep selected games on their installed release',
            'Unpin','Allow selected games to receive updates again',
            'Rollback','Return selected games to the release before their last update',
            'Restore','Restore original files in selected games',
            'Status','Check installed files and the last acceleration log',
            'Check','Compatibility of each selected game: what Install would do, or why it refuses (changes nothing)',
            'Check system','Driver, gamescope, Proton and memory checks for this BC-250 (changes nothing)',
            RISK_ACTION,'Install into one selected game that ships anti-cheat, at the risk of an account ban (asks you to confirm)',
            'Clear','Clear the selection',
            '--text='+('Selected:\n'+'\n'.join(str(p) for p in selected) if selected else 'Frame generation for DirectX 12 games under Proton on the AMD BC-250. Add games to begin.'))
        if action is None:return 0  # Cancel or the window closed: leave Setup
        if not action:continue  # OK with no row chosen
        if action=='Clear':selected=[];continue
        if action=='Add games':
            paths=(dialog('--file-selection','--multiple','--separator=\n','--file-filter=Windows game | *.exe *.EXE') or '').splitlines()
            for path in paths:
                p=Path(path).absolute()
                if p not in selected:selected.append(p)
            continue
        if action=='Check system':show_text(['doctor'],[]);continue
        if action=='Library':selected=select_library(installer,selected);continue
        games=selected
        update_scope=['--component','upscaler'] if action=='Update upscalers' else ['--refresh-recipe'] if action=='Refresh recipe' else []
        if action in ('Update all','Update upscalers','Update selected','Refresh recipe'):
            # Every installed game, no selection needed: the plan first (what changes, what is left and why), then one
            # confirmation. The engine checks launcher closure when its plan changes launcher fields.
            games=selected if action in ('Update selected','Refresh recipe') else update_candidates(installer,selected)
            if not games:dialog('--info','--text=No game with '+NAME+' installed was found in Steam, Heroic or Lutris. Add games to choose them.');continue
            show_text(['plan',*update_scope],games)
            if not prepare_before_update(installer,games,update_scope,action):continue
            if dialog('--question','--width=640','--ok-label=Update','--cancel-label=Back',
                      '--text=Apply the displayed update plan?\nFreeFG, the selected upscaler, OptiScaler and owned launcher fields may change.\n'
                      'Your settings and original backups are retained. Rollback undoes the latest update or provider switch.\n'
                      'Close the games you want to update. Running or unavailable games are deferred; other games can finish.') is None:continue
        elif not selected:dialog('--info','--text=Add games first.');continue
        # Check prints each game's verdict and the redacted report a game report issue asks for (CONTRIBUTING.md).
        if action=='Check':show_text(['check','--report'],selected);continue
        command={'Install':'install','Restore':'restore','Status':'status','Settings':'configure','Upscaler':'configure',RISK_ACTION:'install','Wiki settings':'wiki-apply',
                 'Update all':'update','Update upscalers':'update','Update selected':'update','Refresh recipe':'update','Rollback':'rollback','Register':'register','Pin':'pin','Unpin':'unpin'}[action]
        extra=update_scope
        if action=='Upscaler':
            extra=choose_upscaler(installer,'Close the selected games first. Switch them to this upscaler (each must be installed).\n'
                                  'Upscaler prepares one that is not ready yet, once for every game, and says first what that takes.\n'+HELIXSR_ABOUT,installed=True)
            if not extra:continue
        if action=='Settings':
            selected_settings=dialog('--forms','--width=620','--separator=|',
                '--text=Close the selected games first; the settings apply when a game starts.'+('\nOnly generated frames are scaled. Match output keeps full resolution. OptiScaler also offers these controls under Frame Generation → XeFG scaling.' if SCALING else ''),
                '--add-combo=Frame generation','--combo-values=Keep current|'+'|'.join(FACTORS),
                *(['--add-combo=Generated frames','--combo-values=Keep current|Match output|Scale|720p limit|1080p limit|1440p limit|2160p limit',
                '--add-combo=Downscale','--combo-values=Keep current|Bilinear|Area',
                '--add-combo=Upscale','--combo-values=Keep current|Bilinear|Bicubic|Lanczos2|FSR1 (EASU)'] if SCALING else []))
            selected_settings=selected_settings.split('|') if selected_settings is not None else []
            if not SCALING and len(selected_settings)==1:selected_settings+=['Keep current']*3
            if len(selected_settings)!=4:continue
            factor,resolution,down,up=selected_settings
            if factor in ['2×','3×','4×']:extra+=['--factor',factor[0]]
            if resolution=='Match output':extra+=['--resolution','output']
            elif resolution=='Scale':
                percent=dialog('--scale','--text=Generated-frame width and height (% of output)','--value=75','--min-value=50','--max-value=100','--step=1')
                if not percent:continue
                extra+=['--percent',percent]
            elif resolution.endswith('p limit'):extra+=['--limit',resolution.split('p')[0]]
            if down!='Keep current':extra+=['--downscale',down.lower()]
            if up!='Keep current':extra+=['--upscale','fsr1' if up=='FSR1 (EASU)' else up.lower()]
        if action=='Install':
            extra=install_choices(installer,games)
            if extra is None:continue
        if action=='Wiki settings':
            extra=wiki_choices(installer,selected)
            if extra is None:continue
            games=selected[:1]
        if action==RISK_ACTION:
            # Only the one game the user confirmed: install.py repeats the check and the sentence (CODE=EXE scoping).
            picked=override_anticheat(installer,selected)
            if not picked:continue
            games=[picked[0]]
            extra=install_choices(installer,games,risk=True)
            if extra is None:continue
            extra+=['--accept-anticheat-risk='+str(picked[0]),'--confirm-anticheat-risk',picked[1]]
        if command not in ('status','register','pin','unpin','update') and not wait_closed(installer,games,command in ['install','restore']):continue
        # A Helix upscaler that is not ready: install.py prepares it first, which the progress window says with its time.
        first=preparing(installer,extra) if command in ('install','configure') else None
        working='Working. First setup may download dependencies.' if not first else ' '.join(filter(None,(
            'Preparing '+installer.hlx.NAMES[first]+', then '+('installing' if command=='install' else 'switching')+'.',build_sentence(installer,[first]))))
        with tempfile.TemporaryDirectory(prefix='bc250-xefg-setup-') as temporary:
            output=Path(temporary)/'result.txt'
            result=run_installer([command,*map(str,games),*extra],working,output)
            # 3: refused before anything changed (a game or launcher still running, a refusal); 1: something failed.
            if result==3:
                with output.open('a') as stream:stream.write('\nNothing was changed in the games named above: close them (and their launchers) or do what their message says, then try again.\n')
            elif result:
                with output.open('a') as stream:stream.write('\nSome games could not complete. Read their messages above. For an interrupted update, retry Update or use Rollback. For an interrupted first installation, use Restore.\n')
            dialog('--text-info','--width=1000','--height=650','--filename='+str(output))
    return 0

if __name__=='__main__':sys.exit(main())
