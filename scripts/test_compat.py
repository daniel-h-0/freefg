# SPDX-License-Identifier: MIT
"""The compatibility verdict (packaging/compat.py): tiers, the layer precedence of research/recipes/RULES.md, wiki
conditions evaluated as true / false / unknown, FG-input vetoes, refusals and their texts, the run summary from logs,
the redacted report, every verified recipe unchanged in effect, and the verdicts on a synthetic library."""
import copy, json, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'packaging'))
import compat as c
import recipes as r

FIXTURES = Path(__file__).resolve().parent/'fixtures/compat'


def scan(**over):
    """A 64-bit Unreal DX12 game with DLSS, fully read; keyword arguments replace fields."""
    s = dict(store='steam', id='4242', name='Hero', root='/library/Hero', complete=True,
             exe=dict(selected='Hero/Binaries/Win64/Hero-Win64-Shipping.exe', best='Hero/Binaries/Win64/Hero-Win64-Shipping.exe',
                      confidence='high', bits=64, imports=True, stub=None, native_linux=[]),
             api=dict(apis=['d3d11', 'd3d12?', 'dxgi'], dx12=True, default='d3d11', switch='-dx12', switch_kind='likely needed',
                      confidence='low', current_switch=[]),
             engine=dict(name='unreal', version='UE4', major='UE4'), upscalers=['dlss'],
             game_fg=dict(fsrfg_sdk2=False, dlssg=False, fsrfg_combined=False, fsrfg30=False), native_xefg=False, xefg_beside=False,
             native_xefg_elsewhere=None, dlss_copy=True, dlss_unconfirmed=None, fg_toggle_hints=[], anticheat=[], protonfix=None, mods=[])
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            s[k] = dict(s[k], **v)
        else:
            s[k] = v
    return s


def ids(exe='hero-win64-shipping.exe', steam=('4242',), titles=('hero',), folders=()):
    return dict(exe=exe, steam=set(steam), gog=set(), epic=set(), titles=set(titles), folders=set(folders))


VERIFIED = dict(title='Hero', match=dict(steam=['4242'], exe=['hero-win64-shipping.exe']), route='opti', fg_input='dlssg',
                ini={'FrameGen.FTInput': '2'}, game_settings=[], launch_args=['-dx12'], note='Test note.', evidence='gameplay',
                observed='2.0 in gameplay')
COMMUNITY = dict(title='Hero', match=dict(steam=['4242']), status='community-bc250', route='opti', fg_input='upscaler',
                 ini={'Hotfix.ColorResourceBarrier': '4', 'Hotfix.MotionVectorResourceBarrier': '8'}, game_settings=[],
                 launch_args=['-d3d12'], manual_steps=['Choose DLSS in Video.'], reports=2)
WIKI = dict(title='Hero', match=dict(title=['hero'], exe=['hero-win64-shipping.exe']), pages=['https://wiki/Hero'],
            launch_args=['-dx12'], promoted=[dict(key='Hotfix.ColorResourceBarrier', value='5'), dict(key='OptiFG.ResourceBlocking', value='true',
                                                                                                 when=dict(fg_input='upscaler'))],
            ini=[dict(key='OptiFG.HUDFix', value='true'), dict(key='Spoofing.Dxgi', value='false'), dict(key='fakenvapi.EnableLogs', value='true'),
                 dict(key='FSR.FsrNonLinearPQ', value='true'), dict(key='Hotfix.ColorResourceBarrier', value='5'),
                 dict(key='OptiFG.ResourceBlocking', value='true', when=dict(fg_input='upscaler')),
                 dict(key='Hotfix.DisableOverlays', value='true', when=dict(condition='crashing on startup')),
                 dict(key='Spoofing.Vulkan', value='true', when=dict(api='vulkan')),
                 dict(key='V-Sync.ForceVsync', value='false'), dict(key='Inputs.EnableFsr2Inputs', value='false', when=dict(gpu='nvidia'))],
            fg_advice=[dict(advice='prefer', input='dlssg'), dict(advice='broken', input='fsrfg'), dict(advice='works', input='upscaler'),
                       dict(advice='avoid', input='fsrfg30', when=dict(upscaler_input='fsr3'))])


def data(verified=(), community=(), wiki=(), quirk_keys=None):
    return dict(verified=list(verified), community=list(community), wiki=list(wiki), quirk_keys=quirk_keys or {}, leave_auto={}, backports={})


class ConditionTests(unittest.TestCase):
    def test_true_false_unknown(self):
        ctx = dict(c.DEFAULT_CONTEXT, fg_input='upscaler', store='steam', engine='unreal')
        cases = [({'gpu': 'AMD'}, True), ({'gpu': 'non-NVIDIA'}, True), ({'gpu': 'RTX 4090'}, False), ({'gpu': 'RX 9070 XT'}, False),
                 ({'gpu': 'Arc'}, False), ({'os': 'Linux (Proton)'}, True), ({'os': 'W11 24H2'}, False), ({'fg_output': 'xefg'}, True),
                 ({'fg_output': 'fsrfg'}, False), ({'fg_input': 'upscaler'}, True), ({'fg_input': 'dlssg'}, False),
                 ({'fg_input': 'not dlssg'}, True), ({'fg_input': 'nukems'}, False), ({'upscaler': 'fsr4'}, True), ({'upscaler': 'dlss'}, False),
                 ({'api': 'dx12'}, True), ({'api': 'vulkan'}, False), ({'optiscaler': '0.7.9'}, False), ({'optiscaler': '0.9.4'}, True),
                 ({'platform': 'Xbox / Game Pass'}, False), ({'store': 'Steam'}, True), ({'engine': 'UE4'}, True), ({'engine': 'Unity'}, False),
                 ({'reason': 'SL1 game'}, True), ({'condition': 'XeFG output'}, True),
                 ({'upscaler_input': 'dlss'}, None), ({'condition': 'crashing on startup'}, None), ({'game_version': '<1.8'}, None),
                 ({'gpu': 'amd', 'condition': 'stuck on boot'}, None), ({'gpu': 'nvidia', 'condition': 'stuck on boot'}, False)]
        for when, expected in cases:
            self.assertIs(c.evaluate(when, ctx)[0], expected, when)
        self.assertEqual(c.evaluate({'condition': 'crashing on startup'}, ctx)[1], ['condition: crashing on startup'])
        self.assertEqual(c.evaluate({'gpu': 'RTX 3070'}, ctx)[1], ['NVIDIA GPUs only'])
        helix = dict(ctx, upscaler='helixsr')  # claude/helixsr's output choice
        self.assertIs(c.evaluate({'upscaler': 'fsr4'}, helix)[0], False)

    def test_key_rules(self):
        expect = {'OptiFG.HUDFix': 'blocked', 'OptiFG.HUDLimit': 'blocked', 'Spoofing.Dxgi': 'blocked', 'fakenvapi.EnableLogs': 'blocked',
                  'FSR.FsrNonLinearPQ': 'blocked', 'FrameGen.FGInput': 'installer', 'Upscalers.Dx12Upscaler': 'installer',
                  'Spoofing.SpoofedVendorId': 'policy', 'V-Sync.ForceVsync': 'policy', 'FSRFG.Something': 'never',
                  'Hotfix.ColorResourceBarrier': None, 'OptiFG.ResourceBlocking': None}
        for key, cls in expect.items():
            self.assertEqual(c.key_rule(key, 'x')[0], cls, key)
        self.assertEqual(c.key_rule('FrameGen.FGOutput', 'xefg')[0], 'redundant')
        self.assertEqual(c.key_rule('XeFG.ForceBorderless', 'true')[0], 'redundant')


class PrecedenceTests(unittest.TestCase):
    def test_user_beats_the_verified_recipe(self):
        v = c.decide(scan(), data([VERIFIED]), ids(), choice=dict(route='opti', fg_input='upscaler'))
        self.assertEqual((v['tier'], v['route'], v['fg_input'], v['choice']), ('A', 'opti', 'upscaler', 'user'))

    def test_verified_beats_community_wiki_and_detection(self):
        v = c.decide(scan(), data([VERIFIED], [COMMUNITY], [WIKI]), ids())
        self.assertEqual((v['tier'], v['route'], v['fg_input']), ('A', 'opti', 'dlssg'))
        self.assertEqual(v['ini'], {})  # neither the community nor the promoted wiki keys under a verified recipe
        self.assertEqual((v['launch_args'], v['launch_source']), (['-dx12'], 'verified recipe'))
        self.assertEqual(v['dlss_helper'], 'auto')
        self.assertIn('Known on BC-250: Test note.', v['warnings'])
        self.assertIn('Verified on BC-250: Hero (2.0 in gameplay)', v['line'])

    def test_community_beats_promoted_wiki_and_detection(self):
        v = c.decide(scan(), data([], [COMMUNITY], [WIKI]), ids())
        self.assertEqual((v['tier'], v['fg_input']), ('B', 'upscaler'))
        self.assertEqual(v['ini'][('Hotfix', 'ColorResourceBarrier')], '4')  # the community value, not the wiki's 5
        self.assertEqual(v['ini_sources']['Hotfix.ColorResourceBarrier'], 'community recipe')
        self.assertEqual(v['ini'][('OptiFG', 'ResourceBlocking')], 'true')  # promoted, condition true for OptiFG
        self.assertEqual((v['launch_args'], v['launch_source']), (['-d3d12'], 'community recipe'))
        self.assertIn('Choose DLSS in Video.', v['manual_steps'])
        self.assertIn('Reported working on BC-250 by 2 reports', v['line'])

    def test_quirk_keys_are_never_written_below_a_verified_recipe(self):
        quirks = {'hero-win64-shipping.exe': {'Hotfix.ColorResourceBarrier': '4', 'OptiFG.ResourceBlocking': 'false'}}
        v = c.decide(scan(), data([], [COMMUNITY], [WIKI], quirks), ids())
        self.assertNotIn(('Hotfix', 'ColorResourceBarrier'), v['ini'])
        self.assertNotIn(('OptiFG', 'ResourceBlocking'), v['ini'])
        self.assertEqual(v['ini'], {('Hotfix', 'MotionVectorResourceBarrier'): '8'})

    def test_promoted_only_for_a_strong_match_and_true_conditions(self):
        v = c.decide(scan(), data([], [], [WIKI]), ids())
        self.assertEqual(v['tier'], 'C')
        self.assertEqual(v['ini'], {('Hotfix', 'ColorResourceBarrier'): '5', ('OptiFG', 'ResourceBlocking'): 'true'})
        v = c.decide(scan(), data([], [], [WIKI]), ids(), choice=dict(route='opti', fg_input='dlssg'))
        self.assertEqual(v['ini'], {('Hotfix', 'ColorResourceBarrier'): '5'})  # ResourceBlocking only with OptiFG input
        weak = c.decide(scan(), data([], [], [WIKI]), ids(exe='other.exe'))  # title only: weak
        self.assertEqual(weak['ini'], {})
        self.assertEqual(weak['tier'], 'D')
        # A weak match still gives its DX12 argument where detection confirms the D3D12 path (0.9.0's L1, narrowed).
        self.assertEqual((weak['launch_args'], weak['launch_source']), (['-dx12'], 'OptiScaler wiki (Hero)'))
        no_dx12 = c.decide(scan(api=dict(dx12=False, default='d3d11', switch=None)), data([], [], [WIKI]), ids(exe='other.exe'))
        self.assertNotEqual(no_dx12['launch_source'], 'OptiScaler wiki (Hero)')

    def test_wiki_lines_under_a_verified_recipe(self):
        # What the recipe sets itself is applied by the recipe, not "a candidate"; a wiki veto does not choose the
        # input under a verified recipe (or the user's choice); inputs this build never uses are hidden.
        wiki = dict(WIKI, match=dict(title=['hero'], steam=['4242']), promoted=[], ini=[dict(key='FrameGen.FTInput', value='2')],
                    game_settings=[dict(file='renderer.ini', key='m_eDLSSFGMode', value='1'), dict(file='renderer.ini', key='m_bGrain', value='0')],
                    fg_advice=[dict(advice='broken', input='upscaler'), dict(advice='works', input='nukems')])
        verified = dict(VERIFIED, game_settings=[dict(file='AppData/Local/Hero/renderer.ini', format='json', values={'m_eDLSSFGMode': 1})])
        d = data([verified], [], [wiki])
        v = c.decide(scan(), d, ids())
        self.assertEqual((v['tier'], v['choice']), ('A', 'verified'))
        advice = c.wiki_advice(d, ids(), v)
        self.assertIn('Game setting m_eDLSSFGMode=1 in renderer.ini (the verified recipe sets it)', advice['applied'])
        self.assertIn('Game setting m_bGrain=0 in renderer.ini (a recipe candidate; not applied)', advice['shown'])
        self.assertIn('FrameGen.FTInput=2 (the verified recipe sets it)', advice['applied'])
        self.assertIn('Reports problems with OptiFG input (not used here: the verified recipe decides the input)', advice['shown'])
        self.assertFalse(any('left out of the automatic choice' in a for a in advice['applied']))
        self.assertFalse(any('Nukem' in x for x in advice['applied'] + advice['shown']))
        self.assertEqual(advice['hidden'].get('an FG input this build never uses (F0)'), 1)
        auto = c.decide(scan(game_fg=dict(dlssg=True)), data([], [], [wiki]), ids())
        self.assertIn('OptiFG input left out of the automatic choice (reported broken)', c.wiki_advice(data([], [], [wiki]), ids(), auto)['applied'])

    def test_wiki_rule_conflicts_are_shown_not_applied(self):
        v = c.decide(scan(), data([], [], [WIKI]), ids())
        advice = c.wiki_advice(data([], [], [WIKI]), ids(), v)
        shown = '\n'.join(advice['shown'])
        self.assertIn('OptiFG.HUDFix=true: not applied automatically (H1', shown)
        self.assertIn('Spoofing.Dxgi=false: not applied automatically (D1', shown)
        self.assertIn('fakenvapi.EnableLogs=true: not applied automatically (R1', shown)
        self.assertIn('FSR.FsrNonLinearPQ=true: not applied automatically (S1', shown)
        self.assertIn('V-Sync.ForceVsync=false: not applied (warning: V-Sync', shown)
        self.assertIn('Hotfix.DisableOverlays=true: a known fix when condition: crashing on startup', shown)
        self.assertIn('Prefers DLSS FG input (a suggestion; F3)', shown)
        self.assertIn('Reports OptiFG input working', shown)  # the full recipe file keeps "works" advice too
        self.assertIn('Reports problems with FSR 3.0 FG input when upscaler_input: fsr3', shown)
        self.assertNotIn('Reports problems with OptiFG', shown)
        self.assertNotIn('Spoofing.Vulkan', shown)  # api vulkan: false here, hidden
        self.assertNotIn('EnableFsr2Inputs', shown)  # NVIDIA only: hidden
        self.assertEqual(sum(advice['hidden'].values()), 2)
        self.assertIn('Hotfix.ColorResourceBarrier=5 (OptiScaler wiki (Hero), promoted)', advice['applied'])
        quirks = {'hero-win64-shipping.exe': {'Spoofing.Dxgi': 'false', 'Hotfix.DisableOverlays': 'false'}}
        advice = c.wiki_advice(data([], [], [WIKI], quirks), ids(), v)
        self.assertIn('Hotfix.DisableOverlays=true: not applied; OptiScaler\'s own fix for this game sets Hotfix.DisableOverlays (Q1)', advice['shown'])
        self.assertEqual(advice['hidden']['already handled by OptiScaler'], 1)  # the same Dxgi value: redundant


class InputTests(unittest.TestCase):
    def test_detection_order(self):
        native = c.decide(scan(native_xefg=True), data(), ids())
        self.assertEqual((native['route'], native['tier']), ('native', 'D'))
        self.assertIn('Turn on the game\'s XeSS frame generation', native['manual_steps'][0])
        opti = c.decide(scan(), data(), ids())
        self.assertEqual((opti['route'], opti['fg_input'], opti['needs_step']), ('opti', 'upscaler', False))
        self.assertEqual((opti['launch_args'], opti['launch_source']), (['-dx12'], 'detection (likely needed)'))
        game_fg = c.decide(scan(upscalers=[], game_fg=dict(dlssg=True), fg_toggle_hints=['Unreal Streamline DLSS-G']), data(), ids())
        self.assertEqual((game_fg['route'], game_fg['fg_input'], game_fg['needs_step']), ('opti', 'dlssg', True))
        self.assertIn('Unreal Streamline DLSS-G', game_fg['manual_steps'][1])
        sdk2 = c.decide(scan(upscalers=[], game_fg=dict(dlssg=True, fsrfg_sdk2=True)), data(), ids())
        self.assertEqual(sdk2['fg_input'], 'fsrfg')
        only30 = c.decide(scan(upscalers=[], game_fg=dict(fsrfg30=True)), data(), ids())
        self.assertNotEqual(only30['fg_input'], 'fsrfg30')  # FSR 3.0 FG is never chosen automatically
        self.assertEqual(only30['tier'], 'D')  # it is an input the game ships, so not "no input"

    def test_vetoes_remove_never_add(self):
        veto = dict(WIKI, fg_advice=[dict(advice='broken', input='upscaler'), dict(advice='broken', input='native-xefg')], promoted=[])
        v = c.decide(scan(game_fg=dict(dlssg=True), native_xefg=True), data([], [], [veto]), ids())
        self.assertEqual((v['route'], v['fg_input'], v['tier']), ('opti', 'dlssg', 'C'))
        self.assertTrue(v['needs_step'])
        v = c.decide(scan(), data([], [], [veto]), ids())  # nothing left: a veto adds no input
        self.assertEqual((v['route'], v['fg_input']), ('opti', 'upscaler'))
        explicit = c.decide(scan(), data([], [], [veto]), ids(), choice=dict(route='opti', fg_input='upscaler'))
        self.assertTrue(any('reports OptiFG broken' in w for w in explicit['warnings']))
        self.assertEqual(explicit['blocking'], [])
        weak = c.decide(scan(game_fg=dict(dlssg=True)), data([], [], [veto]), ids(exe='other.exe'))
        self.assertEqual(weak['fg_input'], 'upscaler')  # a title match only warns
        self.assertTrue(any('matched by title only' in w for w in weak['warnings']))
        conditional = dict(veto, fg_advice=[dict(advice='broken', input='upscaler', when=dict(condition='MS Store version'))])
        self.assertEqual(c.decide(scan(game_fg=dict(dlssg=True)), data([], [], [conditional]), ids())['fg_input'], 'upscaler')

    def test_one_api_switch(self):
        user = c.decide(scan(api=dict(current_switch=['-dx11'])), data([], [], [WIKI]), ids())
        self.assertTrue(any('select -dx11' in w for w in user['warnings']))
        unity = c.decide(scan(engine=dict(name='unity', version='2021'), api=dict(switch='-force-d3d12')), data(), ids(exe='cube.exe', titles=()))
        self.assertEqual(unity['launch_args'], ['-force-d3d12'])
        godot = c.decide(scan(api=dict(switch='--rendering-driver d3d12')), data(), ids(exe='g.exe', titles=()))
        self.assertEqual(godot['launch_args'], ['--rendering-driver', 'd3d12'])
        no_switch = c.decide(scan(api=dict(switch=None, default='vulkan')), data(), ids(exe='x.exe', titles=()))
        self.assertIn('Select DirectX 12 in the game\'s own settings.', no_switch['manual_steps'])

    def test_dlss_helper_for_dlss_only_games(self):
        self.assertEqual(c.decide(scan(dlss_copy=False), data(), ids())['dlss_helper'], 'yes')
        self.assertEqual(c.decide(scan(dlss_copy=True), data(), ids())['dlss_helper'], 'auto')
        self.assertEqual(c.decide(scan(dlss_copy=False, upscalers=['dlss', 'xess']), data(), ids())['dlss_helper'], 'auto')
        self.assertEqual(c.decide(scan(dlss_copy=False), data([VERIFIED]), ids())['dlss_helper'], 'auto')


class RefusalTests(unittest.TestCase):
    def codes(self, v):
        return [(x['code'], x['kind']) for x in v['refusals']]

    def test_each_refusal_and_its_text(self):
        cases = [
            (dict(anticheat=[dict(name='Easy Anti-Cheat', evidence=['EasyAntiCheat'], proton_runtime=False)]), 'anticheat', 'may ban the account'),
            (dict(exe=dict(selected=None, best=None, native_linux=['game.x86_64'])), 'native-linux', 'force a Proton version'),
            (dict(exe=dict(selected=None, best=None, native_linux=[])), 'no-exe', 'No Windows game executable'),
            (dict(exe=dict(bits=32)), '32bit', '64-bit only'),
            (dict(api=dict(dx12=False, default='vulkan')), 'api-vulkan', 'Vulkan only'),
            (dict(api=dict(dx12=False, default='opengl')), 'api-opengl', 'OpenGL only'),
            (dict(api=dict(dx12=False, default='d3d11')), 'api-dx11', 'black screen'),
            (dict(upscalers=[]), 'no-input', 'no motion vectors'),
            (dict(api=dict(dx12=False, default=None, apis=[]), upscalers=[]), 'no-dx12', 'No DirectX 12 path'),
            (dict(exe=dict(selected='Hero.exe', stub='Hero/Binaries/Win64/Hero-Win64-Shipping.exe')), 'wrong-exe', 'Choose Hero/Binaries'),
            (dict(protonfix=dict(tool='GE-Proton11-7', change="append_argument('-fullscreen -vulkan')")), 'protonfix-api', 'PROTONFIXES_DISABLE=1'),
        ]
        for over, code, text in cases:
            v = c.decide(scan(**over), data(), ids())
            found = [x for x in v['refusals'] if x['code'] == code]
            self.assertTrue(found, (code, self.codes(v)))
            self.assertIn(text, found[0]['text'] + ' ' + found[0]['way'], code)
            self.assertEqual(v['tier'], 'R', code)
            with self.assertRaises(c.Refused) as refused:
                c.preflight(v)
            self.assertIn('[' + v['blocking'][0]['code'] + ']', str(refused.exception))

    def test_low_confidence_is_not_refused(self):
        # The installer tests' stand-in executable: no import table, nothing read about its API.
        v = c.decide(scan(exe=dict(imports=False), api=dict(dx12=False, default=None, apis=[]), upscalers=[]), data(), ids())
        self.assertEqual(v['blocking'], [])
        self.assertTrue(any('could not read enough' in w for w in v['warnings']))
        self.assertEqual(c.decide(scan(complete=False, upscalers=[]), data(), ids())['blocking'], [])

    def test_recipes_override_detection_refusals_but_not_anticheat(self):
        self.assertEqual(c.decide(scan(upscalers=[]), data([VERIFIED]), ids())['blocking'], [])
        self.assertEqual(c.decide(scan(api=dict(dx12=False, default='d3d11')), data([VERIFIED]), ids())['blocking'], [])
        ac = c.decide(scan(anticheat=[dict(name='BattlEye', evidence=['BattlEye'], proton_runtime=True)]), data([VERIFIED]), ids())
        self.assertEqual(ac['blocking'][0]['code'], 'anticheat')

    def test_soft_refusals_need_an_accept(self):
        fix = dict(protonfix=dict(tool='GE-Proton11-7', change="append_argument('-dx11')"))
        v = c.decide(scan(**fix), data(), ids())
        self.assertEqual([x['code'] for x in v['blocking']], ['protonfix-api'])
        v = c.decide(scan(**fix), data(), ids(), accept=['protonfix-api'])
        self.assertEqual((v['blocking'], v['accepted'], v['extra_env']), ([], ['protonfix-api'], {'PROTONFIXES_DISABLE': '1'}))
        broken = dict(WIKI, compat='not-working', promoted=[], fg_advice=[])
        v = c.decide(scan(), data([], [], [broken]), ids())
        self.assertEqual([x['code'] for x in v['blocking']], ['wiki-not-working'])
        self.assertEqual(c.decide(scan(), data([], [], [broken]), ids(), accept=['wiki-not-working'])['blocking'], [])
        with self.assertRaises(c.Refused):
            c.preflight(c.decide(scan(anticheat=[dict(name='EQU8', evidence=['equ8.dll'], proton_runtime=False)]), data(), ids(),
                                 accept=['anticheat']))

    def test_an_explicit_choice_makes_detection_refusals_soft(self):
        # Detection can miss an input (a packed executable, an SDK it does not know): the user's explicit choice may
        # install anyway with an accept; Automatic never does.
        for over, code in ((dict(upscalers=[]), 'no-input'), (dict(api=dict(dx12=False, default='vulkan')), 'api-vulkan'),
                           (dict(api=dict(dx12=False, default='d3d11')), 'api-dx11'),
                           (dict(api=dict(dx12=False, default=None, apis=[]), upscalers=[]), 'no-dx12')):
            auto = c.decide(scan(**over), data(), ids())
            self.assertEqual([(x['code'], x['kind']) for x in auto['blocking']], [(code, 'hard')], code)
            self.assertEqual(c.decide(scan(**over), data(), ids(), accept=[code])['tier'], 'R', code)
            chosen = dict(route='opti', fg_input='upscaler')
            explicit = c.decide(scan(**over), data(), ids(), choice=chosen)
            self.assertEqual([(x['code'], x['kind']) for x in explicit['blocking']], [(code, 'soft')], code)
            self.assertIn('Install anyway (you chose the input)', explicit['blocking'][0]['way'])
            accepted = c.decide(scan(**over), data(), ids(), choice=chosen, accept=[code])
            self.assertEqual((accepted['blocking'], accepted['accepted'], accepted['tier']), ([], [code], 'D'), code)
        # 32-bit and a missing executable stay hard whatever is chosen; anti-cheat stays a risk refusal, which no accept lifts.
        ac = c.decide(scan(anticheat=[dict(name='BattlEye', evidence=['BattlEye'], proton_runtime=False)]), data(), ids(),
                      choice=dict(route='opti', fg_input='upscaler'), accept=['anticheat'])
        self.assertEqual((ac['blocking'][0]['code'], ac['blocking'][0]['kind'], ac['tier']), ('anticheat', 'risk', 'R'))
        self.assertEqual(c.decide(scan(exe=dict(bits=32)), data(), ids(), choice=dict(route='opti'), accept=['32bit'])['tier'], 'R')

    def test_anticheat_is_a_risk_refusal_lifted_only_by_the_override(self):
        both = [dict(name='Easy Anti-Cheat', evidence=['EasyAntiCheat/'], proton_runtime=True),
                dict(name='BattlEye', evidence=['BattlEye/'], proton_runtime=False)]
        v = c.decide(scan(anticheat=both), data(), ids())
        r_ = v['blocking'][0]
        self.assertEqual((r_['code'], r_['kind'], r_['names'], v['tier']), ('anticheat', 'risk', ['Easy Anti-Cheat', 'BattlEye'], 'R'))
        self.assertIn('ships anti-cheat: Easy Anti-Cheat and BattlEye', r_['text'])
        # The way forward names the override's option and where it is described, without offering it as Install anyway.
        self.assertEqual(r_['way'], 'None by default. An override for one game risks a ban: --accept-anticheat-risk '
                                    '(COMPATIBILITY.md#anti-cheat).')
        self.assertNotIn('Install anyway', r_['way'])
        self.assertIn('--accept-anticheat-risk', v['line'])
        # Neither an accept of its code nor every soft code lifts it, with Automatic or an explicit input.
        for choice in (None, dict(route='opti', fg_input='upscaler')):
            accepted = c.decide(scan(anticheat=both), data(), ids(), choice=choice, accept=['anticheat', 'protonfix-api', 'wiki-not-working'])
            self.assertEqual(([x['code'] for x in accepted['blocking']], accepted['accepted'], accepted['risk_accepted']), (['anticheat'], [], []))
            with self.assertRaises(c.Refused):
                c.preflight(accepted)
        # The override lifts it: the plan is the one the game has without anti-cheat, and the verdict says it was overridden.
        plain = c.decide(scan(), data([VERIFIED]), ids())
        overridden = c.decide(scan(anticheat=both), data([VERIFIED]), ids(), accept_risk=['anticheat'])
        c.preflight(overridden)
        self.assertEqual((overridden['blocking'], overridden['accepted'], overridden['risk_accepted']), ([], [], ['anticheat']))
        for key in ('tier', 'route', 'fg_input', 'launch_args', 'ini', 'line'):
            self.assertEqual(overridden[key], plain[key], key)
        lines = c.check_lines(overridden, scan(anticheat=both), installed_notes=['Installed despite anti-cheat (BattlEye), risk accepted on 2026-10-20.'])
        self.assertTrue(any(line.startswith('[anticheat, risk, risk accepted]') for line in lines))
        self.assertIn('Installed despite anti-cheat (BattlEye), risk accepted on 2026-10-20.', lines)
        refused = c.check_lines(v, scan(anticheat=both))
        self.assertTrue(any(line.startswith('[anticheat, risk, refused]') and '--accept-anticheat-risk' in line for line in refused))
        # The override lifts only risk refusals: never a soft or a hard one.
        fix = dict(protonfix=dict(tool='GE-Proton11-7', change="append_argument('-dx11')"))
        soft = c.decide(scan(anticheat=both, **fix), data(), ids(), accept_risk=['anticheat', 'protonfix-api'])
        self.assertEqual([x['code'] for x in soft['blocking']], ['protonfix-api'])
        hard = c.decide(scan(anticheat=both, exe=dict(bits=32)), data(), ids(), accept_risk=['anticheat', '32bit'])
        self.assertEqual([x['code'] for x in hard['blocking']], ['32bit'])

    def test_the_report_lists_an_override_with_the_package(self):
        text = c.report(c.decide(scan(), data(), ids()), scan(), package='freefg-1.0.1',
                        installed_notes=['Installed despite anti-cheat (BattlEye), risk accepted on 2026-10-20.'])
        self.assertIn('- Package: freefg-1.0.1\n', text)
        self.assertIn('- Installed despite anti-cheat (BattlEye), risk accepted on 2026-10-20.\n', text)

    def test_native_choice_needs_the_games_xess_fg(self):
        v = c.decide(scan(), data(), ids(), choice=dict(route='native'))
        self.assertEqual((v['blocking'][0]['code'], v['blocking'][0]['kind'], v['tier']), ('no-native-xefg', 'hard', 'R'))
        self.assertEqual(c.decide(scan(xefg_beside=True), data(), ids(), choice=dict(route='native'))['blocking'], [])

    def test_unity_dlss_dll_alone_is_unconfirmed(self):
        unity = dict(engine=dict(name='unity', version='2021.3'), upscalers=[], dlss_copy=True, api=dict(switch='-force-d3d12'),
                     dlss_unconfirmed='nvngx_dlss.dll and NVUnityPlugin.dll come with Unity\'s NVIDIA module, and the game\'s code never names DLSS (3 code files read)')
        v = c.decide(scan(**unity), data(), ids(exe='cube.exe', titles=()))
        self.assertEqual([(x['code'], x['kind']) for x in v['blocking']], [('input-unconfirmed', 'soft')])
        self.assertIn('Install anyway only if the game\'s graphics menu offers DLSS', v['line'])
        accepted = c.decide(scan(**unity), data(), ids(exe='cube.exe', titles=()), accept=['input-unconfirmed'])
        self.assertEqual((accepted['tier'], accepted['route'], accepted['fg_input'], accepted['dlss_helper']), ('D', 'opti', 'upscaler', 'auto'))
        self.assertIn('Unity bundles', accepted['reason'])
        self.assertIn('a DLSS DLL Unity bundles', '\n'.join(c.check_lines(v, scan(**unity))))
        # Another input the game ships, or a verified recipe, settles it.
        self.assertEqual(c.decide(scan(**dict(unity, upscalers=['fsr2'])), data(), ids(exe='cube.exe', titles=()))['blocking'], [])
        self.assertEqual(c.decide(scan(**unity), data([VERIFIED]), ids())['blocking'], [])

    def test_wiki_not_working_needs_a_strong_match(self):
        broken = dict(WIKI, compat='not-working', promoted=[], fg_advice=[], match=dict(title=['hero']))  # as shipped: title only
        v = c.decide(scan(), data([], [], [broken]), ids())
        self.assertEqual(v['blocking'], [])
        self.assertTrue(any('matched by title only' in w and 'does not work' in w for w in v['warnings']))
        strong = dict(broken, match=dict(title=['hero'], steam=['4242']))
        self.assertEqual([x['code'] for x in c.decide(scan(), data([], [], [strong]), ids())['blocking']], ['wiki-not-working'])

    def test_protonfix_way_names_what_else_the_fix_does(self):
        fix = dict(tool='GE-Proton11-7', change="append_argument('-dx11')", others=["protontricks('d3dx9_43')"])
        way = c.decide(scan(protonfix=fix), data(), ids())['blocking'][0]['way']
        self.assertIn('turns off all of GE-Proton\'s fixes for this game (here also: protontricks(\'d3dx9_43\'))', way)
        self.assertIn('(here only that switch)', c.decide(scan(protonfix=dict(fix, others=[])), data(), ids())['blocking'][0]['way'])

    def test_folder_refusals_block_install_but_keep_the_verdict(self):
        # install.preconditions: an earlier installation, another OptiScaler setup... Check still shows the plan.
        setup = [dict(code='existing-optiscaler', kind='hard', text='An OptiScaler setup from another source is in the game folder.',
                      way='Restore or remove it first.')]
        v = c.decide(scan(), data(), ids(), setup=setup)
        self.assertEqual((v['tier'], v['route'], [x['code'] for x in v['blocking']]), ('D', 'opti', ['existing-optiscaler']))
        self.assertTrue(v['line'].startswith('Automatic (no recipe)'))
        self.assertIn('Before Install: An OptiScaler setup from another source', v['line'])
        text = '\n'.join(c.check_lines(v, scan()))
        self.assertIn('Plan: OptiFG input', text)
        self.assertIn('[existing-optiscaler, hard, before Install, refused]', text)
        with self.assertRaises(c.Refused):
            c.preflight(v)
        both = c.decide(scan(upscalers=[]), data(), ids(), setup=setup)
        self.assertTrue(both['line'].startswith('Not supported:'))  # a compatibility refusal comes first

    def test_launcher_refusals_pass_through(self):
        conflict = dict(code='shared-entry', kind='hard', text='This Heroic entry already starts an installation in /x.', way='Restore it first.')
        v = c.decide(scan(), data(), ids(), launcher_conflicts=[conflict], launchers=[{}])
        self.assertEqual(v['blocking'][0]['code'], 'shared-entry')
        self.assertEqual(c.decide(scan(), data(), ids(), launchers=[])['blocking'][0]['code'], 'no-launcher')


class VerifiedUnchangedTests(unittest.TestCase):
    """Every verified recipe in the shipped recipe file decides as 0.9.0 did: route, input, launch argument, no extra
    keys, no DLSS helper, no refusal, whatever detection finds."""

    def test_every_verified_recipe(self):
        data_ = r.load(ROOT/'packaging/recipes/recipes-runtime.json')
        self.assertEqual(len(data_['verified']), 19)
        for v in data_['verified']:
            m = v['match']
            game = dict(exe=m['exe'][0], steam=set(m.get('steam', [])), gog=set(m.get('gog', [])), epic=set(m.get('epic', [])),
                        titles={r.norm(v['title'])}, folders=set())
            verified, wiki, _, _ = r.match(data_, game)
            self.assertIs(verified, v)
            native = v['route'] == 'native'
            # The last case: the game's libxess_fg.dll beside the executable with an XeSSMFG folder there (native_xefg
            # false, xefg_beside true): a verified native recipe keeps its route, as in 0.9.0.
            for detected in (scan(native_xefg=native, xefg_beside=native), scan(native_xefg=native, xefg_beside=native, upscalers=[],
                                                                                 api=dict(dx12=False, default='d3d11', switch=None)),
                             scan(native_xefg=False, xefg_beside=native)):
                d = c.decide(detected, data_, game)
                self.assertEqual((d['tier'], d['route'], d['fg_input']), ('A', v['route'], v.get('fg_input') or 'upscaler'), v['title'])
                self.assertEqual(d['launch_args'], r.launch_args(verified, wiki), v['title'])
                self.assertEqual((d['ini'], d['dlss_helper'], d['extra_env'], d['blocking']), ({}, 'auto', {}, []), v['title'])


class LibraryTests(unittest.TestCase):
    """The verdicts on a synthetic library (fixtures/compat/library-synthetic.json): made-up games, one or two per verdict
    group, in the shape of gamescan.py's scans. The maintainers check the same verdicts on their own library with
    scripts/test_compat_library.py, which stays out of the public tree."""

    @staticmethod
    def verdict(s, data_):
        exe = ((s['exe'] or {}).get('selected') or '').rsplit('/', 1)[-1].lower()
        game = dict(exe=exe, steam=set(), gog=set(), epic=set(), titles={r.norm(s['name'] or '')}, folders=set())
        game[s['store']].add(s['id'])
        return c.decide(s, data_, game)

    def test_every_group(self):
        games = json.loads((FIXTURES/'library-synthetic.json').read_text())['games']
        data_ = r.load(ROOT/'packaging/recipes/recipes-runtime.json')
        found = {}
        for s in games:
            v = self.verdict(s, data_)
            found[s['id']] = (v['tier'], v['route'], tuple(v['launch_args'])) if not v['blocking'] else \
                (v['blocking'][0]['code'], v['blocking'][0]['kind'])
        self.assertEqual(found, {
            '9990001': ('D', 'opti', ('-dx12',)),          # Unreal 5 with DLSS, FSR 3.1 and XeSS
            '9990002': ('D', 'opti', ('-force-d3d12',)),   # Unity HDRP whose code uses DLSS
            '9990003': ('D', 'native', ()),                # the game's own XeSS FG beside the executable
            '9990004': ('no-input', 'hard'), '9990005': ('no-input', 'hard'),
            '9990006': ('input-unconfirmed', 'soft'),      # only the DLSS DLL Unity's NVIDIA module bundles
            '9990007': ('native-linux', 'hard'), '9990008': ('32bit', 'hard'), '9990009': ('api-vulkan', 'hard'),
            '9990010': ('api-opengl', 'hard'), '9990011': ('api-dx11', 'hard'), '9990012': ('no-dx12', 'hard'),
            '9990013': ('no-exe', 'hard'), '9990014': ('anticheat', 'risk')})
        self.assertFalse(any('mods' in s for s in games))  # other tools' files are never part of a fixture

    def test_a_strong_wiki_match_guides_the_automatic_setup(self):
        # Tier C: the synthetic Unreal 5 game under the executable and title of a wiki entry that names a DX12 launch
        # option, a strong match (the wiki list is public; no maintainer's game is named here). A title alone still takes
        # the option where detection confirms DX12, but stays tier D.
        games = json.loads((FIXTURES/'library-synthetic.json').read_text())['games']
        data_ = r.load(ROOT/'packaging/recipes/recipes-runtime.json')
        wiki = next(w for w in data_['wiki'] if w['match'].get('exe') and w.get('compat') == 'working' and not w['match'].get('steam')
                    and any(a.lower() in c.DX12_ARGS for a in w.get('launch_args', [])))
        args = [a for a in wiki['launch_args'] if a.lower() in c.DX12_ARGS][:1]
        strong = dict(copy.deepcopy(games[0]), name=wiki['title'])
        strong['exe'] = dict(strong['exe'], selected='Game/Binaries/Win64/' + wiki['match']['exe'][0], best='Game/Binaries/Win64/' + wiki['match']['exe'][0])
        weak = dict(copy.deepcopy(games[0]), name=wiki['title'])
        for s, tier in ((strong, 'C'), (weak, 'D')):
            v = self.verdict(s, data_)
            self.assertEqual((v['tier'], v['blocking'], v['launch_args']), (tier, [], args), wiki['title'])
            self.assertTrue(v['launch_source'].startswith('OptiScaler wiki'), wiki['title'])


class RunAndReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_last_run(self):
        self.assertFalse(c.last_run(self.root)['found'])
        (self.root/'OptiScaler.log').write_text('[I] FrameGen.FGInput: upscaler\n[I] TryCreateOptiFeature Creating FSR 3.X upscaler feature\n'
                                                '[I] FFXFeatureDx12 ffx loaded\n[I] CreateSwapchain XeFG swapchain created\n')
        (self.root/'BC250-MFG.log').write_text("MFG proxy ready: Intel's XeFG runtime unmodified beside it\n" + self.OWNER)
        (self.root/'BC250-XeFG-fast.log').write_text('WINOGRAD_EXECUTE shader=aa\nWINOGRAD_EXECUTE shader=bb\nFAIL stage 2\n')
        run = c.last_run(self.root)
        self.assertEqual((run['xefg'], run['fg_input'], run['upscaler'], run['proxy'], run['accelerated'], run['cause']),
                         (True, 'upscaler', 'FSR', 'ready', 2, None))
        self.assertIn('a FAIL marker in BC250-XeFG-fast.log', run['problems'])
        (self.root/'OptiScaler.log').write_text('[I] FrameGen.FGInput: upscaler\n')
        (self.root/'BC250-MFG.log').write_text('MFG proxy: Intel XeFG runtime did not load (error 126)\n')
        run = c.last_run(self.root)
        self.assertFalse(run['xefg'])
        self.assertIn('never created an upscaler', run['cause'])
        # The fast log is the earlier session's (this one has no FAST_OWNER): its FAIL marker is not this session's.
        self.assertTrue(run['fast_stale'])
        self.assertNotIn('a FAIL marker in BC250-XeFG-fast.log', run['problems'])
        self.assertTrue(any('did not load' in p for p in run['problems']))
        self.assertIn('Likely cause:', '\n'.join(c.last_run_lines(run)))

    # Logs of the proxy's 1.1 builds (made-up hashes; the line texts are the proxy's own).
    READY = 'MFG_SETTINGS mode=0 percent=75 limit=1080 down=0 up=0 override=0\nMFG proxy ready: Intel\'s XeFG runtime unmodified beside it\n'
    GENERATES = 'MFG_FACTOR context initialised for up to 2x\nMFG_STATUS XeFG generates: 2 frames per present (SDK status)\nMFG_PRESENT enabled=1 status=0 presents=2\n'
    OWNER = 'FAST_OWNER first initialized context selected\n'
    COEXIST = ('FAST_COEXIST another module hooks Intel\'s XeFG runtime (xefgSwapChainD3D12CreateContext: its code was changed; jumps to '
               '{module}): lifecycle calls keep their caller, unrecognised work steps aside instead of ending the game\n')
    SKIP = ('FAST_SKIP beside another module hooking Intel\'s XeFG runtime only OptiScaler\'s own contexts are accelerated; this one '
            '(created from Game.exe) keeps the caller\'s device and runs Intel\'s or that module\'s shaders\n')
    BESIDE = 'FAST_COEXIST this context is accelerated beside the other module; replaced pipelines keep Intel\'s originals beside them\n'

    def logs(self, proxy, programs=None, f4q=0, model=None, unlocker=False):
        """The game folder after a session: BC250-MFG.log, a fast log with programs REPLACE lines (None: no fast log),
        OptiScaler.ini with XeFGModel (None: no key) and MFG Unlocker's plugin."""
        for name in ('BC250-MFG.log', 'BC250-XeFG-fast.log', 'OptiScaler.ini', 'OptiScaler/plugins/MFGUnlocker.asi'):
            (self.root/name).unlink(missing_ok=True)
        (self.root/'BC250-MFG.log').write_text(proxy)
        if programs is not None:
            lines = ['FAST_CONTEXT_BEGIN', 'INTEL_FREE own shaders only']
            for i in range(programs):
                lines += [f'REPLACE {i:016x} 56888', f'PSO 00000001058455C0 {i:016x}']
            lines += [f'F4Q_REPLACE {i:016x} {i:016x}.f4q.dxil 72484' for i in range(f4q)]
            (self.root/'BC250-XeFG-fast.log').write_text('\n'.join(lines) + '\n')
        (self.root/'OptiScaler.ini').write_text('[XeFG]\nForceBorderless=true\n' + (f'XeFGModel = {model}\n' if model is not None else ''))
        if unlocker:
            (self.root/'OptiScaler/plugins').mkdir(parents=True, exist_ok=True)
            (self.root/'OptiScaler/plugins/MFGUnlocker.asi').write_bytes(b'placeholder')

    def case(self, route=None):
        run = c.last_run(self.root, route)
        return run['acceleration'], run['acceleration_reason'], run['own_programs'], c.acceleration_lines(run)

    def test_acceleration_full(self):
        # 13 programs on this build's shaders: 2x native, and 3x/4x through MFG Unlocker with XeFGModel=default.
        self.logs(self.READY + self.OWNER + self.GENERATES, 13, 2)
        kind, why, n, lines = self.case('native')
        self.assertEqual((kind, why, n), ('full', None, 13))
        self.assertEqual(lines, ["Acceleration: full (this build's shaders ran on 13 of 13 programs)."])
        self.assertEqual(c.last_run(self.root)['f4q'], 2)
        self.logs(self.READY + self.COEXIST.format(module='MFGUnlocker.asi') + self.SKIP + self.OWNER + self.BESIDE + self.GENERATES,
                  13, 2, model='default', unlocker=True)
        run = c.last_run(self.root, 'opti')
        self.assertEqual((run['acceleration'], run['owner'], run['coexist_accelerated'], run['skipped_game_context'], run['mfg_unlocker'],
                          run['xefg_model']), ('full', True, True, True, 'MFGUnlocker.asi', 'default'))
        # An earlier build replaced more programs: full all the same.
        self.logs(self.READY + self.OWNER, 19)
        self.assertEqual(self.case('native')[3], ["Acceleration: full (this build's shaders ran on 19 programs)."])
        # The last run line no longer repeats the stage count beside it.
        self.assertNotIn('accelerated stages', '\n'.join(c.last_run_lines(c.last_run(self.root))))

    def test_acceleration_partial_with_mfg_unlocker_model(self):
        # OptiScaler's FG with MFG Unlocker, XeFGModel unset, empty or auto: 7 of 13 programs (4K report, 2026-10-21).
        proxy = self.READY + self.COEXIST.format(module='MFGUnlocker.asi') + self.SKIP + self.OWNER + self.BESIDE + self.GENERATES
        for model in (None, '', 'auto'):
            with self.subTest(model=model):
                self.logs(proxy, 7, 1, model=model, unlocker=True)
                kind, why, n, lines = self.case('opti')
                self.assertEqual((kind, why, n), ('partial', 'mfg-unlocker-model', 7))
                self.assertEqual(lines, ["Acceleration: partial (this build's shaders ran on 7 of 13 programs): MFG Unlocker's own model "
                                         'replaced the rest.',
                                         'Fix: set XeFGModel=default under [XeFG] in OptiScaler.ini (a new Install writes it where it is unset).'])
        # The module is named in the log alone (no plugin file found): the same answer.
        self.logs(proxy, 7, 1)
        self.assertEqual(self.case()[:2], ('partial', 'mfg-unlocker-model'))
        # XeFGModel=default since that session, or no MFG Unlocker at all: the count, stated neutrally.
        self.logs(proxy, 7, 1, model='default', unlocker=True)
        self.assertEqual(self.case('opti')[1:], (None, 7, ["Acceleration: partial (this build's shaders ran on 7 of 13 programs)."]))
        self.logs(self.READY + self.OWNER, 5)
        self.assertEqual(self.case('native')[:3], ('partial', None, 5))

    def test_acceleration_not_running(self):
        native = ['Acceleration: none. MFG Unlocker is loaded and the game\'s own XeSS frame generation was used: this build accelerates '
                  'only OptiScaler\'s frame generation beside MFG Unlocker.',
                  'Fix: remove MFG Unlocker for 2×, or install on the OptiScaler route for 3×/4×.']
        generic = ['Acceleration: none (no acceleration log).',
                   'Check: the launch options for BC250_XEFG_DISABLE, and BC250-MFG.log for FAST_FALLBACK, FAST_SKIP or FAST_ASIDE lines.']
        # The game's own XeSS FG with MFG Unlocker loaded: FAST_SKIP beside another module, no FAST_OWNER and no
        # CONTEXT_CALLER (no OptiScaler context reached the choice). Named on any route, also with the route unknown.
        skipped = self.READY + self.COEXIST.format(module='MFGUnlocker.asi') + self.SKIP + self.GENERATES
        self.logs(skipped, unlocker=True)
        self.assertEqual(self.case('native'), ('not-running', 'native-beside-mfg-unlocker', 0, native))
        self.assertEqual(self.case(None), ('not-running', 'native-beside-mfg-unlocker', 0, native))
        opti = self.case('opti')
        self.assertEqual(opti[:2], ('not-running', 'native-beside-mfg-unlocker'))
        self.assertTrue(opti[3][1].startswith('Fix: in the game, use the frame generation of the installation\'s OptiScaler input'))
        # BC250_XEFG_DISABLE=1 on the OptiScaler route beside MFG Unlocker: OptiScaler's context logs CONTEXT_CALLER first.
        disabled = self.READY + self.COEXIST.format(module='MFGUnlocker.asi') + 'CONTEXT_CALLER Z:\\Game\\dxgi.dll\n' + self.SKIP + self.GENERATES
        self.logs(disabled, unlocker=True)
        for route in ('opti', None):
            self.assertEqual(self.case(route), ('not-running', None, 0, generic), route)
        # Another module than MFG Unlocker.
        self.logs(self.READY + self.COEXIST.format(module='Z:\\mods\\Other.asi') + self.SKIP + self.GENERATES)
        self.assertTrue(self.case('native')[3][0].startswith('Acceleration: none. Another module (Other.asi) hooks Intel'))
        # BC250_XEFG_DISABLE=1 on the native route: frames generated, nothing accelerated, no line explains it.
        self.logs(self.READY + self.GENERATES)
        self.assertEqual(self.case('native'), ('not-running', None, 0, generic))
        # XeFG never made a context (frame generation off): not used, nothing to fix.
        self.logs(self.READY)
        self.assertEqual(self.case('native')[0::3], ('idle', ['Acceleration: not used (no XeFG frame-generation context in the last session).']))
        # A proxy that failed already says why (its own Log: line): no second explanation.
        self.logs("MFG proxy: Intel XeFG runtime did not load (error 126)\n")
        self.assertEqual(self.case('native')[3], [])

    def test_acceleration_from_unusual_logs(self):
        # No logs, garbled logs, a symlinked log or INI, logs of another format: no crash, and no claim the logs do not make.
        self.assertIsNone(c.last_run(self.root, 'native')['acceleration'])
        (self.root/'BC250-MFG.log').write_bytes(b'\xff\xfe\x00FAST_OWNER\x00 garbage \xc3\x28\n' * 50)
        (self.root/'BC250-XeFG-fast.log').write_bytes(b'\x00\xffREPLACE 0123 7\n\x89PNG REPLACE nothing\n')
        (self.root/'OptiScaler.ini').write_bytes(b'\xff[XeFG\nXeFGModel\n=\n[[[')
        run = c.last_run(self.root, 'native')
        self.assertEqual((run['acceleration'], run['own_programs'], run['owner'], run['xefg_model']), (None, 0, False, None))
        self.assertEqual(c.acceleration_lines(run), [])
        # A symlinked fast log or INI is not read.
        for name in ('BC250-MFG.log', 'BC250-XeFG-fast.log', 'OptiScaler.ini'):
            (self.root/name).unlink()
        elsewhere = self.root/'elsewhere'
        elsewhere.mkdir()
        (elsewhere/'fast.log').write_text(''.join(f'REPLACE {i:016x} 1\n' for i in range(13)))
        (elsewhere/'OptiScaler.ini').write_text('[XeFG]\nXeFGModel=default\n')
        (self.root/'BC250-XeFG-fast.log').symlink_to(elsewhere/'fast.log')
        (self.root/'OptiScaler.ini').symlink_to(elsewhere/'OptiScaler.ini')
        (self.root/'BC250-MFG.log').write_text(self.READY + self.OWNER)
        run = c.last_run(self.root, 'native')
        self.assertEqual((run['own_programs'], run['xefg_model'], run['acceleration']), (0, None, None))
        # An earlier build's fast log (stage lines, no REPLACE): the logs do not say how much ran.
        (self.root/'BC250-XeFG-fast.log').unlink()
        (self.root/'BC250-XeFG-fast.log').write_text('WINOGRAD_EXECUTE shader=aa\n')
        self.assertIsNone(c.last_run(self.root, 'native')['acceleration'])
        # MFG Unlocker known only from the files it writes beside the executable.
        (self.root/'BC250-XeFG-fast.log').unlink()
        (self.root/'RTXMFG-Universal.status.json').write_text('{}')
        self.assertEqual(c.last_run(self.root)['mfg_unlocker'], 'RTXMFG-Universal.status.json')

    def test_stale_fast_log_is_not_this_session(self):
        # BC250-MFG.log is new at every start; the fast log only in a session with FAST_OWNER. A full fast log left by
        # an earlier session must not make a session that accelerated nothing look full.
        full_fast = ''.join(f'REPLACE {i:016x} 56888\n' for i in range(13))
        skipped = self.READY + self.COEXIST.format(module='MFGUnlocker.asi') + self.SKIP + self.GENERATES
        for proxy, route, expected in ((skipped, 'native', ('not-running', 'native-beside-mfg-unlocker')),
                                       (self.READY + self.GENERATES, 'native', ('not-running', None)),  # BC250_XEFG_DISABLE
                                       (self.READY, 'native', ('idle', None))):                          # FG off
            with self.subTest(expected=expected):
                self.logs(proxy, unlocker=proxy is skipped)
                (self.root/'BC250-XeFG-fast.log').write_text(full_fast)
                run = c.last_run(self.root, route)
                self.assertEqual((run['acceleration'], run['acceleration_reason'], run['own_programs'], run['fast_stale']),
                                 expected + (0, True))
                self.assertNotIn('full', '\n'.join(c.acceleration_lines(run)))
        # The tester's sequence: native 2x worked, then MFG Unlocker added. Status gives one consistent answer.
        self.logs(skipped, unlocker=True)
        (self.root/'BC250-XeFG-fast.log').write_text(full_fast)
        run = c.last_run(self.root, 'native')
        self.assertEqual(c.setup_notes(self.root, 'native', run=run), [])
        self.assertTrue(c.acceleration_lines(run)[0].startswith('Acceleration: none. MFG Unlocker is loaded'))
        # An empty BC250-MFG.log (a session that ended before its first line) is still this session's: the fast log is not.
        (self.root/'BC250-MFG.log').write_bytes(b'')
        run = c.last_run(self.root, 'native')
        self.assertEqual((run['fast_stale'], run['own_programs'], run['acceleration']), (True, 0, None))
        # With no BC250-MFG.log at all (another format), the fast log is still read.
        (self.root/'BC250-MFG.log').unlink()
        self.assertEqual(c.last_run(self.root, 'native')['own_programs'], 13)

    def test_acceleration_stepped_aside(self):
        # FAST_ASIDE (an unverified census or work order beside another module): the REPLACE lines were written before,
        # but this build's shaders are off for the rest of the session.
        aside = ("FAST_ASIDE model census not verified, with another module hooking Intel's XeFG runtime: this context now runs "
                 "Intel's (or that module's) shaders; FreeFG's are off until it is destroyed\n")
        self.logs(self.READY + self.COEXIST.format(module='MFGUnlocker.asi') + 'CONTEXT_CALLER Z:\\Game\\dxgi.dll\n' + self.OWNER
                  + self.BESIDE + self.GENERATES + aside, 13, 2, model='default', unlocker=True)
        with open(self.root/'BC250-XeFG-fast.log', 'a') as f:
            f.write(aside)
        kind, why, n, lines = self.case('opti')
        self.assertEqual((kind, why, n), ('not-running', 'aside', 13))
        self.assertEqual(lines, ["Acceleration: stepped aside during the session (model census not verified): Intel's or the other "
                                 "module's shaders ran from then on.",
                                 'Fix: use MFG Unlocker v1.6.0 (the version this build was checked with) with XeFGModel=default, or '
                                 'remove the other module.'])

    def test_partial_beside_renamed_mfg_unlocker(self):
        # MFG Unlocker under another name: the RTXMFG-* files or the FAST_COEXIST line still give the XeFGModel fix.
        proxy = self.READY + self.COEXIST.format(module='RTXUnlocker.asi') + self.SKIP + self.OWNER + self.BESIDE + self.GENERATES
        self.logs(proxy, 7, 1)
        (self.root/'RTXMFG-Universal.status.json').write_text('{}')
        kind, why, n, lines = self.case('opti')
        self.assertEqual((kind, why), ('partial', 'mfg-unlocker-model'))
        self.assertIn("MFG Unlocker's own model", lines[0])
        self.assertTrue(lines[1].startswith('Fix: set XeFGModel=default'))
        (self.root/'RTXMFG-Universal.status.json').unlink()
        kind, why, n, lines = self.case('opti')
        self.assertEqual((kind, why), ('partial', 'mfg-unlocker-model'))
        self.assertIn('(RTXUnlocker.asi)', lines[0])

    def test_xefg_model_reader(self):
        self.assertIsNone(c.xefg_model(self.root))
        # A BOM before a first [XeFG] section (install.read_ini accepts and keeps one).
        (self.root/'OptiScaler.ini').write_bytes(b'\xef\xbb\xbf[XeFG]\r\nXeFGModel = default\r\n')
        self.assertEqual(c.xefg_model(self.root), 'default')
        (self.root/'OptiScaler.ini').write_text('[xefg]\r\n  xefgmodel =  Default  \r\n[Other]\r\nXeFGModel=xess\r\n')
        self.assertEqual(c.xefg_model(self.root), 'Default')
        (self.root/'OptiScaler.ini').write_text('[XeFG]\nForceBorderless=true\n[XeFG]\nXeFGModel=\n')  # configparser refuses this
        self.assertEqual(c.xefg_model(self.root), '')

    def test_setup_notes(self):
        unset = ('MFG Unlocker (OptiScaler/plugins/MFGUnlocker.asi) is in this game folder and XeFGModel is not set: on MFG Unlocker\'s '
                 'own model this build\'s shaders run on 7 of their 13 programs. Fix: set XeFGModel=default under [XeFG] in '
                 'OptiScaler.ini (a new Install writes it where it is unset).')
        native = ('MFG Unlocker (OptiScaler/plugins/MFGUnlocker.asi) is in this game folder: on the native route this build does not '
                  'accelerate the game\'s own XeSS frame generation beside it, which then runs without this build\'s shaders. Remove it '
                  'for 2×, or install on the OptiScaler route for 3×/4×.')
        self.assertEqual(c.setup_notes(self.root, 'opti'), [])
        self.logs(self.READY, unlocker=True)
        self.assertEqual(c.setup_notes(self.root, 'opti'), [unset])
        self.assertEqual(c.setup_notes(self.root, None), [unset])
        self.assertEqual(c.setup_notes(self.root, 'opti', installed=False), [])  # a new Install writes it
        self.assertEqual(c.setup_notes(self.root, 'native'), [native])
        self.assertEqual(c.setup_notes(self.root, 'native', installed=False), [native])
        self.logs(self.READY, model='auto', unlocker=True)
        self.assertIn('XeFGModel is auto', c.setup_notes(self.root, 'opti')[0])
        self.logs(self.READY, model='default', unlocker=True)
        self.assertEqual(c.setup_notes(self.root, 'opti'), [])
        # This build's own plugin is not MFG Unlocker; leftover RTXMFG files alone do not warn.
        self.logs(self.READY)
        (self.root/'OptiScaler/plugins/BC250-MFG.asi').write_bytes(b'addon')
        (self.root/'RTXMFG-Universal.status.json').write_text('{}')
        self.assertEqual(c.setup_notes(self.root, 'native'), [])
        # The last run already gives the advice: said once.
        self.logs(self.READY + self.COEXIST.format(module='MFGUnlocker.asi') + self.OWNER, 7, 1, unlocker=True)
        run = c.last_run(self.root, 'opti')
        self.assertEqual(c.setup_notes(self.root, 'opti', run=run), [])
        self.logs(self.READY + self.COEXIST.format(module='MFGUnlocker.asi') + self.SKIP + self.GENERATES, unlocker=True)
        self.assertEqual(c.setup_notes(self.root, 'native', run=c.last_run(self.root, 'native')), [])

    def test_key_rule_xefg_model(self):
        self.assertEqual(c.key_rule('XeFG.XeFGModel', 'default')[0], 'redundant')
        self.assertEqual(c.key_rule('XeFG.XeFGModel', 'xess')[0], 'installer')

    def test_report_has_no_home_path_or_user_name(self):
        home = Path('/srv/users/somebody')
        s = scan(root='/srv/users/somebody/Games/Library/Hero', mods=['dxgi.dll'])
        v = c.decide(s, data([], [], [WIKI]), ids())
        text = c.report(v, s, versions={'Kernel': '7.2.8', 'Proton': '/srv/users/somebody/.steam/root/compatibilitytools.d/GE-Proton11-7'},
                        run=dict(found=True, xefg=True, fg_input='upscaler', upscaler='DLSS', proxy='ready', accelerated=4,
                                 problems=['MFG proxy: C:\\users\\somebody\\x'], cause=None), package='freefg-0.9.0', home=home)
        self.assertNotIn('/srv/users/somebody', text)
        self.assertNotRegex(text, r'(?<!\w)somebody(?!\w)')
        self.assertIn('~/.steam', text)
        self.assertIn('"route": "opti"', text)
        self.assertIn('hero-win64-shipping.exe'.replace('hero', 'Hero').replace('win64', 'Win64').replace('shipping', 'Shipping'), text)

    def test_report_redacts_wine_paths(self):
        # OptiScaler's [E] lines show paths as the game sees them under Wine (Z:\\...), in any case.
        home = Path('/srv/users/somebody')
        s = scan(root='/srv/library/common/Hero')
        v = c.decide(s, data(), ids())
        problems = ['Z:\\srv\\library\\common\\Hero\\libxess_fg.dll not found', 'z:/SRV/users/somebody/x', 'Z:\\srv\\users\\somebody\\y']
        text = c.report(v, s, run=dict(found=True, xefg=False, fg_input=None, upscaler=None, proxy=None, accelerated=0, problems=problems,
                                       cause=None), home=home)
        self.assertNotIn('library', text.replace('<library>', ''))
        self.assertNotRegex(text.lower(), r'(?<!\w)somebody(?!\w)')
        self.assertIn('Z:<library>\\Hero\\libxess_fg.dll', text)
        self.assertIn('Z:~\\y', text)

    def test_check_lines(self):
        s = scan()
        v = c.decide(s, data([], [], [WIKI]), ids())
        lines = c.check_lines(v, s, c.wiki_advice(data([], [], [WIKI]), ids(), v), run=c.last_run(self.root))
        text = '\n'.join(lines)
        self.assertTrue(lines[0].startswith('Automatic, guided by the OptiScaler wiki: detected Unreal Engine UE4, DLSS'))
        self.assertIn('Plan: OptiFG input', text)
        self.assertIn('OptiScaler.ini Hotfix.ColorResourceBarrier=5', text)
        self.assertIn('Your steps:', text)
        self.assertIn('OptiScaler wiki (community reports): Hero (strong match)', text)
        self.assertIn('No logs yet', text)
        refused = c.decide(scan(upscalers=[]), data(), ids())
        self.assertIn('[no-input, hard, refused]', '\n'.join(c.check_lines(refused, scan(upscalers=[]))))


if __name__ == '__main__':
    unittest.main()
