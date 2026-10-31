# SPDX-License-Identifier: MIT
"""System check (packaging/doctor.py): a BC-250 gets its GPU-specific checks; any other GPU gets one GPU line naming it
and the experimental BC250_XEFG_ANY_GPU=1 opt-in, and none of the BC-250-only checks (Vulkan compute queue, memory, clock).
The texts follow the package's manifest: the enabler-free proxy build promises neither pacing nor Scale/Limit there."""
import importlib.util, json, tempfile, unittest
from pathlib import Path

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


if __name__ == '__main__':
    unittest.main()
