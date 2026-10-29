#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only update adapters for the selected super-resolution provider.

Adapters return bytes or pinned dependency references; only the installer's transaction engine writes game files.
Provider selection, FG settings and installation of an unknown provider are separate operations.
"""
import hashlib
from pathlib import Path
import helixsr

DLL = 'amd_fidelityfx_upscaler_dx12.dll'


def _fsr4(package, record, pins, files, prepared, installed):
    current = record['upscaler']
    runtime = pins['runtime']
    source = runtime.get('ProxyPackage', {}).get('fsr4/' + DLL)
    if not source:
        return {'deferred': 'This package has no compatible FSR 4 dependency.'}
    descriptor = (pins.get('upscalers') or {}).get('fsr4') or {}
    metadata = dict(current)
    if descriptor.get('version'):
        metadata['version'] = descriptor['version']
    archive = (pins.get('inputs') or {}).get(descriptor.get('input', 'fsr4')) or {}
    if archive.get('sha256'):
        metadata.update(source_archive_sha256=archive['sha256'], adapter='fidelityfx-pinned-v1')
    return {'component': 'fsr4', 'target': current['target'], 'data': files.get('fsr4/' + DLL),
            'dependency': source, 'sha256': runtime['Files'][source], 'metadata': metadata}


def _helixsr(package, record, pins, files, prepared, installed):
    current = record['upscaler']
    pin = helixsr.pins(package)
    if pin is None:
        return {'deferred': 'This package has no qualified HelixSR update.'}
    preferred = pin.get('PreferredBaseHash')
    candidates = [sha for sha, version in pin['Releases'].items() if version == pin['Version']]
    if preferred is not None and preferred not in candidates:
        raise ValueError('HelixSR preferred code hash is not a pin for the selected release')
    if preferred is None:
        if len(candidates) != 1:
            return {'deferred': 'The HelixSR catalog must identify one preferred archive revision.'}
        preferred = candidates[0]
    metadata = dict(current, version=pin['Version'], source_archive_sha256=pin['input']['sha256'],
                    code_sha256=preferred, adapter='helixsr-ffx-network-v1')
    # An already current, owned DLL needs no copy of its original setup folder. The game remains portable after
    # the user deletes the download cache. An explicit prepared build still permits a deliberate network refresh.
    if prepared is None and installed is not None and installed.is_file():
        data = installed.read_bytes()
        network = helixsr.network_size(installed)
        owned = next((row['after'] for row in record['files'] if row['path'] == current['target']), None)
        if network is not None and hashlib.sha256(data).hexdigest() == owned and hashlib.sha256(data[:-network]).hexdigest() == preferred:
            return {'component': 'helixsr', 'target': current['target'], 'data': data, 'dependency': None,
                    'sha256': owned, 'metadata': metadata}
    found = None
    folders = [Path(prepared).absolute()] if prepared is not None else helixsr.candidates(pin)
    for folder in folders:
        candidate = helixsr.check_release(folder, pin)
        if candidate.get('state') != 'ready' or candidate.get('version') != pin['Version']:
            continue
        candidate_data = helixsr.dll_bytes(candidate, pin)
        network = helixsr.network_size(Path(candidate['dll']))
        if network is not None and hashlib.sha256(candidate_data[:-network]).hexdigest() == preferred:
            found, data = candidate, candidate_data
            break
    if found is None:
        guidance = helixsr.find(package, explicit=prepared)
        return {'deferred': 'Prepare HelixSR ' + pin['Version'] + ' once with its own setup, then retry Update all. ' +
                'The prepared code must match the pinned archive revision. ' + helixsr.guidance(guidance)}
    metadata.update(release=found['folder'])
    return {'component': 'helixsr', 'target': current['target'], 'data': data, 'dependency': None,
            'sha256': hashlib.sha256(data).hexdigest(), 'metadata': metadata}


ADAPTERS = {'fsr4': _fsr4, 'helixsr': _helixsr}


def plan(package, record, pins, files, prepared=None, installed=None):
    """Update the existing provider only. A missing/unqualified build is deferred without touching it."""
    selected = record.get('upscaler') or {}
    if not selected.get('target'):
        return {'deferred': 'The installed upscaler has no owned target; import or repair its record first.'}
    adapter = ADAPTERS.get(selected.get('name'))
    if adapter is None:
        return {'deferred': 'No qualified update adapter for ' + str(selected.get('name')) + '; its files stay unchanged.'}
    descriptor = (pins.get('upscalers') or {}).get(selected['name']) or {}
    expected = {'fsr4': 'fidelityfx-pinned-v1', 'helixsr': 'helixsr-ffx-network-v1'}[selected['name']]
    if descriptor.get('adapter', expected) != expected:
        return {'deferred': 'This upscaler requires a newer integration adapter; its files stay unchanged.'}
    return adapter(Path(package), record, pins, files, prepared, installed)
