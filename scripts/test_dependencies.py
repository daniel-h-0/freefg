# SPDX-License-Identifier: MIT
"""dependencies.py and dependencies.json: pinned upstream files fetched by group into the user's cache, from local fixture
archives (file:// URLs, nothing leaves the machine), and the pins the package ships."""
import contextlib, hashlib, importlib.util, io, json, os, shutil, subprocess, sys, tempfile, unittest, urllib.error, urllib.request, zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_game_install as fixtures

PACKAGING = Path(__file__).resolve().parents[1]/'packaging'
spec = importlib.util.spec_from_file_location('bc250_dependencies', PACKAGING/'dependencies.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
REAL_PREPARE = fixtures.m.prepare_dependencies  # before any fixture replaces it
REAL_URLOPEN = urllib.request.urlopen


def sha(data):
    return hashlib.sha256(data).hexdigest()


# Fixture upstream files for the whole-file inputs (Intel's repository files, OptiPatcher, NVIDIA's DLSS files): input key ->
# (pinned name, group). Intel's three are also members of the fixture OptiScaler archive, their mirror, as upstream.
PLAIN = {'xess_fg': ('OptiScaler/libxess_fg.dll', 'runtime'), 'xell': ('OptiScaler/libxell.dll', 'runtime'),
         'xess_license': ('Licenses/XeSS_LICENSE.txt', 'runtime'), 'patcher': ('OptiScaler/plugins/OptiPatcher.asi', 'payload'),
         'dlss': ('nvngx_dlss.dll', 'dlss'), 'dlss_license': ('Licenses/NVIDIA-DLSS-LICENSE.txt', 'dlss')}
MIRRORED = {'xess_fg', 'xell', 'xess_license'}


def upstream(root, dependencies):
    """Fixture upstream downloads holding the fixture files of dependencies (by group, as test_game_install's): an
    OptiScaler 7z, a FSR4 release zip with its notices, and plain files. Returns dependencies.json for them."""
    root.mkdir(parents=True)
    tree = root/'opti-tree'
    whole = {name for key, (name, _) in PLAIN.items() if key not in MIRRORED}
    opti_names = [n for group in ('payload', 'runtime') for n in dependencies[group] if not n.startswith('fsr4/') and n not in whole]
    for name in opti_names:
        data = dependencies['payload'].get(name, dependencies['runtime'].get(name))
        (tree/name).parent.mkdir(parents=True, exist_ok=True)
        (tree/name).write_bytes(data)
    subprocess.run(['bsdtar', '--format', '7zip', '-cf', str(root/'opti.7z'), *sorted({n.split('/')[0] for n in opti_names})], cwd=tree, check=True)
    with zipfile.ZipFile(root/'fsr4.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(fixtures.m.DLL, dependencies['runtime']['fsr4/'+fixtures.m.DLL])
        z.writestr('notices/LICENSE.new-code', b'MIT notice')
        z.writestr('README.md', b'not pinned')
    for key, (name, group) in PLAIN.items():
        (root/key).write_bytes(dependencies[group][name])
    inputs = {}
    for key, name in [('opti', 'opti.7z'), ('fsr4', 'fsr4.zip'), *((key, key) for key in PLAIN)]:
        data = (root/name).read_bytes()
        inputs[key] = dict(url=(root/name).as_uri(), file=key + '-' + name, sha256=sha(data), size=len(data))
    pins = fixtures.pins_for(dependencies)
    pins['runtime']['Files']['fsr4/notices/LICENSE.new-code'] = sha(b'MIT notice')
    sources = {name: {'input': key} for key, (name, _) in PLAIN.items()}
    for key in MIRRORED:
        sources[PLAIN[key][0]]['mirrors'] = [{'input': 'opti', 'member': PLAIN[key][0]}]
    sources.update({'fsr4/' + fixtures.m.DLL: {'input': 'fsr4', 'member': fixtures.m.DLL},
                    'fsr4/notices/LICENSE.new-code': {'input': 'fsr4', 'member': 'notices/LICENSE.new-code'}})
    pins.update(inputs=inputs, sources=sources)
    return pins


@unittest.skipUnless(shutil.which('bsdtar'), 'needs bsdtar')
class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pins = upstream(self.root/'upstream', fixtures.DEPENDENCIES)
        self.package = self.root/'package'
        self.package.mkdir()
        self.write_pins()
        self.downloads = []

        def urlopen(request, timeout=None):
            self.downloads.append(request.full_url.rsplit('/', 1)[1])
            return REAL_URLOPEN(request, timeout=timeout)
        for context in (patch.dict(os.environ, XDG_CACHE_HOME=str(self.root/'cache')), patch.object(d.urllib.request, 'urlopen', side_effect=urlopen),
                        contextlib.redirect_stdout(io.StringIO())):
            context.__enter__()
            self.addCleanup(context.__exit__, None, None, None)

    def write_pins(self):
        (self.package/'dependencies.json').write_text(json.dumps(self.pins))

    def test_default_groups_are_a_fresh_setup_and_the_runtime(self):
        # What the library owner's prepare(package) warms: everything a fresh setup and every installation take. The
        # fresh setup needs the OptiScaler archive anyway, so Intel's runtime comes from that mirror (no extra download);
        # NVIDIA's DLSS helper is not among the default groups.
        target = d.prepare(self.package)
        self.assertEqual(target, self.root/'cache/bc250-xefg-testers/payload')
        for name, data in [*fixtures.DEPENDENCIES['payload'].items(), *fixtures.DEPENDENCIES['runtime'].items()]:
            self.assertEqual((target/name).read_bytes(), data, name)
        self.assertEqual((target/'fsr4/notices/LICENSE.new-code').read_bytes(), b'MIT notice')
        self.assertFalse((target/'nvngx_dlss.dll').exists())
        self.assertFalse((target/'fsr4/README.md').exists())  # only pinned members
        self.assertEqual(sorted(self.downloads), ['fsr4.zip', 'opti.7z', 'patcher'])

    def test_runtime_comes_from_intels_repository_and_the_fsr4_release(self):
        # Every installation's runtime without the OptiScaler nightly: Intel's files from their own pinned source.
        target = d.prepare(self.package, ('runtime',))
        self.assertEqual(sorted(self.downloads), ['fsr4.zip', 'xell', 'xess_fg', 'xess_license'])
        self.assertEqual((target/'OptiScaler/libxess_fg.dll').read_bytes(), b'Intel FG')

    def test_dlss_group_alone(self):
        target = d.prepare(self.package, ('dlss',))
        self.assertEqual(sorted(self.downloads), ['dlss', 'dlss_license'])
        self.assertEqual((target/'nvngx_dlss.dll').read_bytes(), b'helper')
        self.assertEqual((target/'Licenses/NVIDIA-DLSS-LICENSE.txt').read_bytes(), b'NVIDIA licence')

    def test_nightly_gone_runtime_still_prepared(self):
        # The OptiScaler nightly aged out (a 404): every installation's runtime still comes from its primary sources;
        # only a fresh OptiScaler setup, whose files have no other source, fails, and says where it looked.
        self.pins['inputs']['opti']['url'] = (self.root/'upstream/gone.7z').as_uri()
        self.write_pins()
        d.prepare(self.package, ('runtime',))
        self.assertNotIn('opti.7z', self.downloads)
        with self.assertRaisesRegex(ValueError, 'Cannot download opti-opti.7z from file:'):
            d.prepare(self.package)

    def test_mirror_when_the_primary_is_unreachable(self):
        # Intel's file unreachable: the same bytes from the OptiScaler archive; once that archive is downloaded, the other
        # files it holds come from it without trying their own sources.
        self.pins['inputs']['xess_fg']['url'] = (self.root/'upstream/gone').as_uri()
        self.write_pins()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            target = d.prepare(self.package, ('runtime',))
        self.assertEqual((target/'OptiScaler/libxess_fg.dll').read_bytes(), b'Intel FG')
        self.assertEqual((target/'OptiScaler/libxell.dll').read_bytes(), b'new LL')
        self.assertEqual(sorted(self.downloads), ['fsr4.zip', 'gone', 'opti.7z'])
        self.assertIn('OptiScaler/libxess_fg.dll: xess_fg-xess_fg was not usable; the same bytes came from opti-opti.7z.', out.getvalue())

    def test_mirror_when_the_primary_holds_other_bytes(self):
        (self.root/'upstream/xell').write_bytes(b'other bytes')
        self.write_pins()
        target = d.prepare(self.package, ('runtime',))
        self.assertEqual((target/'OptiScaler/libxell.dll').read_bytes(), b'new LL')
        self.assertIn('xell', self.downloads)
        self.assertIn('opti.7z', self.downloads)
        cache = self.root/'cache/bc250-xefg-testers'
        self.assertFalse((cache/self.pins['inputs']['xell']['file']).exists())  # the wrong bytes were not kept
        self.assertTrue((cache/self.pins['inputs']['xess_fg']['file']).is_file())  # tried before the mirror existed

    def test_both_sources_failing_names_both(self):
        for key in ('xess_fg', 'opti'):
            self.pins['inputs'][key]['url'] = (self.root/'upstream/gone').as_uri()
        self.write_pins()
        with self.assertRaises(ValueError) as caught:
            d.prepare(self.package, ('runtime',))
        message = str(caught.exception)
        self.assertIn('Cannot download xess_fg-xess_fg', message)
        self.assertIn('Also tried ' + self.pins['inputs']['opti']['url'], message)
        self.assertFalse((self.root/'cache/bc250-xefg-testers/payload/OptiScaler').exists())  # nothing placed

    def test_release_archive_mirror_when_the_others_fail(self):
        # Intel's repository unreachable (a rate limit on raw.githubusercontent.com) and the nightly gone: Intel's files
        # come from members of the SDK release archive, another host. Once it is downloaded, the other two files come from
        # it without trying their own failing sources.
        sdk = self.root/'upstream/sdk.zip'
        with zipfile.ZipFile(sdk, 'w') as z:
            for key, member in [('xess_fg', 'bin/libxess_fg.dll'), ('xell', 'bin/libxell.dll'), ('xess_license', 'LICENSE.txt')]:
                z.writestr(member, (self.root/'upstream'/key).read_bytes())
        data = sdk.read_bytes()
        self.pins['inputs']['xess_sdk'] = dict(url=sdk.as_uri(), file='sdk.zip', sha256=sha(data), size=len(data))
        for key, member in [('xess_fg', 'bin/libxess_fg.dll'), ('xell', 'bin/libxell.dll'), ('xess_license', 'LICENSE.txt')]:
            self.pins['sources'][PLAIN[key][0]]['mirrors'].append({'input': 'xess_sdk', 'member': member})
            self.pins['inputs'][key]['url'] = (self.root/'upstream/gone').as_uri()
        self.pins['inputs']['opti']['url'] = (self.root/'upstream/gone.7z').as_uri()
        self.write_pins()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            target = d.prepare(self.package, ('runtime',))
        for name, data in fixtures.DEPENDENCIES['runtime'].items():
            self.assertEqual((target/name).read_bytes(), data, name)
        self.assertEqual(sorted(self.downloads), ['fsr4.zip', 'gone', 'gone.7z', 'sdk.zip'])
        self.assertIn('OptiScaler/libxess_fg.dll: xess_fg-xess_fg was not usable; the same bytes came from sdk.zip.', out.getvalue())

    def test_tls_error_partway_through_tries_the_mirror(self):
        # A TLS failure (or a reset) while reading the primary download is a failed source like an HTTP error: the next
        # candidate is tried and nothing partial stays in the cache.
        import ssl

        class Broken:
            def __init__(self, error):
                self.error = error

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size=-1):
                raise self.error
        for error in (ssl.SSLError(1, 'decryption failed or bad record mac'), ConnectionResetError(104, 'Connection reset by peer')):
            with self.subTest(error=type(error).__name__):
                shutil.rmtree(self.root/'cache', ignore_errors=True)
                self.downloads.clear()

                def urlopen(request, timeout=None):
                    self.downloads.append(request.full_url.rsplit('/', 1)[1])
                    return Broken(error) if request.full_url.endswith('/xess_fg') else REAL_URLOPEN(request, timeout=timeout)
                with patch.object(d.urllib.request, 'urlopen', side_effect=urlopen):
                    target = d.prepare(self.package, ('runtime',))
                self.assertEqual((target/'OptiScaler/libxess_fg.dll').read_bytes(), b'Intel FG')
                self.assertIn('opti.7z', self.downloads)
                cache = self.root/'cache/bc250-xefg-testers'
                self.assertFalse((cache/self.pins['inputs']['xess_fg']['file']).exists())
                self.assertEqual([p.name for p in cache.iterdir() if p.name.startswith('tmp')], [])

    def test_a_failing_cache_write_is_not_a_network_error(self):
        # A full disk while saving a download is not "this source did not deliver": it stays an OSError, no mirror is tried.
        real_write = tempfile._TemporaryFileWrapper.__getattr__

        def full(self, name):
            if name == 'write':
                def write(data):
                    raise OSError(28, 'No space left on device')
                return write
            return real_write(self, name)
        with patch.object(tempfile._TemporaryFileWrapper, '__getattr__', full):
            with self.assertRaisesRegex(OSError, 'No space left'):
                d.prepare(self.package, ('runtime',))
        self.assertEqual(len(self.downloads), 1)

    def test_cached_mirror_is_used_without_downloading(self):
        # A cache that already holds the OptiScaler archive (an earlier fresh setup, or an earlier build whose runtime
        # came from it) serves Intel's runtime without contacting Intel's repository.
        target = d.prepare(self.package)
        for name in ('OptiScaler/libxess_fg.dll', 'OptiScaler/libxell.dll', 'Licenses/XeSS_LICENSE.txt'):
            (target/name).unlink()
        self.downloads.clear()
        d.prepare(self.package, ('runtime',))
        self.assertEqual(self.downloads, [])
        self.assertEqual((target/'OptiScaler/libxell.dll').read_bytes(), b'new LL')

    def test_without_bsdtar_only_whole_files(self):
        # Intel's files are whole downloads; the FSR4 DLL is an archive member, so the runtime still needs bsdtar.
        with patch.object(d.shutil, 'which', return_value=None):
            target = d.prepare(self.package, ('dlss',))
            self.assertTrue((target/'nvngx_dlss.dll').is_file())
            with self.assertRaisesRegex(ValueError, 'needs bsdtar'):
                d.prepare(self.package, ('runtime',))
        self.assertFalse((target/'OptiScaler/libxess_fg.dll').exists())

    def test_unknown_mirror_input_is_refused(self):
        self.pins['sources']['OptiScaler/libxell.dll']['mirrors'] = [{'input': 'nowhere', 'member': 'x'}]
        self.write_pins()
        with self.assertRaisesRegex(ValueError, 'Unknown dependency input'):
            d.prepare(self.package, ('runtime',))

    def test_cache_is_reused(self):
        d.prepare(self.package, ('runtime',))
        self.downloads.clear()
        d.prepare(self.package, ('runtime',))
        self.assertEqual(self.downloads, [])
        d.prepare(self.package)  # the runtime is already there: only the fresh setup's own files
        self.assertEqual(sorted(self.downloads), ['opti.7z', 'patcher'])
        self.downloads.clear()
        d.prepare(self.package)
        d.prepare(self.package, ('dlss',))
        self.assertEqual(sorted(self.downloads), ['dlss', 'dlss_license'])
        self.downloads.clear()
        d.prepare(self.package, ('payload', 'runtime', 'dlss'))
        self.assertEqual(self.downloads, [])

    def test_unreachable_download_names_its_url_and_the_cache(self):
        # Offline (or a moved upstream file): a ValueError the installer prints as it is, not a urllib traceback.
        def offline(request, timeout=None):
            raise urllib.error.URLError(OSError(101, 'Network is unreachable'))
        with patch.object(d.urllib.request, 'urlopen', side_effect=offline):
            with self.assertRaises(ValueError) as caught:
                d.prepare(self.package, ('runtime',))
        message = str(caught.exception)
        self.assertIn(self.pins['inputs']['xess_fg']['url'], message)
        self.assertIn('Also tried ' + self.pins['inputs']['opti']['url'], message)  # Intel's runtime: the mirror too
        self.assertIn('Network is unreachable', message)
        self.assertIn('internet', message)
        self.assertIn(str(self.root/'cache/bc250-xefg-testers'), message)
        self.pins['inputs']['patcher']['url'] = (self.root/'upstream/gone').as_uri()
        self.write_pins()
        with self.assertRaisesRegex(ValueError, 'Cannot download patcher-patcher from file:'):
            d.prepare(self.package)

    def test_damaged_cached_file_is_extracted_again_without_downloading(self):
        target = d.prepare(self.package)
        (target/'fsr4'/fixtures.m.DLL).write_bytes(b'damaged')
        self.downloads.clear()
        d.prepare(self.package, ('runtime',))
        self.assertEqual(self.downloads, [])
        self.assertEqual((target/'fsr4'/fixtures.m.DLL).read_bytes(), b'FSR')

    def test_changed_upstream_download_is_refused(self):
        (self.root/'upstream/fsr4.zip').write_bytes(b'something else')
        self.pins['inputs']['fsr4']['size'] = len(b'something else')
        self.write_pins()
        with self.assertRaisesRegex(ValueError, 'Download checksum mismatch'):
            d.prepare(self.package, ('runtime',))
        cache = self.root/'cache/bc250-xefg-testers'
        self.assertFalse((cache/'payload/fsr4').exists())
        self.assertFalse((cache/self.pins['inputs']['fsr4']['file']).exists())

    def test_download_size_is_checked(self):
        self.pins['inputs']['patcher']['size'] += 1
        self.write_pins()
        with self.assertRaisesRegex(ValueError, 'Download size mismatch'):
            d.prepare(self.package)

    def test_unexpected_member_is_refused_and_nothing_is_placed(self):
        self.pins['runtime']['Files']['fsr4/' + fixtures.m.DLL] = sha(b'another build')
        self.write_pins()
        with self.assertRaisesRegex(ValueError, 'Unexpected dependency'):
            d.prepare(self.package, ('runtime',))
        self.assertFalse((self.root/'cache/bc250-xefg-testers/payload/OptiScaler/libxess_fg.dll').exists())

    def test_conflicting_or_unsafe_pins_are_refused(self):
        self.pins['payload']['Files']['OptiScaler/libxell.dll'] = sha(b'other')
        self.write_pins()
        with self.assertRaisesRegex(ValueError, 'Conflicting pins'):
            d.prepare(self.package)
        self.pins['extra'] = {'Files': {'../outside.dll': sha(b'x')}}
        self.write_pins()
        with self.assertRaisesRegex(ValueError, 'Unsafe dependency name'):
            d.prepare(self.package, ('extra',))

    def game(self):
        """A fixture game (test_game_install.GameFixture) whose package pins this test's upstream downloads."""
        class Install(fixtures.GameFixture):
            def runTest(inner):
                pass
        case = Install()
        fixtures.GameFixture.setUp(case)
        self.addCleanup(case.doCleanups)
        fixtures.set_package_file(case.package, 'dependencies.json', json.dumps(self.pins).encode())
        return case

    def test_install_downloads_through_the_real_cache(self):
        # The installer without a prepared directory: its dependencies.py fetches a fresh setup's files and the runtime
        # into the cache. NVIDIA's helper only for a DLSS input (v30 fetched and placed it in every fresh setup).
        case = self.game()
        with patch.object(fixtures.m, 'prepare_dependencies', REAL_PREPARE):
            case.fresh()
            fixtures.m.install(case.package, case.exe, route='opti', fg_input='upscaler')
            self.assertEqual((case.game/'libxess_fg.dll').read_bytes(), b'Intel FG')
            self.assertEqual((case.game/'OptiScaler'/fixtures.m.DLL).read_bytes(), b'FSR')
            self.assertFalse((case.game/'nvngx_dlss.dll').exists())
            self.assertEqual(sorted(self.downloads), ['fsr4.zip', 'opti.7z', 'patcher'])
            fixtures.m.restore(case.exe)
            self.downloads.clear()
            fixtures.m.install(case.package, case.exe, route='opti', fg_input='dlssg')
            self.assertEqual(sorted(self.downloads), ['dlss', 'dlss_license'])
            self.assertEqual((case.game/'nvngx_dlss.dll').read_bytes(), b'helper')
            fixtures.m.restore(case.exe)
        self.assertFalse((case.game/'nvngx_dlss.dll').exists())

    def test_package_installer_uses_its_own_dependencies_py(self):
        # A tester runs the package's install.py, which loads the dependencies.py beside it (no fixture in between).
        # Paired with an earlier build's dependencies.py (prepare(package) only) it refuses clearly before any change.
        case = self.game()
        for name in ('install.py', 'dependencies.py'):
            shutil.copyfile(PACKAGING/name, case.package/name)
        spec = importlib.util.spec_from_file_location('package_install', case.package/'install.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)

        def cli(*args):
            errors = io.StringIO()
            with patch.object(sys, 'argv', ['install.py', *args]), contextlib.redirect_stderr(errors):
                return installer.main(), errors.getvalue()
        code, errors = cli('install', str(case.exe), '--route', 'opti', '--fg-input', 'upscaler')
        self.assertEqual((code, errors), (0, ''))
        # An existing setup: the runtime only, Intel's files from Intel's repository (no OptiScaler nightly).
        self.assertEqual(sorted(self.downloads), ['fsr4.zip', 'xell', 'xess_fg', 'xess_license'])
        self.assertEqual((case.game/'XeSSMFG/libxell.dll').read_bytes(), b'new LL')
        self.assertEqual(cli('restore', str(case.exe))[0], 0)
        case.assertOriginal()
        (case.package/'dependencies.py').write_text('def prepare(package):\n    raise AssertionError("an earlier build")\n')
        shutil.rmtree(self.root/'cache')
        code, errors = cli('install', str(case.exe), '--route', 'opti', '--fg-input', 'upscaler')
        self.assertEqual(code, 1)
        self.assertIn('install.py and dependencies.py come from different builds', errors)
        self.assertNotIn('Unexpected error', errors)
        self.assertEqual(json.loads((case.game/fixtures.m.STATE/'state.json').read_text())['status'], 'restored')
        case.assertOriginal()


class ShippedPinsTests(unittest.TestCase):
    """The dependencies.json a package ships."""
    pins = json.loads((PACKAGING/'dependencies.json').read_text())
    INTEL = 'https://raw.githubusercontent.com/intel/xess/de0fb9c1c510661c571164e1418ceca8101dab69/'
    INTEL_TAG = 'https://raw.githubusercontent.com/intel/xess/8fe81bdbbaf00b3c1b733fd0d830c333dc84e6f0/'  # tag v3.0.2

    def test_groups_and_sources_are_consistent(self):
        files = d.pinned_files(self.pins, ('payload', 'runtime', 'dlss'))
        for name in files:
            for key, member in d.candidates(self.pins, name):
                self.assertIn(key, self.pins['inputs'], name)
                if member is None:
                    self.assertEqual(self.pins['inputs'][key]['sha256'], files[name], name)
        for key, item in self.pins['inputs'].items():
            self.assertTrue(item['url'].startswith('https://'), key)
            self.assertRegex(item['sha256'], r'^[0-9a-f]{64}$')
            self.assertIsInstance(item['size'], int)
            self.assertNotIn('latest', item['url'])
            self.assertNotIn('/', item['file'])
        self.assertEqual(len({item['file'] for item in self.pins['inputs'].values()}), len(self.pins['inputs']))
        for layout in ('Package', 'ProxyPackage'):
            for name, source in self.pins['runtime'][layout].items():
                self.assertIn(source, self.pins['runtime']['Files'], name)

    def test_runtime_is_the_qualified_bytes(self):
        # Intel's runtime: the bytes tester v30 carried in the package (its manifest and qualification receipt). FSR 4:
        # the BC-250 build RC12 since 1.1.2 (RC11, 8192ea97, before).
        files = self.pins['runtime']['Files']
        self.assertEqual(files['fsr4/amd_fidelityfx_upscaler_dx12.dll'], '4b0df27761d7ced52c30dcbd1641c55bdcf4d2ae10d59f7e5b4b2f895b6bba79')
        self.assertEqual(files['OptiScaler/libxess_fg.dll'], 'ec5e0c65e075570c6ede72618bb666d0be0c2e10b2ea9762c0fe8cb8e375ab27')
        self.assertEqual(files['OptiScaler/libxell.dll'], 'd2030dcd694fda8f2ec7e044b13e6db8f0b56d4ba9113a5efad334e3f3ded8c7')
        self.assertEqual(self.pins['runtime']['Package'], {
            'fsr4/amd_fidelityfx_upscaler_dx12.dll': 'fsr4/amd_fidelityfx_upscaler_dx12.dll',
            'payload/libxess_fg.dll': 'OptiScaler/libxess_fg.dll', 'payload/libxell.dll': 'OptiScaler/libxell.dll',
            'payload/XeSSMFG/libxess_fg.dll': 'OptiScaler/libxess_fg.dll', 'payload/XeSSMFG/libxell.dll': 'OptiScaler/libxell.dll'})
        self.assertEqual(self.pins['runtime']['ProxyPackage'], {
            'fsr4/amd_fidelityfx_upscaler_dx12.dll': 'fsr4/amd_fidelityfx_upscaler_dx12.dll',
            'payload/bc250_xefg_original.dll': 'OptiScaler/libxess_fg.dll', 'payload/libxell.dll': 'OptiScaler/libxell.dll'})
        self.assertTrue(self.pins['inputs']['fsr4']['url'].startswith('https://github.com/daniel-h-0/bc250-fsr4-fork/releases/download/v4.0.0-rc12/'))

    def test_intel_runtime_comes_from_intels_repository_with_the_nightly_as_mirror(self):
        # Durable pin: Intel's repository at the commit whose headers the build uses (downloaded and hashed 2026-10-18).
        # Mirrors of the same bytes, in order: the same repository at the v3.0.2 tag commit (for a rewritten main), the
        # OptiScaler nightly archive (which may age out) and the XeSS SDK 3.0.2 release asset (another host).
        for name, key, path in [('OptiScaler/libxess_fg.dll', 'xess_fg', 'bin/libxess_fg.dll'), ('OptiScaler/libxell.dll', 'xell', 'bin/libxell.dll'),
                                ('Licenses/XeSS_LICENSE.txt', 'xess_license', 'LICENSE.txt')]:
            self.assertEqual(d.candidates(self.pins, name), [(key, None), (key + '_v302', None), ('opti', name), ('xess_sdk', path)])
            self.assertEqual(self.pins['inputs'][key]['url'], self.INTEL + path)
            self.assertEqual(self.pins['inputs'][key + '_v302']['url'], self.INTEL_TAG + path)
            for item in (key, key + '_v302'):
                self.assertEqual(self.pins['inputs'][item]['sha256'], self.pins['runtime']['Files'][name])
        self.assertEqual(self.pins['inputs']['xess_sdk']['url'], 'https://github.com/intel/xess/releases/download/v3.0.2/XeSS_SDK_3.0.2.zip')
        self.assertEqual(self.pins['inputs']['xess_sdk']['sha256'], '88b8a373f30e33f3558a77a93e634f11b8132fc3047ea1a8edeead32b8471990')
        self.assertEqual(self.pins['inputs']['xess_sdk']['size'], 76839749)
        self.assertEqual(self.pins['inputs']['xess_fg']['size'], 22957432)
        self.assertEqual(self.pins['inputs']['xell']['size'], 415368)
        self.assertIn('likely_expiry', self.pins['inputs']['opti'])
        self.assertIn('nightly', self.pins['inputs']['opti']['url'])
        lock = PACKAGING.parent/'release/inputs.lock.json'
        if lock.is_file():  # the proxy verifies and loads exactly the bytes of the build's lock
            runtime = json.loads(lock.read_text())['fetch']['intel-xess-runtime']
            self.assertTrue(self.INTEL.endswith('/' + runtime['commit'] + '/'))
            self.assertEqual(runtime['files']['bin/libxess_fg.dll']['sha256'], self.pins['runtime']['Files']['OptiScaler/libxess_fg.dll'])
        # Every installation's runtime has a source outside the nightly.
        for name in self.pins['runtime']['Files']:
            self.assertNotEqual(d.source(self.pins, name)[0], 'opti', name)

    def test_fresh_setup_is_tester_v30s_without_the_dlss_helper(self):
        # The 'payload' and 'dlss' groups together are v30's 'payload', byte for byte (canonical JSON of v30's
        # dependencies.json 'payload'); the DLSS helper and its licence are their own group, not part of every fresh setup.
        merged = dict(self.pins['payload'], Files=dict(self.pins['payload']['Files'], **self.pins['dlss']['Files']))
        self.assertEqual(sha(json.dumps(merged, sort_keys=True).encode()), '11511b4b431afd6d0f7ca068e464b361d9dfa31247281443c15b9398272f70cf')
        self.assertNotIn('nvngx_dlss.dll', self.pins['payload']['Files'])
        self.assertEqual(sorted(self.pins['dlss']['Files']), ['Licenses/NVIDIA-DLSS-LICENSE.txt', 'nvngx_dlss.dll'])
        for key in ('dlss', 'dlss_license'):
            self.assertRegex(self.pins['inputs'][key]['url'], r'^https://raw\.githubusercontent\.com/NVIDIA/DLSS/[0-9a-f]{40}/')
        self.assertEqual(d.DEFAULT_GROUPS, ('payload', 'runtime'))
        self.assertEqual({k for k, v in self.pins.items() if isinstance(v, dict) and 'Files' in v}, {'payload', 'runtime', 'dlss'})

    def test_installer_and_dependencies_py_agree(self):
        self.assertEqual(d.FORMAT, fixtures.m.DEPENDENCIES_FORMAT)
        self.assertIs(fixtures.m.check_pins(self.pins), self.pins)

    def test_no_host_paths(self):
        text = (PACKAGING/'dependencies.json').read_text()
        # Written in pieces so that this file does not name a host path itself.
        for marker in ('/' + 'home/', '/run' + '/media', '~/', 'bc250' + '-admin'):
            self.assertNotIn(marker, text)


if __name__ == '__main__':
    unittest.main()
