"""macOS behavior regression tests runnable without Cocoa, BlueStacks or ADB.

Real spawn processes and config/filesystem paths are exercised. Native macOS
APIs, emulator launches and PyInstaller execution are isolated, so passing these
tests does not certify a native .app or actual gameplay on Apple Silicon.
"""
import importlib.util
import json
import logging
import multiprocessing
import os
from pathlib import Path
import re
import runpy
import shlex
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from jev.client import JevClient, Settings
from jev.runtime import create_service


def spawn_probe(connection):
    """Actual macOS-style spawn target; never sends an API request."""
    client = JevClient(Settings(mode='shadow'))
    connection.send({'key_present': bool(client._api_key),
        'test_key_inherited': client._api_key == 'macos-test-placeholder',
        'key_hidden_in_repr': 'macos-test-placeholder' not in repr(client),
        'calls': client.calls, 'model': client.settings.model})
    connection.close()


def load_launch(disable_sleep=True):
    config = ModuleType('configs')
    config.DISABLE_DEVICE_SLEEP = disable_sleep
    spec = importlib.util.spec_from_file_location('launch_macos_test', ROOT / 'src/launch.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'configs': config}):
        spec.loader.exec_module(module)
    return module


class LaunchTests(unittest.TestCase):
    def test_cli_imports_sleep_manager_before_starting_bot(self):
        launch = load_launch()
        utils = ModuleType('utils')
        calls = []
        utils.disable_sleep = lambda: calls.append('sleep')
        launch.launch_proc = lambda args: calls.append('bot')
        with patch.dict(sys.modules, {'utils': utils}):
            launch.cmd_launch(SimpleNamespace())
        self.assertEqual(calls, ['sleep', 'bot'])

    def test_cli_can_run_without_sleep_helper(self):
        launch = load_launch(disable_sleep=False)
        launched = []
        args = SimpleNamespace(id='main')
        launch.launch_proc = lambda value: launched.append(value.id)
        launch.cmd_launch(args)
        self.assertEqual(launched, ['main'])

    def test_worker_initializes_instance_before_creating_jev_bot(self):
        launch = load_launch()
        events = []
        utils = ModuleType('utils')
        utils.parse_args = lambda *args: events.append(('args', args))
        utils.init_instance = lambda instance: events.append(('instance', instance))
        log = ModuleType('log')
        log.enable_logging = lambda instance: events.append(('logging', instance))
        bot_module = ModuleType('coc_bot')
        class Bot:
            def __init__(self): events.append(('construct', None))
            def run(self): events.append(('run', None))
        bot_module.CoC_Bot = Bot
        args = SimpleNamespace(debug=False, id='main', gui=True, gui_port=1234)
        with patch.dict(sys.modules, {'utils': utils, 'log': log, 'coc_bot': bot_module}):
            launch.launch_proc(args)
        self.assertEqual([event[0] for event in events], ['args', 'instance', 'logging', 'construct', 'run'])
        self.assertEqual(events[0][1], (False, 'main', True, 1234))


class SpawnTests(unittest.TestCase):
    def probe(self, present):
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe(duplex=False)
        worker = context.Process(target=spawn_probe, args=(child,))
        try:
            with patch.dict(os.environ):
                if present: os.environ['OPENROUTER_API_KEY'] = 'macos-test-placeholder'
                else: os.environ.pop('OPENROUTER_API_KEY', None)
                worker.start()
            child.close()
            self.assertTrue(parent.poll(10), 'Spawn worker did not respond')
            result = parent.recv()
            worker.join(10)
            self.assertEqual(worker.exitcode, 0)
            return result
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
            parent.close()
            child.close()

    def test_terminal_key_is_inherited_by_spawned_bot_process(self):
        result = self.probe(True)
        self.assertTrue(result['test_key_inherited'])
        self.assertTrue(result['key_hidden_in_repr'])
        self.assertEqual(result['calls'], 0)
        self.assertEqual(result['model'], 'typesafe/jev-1.13')

    def test_finder_style_missing_environment_key_does_not_crash(self):
        result = self.probe(False)
        self.assertFalse(result['key_present'])
        self.assertEqual(result['calls'], 0)


class MacPlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Load the actual production module before simulating darwin. Importing
        # native dependencies while pretending Linux is macOS would be invalid.
        try:
            import cv2
            import loguru
        except ImportError:
            raise unittest.SkipTest('Use the bot .venv for platform integration tests')
        if importlib.util.find_spec('configs') is None and importlib.util.find_spec('configs_build') is None:
            # Fresh checkouts have no personal config. Exercise the real module
            # with the real template without creating a config that could get
            # embedded into a subsequent CLI release.
            config = ModuleType('configs')
            config.__dict__.update(runpy.run_path(str(ROOT / 'src/configs.template.py')))
            with patch.dict(sys.modules, {'configs': config}):
                import utils
        else:
            import utils
        cls.utils = utils

    def test_bluestacks_instance_and_adb_port_from_mac_config(self):
        utils = self.utils
        with tempfile.TemporaryDirectory() as directory:
            conf = Path(directory) / 'Application Support/BlueStacks/bluestacks.conf'
            conf.parent.mkdir(parents=True)
            conf.write_text('bst.instance.Pie64_1.display_name="main"\nbst.instance.Pie64_1.adb_port="5555"\n')
            with patch.object(sys, 'platform', 'darwin'), patch.object(utils, 'INSTANCE_ID', 'main'), patch.multiple(utils.BlueStacks_Manager, _conf_path=str(conf), _internal_instance_name=None, _adb_port=None):
                self.assertEqual(utils.BlueStacks_Manager.internal_instance_name, 'Pie64_1')
                self.assertEqual(utils.BlueStacks_Manager.adb_address, '127.0.0.1:5555')

    def test_missing_mac_instance_reports_actionable_error(self):
        utils = self.utils
        with tempfile.TemporaryDirectory() as directory:
            conf = Path(directory) / 'bluestacks.conf'
            conf.write_text('bst.instance.Pie64_1.display_name="other"\n')
            with patch.object(sys, 'platform', 'darwin'), patch.object(utils, 'INSTANCE_ID', 'main'), patch.multiple(utils.BlueStacks_Manager, _conf_path=str(conf), _internal_instance_name=None):
                with self.assertRaisesRegex(RuntimeError, 'Rename the emulator instance'):
                    _ = utils.BlueStacks_Manager.internal_instance_name

    def test_mac_bluestacks_executable_path_with_spaces_is_one_argument(self):
        utils = self.utils
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'BlueStacks Air.app/Contents/MacOS/BlueStacks'
            executable.parent.mkdir(parents=True)
            executable.touch()
            with patch.object(sys, 'platform', 'darwin'), patch.object(utils, 'INSTANCE_ID', 'main'), patch.object(utils, 'BLUESTACKS_BIN_PATH', str(executable)), patch.object(utils, 'Cache_Manager', {}), patch.multiple(utils.BlueStacks_Manager, _internal_instance_name='Pie64_1', _pid=None), patch.object(utils.BlueStacks_Manager, 'wake'), patch.object(utils.BlueStacks_Manager, 'check', side_effect=[False, True]), patch('subprocess.Popen', return_value=SimpleNamespace(pid=9012)) as popen:
                utils.BlueStacks_Manager.start()
                self.assertEqual(popen.call_args.args[0], [str(executable), '--instance', 'Pie64_1'])
                self.assertTrue(popen.call_args.kwargs['start_new_session'])
                self.assertEqual(utils.Cache_Manager['main_emulator_pid'], 9012)

    def test_mumu_is_rejected_on_mac_before_any_launch(self):
        with patch.object(sys, 'platform', 'darwin'):
            with self.assertRaisesRegex(Exception, 'Use BlueStacks'):
                self.utils.MuMu_Manager.init()

    def test_accessibility_request_uses_native_api_and_rechecks_permission(self):
        services = ModuleType('ApplicationServices')
        services.AXIsProcessTrustedWithOptions = Mock()
        with patch.object(sys, 'platform', 'darwin'), patch.dict(sys.modules, {'ApplicationServices': services}), patch('subprocess.run', side_effect=[SimpleNamespace(stdout='false'), SimpleNamespace(stdout='true')]), patch('time.sleep'):
            self.utils.request_perms()
        services.AXIsProcessTrustedWithOptions.assert_called_once_with({'AXTrustedCheckOptionPrompt': True})

    def test_packaged_sleep_helper_handles_spaces_and_quotes_in_home_path(self):
        utils = self.utils
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / 'CoC Bot.app/Contents/Frameworks'
            bundle.mkdir(parents=True)
            shutil.copyfile(ROOT / 'src/sleep_helper.sh', bundle / 'sleep_helper.sh')
            # Apostrophes are legal in Windows fixture paths too, and require
            # both shell quoting and escaped AppleScript double quotes.
            app_data = Path(directory) / "Test User's Mac/.CoC_Bot"
            app_data.mkdir(parents=True)
            with patch.object(sys, 'platform', 'darwin'), patch.object(utils, '__file__', str(bundle / 'utils.py')), patch.object(utils, 'APP_DATA_DIR', app_data), patch.object(utils.Exit_Handler, 'register'), patch('os.getpid', return_value=4567), patch('subprocess.Popen') as popen:
                utils.disable_sleep()
            script = popen.call_args.args[0][2]
            match = re.fullmatch(r'do shell script (".*") with administrator privileges', script)
            self.assertIsNotNone(match)
            command = json.loads(match.group(1))
            self.assertEqual(shlex.split(command), [str(app_data / 'sleep_helper.sh'), '4567'])
            self.assertEqual((app_data / 'sleep_helper.sh').read_bytes(), (ROOT / 'src/sleep_helper.sh').read_bytes())

    @unittest.skipUnless(sys.platform == 'darwin', 'Requires the native macOS AppleScript interpreter')
    def test_native_applescript_parses_production_helper_command(self):
        utils = self.utils
        with tempfile.TemporaryDirectory() as directory:
            app_data = Path(directory) / 'Test User "M4"/.CoC_Bot'
            app_data.mkdir(parents=True)
            with patch.object(utils, 'APP_DATA_DIR', app_data), patch.object(utils.Exit_Handler, 'register'), patch('subprocess.Popen') as popen:
                utils.disable_sleep()
            script = popen.call_args.args[0][2]
            quoted = re.fullmatch(r'do shell script (".*") with administrator privileges', script).group(1)
            # Parse the actual produced AppleScript string; do not execute the
            # helper or ask for administrator privileges.
            result = subprocess.run(['osascript', '-e', 'return ' + quoted], capture_output=True, text=True, check=True, timeout=5)
            self.assertEqual(shlex.split(result.stdout.strip()), [str(app_data / 'sleep_helper.sh'), str(os.getpid())])


class PackagingTests(unittest.TestCase):
    def test_mac_release_uses_jev_defaults_and_bundles_required_assets(self):
        for kind in ('gui', 'cli'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'src').mkdir()
                shutil.copyfile(ROOT / 'src/configs.template.py', root / 'src/configs.template.py')
                original = Path.cwd()
                try:
                    os.chdir(root)
                    with patch.object(sys, 'platform', 'darwin'), patch.object(sys, 'argv', ['build_release.py', '--version', 'test', '--'+kind]), patch.dict(os.environ, {'OPENROUTER_API_KEY': 'macos-test-placeholder'}), patch('subprocess.run') as run, patch('shutil.make_archive') as archive:
                        runpy.run_path(str(ROOT / '.github/workflows/build_release.py'), run_name='__main__')
                    content = (root / 'src/configs_build.py').read_text()
                    config = SimpleNamespace(**runpy.run_path(str(root / 'src/configs_build.py')))
                    settings = Settings.from_config(config)
                    self.assertEqual(settings.mode, 'off')
                    self.assertEqual(settings.model, 'typesafe/jev-1.13')
                    self.assertEqual(config.LOCAL_GUI, kind == 'gui')
                    self.assertNotIn('macos-test-placeholder', content)
                    build = run.call_args_list[0]
                    self.assertEqual(build.args[0][0], 'pyinstaller')
                    self.assertIn('assets:assets', build.args[0])
                    self.assertIn('src/sleep_helper.sh:.', build.args[0])
                    self.assertTrue(build.kwargs['check'])
                    if kind == 'gui':
                        self.assertIn('src/gui_server:gui_server', build.args[0])
                        self.assertEqual(run.call_args_list[1].args[0][-1], 'CoC Bot.app')
                    else:
                        self.assertEqual(archive.call_args.args[0], 'CoC_Bot-test-mac-cli')
                finally:
                    os.chdir(original)

    def test_jev_events_use_writable_app_data_without_exposing_key(self):
        instance = 'mac_test_' + uuid.uuid4().hex
        sink = logging.getLogger('jev.events.' + instance)
        with tempfile.TemporaryDirectory() as directory:
            log = ModuleType('log')
            log.LOG_DIR = Path(directory) / '.CoC_Bot/debug'
            log.logger = Mock()
            utils = ModuleType('utils')
            utils.INSTANCE_ID = instance
            try:
                with patch.dict(sys.modules, {'log': log, 'utils': utils}), patch.dict(os.environ, {'OPENROUTER_API_KEY': 'macos-test-placeholder'}):
                    service = create_service(SimpleNamespace(JEV_MODE='shadow'))
                    service.record('startup_probe', ready=True)
                path = log.LOG_DIR / f'{instance}.jev.jsonl'
                content = path.read_text()
                event = json.loads(content)
                self.assertEqual(event['mode'], 'shadow')
                self.assertEqual(event['instance_id'], instance)
                self.assertTrue(event['ready'])
                self.assertNotIn('macos-test-placeholder', content)
                self.assertEqual(service.client.calls, 0)
            finally:
                for handler in list(sink.handlers):
                    handler.close()
                    sink.removeHandler(handler)


if __name__ == '__main__':
    unittest.main()
