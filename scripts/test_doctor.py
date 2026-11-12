# SPDX-License-Identifier: MIT
"""System check (packaging/doctor.py): a BC-250 gets its GPU-specific checks; any other GPU gets one GPU line naming it
and the experimental BC250_XEFG_ANY_GPU=1 opt-in, and none of the BC-250-only checks (Vulkan compute queue, memory, clock).
The texts follow the package's manifest: the enabler-free proxy build promises neither pacing nor Scale/Limit there."""
import importlib.util, json, sys, tempfile, types, unittest
from pathlib import Path
from unittest.mock import patch

DOCTOR = Path(__file__).resolve().parents[1] / 'packaging/doctor.py'


def card(drm, name, vendor, device, **extra):
    path = drm / name / 'device'
    path.mkdir(parents=True)
    (path / 'vendor').write_text(vendor + '\n')
    (path / 'device').write_text(device + '\n')
    for key, value in extra.items():
        (path / key).write_text(value + '\n')


class Doctor(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('bc250_doctor', DOCTOR)
        self.doctor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.doctor)
        self.queried = []
        self.doctor.vulkan_queue_families = lambda: self.queried.append(1) or [(1 | 2 | 4, 1)]
        self.tmp = tempfile.TemporaryDirectory()
        self.drm = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self, manifest=None):
        package = self.drm / 'package'
        package.mkdir(exist_ok=True)
        if manifest is not None:
            (package / 'manifest.json').write_text(json.dumps(manifest))
        return {item: (level, text) for level, item, text in self.doctor.checks(home=self.drm / 'home', drm=self.drm, package=package)}

    PROXY = dict(name='x-intel-free-2x', addon_entry='libxess_fg-proxy', max_factor=2,
                 files={'payload/libxess_fg.dll': '0' * 64, 'payload/BC250-XeFG/shaders/winograd.required': '0' * 64})
    ENABLER = dict(name='x', files={'payload/version.dll': '0' * 64,
                                    'payload/OptiScaler/plugins/BC250-XeFG/shaders/mfg-frame-settings.required': '0' * 64})

    def test_games_row_points_to_the_compatibility_check(self):
        card(self.drm, 'card0', '0x1002', '0x13fe')
        package = self.drm / 'package'
        package.mkdir()
        (package / 'compat.py').write_text('')
        level, text = self.rows(self.PROXY)['Games']
        self.assertEqual(level, 'INFO')
        self.assertIn('install.py check --all', text)

    def test_proxy_build_on_another_gpu_promises_no_pacing_or_scaling(self):
        card(self.drm, 'card0', '0x1002', '0x731f')
        rows = self.rows(self.PROXY)
        level, text = rows['GPU']
        self.assertEqual(level, 'WARN')
        self.assertIn('not paced', text)
        self.assertIn('no Scale/Limit settings', text)
        self.assertNotIn('paced like', text)
        self.assertNotIn('tries the BC-250 optimisations and the Scale/Limit', text)
        self.assertIn('BC250_XEFG_ANY_GPU=1', text)
        self.assertIn('experimental', text)
        # 2x is Intel's limit on non-Intel GPUs; on an Intel GPU Intel's runtime allows more and the proxy leaves such a
        # context to Intel's shaders, so a native XeSS FG game can run more there (only the OptiScaler routes are set to 2x).
        self.assertIn('2x on a non-Intel GPU', text)
        self.assertIn('on an Intel GPU a native XeSS FG game\'s own setting can ask for more', text)
        self.assertNotIn('2x only', text)
        self.assertIn('beside the game\'s executable', text)  # the proxy writes its logs there, not in OptiScaler/plugins
        self.assertNotIn('OptiScaler/plugins', text)
        self.assertTrue(rows['Build'][1].startswith('2x: one generated frame per real frame'))
        self.assertIn('non-Intel GPU', rows['Build'][1])
        self.assertIn('no Scale/Limit', rows['Build'][1])

    def test_proxy_build_on_an_intel_gpu(self):
        card(self.drm, 'card0', '0x8086', '0xe20b')
        text = self.rows(self.PROXY)['GPU'][1]
        self.assertIn('8086:e20b: not a BC-250', text)
        self.assertIn('a context asking for more keeps Intel\'s shaders', text)
        self.assertIn('installer sets the OptiScaler routes to 2x', text)

    def test_current_proxy_describes_sdk_pacing_and_optional_mfg(self):
        card(self.drm, 'card0', '0x1002', '0x731f')
        rows = self.rows(dict(self.PROXY, variant='intel-free-mfg'))
        self.assertIn("SDK's reported generation, including Intel's shaders", rows['GPU'][1])
        self.assertIn('untested', rows['GPU'][1])
        self.assertIn('no Scale/Limit', rows['GPU'][1])
        self.assertIn('3x/4x through OptiScaler', rows['Build'][1])
        self.assertIn('BC250_XEFG_DISABLE=1', rows['Build'][1])
        self.assertNotIn('not paced', rows['GPU'][1])

    def test_enabler_build_on_another_gpu(self):
        card(self.drm, 'card0', '0x8086', '0xe20b')
        text = self.rows(self.ENABLER)['GPU'][1]
        self.assertIn('experimental', text)
        self.assertIn('Scale/Limit settings on that GPU', text)
        self.assertIn('OptiScaler/plugins', text)
        self.assertNotIn('paced like on the BC-250', text)
        without = dict(self.ENABLER, files={'payload/version.dll': '0' * 64})  # the Intel-free build: no scaling
        self.assertNotIn('Scale/Limit settings on that GPU', self.rows(without)['GPU'][1])

    def test_bc250_with_the_proxy_build(self):
        card(self.drm, 'card1', '0x1002', '0x13fe')
        rows = self.rows(self.PROXY)
        self.assertEqual(rows['GPU'], ('OK', 'AMD BC-250 (Cyan Skillfish, 0x13fe)'))
        self.assertTrue(rows['Build'][1].startswith('2x: '))
        self.assertIn('Compute queue', rows)

    def test_kernel_line_names_the_checked_kernel(self):
        level, text = self.rows()['Kernel']
        self.assertEqual(level, 'INFO')
        self.assertIn('linux-cachyos-bc250 7.3.0-2.326', text)
        self.assertNotIn('7.2.7-1.212', text)

    def test_no_manifest_no_build_line(self):
        self.assertNotIn('Build', self.rows())
        (self.drm / 'package' / 'manifest.json').write_text('not json')
        self.assertNotIn('Build', self.rows())

    def test_other_gpu(self):
        card(self.drm, 'card1', '0x1002', '0x731f')
        (self.drm / 'card1-DP-1').mkdir()  # a connector, not a card
        rows = self.rows()
        level, text = rows['GPU']
        self.assertEqual(level, 'WARN')
        self.assertIn('1002:731f: not a BC-250', text)
        self.assertIn('BC250_XEFG_ANY_GPU=1', text)
        self.assertIn("Intel's shaders", text)
        for item in ('Vulkan', 'Compute queue', 'Memory', 'GPU clock'):
            self.assertNotIn(item, rows)
        self.assertEqual(self.queried, [])

    def test_two_gpus_one_bc250(self):
        card(self.drm, 'card0', '0x10de', '0x2684')
        card(self.drm, 'card1', '0x1002', '0x13fe', mem_info_gtt_total=str(6 << 30), mem_info_vram_total=str(512 << 20),
             pp_dpm_sclk='0: 1000Mhz\n1: 1850Mhz *')
        rows = self.rows()
        self.assertEqual(rows['GPU'][0], 'OK')
        self.assertNotIn('BC250_XEFG_ANY_GPU', rows['GPU'][1])
        self.assertIn('Memory', rows)
        self.assertEqual(rows['GPU clock'][0], 'OK')
        self.assertEqual(self.queried, [1])

    def test_no_gpu(self):
        level, text = self.rows()['GPU']
        self.assertEqual(level, 'WARN')
        self.assertTrue(text.startswith('No BC-250 GPU found'))
        self.assertIn('BC250_XEFG_ANY_GPU=1', text)

    def layer_package(self, glibc='2.34'):
        package = self.drm / 'package'
        (package / 'payload/BC250-XeFG/layer').mkdir(parents=True, exist_ok=True)
        (package / self.doctor.LAYER).write_bytes(b'\x7fELF')
        manifest = dict(self.PROXY, variant='intel-free-mfg')
        if glibc:
            manifest['present_pacing'] = dict(layer_sha256='0' * 64, build='gcc', glibc=glibc)
        (package / 'manifest.json').write_text(json.dumps(manifest))
        return package

    def test_pacing_layer_loads_and_names_its_glibc(self):
        package = self.layer_package()
        level, item, text = self.doctor.layer_row(package, glibc=(2, 44), load=lambda path: (True, ''))
        self.assertEqual((level, item), ('OK', 'Pacing layer'))
        self.assertIn('needs glibc 2.34; this system has glibc 2.44', text)
        self.assertIsNone(self.doctor.layer_row(self.drm / 'elsewhere'))  # the source tree: no layer, no row

    def test_pacing_layer_on_an_older_glibc(self):
        package = self.layer_package()
        loads = []
        level, _item, text = self.doctor.layer_row(package, glibc=(2, 31), load=lambda path: loads.append(path) or (True, ''))
        self.assertEqual(level, 'WARN')
        self.assertIn('needs glibc 2.34; this system has glibc 2.31', text)
        self.assertIn('not paced', text)
        self.assertEqual(loads, [package / self.doctor.LAYER])  # the load is still tried, in a process of its own

    def test_pacing_layer_that_does_not_load(self):
        package = self.layer_package(glibc=None)  # a manifest from before the glibc record: the load decides
        reason = "version `GLIBC_2.38' not found (required by libxefg_wave.so)"
        level, _item, text = self.doctor.layer_row(package, glibc=(2, 36), load=lambda path: (False, reason))
        self.assertEqual(level, 'WARN')
        self.assertIn(reason, text)
        self.assertIn('this system has glibc 2.36', text)
        self.assertEqual(self.doctor.layer_row(package, glibc=(2, 36), load=lambda path: (None, 'TimeoutExpired'))[0], 'INFO')

    def test_pacing_layer_load_runs_apart(self):
        package = self.layer_package()
        loaded, reason = self.doctor.layer_load(package / self.doctor.LAYER)  # not a loadable object: refused, no crash here
        self.assertIs(loaded, False)
        self.assertTrue(reason)
        self.assertIn('Pacing layer', {item for _level, item, _text in self.doctor.checks(home=self.drm / 'home', drm=self.drm,
                                                                                            package=package)})


def fake_hlx(ready, missing=()):
    """An hlx module for the Helix row: HelixSR's four upscalers, those in ready prepared on this computer; missing: what
    building HLX DLSS needs and this computer lacks (hlx.requirements)."""
    module = types.ModuleType('hlx')
    module.NAMES = {'hlx-dlss': 'HLX DLSS Model E', 'hlx-dlss-k': 'HLX DLSS Preset K', 'hlx-fsr4': 'HLX FSR 4',
                    'hlx-fsr4-full': 'HLX FSR 4 Full'}
    module.SUGGESTED = 'hlx-dlss'
    module.OPTIONAL = ('hlx-dlss-k',)
    spec = {'format': 2, 'version': '3.3.0', 'archive': {'size': 279494747},
            'providers': {'hlx-dlss': {'build': 'network'}, 'hlx-dlss-k': {'build': 'preset-k'}, 'hlx-fsr4': {}, 'hlx-fsr4-full': {}}}
    module.catalog = lambda package: spec
    module.built = lambda spec, provider: spec['providers'][provider].get('build')
    module.requirements = lambda: list(missing)

    def find(package, provider, explicit=None):
        if provider not in ready:
            raise ValueError('Prepare Helix 3.3.0 once (' + module.NAMES[provider] + '): missing /cache/x')
        return spec, Path('/cache/HelixSR-3.3.0'), {}
    module.find = find
    return module


class HelixRow(unittest.TestCase):
    """The system check's row for HelixSR's four upscalers: which are ready, the suggested one, and how the rest get ready:
    Install prepares one on first use, so the row never tells the user to prepare anything first."""
    ALL = ['hlx-dlss', 'hlx-dlss-k', 'hlx-fsr4', 'hlx-fsr4-full']

    def setUp(self):
        spec = importlib.util.spec_from_file_location('bc250_doctor_helix', DOCTOR)
        self.doctor = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.doctor)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.package = Path(self.tmp.name)
        (self.package / 'dependencies.json').write_text(json.dumps({'hlx': {'format': 2}}))

    def row(self, ready, missing=()):
        with patch.dict(sys.modules, {'hlx': fake_hlx(ready, missing)}):
            return self.doctor.helixsr_row(self.package / 'home', self.package)

    def test_everything_ready(self):
        level, item, text = self.row(self.ALL, missing=['wine'])  # what a build would need no longer matters
        self.assertEqual((level, item), ('OK', 'Helix'))
        self.assertTrue(text.startswith('ready: HLX DLSS Model E (suggested), HLX DLSS Preset K, HLX FSR 4, HLX FSR 4 Full (optional'))
        self.assertIn('HelixSR 3.3.0, a separate project by lonewolf0622', text)
        for word in ('prepares', 'downloaded', 'not built', 'wine'):
            self.assertNotIn(word, text)

    def test_preset_k_is_optional(self):
        # Not built is not a problem: the row stays OK and says how it gets built.
        level, _, text = self.row(['hlx-dlss', 'hlx-fsr4', 'hlx-fsr4-full'])
        self.assertEqual(level, 'OK')
        self.assertIn('HLX DLSS Preset K is optional and not built: choosing it for a game builds it, about 30 minutes more.', text)
        self.assertNotIn('Install prepares', text)
        self.assertNotIn('downloaded on first use', text)
        # Where its build cannot run, the row names what is missing; still nothing to worry about.
        level, _, text = self.row(['hlx-dlss', 'hlx-fsr4', 'hlx-fsr4-full'], missing=['wine', 'Python numpy'])
        self.assertEqual(level, 'OK')
        self.assertIn('about 30 minutes more, once wine, Python numpy are installed.', text)

    def test_install_prepares_the_suggested_upscaler_on_first_use(self):
        level, _, text = self.row(['hlx-fsr4', 'hlx-fsr4-full'])
        self.assertEqual(level, 'INFO')  # never a warning: FSR 4 needs none of it
        self.assertTrue(text.startswith('ready: HLX FSR 4, HLX FSR 4 Full ('))
        self.assertIn('Install prepares HLX DLSS Model E (suggested) on first use, once for every game', text)
        self.assertIn('it downloads HelixSR\'s official archive (about 280 MB) and NVIDIA\'s DLSS DLL (from NVIDIA\'s repository, '
                      'under NVIDIA\'s licence) and builds the upscaler on this computer, about 15 minutes on a BC-250', text)
        self.assertIn('Nothing has to be prepared first (Setup\'s Install, or install.py install GAME.exe --upscaler hlx-dlss).', text)
        self.assertIn('HLX DLSS Preset K is optional', text)
        # The row no longer sends the user to prepare anything, and a new installation no longer falls back to FSR 4.
        for words in ('Prepare in Setup', 'install.py hlx', 'takes FSR 4', 'downloaded on first use'):
            self.assertNotIn(words, text)

    def test_a_build_that_cannot_run_here_names_what_is_missing(self):
        level, _, text = self.row(['hlx-fsr4', 'hlx-fsr4-full'], missing=['bwrap', 'Python numpy'])
        self.assertEqual(level, 'INFO')  # still no warning: FSR 4 and the two that come built need none of it
        self.assertIn('HLX DLSS Model E (suggested) cannot be built on this computer yet: its build needs bwrap, Python numpy. '
                      'Until they are installed, a new installation takes FSR 4.', text)
        self.assertNotIn('Install prepares', text)
        level, _, text = self.row([], missing=['wine'])
        self.assertIn('its build needs wine. Until that is installed, a new installation takes FSR 4.', text)
        # The two that come built are still downloaded on first use, with the archive's size named here.
        self.assertIn('HLX FSR 4 and HLX FSR 4 Full are downloaded on first use with HelixSR\'s official archive (about 280 MB), '
                      'which they come built in: nothing is built.', text)
        # A check of the requirements that fails leaves them to install.py, which checks before it builds.
        broken = fake_hlx([])
        broken.requirements = lambda: (_ for _ in ()).throw(RuntimeError('no numpy check'))
        with patch.dict(sys.modules, {'hlx': broken}):
            _, _, text = self.doctor.helixsr_row(self.package / 'home', self.package)
        self.assertIn('Install prepares HLX DLSS Model E (suggested) on first use', text)

    def test_the_two_that_come_built_are_downloaded_on_first_use(self):
        level, _, text = self.row(['hlx-dlss'])
        self.assertEqual(level, 'INFO')
        self.assertIn('HLX FSR 4 and HLX FSR 4 Full are downloaded on first use with HelixSR\'s official archive (about 280 MB), '
                      'which they come built in: nothing is built.', text)
        self.assertNotIn('Install prepares', text)
        level, _, text = self.row(['hlx-dlss', 'hlx-fsr4'])
        self.assertEqual(level, 'INFO')
        self.assertIn('HLX FSR 4 Full is downloaded on first use with HelixSR\'s official archive (about 280 MB), which it comes '
                      'built in', text)

    def test_nothing_prepared(self):
        level, item, text = self.row([])
        self.assertEqual((level, item), ('INFO', 'Helix'))
        self.assertTrue(text.startswith('none is ready on this computer ('))
        for words in ('Install prepares HLX DLSS Model E (suggested) on first use',
                      'HLX FSR 4 and HLX FSR 4 Full are downloaded on first use with that archive',
                      'HLX DLSS Preset K is optional and not built'):
            self.assertIn(words, text)
        self.assertEqual(text.count('280 MB'), 1)  # the archive is one download, named once
        self.assertTrue(text.isascii())  # the check prints to any terminal
        self.assertNotIn('!', text)

    def test_the_row_is_part_of_the_check_and_never_a_warning(self):
        with patch.dict(sys.modules, {'hlx': fake_hlx([])}):
            rows = {item: level for level, item, _ in self.doctor.checks(home=self.package / 'home', drm=self.package / 'drm',
                                                                          package=self.package)}
        self.assertEqual(rows['Helix'], 'INFO')
        self.assertNotIn('HelixSR', rows)

    def test_a_catalog_this_installer_cannot_read_is_said_and_stops_nothing(self):
        broken = fake_hlx([])
        broken.catalog = lambda package: (_ for _ in ()).throw(ValueError('Unsupported HLX catalog; use its matching installer'))
        with patch.dict(sys.modules, {'hlx': broken}):
            self.assertEqual(self.doctor.helixsr_row(self.package / 'home', self.package),
                             ('INFO', 'Helix', 'cannot check: Unsupported HLX catalog; use its matching installer'))
            rows = [item for _, item, _ in self.doctor.checks(home=self.package / 'home', drm=self.package / 'drm', package=self.package)]
        self.assertIn('Helix', rows)
        self.assertIn('Setup tools', rows)

    def test_this_package_with_nothing_prepared(self):
        # The real catalog and hlx.py, on an empty cache: every upscaler named once, by how it gets ready. What the
        # build needs is whatever this computer has (hlx.requirements is asked for real, and never fails the row).
        import os
        packaging = DOCTOR.parent
        with patch.dict(os.environ, {'XDG_CACHE_HOME': self.tmp.name, 'HOME': self.tmp.name}), \
                patch.object(sys, 'path', [str(packaging), *sys.path]), patch.dict(sys.modules):
            sys.modules.pop('hlx', None)
            level, item, text = self.doctor.helixsr_row(self.package / 'home', packaging)
        self.assertEqual((level, item), ('INFO', 'Helix'))
        for name in ('HLX DLSS Model E (suggested)', 'HLX DLSS Preset K', 'HLX FSR 4 and HLX FSR 4 Full'):
            self.assertEqual(text.count(name), 1, name)
        self.assertTrue('Install prepares HLX DLSS Model E (suggested) on first use' in text or
                        'cannot be built on this computer yet: its build needs' in text)


if __name__ == '__main__':
    unittest.main()
