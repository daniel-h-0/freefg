#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Unit tests of the release tooling's text helpers: release/host_paths.py (the host-path detector of export_tree.py
and assemble.py), release/unifdef.py (the conditional resolver of export_tree.py --public) and the public export's
projections in release/export_tree.py (inputs.lock.json, package.json, the repository's top files), and the OptiScaler
fork's source offer: release/fork_source_archive.py and the source companion's fork reader on git fixtures (local
repositories stand in for the submodules' hosts), the third-party licence texts against their provenance, and the
lock's fork group. No build, no network. They pass in this tree and in a tree exported with --public.

  python3 release/test_release_tools.py
"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_paths  # noqa: E402
import unifdef  # noqa: E402

PROFILE = Path(__file__).resolve().parent / 'profile'
# Host paths are assembled from pieces so that this file names none itself (export_tree.py scans it).
HOME = '/' + 'home'
REPO_NAME = 'bc250' + '-admin'


class HostPaths(unittest.TestCase):
    def check(self, text, shipped, review):
        self.assertEqual(bool(host_paths.find(text)), shipped, f'shipped mode on {text!r}')
        self.assertEqual(bool(host_paths.find(text, review=True)), review, f'review mode on {text!r}')

    def test_home_directories(self):
        self.check(HOME + '/alice/x', True, True)
        self.check('file://' + HOME + '/alice/x', True, True)
        self.check('HOME=' + HOME + '/alice', True, True)
        self.check('/var' + HOME + '/alice/', True, True)
        self.check('/run' + '/media/system/x', True, True)

    def test_tilde(self):
        for hidden in ('~/.steam/steam', '~/.config/x', '~/.local/share', '~/.cache/y'):
            self.check(hidden, False, False)
        self.check('~/' + 'Downloads/x', True, True)
        self.check('~/' + REPO_NAME + '/reports', True, True)

    def test_wine_and_windows(self):
        self.check('Z:\\' + 'home\\alice\\x', True, True)
        self.check('Z:\\\\' + 'home\\\\alice', True, True)  # as JSON writes it
        self.check('Z:/' + 'home/alice', True, True)
        self.check('C:\\Users\\' + 'steamuser\\AppData', False, False)
        self.check('C:\\Users\\' + 'alice\\x', True, True)
        self.check('drive_c/users/steamuser/AppData', False, False)

    def test_repository_name(self):
        self.check('"host": "' + REPO_NAME + ' library, 2026-09-29"', False, True)
        self.check(REPO_NAME + '/reports', True, True)
        self.check('x/' + REPO_NAME, True, True)

    def test_not_host_paths(self):
        for text in ('https://github.com/intel/xess', '/usr/include/wine', 'src/game/wave_layer.c', '~/'):
            self.check(text, False, False)

    def test_binary_files_are_not_scanned(self):
        self.assertIsNone(host_paths.text_of(b'DXBC\0\0' + b'~/' + b'd'))
        self.assertIsNone(host_paths.in_file_bytes(b'\0' + ('~/' + 'Downloads').encode()))
        utf16 = '\ufeff' + HOME + '/alice/x'
        self.assertTrue(host_paths.in_file_bytes(utf16.encode('utf-16-le')))

    def test_profile_shaders_never_match(self):
        """The committed own shaders are binary: their bytes may spell a host path (1f27b449fb99a587.dxil holds a tilde,
        a slash and a letter in its bitcode) and must never be reported."""
        shaders = sorted(PROFILE.glob('*.dxil'))
        if not shaders:
            self.skipTest('no release/profile in this tree')
        spelled = [p.name for p in shaders if host_paths.REVIEW.search(p.read_bytes().decode('latin-1'))]
        self.assertTrue(spelled, 'no profile shader spells a host path any more; the regression case is gone')
        self.assertEqual([p.name for p in shaders if host_paths.in_file_bytes(p.read_bytes())], [])

    def test_this_file_and_the_detector_name_no_host_path(self):
        for path in (Path(__file__), Path(host_paths.__file__)):
            self.assertIsNone(host_paths.in_file_bytes(path.read_bytes()), path.name)


SOURCE = '''#include <a.h>
#ifdef RESEARCH
research();
#include "research.h"
#endif
#ifndef RESEARCH
plain();
#else
other();
#endif
#if defined(GAME) && !defined(RESEARCH)
game();
#endif
#if KNOB > 1
knob();
#endif
#ifdef GAME  /* comment */
# ifdef RESEARCH
nested();
# endif
both();
#else
neither();
#endif
'''


class Unifdef(unittest.TestCase):
    def resolve(self, text, **kwargs):
        return unifdef.unifdef(text, kwargs.pop('defined', {'GAME': 1}), kwargs.pop('undefined', {'RESEARCH'}), **kwargs)

    def test_resolution(self):
        result = self.resolve(SOURCE)
        self.assertEqual(result.text, '#include <a.h>\nplain();\ngame();\n#if KNOB > 1\nknob();\n#endif\nboth();\n')
        self.assertEqual((result.resolved, result.kept), (5, 1))

    def test_idempotent(self):
        once = self.resolve(SOURCE).text
        self.assertEqual(self.resolve(once).text, once)

    def test_expressions(self):
        cases = {'#if RESEARCH >= 2\nx\n#endif\n': '', '#if GAME == 1 || RESEARCH\nx\n#endif\n': 'x\n',
                 '#if !(defined GAME)\nx\n#else\ny\n#endif\n': 'y\n', '#if (GAME << 2) == 4\nx\n#endif\n': 'x\n'}
        for text, expected in cases.items():
            self.assertEqual(self.resolve(text).text, expected, text)

    def test_continuation(self):
        text = '#if defined(RESEARCH) || \\\n    defined(OTHER_RESEARCH)\nx\n#endif\ny\n'
        self.assertEqual(self.resolve(text, undefined={'RESEARCH', 'OTHER_RESEARCH'}).text, 'y\n')

    def test_partial_condition_refused(self):
        with self.assertRaises(unifdef.UnifdefError):
            self.resolve('#if defined(GAME) && defined(UNKNOWN)\nx\n#endif\n')

    def test_elif_with_given_macro_refused(self):
        with self.assertRaises(unifdef.UnifdefError):
            self.resolve('#if RESEARCH\nx\n#elif UNKNOWN\ny\n#endif\n')
        text = '#if A\nx\n#elif B\ny\n#endif\n'
        self.assertEqual(self.resolve(text).text, text)

    def test_unclosed_comment_on_a_removed_directive_refused(self):
        with self.assertRaises(unifdef.UnifdefError):
            self.resolve('#ifdef RESEARCH /* starts\n   continues */\nx\n#endif\n')

    def test_directives_in_comments_ignored(self):
        text = '/*\n#ifdef RESEARCH\n*/\nx\n'
        self.assertEqual(self.resolve(text).text, text)

    def test_protected_text_keeps_its_conditional(self):
        text = '#ifdef RESEARCH\nstatic void patched(void);\n#endif\n#ifdef RESEARCH\nother();\n#endif\n'
        result = self.resolve(text, protected=['static void patched(void);'])
        self.assertEqual(result.text, '#ifdef RESEARCH\nstatic void patched(void);\n#endif\n')
        self.assertEqual(result.protected, [1])

    def test_unbalanced_refused(self):
        for text in ('#ifdef X\n', '#endif\n', '#if X\n#else\n#else\n#endif\n'):
            with self.assertRaises(unifdef.UnifdefError):
                self.resolve(text)

    def test_helpers(self):
        self.assertFalse(unifdef.has_code('/* only\n a comment */\n  // and this\n'))
        self.assertTrue(unifdef.has_code('/* c */ int x;\n'))
        self.assertEqual(unifdef.remove_includes('#include "a.h"\n#include "b.h"\n/*\n#include "a.h"\n*/\n', {'a.h'}),
                         '#include "b.h"\n/*\n#include "a.h"\n*/\n')
        self.assertEqual(unifdef.conditional_macros(SOURCE), {'RESEARCH', 'GAME', 'KNOB'})
        self.assertEqual(unifdef.defined_macros('#define A 1\n/* #define B */\n # define C(x) x\n'), {'A', 'C'})


class PublicLock(unittest.TestCase):
    def test_projection(self):
        import export_tree
        lock = {'work': {export_tree.PROFILE_GROUP: {'path': 'p', 'description': 'private', 'files': {
                    'a.dxil': {'sha256': '1', 'origin': 'own'}, 'b.dxil': {'sha256': '2', 'origin': 'intel-derived'}}},
                         'xessmfg-enabler': {'files': {}}, 'optiscaler-fork': {'files': {}}}, 'fetch': {}}
        public, report = export_tree.public_lock(lock)
        self.assertEqual(list(public['work']), [export_tree.PROFILE_GROUP, 'optiscaler-fork'])
        self.assertEqual(list(public['work'][export_tree.PROFILE_GROUP]['files']), ['a.dxil'])
        self.assertEqual(report, dict(dropped_groups=['xessmfg-enabler'], dropped_profile_files=1, dropped_fork_notes=[]))
        self.assertEqual(export_tree.public_lock(public)[0], public)
        self.assertEqual(lock['work'][export_tree.PROFILE_GROUP]['description'], 'private')  # the input is not changed


def tiny_package():
    """A package declaration in package.json's shape: a default package and an intel-free-2x variant."""
    return {'about': 'x', 'name': 'bc250-fsr4-xemfg-private-test-99', 'manifest': {'runtime': 'xemfg', 'status': 'a'},
            'components': {
                'documents': {'files': {'README.md': 'repo:packaging/v99/README.md'}},
                'addon': {'files': {'payload/a.asi': 'build:addon', 'qualification/addon-build.json': 'build:addon-record'}},
                'xessmfg-enabler': {'files': {'payload/XeSSMFG/XeSSMFG.dll': 'input:xessmfg-enabler/XeSSMFG.dll'}},
                'licenses': {'files': {'licenses/BC250-XeFG.txt': 'repo:LICENSE.new-code',
                                       'licenses/Intel-XeSS.txt': 'input:intel-xess/LICENSE.txt'}}},
            'never_ship': {'paths': ['payload/libxell.dll'], 'prefixes': ['fsr4/'], 'sha256': {}},
            'source_companion': {'description': 'd', 'files': {'scripts/x.py': 'repo:scripts/x.py'}},
            'installer_tests': ['test_a'],
            'variants': {'intel-free-2x': {
                'about': 'v', 'name': 'bc250-fsr4-xemfg-private-test-99-intel-free-2x', 'package_dir': 'package-2x',
                'documents_version': 'public', 'manifest': {'status': 'b', 'max_factor': 2}, 'allowed_components': {},
                'replace': {'addon': 'addon-intel-free-2x', 'xessmfg-enabler': None, 'documents': 'documents-public'},
                'components': {
                    'addon-intel-free-2x': {'files': {'payload/libxess_fg.dll': 'build:addon-intel-free-2x',
                                                      'payload/BC250-XeFG/shaders/a.dxil':
                                                          'build:addon-intel-free-2x-profile/a.dxil'}},
                    'documents-public': {'files': {'README.md': 'repo:packaging/public/README.md'}}},
                'never_ship': {'paths': ['payload/bc250_xefg_original.dll'], 'prefixes': ['fsr4/'], 'sha256': {}}}}}


TINY_NAMES = {'packaging/public/README.md', 'packaging/public/LICENSE', 'release/package.json'}
TINY_LOCK = {'fetch': {'intel-xess': {'files': {'LICENSE.txt': {'sha256': '1'}}}}, 'work': {}}


class PublicPackage(unittest.TestCase):
    """export_tree.public_package: the public package.json declares the intel-free-2x package at the top level."""

    def setUp(self):
        import export_tree
        self.export_tree = export_tree

    def test_projection(self):
        private = tiny_package()
        before = copy.deepcopy(private)
        public, report = self.export_tree.public_package(private, TINY_NAMES)
        self.assertEqual(private, before)  # the input is not changed
        self.assertEqual(public['variant'], 'intel-free-2x')
        self.assertEqual(public['name'], 'bc250-fsr4-xemfg-private-test-99-intel-free-2x')
        self.assertEqual(list(public['components']), ['documents', 'addon-intel-free-2x', 'licenses'])
        self.assertEqual(public['components']['documents']['files'], {'README.md': 'repo:packaging/public/README.md'})
        self.assertEqual(public['components']['licenses']['files']['licenses/BC250-XeFG.txt'],
                         'repo:packaging/public/LICENSE')
        self.assertEqual(public['manifest'], {'runtime': 'xemfg', 'status': self.export_tree.PUBLIC_PACKAGE_STATUS,
                                              'max_factor': 2})  # the maintainers' status text replaced
        self.assertEqual(public['never_ship']['paths'], ['payload/bc250_xefg_original.dll'])
        self.assertEqual((public['documents_version'], public['documents_component'], public['package_dir']),
                         ('public', 'documents', 'package-2x'))
        self.assertEqual(public['source_companion']['files'], {})
        self.assertEqual(report['renamed_components'], {'documents-public': 'documents'})
        self.assertEqual(report['dropped_companion_files'], ['scripts/x.py'])
        self.assertEqual(self.export_tree.public_package_problems(public, TINY_LOCK, TINY_NAMES.__contains__), [])

    def test_variant_flag_declares_the_same_package(self):
        from assemble import apply_variant
        public, _ = self.export_tree.public_package(tiny_package(), TINY_NAMES)
        self.assertEqual(apply_variant(public, 'intel-free-2x'), {k: v for k, v in public.items() if k != 'variants'})

    def test_idempotent(self):
        public, _ = self.export_tree.public_package(tiny_package(), TINY_NAMES)
        again, report = self.export_tree.public_package(public, TINY_NAMES)
        self.assertEqual(self.export_tree.json_text(again), self.export_tree.json_text(public))
        self.assertEqual((report['renamed_components'], report['swapped_sources']), ({}, []))

    def test_problems(self):
        public, _ = self.export_tree.public_package(tiny_package(), TINY_NAMES)
        problems = self.export_tree.public_package_problems
        for component, source in (('enabler', 'input:xessmfg-enabler/XeSSMFG.dll'), ('default', 'build:addon'),
                                  ('default-record', 'build:addon-record'), ('missing', 'repo:scripts/x.py'),
                                  ('unpinned', 'input:intel-xess/other.txt'), ('odd', 'http://example.org/x')):
            broken = copy.deepcopy(public)
            broken['components'][component] = {'files': {'payload/x': source}}
            found = problems(broken, TINY_LOCK, TINY_NAMES.__contains__)
            self.assertEqual(len(found), 1, (source, found))
            self.assertIn(source, found[0])
        broken = copy.deepcopy(public)
        broken['variants']['intel-free-2x']['manifest'] = {'status': 'other'}
        self.assertEqual(problems(broken, TINY_LOCK, TINY_NAMES.__contains__),
                         ['--variant intel-free-2x declares a different package'])
        broken['variants']['intel-free-2x']['replace'] = {'addon': 'x'}
        self.assertIn('--variant intel-free-2x fails', problems(broken, TINY_LOCK, TINY_NAMES.__contains__)[0])
        broken = copy.deepcopy(public)
        broken['components']['documents']['files']['README.md'] = 'repo:packaging/v99/README.md'
        self.assertEqual(len(problems(broken, TINY_LOCK, lambda name: True)), 1)

    def test_this_tree(self):
        """This tree's package.json projects to a package that only the proxy, the layer, exported files and the public
        lock supply; in the maintainers' tree it ships the same files as the intel-free-2x variant."""
        from assemble import apply_variant
        export_tree = self.export_tree
        spec = json.loads((export_tree.REPO / export_tree.PACKAGE).read_text())
        names = export_tree.read_keep(public=True)
        public, _ = export_tree.public_package(spec, set(names))
        lock, _ = export_tree.public_lock(json.loads((export_tree.REPO / export_tree.LOCK).read_text()))
        self.assertEqual(export_tree.public_package_problems(public, lock, set(names).__contains__), [])
        self.assertNotIn('xessmfg-enabler', public['components'])
        self.assertNotIn('profile-intel-derived', public['components'])
        self.assertEqual(export_tree.json_text(export_tree.public_package(public, set(names))[0]),
                         export_tree.json_text(public))
        if spec['variants'][export_tree.PUBLIC_VARIANT]['replace']:  # the maintainers' package.json
            variant = apply_variant(spec, export_tree.PUBLIC_VARIANT)
            files = {t: s for c in variant['components'].values() for t, s in c['files'].items()}
            public_files = {t: s for c in public['components'].values() for t, s in c['files'].items()}
            self.assertEqual(public_files, {t: export_tree.PUBLIC_SOURCES.get(s, s) for t, s in files.items()})
            for key in ('name', 'never_ship', 'allowed_components', 'documents_version', 'package_dir',
                        'installer_tests'):
                self.assertEqual(public[key], variant[key], key)
            # the manifest's maintainers' text (status, profile.research) is replaced by neutral lines
            neutral = {k: v for k, v in public['manifest'].items() if k not in ('status', 'profile')}
            self.assertEqual(neutral, {k: v for k, v in variant['manifest'].items() if k not in ('status', 'profile')})
            self.assertEqual(public['manifest']['status'], export_tree.PUBLIC_PACKAGE_STATUS)
            self.assertEqual(public['manifest']['profile']['name'], variant['manifest']['profile']['name'])
            text = json.dumps(public['manifest'])
            self.assertNotRegex(text, r'(?i)private|tester|library owner|measurement build|\bq\d+\b(?!-)')
        else:  # a public tree: its package.json is its own projection
            self.assertEqual(export_tree.json_text(public), (export_tree.REPO / export_tree.PACKAGE).read_text())

    def test_public_licence(self):
        """packaging/public/LICENSE is the MIT text of LICENSE.new-code with its own holder line: the placeholder until
        the rename writes the chosen holder."""
        import export_tree
        text = (export_tree.REPO / 'packaging/public/LICENSE').read_text()
        self.assertRegex(text, r'\AMIT License\n\nCopyright \(c\) 2026 [^\n]+\n\nPermission is hereby')
        self.assertNotIn('XeFG', text)
        private = export_tree.REPO / 'LICENSE.new-code'
        if private.is_file():
            body = private.read_text()
            self.assertEqual(text.partition('Permission')[2], body.partition('Permission')[2])


class PublicRoot(unittest.TestCase):
    """export_tree.root_copy / public_root / check_public_export: the repository's top files."""

    AVAILABLE = {'packaging/public/PRIVACY.md', 'packaging/public/NOTICE.md', 'packaging/public/LICENSE',
                 'packaging/public/README.md', 'README.md', 'NOTICE.md', 'LICENSE', '.github/SECURITY.md'}

    def copy(self, target, text):
        import export_tree
        return export_tree.root_copy(target, export_tree.PUBLIC_ROOT[target], text, self.AVAILABLE)

    def test_links_at_the_top(self):
        import export_tree
        text = '[a](PRIVACY.md) [b](NOTICE.md#x) [c](#y) [d](https://example.org/z.md) [e](LICENSE) [f](mailto:a@b)\n'
        out, missing = self.copy('README.md', text)
        note = export_tree.ROOT_NOTE.format(source='packaging/public/README.md')
        self.assertEqual(out, note + '[a](packaging/public/PRIVACY.md) [b](NOTICE.md#x) [c](#y) '
                                     '[d](https://example.org/z.md) [e](LICENSE) [f](mailto:a@b)\n')
        self.assertEqual(missing, [])

    def test_links_in_a_folder(self):
        out, missing = self.copy('.github/SECURITY.md', '[a](PRIVACY.md) [b](NOTICE.md) [c](README.md#z)\n')
        self.assertTrue(out.endswith('[a](../packaging/public/PRIVACY.md) [b](../NOTICE.md) [c](../README.md#z)\n'))
        self.assertEqual(missing, [])

    def test_missing_links(self):
        _out, missing = self.copy('README.md', '[a](MISSING.md) [b](../outside.md) [c](PRIVACY.md)\n')
        self.assertEqual(missing, ['MISSING.md', '../outside.md'])

    def test_licence_is_copied_verbatim(self):
        self.assertEqual(self.copy('LICENSE', 'MIT License\n[x](y)\n'), ('MIT License\n[x](y)\n', []))

    def test_draft_markers_only_in_removable_comments(self):
        """Every [DRAFT] marker of the public documents sits in an HTML comment, which publication removes. Text that
        spells the marker anywhere else keeps assemble.py --archive and check_public_docs.py --release refusing the
        document after those comments are gone."""
        import re
        docs = sorted((Path(__file__).resolve().parent.parent / 'packaging/public').glob('*.md'))
        self.assertTrue(docs)
        for path in docs:
            rest = re.sub(r'<!--(?:(?!-->).)*?\[DRAFT\].*?-->', lambda m: '\n' * m.group(0).count('\n'),
                          path.read_text(), flags=re.S)
            lines = [n for n, line in enumerate(rest.splitlines(), 1) if '[DRAFT]' in line]
            self.assertEqual(lines, [], f'{path.name}: [DRAFT] outside a draft comment on these lines')

    def test_this_tree(self):
        import export_tree
        names = export_tree.read_keep(public=True)
        contents, report = export_tree.public_root(names)
        self.assertEqual(set(contents), set(export_tree.PUBLIC_ROOT))
        self.assertEqual(contents['LICENSE'], (export_tree.REPO / 'packaging/public/LICENSE').read_bytes())
        self.assertEqual(report['LICENSE']['source'], 'packaging/public/LICENSE')
        self.assertLessEqual(set(report['LICENSE']['placeholders']), {'[COPYRIGHT HOLDER]'})  # until the rename
        readme = contents['README.md'].decode()
        self.assertIn('](NOTICE.md)', readme)
        self.assertIn('](packaging/public/PRIVACY.md)', readme)
        with self.assertRaises(export_tree.ReleaseError):
            export_tree.public_root(names + ['README.md'])

    def test_check_public_export(self):
        import export_tree
        public, _ = export_tree.public_package(tiny_package(), TINY_NAMES)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            files = {'release/package.json': export_tree.json_text(public), 'release/inputs.lock.json': json.dumps(TINY_LOCK),
                     'packaging/public/README.md': '# r\n', 'packaging/public/LICENSE': 'MIT License\n',
                     'README.md': '[n](NOTICE.md) [p](packaging/public/README.md#r)\n', 'LICENSE': 'MIT License\n',
                     'NOTICE.md': '[r](README.md)\n', '.github/SECURITY.md': '[n](../NOTICE.md)\n',
                     '.github/CONTRIBUTING.md': 'c\n'}
            for name, text in files.items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text)
            self.assertEqual(export_tree.check_public_export(root), [])
            (root / 'packaging/public/LICENSE').unlink()
            (root / '.github/SECURITY.md').write_text('[n](NOTICE.md)\n')
            found = export_tree.check_public_export(root)
            self.assertEqual(len(found), 2, found)
            self.assertIn('repo:packaging/public/LICENSE', found[0])
            self.assertIn('.github/SECURITY.md: link to missing NOTICE.md', found[1])


# ------------------------------------------------------------------------------------------- rename tool and installer
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402

RELEASE_DIR = Path(__file__).resolve().parent
TREE = RELEASE_DIR.parent
OWNER = re.compile(r'private-test-(\d+)$')  # the private library owner's package-name pattern


def fixture_package(public=False):
    """release/package.json in its private shape (a default package and two variants), or with public as
    export_tree.py --public writes it (the public package at the top level, as its only variant)."""
    files = {'Start-BC250-XeFG.sh': 'repo:packaging/Start-BC250-XeFG.sh',
             'licenses/BC250-XeFG.txt': 'repo:packaging/public/LICENSE',
             'extras/x/bc250-xemfg-gamescope-cap.hook': 'repo:packaging/extras/x/bc250-xemfg-gamescope-cap.hook'}
    if public:
        name = 'bc250-fsr4-xemfg-private-test-31-intel-free-2x'
        return {'name': name, 'variant': 'intel-free-2x', 'components': {'installer': {'files': files}},
                'variants': {'intel-free-2x': {'name': name}}}
    return {'name': 'bc250-fsr4-xemfg-private-test-31', 'components': {'installer': {'files': files}},
            'variants': {'intel-free': {'name': 'bc250-fsr4-xemfg-private-test-31-intel-free'},
                         'intel-free-2x': {'name': 'bc250-fsr4-xemfg-private-test-31-intel-free-2x'}}}


FIXTURE = {
    'packaging/public/README.md':
        '# [PRODUCT]\n\n[PRODUCT] works with Intel XeSS Frame Generation (XeFG); it is not XeSS itself.\n'
        'Downloads send `BC250-XeFG-private-test/1`. Logs: `BC250-XeFG-fast.log` in `BC250-XeFG/`.\n'
        'Cache `~/.cache/bc250-xefg-testers`; start `./Start-BC250-XeFG.sh`; licence `licenses/BC250-XeFG.txt`.\n',
    'packaging/public/LICENSE': 'MIT License\n\nCopyright (c) 2026 [COPYRIGHT HOLDER]\n',
    'packaging/mfg/setup.py':
        "MFG=True\nNAME='FSR4 + XeMFG' if MFG else 'FSR4 + XeFG 2×'\n"
        "def dialog(*args):return ['zenity','--title=BC250 '+NAME,*args]\nTEMP='bc250-xefg-setup-'\n",
    'scripts/test_setup_front_end.py': "def check(self):self.assertEqual(self.setup.NAME, 'FSR4 + XeMFG')\n",
    'packaging/dependencies.py': "HEADERS={'User-Agent': 'BC250-XeFG-private-test/1'}\nCACHE='bc250-xefg-testers'\n",
    'release/fetch.py': "AGENT='bc250-xemfg-release-fetch'\n",
    'release/config.py': "SETTINGS={'work': 'XEMFG_WORK'}\n",
    'packaging/install.py':
        "STATE='.bc250-xefg-experimental'\nPROXY_LOGS=['BC250-MFG.log','BC250-XeFG-fast.log']\n"
        "def refuse():raise ValueError('This installer installs XeMFG packages')\n",
    'packaging/launcher_config.py':
        "LAYER='VK_LAYER_BC250_xefg_wave'\nLAYER_PATH='BC250-XeFG/layer'\nSWITCH='BC250_XEFG_DISABLE'\n"
        "RUNTIME='xemfg'\nCONFIG='XEFG_WAVE_CONFIG'\n",
    'src/x.c': 'static const char*dll="bc250_xefg_original.dll";\n#ifdef XEFG_INTEL_FREE\n#endif\n'
               'static const char*ok="XEFG_SWAPCHAIN_RESULT_SUCCESS";\n',
    'packaging/Start-BC250-XeFG.sh': '#!/bin/sh\n',
    'packaging/extras/x/bc250-xemfg-gamescope-cap.hook': '[Trigger]\n',
    'release/test_release_tools.py': "FOLDER='BC250-XeFG/'\n",  # names.json "exclude"
}


class RenameTool(unittest.TestCase):
    """release/rename.py with release/names.json on a small fixture tree, and on this tree (dry run only); and
    packaging/install.py under an isolated interpreter (python3 -I), which does not put a script's folder on sys.path."""

    @classmethod
    def setUpClass(cls):
        import rename
        cls.rename = rename
        cls.names = package_name_form(rename.load_names())

    def tree(self, private=False, package=None, extra=None):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        files = dict(FIXTURE, **(extra or {}))
        files['release/package.json'] = json.dumps(package or fixture_package(), indent=1) + '\n'
        listed = sorted(files) + ['release/keep-public.txt', 'release/profile/a.dxil']
        files['release/keep-public.txt'] = '# fixture\n' + '\n'.join(listed) + '  # trailing comment\n'
        if private:
            files['release/keep.txt'] = '\n'.join(listed) + '\n'
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding='utf-8')
        (root / 'release/profile').mkdir()
        (root / 'release/profile/a.dxil').write_bytes(b'DXBC\0BC250-XeFG/')  # binary: never scanned or rewritten
        return root

    def apply(self, root, **kwargs):
        kwargs.setdefault('name', 'Lumen Pace')
        kwargs.setdefault('slug', 'lumen-pace')
        return self.rename.apply(root, self.names, **kwargs)

    @staticmethod
    def snapshot(root):
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}

    # names.json

    def test_names_json(self):
        families = self.names['families']
        self.assertEqual([f['id'] for f in families if f['class'] == 'user-visible' and f.get('default')],
                         ['product-name', 'user-agent', 'mit-holder', 'setup-title', 'package-name'])
        self.assertEqual(families[-1]['id'], 'old-name')  # the catch-all claims last
        for family in families:
            if family['class'] == 'compat':
                self.assertIn(family['policy'], ('rename-with-compat', 'rename-with-rebuild', 'keep', 'keep-with-alias'))
            if family['class'] in ('internal', 'review'):
                self.assertFalse(family.get('replacements'), family['id'])
        self.assertEqual(self.names['library_owner']['pattern'], OWNER.pattern)
        import export_tree
        root_files = getattr(export_tree, 'PUBLIC_ROOT', None)
        if root_files is not None:
            self.assertEqual(sorted(self.names['public_root_files']['files']), sorted(root_files))

    # scan

    def test_scan_groups_each_occurrence_once(self):
        result = self.rename.scan(self.tree(), self.names)
        found = {f['id']: [(o['file'], o['line'], o['text']) for o in f['occurrences']] for f in result['families']}
        self.assertEqual(found['product-name'], [('packaging/public/README.md', 1, '[PRODUCT]'),
                                                 ('packaging/public/README.md', 3, '[PRODUCT]')])
        self.assertEqual([f for f, _, _ in found['setup-title']],
                         ['packaging/mfg/setup.py', 'packaging/mfg/setup.py', 'scripts/test_setup_front_end.py'])
        self.assertEqual(len(found['package-name']), 3)
        self.assertEqual(len(found['user-agent']), 3)
        self.assertEqual(found['mit-holder'], [('packaging/public/LICENSE', 3, '[COPYRIGHT HOLDER]')])
        self.assertEqual(sorted(t for _, _, t in found['launcher-script']),  # README, package path, source, keep list
                         ['Start-BC250-XeFG.sh'] * 2 + ['packaging/Start-BC250-XeFG.sh'] * 2)
        self.assertEqual(len(found['log-names']), 3)
        self.assertEqual([t for _, _, t in found['compile-macros']], ['XEFG_INTEL_FREE'])  # not Intel's XEFG_SWAPCHAIN_*
        self.assertEqual(found['old-name'], [('packaging/install.py', 3, 'XeMFG')])
        for family in ('state-dir', 'layer-name', 'user-env', 'xefg-env', 'runtime-record', 'build-env', 'runtime-dll'):
            self.assertEqual(len(found[family]), 1, family)
        texts = [t for items in found.values() for _, _, t in items]
        self.assertNotIn('XeFG', texts)  # Intel's names on their own are no rename item
        self.assertNotIn('XeSS', texts)
        self.assertFalse(any(f == 'release/test_release_tools.py' for items in found.values() for f, _, _ in items))
        self.assertEqual(result['excluded'], ['release/test_release_tools.py'])
        self.assertIn('release/profile/a.dxil', result['binary_or_missing'])
        self.assertEqual(result['paths'], ['packaging/Start-BC250-XeFG.sh',
                                           'packaging/extras/x/bc250-xemfg-gamescope-cap.hook'])

    # apply

    def test_dry_run_writes_nothing(self):
        root = self.tree()
        before = self.snapshot(root)
        result = self.apply(root)
        self.assertTrue(result['changes'])
        self.assertFalse(result['written'])
        self.assertEqual(self.snapshot(root), before)

    def test_default_families(self):
        root = self.tree()
        before = self.snapshot(root)
        result = self.apply(root, write=True)
        self.assertTrue(result['written'])
        self.assertEqual({k: v['replacements'] for k, v in result['families'].items()},
                         {'product-name': 2, 'user-agent': 3, 'mit-holder': 1, 'setup-title': 3, 'package-name': 1})
        read = lambda name: (root / name).read_text(encoding='utf-8')  # noqa: E731
        readme = read('packaging/public/README.md')
        self.assertTrue(readme.startswith('# Lumen Pace\n\nLumen Pace works with Intel XeSS Frame Generation (XeFG)'))
        self.assertIn('`lumen-pace-installer/1`', readme)
        self.assertIn('BC250-XeFG-fast.log` in `BC250-XeFG/`', readme)  # compatibility names stay
        self.assertIn('Start-BC250-XeFG.sh', readme)  # not a default family
        self.assertIn('Copyright (c) 2026 Lumen Pace contributors\n', read('packaging/public/LICENSE'))
        setup = read('packaging/mfg/setup.py')
        self.assertIn("NAME='Lumen Pace'\n", setup)
        self.assertIn("'--title='+NAME", setup)
        self.assertIn("TEMP='bc250-xefg-setup-'", setup)
        self.assertIn("self.setup.NAME, 'Lumen Pace'", read('scripts/test_setup_front_end.py'))
        self.assertEqual(read('release/fetch.py'), "AGENT='lumen-pace-release-fetch'\n")
        self.assertIn("CACHE='bc250-xefg-testers'", read('packaging/dependencies.py'))
        spec = json.loads(read('release/package.json'))
        self.assertEqual(spec['name'], 'bc250-fsr4-xemfg-private-test-31')
        self.assertTrue(OWNER.search(spec['name']))  # the library owner still finds private builds
        self.assertEqual(spec['variants']['intel-free']['name'], 'bc250-fsr4-xemfg-private-test-31-intel-free')
        self.assertEqual(spec['variants']['intel-free-2x']['name'], 'lumen-pace-31-2x')
        self.assertIsNone(OWNER.search('lumen-pace-31-2x'))
        self.assertEqual(result['public_package_name'], 'lumen-pace-31-2x')
        self.assertIsNone(result['assemble_accepts_public_name'])  # no assemble.py in the fixture
        after = self.snapshot(root)
        for name in ('packaging/install.py', 'packaging/launcher_config.py', 'src/x.c', 'release/config.py',
                     'release/profile/a.dxil', 'release/test_release_tools.py', 'release/keep-public.txt'):
            self.assertEqual(after[name], before[name], name)
        again = self.apply(root, write=True)
        self.assertEqual(again['changes'], [])
        self.assertEqual(sum('nothing to rewrite' in w for w in again['warnings']), 5)

    def test_holder(self):
        root = self.tree()
        self.apply(root, holder='Jane Doe', write=True)
        self.assertIn('Copyright (c) 2026 Jane Doe\n', (root / 'packaging/public/LICENSE').read_text())
        for holder in ('x', 'a\\1', '{name}', 'two\nlines'):
            with self.assertRaises(self.rename.RenameError, msg=holder):
                self.apply(root, holder=holder)

    def test_compatibility_families(self):
        root = self.tree()
        result = self.apply(root, include_compat=True, write=True)
        self.assertIn('layer-name', result['families'])
        self.assertNotIn('state-dir', result['families'])  # needs an alias: only by --family
        launcher = (root / 'packaging/launcher_config.py').read_text()
        self.assertIn("LAYER='VK_LAYER_LUMEN_PACE_wave'", launcher)
        for kept in ("LAYER_PATH='BC250-XeFG/layer'", "SWITCH='BC250_XEFG_DISABLE'", "RUNTIME='xemfg'",
                     "CONFIG='XEFG_WAVE_CONFIG'"):
            self.assertIn(kept, launcher)
        self.assertIn("CACHE='lumen-pace'", (root / 'packaging/dependencies.py').read_text())
        self.assertEqual((root / 'release/config.py').read_text(), "SETTINGS={'work': 'LUMEN_PACE_WORK'}\n")
        self.assertIn('"bc250_xefg_original.dll"', (root / 'src/x.c').read_text())  # needs a rebuild: only by --family
        self.assertIn("TEMP='lumen-pace-setup-'", (root / 'packaging/mfg/setup.py').read_text())
        install = (root / 'packaging/install.py').read_text()
        self.assertIn("STATE='.bc250-xefg-experimental'", install)
        self.assertIn("PROXY_LOGS=['BC250-MFG.log','BC250-XeFG-fast.log']", install)
        self.assertNotIn('runtime-dll', result['families'])
        rebuilt = self.apply(root, family_ids=['runtime-dll'], write=True)
        self.assertIn('"lumen_pace_original.dll"', (root / 'src/x.c').read_text())
        self.assertTrue(any('runtime-dll: rebuild libxess_fg.dll' in line for line in rebuilt['follow_ups']))
        named = self.apply(root, family_ids=['state-dir'], write=True)
        self.assertIn("STATE='.lumen-pace'", (root / 'packaging/install.py').read_text())
        self.assertTrue(any(w.startswith('state-dir: earlier installations need the old name') for w in named['warnings']))
        for family in ('runtime-record', 'old-name', 'no-such-family'):
            with self.assertRaises(self.rename.RenameError, msg=family):
                self.apply(root, family_ids=[family])

    def test_tracked_files_follow_the_keep_list(self):
        root = self.tree()
        result = self.apply(root, family_ids=['extras-hook', 'launcher-script'], defaults=False, write=True)
        new = 'packaging/extras/x/lumen-pace-gamescope-cap.hook'
        self.assertEqual(result['moves'], {'packaging/extras/x/bc250-xemfg-gamescope-cap.hook': new})
        self.assertTrue((root / new).is_file())
        self.assertFalse((root / 'packaging/extras/x/bc250-xemfg-gamescope-cap.hook').exists())
        self.assertIn(new, self.rename.keep_entries(root / 'release/keep-public.txt'))
        files = json.loads((root / 'release/package.json').read_text())['components']['installer']['files']
        self.assertEqual(files['extras/x/lumen-pace-gamescope-cap.hook'], 'repo:' + new)
        self.assertEqual(files['Start-lumen-pace.sh'], 'repo:packaging/Start-BC250-XeFG.sh')  # the source keeps its name
        self.assertTrue((root / 'packaging/Start-BC250-XeFG.sh').is_file())

    def test_public_package_json(self):
        root = self.tree(package=fixture_package(public=True))
        self.apply(root, write=True)
        spec = json.loads((root / 'release/package.json').read_text())
        self.assertEqual((spec['name'], spec['variants']['intel-free-2x']['name']), ('lumen-pace-31-2x',) * 2)

    def test_private_names_never_change(self):
        package = fixture_package()
        package['name'] = 'bc250-fsr4-xemfg-private-test-31-intel-free-2x'  # a private tree's top-level name
        with self.assertRaisesRegex(self.rename.RenameError, 'private package name'):
            self.apply(self.tree(package=package))

    def test_refused_names(self):
        root = self.tree()
        for name in ('Xe Pace', 'XeBoost', 'FSR4 Plus', 'DLSS-Lite', 'Intel Pacer', 'NVIDIA Frames', 'Pace XeSS',
                     'Radeon Boost', 'xefg', 'XEFG Pace', 'a', 'Pace"', 'Pace\\', '{name}', '-Pace'):
            with self.assertRaises(self.rename.RenameError, msg=name):
                self.apply(root, name=name)
        for slug in ('xe-pace', 'fsr-boost', 'pace-dlss3', 'Lumen', 'lumen_pace', 'lumen-'):
            with self.assertRaises(self.rename.RenameError, msg=slug):
                self.apply(root, slug=slug)
        self.assertEqual(self.rename.check_name('Lumen Pace', 'lumen-pace', self.names), [])
        self.assertTrue(self.rename.check_name('Xenon Pace', 'xenon-pace', self.names))  # a warning, not a refusal
        self.assertTrue(self.rename.check_name('BC250 Pace', 'bc250-pace', self.names))

    def test_write_refused_in_the_private_tree(self):
        root = self.tree(private=True)
        self.apply(root)  # a dry run is fine
        with self.assertRaisesRegex(self.rename.RenameError, 'private tree'):
            self.apply(root, write=True)
        self.assertTrue(self.apply(root, write=True, allow_private_tree=True)['written'])

    def test_library_form(self):
        changed, moves, _warnings = self.rename.rename_texts({'packaging/public/README.md': '# [PRODUCT]\n'},
                                                            'Lumen Pace', 'lumen-pace')
        self.assertEqual((changed, moves), ({'packaging/public/README.md': '# Lumen Pace\n'}, {}))
        with self.assertRaises(self.rename.RenameError):
            self.rename.rename_texts({}, 'Intel Pace', 'pace')

    def test_this_tree(self):
        """A dry run here (or in a public export): no [PRODUCT] placeholder survives in the documents, and while the
        tree still has the placeholder (it is not renamed yet) every default family finds what it renames."""
        texts, _skipped, _excluded = self.rename.tree_files(TREE, self.names)
        result = self.rename.plan(texts, self.names, 'Lumen Pace', 'lumen-pace')
        self.assertEqual(result['problems'], [])
        docs = [n for n in texts if n.endswith('.md')]
        self.assertTrue(docs)
        if any('[PRODUCT]' in texts[name] for name in docs):
            for family in ('product-name', 'user-agent', 'mit-holder', 'setup-title', 'package-name'):
                self.assertTrue(result['counts'][family], f'{family}: its patterns no longer match this tree (names.json)')
        for name in docs:
            self.assertNotIn('[PRODUCT]', result['changed'].get(name, texts[name]), name)
        if result['public_name']:
            self.assertIsNone(OWNER.search(result['public_name']))

    # packaging/install.py under python3 -I

    def test_install_finds_its_modules_under_an_isolated_interpreter(self):
        with tempfile.TemporaryDirectory() as folder:
            package = Path(folder) / 'package'
            package.mkdir()
            for name in ('install.py', 'launcher_config.py', 'steam_config.py'):
                shutil.copy2(TREE / 'packaging' / name, package / name)
            shutil.copytree(TREE / 'packaging/vendor', package / 'vendor')
            # A stand-in for doctor.py that imports what the real modules import, without probing this system.
            (package / 'doctor.py').write_text('def main():\n    import launcher_config\n    from vendor import yaml\n'
                                               '    print("doctor", launcher_config.Document.__name__, yaml.__name__)\n'
                                               '    return 0\n')
            out = subprocess.run([sys.executable, '-I', '-B', str(package / 'install.py'), 'doctor'], cwd=folder,
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual((out.returncode, out.stdout.strip()), (0, 'doctor Document vendor.yaml'), out.stderr)

    def test_install_adds_its_folder_once(self):
        import importlib.util
        folder = str((TREE / 'packaging').resolve())
        had = folder in sys.path
        try:
            for module in ('rename_test_install_a', 'rename_test_install_b'):
                spec = importlib.util.spec_from_file_location(module, TREE / 'packaging/install.py')
                spec.loader.exec_module(importlib.util.module_from_spec(spec))
            self.assertEqual(sys.path.count(folder), 1)
        finally:
            if not had:
                while folder in sys.path:
                    sys.path.remove(folder)


# --------------------------------------------------------------------- the chosen public name: export and assembly
import hashlib  # noqa: E402
import types  # noqa: E402
from unittest import mock  # noqa: E402

CHOSEN = {'name': 'Lumen Pace', 'slug': 'lumen-pace'}
EMPTY_CHOSEN = {'about': 'test', 'name': None, 'slug': None, 'holder': None, 'families': []}
# The package-name family's public_template and replacement template in the build-number form the fixtures assume
# (the private build number: lumen-pace-31-2x, v31-2x). This tree's names.json may carry a decided version instead;
# the tests named this_tree use the tree's own family.
BUILD_NUMBER_FORM = ('{slug}-{number}-2x', '\\1{slug}-\\2-2x\\3')
FIXED_SEMVER_FORM = ('{slug}-0.1.0', '\\1{slug}-0.1.0\\3')  # a decided dotted version, as names.json would carry it


def package_name_form(names, form=BUILD_NUMBER_FORM):
    """names (release/names.json as loaded) with the package-name family's public_template and replacement template
    set to form, and the committed receipt template."""
    family = next(f for f in names['families'] if f['id'] == 'package-name')
    family['public_template'], family['replacements'][0]['template'] = form
    family['public_receipt_template'] = '{slug}-{version}-package.json'
    return names


def names_with(chosen, form=BUILD_NUMBER_FORM):
    """release/names.json loaded by rename.py, with "chosen" replaced (the committed block is never changed) and the
    package-name family in form (None: as this tree has it)."""
    import rename
    names = rename.load_names()
    names['chosen'] = dict(EMPTY_CHOSEN, **chosen)
    return package_name_form(names, form) if form else names


def export_contents():
    """{path: bytes} of FIXTURE as export_tree.py --public writes it: the public package.json, the top copies of the
    public README and licence, and a binary profile file."""
    contents = {name: text.encode('utf-8') for name, text in FIXTURE.items()}
    contents['release/package.json'] = (json.dumps(fixture_package(public=True), indent=1) + '\n').encode()
    contents['README.md'] = FIXTURE['packaging/public/README.md'].encode('utf-8')
    contents['LICENSE'] = FIXTURE['packaging/public/LICENSE'].encode('utf-8')
    contents['release/profile/a.dxil'] = b'DXBC\0BC250-XeFG/'
    return contents


def identifier_counts(texts, names, classes=('compat', 'internal')):
    """{family id: number of matches of its patterns} over texts ({path: str}) for the families of these classes."""
    return {f['id']: sum(len(p.findall(text)) for p in f['_patterns'] for text in texts.values())
            for f in names['families'] if f['class'] in classes}


def decoded(contents, root=TREE):
    """{path: text} of contents ({path: bytes, or None for a file of root}), binary files left out: those with a NUL
    byte or not UTF-8, as release/rename.py text_of() reads them (a third-party licence text in Windows-1252, such as
    NVIDIA's, is kept byte for byte and is no rename item)."""
    out = {}
    for name, data in contents.items():
        data = data if data is not None else (root / name).read_bytes()
        if b'\0' not in data:
            try:
                out[name] = data.decode('utf-8')
            except UnicodeDecodeError:
                pass
    return out


class ExportRename(unittest.TestCase):
    """export_tree.public_rename: names.json "chosen" applied to the copies a public export writes."""

    @classmethod
    def setUpClass(cls):
        import export_tree
        import rename
        cls.export_tree, cls.rename = export_tree, rename

    def test_committed_block(self):
        """names.json has an explicit "chosen" block that chosen_name() accepts; while it is empty (no decided name)
        the export of this tree renames nothing."""
        names = self.rename.load_names()
        self.assertIn('chosen', names)
        self.assertLessEqual(set(names['chosen']), set(self.rename.CHOSEN_KEYS))
        if self.rename.chosen_name(names) is None:
            contents = {name: None for name in self.export_tree.read_keep(public=True)}
            out, report = self.export_tree.public_rename(contents)
            self.assertIs(out, contents)
            self.assertEqual(report, dict(chosen=None))

    def test_no_chosen_name_changes_nothing(self):
        contents = export_contents()
        for chosen in ({}, {'name': '', 'slug': ''}):
            out, report = self.export_tree.public_rename(contents, names_with(chosen))
            self.assertIs(out, contents)
            self.assertEqual(report, dict(chosen=None))

    def test_chosen_name_renames_the_copies(self):
        contents = export_contents()
        before = copy.deepcopy(contents)
        names = names_with(CHOSEN)
        out, report = self.export_tree.public_rename(contents, names)
        self.assertEqual(contents, before)  # the input is not changed
        self.assertEqual(sorted(n for n in out if out[n] != contents[n]), report['files'])
        text = lambda name: out[name].decode('utf-8')  # noqa: E731
        for readme in ('packaging/public/README.md', 'README.md'):
            self.assertTrue(text(readme).startswith('# Lumen Pace\n\nLumen Pace works with Intel XeSS Frame Generation '
                                                    '(XeFG); it is not XeSS itself.\n'), readme)
            self.assertIn('`lumen-pace-installer/1`', text(readme))
            # compatibility identifiers and non-default families stay
            for kept in ('`BC250-XeFG-fast.log` in `BC250-XeFG/`', '~/.cache/bc250-xefg-testers', 'Start-BC250-XeFG.sh',
                         'licenses/BC250-XeFG.txt'):
                self.assertIn(kept, text(readme))
        for licence in ('packaging/public/LICENSE', 'LICENSE'):
            self.assertEqual(text(licence), 'MIT License\n\nCopyright (c) 2026 Lumen Pace contributors\n')
        setup = text('packaging/mfg/setup.py')
        self.assertIn("NAME='Lumen Pace'\n", setup)
        self.assertIn("'--title='+NAME", setup)
        self.assertIn("TEMP='bc250-xefg-setup-'", setup)  # temp-prefix is compat
        self.assertIn("self.setup.NAME, 'Lumen Pace'", text('scripts/test_setup_front_end.py'))
        self.assertEqual(text('release/fetch.py'), "AGENT='lumen-pace-release-fetch'\n")
        self.assertEqual(text('packaging/dependencies.py'),
                         "HEADERS={'User-Agent': 'lumen-pace-installer/1'}\nCACHE='bc250-xefg-testers'\n")
        spec = json.loads(out['release/package.json'])
        expected = self.rename.public_package_name(names, self.rename.template_fields('Lumen Pace', 'lumen-pace'), '31')
        self.assertEqual(expected, 'lumen-pace-31-2x')
        self.assertEqual((spec['name'], spec['variants']['intel-free-2x']['name']), (expected, expected))
        self.assertIsNone(OWNER.search(expected))
        self.assertEqual(spec['components'], fixture_package(public=True)['components'])  # package paths stay
        for name in ('packaging/install.py', 'packaging/launcher_config.py', 'src/x.c', 'release/config.py',
                     'release/profile/a.dxil', 'release/test_release_tools.py', 'packaging/Start-BC250-XeFG.sh',
                     'packaging/extras/x/bc250-xemfg-gamescope-cap.hook'):
            self.assertEqual(out[name], contents[name], name)
        self.assertEqual(identifier_counts(decoded(out), names), identifier_counts(decoded(contents), names))
        self.assertEqual((report['public_package_name'], report['version'], report['receipt']),
                         (expected, 'v31-2x', 'qualification/lumen-pace-v31-2x-package.json'))
        self.assertEqual(report['chosen'], dict(name='Lumen Pace', slug='lumen-pace', holder=None, families=[]))

    def test_idempotent(self):
        names = names_with(CHOSEN)
        once, _ = self.export_tree.public_rename(export_contents(), names)
        again, report = self.export_tree.public_rename(once, names)
        self.assertEqual(again, once)
        self.assertEqual(report['files'], [])
        self.assertEqual(report['public_package_name'], 'lumen-pace-31-2x')  # already renamed: still checked

    def test_holder_and_extra_families(self):
        names = names_with(dict(CHOSEN, holder='Jane Doe', families=['launcher-script', 'licence-file']))
        out, report = self.export_tree.public_rename(export_contents(), names)
        readme = out['packaging/public/README.md'].decode()
        self.assertIn('start `./Start-lumen-pace.sh`; licence `licenses/lumen-pace.txt`', readme)
        self.assertIn('Copyright (c) 2026 Jane Doe\n', out['LICENSE'].decode())
        files = json.loads(out['release/package.json'])['components']['installer']['files']
        self.assertEqual(files['Start-lumen-pace.sh'], 'repo:packaging/Start-BC250-XeFG.sh')  # the source keeps its name
        self.assertEqual(files['licenses/lumen-pace.txt'], 'repo:packaging/public/LICENSE')
        self.assertEqual(report['chosen']['families'], ['launcher-script', 'licence-file'])

    def test_refused_choices(self):
        contents = export_contents()
        for chosen in ({'name': 'Lumen Pace'}, {'slug': 'lumen-pace'}, {'holder': 'Jane Doe'}, {'families': ['licence-file']},
                       {'name': 'Xe Pace', 'slug': 'xe-pace'}, {'name': 'Lumen Pace', 'slug': 'pace-dlss'},
                       dict(CHOSEN, holder='x'), dict(CHOSEN, families=['layer-name']), dict(CHOSEN, families=['old-name']),
                       dict(CHOSEN, families=['no-such-family']), dict(CHOSEN, families='launcher-script'),
                       dict(CHOSEN, colour='blue'), dict(CHOSEN, name=5), dict(CHOSEN, holder=['Jane Doe'])):
            with self.assertRaises(self.export_tree.ReleaseError, msg=chosen):
                self.export_tree.public_rename(contents, names_with(chosen))

    def test_template_drift_refused(self):
        """The rewritten package name must be package-name's public_template (assemble.py parses public names by it)."""
        names = names_with(CHOSEN)
        names['_by_id']['package-name']['public_template'] = '{slug}-v{number}'
        with self.assertRaisesRegex(self.export_tree.ReleaseError, 'public_template'):
            self.export_tree.public_rename(export_contents(), names)
        # a decided version written into one of the two only
        for form in (('{slug}-0.1.0', '\\1{slug}-0.2.0\\3'), ('{slug}-0.1.0', '\\1{slug}-\\2-2x\\3'),
                     ('{slug}-{number}-2x', '\\1{slug}-0.1.0-2x\\3')):
            with self.assertRaisesRegex(self.export_tree.ReleaseError, 'public_template', msg=form):
                self.export_tree.public_rename(export_contents(), names_with(CHOSEN, form))

    def test_decided_version_is_names_json_data(self):
        """A decided version is two edits of names.json (public_template and the replacement's template, the same fixed
        text): the export names the public package with it, with no change to rename.py or assemble.py."""
        for form, name, version in ((FIXED_SEMVER_FORM, 'lumen-pace-0.1.0', 'v0.1.0'),
                                    (('{slug}-0.1.0-2x', '\\1{slug}-0.1.0-2x\\3'), 'lumen-pace-0.1.0-2x', 'v0.1.0-2x'),
                                    (('{slug}-32-2x', '\\1{slug}-32-2x\\3'), 'lumen-pace-32-2x', 'v32-2x')):
            out, report = self.export_tree.public_rename(export_contents(), names_with(CHOSEN, form))
            spec = json.loads(out['release/package.json'])
            self.assertEqual((spec['name'], spec['variants']['intel-free-2x']['name']), (name, name), form)
            self.assertEqual((report['public_package_name'], report['version'], report['receipt']),
                             (name, version, f'qualification/lumen-pace-{version}-package.json'), form)
            self.assertIsNone(OWNER.search(name))

    def test_this_tree_with_a_chosen_name(self):
        """This tree's public export renamed under a trial name: the documents lose [PRODUCT], the public package is
        named by the template and still projects to itself, compatibility and internal identifiers keep every
        occurrence, no C source or binary changes, and no file of this tree is written."""
        export_tree, rename = self.export_tree, self.rename
        listed = export_tree.read_keep(public=True)
        spec = json.loads((TREE / export_tree.PACKAGE).read_text())
        public, _ = export_tree.public_package(spec, set(listed))
        if not re.search(r'private-test-(\d+)', public['name']):
            self.skipTest(f'this tree is a public export renamed already ({public["name"]})')
        contents = {name: None for name in listed}
        contents.update(export_tree.public_root(listed)[0])
        contents[export_tree.PACKAGE] = export_tree.json_text(public).encode()
        on_disk = {name: (TREE / name).read_bytes() for name in listed}
        names = names_with(CHOSEN, form=None)  # this tree's own package-name family
        out, report = export_tree.public_rename(contents, names)
        self.assertEqual({name: (TREE / name).read_bytes() for name in listed}, on_disk)
        self.assertTrue(report['files'])
        for name in report['files']:
            self.assertFalse(name.startswith('src/') or name.endswith(('.c', '.h', '.so', '.dll', '.dxil')), name)
        self.assertNotIn('release/files/layer.json', report['files'])  # layer-description is not a default
        texts = decoded(out)
        for name, text in texts.items():
            if name.endswith('.md') and name not in names['exclude']:
                self.assertNotIn('[PRODUCT]', text, name)
        self.assertIn('Lumen Pace', texts['README.md'])
        number = re.search(r'private-test-(\d+)', public['name'])[1]
        expected = rename.public_package_name(names, rename.template_fields('Lumen Pace', 'lumen-pace'), number)
        renamed = json.loads(out[export_tree.PACKAGE])
        self.assertEqual((renamed['name'], report['public_package_name']), (expected, expected))
        self.assertEqual(export_tree.json_text(export_tree.public_package(renamed, set(listed))[0]),
                         out[export_tree.PACKAGE].decode())
        lock, _ = export_tree.public_lock(json.loads((TREE / export_tree.LOCK).read_text()))
        self.assertEqual(export_tree.public_package_problems(renamed, lock, set(listed).__contains__), [])
        self.assertEqual(identifier_counts(texts, names), identifier_counts(decoded(contents), names))


DEPENDENCIES = {'runtime': {'ProxyPackage': {'payload/bc250_xefg_original.dll': 'intel/libxess_fg.dll'},
                            'Files': {'intel/libxess_fg.dll': '0' * 64}}}


def assembly_package():
    """A private package.json in release/package.json's shape (a default package and its intel-free-2x variant) that
    assemble.assemble() builds from FakeSources."""
    manifest = dict(runtime='xemfg', launcher_setup='automatic', profile={'name': 'p'}, default_factor=2,
                    default_cap='match output', fsr4='f', enabler='e', status='s', frame_start_pacing={},
                    enabler_overlay='o', extras={}, runtime_downloads='r')
    return {
        'about': 'x', 'name': 'bc250-fsr4-xemfg-private-test-31', 'manifest': manifest,
        'components': {
            'installer': {'files': {'install.py': 'repo:packaging/install.py',
                                    'dependencies.json': 'repo:packaging/dependencies.json'}},
            'documents': {'files': {'README.md': 'repo:packaging/v31/README.md'}},
            'addon': {'files': {'payload/OptiScaler/plugins/BC250-MFG.asi': 'build:addon'}},
            'layer': {'files': {'payload/BC250-XeFG/layer/libxefg_wave.so': 'build:layer'}},
            'licenses': {'files': {'licenses/BC250-XeFG.txt': 'repo:LICENSE.new-code'}}},
        'never_ship': {'paths': [], 'prefixes': ['fsr4/'], 'sha256': {}},
        'source_companion': {'description': 'd', 'files': {}},
        'installer_tests': [],
        'variants': {'intel-free-2x': {
            'about': 'v', 'name': 'bc250-fsr4-xemfg-private-test-31-intel-free-2x', 'package_dir': 'package-intel-free-2x',
            'documents_version': 'public', 'manifest': {'addon_entry': 'libxess_fg-proxy', 'max_factor': 2},
            'allowed_components': {}, 'replace': {'addon': 'addon-intel-free-2x', 'documents': 'documents-public'},
            'components': {
                'addon-intel-free-2x': {'files': {
                    'payload/libxess_fg.dll': 'build:addon-intel-free-2x',
                    'payload/BC250-XeFG/shaders/a.dxil': 'build:addon-intel-free-2x-profile/a.dxil',
                    'qualification/addon-build.json': 'build:addon-intel-free-2x-record'}},
                'documents-public': {'files': {'README.md': 'repo:packaging/public/README.md'}}},
            'never_ship': {'paths': ['payload/bc250_xefg_original.dll'], 'prefixes': ['fsr4/'],
                           'sha256': {'0' * 64: "Intel's runtime"}}}}}


class FakeSources:
    """assemble.Sources for a package assembled from nothing: each source is a small file under <build>/../sources,
    each build a record that matches its binary (no compiler, no work directory, no lock)."""

    def __init__(self, config):
        self.root = config.build.parent / 'sources'

    def file(self, name, data):
        path = self.root / name
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return path

    def record(self, kind):
        binary = self.file(f'build/{kind}/output', f'{kind} binary\n'.encode())
        record = dict(sha256=hashlib.sha256(binary.read_bytes()).hexdigest(), sources={}, matches_reference=True,
                      profile=dict(file_sha256={'a.dxil': hashlib.sha256(b'a.dxil\n').hexdigest()}))
        return record, binary, self.file(f'build/{kind}/build.json', json.dumps(record).encode())

    def resolve(self, source):
        scheme, _, rest = source.partition(':')
        if scheme == 'repo':
            data = json.dumps(DEPENDENCIES).encode() if rest == 'packaging/dependencies.json' else f'{rest}\n'.encode()
            return self.file(f'repo/{rest}', data)
        target, _, profile_file = rest.partition('/')
        if target.endswith('-profile'):
            return self.file(f'profile/{profile_file}', f'{profile_file}\n'.encode())
        _record, binary, path = self.record(target.removesuffix('-record'))
        return path if target.endswith('-record') else binary


class PublicNameAssembly(unittest.TestCase):
    """release/assemble.py package_naming(): the private names as before, and the public name of names.json's
    public_template, under which a renamed public tree assembles."""

    @classmethod
    def setUpClass(cls):
        import assemble
        import export_tree
        cls.assemble, cls.export_tree = assemble, export_tree
        cls.names = package_name_form(json.loads((RELEASE_DIR / 'names.json').read_text()))

    @staticmethod
    def old_version_of(name):
        """assemble.version_of() before public names (HEAD 38b423f), the reference for private names."""
        match = re.fullmatch(r'bc250-fsr4-xemfg-private-test-(\d+)(-[a-z][a-z0-9-]*)?', name)
        return 'v' + match[1] + (match[2] or '') if match else None

    def test_private_names_as_before(self):
        assemble = self.assemble
        for name in ('bc250-fsr4-xemfg-private-test-31', 'bc250-fsr4-xemfg-private-test-31-intel-free',
                     'bc250-fsr4-xemfg-private-test-31-intel-free-2x', 'bc250-fsr4-xemfg-private-test-7',
                     'bc250-fsr4-xemfg-private-test-100-x2'):
            version = self.old_version_of(name)
            self.assertEqual(assemble.version_of(name), version, name)
            self.assertEqual(assemble.receipt_file(name), f'xemfg-{version}-package.json', name)
            self.assertEqual(assemble.package_naming(name)['kind'], 'private', name)
        # refused before and now (-2x is no private variant, and as a public name its slug carries FSR)
        for name in ('bc250-fsr4-xemfg-private-test-', 'bc250-fsr4-xemfg-v31', 'private-test-31',
                     'bc250-fsr4-xemfg-private-test-31-Intel', 'BC250-fsr4-xemfg-private-test-31',
                     'bc250-fsr4-xemfg-private-test-31-2x'):
            self.assertIsNone(self.old_version_of(name))
            with self.assertRaises(assemble.ReleaseError, msg=name):
                assemble.version_of(name)
        with mock.patch.object(assemble, 'load_names', return_value=None):  # a tree without names.json
            self.assertEqual(assemble.version_of('bc250-fsr4-xemfg-private-test-31'), 'v31')
            with self.assertRaisesRegex(assemble.ReleaseError, r'private-test-NN\[-variant\]: lumen-pace-31-2x'):
                assemble.version_of('lumen-pace-31-2x')

    def test_public_names(self):
        assemble, names = self.assemble, self.names
        self.assertEqual(assemble.package_naming('lumen-pace-31-2x', names),
                         dict(kind='public', version='v31-2x', receipt='lumen-pace-v31-2x-package.json', slug='lumen-pace',
                              number='31'))
        self.assertEqual(assemble.package_naming('pace-2-31-2x', names)['slug'], 'pace-2')
        self.assertIsNone(OWNER.search('lumen-pace-31-2x'))
        for name in ('lumen-pace-31', 'Lumen-Pace-31-2x', 'lumen_pace-31-2x', 'lumen-pace-31-2x-extra', '-31-2x',
                     'xe-pace-31-2x', 'pace-dlss-31-2x', 'intel-free-31-2x', 'lumen-pace-x-2x'):
            with self.assertRaises(assemble.ReleaseError, msg=name):
                assemble.package_naming(name, names)

    def test_dotted_versions(self):
        """{number} is a build number or a dotted semantic version MAJOR.MINOR.PATCH; the private names stay as they
        are."""
        assemble, names = self.assemble, self.names
        self.assertEqual(assemble.package_naming('lumen-pace-0.1.0-2x', names),
                         dict(kind='public', version='v0.1.0-2x', receipt='lumen-pace-v0.1.0-2x-package.json',
                              slug='lumen-pace', number='0.1.0'))
        self.assertEqual(assemble.package_naming('pace-2-10.20.30-2x', names)['number'], '10.20.30')
        self.assertEqual(assemble.package_naming('pace-2-10.20.30-2x', names)['slug'], 'pace-2')
        for name in ('lumen-pace-0.1-2x', 'lumen-pace-01.2.3-2x', 'lumen-pace-1.02.3-2x', 'lumen-pace-0.1.0.1-2x',
                     'lumen-pace-v0.1.0-2x', 'lumen-pace-0.1.0-rc1-2x', 'lumen-pace-0.1.0', 'lumen-pace-.1.0-2x'):
            with self.assertRaises(assemble.ReleaseError, msg=name):
                assemble.package_naming(name, names)
        family = next(f for f in names['families'] if f['id'] == 'package-name')
        family['public_template'] = '{slug}-{number}'
        try:
            self.assertEqual(assemble.package_naming('lumen-pace-0.1.0', names),
                             dict(kind='public', version='v0.1.0', receipt='lumen-pace-v0.1.0-package.json',
                                  slug='lumen-pace', number='0.1.0'))
            self.assertEqual(assemble.package_naming('lumen-pace-31', names)['version'], 'v31')
        finally:
            family['public_template'] = BUILD_NUMBER_FORM[0]
        for name in ('bc250-fsr4-xemfg-private-test-0.1.0', 'bc250-fsr4-xemfg-private-test-0.1.0-intel-free-2x'):
            with self.assertRaises(assemble.ReleaseError, msg=name):
                assemble.package_naming(name, names)
        self.assertEqual(assemble.package_naming('bc250-fsr4-xemfg-private-test-31-intel-free-2x', names),
                         dict(kind='private', version='v31-intel-free-2x',
                              receipt='xemfg-v31-intel-free-2x-package.json'))

    def test_fixed_version_templates(self):
        """Once decided, public_template may carry the version as fixed text in place of {number}."""
        assemble = self.assemble
        names = json.loads((RELEASE_DIR / 'names.json').read_text())
        family = next(f for f in names['families'] if f['id'] == 'package-name')
        cases = {'{slug}-0.1.0': ('lumen-pace-0.1.0', 'v0.1.0'),
                 '{slug}-0.1.0-2x': ('lumen-pace-0.1.0-2x', 'v0.1.0-2x'),
                 '{slug}-32-2x': ('lumen-pace-32-2x', 'v32-2x'), '{slug}-v1.2.3': ('lumen-pace-v1.2.3', 'v1.2.3'),
                 '{slug}-10.0.0': ('lumen-pace-10.0.0', 'v10.0.0')}
        for template, (name, version) in cases.items():
            family['public_template'] = template
            fixed = re.search(r'\d+(?:\.\d+)*', template)[0]
            self.assertEqual(assemble.package_naming(name, names),
                             dict(kind='public', version=version, receipt=f'lumen-pace-{version}-package.json',
                                  slug='lumen-pace', number=fixed), template)
            for other in ('lumen-pace-0.1.1', 'lumen-pace-31-2x', name + '-2x', name.replace('lumen-pace', 'xe-pace')):
                if other != name:
                    with self.assertRaises(assemble.ReleaseError, msg=(template, other)):
                        assemble.package_naming(other, names)
        for template in ('{slug}-2x', '{slug}-0.1', '{slug}-0.1.0.1', '{slug}-01.2.3', '{slug}-1.2.3x', '{slug}',
                         '{slug}-', '{slug}-v'):
            family['public_template'] = template
            with self.assertRaisesRegex(assemble.ReleaseError, 'fixed version', msg=template):
                assemble.package_naming('lumen-pace-0.1.0', names)

    def test_this_tree_template(self):
        """This tree's package-name family, whatever version form it carries, is one assemble.py parses and rename.py's
        replacement reproduces."""
        import rename
        names = rename.load_names()
        public = self.assemble.public_naming(names)
        fields = rename.template_fields('Lumen Pace', 'lumen-pace')
        name = rename.public_package_name(names, fields, '31')
        self.assertTrue(public['pattern'].fullmatch(name), name)
        self.assertEqual(self.assemble.package_naming(name, names)['kind'], 'public')
        replaced = names['_by_id']['package-name']['replacements'][0]
        old = '"name": "bc250-fsr4-xemfg-private-test-31-intel-free-2x"'
        self.assertEqual(replaced['_pattern'].sub(replaced['template'].format(**fields), old), f'"name": "{name}"')

    def test_templates(self):
        assemble = self.assemble
        names = json.loads((RELEASE_DIR / 'names.json').read_text())
        family = next(f for f in names['families'] if f['id'] == 'package-name')
        family['public_template'] = '{slug}-{number}'
        self.assertEqual(assemble.package_naming('lumen-pace-31', names),
                         dict(kind='public', version='v31', receipt='lumen-pace-v31-package.json', slug='lumen-pace',
                              number='31'))
        with self.assertRaisesRegex(assemble.ReleaseError, 'library owner'):
            assemble.package_naming('lumen-private-test-31', names)  # the owner would take it for a private build
        for template in ('{number}-{slug}', '{slug}', '{slug}-{number!r}', '{slug}-{number}-{name}'):
            family['public_template'] = template
            with self.assertRaises(assemble.ReleaseError, msg=template):
                assemble.package_naming('lumen-pace-31-2x', names)
        family['public_template'] = '{slug}-{number}-2x'
        for receipt in ('{slug}-{version}.txt', 'qualification/{slug}.json', '{slug}-{name}.json', None):
            family['public_receipt_template'] = receipt
            with self.assertRaises(assemble.ReleaseError, msg=receipt):
                assemble.package_naming('lumen-pace-31-2x', names)

    def test_rename_reports_that_assemble_accepts(self):
        import rename
        names = rename.load_names()  # assemble_accepts() runs this tree's assemble.py with this tree's names.json
        public = rename.public_package_name(names, rename.template_fields('Lumen Pace', 'lumen-pace'), '31')
        self.assertEqual(rename.assemble_accepts(TREE, public),
                         (True, self.assemble.package_naming(public, names)['version']))
        self.assertEqual(rename.assemble_accepts(TREE, 'bc250-fsr4-xemfg-private-test-31'), (True, 'v31'))
        self.assertFalse(rename.assemble_accepts(TREE, 'xe-pace-31-2x')[0])

    def assembled(self, spec, receipt=None, evidence=None, names=None, public_tree=False):
        """assemble.assemble() of spec with FakeSources in a temporary build directory (no git, keep list, Intel-free
        check or source companion), names.json as names (default: the build-number form, no chosen name) and this tree
        taken for a public export if public_tree: (package directory, manifest, receipt, temporary folder)."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        if evidence:
            for name, value in evidence.items():
                (root / 'evidence').mkdir(exist_ok=True)
                (root / 'evidence' / name).write_text(json.dumps(value))
        config = types.SimpleNamespace(build=root / 'build')
        names = names or names_with({})
        with mock.patch.multiple(self.assemble, Sources=FakeSources, read_keep=lambda: [],
                                 git_state=lambda paths: (None, None), EVIDENCE=root / 'evidence',
                                 intel_free_check=lambda config, spec, out: dict(result='pass'),
                                 load_names=lambda path=None: names, is_public_tree=lambda: public_tree):
            out, manifest, skeleton = self.assemble.assemble(config, spec, companion=False)
            if receipt is None:
                return out, manifest, skeleton, root
            passed = dict(skeleton, status='pass', **receipt)
            (root / 'receipt.json').write_text(json.dumps(passed, indent=2) + '\n')
            out, manifest, staged = self.assemble.assemble(config, spec, root / 'receipt.json', companion=False)
            self.assertEqual((out / 'qualification' / self.assemble.receipt_file(spec['name'])).read_bytes(),
                             (root / 'receipt.json').read_bytes())  # staged verbatim
            return out, manifest, staged, root

    def public_spec(self, chosen=None, form=BUILD_NUMBER_FORM):
        """The fixture's public package.json as export_tree.py --public writes it, renamed under chosen if given (with
        the package-name family in form)."""
        export_tree = self.export_tree
        public, _ = export_tree.public_package(assembly_package())
        if chosen is None:
            return public
        contents = {export_tree.PACKAGE: export_tree.json_text(public).encode(),
                    'packaging/public/README.md': b'# [PRODUCT]\n'}
        out, report = export_tree.public_rename(contents, names_with(chosen, form))
        name = json.loads(out[export_tree.PACKAGE])['name']
        self.assertEqual(report['receipt'], f'qualification/lumen-pace-{report["version"]}-package.json')
        self.assertEqual(report['public_package_name'], name)
        return json.loads(out[export_tree.PACKAGE])

    def test_assembles_under_the_public_name(self):
        spec = self.public_spec(CHOSEN)
        self.assertEqual(spec['name'], 'lumen-pace-31-2x')
        out, manifest, receipt, root = self.assembled(spec)
        self.assertEqual(out, root / 'build/package-intel-free-2x/lumen-pace-31-2x')
        self.assertEqual((manifest['name'], manifest['variant'], manifest['candidate']),
                         ('lumen-pace-31-2x', 'intel-free-2x', True))
        self.assertEqual(sorted(p.name for p in (out / 'qualification').iterdir()),
                         ['addon-build.json', 'lumen-pace-v31-2x-package.json'])
        on_disk = json.loads((out / 'qualification/lumen-pace-v31-2x-package.json').read_text())
        self.assertEqual(on_disk, receipt)
        self.assertEqual((receipt['status'], receipt['version'], receipt['package']), ('pending', 'v31-2x', spec['name']))
        self.assertIn('qualification/lumen-pace-v31-2x-package.json', manifest['files'])
        self.assertEqual(json.loads((out / 'manifest.json').read_text())['name'], 'lumen-pace-31-2x')
        # after qualification: the passed receipt is staged, and one for another version is refused
        _out, manifest, staged, _root = self.assembled(spec, receipt={'results': 'ok'})
        self.assertEqual((staged['status'], manifest['candidate']), ('pass', False))
        with self.assertRaisesRegex(self.assemble.ReleaseError, 'qualifies'):
            self.assembled(spec, receipt={'version': 'v31-intel-free-2x'})
        # an earlier, different build under the same public version in evidence/ is refused
        with self.assertRaisesRegex(self.assemble.ReleaseError, 'already names a different build'):
            self.assembled(spec, evidence={'lumen-pace-v31-2x-package.json': {'payload': {}}})

    def test_private_name_assembles_as_before(self):
        spec = self.public_spec()
        self.assertEqual(spec['name'], 'bc250-fsr4-xemfg-private-test-31-intel-free-2x')
        out, manifest, receipt, _root = self.assembled(spec)
        self.assertEqual(out.name, spec['name'])
        self.assertTrue((out / 'qualification/xemfg-v31-intel-free-2x-package.json').is_file())
        self.assertEqual((receipt['version'], receipt['package']), ('v31-intel-free-2x', spec['name']))
        with self.assertRaisesRegex(self.assemble.ReleaseError, 'already names a different build'):
            self.assembled(spec, evidence={'xemfg-v31-intel-free-2x-package.json': {'payload': {}}})

    def test_assembles_under_a_decided_version(self):
        names = names_with(CHOSEN, FIXED_SEMVER_FORM)
        spec = self.public_spec(CHOSEN, FIXED_SEMVER_FORM)
        self.assertEqual(spec['name'], 'lumen-pace-0.1.0')
        out, manifest, receipt, root = self.assembled(spec, names=names)
        self.assertEqual(out, root / 'build/package-intel-free-2x/lumen-pace-0.1.0')
        self.assertTrue((out / 'qualification/lumen-pace-v0.1.0-package.json').is_file())
        self.assertEqual((receipt['version'], receipt['package']), ('v0.1.0', 'lumen-pace-0.1.0'))
        self.assertTrue(manifest['status'].startswith('Lumen Pace v0.1.0: 2x frame generation'), manifest['status'])

    # the public build's manifest text

    PRIVATE_WORDING = re.compile(r'(?i)private|tester|library owner|measurement build|\bq\d+\b')

    def test_public_manifest_text(self):
        """The public build's status and profile.research are neutral text with the chosen name; the machine-read
        fields (runtime, candidate, profile name) and everything else stay as package.json and the receipt give them."""
        spec = self.public_spec(CHOSEN)
        out, manifest, _receipt, _root = self.assembled(spec, names=names_with(CHOSEN))
        public = self.assemble.PUBLIC_MANIFEST
        self.assertEqual(manifest['status'], public['status'].format(product='Lumen Pace', version='v31-2x'))
        self.assertEqual(manifest['profile'], {'name': 'p', 'research': public['profile.research']})
        for text in (manifest['status'], manifest['profile']['research']):
            self.assertNotIn('[PRODUCT]', text)
            self.assertIsNone(self.PRIVATE_WORDING.search(text), text)
        self.assertEqual((manifest['runtime'], manifest['candidate'], manifest['launcher_setup']),
                         ('xemfg', True, 'automatic'))  # install.py refuses a runtime other than xemfg
        self.assertEqual(json.loads((out / 'manifest.json').read_text())['status'], manifest['status'])
        fixture = assembly_package()['manifest']
        for key in ('fsr4', 'enabler', 'default_cap', 'extras', 'runtime_downloads', 'enabler_overlay'):
            self.assertEqual(manifest[key], fixture[key], key)
        _out, manifest, staged, _root = self.assembled(spec, receipt={'results': 'ok'}, names=names_with(CHOSEN))
        self.assertEqual((staged['status'], manifest['candidate']), ('pass', False))
        self.assertTrue(manifest['status'].startswith('Lumen Pace v31-2x: '))

    def test_public_manifest_without_a_decided_name(self):
        spec = self.public_spec(CHOSEN)
        for names in (names_with({}), names_with({'name': 'Other Name', 'slug': 'other-name'})):
            _out, manifest, _receipt, _root = self.assembled(spec, names=names)
            self.assertTrue(manifest['status'].startswith('[PRODUCT] v31-2x: '), manifest['status'])

    def test_private_text_kept(self):
        """The private builds keep package.json's text: the default package, and the public variant under its private
        name in this tree; in a public export the public variant carries the public text before it is renamed."""
        fixture = assembly_package()
        public_profile = {'name': 'p', 'research': self.assemble.PUBLIC_MANIFEST['profile.research']}
        for spec, text in ((fixture, ('s', {'name': 'p'})),
                           (self.public_spec(), (self.export_tree.PUBLIC_PACKAGE_STATUS, public_profile))):
            _out, manifest, _receipt, _root = self.assembled(spec, names=names_with(CHOSEN))
            self.assertEqual((manifest['status'], manifest['profile']), text, spec['name'])
        _out, manifest, _receipt, _root = self.assembled(fixture, names=names_with(CHOSEN), public_tree=True)
        self.assertEqual(manifest['status'], 's')  # no public documents: not the public build
        _out, manifest, _receipt, _root = self.assembled(self.public_spec(), names=names_with(CHOSEN), public_tree=True)
        self.assertTrue(manifest['status'].startswith('[PRODUCT] v31-intel-free-2x: '), manifest['status'])
        self.assertEqual(manifest['profile']['research'], self.assemble.PUBLIC_MANIFEST['profile.research'])

    def test_package_json_public_variant_wording(self):
        """What the public build no longer ships: this tree's intel-free-2x manifest text (the maintainers' wording)."""
        spec = json.loads((RELEASE_DIR / 'package.json').read_text())
        variant = spec['variants']['intel-free-2x']['manifest'] if 'intel-free-2x' in spec.get('variants', {}) else {}
        manifest = dict(spec['manifest'], **variant)
        public = self.assemble.public_manifest(manifest, 'v31-2x', 'Lumen Pace')
        self.assertIsNone(self.PRIVATE_WORDING.search(public['status'] + public['profile']['research']))
        self.assertEqual((public['runtime'], public['profile']['name']),
                         (manifest['runtime'], manifest['profile']['name']))

    # the --archive gate of the public package

    def archive_gate(self, spec, names, docs_errors=(), receipt=None, companion=None):
        """assemble.assemble(..., archive_requested=True) of spec after a pending assembly, with a passed receipt (plus
        receipt's fields), a clean git checkout and check_public_docs.py --release replaced by docs_errors (None: it
        must not run): (package directory, manifest). companion: a stand-in for release/source_companion.py (then the
        source companion is built)."""
        def docs(root=None):
            if docs_errors is None:
                raise AssertionError('check_public_docs.py ran for a package without the public documents')
            return list(docs_errors)
        _out, _manifest, skeleton, root = self.assembled(spec, names=names)
        passed = dict(skeleton, status='pass', **(receipt or {}))
        (root / 'receipt.json').write_text(json.dumps(passed, indent=2) + '\n')
        config = types.SimpleNamespace(build=root / 'build')
        with mock.patch.multiple(self.assemble, Sources=FakeSources, read_keep=lambda: [],
                                 git_state=lambda paths: ('0' * 40, []), EVIDENCE=root / 'evidence',
                                 intel_free_check=lambda config, spec, out: dict(result='pass'),
                                 load_names=lambda path=None: names, is_public_tree=lambda: False,
                                 public_docs_errors=docs, **({'source_companion': companion} if companion else {})):
            out, manifest, _receipt = self.assemble.assemble(config, spec, root / 'receipt.json',
                                                            companion=companion is not None, archive_requested=True)
        return out, manifest

    def test_archive_gate(self):
        spec, names = self.public_spec(CHOSEN), names_with(CHOSEN)
        out, manifest = self.archive_gate(spec, names)
        self.assertEqual((out.name, manifest['candidate']), ('lumen-pace-31-2x', False))
        error = self.assemble.ReleaseError
        with self.assertRaisesRegex(error, r'check_public_docs\.py --release reports 2 error\(s\): README\.md: '
                                           r'placeholders \{\'\[VERSION\]\': 1\}; NOTICE\.md: \[DRAFT\] marker'):
            self.archive_gate(spec, names, ["README.md: placeholders {'[VERSION]': 1}", 'NOTICE.md: [DRAFT] marker'])
        with self.assertRaisesRegex(error, r'manifest\.json still carries \[PRODUCT\] \(release/names\.json "chosen" '
                                           r'names no product'):
            self.archive_gate(spec, names_with({}))
        with self.assertRaisesRegex(error, r'the receipt receipt\.json still carries \[CONTACT\], \[DRAFT\]'):
            self.archive_gate(spec, names, receipt={'not_covered': '[DRAFT] ask [CONTACT]'})
        # private builds: no public gate
        self.archive_gate(assembly_package(), names, docs_errors=None, receipt={'note': '[DRAFT]'})
        out, _manifest = self.archive_gate(self.public_spec(), names, receipt={})  # private name, public documents
        self.assertEqual(out.name, 'bc250-fsr4-xemfg-private-test-31-intel-free-2x')
        with self.assertRaisesRegex(error, 'check_public_docs'):
            self.archive_gate(self.public_spec(), names, ['README.md: placeholders {\'[PRODUCT]\': 27}'])

    def test_archive_gate_refuses_a_draft_receipt(self):
        spec, names = self.public_spec(CHOSEN), names_with(CHOSEN)
        error = self.assemble.ReleaseError
        for fields, shown in ((dict(draft='DRAFT for review'), r'draft fields draft'),
                              (dict(proposed_status='pass'), r'draft fields proposed_status'),
                              (dict(scope='the [PACKAGE-NAME] zip'), r'unfilled tokens \[PACKAGE-NAME\]'),
                              (dict(note='DRAFT'), r'the word DRAFT')):
            with self.assertRaisesRegex(error, r'the receipt receipt\.json is not finished: ' + shown, msg=fields):
                self.archive_gate(spec, names, receipt=fields)
        self.archive_gate(assembly_package(), names, docs_errors=None, receipt=dict(draft='x'))  # private: no gate

    def test_archive_gate_reads_the_fork_build_route(self):
        """With the source companion, the gate refuses while the fork's FORK.md at the locked tag still carries
        placeholders (source_companion.route_placeholders), and checks the generated SOURCE.md and SOURCE.json."""
        import source_companion
        spec, names = self.public_spec(CHOSEN), names_with(CHOSEN)
        error = self.assemble.ReleaseError

        def companion(route=(), record=None):
            def build(config, spec, name, keep, target):
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'zip')
                return dict(record or {}, archive=f'{name}-source.zip', sha256='5' * 64, bytes=3, files=1,
                            optiscaler_commit='c' * 40, optiscaler_tag='bc250-t', optiscaler_tag_commit='d' * 40,
                            instruction=source_companion.INSTRUCTION)
            return types.SimpleNamespace(build=build, source_md=source_companion.source_md,
                                         route_placeholders=lambda config, pattern, marker: list(route),
                                         archive_path=source_companion.archive_path)
        with self.assertRaisesRegex(error, r"Not archiving: the fork's FORK\.md at tag bc250-t .* still carries "
                                           r"\[PRODUCT\]"):
            self.archive_gate(spec, names, companion=companion(["the fork's FORK.md at tag bc250-t (dddddddddddd) "
                                                                "still carries [PRODUCT]"]))
        with self.assertRaisesRegex(error, r'Not archiving: SOURCE\.json still carries \[OPTISCALER-FORK-TAG\]'):
            self.archive_gate(spec, names, companion=companion(record=dict(note='[OPTISCALER-FORK-TAG]')))
        # the gate passes: the receipt (from an assembly without the companion) then differs in its components
        with self.assertRaisesRegex(error, r'The qualified components differs .*SOURCE\.json'):
            self.archive_gate(spec, names, companion=companion())


class ReceiptDrafts(unittest.TestCase):
    def test_receipt_draft_problems(self):
        import assemble
        problems = assemble.receipt_draft_problems
        self.assertEqual(problems(dict(status='pass', note='Skeleton written by release/assemble.py', drafted=1)), [])
        found = problems(dict(status='pass', draft='DRAFT for review', proposed_status='pass',
                              qualified_candidate=dict(public_delta=[]), package='[PACKAGE-NAME]', ci='[VERSION]'))
        self.assertEqual(found, ['draft fields draft, proposed_status, qualified_candidate.public_delta',
                                 'unfilled tokens [PACKAGE-NAME], [VERSION]', 'the word DRAFT'])
        self.assertEqual(problems(dict(note='[DRAFT] comments removed')), ['unfilled tokens [DRAFT]'])
        # a receipt drafted for review, with status, package and version already set but the rest not finished
        drafted = dict(status='pass', proposed_status='pending', draft="DRAFT for review, not a qualification record yet",
                       version='v0.1.0', package='lumen-pace-0.1.0', scope='[PRODUCT] [VERSION] in [PACKAGE-NAME]')
        self.assertEqual(len(problems(drafted)), 3)


class PublicArchiveGate(unittest.TestCase):
    """The public package's --archive gate outside assemble(): packaging/public/check_public_docs.py --release on a copy
    of this tree's public documents (assemble.public_docs_errors), and the host-path scan of the written zips
    (assemble.write_archives)."""

    @classmethod
    def setUpClass(cls):
        import assemble
        cls.assemble = assemble

    def tree(self):
        """A folder with what check_public_docs.py reads: packaging/public/, packaging/dependencies.json,
        release/package.json and release/inputs.lock.json, copied from this tree."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        shutil.copytree(TREE / 'packaging/public', root / 'packaging/public',
                        ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('packaging/dependencies.json', 'release/package.json', 'release/inputs.lock.json'):
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(TREE / name, root / name)
        return root

    def filled(self, root):
        """The copy's documents as publication leaves them: the [DRAFT] comments removed and every placeholder replaced
        by its own word ([PRODUCT] -> PRODUCT, which keeps every heading's anchor)."""
        pattern = self.assemble.placeholder_pattern(root)
        for path in sorted((root / 'packaging/public').glob('*.md')) + [root / 'packaging/public/LICENSE']:
            text = re.sub(r'<!--(?:(?!-->).)*?\[DRAFT\].*?-->\n?', '', path.read_text(encoding='utf-8'), flags=re.S)
            path.write_text(pattern.sub(lambda m: m.group(1), text), encoding='utf-8')
        return root

    def test_filled_documents_pass(self):
        self.assertEqual(self.assemble.public_docs_errors(self.filled(self.tree())), [])

    def test_placeholders_and_drafts_refused(self):
        root = self.filled(self.tree())
        public = root / 'packaging/public'
        (public / 'README.md').write_text((public / 'README.md').read_text() + '\nVersion [VERSION].\n')
        (public / 'NOTICE.md').write_text('<!-- [DRAFT] review -->\n' + (public / 'NOTICE.md').read_text())
        (public / 'LICENSE').write_text((public / 'LICENSE').read_text() + '\n[COPYRIGHT HOLDER]\n')
        errors = self.assemble.public_docs_errors(root)
        self.assertEqual(sorted(errors), sorted(["README.md: placeholders {'[VERSION]': 1}",
                                                 'NOTICE.md: [DRAFT] marker',
                                                 "LICENSE: placeholders {'[COPYRIGHT HOLDER]': 1}"]))

    def test_checker_missing_or_failing(self):
        root = self.filled(self.tree())
        (root / 'packaging/dependencies.json').write_text('{')  # the checker cannot complete
        self.assertRegex(' '.join(self.assemble.public_docs_errors(root)), 'did not complete')
        (root / self.assemble.PUBLIC_DOCS_CHECK).unlink()
        self.assertRegex(' '.join(self.assemble.public_docs_errors(root)), 'is missing')
        self.assertIsNone(self.assemble.placeholder_pattern(root))

    def test_this_tree(self):
        """This tree's own documents: while they carry a placeholder or [DRAFT] marker, the gate names each such
        document; all other errors are those of the normal check (none)."""
        errors = self.assemble.public_docs_errors(TREE)
        texts = {p.name: p.read_text(encoding='utf-8') for p in (TREE / 'packaging/public').glob('*.md')}
        pattern = self.assemble.placeholder_pattern(TREE)
        for name, text in texts.items():
            if pattern.search(text):
                self.assertTrue(any(e.startswith(f'{name}: placeholders') for e in errors), name)
            if '[DRAFT]' in text:
                self.assertIn(f'{name}: [DRAFT] marker', errors)
        normal = [e for e in errors if not re.match(r'[\w.]+: (placeholders \{|\[DRAFT\] marker$)', e)]
        self.assertEqual(normal, [])

    # the written zips

    def package(self, files, source=None):
        """A package directory build/package-x/<name> with files ({path: bytes}) and, if source is given, the source
        companion <name>-source.zip beside it with those members and its .sha256."""
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        out = Path(folder.name) / 'build/package-x/lumen-pace-31-2x'
        for name, data in files.items():
            (out / name).parent.mkdir(parents=True, exist_ok=True)
            (out / name).write_bytes(data)
        if source is not None:
            import zipfile
            path = out.with_name(out.name + '-source.zip')
            with zipfile.ZipFile(path, 'w') as z:
                for name, data in source.items():
                    z.writestr(name, data)
            path.with_name(path.name + '.sha256').write_text('0' * 64 + f'  {path.name}\n')
        return out

    def archives(self, out):
        return sorted(p.name for p in out.parent.iterdir() if p.is_file())

    # a binary member may spell a host path: it is not scanned
    CLEAN = {'README.md': b'# Lumen Pace\n', 'payload/a.dll': b'MZ\0' + (HOME + '/alice/x').encode()}

    def test_clean_archives(self):
        out = self.package(self.CLEAN, {'src/a.c': b'int a;\n', 'notes.txt': b'~/.steam/steam is fine\n'})
        target, digest, scanned = self.assemble.write_archives(out, scan=True)
        self.assertEqual(scanned, ['lumen-pace-31-2x.zip', 'lumen-pace-31-2x-source.zip'])
        self.assertEqual(self.archives(out), ['lumen-pace-31-2x-source.zip', 'lumen-pace-31-2x-source.zip.sha256',
                                              'lumen-pace-31-2x.zip', 'lumen-pace-31-2x.zip.sha256'])
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), digest)
        out = self.package(self.CLEAN)  # no source companion: only the package zip
        self.assertEqual(self.assemble.write_archives(out, scan=True)[2], ['lumen-pace-31-2x.zip'])

    def test_host_paths_refused_and_deleted(self):
        cases = [
            (dict(self.CLEAN, **{'notes.txt': ('see ' + HOME + '/alice/build').encode()}), {'a.txt': b'ok\n'}),
            (self.CLEAN, {'tools/build.json': ('{"cwd": "Z:\\\\' + 'home\\\\alice\\\\src"}').encode()}),
            (self.CLEAN, {'record.json': ('"host": "' + REPO_NAME + ' library"').encode()}),  # review mode: the word
            (self.CLEAN, {'x/' + REPO_NAME + '/a.txt': b'ok\n'}),  # a member name
            (dict(self.CLEAN, **{'w.txt': ('\ufeffC:\\Users\\' + 'alice\\x').encode('utf-16-le')}), None),
        ]
        for files, source in cases:
            out = self.package(files, source)
            with self.assertRaisesRegex(self.assemble.ReleaseError, r'host path\(s\) in the written archives'):
                self.assemble.write_archives(out, scan=True)
            self.assertEqual(self.archives(out), [], (files, source))
            self.assertTrue(out.is_dir())  # the package directory stays for a look
        out = self.package(cases[0][0], cases[0][1])  # a private package: not scanned, archived as before
        self.assertEqual(self.assemble.write_archives(out)[2], [])
        self.assertIn('lumen-pace-31-2x.zip', self.archives(out))



# ------------------------------------------------------------------------- the OptiScaler fork's source offer and notices

import io  # noqa: E402
import lzma  # noqa: E402
import os  # noqa: E402
import tarfile  # noqa: E402

GIT_IDENTITY = dict(GIT_AUTHOR_NAME='Fixture', GIT_AUTHOR_EMAIL='fixture@example.invalid', GIT_COMMITTER_NAME='Fixture',
                    GIT_COMMITTER_EMAIL='fixture@example.invalid', GIT_AUTHOR_DATE='2026-09-29T13:10:19+00:00',
                    GIT_COMMITTER_DATE='2026-09-29T13:10:19+00:00', GIT_CONFIG_GLOBAL=os.devnull,
                    GIT_CONFIG_NOSYSTEM='1')


def fixture_git(folder, *arguments, stdin=None):
    out = subprocess.run(['git', '-C', str(folder), '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=' + os.devnull,
                          *arguments], input=stdin, capture_output=True, env=dict(os.environ, **GIT_IDENTITY))
    if out.returncode:
        raise AssertionError(f'git {arguments} failed: {out.stderr.decode()}')
    return out.stdout.decode().strip()


def fixture_repository(folder, files, links=None, gitmodules=None, serve=False):
    """A git repository with files {path: (bytes, executable)} and submodule links {path: commit}; returns HEAD."""
    folder.mkdir(parents=True)
    fixture_git(folder, 'init', '-q', '-b', 'main')
    if serve:  # what a public host allows: fetching a pinned commit, also without its files
        fixture_git(folder, 'config', 'uploadpack.allowFilter', 'true')
    for path, (data, executable) in files.items():
        target = folder / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        target.chmod(0o755 if executable else 0o644)
        fixture_git(folder, 'add', '--', path)
    if gitmodules:
        (folder / '.gitmodules').write_text(gitmodules)
        fixture_git(folder, 'add', '.gitmodules')
    for path, commit in (links or {}).items():
        fixture_git(folder, 'update-index', '--add', '--cacheinfo', f'160000,{commit},{path}')
    fixture_git(folder, 'commit', '-q', '-m', 'fixture')
    return fixture_git(folder, 'rev-parse', 'HEAD')


class ForkSource(unittest.TestCase):
    """release/fork_source_archive.py and the source companion's fork reader (release/source_companion.py) on a fork
    fixture with two submodules served from local repositories: no network."""

    LONG = 'deep/' + 'n' * 60 + '/' + 'e' * 60 + '.h'

    @classmethod
    def setUpClass(cls):
        import config
        import fork_source_archive
        import source_companion
        cls.config_module, cls.tool, cls.companion = config, fork_source_archive, source_companion
        cls.temp = tempfile.TemporaryDirectory()
        root = Path(cls.temp.name)
        cls.sub_a = fixture_repository(root / 'serve/sub-a', {
            'include/a.h': (b'int a;\n', False), 'tools/run.sh': (b'#!/bin/sh\n', True), 'win/x.bat': (b'echo\n', False),
            '.gitattributes': (b'* text=auto\n*.bat text eol=crlf\n', False), cls.LONG: (b'long\n', False),
            'café.txt': ('café\n'.encode(), False)}, serve=True)
        cls.sub_b = fixture_repository(root / 'serve/sub-b', {'inc/b.h': (b'int b;\n', False)}, serve=True)
        cls.urls = {'ext/a': (root / 'serve/sub-a').as_uri(), 'ext/b': (root / 'serve/sub-b').as_uri()}
        modules = ''.join(f'[submodule "{path}"]\n\tpath = {path}\n\turl = {url}\n' for path, url in cls.urls.items())
        cls.fork = root / 'fork'
        cls.build_commit = fixture_repository(cls.fork, {'README.md': (b'fork\n', False), 'src/x.c': (b'int x;\n', False),
                                                         '.gitattributes': (b'* text=auto\n', False)},
                                              links={'ext/a': cls.sub_a, 'ext/b': cls.sub_b}, gitmodules=modules)
        cls.tree = fixture_git(cls.fork, 'rev-parse', 'HEAD^{tree}')
        (cls.fork / 'FORK.md').write_text('# Fork\n')
        (cls.fork / 'tools').mkdir()
        (cls.fork / 'tools/bc250-build.py').write_text('#!/usr/bin/env python3\n')
        (cls.fork / 'tools/bc250-build.py').chmod(0o755)
        fixture_git(cls.fork, 'add', 'FORK.md', 'tools/bc250-build.py')
        fixture_git(cls.fork, 'commit', '-q', '-m', 'docs')
        cls.tag_commit = fixture_git(cls.fork, 'rev-parse', 'HEAD')
        fixture_git(cls.fork, 'tag', '-a', '-m', 'build source', 'bc250-test', cls.tag_commit)
        (cls.fork / 'src/x.c').write_text('int y;\n')
        fixture_git(cls.fork, 'commit', '-q', '-am', 'a change the tag must not carry')
        cls.bad_tag_commit = fixture_git(cls.fork, 'rev-parse', 'HEAD')
        fixture_git(cls.fork, 'tag', '-a', '-m', 'wrong', 'bc250-bad', cls.bad_tag_commit)
        # FORK.md as it is before publication: placeholders still in it (another tag on the build commit's line)
        fixture_git(cls.fork, 'checkout', '-q', cls.build_commit)
        (cls.fork / 'FORK.md').write_text('# [PRODUCT] fork\n\nSource: [OPTISCALER-FORK-SOURCE-URL] <!-- [DRAFT] -->\n')
        (cls.fork / 'tools').mkdir(exist_ok=True)
        (cls.fork / 'tools/bc250-build.py').write_text('#!/usr/bin/env python3\n')
        (cls.fork / 'tools/bc250-build.py').chmod(0o755)
        fixture_git(cls.fork, 'add', 'FORK.md', 'tools/bc250-build.py')
        fixture_git(cls.fork, 'commit', '-q', '-m', 'docs to fill in')
        cls.unfilled_commit = fixture_git(cls.fork, 'rev-parse', 'HEAD')
        fixture_git(cls.fork, 'tag', '-a', '-m', 'unfilled', 'bc250-unfilled', cls.unfilled_commit)
        fixture_git(cls.fork, 'checkout', '-q', 'main')
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def config(self, cache='cache', offline=False, **source):
        config = self.config_module.Config({'build': str(self.root / 'build'), 'cache': str(self.root / cache),
                                            'optiscaler_source': str(self.fork)}, offline=offline)
        config.lock = {'fetch': {}, 'work': {'optiscaler-fork': {'files': {'OptiScaler.dll': {'sha256': '1' * 64}},
            'source': dict(dict(commit=self.build_commit, tree=self.tree, tag='bc250-test', tag_commit=self.tag_commit,
                                build_route=['FORK.md', 'tools/bc250-build.py'], branch='b', upstream='u',
                                upstream_base=self.build_commit, reverted_upstream='r', build='b'), **source)}}}
        return config

    def archive(self, out, pointer_only=None, **config):
        pointer = {'ext/b': 'not bundled'} if pointer_only is None else pointer_only
        result = self.tool.build(self.config(**config), pointer, out=self.root / out)
        return result, self.root / out / result['archive']

    def test_reproducible_and_complete(self):
        first, path = self.archive('out-1')
        second, again = self.archive('out-2')
        self.assertEqual(path.read_bytes(), again.read_bytes())
        self.assertTrue(all(f['fetched_now'] is False for f in second['fetched']))  # served from the cache
        self.assertEqual(first['lock'], second['lock'])
        lock = first['lock']
        self.assertEqual((lock['name'], lock['bundled'], lock['pointer_only']),
                         ('OptiScaler-bc250-test-source.tar.xz', ['ext/a'], ['ext/b']))
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), lock['sha256'])
        self.assertEqual(hashlib.sha256(lzma.decompress(path.read_bytes())).hexdigest(), lock['tar_sha256'])
        self.assertEqual((path.parent / (path.name + '.sha256')).read_text(), f'{lock["sha256"]}  {path.name}\n')
        self.assertEqual(self.tool.verify(path)['sha256'], lock['sha256'])
        mtime = int(fixture_git(self.fork, 'log', '-1', '--format=%ct', self.build_commit))
        with tarfile.open(path, 'r:xz') as tar:
            members = tar.getmembers()
            data = {m.name.split('/', 1)[1]: tar.extractfile(m).read() for m in members if m.isfile()}
        names = [m.name for m in members]
        root = 'OptiScaler-bc250-test-source'
        self.assertEqual(names[0], root)
        body = [n.split('/', 1)[1] for n in names[1:]]
        self.assertEqual(body[-3:], list(self.tool.RECORD_FILES))
        self.assertEqual(body[:-3], sorted(body[:-3]))
        for m in members:
            self.assertEqual((m.mtime, m.uid, m.gid, m.uname, m.gname), (mtime, 0, 0, '', ''))
        modes = {m.name.split('/', 1)[-1]: m.mode for m in members}
        self.assertEqual((modes['ext/a/tools/run.sh'], modes['src/x.c'], modes['tools/bc250-build.py'], modes['ext/b']),
                         (0o755, 0o644, 0o755, 0o755))
        self.assertTrue(next(m for m in members if m.name == f'{root}/ext/b').isdir())
        self.assertFalse(any(n.startswith(f'{root}/ext/b/') for n in names))  # pointer-only: an empty folder
        self.assertEqual((data['FORK.md'], data['src/x.c']), (b'# Fork\n', b'int x;\n'))  # tag files, build-commit tree
        self.assertEqual(data['ext/a/win/x.bat'], b'echo\n')  # as git stores it, not converted
        self.assertIn(self.LONG, [n.removeprefix('ext/a/') for n in data])
        self.assertIn('ext/a/café.txt', data)
        record = json.loads(data['SOURCE-ARCHIVE.json'])
        parts = {p['path']: p for p in record['parts']}
        self.assertEqual(parts['ext/a']['eol_crlf_on_checkout'], ['ext/a/win/x.bat'])
        self.assertEqual((parts['ext/a']['commit'], parts['ext/a']['url'], parts['ext/a']['bundled']),
                         (self.sub_a, self.urls['ext/a'], True))
        self.assertEqual((parts['ext/b']['bundled'], parts['ext/b']['commit'], parts['ext/b']['tree']),
                         (False, self.sub_b, fixture_git(self.root / 'serve/sub-b', 'rev-parse', 'HEAD^{tree}')))
        self.assertEqual((parts['.']['tag_commit'], parts['.']['tree']), (self.tag_commit, self.tree))
        sums = data['SOURCE-ARCHIVE.sha256'].decode().splitlines()
        self.assertEqual(len(sums), record['files'])
        self.assertTrue(all(hashlib.sha256(data[line[66:]]).hexdigest() == line[:64] for line in sums))
        self.assertIn(self.urls['ext/b'], data['SOURCE-ARCHIVE.md'].decode())

    def test_bundle_all_and_refusals(self):
        result, path = self.archive('out-all', pointer_only={})
        self.assertEqual(result['lock']['bundled'], ['ext/a', 'ext/b'])
        with tarfile.open(path, 'r:xz') as tar:
            self.assertIn('OptiScaler-bc250-test-source/ext/b/inc/b.h', tar.getnames())
        with self.assertRaisesRegex(self.tool.ReleaseError, 'must only add'):
            self.archive('out-bad', tag='bc250-bad', tag_commit=self.bad_tag_commit)
        with self.assertRaisesRegex(self.tool.ReleaseError, 'tree'):
            self.archive('out-bad', tree='0' * 40)
        with self.assertRaisesRegex(self.tool.ReleaseError, 'offline'):
            self.archive('out-bad', cache='empty-cache', offline=True)
        with self.assertRaisesRegex(self.tool.ReleaseError, 'does not pin'):
            self.archive('out-bad', pointer_only={'ext/c': 'x'})
        with self.assertRaisesRegex(self.tool.ReleaseError, 'lacks "tag_commit"'):
            self.archive('out-bad', tag_commit=None)
        damaged = bytearray(path.read_bytes())
        damaged[len(damaged) // 2] ^= 1
        path.write_bytes(bytes(damaged))
        with self.assertRaises(self.tool.ReleaseError):
            self.tool.verify(path)

    def test_companion_reads_the_build_route(self):
        files, pins = self.companion.fork_files(self.config())
        self.assertEqual(files['FORK.md'], (b'# Fork\n', False))
        self.assertEqual(files['tools/bc250-build.py'], (b'#!/usr/bin/env python3\n', True))
        self.assertEqual(files['src/x.c'], (b'int x;\n', False))
        self.assertNotIn('ext/a', files)
        self.assertEqual((pins['tag'], pins['tag_commit'], [r['path'] for r in pins['build_route']]),
                         ('bc250-test', self.tag_commit, ['FORK.md', 'tools/bc250-build.py']))
        self.assertEqual([(s['path'], s['commit']) for s in pins['submodules']],
                         [('ext/a', self.sub_a), ('ext/b', self.sub_b)])
        archive = dict(name='OptiScaler-bc250-test-source.tar.xz', sha256='2' * 64, tag='bc250-test',
                       tag_commit=self.tag_commit, commit=self.build_commit)
        _files, pins = self.companion.fork_files(self.config(archive=archive))
        self.assertEqual(pins['recursive_source_archive'], archive)
        with self.assertRaisesRegex(self.companion.ReleaseError, 'must only add'):
            self.companion.fork_files(self.config(tag='bc250-bad', tag_commit=self.bad_tag_commit))

    def test_the_tag_must_point_at_the_locked_commit(self):
        """A tag moved to another commit (a FORK.md commit before publication) or missing stops the companion and the
        archive until the lock follows it."""
        moved = dict(tag='bc250-unfilled')  # that tag points at another commit than the locked tag_commit
        for call in (lambda c: self.companion.fork_files(c), lambda c: self.tool.build(c, {}, out=self.root / 'x')):
            with self.assertRaisesRegex(self.companion.ReleaseError, r'points at .* but inputs\.lock\.json names '
                                                                      r'tag_commit .*fork_source_archive\.py'):
                call(self.config(**moved))
            with self.assertRaisesRegex(self.companion.ReleaseError, 'has no tag bc250-none'):
                call(self.config(tag='bc250-none'))
        self.assertFalse((self.root / 'x').exists())

    def test_the_lock_records_must_agree(self):
        """source.archive and the release fetch group name the tag commit; a stale one is refused (the archive tool
        itself ignores source.archive, which it makes)."""
        good = dict(name='OptiScaler-bc250-test-source.tar.xz', sha256='2' * 64, tag='bc250-test',
                    tag_commit=self.tag_commit, commit=self.build_commit)
        self.companion.fork_files(self.config(archive=good))
        stale = dict(good, tag_commit=self.bad_tag_commit)
        with self.assertRaisesRegex(self.companion.ReleaseError, r'source\.archive\.tag_commit'):
            self.companion.fork_files(self.config(archive=stale))
        result, _path = self.archive('out-stale-record', archive=stale)  # the record it is about to replace
        self.assertEqual(result['lock']['tag_commit'], self.tag_commit)
        config = self.config()
        config.lock['work']['optiscaler-fork']['release_fetch'] = dict(enabled=False, commit=self.bad_tag_commit,
                                                                       files={})
        for call in (lambda: self.companion.fork_files(config), lambda: self.tool.build(config, {}, fetch_only=True)):
            with self.assertRaisesRegex(self.companion.ReleaseError, r'release_fetch\.commit'):
                call()

    def test_placeholders_in_the_build_route(self):
        """FORK.md with placeholders: the archive tool warns and the companion's gate check names them (assemble.py
        --archive refuses on them)."""
        unfilled = dict(tag='bc250-unfilled', tag_commit=self.unfilled_commit)
        import assemble
        pattern = assemble.placeholder_pattern(TREE)
        problems = self.companion.route_placeholders(self.config(**unfilled), pattern)
        self.assertEqual(len(problems), 1)
        self.assertRegex(problems[0], r"FORK\.md at tag bc250-unfilled .* still carries \[OPTISCALER-FORK-SOURCE-URL\], "
                                      r"\[PRODUCT\], \[DRAFT\]")
        self.assertEqual(self.companion.route_placeholders(self.config(), pattern), [])
        result, _path = self.archive('out-unfilled', **unfilled)
        self.assertEqual(len(result['warnings']), 1)
        self.assertRegex(result['warnings'][0], r'FORK\.md still carries \[DRAFT\], \[OPTISCALER-FORK-SOURCE-URL\], '
                                                r'\[PRODUCT\]')
        self.assertEqual(self.archive('out-filled')[0]['warnings'], [])

    def test_the_fork_group_after_its_release(self):
        """release_fetch's own instruction, followed literally: the group moves to "fetch" with the placeholders filled,
        "enabled" (and the note) removed and the source record moved with it, and the work group is dropped. The
        companion and the archive tool read the group there."""
        about = json.loads((TREE / 'release/inputs.lock.json').read_text())['work']['optiscaler-fork']['release_fetch']
        self.assertRegex(about['about'], r'"source" record \(commit, tree, tag, tag_commit, build_route, archive, '
                                         r'\.\.\.\) moves with it')
        config = self.config()
        work = config.lock['work'].pop('optiscaler-fork')
        template = dict(about, commit=self.tag_commit, files=work['files'])
        fetch = {key: value.replace('[OPTISCALER-FORK-SOURCE-URL]', 'https://example.invalid/fork')
                 .replace('[OPTISCALER-FORK-TAG]', 'bc250-test') if isinstance(value, str) else value
                 for key, value in template.items() if key not in ('enabled', 'about')}
        fetch['source'] = work['source']
        config.lock['fetch']['optiscaler-fork'] = fetch
        files, pins = self.companion.fork_files(config)
        self.assertEqual((files['FORK.md'][0], pins['tag_commit']), (b'# Fork\n', self.tag_commit))
        self.assertEqual(self.tool.build(config, {}, fetch_only=True)['pointer_only'], [])
        self.assertEqual(self.config_module.fork_group(config.lock)[0], 'fetch')
        fetch['commit'] = self.bad_tag_commit
        with self.assertRaisesRegex(self.companion.ReleaseError, r'fetch\.optiscaler-fork: .*commit is'):
            self.companion.fork_files(config)
        del fetch['source']
        with self.assertRaisesRegex(self.companion.ReleaseError, 'has no "source" record'):
            self.companion.fork_files(config)

    def test_source_md_is_public_wording(self):
        record = dict(archive='p-source.zip', sha256='3' * 64, optiscaler_commit='c' * 40, optiscaler_tag='bc250-test',
                      optiscaler_tag_commit='d' * 40)
        recursive = dict(name='OptiScaler-bc250-test-source.tar.xz', sha256='4' * 64)
        xess = dict(path='external/xess', url='https://github.com/intel/xess.git', commit='e' * 40)
        for extra in ({}, {'optiscaler_recursive_source': recursive},
                      {'optiscaler_recursive_source': dict(recursive, not_bundled=[xess])}):
            text = self.companion.source_md(dict(record, **extra))
            self.assertNotRegex(text + self.companion.INSTRUCTION, r'(?i)tester|private')
            self.assertIn('FORK.md', text)
            self.assertIn('3' * 64, text)
            self.assertEqual('4' * 64 in text, bool(extra))
            self.assertEqual('apart from `external/xess` (https://github.com/intel/xess.git at commit `' + 'e' * 40
                             + '`), which comes from its own repository.' in text,
                             bool(extra.get('optiscaler_recursive_source', {}).get('not_bundled')))

    def test_companion_names_what_the_archive_leaves_out(self):
        """SOURCE.json and SOURCE.md name each submodule the recursive archive does not bundle, with its repository
        and commit (NOTICE.md says the same)."""
        archive = dict(name='OptiScaler-bc250-test-source.tar.xz', sha256='2' * 64, tag='bc250-test',
                       tag_commit=self.tag_commit, commit=self.build_commit, pointer_only=['ext/b'])
        config = self.config(archive=archive)
        spec = dict(source_companion=dict(optiscaler_dir='OptiScaler', optiscaler_pins='optiscaler-source-pins.json'))
        record = self.companion.build(config, spec, 'p', [], self.root / 'companion' / 'p-source.zip')
        self.assertEqual(record['optiscaler_recursive_source']['not_bundled'],
                         [dict(path='ext/b', url=self.urls['ext/b'], commit=self.sub_b)])
        self.assertIn(f'apart from `ext/b` ({self.urls["ext/b"]} at commit `{self.sub_b}`)',
                      self.companion.source_md(record))


LICENSES = TREE / 'packaging/licenses/OptiScaler-third-party'


def package_spec():
    return json.loads((TREE / 'release/package.json').read_text())


class OptiScalerNotices(unittest.TestCase):
    """The licence texts of the third-party code in OptiScaler.dll: byte for byte as PROVENANCE.json records them, all
    shipped beside the DLL, indexed in their README and the FreeType credit in NOTICE.md."""

    def test_texts_match_their_provenance(self):
        provenance = json.loads((LICENSES / 'PROVENANCE.json').read_text())
        on_disk = {p.name for p in LICENSES.iterdir()} - {'README.md', 'PROVENANCE.json'}
        self.assertEqual(on_disk, set(provenance['files']))
        for name, entry in provenance['files'].items():
            self.assertEqual(hashlib.sha256((LICENSES / name).read_bytes()).hexdigest(), entry['sha256'], name)
            for source in entry['sources']:
                self.assertRegex(source['commit'], r'^[0-9a-f]{40}$')
                self.assertEqual(source['url'], 'https://raw.githubusercontent.com/'
                                 + source['repository'].removeprefix('https://github.com/') + '/' + source['commit']
                                 + '/' + source['path'])
        used = {f for component in provenance['components'] for f in component['files']}
        self.assertEqual(used, set(provenance['files']))

    def test_shipped_beside_the_dll_and_indexed(self):
        component = package_spec()['components']['optiscaler-fork']['files']
        self.assertIn('opti/OptiScaler.dll', component)
        shipped = {target.removeprefix('licenses/OptiScaler-third-party/'): source for target, source in component.items()
                   if target.startswith('licenses/OptiScaler-third-party/')}
        names = {p.name for p in LICENSES.iterdir()} - {'PROVENANCE.json'}
        self.assertEqual(set(shipped), names)
        for name, source in shipped.items():
            self.assertEqual(source, f'repo:packaging/licenses/OptiScaler-third-party/{name}')
        readme = (LICENSES / 'README.md').read_text()
        for name in names - {'README.md'}:
            self.assertIn(f'`{name}`', readme)
        credit = 'Portions of this software are copyright © 2024 The FreeType Project (www.freetype.org). All\nrights reserved.'
        self.assertIn(credit.replace('\n', ' '), ' '.join(readme.split()))
        notice = ' '.join((TREE / 'packaging/public/NOTICE.md').read_text().split())
        self.assertIn(' '.join(credit.split()), notice)
        self.assertIn('licenses/OptiScaler-third-party/', notice)


class OptiScalerForkLock(unittest.TestCase):
    """inputs.lock.json's OptiScaler fork group: the build route and tag the source offer needs, the prepared (and
    switched off) fetch group of the fork's release, and a public projection without internal notes."""

    @classmethod
    def setUpClass(cls):
        cls.lock = json.loads((TREE / 'release/inputs.lock.json').read_text())
        cls.group = cls.lock['work']['optiscaler-fork']

    def test_build_route_and_tag(self):
        source = self.group['source']
        self.assertEqual(source['build_route'], ['FORK.md', 'tools/bc250-build.py'])
        self.assertRegex(source['tag_commit'], r'^[0-9a-f]{40}$')
        if source.get('archive'):
            archive = source['archive']
            self.assertEqual((archive['tag_commit'], archive['commit'], archive['tag']),
                             (source['tag_commit'], source['commit'], source['tag']))
            self.assertEqual(archive['name'], f'OptiScaler-{source["tag"]}-source.tar.xz')

    def test_release_fetch_template_is_off(self):
        template = self.group['release_fetch']
        self.assertIs(template['enabled'], False)
        self.assertNotIn('optiscaler-fork', self.lock['fetch'])
        self.assertEqual(template['files'], self.group['files'])
        self.assertEqual(template['commit'], self.group['source']['tag_commit'])
        self.assertIn('{path}', template['url'])
        self.assertTrue({'[OPTISCALER-FORK-SOURCE-URL]', '[OPTISCALER-FORK-TAG]'} <= set(re.findall(r'\[[A-Z-]+\]',
                                                                                                    template['url'])))
        filled = template['url'].replace('[OPTISCALER-FORK-SOURCE-URL]', 'https://example.invalid/fork') \
            .replace('[OPTISCALER-FORK-TAG]', 'bc250-test')
        self.assertEqual(filled.format(commit=template['commit'], path='OptiScaler.dll'),
                         'https://example.invalid/fork/releases/download/bc250-test/OptiScaler.dll')

    def test_public_projection_has_no_internal_notes(self):
        import export_tree
        public, report = export_tree.public_lock(self.lock)
        group = public['work']['optiscaler-fork']
        # source.branch is the fork's branch until its public name is chosen
        text = json.dumps(group).replace(json.dumps(group['source']['branch']), '')
        for word in ('Private', 'private', 'tester', 'noreply', 'rewrite', 'research_record', 'evidence/', 'previous_build',
                     'source_in_work_note', 'fg-controls', 'slmutex'):
            self.assertNotIn(word, text)
        self.assertEqual((group['path'], group['source']['source_in_work']), ('OptiScaler-build', 'OptiScaler'))
        self.assertNotIn('private', json.dumps(public['fetch']['optiscaler-license']))
        self.assertEqual(group['files'], self.group['files'])
        self.assertEqual(group['release_fetch'], self.group['release_fetch'])
        for key in ('commit', 'tree', 'tag', 'tag_commit', 'build_route', 'upstream_base'):
            self.assertEqual(group['source'][key], self.group['source'][key])
        self.assertEqual(export_tree.public_lock(public)[0], public)


if __name__ == '__main__':
    unittest.main()
