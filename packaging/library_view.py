# SPDX-License-Identifier: MIT
"""Read-only library presentation. Mutations are delegated to install.py's transaction engine."""
import json
from pathlib import Path


def rows(installer):
    result=[]
    for item in installer.library_inventory():
        exe=Path(item['exe'])
        row=dict(exe=str(exe),title=exe.stem,release=item.get('package') or 'Unknown',
                 provider=item.get('upscaler') or 'Unknown',files=item['status'].capitalize(),
                 runtime='No recent log',recovery='None',pin='Pinned' if item.get('pinned') else 'Updates enabled')
        if item['status']=='installed':
            try:
                record=json.loads(installer.safe(exe.parent,installer.STATE+'/state.json').read_text())
                row['title']=(record.get('recipe') or {}).get('title') or exe.stem
                provider=record.get('upscaler') or {}
                row['provider']=provider.get('name','Unknown')+(' '+provider['version'] if provider.get('version') else '')
                row['files']='Check with Status'
                if record.get('pending_update'):
                    row['recovery']='Interrupted update';row['files']='Recovery needed'
                elif record.get('generations'):row['recovery']='Rollback available'
                import compat
                last=compat.last_run(exe.parent,record.get('route'),**installer.run_scope(record))
                if last['found']:
                    row['runtime']='Log: '+({'full':'acceleration active','partial':'partial acceleration',
                        'idle':'no FG context','not-running':'acceleration inactive'}.get(last.get('acceleration'),'startup only'))
            except (OSError,ValueError,KeyError) as error:row['files']='Needs attention: '+str(error)
        result.append(row)
    return result
