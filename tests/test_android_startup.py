import ast
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import android_startup as startup


class StartupTests(unittest.TestCase):
    def test_reads_chosen_port_and_ignores_status_port(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bluestacks.conf"
            path.write_text('bst.instance.Tiramisu64.display_name="BlueStacks Air"\nbst.instance.Tiramisu64.adb_port="5555"\nbst.instance.Tiramisu64.status.adb_port="7777"\n')
            self.assertEqual(startup.bluestacks_address(config=path), "127.0.0.1:5555")
            with self.assertRaises(ValueError):
                startup.bluestacks_address(instance="unknown", config=path)

    def test_invalid_port_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bluestacks.conf"
            path.write_text('bst.instance.Tiramisu64.display_name="BlueStacks Air"\nbst.instance.Tiramisu64.adb_port="99999"\n')
            with self.assertRaises(ValueError):
                startup.bluestacks_address(config=path)

    def test_existing_connection_does_not_launch_or_sleep(self):
        adb = Mock()
        adb.device_list.return_value = [SimpleNamespace(serial="127.0.0.1:5555")]
        with patch.object(startup, "open_bluestacks") as launch, patch.object(startup.time, "sleep") as sleep:
            self.assertEqual(startup.ensure_android(adb, address="127.0.0.1:5555"), "127.0.0.1:5555")
            launch.assert_not_called()
            sleep.assert_not_called()

    def test_closed_emulator_launches_once_and_waits_for_adb(self):
        adb = Mock()
        adb.device_list.side_effect = [[], [], [SimpleNamespace(serial="127.0.0.1:5555")]]
        with patch.object(startup, "open_bluestacks") as launch, patch.object(startup.time, "sleep"):
            self.assertEqual(startup.ensure_android(adb, address="127.0.0.1:5555"), "127.0.0.1:5555")
            launch.assert_called_once()

    def test_runtime_wait_does_not_launch_a_second_emulator(self):
        adb = Mock()
        adb.device_list.side_effect = [[], [SimpleNamespace(serial="127.0.0.1:5555")]]
        with patch.object(startup, "open_bluestacks") as launch, patch.object(startup.time, "sleep"):
            startup.ensure_android(adb, address="127.0.0.1:5555", start=False, wait=True)
            launch.assert_not_called()

    def test_retry_deadline_and_no_start_are_bounded(self):
        adb = Mock()
        adb.device_list.return_value = []
        with patch.object(startup, "open_bluestacks") as launch:
            with self.assertRaises(ConnectionError):
                startup.ensure_android(adb, address="127.0.0.1:5555", start=False)
            launch.assert_not_called()
        with patch.object(startup, "open_bluestacks"), patch.object(startup.time, "monotonic", side_effect=[0,0,2]), patch.object(startup.time, "sleep") as sleep:
            with self.assertRaises(ConnectionError):
                startup.ensure_android(adb, address="127.0.0.1:5555", timeout=1)
            sleep.assert_not_called()

    def test_landscape_logo_is_not_a_ready_village(self):
        device = Mock()
        observe = Mock(side_effect=[
            {"ready_for_automation":False, "village_recognized":False},
            {"ready_for_automation":True, "village_recognized":True}])
        with patch.object(startup.time, "sleep") as sleep:
            _, info = startup.wait_for_village(device, observe)
        self.assertTrue(info["ready_for_automation"])
        self.assertEqual(device.screenshot.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_wait_for_village_deadline_keeps_last_observation(self):
        device = Mock()
        observe = Mock(return_value={"ready_for_automation":False})
        with patch.object(startup.time, "monotonic", side_effect=[0,2]), patch.object(startup.time, "sleep") as sleep:
            _, info = startup.wait_for_village(device, observe, timeout=1)
            self.assertFalse(info["ready_for_automation"])
            sleep.assert_not_called()

    def test_previous_diagnostics_are_preserved_but_not_current(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output/"device.json").write_text('{"ready_for_automation":true}')
            (output/"screen.png").write_bytes(b"old screenshot")
            startup.archive_diagnostics(output)
            self.assertFalse((output/"device.json").exists())
            self.assertFalse((output/"screen.png").exists())
            self.assertEqual(len(list(output.glob("*.previous-*"))), 2)

    def test_emulator_initializer_reuses_start_and_does_not_register_shutdown(self):
        tree = ast.parse((ROOT/"src/utils.py").read_text())
        cls = next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name=="_Emulator_Manager")
        method = next(node for node in cls.body if isinstance(node,ast.FunctionDef) and node.name=="init")
        method.decorator_list = []
        namespace = {"Exit_Handler":Mock()}
        exec(compile(ast.Module(body=[method],type_ignores=[]),"utils.py","exec"),namespace)
        manager = SimpleNamespace(start=Mock(), restart=Mock(), stop=Mock(), adb_address="127.0.0.1:5555")
        with patch.dict(sys.modules,{"adbutils":SimpleNamespace(adb="test-client")}), patch.object(startup,"ensure_android") as connect:
            namespace["init"](manager)
        manager.start.assert_called_once()
        manager.restart.assert_not_called()
        namespace["Exit_Handler"].register.assert_not_called()
        connect.assert_called_once_with("test-client",address="127.0.0.1:5555",start=False,wait=True)


if __name__ == "__main__":
    unittest.main()
