#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Updated Cyberpunk/HelixSR comparison. Values and provenance live in data.json.

Bars encode output FPS from zero; whiskers show a Student-t 95% interval across independent benchmark runs.
Game-rendered FPS is a separate numeric column. Generate desktop and narrow variants, SVG and PNG.
"""
import json,math,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True
sys.path.insert(0,str(HERE.parent))
import figstyle as s
D=json.loads((HERE/'data.json').read_text())

def render(narrow=False):
    s.setup('freefg-cyberpunk-helixsr'+('-narrow' if narrow else ''))
    W,H=(740 if narrow else 1050),(916 if narrow else 880)
    left=32 if narrow else 48
    x0=230 if narrow else 300
    right=430 if narrow else 738
    out_x=562 if narrow else 890
    game_x=W-left
    fig,ax=s.canvas(W,H)
    s.text(ax,left,49,f"FreeFG {D['freefg']['version']} with HelixSR",31 if narrow else 36,s.INK,'bold')
    subtitle=f"Cyberpunk 2077 {D['game']['version_label']} · AMD BC-250 · 1440p Quality"
    s.text(ax,left,94,subtitle,19 if narrow else 22,s.MUTED)
    s.text(ax,left,128,'Output includes generated frames; game FPS measures rendering.',18 if narrow else 20,s.MUTED)
    groups=[('SDR','sdr'),('HDR10','hdr')]
    rows=D['conditions']
    maximum=max(r['output_fps']['ci95'][1] for r in rows)
    step=20 if maximum<150 else 40
    ceiling=math.ceil(maximum/step)*step
    scale=(right-x0)/ceiling
    colors={'off':s.CHANGE,'i2':s.INTEL,'f2':s.FREEFG}
    names={'off':'No FG','i2':'Intel XeFG 2×','f2':'FreeFG 2×'}
    description=[]
    for gi,(label,key) in enumerate(groups):
        top=184+gi*278
        s.text(ax,left,top,label,23,s.INK,'bold')
        s.text(ax,out_x,top,'Output FPS',18 if narrow else 20,s.MUTED,align='right')
        s.text(ax,game_x,top,'Game FPS',18 if narrow else 20,s.MUTED,align='right')
        selected={r['arm']:r for r in rows if r['range']==key}
        for i,arm in enumerate(('off','i2','f2')):
            row=selected[arm];y=top+48+i*70;v=row['output_fps']['mean'];g=row['game_fps']['mean'];lo,hi=row['output_fps']['ci95']
            s.text(ax,left,y-3,names[arm],21 if narrow else 24,s.INK,'bold')
            if arm=='off':
                s.text(ax,left,y+22,'No generated frames',16 if narrow else 18,s.MUTED)
            if arm=='f2':
                gain=(v/selected['i2']['output_fps']['mean']-1)*100
                s.text(ax,left,y+22,f'{gain:+.1f}% vs Intel',17 if narrow else 19,s.FREEFG)
            ax.barh(y,v*scale,height=28,left=x0,color=colors[arm],edgecolor='none',zorder=3)
            ax.errorbar(x0+v*scale,y,xerr=[[max(0,v-lo)*scale],[max(0,hi-v)*scale]],fmt='none',ecolor=s.INK,elinewidth=1.4,capsize=4,zorder=4)
            s.text(ax,out_x,y,f'{v:.1f}',25 if narrow else 28,colors[arm],'bold',align='right')
            s.text(ax,game_x,y,f'{g:.1f}',23 if narrow else 26,s.INK,align='right')
            description.append(f"{label}, {names[arm]}: output {v:.2f} FPS (95% CI {lo:.2f}–{hi:.2f}), game {g:.2f} FPS, n={row['n']}")
        ax.plot([x0,x0],[top+26,top+210],color=s.LINE,linewidth=1)
    axis_y=716
    for tick in range(0,ceiling+1,step):
        x=x0+tick*scale
        ax.plot([x,x],[axis_y-6,axis_y-2],color=s.LINE,linewidth=1)
        s.text(ax,x,axis_y+13,str(tick),15 if narrow else 17,s.MUTED,align='center')
    foot=[f"{D['method']['runs_per_condition']} runs per condition · whiskers: 95% CI across runs · higher is faster",
          '1706×960 → 2560×1440 · High preset, ray tracing off · DLSS FG input → XeFG',
          f"Headless 240 Hz · warm shader caches · measured {D['date_label']}"]
    if narrow:
        foot=[f"{D['method']['runs_per_condition']} runs per condition · whiskers: 95% CI · higher is faster",
              '1706×960 → 2560×1440 · High preset, ray tracing off',
              'DLSS FG input → XeFG · headless 240 Hz · warm shader caches',
              f"Measured {D['date_label']}"]
    if D['upscaler'].get('reactive_mask') is False:
        foot.append(f"HelixSR {D['upscaler']['version']} · reactive mask off in every condition")
    for i,line in enumerate(foot):s.text(ax,left,772+i*26,line,16 if narrow else 19,s.MUTED)
    s.check_inside(fig,W,H,margin=24)
    stem='cyberpunk-helixsr-fps'+('-narrow' if narrow else '')
    return s.save(fig,stem,f"FreeFG {D['freefg']['version']} with HelixSR — Cyberpunk 2077",
                  subtitle+'. '+ '; '.join(description)+'. '+'. '.join(foot)+'. Source: docs/data/cyberpunk-helixsr/data.json.')

if __name__=='__main__':
    for narrow in (False,True):
        for p in render(narrow):print(p)
