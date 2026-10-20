# SPDX-License-Identifier: MIT
"""The read-only game scanner (packaging/gamescan.py) on synthetic game folders: PE files written here with import,
delay-import and export tables and version resources (no real game file is copied), in Unreal, Unity and Godot layouts,
with anti-cheat folders, other tools' files and launcher records. The scanner must never execute anything."""
import json, os, struct, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'packaging'))
import gamescan as g


# ------------------------------------------------------------------------------------------------ a PE file writer
def _u16z(text):
    return text.encode('utf-16-le') + b'\0\0'


def _pad4(data):
    return data + b'\0' * (-len(data) % 4)


def _block(key, value=b'', value_length=0, wtype=1, children=b''):
    head = _pad4(struct.pack('<HHH', 0, value_length, wtype) + _u16z(key))
    data = _pad4(head + value) + children if children else head + value
    return struct.pack('<H', len(data)) + data[2:]


def version_resource(strings, version=(1, 0, 0, 0)):
    """A VS_VERSIONINFO blob with a fixed file version and StringFileInfo strings."""
    table = _block('040904b0', children=b''.join(_pad4(_block(k, _u16z(v), len(v) + 1)) for k, v in strings.items()))
    sfi = _block('StringFileInfo', children=_pad4(table))
    ms, ls = version[0] << 16 | version[1], version[2] << 16 | version[3]
    fixed = struct.pack('<13I', 0xFEEF04BD, 0x10000, ms, ls, ms, ls, 0x3f, 0, 4, 1, 0, 0, 0)
    return _block('VS_VERSION_INFO', fixed, 52, 0, _pad4(sfi))


def pe(bits=64, dll=False, imports=None, delay=(), exports=(), strings=None, text=(), size=8192):
    """A PE32+ (or PE32) image: one section holding the import, delay-import, export and resource tables, plus text
    (byte strings the scanner searches for), padded to size bytes."""
    sec = bytearray()
    base = 0x1000

    def put(data, align=8):
        sec.extend(b'\0' * (-len(sec) % align))
        rva = base + len(sec)
        sec.extend(data)
        return rva
    dirs = [(0, 0)] * 16
    step = 8 if bits == 64 else 4
    if imports:
        descriptors = []
        for dll_name, funcs in imports.items():
            names = [put(struct.pack('<H', 0) + f.encode() + b'\0', 2) for f in funcs]
            ilt = put(b''.join(n.to_bytes(step, 'little') for n in names) + b'\0' * step)
            iat = put(b''.join(n.to_bytes(step, 'little') for n in names) + b'\0' * step)
            descriptors.append(struct.pack('<IIIII', ilt, 0, 0, put(dll_name.encode() + b'\0'), iat))
        table = b''.join(descriptors) + b'\0' * 20
        dirs[1] = (put(table, 4), len(table))
    if delay:
        table = b''.join(struct.pack('<8I', 1, put(n.encode() + b'\0'), 0, 0, 0, 0, 0, 0) for n in delay) + b'\0' * 32
        dirs[13] = (put(table, 4), len(table))
    if exports:
        names = [put(n.encode() + b'\0') for n in exports]
        name_table = put(b''.join(struct.pack('<I', n) for n in names), 4)
        directory = struct.pack('<IIHHIIIIIII', 0, 0, 0, 0, put(b'module.dll\0'), 1, len(exports), len(exports), 0, name_table, 0)
        dirs[0] = (put(directory, 4), 40)
    if strings is not None:
        blob = version_resource(strings)
        blob_rva = put(blob, 4)
        start = len(sec) + (-len(sec) % 4)
        rsrc = base + start
        # root (type 16) -> name 1 -> language 0x409 -> data entry
        level3 = struct.pack('<IIHHHH', 0, 0, 0, 0, 0, 1) + struct.pack('<II', 0x409, 72)
        level2 = struct.pack('<IIHHHH', 0, 0, 0, 0, 0, 1) + struct.pack('<II', 1, 0x80000000 | 48)
        root = struct.pack('<IIHHHH', 0, 0, 0, 0, 0, 1) + struct.pack('<II', 16, 0x80000000 | 24)
        data_entry = struct.pack('<IIII', blob_rva, len(blob), 0, 0)
        assert put(root + level2 + level3 + data_entry, 4) == rsrc
        dirs[2] = (rsrc, 88)
    for t in text:
        put(t if isinstance(t, bytes) else t.encode())
    raw = bytes(sec) + b'\0' * (-len(sec) % 512)
    machine, magic = (0x8664, 0x20b) if bits == 64 else (0x14c, 0x10b)
    optsize = 240 if bits == 64 else 224
    opt = bytearray(optsize)
    struct.pack_into('<H', opt, 0, magic)
    struct.pack_into('<H', opt, 68, 2)
    ndirs_at = 108 if bits == 64 else 92
    struct.pack_into('<I', opt, ndirs_at, 16)
    for i, (rva, size_) in enumerate(dirs):
        struct.pack_into('<II', opt, ndirs_at + 4 + 8 * i, rva, size_)
    coff = struct.pack('<HHIIIHH', machine, 1, 0, 0, 0, optsize, 0x2022 if dll else 0x22)
    section = struct.pack('<8sIIIIIIHHI', b'.rdata', len(raw), base, len(raw), 0x400, 0, 0, 0, 0, 0x40000040)
    head = bytearray(0x400)
    head[:2] = b'MZ'
    struct.pack_into('<I', head, 60, 0x80)
    header = b'PE\0\0' + coff + bytes(opt) + section
    head[0x80:0x80 + len(header)] = header
    image = bytes(head) + raw
    return image + b'\0' * max(0, size - len(image))


def write(root, files):
    for name, data in files.items():
        path = Path(root)/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
    return Path(root)


# Game layouts used here and in test_compat / the installer tests.
def unreal(root, project='Hero', stub=True, inputs=('dlss',), ue='UE4', native_fg=False):
    shipping = f'{project}/Binaries/Win64/{project}-Win64-Shipping.exe'
    text = ['++' + ue + '+Release-4.27' if ue == 'UE4' else '++UE5+Release-5.3', 'D3D12CreateDevice', 'd3d12.dll']
    text += {'dlss': ['r.NGX.DLSS.Enable'], 'fsr2': ['r.FidelityFX.FSR2.Enabled'], 'xess': ['r.XeSS.Enabled'],
             'dlssg': ['r.Streamline.DLSSG.Enable']}.get(inputs[0], []) if inputs else []
    files = {shipping: pe(imports={'d3d11.dll': ['D3D11CreateDevice'], 'dxgi.dll': ['CreateDXGIFactory1']}, text=text, size=64 << 10),
             'Engine/Binaries/ThirdParty/readme.txt': 'x'}
    if stub:
        files[f'{project}.exe'] = pe(imports={'kernel32.dll': ['CreateProcessW']}, size=16 << 10)
    if 'dlss' in inputs:
        files['Engine/Plugins/DLSS/Binaries/ThirdParty/Win64/nvngx_dlss.dll'] = pe(dll=True)
    if native_fg:
        files[f'{project}/Binaries/Win64/libxess_fg.dll'] = pe(dll=True)
    return write(root, files)


def unity(root, name='Cube', dlss=True, d3d12=True):
    files = {f'{name}.exe': pe(imports={'unityplayer.dll': ['UnityMain']}, size=16 << 10),
             'UnityPlayer.dll': pe(dll=True, imports={'d3d11.dll': ['D3D11CreateDevice'], 'dxgi.dll': ['CreateDXGIFactory1'],
                                                      **({'d3d12.dll': ['D3D12CreateDevice']} if d3d12 else {})}, size=64 << 10),
             f'{name}_Data/globalgamemanagers': 'unity'}
    if dlss:
        files[f'{name}_Data/Plugins/x86_64/nvngx_dlss.dll'] = pe(dll=True)
    return write(root, files)


def steam(home, root_name, appid, name, launch_options=None):
    """A Steam library under home with an app manifest for the folder root_name (and the user's launch options)."""
    steam_root = Path(home)/'.local/share/Steam'
    write(steam_root, {f'steamapps/appmanifest_{appid}.acf': f'"AppState" {{ "appid" "{appid}" "name" "{name}" "installdir" "{root_name}" "StateFlags" "4" }}'})
    if launch_options is not None:
        write(steam_root, {'userdata/42/config/localconfig.vdf':
                           f'"UserLocalConfigStore" {{ "Software" {{ "Valve" {{ "Steam" {{ "apps" {{ "{appid}" {{ "LaunchOptions" "{launch_options}" }} }} }} }} }} }}'})
    return steam_root/'steamapps/common'/root_name


class PeTests(unittest.TestCase):
    def test_tables_and_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'a.dll'
            path.write_bytes(pe(dll=True, imports={'d3d12.dll': ['D3D12CreateDevice'], 'kernel32.dll': ['Sleep']}, delay=['vulkan-1.dll'],
                                exports=['D3D12SDKVersion', 'Other'], strings={'ProductName': 'OptiScaler', 'FileDescription': 'x'}))
            info = g.pe_parse(path)
            self.assertEqual((info['bits'], info['kind'], info['machine']), (64, 'dll', 'x64'))
            self.assertEqual(info['imports']['d3d12.dll'], ['D3D12CreateDevice'])
            self.assertEqual(info['delay_imports'], ['vulkan-1.dll'])
            self.assertEqual(info['exports'], ['D3D12SDKVersion', 'Other'])
            self.assertEqual(info['version']['strings']['ProductName'], 'OptiScaler')
            self.assertEqual(info['version']['file_version'], '1.0.0.0')
            self.assertEqual(g.gfx_imports(info), {'d3d12', 'vulkan'})
            path.write_bytes(pe(bits=32))
            self.assertEqual(g.pe_parse(path)['bits'], 32)
            path.write_bytes(b'MZ' + b'\0' * 100)
            with self.assertRaises(g.PEError):
                g.pe_parse(path)

    def test_installer_fixture_exe_parses(self):
        # The installer tests' 128-byte stand-in executable: parsed, no tables, never an error.
        import test_game_install
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'Game.exe'
            path.write_bytes(test_game_install.exe_bytes())
            info = g.pe_parse(path)
            self.assertEqual((info['bits'], info['imports']), (64, {}))

    def test_d3d9_pix_markers_are_not_a_renderer(self):
        self.assertEqual(g.gfx_imports(dict(imports={'d3d9.dll': ['D3DPERF_BeginEvent']}, delay_imports=[])), set())


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)

    def test_unreal_stub_resolves_to_the_shipping_build(self):
        root = unreal(self.home/'Hero', inputs=('dlss',))
        res = g.scan_folder(dict(path=str(root)), home=self.home)
        self.assertEqual(res['exe']['best'], 'Hero/Binaries/Win64/Hero-Win64-Shipping.exe')
        self.assertEqual(res['engine']['name'], 'unreal')
        self.assertTrue(res['api']['dx12'])
        self.assertEqual(res['api']['switch'], '-dx12')  # Unreal 4: DX11 unless the project chose DX12
        self.assertEqual(res['upscalers'], ['dlss'])
        self.assertTrue(res['dlss_copy'])
        stub = g.scan_folder(dict(path=str(root)), 'Hero.exe', home=self.home)
        self.assertEqual(stub['exe']['stub'], 'Hero/Binaries/Win64/Hero-Win64-Shipping.exe')

    def test_unity_dx12_player_gets_the_unity_switch(self):
        root = unity(self.home/'Cube')
        res = g.scan_folder(dict(path=str(root)), home=self.home)
        self.assertEqual((res['exe']['selected'], res['engine']['name']), ('Cube.exe', 'unity'))
        self.assertTrue(res['api']['dx12'])
        self.assertEqual((res['api']['default'], res['api']['switch']), ('d3d11', '-force-d3d12'))
        self.assertEqual(res['upscalers'], ['dlss'])
        bare = g.scan_folder(dict(path=str(unity(self.home/'Bare', dlss=False))), home=self.home)
        self.assertEqual(bare['upscalers'], [])
        dx11 = g.scan_folder(dict(path=str(unity(self.home/'Old', d3d12=False))), home=self.home)
        self.assertFalse(dx11['api']['dx12'])

    def test_godot_and_vulkan_only(self):
        write(self.home/'Godot', {'Godot.exe': pe(imports={'d3d12.dll': ['D3D12CreateDevice'], 'vulkan-1.dll': ['vkCreateInstance']},
                                                  text=['Godot Engine v4.3.stable'])})
        res = g.scan_folder(dict(path=str(self.home/'Godot')), home=self.home)
        self.assertEqual(res['engine']['name'], 'godot')
        self.assertEqual(res['api']['switch'], '--rendering-driver d3d12')
        write(self.home/'Vk', {'Vk.exe': pe(imports={'vulkan-1.dll': ['vkCreateInstance']})})
        res = g.scan_folder(dict(path=str(self.home/'Vk')), home=self.home)
        self.assertEqual((res['api']['dx12'], res['api']['default']), (False, 'vulkan'))

    def test_native_xess_fg_beside_or_elsewhere(self):
        root = unreal(self.home/'Fg', project='Fg', native_fg=True, inputs=('xess',))
        res = g.scan_folder(dict(path=str(root)), home=self.home)
        self.assertTrue(res['native_xefg'])
        write(root, {'Engine/Plugins/XeSS/Binaries/Win64/libxess_fg.dll': pe(dll=True)})
        (root/'Fg/Binaries/Win64/libxess_fg.dll').unlink()
        res = g.scan_folder(dict(path=str(root)), home=self.home)
        self.assertFalse(res['native_xefg'])
        self.assertEqual(res['native_xefg_elsewhere'], 'Engine/Plugins/XeSS/Binaries/Win64/libxess_fg.dll')
        # The game's own DLL beside the executable with an XeSSMFG folder there: not the automatic native route, but
        # still the game's XeSS FG (a verified native recipe keeps its route: compat.decide).
        write(root, {'Fg/Binaries/Win64/libxess_fg.dll': pe(dll=True), 'Fg/Binaries/Win64/XeSSMFG/settings.ini': '[XeSSMFG]'})
        res = g.scan_folder(dict(path=str(root)), home=self.home)
        self.assertEqual((res['native_xefg'], res['xefg_beside']), (False, True))

    def test_unity_dlss_needs_the_games_code(self):
        # Unity's NVIDIA module bundles nvngx_dlss.dll and NVUnityPlugin.dll; only the game's code says DLSS is used.
        root = unity(self.home/'Plain', dlss=False)
        write(root, {'nvngx_dlss.dll': pe(dll=True), 'NVUnityPlugin.dll': pe(dll=True),
                     'Plain_Data/Managed/Assembly-CSharp.dll': pe(dll=True, text=['PlayerController']),
                     'Plain_Data/Managed/UnityEngine.NVIDIAModule.dll': pe(dll=True, text=['DLSSContext']),
                     'Plain_Data/Managed/Unity.RenderPipelines.Core.Runtime.dll': pe(dll=True, text=['DLSSPerfQualitySetting'])})
        res = g.scan_folder(dict(path=str(root)), home=self.home)
        self.assertEqual(res['upscalers'], [])
        self.assertIn('never names DLSS', res['dlss_unconfirmed'])
        write(root, {'Plain_Data/Managed/Unity.RenderPipelines.HighDefinition.Runtime.dll': pe(dll=True, text=['DLSSPass', 'DLSSContext'])})
        res = g.scan_folder(dict(path=str(root)), home=self.home)
        self.assertEqual((res['upscalers'], res['dlss_unconfirmed']), (['dlss'], None))
        self.assertTrue(any('HighDefinition' in c for c in res['inputs']['dlss']['code']))
        # IL2CPP: the metadata names the types the game's code kept.
        root = unity(self.home/'Cpp', dlss=False)
        write(root, {'nvngx_dlss.dll': pe(dll=True), 'NVUnityPlugin.dll': pe(dll=True), 'GameAssembly.dll': pe(dll=True),
                     'Cpp_Data/il2cpp_data/Metadata/global-metadata.dat': b'\xaf\x1b\xb1\xfa' + b'Player\0ActivateDLSS\0'})
        self.assertEqual(g.scan_folder(dict(path=str(root)), home=self.home)['upscalers'], ['dlss'])
        write(root, {'Cpp_Data/il2cpp_data/Metadata/global-metadata.dat': b'\xaf\x1b\xb1\xfa' + b'Player\0'})
        self.assertIsNotNone(g.scan_folder(dict(path=str(root)), home=self.home)['dlss_unconfirmed'])
        # No game code to read here: the bundled DLL still counts (nothing to contradict it).
        root = unity(self.home/'Unread', dlss=False)
        write(root, {'nvngx_dlss.dll': pe(dll=True), 'NVUnityPlugin.dll': pe(dll=True)})
        self.assertEqual(g.scan_folder(dict(path=str(root)), home=self.home)['upscalers'], ['dlss'])

    def test_anticheat_signatures(self):
        cases = {'eac': ['EasyAntiCheat/Settings.json', 'start_protected_game.exe'], 'eac-proton': ['EasyAntiCheat/easyanticheat_x64.so'],
                 'battleye': ['BattlEye/BEClient_x64.dll', 'Game_BE.exe'], 'gameguard': ['GameGuard/GameGuard.des'],
                 'xigncode': ['xigncode/x3.xem'], 'javelin': ['EAAntiCheat.GameServiceLauncher.exe'], 'ace': ['ACE-Base64.dll'],
                 'none': ['Game_Data/globalgamemanagers', 'UnityPlayer.dll']}
        expect = {'eac': {'Easy Anti-Cheat'}, 'eac-proton': {'Easy Anti-Cheat'}, 'battleye': {'BattlEye'}, 'gameguard': {'nProtect GameGuard'},
                  'xigncode': {'XIGNCODE3'}, 'javelin': {'EA Javelin'}, 'ace': {'Anti-Cheat Expert (ACE)'}, 'none': set()}
        for name, files in cases.items():
            root = write(self.home/name, {f: b'' for f in files + ['Game.exe']})
            found = g.detect_anticheat(g.Tree(root))
            self.assertEqual({a['name'] for a in found}, expect[name], name)
            if name == 'eac-proton':
                self.assertTrue(found[0]['proton_runtime'])

    def test_other_tools_and_installer_files_are_not_the_games(self):
        root = unity(self.home/'Modded', dlss=False)
        write(root, {'dxgi.dll': pe(dll=True, strings={'ProductName': 'OptiScaler'}), 'OptiScaler/OptiScaler.dll': b'x',
                     'nvngx_dlss.dll': pe(dll=True), 'ReShade.ini': '[x]'})
        # An earlier installation created nvngx_dlss.dll (before: null): not the game's DLSS.
        write(root, {'.bc250-xefg-experimental/state.json': json.dumps(dict(package='p', files=[dict(path='nvngx_dlss.dll', before=None)]))})
        res = g.scan_folder(dict(path=str(root)), home=self.home)
        whats = {m['path']: m['what'] for m in res['mods']}
        self.assertEqual(whats['dxgi.dll'], 'OptiScaler')
        self.assertIn('OptiScaler/', [m['what'] for m in res['mods']])
        self.assertIn('created by p', whats['nvngx_dlss.dll'])
        self.assertEqual(res['upscalers'], [])
        self.assertEqual(res['inputs']['dlss']['foreign'][0]['path'], 'nvngx_dlss.dll')
        # A file an installation replaced (before: a digest) still names the game's own input.
        write(root, {'.bc250-xefg-experimental/state.json': json.dumps(dict(files=[dict(path='nvngx_dlss.dll', before='0' * 64)]))})
        self.assertEqual(g.scan_folder(dict(path=str(root)), home=self.home)['upscalers'], ['dlss'])

    def test_native_linux_build_and_32_bit(self):
        write(self.home/'Linux', {'game.x86_64': b'\x7fELF' + b'\0' * 8192})
        res = g.scan_folder(dict(path=str(self.home/'Linux')), home=self.home)
        self.assertIsNone(res['exe']['selected'])
        self.assertEqual(res['exe']['native_linux'], ['game.x86_64'])
        write(self.home/'Old32', {'Old.exe': pe(bits=32, imports={'d3d9.dll': ['Direct3DCreate9']})})
        self.assertEqual(g.scan_folder(dict(path=str(self.home/'Old32')), home=self.home)['exe']['bits'], 32)

    def test_steam_records_launch_options_and_protonfix(self):
        root = steam(self.home, 'Hero Game', 4242, 'Hero Game', launch_options='-dx11 %command%')
        unreal(root)
        steam_root = self.home/'.local/share/Steam'
        write(steam_root, {'config/config.vdf': '"InstallConfigStore" { "Software" { "Valve" { "Steam" { "CompatToolMapping" { '
                                                '"4242" { "name" "GE-Proton11-7" } } } } } }',
                           'compatibilitytools.d/GE-Proton11-7/protonfixes/gamefixes-steam/4242.py':
                           'from protonfixes import util\n\ndef main():\n    util.protontricks(\'d3dx9_43\')\n'
                           '    util.append_argument(\'-fullscreen -vulkan\')\n'})
        games = g.installed_games(self.home)
        self.assertEqual([(x['store'], x['id'], x['name']) for x in games], [('steam', '4242', 'Hero Game')])
        res = g.scan_exe(root/'Hero/Binaries/Win64/Hero-Win64-Shipping.exe', self.home)
        self.assertEqual((res['store'], res['id']), ('steam', '4242'))
        self.assertEqual(res['api']['current_switch'], ['-dx11'])
        self.assertEqual(res['protonfix']['tool'], 'GE-Proton11-7')
        self.assertIn('-vulkan', res['protonfix']['change'])
        self.assertEqual(res['protonfix']['others'], ["protontricks('d3dx9_43')"])  # PROTONFIXES_DISABLE=1 turns these off too

    def test_never_executes_or_writes(self):
        root = unreal(self.home/'Quiet', inputs=('dlss',))
        before = {p: p.stat().st_mtime_ns for p in root.rglob('*')}

        def refuse(*args, **kwargs):
            raise AssertionError('the scanner started a process')
        with patch.object(subprocess, 'run', refuse), patch.object(subprocess, 'Popen', refuse), patch.object(os, 'system', refuse), \
                patch.object(os, 'execv', refuse), patch.object(os, 'execve', refuse), patch.object(os, 'posix_spawn', refuse):
            g.scan_folder(dict(path=str(root)), home=self.home)
            g.scan_exe(root/'Hero.exe', self.home)
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in root.rglob('*')})
        self.assertNotIn('socket', g.__dict__)
        self.assertNotIn('urllib', g.__dict__)


if __name__ == '__main__':
    unittest.main()
