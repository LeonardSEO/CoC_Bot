"""Regression cases for the user's attack timeout and red upgrade prices."""
import unittest
from unittest.mock import Mock, patch
import numpy as np
import test_attacks as attack_tests
from test_upgrades import load_upgrader
from automation_safety import AutomationStopped
from jev.client import Settings
from upgrade_prices import price_status


def row(colour=(255,255,255), price=True):
    image = np.full((50,300,3), (45,45,45), dtype=np.uint8)
    image[10:20,10:80] = (255,255,255)  # Name is white even when cost is red.
    if price:
        image[25:35,220:260] = colour
    return image


class PriceTests(unittest.TestCase):
    def test_red_and_antialiased_variants_are_unaffordable(self):
        for colour in [(255,136,127),(240,110,105),(190,70,65),(255,90,85)]:
            with self.subTest(colour=colour):
                self.assertIs(price_status(row(colour)), False)

    def test_white_price_is_distinct_from_unknown(self):
        self.assertIs(price_status(row()), True)
        self.assertIsNone(price_status(row(price=False)))
        self.assertIsNone(price_status(row((100,100,100))))

    def test_red_name_or_icon_is_not_a_red_price(self):
        image = row()
        image[10:20,10:80] = (255,90,85)
        self.assertIs(price_status(image), True)

    def test_wrong_image_type_is_not_assumed_affordable(self):
        for image in [np.zeros((2,2)), np.zeros((0,3,3))]:
            with self.assertRaises(ValueError): price_status(image)

    def test_menu_rejects_offset_red_price_outside_old_palette(self):
        module, utils = load_upgrader()
        bot = module.Upgrader(decisions=Mock(settings=Settings(mode='shadow')))
        utils.Frame_Handler.crop.return_value = row((240,110,105))
        self.assertFalse(bot._row_price_allowed(.3,.4,.8))
        utils.Input_Handler.click.assert_not_called()

    def test_single_red_or_unknown_candidate_never_calls_jev_or_returns_click(self):
        for mode in ('off','shadow','active'):
            for image in [row((240,110,105)),row(price=False)]:
                module, utils = load_upgrader()
                service = Mock(settings=Settings(mode=mode))
                bot = module.Upgrader(decisions=service)
                utils.Frame_Handler.crop.return_value = image
                self.assertEqual(bot._choose_jev_upgrade([(.5,.4)],(.5,.4),.3,.8,'home_base'),(None,None))
                service.choose.assert_not_called()
                utils.Input_Handler.click.assert_not_called()

    def test_unknown_cost_and_balance_are_not_invented_and_duplicates_removed(self):
        module, utils = load_upgrader()
        service = Mock(settings=Settings(mode='shadow'))
        service.choose.return_value = 'candidate_0'
        bot = module.Upgrader(decisions=service)
        module.Cache_Manager = {'vocab':{'heroes':[]}}
        result = bot._choose_jev_upgrade([(.5,.4,'Laboratory'),(.5,.4005,'Laboratory'),(.5,.5,'Army Camp')],(.5,.4,'Laboratory'),.3,.8,'home_base')
        self.assertEqual(result, (.5,.4,'Laboratory'))
        candidates = service.choose.call_args.args[1].state['candidates']
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(c['cost'] is None and c['resource_balance'] is None for c in candidates))
        self.assertTrue(all(c['affordability_source']=='fresh_menu_price_colour' for c in candidates))

    def test_confirmation_uses_fresh_red_guard_in_all_modes(self):
        for mode in ('off','shadow','active'):
            module, utils = load_upgrader()
            bot = module.Upgrader(decisions=Mock(settings=Settings(mode=mode)))
            utils.Frame_Handler.locate.return_value = (.5,.8)
            utils.Frame_Handler.crop.return_value = row((240,110,105))
            self.assertFalse(bot._click_home_confirm())
            utils.Frame_Handler.get_frame.assert_called_once_with(grayscale=False)
            utils.Input_Handler.click.assert_not_called()

    def test_failed_wall_result_is_not_repeated_in_same_cycle(self):
        module, utils = load_upgrader()
        bot = module.Upgrader(decisions=Mock(settings=Settings(mode='shadow')))
        module.MAX_UPGRADES_PER_CHECK = 10
        module.OPEN_HOME_BUILDERS = 0
        module.get_home_builders = Mock(side_effect=[1,1])
        utils.Task_Handler.excluded.return_value = True
        bot.home_upgrade = Mock(return_value='wall')
        with patch('time.sleep'):
            bot.run_home_base(exclude_lab=True)
        bot.home_upgrade.assert_called_once()
        bot.decisions.record.assert_any_call('upgrade_cycle_stopped',reason='wall_result_unverified')


class BattleTests(unittest.TestCase):
    def bot(self):
        bot, module, utils = attack_tests.AttackIntegrationTests().bot(mode='shadow')
        module.AutomationStopped = AutomationStopped
        module.running = Mock(return_value=True)
        module.get_home_builders = Mock(return_value=False)
        bot.assets = {'return_home':'return_home'}
        return bot,module,utils

    def test_attack_finishes_via_result_and_confirmed_village_without_restart(self):
        bot,module,utils = self.bot()
        module.get_home_builders.side_effect = [False,False,True]
        utils.Frame_Handler.locate.side_effect = [(None,None),(.5,.9),(.5,.9)]
        with patch('time.sleep'):
            self.assertTrue(bot._wait_for_home_battle())
        utils.Input_Handler.click.assert_called_once_with(.5,.9)
        utils.start_coc.assert_not_called()
        utils.stop_coc.assert_not_called()
        self.assertEqual(bot.decisions.record.call_args.kwargs['completion'],'returned_to_village')

    def test_result_button_disappearing_before_click_is_not_clicked(self):
        bot,module,utils = self.bot()
        module.get_home_builders.side_effect = [False,True]
        utils.Frame_Handler.locate.side_effect = [(.5,.9),(None,None)]
        with patch('time.sleep'):
            self.assertTrue(bot._wait_for_home_battle())
        utils.Input_Handler.click.assert_not_called()

    def test_ongoing_attack_waits_beyond_old_startup_deadline(self):
        bot,module,utils = self.bot()
        module.get_home_builders.side_effect = [False,False,True]
        utils.Frame_Handler.locate.return_value = (None,None)
        clock = [0]
        with patch('time.monotonic',side_effect=lambda:clock[0]), patch('time.sleep',side_effect=lambda _:clock.__setitem__(0,clock[0]+40)):
            self.assertTrue(bot._wait_for_home_battle(timeout=240))
        self.assertEqual(clock[0],80)
        utils.Input_Handler.click.assert_not_called()
        utils.start_coc.assert_not_called()

    def test_unknown_result_times_out_without_blind_inputs(self):
        bot,module,utils = self.bot()
        utils.Frame_Handler.locate.return_value = (None,None)
        clock = [0]
        with patch('time.monotonic',side_effect=lambda:clock[0]), patch('time.sleep',side_effect=lambda _:clock.__setitem__(0,clock[0]+1)), self.assertRaises(AutomationStopped):
            bot._wait_for_home_battle(timeout=3)
        self.assertEqual(clock[0],3)
        utils.Input_Handler.click.assert_not_called()
        utils.start_coc.assert_not_called()
        self.assertEqual(bot.decisions.record.call_args.kwargs['completion'],'result_timeout')

    def test_deployment_calls_battle_wait_instead_of_startup(self):
        bot,module,utils = self.bot()
        bot.detect_troop_positions = Mock(return_value=([],[],[],[],0))
        bot._wait_for_home_battle = Mock(return_value=True)
        bot.complete_normal_attack()
        bot._wait_for_home_battle.assert_called_once()
        utils.start_coc.assert_not_called()
        utils.stop_coc.assert_not_called()

    def test_pause_stops_wait_without_clicks(self):
        bot,module,utils = self.bot()
        module.running.return_value = False
        with self.assertRaises(AutomationStopped): bot._wait_for_home_battle()
        utils.Frame_Handler.get_frame.assert_not_called()
        utils.Input_Handler.click.assert_not_called()


if __name__ == '__main__': unittest.main()
