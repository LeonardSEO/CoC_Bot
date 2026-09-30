import unittest
from unittest.mock import Mock, patch
from jev.client import Settings
from wall_upgrades import wall_level, wall_name
from test_upgrades import load_upgrader


class WallTests(unittest.TestCase):
    def bot(self):
        module,utils = load_upgrader()
        module.OCR_Handler = Mock()
        module.OCR_Handler.local_ocr.return_value = []
        module.render_text = lambda *args: 'select_row_template'
        module.configs.WALL_GROUP_UPGRADES = True
        bot = module.Upgrader(decisions=Mock(settings=Settings(mode='shadow')))
        return bot,module,utils

    def test_levels_require_explicit_unambiguous_wall_label(self):
        self.assertEqual(wall_level(['Wall','(Level 12)']),12)
        self.assertEqual(wall_level(['Wall x8','Level 13']),13)
        for text in ['Level 12','Wall x12','Wall Level 12 Wall Level 13','Wall Level 0']:
            self.assertIsNone(wall_level([text]))
        self.assertTrue(wall_name(['Wall']))
        self.assertFalse(wall_name(['Wall Breaker']))

    def test_wall_row_uses_recognized_select_row_action(self):
        bot,module,utils = self.bot()
        bot._wall_selected = True
        module.OCR_Handler.local_ocr.return_value = ['Wall (Level 12)','Select Row']
        utils.Frame_Handler.locate.return_value = (.4,.5)
        with patch('time.sleep'):
            self.assertTrue(bot._try_wall_row())
        self.assertEqual(bot._wall_before,12)
        self.assertTrue(bot._wall_group)
        self.assertEqual(utils.Frame_Handler.locate.call_count,2)
        utils.Input_Handler.click.assert_called_once_with(.05+.4*.8,.62+.5*.33)

    def test_missing_row_button_keeps_single_wall_without_extra_click(self):
        bot,module,utils = self.bot()
        bot._wall_selected = True
        module.OCR_Handler.local_ocr.return_value = ['Wall Level 12','Upgrade']
        self.assertFalse(bot._try_wall_row())
        utils.Input_Handler.click.assert_not_called()

    def test_row_button_disappearing_is_not_clicked(self):
        bot,module,utils = self.bot()
        bot._wall_selected = True
        module.OCR_Handler.local_ocr.return_value = ['Wall Level 12','Select Row']
        utils.Frame_Handler.locate.side_effect = [(.4,.5),(None,None)]
        self.assertFalse(bot._try_wall_row())
        utils.Input_Handler.click.assert_not_called()

    def test_non_wall_cannot_request_group_selection(self):
        bot,module,utils = self.bot()
        self.assertFalse(bot._try_wall_row())
        module.OCR_Handler.local_ocr.assert_not_called()
        utils.Input_Handler.click.assert_not_called()

    def test_group_setting_can_disable_select_row(self):
        bot,module,utils = self.bot()
        bot._wall_selected = True
        module.configs.WALL_GROUP_UPGRADES = False
        module.OCR_Handler.local_ocr.return_value = ['Wall Level 12','Select Row']
        self.assertFalse(bot._try_wall_row())
        utils.Input_Handler.click.assert_not_called()

    def test_wall_success_is_level_change_not_builder_change(self):
        for after,expected in [('Wall Level 13',True),('Wall Level 12',False),('Return Home',None)]:
            bot,module,utils = self.bot()
            bot._wall_selected = True
            bot._wall_before = 12
            module.OCR_Handler.local_ocr.return_value = [after]
            bot._verify_wall_upgrade()
            self.assertIs(bot._wall_success,expected)

    def test_group_confirmation_must_still_identify_wall(self):
        bot,module,utils = self.bot()
        bot._wall_group = True
        bot._jev_confirmation_name = Mock(return_value='cannon')
        self.assertFalse(bot._click_home_confirm())
        utils.Input_Handler.click.assert_not_called()

    def test_group_dialog_name_handles_count_and_parenthesized_level(self):
        for title in ['Wall x8 to level 13','Wall x8 (Level 13)','Wall (Level 13)','Upgrade Wall to Level 13?']:
            bot,module,utils = self.bot()
            utils.Frame_Handler.locate.return_value = (.2,.2)
            module.OCR_Handler.get_text.return_value = [title]
            self.assertEqual(bot._jev_confirmation_name(utils.Frame_Handler.get_frame.return_value),'wall')

    def test_red_total_group_price_is_rejected(self):
        bot,module,utils = self.bot()
        bot._wall_group = True
        bot._jev_confirmation_name = Mock(return_value='wall')
        utils.Frame_Handler.locate.return_value = (.5,.8)
        bot._confirmation_price_allowed = Mock(return_value=False)
        self.assertFalse(bot._click_home_confirm())
        bot._confirmation_price_allowed.assert_called_once()
        utils.Input_Handler.click.assert_not_called()

    def test_all_builders_busy_runs_only_configured_walls(self):
        for village in ('home','builder'):
            bot,module,utils = self.bot()
            setattr(module.configs, f'{village.upper()}_BASE_UPGRADE_PRIORITY', [['Cannon'],['Wall']])
            specified = Mock(return_value='wall')
            setattr(bot,f'{village}_specified_upgrade',specified)
            self.assertEqual(getattr(bot,f'{village}_upgrade')(walls_only=True),'wall')
            specified.assert_called_once_with(['Wall'])

    def test_wall_not_configured_is_not_forced_when_builders_busy(self):
        bot,module,utils = self.bot()
        module.configs.HOME_BASE_UPGRADE_PRIORITY = [['Cannon']]
        bot.home_specified_upgrade = Mock()
        self.assertIsNone(bot.home_upgrade(walls_only=True))
        bot.home_specified_upgrade.assert_not_called()

    def test_monitor_does_not_skip_wall_route_with_zero_builders(self):
        bot,module,utils = self.bot()
        module.MAX_UPGRADES_PER_CHECK = 10
        module.OPEN_HOME_BUILDERS = 0
        module.get_home_builders = Mock(return_value=0)
        utils.Task_Handler.excluded.return_value = True
        bot.home_upgrade = Mock(return_value='wall')
        bot._wall_success = None
        with patch('time.sleep'):
            bot.run_home_base(exclude_lab=True)
        bot.home_upgrade.assert_called_once_with(walls_only=True)

    def test_verified_wall_levels_allow_bounded_further_groups(self):
        bot,module,utils = self.bot()
        module.MAX_UPGRADES_PER_CHECK = 2
        module.OPEN_HOME_BUILDERS = 0
        module.get_home_builders = Mock(return_value=0)
        utils.Task_Handler.excluded.return_value = True
        bot.home_upgrade = Mock(return_value='wall')
        bot._wall_success = True
        with patch('time.sleep'):
            bot.run_home_base(exclude_lab=True)
        self.assertEqual(bot.home_upgrade.call_count,2)


if __name__=='__main__': unittest.main()
