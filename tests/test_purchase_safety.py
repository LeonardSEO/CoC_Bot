import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from PIL import Image
from automation_safety import AutomationStopped
from purchase_safety import purchase_reason, reject_purchase_text
from test_automation_safety import load

ROOT = Path(__file__).resolve().parents[1]


class PurchaseTests(unittest.TestCase):
    def test_money_shop_and_topup_prompts_are_blocked(self):
        for text in ['€ 4,99','4.99 $','Google Play','Shop','Winkel','Buy Gems','Not enough resources','Purchase confirmed','Betalen']:
            with self.subTest(text=text), self.assertRaises(AutomationStopped):
                reject_purchase_text([text])

    def test_normal_upgrade_and_battle_labels_remain_allowed(self):
        for text in ['Confirm upgrade 100000','End Battle','Return Home','Laboratory level 12']:
            self.assertIsNone(purchase_reason([text]))
            reject_purchase_text([text])

    def test_game_footer_and_resource_icon_ocr_do_not_fake_payment(self):
        for texts in [('SHOP',),('Winkel',),('£24','Wall Level 12'),('SHOP','With the Gold Pass you could save up to:','300000')]:
            self.assertIsNone(purchase_reason(texts,trusted_game_screen=True))
        self.assertEqual(purchase_reason(['SHOP']), 'shop_label')

    def test_real_prices_and_purchase_actions_still_block_recognized_game(self):
        for texts in [('SHOP','€4,99'),('£ 4.99',),('9.99 $',),('USD 5',),('Buy Gems',),('Google Play',),('Missing Resources',)]:
            self.assertIsNotNone(purchase_reason(texts,trusted_game_screen=True))

    def test_trusted_village_does_not_stop_on_footer_or_integer_resource_icon(self):
        handler,ns = self.handler(village=True,texts=('SHOP','£24','Suggested upgrades'))
        handler._guard_purchase(.5,.4)
        ns['OCR_Handler'].local_ocr.assert_called_once()

    def test_unknown_shop_screen_is_still_blocked(self):
        handler,ns = self.handler(texts=('SHOP',))
        with self.assertRaises(AutomationStopped): handler._guard_purchase(.5,.8)

    def test_empty_ocr_fails_closed(self):
        with self.assertRaises(AutomationStopped): reject_purchase_text([])

    def handler(self, village=False, texts=('End Battle',), package='com.supercell.clashofclans'):
        device = Mock()
        device.app_current.return_value = SimpleNamespace(package=package)
        namespace = {'ADB_Manager':SimpleNamespace(adbutils_device=device),'Frame_Handler':Mock(),
                     'get_home_builders':Mock(return_value=village),'get_builder_builders':Mock(return_value=False),
                     'OCR_Handler':Mock(), 'Asset_Manager':SimpleNamespace(upgrader_assets={'confirm':'confirm'})}
        namespace['Frame_Handler'].locate.return_value = (None,None)
        namespace['OCR_Handler'].local_ocr.return_value = list(texts)
        return load({'Input_Handler'},namespace)['Input_Handler'], namespace

    def test_village_coordinates_do_not_define_a_payment_screen(self):
        handler,ns = self.handler(village=True)
        for point in [(.95,.9),(.92,.1),(-.05,-.1)]:
            handler._guard_purchase(*point)
        ns['OCR_Handler'].get_text.assert_not_called()

    def test_menu_cleanup_does_not_tap_shop_corner_or_back_from_plain_village(self):
        handler,ns = self.handler(village=True,texts=('Attack!', 'SHOP'))
        handler.click = Mock()
        handler.click_exit(n=4)
        handler.click.assert_not_called()
        ns['ADB_Manager'].adbutils_device.keyevent.assert_not_called()

    def test_menu_cleanup_backs_out_once_then_stops_at_village(self):
        handler,ns = self.handler(village=True)
        ns['OCR_Handler'].local_ocr.side_effect = [['Suggested upgrades:','Wall'],['Attack!','SHOP']]
        handler.click = Mock()
        with patch('time.sleep'):
            handler.click_exit(n=4)
        handler.click.assert_not_called()
        ns['ADB_Manager'].adbutils_device.keyevent.assert_called_once_with(4)

    def test_menu_cleanup_cannot_send_inputs_to_payment_overlay(self):
        handler,ns = self.handler(package='com.android.vending')
        with self.assertRaises(AutomationStopped): handler.click_exit(n=4)
        ns['ADB_Manager'].adbutils_device.keyevent.assert_not_called()

    def test_shop_modal_with_village_hud_is_blocked(self):
        handler,ns = self.handler(village=True,texts=('Shop','€4.99'))
        with self.assertRaises(AutomationStopped): handler._guard_purchase(.5,.8)
        ns['OCR_Handler'].local_ocr.assert_called_once()
        ns['OCR_Handler'].external_ocr.assert_not_called()

    def test_anchored_upgrade_dialog_does_not_scan_village_shop_footer(self):
        handler,ns = self.handler(texts=('Upgrade Wall to Level 13?', 'Confirm'))
        ns['Frame_Handler'].locate.return_value = (.5,.8)
        handler._guard_purchase(.5,.8)
        ns['Frame_Handler'].crop.assert_called_once()
        ns['OCR_Handler'].local_ocr.assert_called_once_with(ns['Frame_Handler'].crop.return_value)

    def test_payment_overlay_in_another_package_is_blocked(self):
        handler,ns = self.handler(package='com.android.vending')
        with self.assertRaises(AutomationStopped): handler._guard_purchase(.5,.8)
        ns['Frame_Handler'].get_frame.assert_not_called()

    def test_local_ocr_failure_blocks_input(self):
        handler,ns = self.handler()
        ns['OCR_Handler'].local_ocr.side_effect = RuntimeError('unavailable')
        with self.assertRaises(AutomationStopped): handler.down(.5,.8)

    def test_guard_prevents_every_gesture_from_reaching_touch_server(self):
        handler,ns = self.handler()
        handler._guard_purchase = Mock(side_effect=AutomationStopped('shop'))
        handler._to_raw = Mock(return_value=(1,1))
        builder = Mock()
        with patch('pyminitouch.CommandBuilder',return_value=builder):
            for method,args in [('click',(.5,.8)),('down',(.5,.8)),('multi_click',(.4,.8,.5,.8)),('swipe',(.3,.3,.5,.5)),('zoom',())]:
                with self.subTest(method=method), self.assertRaises(AutomationStopped):
                    getattr(handler,method)(*args)
        builder.down.assert_not_called()
        builder.publish.assert_not_called()

    def test_normal_battle_input_uses_only_local_ocr(self):
        handler,ns = self.handler()
        handler._guard_purchase(.5,.8)
        ns['OCR_Handler'].local_ocr.assert_called_once()
        ns['OCR_Handler'].get_text.assert_not_called()


class InventoryTests(unittest.TestCase):
    def test_scan_records_version_ocr_and_templates_without_inputs(self):
        spec = importlib.util.spec_from_file_location('scan_ui',ROOT/'scripts/scan_current_ui.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        device = Mock()
        device.shell.return_value = 'versionCode=123 versionName=18.0'
        device.screenshot.return_value = Image.new('RGB',(1920,1080),'black')
        device.app_current.return_value = SimpleNamespace(package='com.supercell.clashofclans')
        ocr = Mock(return_value=['Town Hall','Shop'])
        with tempfile.TemporaryDirectory() as directory:
            report = module.scan(device,directory,ocr)
            self.assertEqual(report['app_version'],{'versionCode':'123','versionName':'18.0'})
            self.assertEqual(report['inputs_sent'],0)
            self.assertEqual(report['model_requests'],0)
            self.assertFalse(report['templates_updated'])
            self.assertTrue(report['observations'][0]['template_scores'])
            self.assertTrue((Path(directory)/'report.json').exists())
            self.assertEqual((Path(directory)/'report.json').stat().st_mode & 0o777,0o600)
        device.shell.assert_called_once_with(['dumpsys','package','com.supercell.clashofclans'])
        self.assertEqual(len(device.mock_calls),3)
        device.screenshot.assert_called_once_with(error_ok=False)


if __name__=='__main__': unittest.main()
