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

def main():
    if not shutil.which('zenity'):
        print('The desktop installer needs zenity. The command-line route is in README.md.',file=sys.stderr);return 1
    selected=[]
    try:installer=load_installer()
    except Exception:installer=None
    while True:
        action=dialog('--list','--width=740','--height=400','--column=Action','--column=Description',
            'Add games','Choose actual game .exe files; repeat to add another folder',
            'Install','Install '+NAME+' into selected games',
            # A 2×-only package (no 3×/4×, no generated-frame scaling) has nothing for Settings to change.
            *(['Settings','Choose '+'/'.join(FACTORS)+' and generated-frame resolution'] if MFG and len(FACTORS)>1 else []),
            'Restore','Restore original files in selected games',
            'Status','Check installed files and the last acceleration log',
            'Check system','Driver, gamescope, Proton and memory checks for this BC-250 (changes nothing)',
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
        if action=='Check system':
            with tempfile.TemporaryDirectory(prefix='bc250-xefg-setup-') as temporary:
                output=Path(temporary)/'result.txt'
                with output.open('w') as stream:subprocess.run([sys.executable,'-u',str(ROOT/'install.py'),'doctor'],stdout=stream,stderr=subprocess.STDOUT)
                dialog('--text-info','--width=1000','--height=500','--filename='+str(output))
            continue
        if not selected:dialog('--info','--text=Add games first.');continue
        command={'Install':'install','Restore':'restore','Status':'status','Settings':'configure'}[action];extra=[]
        if action=='Settings':
            selected_settings=dialog('--forms','--width=620','--separator=|',
                '--text=Close the selected games first; the settings apply when a game starts.\nOptiScaler also has these controls under Frame Generation → XeFG scaling.',
                '--add-combo=Frame generation','--combo-values=Keep current|'+'|'.join(FACTORS),
                '--add-combo=Generated frames','--combo-values=Keep current|Match output|Scale|720p limit|1080p limit|1440p limit|2160p limit',
                '--add-combo=Downscale','--combo-values=Keep current|Bilinear|Area',
                '--add-combo=Upscale','--combo-values=Keep current|Bilinear|Bicubic|Lanczos2|FSR1 (EASU)')
            selected_settings=selected_settings.split('|') if selected_settings is not None else []
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
            # What each selected game ships, so the input can be chosen per batch (install.detect_input's scan).
            try:found='\n'.join(Path(exe).name+': '+installer.detect_input(Path(exe))[2] for exe in selected[:8])
            except Exception:found=''
            route=dialog('--list','--width=850','--height=420','--column=Route','--column=Use',
                'Automatic','Native XeSS FG where the game ships it, otherwise OptiFG; reports other FG inputs each game has',
                'OptiFG','Games without native FG: uses the upscaler input; may affect HUDs',
                'DLSS FG','Games with supported DLSS FG (Streamline 2+)',
                'FSR 3.1 FG','Games with native FSR 3.1 frame generation',
                'FSR 3.0 FG','Games with native FSR 3.0 frame generation',
                'Native XeSS FG','Games with native XeSS FG DLL beside the executable',
                '--text=Choose the same input for these games, or Automatic. Prefer a native FG input when available.\nAll OptiScaler routes use XeFG output. '+('Frame generation defaults to 2×.' if MFG and len(FACTORS)>1 else 'Frame generation is 2×.')+' Per-game recipes verified on a BC-250 are applied (Automatic also takes their input); OptiScaler wiki notes are listed.'+('\n\nFound:\n'+found if found else ''))
            source={'OptiFG':'upscaler','DLSS FG':'dlssg','FSR 3.1 FG':'fsrfg','FSR 3.0 FG':'fsrfg30'}
            if not route:continue
            extra=['--route','auto','--fg-input','auto'] if route.startswith('Automatic') else ['--route','native'] if route=='Native XeSS FG' else ['--route','opti','--fg-input',source[route]]
            if dialog('--question','--width=680','--text=Setup will configure '+NAME+' and each game’s launch settings.\nThe first installation downloads checked upstream files (FSR4 and Intel’s XeFG runtime);\na fresh OptiScaler setup also fetches OptiScaler and OptiPatcher, and NVIDIA’s DLSS helper only for a DLSS input\nwhere OptiScaler finds no copy of the game’s own.\nAfter installation, reopen your launcher and play normally.') is None:continue
        if command!='status' and not wait_closed(installer,selected,command in ['install','restore']):continue
        with tempfile.TemporaryDirectory(prefix='bc250-xefg-setup-') as temporary:
            output=Path(temporary)/'result.txt'
            with output.open('w') as stream:
                process=subprocess.Popen([sys.executable,'-u',str(ROOT/'install.py'),command,*map(str,selected),*extra],stdout=stream,stderr=subprocess.STDOUT)
                progress=subprocess.Popen(['zenity','--progress','--pulsate','--no-cancel','--auto-close','--title='+NAME,'--text=Working. First setup may download dependencies.'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                result=process.wait()
                try:progress.communicate(b'100\n',timeout=10)
                except (subprocess.TimeoutExpired,BrokenPipeError):progress.terminate();progress.wait()
            if result:
                with output.open('a') as stream:stream.write('\nSome games could not complete. Read their messages above. If an install was interrupted after saving backups, use Restore before retrying.\n')
            dialog('--text-info','--width=1000','--height=650','--filename='+str(output))
    return 0

if __name__=='__main__':sys.exit(main())
