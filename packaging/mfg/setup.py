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

# The upscaler choice (install.py --upscaler). HelixSR is a separate project by lonewolf0622: Setup downloads its official
# release from its GitHub releases when the user asks, and the user builds it once with HelixSR's own setup.
UPSCALER_ROWS=['FSR 4','Default: the BC-250 build of AMD FSR 4, downloaded by checked hash',
               'HelixSR (by lonewolf0622)','NVIDIA’s DLSS network as compute shaders: a separate project by lonewolf0622, under its own licence']
HELIXSR_ABOUT=('HelixSR is a separate project by lonewolf0622 (github.com/lonewolf0622/HelixSR), under its own licence (the '
               'HelixSR Freeware License). It runs NVIDIA’s DLSS network as compute shaders. This package ships none of it.')

def run_and_show(args,text):
    """Run install.py with args under a progress window, then show what it printed."""
    with tempfile.TemporaryDirectory(prefix='bc250-xefg-setup-') as temporary:
        output=Path(temporary)/'result.txt'
        with output.open('w') as stream:
            process=subprocess.Popen([sys.executable,'-u',str(ROOT/'install.py'),*args],stdout=stream,stderr=subprocess.STDOUT)
            progress=subprocess.Popen(['zenity','--progress','--pulsate','--no-cancel','--auto-close','--title='+NAME,'--text='+text],
                                      stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            process.wait()
            try:progress.communicate(b'100\n',timeout=10)
            except (subprocess.TimeoutExpired,BrokenPipeError):progress.terminate();progress.wait()
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

def hlx_ready(installer,provider):
    try:installer.hlx.find(ROOT,provider);return []
    except (OSError,ValueError):pass
    choice=dialog('--list','--width=720','--height=270','--column=Action','--column=Description',
        'Use prepared folder','Select an HLX release already built on this computer',
        'Prepare HLX','Build DLSS and FSR 4 once from local model inputs; no games are changed',
        '--text=HLX preparation is shared by every game. Built model files stay on this computer.')
    if choice=='Use prepared folder':
        folder=dialog('--file-selection','--directory','--title=Prepared HelixSR release folder')
        if not folder:return None
        try:installer.hlx.find(ROOT,provider,folder);return ['--helixsr',folder]
        except (OSError,ValueError) as error:dialog('--error','--text='+str(error));return None
    if choice=='Prepare HLX':
        dlss=dialog('--file-selection','--title=NVIDIA nvngx_dlss.dll model input')
        if not dlss:return None
        amd=dialog('--file-selection','--title=AMD amdxcffx64.dll model input')
        if not amd:return None
        run_and_show(['hlx','--dlss-input',dlss,'--amd-input',amd],'Preparing HLX for all games. This takes several minutes.')
        try:installer.hlx.find(ROOT,provider);return []
        except (OSError,ValueError):return None
    return None


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


def choose_upscaler(installer,text):
    """install.py arguments for the upscaler the user picks, or None (cancelled, or HelixSR not ready yet)."""
    modern=hasattr(installer,'hlx') and bool(installer.hlx.catalog(ROOT))
    rows=(['FSR 4','AMD FSR 4 BC-250 build','HLX DLSS','Helix DLSS network, prepared locally',
           'HLX FSR 4','Helix FSR 4 provider, prepared locally'] if modern else UPSCALER_ROWS)
    choice=dialog('--list','--width=900','--height=300','--column=Upscaler','--column=About',*rows,'--text='+text)
    if not choice:return None
    if choice=='FSR 4':return ['--upscaler','fsr4']
    if modern:
        provider={'HLX DLSS':'hlx-dlss','HLX FSR 4':'hlx-fsr4'}[choice]
        extra=hlx_ready(installer,provider)
        return ['--upscaler',provider,*extra] if extra is not None else None
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

def update_candidates(installer,selected):
    """The games Update all goes through: every game with this build installed that a Steam, Heroic or Lutris entry starts
    (install.py library), and the selected games."""
    try:found=([row['exe'] for row in installer.library_inventory()] if hasattr(installer,'library_inventory') else list(installer.library())) if installer else []
    except Exception:found=[]  # noqa: BLE001 - the selected games are still offered
    return sorted({Path(p).absolute() for p in [*found,*selected]})

def show_text(command,selected):
    """Run install.py command on the selected games and show its output (Check system, Check)."""
    with tempfile.TemporaryDirectory(prefix='bc250-xefg-setup-') as temporary:
        output=Path(temporary)/'result.txt'
        with output.open('w') as stream:subprocess.run([sys.executable,'-u',str(ROOT/'install.py'),*command,*map(str,selected)],stdout=stream,stderr=subprocess.STDOUT)
        dialog('--text-info','--width=1000','--height=600','--filename='+str(output))

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
    upscaler=choose_upscaler(installer,'Choose the upscaler for these games. Frame generation is XeFG with either. Upscaler switches it later.\n'+HELIXSR_ABOUT)
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

def main():
    if not shutil.which('zenity'):
        print('The desktop installer needs zenity. The command-line route is in README.md.',file=sys.stderr);return 1
    selected=[]
    try:installer=load_installer()
    except Exception:installer=None
    while True:
        action=dialog('--list','--width=740','--height=420','--column=Action','--column=Description',
            'Add games','Choose actual game .exe files; repeat to add another folder',
            'Install','Install '+NAME+' into selected games',
            # A 2×-only package (no 3×/4×, no generated-frame scaling) has nothing for Settings to change.
            *(['Settings','Choose '+'/'.join(FACTORS)+(' and generated-frame resolution' if SCALING else ' frame generation')] if MFG and (len(FACTORS)>1 or SCALING) else []),
            'Upscaler','Choose AMD FSR 4, HLX DLSS or HLX FSR 4 for selected games',
            'Update all','Update '+NAME+' in every installed game to this package, keeping settings (shows the plan first)',
            'Update upscalers','Update each selected compatible upscaler across the library, keeping FreeFG and provider selection',
            'Library','Select enrolled games; view versions, last-session logs and recovery'
            ,'Update selected','Preview and update the selected games in place',
            'Refresh recipe','Apply a tested input and launcher recipe in place; game settings stay manual',
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
            if dialog('--question','--width=640','--ok-label=Update','--cancel-label=Back',
                      '--text=Apply the displayed update plan?\nFreeFG, the selected upscaler, OptiScaler and owned launcher fields may change.\n'
                      'Your settings and original backups are retained. Rollback undoes the latest update or provider switch.\n'
                      'Close the games you want to update. Running or unavailable games are deferred; other games can finish.') is None:continue
        elif not selected:dialog('--info','--text=Add games first.');continue
        # Check prints each game's verdict and the redacted report a game report issue asks for (CONTRIBUTING.md).
        if action=='Check':show_text(['check','--report'],selected);continue
        command={'Install':'install','Restore':'restore','Status':'status','Settings':'configure','Upscaler':'configure',RISK_ACTION:'install',
                 'Update all':'update','Update upscalers':'update','Update selected':'update','Refresh recipe':'update','Rollback':'rollback','Register':'register','Pin':'pin','Unpin':'unpin'}[action]
        extra=update_scope
        if action=='Upscaler':
            extra=choose_upscaler(installer,'Close the selected games first. Switch them to this upscaler (each must be installed):\n'+HELIXSR_ABOUT)
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
        if action==RISK_ACTION:
            # Only the one game the user confirmed: install.py repeats the check and the sentence (CODE=EXE scoping).
            picked=override_anticheat(installer,selected)
            if not picked:continue
            games=[picked[0]]
            extra=install_choices(installer,games,risk=True)
            if extra is None:continue
            extra+=['--accept-anticheat-risk='+str(picked[0]),'--confirm-anticheat-risk',picked[1]]
        if command not in ('status','register','pin','unpin','update') and not wait_closed(installer,games,command in ['install','restore']):continue
        with tempfile.TemporaryDirectory(prefix='bc250-xefg-setup-') as temporary:
            output=Path(temporary)/'result.txt'
            with output.open('w') as stream:
                process=subprocess.Popen([sys.executable,'-u',str(ROOT/'install.py'),command,*map(str,games),*extra],stdout=stream,stderr=subprocess.STDOUT)
                progress=subprocess.Popen(['zenity','--progress','--pulsate','--no-cancel','--auto-close','--title='+NAME,'--text=Working. First setup may download dependencies.'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                result=process.wait()
                try:progress.communicate(b'100\n',timeout=10)
                except (subprocess.TimeoutExpired,BrokenPipeError):progress.terminate();progress.wait()
            if result:
                with output.open('a') as stream:stream.write('\nSome games could not complete. Read their messages above. For an interrupted update, retry Update or use Rollback. For an interrupted first installation, use Restore.\n')
            dialog('--text-info','--width=1000','--height=650','--filename='+str(output))
    return 0

if __name__=='__main__':sys.exit(main())
