import importlib.util
import sys
import time
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from jev.client import Settings
from jev.models import Choice
from jev.policy import DecisionService
from jev.upgrades import UpgradeCandidate, choose_upgrade


class UpgradeTests(unittest.TestCase):
    def service(self, mode='active', value='candidate_1'):
        client = Mock(settings=Settings(mode=mode), cost_usd=0, last_usage=None, last_model=None)
        client.decide.return_value = {'action': Choice(value, .95, {'candidate_0': .03, 'candidate_1': .97})}
        return DecisionService(client, emit=Mock()), client

    def test_only_affordable_highest_priority_and_discount_group(self):
        service, client = self.service()
        rows = [UpgradeCandidate('Laboratory', .5, .2, priority=0), UpgradeCandidate('Army Camp', .5, .3, priority=0), UpgradeCandidate('Wall', .5, .4, priority=1), UpgradeCandidate('Archer Queen', .5, .5, affordable=False, priority=0)]
        chosen = choose_upgrade(service, rows, rows[0], 'home_base', {'builders': 1})
        self.assertEqual(chosen.name, 'Army Camp')
        state = client.decide.call_args.args[0]
        self.assertEqual([r['name'] for r in state['candidates']], ['Laboratory', 'Army Camp'])
        rows[0] = UpgradeCandidate('Laboratory', .5, .2, priority=0, discounted=True)
        client.reset_mock()
        self.assertEqual(choose_upgrade(service, rows, rows[0], 'home_base', {}), rows[0])
        client.decide.assert_not_called()

    def test_shadow_and_low_quality_keep_original_location(self):
        rows = [UpgradeCandidate('Wall', .5, .2), UpgradeCandidate('Army Camp', .5, .3)]
        service, _ = self.service(mode='shadow')
        self.assertEqual(choose_upgrade(service, rows, rows[0], 'home_base', {}), rows[0])
        service, client = self.service()
        rows[1] = UpgradeCandidate('Unknown', .5, .3, quality=0)
        self.assertEqual(choose_upgrade(service, rows, rows[0], 'home_base', {}), rows[0])
        client.decide.assert_not_called()

    def test_stale_candidates_never_call(self):
        service, client = self.service()
        rows = [UpgradeCandidate('Wall', .5, .2, observed_at=0), UpgradeCandidate('Army Camp', .5, .3, observed_at=0)]
        self.assertEqual(choose_upgrade(service, rows, rows[0], 'home_base', {}), rows[0])
        client.decide.assert_not_called()


def load_upgrader():
    """Load real integration methods with device/GUI dependencies isolated."""
    utils = ModuleType('utils')
    utils.require_exit = lambda *a, **kw: lambda func: func
    utils.Asset_Manager = SimpleNamespace(upgrader_assets={'confirm': 'confirm', 'upgrade_name': 'upgrade_name'}, misc_assets={})
    utils.Frame_Handler = Mock()
    utils.Input_Handler = Mock()
    utils.Task_Handler = Mock()
    utils.Task_Handler.excluded.return_value = False
    utils.logger = Mock()
    config = ModuleType('configs')
    config.DEBUG = False
    config.WINDOW_DIMS = (1920, 1080)
    utils.click_with_timeout = lambda locator_func, **kw: all(value is not None for value in locator_func())
    spec = importlib.util.spec_from_file_location('upgrader_under_test', Path(__file__).resolve().parents[1] / 'src/upgrader.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'utils': utils, 'configs': config}):
        spec.loader.exec_module(module)
    return module, utils


class UpgradeIntegrationTests(unittest.TestCase):
    def test_candidate_ocr_failure_retains_original_choice(self):
        module, utils = load_upgrader()
        bot = module.Upgrader(decisions=Mock(settings=Settings(mode='active')))
        module.Cache_Manager = {'vocab': {'buildings/home-village': ['Army Camp', 'Laboratory']}}
        module.OCR_Handler = Mock()
        module.OCR_Handler.get_text.side_effect = RuntimeError('OCR unavailable')
        legacy = (.5, .4)
        self.assertEqual(bot._choose_jev_upgrade([legacy, (.5, .5)], legacy, .3, .8, 'home_base'), legacy)
        self.assertIsNone(bot._pending_jev_upgrade)

    def test_active_unchanged_choice_rechecks_row_after_api_wait(self):
        module, utils = load_upgrader()
        service = Mock(settings=Settings(mode='active'))
        service.choose.return_value = 'candidate_0'
        bot = module.Upgrader(decisions=service)
        module.Cache_Manager = {'vocab': {'heroes': []}}
        module.render_text = lambda name, *a, **kw: name
        module.check_color = lambda *a, **kw: False
        utils.Frame_Handler.locate.return_value = (None, None)
        legacy = (.5, .4, 'Laboratory')
        result = bot._choose_jev_upgrade([legacy, (.5, .5, 'Army Camp')], legacy, .3, .8, 'home_base')
        self.assertEqual(result, (None, None, None))
        self.assertIsNone(bot._pending_jev_upgrade)

    def test_existing_priority_locators_use_jev_choice(self):
        for prefix in ('home', 'home_lab', 'builder', 'builder_lab'):
            with self.subTest(prefix=prefix):
                module, utils = load_upgrader()
                client = Mock(settings=Settings(mode='active'), cost_usd=0, last_usage=None, last_model=None)
                client.decide.return_value = {'action': Choice('candidate_1', .95, {'candidate_0': .03, 'candidate_1': .97})}
                bot = module.Upgrader(decisions=DecisionService(client, emit=Mock()))
                bot.assets = {'green_tag': 'discount'}
                module.Cache_Manager = {'vocab': {'heroes': []}}
                module.OCR_Handler = Mock()
                module.render_text = lambda name, *a, **kw: name
                module.check_color = lambda *a, **kw: False
                module.get_home_builders = lambda *a, **kw: True
                module.click_with_timeout = Mock(return_value=True)
                utils.Frame_Handler.locate.return_value = (.4, .2)
                locs = [(.3, .4), (.3, .5)]
                utils.Frame_Handler.batch_locate.return_value = [[loc] for loc in locs] if prefix == 'home' else locs
                bot._get_suggested_upgrade_template = lambda: ('suggested', .2, .02)
                bot._get_upgrade_menu = lambda *a, **kw: (Mock(), .3, .15, .8, .9)
                bot._scroll_locate_upgrade = lambda func, *a, **kw: func()
                bot._get_upgrade_name = lambda *a: 'army camp'
                bot._click_home_confirm = Mock(return_value=True)
                bot._click_builder_confirm = Mock(return_value=True)
                module.configs.START_FROM_MENU_TOP = True
                with patch('numpy.random.shuffle'), patch('time.sleep'):
                    result = getattr(bot, f'{prefix}_specified_upgrade')(['Laboratory', 'Army Camp'])
                self.assertEqual(result.lower(), 'army camp')
                self.assertTrue(any(call.args[1] == .5 for call in utils.Input_Handler.click.call_args_list))
                client.decide.assert_called_once()

    def test_confirmation_must_match_fresh_chosen_name(self):
        module, utils = load_upgrader()
        service = Mock(settings=Settings(mode='active'))
        bot = module.Upgrader(decisions=service)
        bot._pending_jev_upgrade = {'name': 'Laboratory', 'context': 'home_base'}
        bot._jev_confirmation_name = Mock(return_value='army camp')
        self.assertFalse(bot._click_home_confirm())
        utils.Input_Handler.click.assert_not_called()
        bot._pending_jev_upgrade = {'name': 'Laboratory', 'context': 'home_base'}
        bot._jev_confirmation_name.return_value = 'laboratory'
        utils.Frame_Handler.locate.return_value = (.5, .8)
        self.assertTrue(bot._click_home_confirm())
        utils.Frame_Handler.get_frame.assert_called()

    def test_hero_exclusion_rechecked_before_confirmation(self):
        module, utils = load_upgrader()
        bot = module.Upgrader(decisions=Mock(settings=Settings(mode='active')))
        bot._pending_jev_upgrade = {'name': 'Archer Queen', 'context': 'home_base', 'hero': True}
        bot._jev_confirmation_name = Mock(return_value='archer queen')
        utils.Task_Handler.excluded.side_effect = lambda key, **kw: key == 'heroes'
        self.assertFalse(bot._click_home_confirm())
        utils.Input_Handler.click.assert_not_called()

    def test_confirmation_waits_for_matching_dialog_transition(self):
        module, utils = load_upgrader()
        bot = module.Upgrader(decisions=Mock(settings=Settings(mode='active')))
        bot._pending_jev_upgrade = {'name': 'Laboratory', 'context': 'builder_lab'}
        bot._jev_confirmation_name = Mock(side_effect=[None, None, 'laboratory'])
        bot._find_builder_confirm = Mock(return_value=(.5, .85))
        def poll(locator, **kw):
            for _ in range(3):
                x, y = locator()
                if x is not None and y is not None: return True
            return False
        module.click_with_timeout = poll
        self.assertTrue(bot._click_builder_confirm())
        self.assertEqual(bot._jev_confirmation_name.call_count, 3)
        self.assertIsNone(bot._pending_jev_upgrade)

    def test_confirmation_requires_dialog_anchor_and_exact_ocr(self):
        module, utils = load_upgrader()
        bot = module.Upgrader(decisions=Mock(settings=Settings(mode='active')))
        module.OCR_Handler = Mock()
        module.OCR_Handler.get_text.return_value = ['Laborat0ry 12']
        utils.Frame_Handler.locate.return_value = (None, None)
        bot._pending_jev_upgrade = {'name': 'Laboratory', 'context': 'builder_lab'}
        self.assertFalse(bot._verify_jev_confirmation())
        module.OCR_Handler.get_text.assert_not_called()
        utils.Frame_Handler.locate.return_value = (.2, .2)
        self.assertFalse(bot._verify_jev_confirmation())
        module.OCR_Handler.get_text.return_value = ['Laboratory to level 12']
        self.assertTrue(bot._verify_jev_confirmation())

    def test_off_and_shadow_preserve_original_discount_alignment(self):
        for mode in ('off', 'shadow'):
            with self.subTest(mode=mode):
                module, utils = load_upgrader()
                bot = module.Upgrader(decisions=Mock(settings=Settings(mode=mode)))
                bot.assets = {'green_tag': 'discount'}
                module.Cache_Manager = {'vocab': {'heroes': []}}
                module.render_text = lambda name, *a, **kw: name
                module.check_color = lambda *a, **kw: False
                module.get_home_builders = lambda *a, **kw: True
                utils.Frame_Handler.locate.side_effect = lambda asset, *a, **kw: (96, 10) if asset == 'discount' else (.4, .2)
                utils.Frame_Handler.batch_locate.return_value = [[(.35, .4)], [(.3, .5)]]
                bot._get_suggested_upgrade_template = lambda: ('suggested', .2, .02)
                bot._get_upgrade_menu = lambda *a, **kw: (Mock(), .3, .15, .8, .9)
                bot._scroll_locate_upgrade = lambda func, *a, **kw: func()
                bot._get_upgrade_name = lambda *a: 'army camp'
                bot._click_upgrade = Mock(return_value=True)
                bot._click_home_confirm = Mock(return_value=True)
                bot._choose_jev_upgrade = lambda locations, legacy, *a, **kw: legacy
                module.configs.START_FROM_MENU_TOP = True
                with patch('numpy.random.shuffle'), patch('time.sleep'):
                    bot.home_specified_upgrade(['Laboratory', 'Army Camp'])
                self.assertTrue(any(call.args[1] == .5 for call in utils.Input_Handler.click.call_args_list))

    def test_shadow_confirmation_has_no_extra_observation_or_inputs(self):
        module, utils = load_upgrader()
        bot = module.Upgrader(decisions=Mock(settings=Settings(mode='shadow')))
        module.click_with_timeout = Mock(return_value=True)
        self.assertTrue(bot._click_home_confirm())
        utils.Frame_Handler.get_frame.assert_not_called()


if __name__ == '__main__':
    unittest.main()
