"""Reproduce failed startup/HUD detection without sending device inputs."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from automation_safety import AutomationStopped, raw_touch, validate_frame


def load(names, namespace):
    tree = ast.parse((ROOT / 'src/utils.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    namespace.update(AutomationStopped=AutomationStopped, raw_touch=raw_touch, validate_frame=validate_frame)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'utils.py', 'exec'), namespace)
    return namespace


class StartupTests(unittest.TestCase):
    def context(self, home=False, builder=False):
        return load({'start_coc', 'to_home_base', 'to_builder_base'}, {
            'Emulator_Manager': Mock(), 'running': Mock(return_value=True),
            'ADB_Manager': SimpleNamespace(adbutils_device=Mock()),
            'get_home_builders': Mock(return_value=home),
            'get_builder_builders': Mock(return_value=builder),
            'Input_Handler': Mock(), 'Frame_Handler': Mock(), 'TEMP_CACHE': {},
            'stop_coc': Mock(), 'to_system_home': Mock(), 'update_coc': Mock(),
            'logger': Mock()})

    def test_both_huds_false_never_reports_started_or_clicks(self):
        context = self.context()
        with patch('time.time', side_effect=[0,0,1,4]), patch('time.sleep'), self.assertRaises(AutomationStopped):
            context['start_coc'](timeout=2, detailed=True)
        context['get_builder_builders'].assert_called()
        self.assertEqual(context['Input_Handler'].mock_calls, [])
        context['update_coc'].assert_not_called()
        context['stop_coc'].assert_not_called()
        context['to_system_home'].assert_not_called()
        self.assertNotIn('location', context['TEMP_CACHE'])
        self.assertNotIn(unittest.mock.call.info('CoC started'), context['logger'].mock_calls)

    def test_confirmed_village_can_start_without_extra_inputs(self):
        for home,builder,expected in [(True,False,'home_base'),(False,True,'builder_base')]:
            context = self.context(home,builder)
            self.assertEqual(context['start_coc'](detailed=True), (True,'running'))
            self.assertEqual(context['TEMP_CACHE']['location'], expected)
            self.assertEqual(context['Input_Handler'].mock_calls, [])

    def test_stale_cached_location_does_not_authorize_navigation(self):
        for function in ('to_home_base','to_builder_base'):
            context = self.context()
            context['TEMP_CACHE']['location'] = function.removeprefix('to_')
            with self.assertRaises(AutomationStopped): context[function](ref_cache=True)
            self.assertEqual(context['Input_Handler'].mock_calls, [])

    def test_safety_exception_bypasses_legacy_cleanup_clicks(self):
        namespace = load({'require_exit'}, {'Input_Handler':Mock()})
        @namespace['require_exit']()
        def failure(): raise AutomationStopped('unreadable')
        with self.assertRaises(AutomationStopped): failure()
        namespace['Input_Handler'].click_exit.assert_not_called()

    def test_worker_does_not_retry_or_send_home_key_after_safety_stop(self):
        tree = ast.parse((ROOT/'src/coc_bot.py').read_text())
        cls = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CoC_Bot')
        namespace = {'AutomationStopped':AutomationStopped,'online':Mock(return_value=True),
                     'running':Mock(return_value=True),'start_coc':Mock(side_effect=AutomationStopped('wrong resolution')),
                     'logger':Mock(),'update_status':Mock(),'stop_coc':Mock()}
        exec(compile(ast.Module(body=[cls],type_ignores=[]),'coc_bot.py','exec'),namespace)
        obj = namespace['CoC_Bot'].__new__(namespace['CoC_Bot'])
        obj.run()
        namespace['start_coc'].assert_called_once_with(detailed=True)
        namespace['stop_coc'].assert_not_called()
        namespace['update_status'].assert_called_once_with('error')


class FrameTests(unittest.TestCase):
    def test_mismatch_cannot_be_silently_resized(self):
        for shape in [(720,1280,3),(1080,1920,3)]:
            frame = np.ones(shape, dtype=np.uint8)
            if shape[:2] == (1080,1920): validate_frame(frame, (1920,1080))
            else:
                with self.assertRaises(AutomationStopped): validate_frame(frame, (1920,1080))

    def test_black_and_malformed_frames_stop(self):
        for frame in (np.zeros((1080,1920,3),dtype=np.uint8),np.ones((1080,1920),dtype=np.uint8)):
            with self.assertRaises(AutomationStopped): validate_frame(frame,(1920,1080))

    def test_capture_uses_strict_screenshot_and_never_framebuffer(self):
        device = Mock()
        device.screenshot.return_value = np.ones((1080,1920,3),dtype=np.uint8)
        namespace = load({'Frame_Handler'}, {'ADB_Manager':SimpleNamespace(adbutils_device=device),'WINDOW_DIMS':(1920,1080)})
        frame = namespace['Frame_Handler'].get_frame(grayscale=False)
        self.assertEqual(frame.shape,(1080,1920,3))
        device.screenshot.assert_called_once_with(error_ok=False)
        device.framebuffer.assert_not_called()

    def test_failed_capture_cannot_use_black_sdk_fallback_or_old_frame(self):
        device = Mock()
        device.screenshot.side_effect = RuntimeError('bad PNG')
        namespace = load({'Frame_Handler'}, {'ADB_Manager':SimpleNamespace(adbutils_device=device),'WINDOW_DIMS':(1920,1080)})
        namespace['Frame_Handler'].cached_frame = np.ones((1080,1920,3),dtype=np.uint8)
        with self.assertRaises(AutomationStopped): namespace['Frame_Handler'].get_frame()


class TouchTests(unittest.TestCase):
    def test_square_axes_use_android_rotation_instead_of_aspect_guess(self):
        android = Mock()
        manager = SimpleNamespace(adbutils_device=android,minitouch_device=SimpleNamespace(connection=SimpleNamespace(max_x=32767,max_y=32767)))
        h = load({'Input_Handler'},{'ADB_Manager':manager})['Input_Handler']
        for rotation, expected in [(0,(3276,26213)),(1,(6553,3276)),(2,(29490,6553)),(3,(26213,29490))]:
            android.rotation.return_value = rotation
            self.assertEqual(h._to_raw(.1,.8),expected)
        android.rotation.side_effect = RuntimeError('missing rotation')
        with self.assertRaises(AutomationStopped): h._to_raw(.1,.8)

    def test_invalid_geometry_and_coordinates_stop(self):
        for args in [(-.1,.8,100,100,0),(.2,float('nan'),100,100,0),(.1,.8,100,100,4),(.1,.8,0,100,0)]:
            with self.assertRaises(AutomationStopped): raw_touch(*args)


class HudTests(unittest.TestCase):
    def test_missing_slash_returns_false_instead_of_raising_and_starting(self):
        import cv2
        namespace = load({'get_home_builders','get_builder_builders'}, {
            'Frame_Handler':Mock(), 'Asset_Manager':SimpleNamespace(misc_assets={'slash':np.ones((3,3,3),dtype=np.uint8)}),
            'configs':SimpleNamespace(DEBUG=False),'OCR_Handler':Mock(),'logger':Mock()})
        namespace['Frame_Handler'].get_frame_section.return_value = np.zeros((10,20),dtype=np.uint8)
        with patch.object(cv2,'minMaxLoc',return_value=(0,.2,(0,0),(0,0))), patch('time.sleep'):
            for name in ('get_home_builders','get_builder_builders'):
                self.assertFalse(namespace[name](0,return_amount=False))
        namespace['OCR_Handler'].get_text.assert_not_called()

    def test_empty_lab_ocr_stops_before_confirmation_or_cleanup(self):
        import cv2
        tree = ast.parse((ROOT/'src/upgrader.py').read_text())
        cls = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Upgrader')
        for name in ('home_lab_available','builder_lab_available'):
            method = next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==name)
            namespace = {'AutomationStopped':AutomationStopped, 'Frame_Handler':Mock(), 'OCR_Handler':Mock(),
                         'configs':SimpleNamespace(DEBUG=False), 'logger':Mock(), 'fix_digits':lambda s:s}
            namespace['Frame_Handler'].get_frame_section.return_value = np.ones((10,20),dtype=np.uint8)
            namespace['OCR_Handler'].get_text.return_value = []
            exec(compile(ast.Module(body=[method],type_ignores=[]),'upgrader.py','exec'), namespace)
            obj = SimpleNamespace(misc_assets={'slash':np.ones((3,3,3),dtype=np.uint8)})
            with patch.object(cv2,'minMaxLoc',return_value=(0,.95,(0,0),(0,0))), self.assertRaises(AutomationStopped):
                namespace[name](obj)


class ConnectionTests(unittest.TestCase):
    def test_partial_connection_cleanup_and_no_global_adb_restart(self):
        import adbutils
        import pyminitouch
        import uiautomator2
        namespace = load({'classproperty','ADB_Manager'}, {'sys':sys,'configs':SimpleNamespace(EMULATOR_TYPE='bluestacks'),
                    'ADB_ADDRESS':'127.0.0.1:5555','ADB_ABS_DIR':'','Exit_Handler':Mock(),'Path':Path})
        manager = namespace['ADB_Manager']
        old = Mock()
        manager._minitouch_device = old
        touch = Mock()
        with patch('shutil.which',return_value='/test/adb'), patch('subprocess.run') as shell, patch.object(adbutils.adb,'connect',return_value='connected'), patch.object(adbutils,'device'), patch.object(pyminitouch,'MNTDevice',return_value=touch), patch.object(uiautomator2,'connect',side_effect=RuntimeError('connection failure')):
            with self.assertRaises(RuntimeError): manager.connect_once()
        old.stop.assert_called_once()
        touch.stop.assert_called_once()
        self.assertIsNone(manager._minitouch_device)
        self.assertEqual([c.args[0] for c in shell.call_args_list],[['/test/adb','start-server']])


class DiagnosticTests(unittest.TestCase):
    def test_diagnostic_only_reads_and_saves_local_files(self):
        import importlib.util
        import tempfile
        from PIL import Image
        spec = importlib.util.spec_from_file_location('android_diagnostics_test', ROOT/'scripts/diagnose_android.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        device = Mock()
        device.screenshot.return_value = Image.new('RGB',(1280,720),'white')
        device.rotation.return_value = 1
        device.shell.return_value = 'Physical size: 1280x720'
        adb = SimpleNamespace(adb=Mock(),device=Mock(return_value=device))
        adb.adb.device_list.return_value = [SimpleNamespace(serial='127.0.0.1:5555')]
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules,{'adbutils':adb}), patch.object(sys,'argv',['diagnose_android.py','--output',directory]), patch('builtins.print'):
            self.assertEqual(module.main(),1)
            self.assertTrue((Path(directory)/'screen.png').exists())
            self.assertTrue((Path(directory)/'device.json').exists())
        device.shell.assert_called_once_with('wm size')
        device.screenshot.assert_called_once_with(error_ok=False)
        self.assertEqual(len(device.mock_calls),3)

    def test_disconnected_emulator_does_not_attempt_capture(self):
        import importlib.util
        import tempfile
        spec = importlib.util.spec_from_file_location('android_diagnostics_disconnected', ROOT/'scripts/diagnose_android.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        adb = SimpleNamespace(adb=Mock(),device=Mock())
        adb.adb.device_list.return_value = []
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules,{'adbutils':adb}), patch.object(sys,'argv',['diagnose_android.py','--output',str(Path(directory)/'missing')]), patch('builtins.print') as message:
            self.assertEqual(module.main(),2)
            self.assertFalse((Path(directory)/'missing').exists())
            self.assertIn('No connected Android device',message.call_args.args[0])
        adb.device.assert_not_called()


if __name__ == '__main__': unittest.main()
