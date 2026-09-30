import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from jev.attacks import DeploymentPlan, choose_deployment, select_base
from jev.client import Settings
from jev.models import Choice
from jev.observations import ScreenObserver, parse_amount
from jev.policy import DecisionService, Observation


def scout(signature='a'):
    return Observation({'loot': {'gold': 500000, 'elixir': 500000, 'dark_elixir': None}, 'search_cost': 1000, 'signature': signature, 'next_position': [.9, .7]}, quality=1)


class AttackTests(unittest.TestCase):
    def service(self, mode='active', **kw):
        client = Mock(settings=Settings(mode=mode, base_selection=True, deployment=True, **kw), cost_usd=0, last_usage=None, last_model=None)
        client.decide.return_value = {'action': Choice('skip', .99, {'attack': .01, 'skip': .99})}
        return DecisionService(client, emit=Mock()), client

    def test_parse_resources_rejects_ambiguous_ocr(self):
        for raw, expected in [('1 234 567', 1234567), ('1,234', 1234), ('12.345', 12345), ('9000', 9000), ('12.5K', None), ('1O00', None), ('', None), ('-1', None), ('12 34', None)]:
            self.assertEqual(parse_amount(raw), expected)

    def test_shadow_observes_once_without_skipping(self):
        service, client = self.service(mode='shadow')
        observer = Mock()
        observer.scout.return_value = scout()
        click = Mock()
        select_base(service, observer, Mock(), click)
        click.assert_not_called()
        observer.scout.assert_called_once()
        client.decide.assert_called_once()

    def test_skip_limit_and_fresh_revalidation(self):
        service, client = self.service(max_skips=2)
        observer = Mock()
        observer.scout.side_effect = [scout('a'), scout('a'), scout('b'), scout('b'), scout('c')]
        click = Mock()
        select_base(service, observer, Mock(), click, sleep=lambda _: None)
        self.assertEqual(click.call_count, 2)
        self.assertEqual(client.decide.call_count, 2)

    def test_changed_base_during_api_call_never_clicks(self):
        service, _ = self.service()
        observer = Mock()
        observer.scout.side_effect = [scout('a'), scout('b')]
        click = Mock()
        select_base(service, observer, Mock(), click)
        click.assert_not_called()

    def test_search_deadline_prevents_click_after_slow_api(self):
        service, client = self.service(max_search_seconds=1)
        observer = Mock()
        observer.scout.return_value = scout()
        clock = [100]
        def slow(*args):
            clock[0] += 2
            return {'action': Choice('skip', .99, {'attack': .01, 'skip': .99})}
        client.decide.side_effect = slow
        click = Mock()
        with patch('jev.attacks.time.monotonic', side_effect=lambda: clock[0]):
            select_base(service, observer, Mock(), click)
        click.assert_not_called()

    def test_search_deadline_rechecked_after_slow_revalidation(self):
        service, _ = self.service(max_search_seconds=1)
        observer = Mock()
        clock = [100]
        calls = [0]
        def observe(_):
            calls[0] += 1
            if calls[0] == 2: clock[0] += 2
            return scout()
        observer.scout.side_effect = observe
        click = Mock()
        with patch('jev.attacks.time.monotonic', side_effect=lambda: clock[0]):
            select_base(service, observer, Mock(), click)
        click.assert_not_called()

    def test_missing_vision_or_bad_ocr_does_not_call(self):
        service, client = self.service()
        observer = Mock()
        observer.scout.return_value = None
        click = Mock()
        select_base(service, observer, Mock(), click)
        client.decide.assert_not_called()
        click.assert_not_called()

    def test_only_executable_deployment_plans_and_enabled_cards(self):
        service, client = self.service()
        client.decide.return_value = {'action': Choice('distributed', .99, {'legacy': .01, 'concentrated': 0, 'distributed': .99})}
        plans = [DeploymentPlan('concentrated', ((.3, .7),)), DeploymentPlan('distributed', ((.3, .7), (.7, .7)))]
        obs = Observation({'village': 'home'}, quality=1)
        result = choose_deployment(service, obs, plans, [{'type': 'troop', 'enabled': True}, {'type': 'clan', 'enabled': False}])
        self.assertEqual(result.name, 'distributed')
        state = client.decide.call_args.args[0]
        self.assertEqual(state['cards'], [{'type': 'troop', 'enabled': True}])

    def test_invalid_points_and_shadow_keep_legacy(self):
        with self.assertRaises(ValueError):
            DeploymentPlan('distributed', ((1.2, .7),))
        service, client = self.service(mode='shadow')
        client.decide.return_value = {'action': Choice('concentrated', .99, {'legacy': .01, 'concentrated': .99})}
        result = choose_deployment(service, Observation({}, quality=1), [DeploymentPlan('concentrated', ((.3, .7),))], [{'type': 'hero', 'enabled': True}])
        self.assertEqual(result.name, 'legacy')


def load_attacker():
    import importlib.util
    from types import ModuleType, SimpleNamespace
    utils = ModuleType('utils')
    utils.require_exit = lambda *a, **kw: lambda func: func
    utils.Asset_Manager = SimpleNamespace(attacker_assets={}, misc_assets={})
    utils.Frame_Handler = Mock()
    utils.Input_Handler = Mock()
    utils.logger = Mock()
    config = ModuleType('configs')
    config.TROOP_DEPLOY_TIME = .001
    config.ATTACK_SLOT_RANGE = (1, 1)
    config.EXCLUDE_CLAN_TROOPS = True
    spec = importlib.util.spec_from_file_location('attacker_under_test', Path(__file__).resolve().parents[1] / 'src/attacker.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'utils': utils, 'configs': config}):
        spec.loader.exec_module(module)
    return module, utils


class AttackIntegrationTests(unittest.TestCase):
    def bot(self, mode='active'):
        module, utils = load_attacker()
        settings = Settings(mode=mode, deployment=True, base_selection=True)
        service = Mock(settings=settings)
        bot = module.Attacker(decisions=service, observer=Mock())
        return bot, module, utils

    def test_custom_plan_respects_slots_and_never_holds_legacy_point(self):
        bot, module, utils = self.bot()
        bot._choose_deployment_plan = Mock(return_value=DeploymentPlan('distributed', ((.3, .7), (.7, .7))))
        bot.observer.points_valid.return_value = True
        bot.deploy_troops([.1, .2, .3], [0, 1, 0], ['clan', 'hero', 'troop'], [1, 1, -1])
        utils.Input_Handler.click.assert_any_call(.2, .9)
        utils.Input_Handler.click.assert_any_call(.3, .7)
        self.assertFalse(any(call.args == (.1, .9) or call.args == (.3, .9) for call in utils.Input_Handler.click.call_args_list))
        utils.Input_Handler.down.assert_not_called()

    def test_changed_legal_area_falls_back_before_deployment(self):
        bot, module, utils = self.bot()
        bot._choose_deployment_plan = Mock(return_value=DeploymentPlan('concentrated', ((.3, .7),)))
        bot.observer.points_valid.return_value = False
        bot.deploy_troops([.2], [1], ['hero'], [1])
        utils.Input_Handler.click.assert_any_call(.5, .8)
        self.assertFalse(any(call.args == (.3, .7) for call in utils.Input_Handler.click.call_args_list))

    def test_touch_pointers_are_released_on_exception(self):
        bot, module, utils = self.bot(mode='off')
        bot._choose_deployment_plan = Mock(return_value=DeploymentPlan('legacy', ((.5, .8),)))
        utils.Input_Handler.click.side_effect = [None, RuntimeError('device disconnected')]
        with self.assertRaises(RuntimeError):
            bot.deploy_troops([.2], [1], ['hero'], [1])
        utils.Input_Handler.up.assert_any_call(pointer=1)

    def test_no_enabled_slots_means_no_touch_events(self):
        bot, module, utils = self.bot(mode='off')
        bot.deploy_troops([.1, .2], [0, 0], ['clan', 'troop'], [1, -1])
        utils.Input_Handler.click.assert_not_called()
        utils.Input_Handler.down.assert_not_called()

    def test_builder_base_honors_attack_slot_range(self):
        bot, module, utils = self.bot(mode='off')
        bot.deploy_troops = Mock()
        module.start_coc = Mock()
        bot.complete_builder_attack()
        slots = bot.deploy_troops.call_args.kwargs['available_slots']
        self.assertEqual(list(slots), [0, 1] + [0]*9)


class ScreenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import cv2
        except ImportError:
            raise unittest.SkipTest('Run with the bot .venv for OpenCV screenshot tests')

    def test_unvalidated_profile_cannot_enable_vision(self):
        observer = ScreenObserver({'validated': False}, root=Path('.'), ocr=Mock())
        self.assertIsNone(observer.scout(None))
        self.assertIsNone(observer.deployment(None, 'home'))

    def test_screenshot_templates_ocr_and_boundary_masks(self):
        # Synthetic regression fixture, explicitly not live-game calibration.
        import cv2
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rng = np.random.default_rng(42)
            frame = np.zeros((200, 300, 3), dtype=np.uint8)
            anchor = rng.integers(0, 255, (12, 20, 3), dtype=np.uint8)
            frame[15:27, 10:30] = anchor
            frame[130:142, 270:290] = anchor
            cv2.imwrite(str(root / 'anchor.png'), cv2.cvtColor(anchor, cv2.COLOR_RGB2BGR))
            mask = np.zeros((200, 300), dtype=np.uint8)
            mask[35:155, 20:260] = 255
            cv2.imwrite(str(root / 'playable.png'), mask)
            cv2.rectangle(frame, (80, 45), (210, 100), (255, 0, 0), 3)
            profile = {'version': 1, 'validated': True, 'resolution': [300, 200],
                'templates': {'scouting': {'path': 'anchor.png', 'region': [0, 0, .2, .2]}, 'next': {'path': 'anchor.png', 'region': [.85, .6, 1, .8]}},
                'loot_regions': {'gold': [0, 0, .1, .1], 'elixir': [0, 0, .1, .1], 'search_cost': [0, 0, .1, .1]},
                'base_region': [.2, .2, .8, .6],
                'deployment': {'home': {'anchor': {'path': 'anchor.png', 'region': [0, 0, .2, .2]}, 'playable_mask': 'playable.png'}}}
            observer = ScreenObserver(profile, root=root, ocr=lambda _: ['123 456'])
            result = observer.scout(frame)
            self.assertEqual(result.state['loot']['gold'], 123456)
            self.assertIsNone(result.state['loot']['dark_elixir'])
            result, plans = observer.deployment(frame, 'home')
            self.assertEqual({p.name for p in plans}, {'concentrated', 'distributed'})
            for plan in plans:
                self.assertTrue(observer.points_valid(frame, 'home', plan.points))
            self.assertFalse(observer.points_valid(frame, 'home', ((.5, .35),)))
            changed = frame.copy()
            changed[15:27, 10:30] = 0
            self.assertIsNone(observer.scout(changed))
            self.assertIsNone(observer.deployment(changed, 'home'))


if __name__ == '__main__':
    unittest.main()
