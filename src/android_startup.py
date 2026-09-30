"""Discover and start BlueStacks without creating touch servers or gameplay input."""
from pathlib import Path
import re
import subprocess
import sys
import time


PACKAGE = "com.supercell.clashofclans"
ACTIVITY = PACKAGE + "/com.supercell.titan.GameApp"
DEFAULT_CONFIG = Path("/Users/Shared/Library/Application Support/BlueStacks/bluestacks.conf")


def bluestacks_address(instance="BlueStacks Air", config=DEFAULT_CONFIG):
    """Read only the chosen instance's name and ADB port."""
    names, ports = {}, {}
    for line in Path(config).read_text().splitlines():
        match = re.fullmatch(r'bst\.instance\.([^.]+)\.(display_name|adb_port)="?([^"]*)"?', line.strip())
        if match:
            internal, field, value = match.groups()
            (names if field == "display_name" else ports)[internal] = value
    matches = [internal for internal, name in names.items() if name == instance]
    if len(matches) != 1:
        raise ValueError("BlueStacks instance name is missing or ambiguous")
    port = int(ports.get(matches[0], "0"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid BlueStacks ADB port")
    return f"127.0.0.1:{port}"


def open_bluestacks():
    if sys.platform != "darwin":
        raise RuntimeError("Open the Android emulator manually on this platform")
    for name in ("BlueStacks", "BlueStacks Air"):
        result = subprocess.run(["open", "-a", name], capture_output=True, timeout=15)
        if result.returncode == 0:
            return
    raise RuntimeError("BlueStacks could not be opened; check its installation")


def ensure_android(adb, address=None, instance="BlueStacks Air", start=True, timeout=60, wait=False):
    """Connect to an existing emulator or launch it and wait, without touches."""
    if address is None:
        address = bluestacks_address(instance) if DEFAULT_CONFIG.exists() else "127.0.0.1:5555"
    deadline = time.monotonic() + timeout
    opened = False
    while True:
        try:
            adb.connect(address, timeout=min(2, max(.1, deadline-time.monotonic())))
            if address in {device.serial for device in adb.device_list()}:
                return address
        except Exception:
            pass
        if not start and not wait:
            raise ConnectionError(f"No connected Android device at {address}")
        if start and not opened:
            open_bluestacks()
            opened = True
        if time.monotonic() >= deadline:
            raise ConnectionError(f"BlueStacks ADB is not ready at {address}; enable ADB in BlueStacks")
        time.sleep(1)


def wait_for_village(device, observe, timeout=60):
    """Wait for package, geometry and HUD together; never send gameplay input."""
    deadline = time.monotonic() + timeout
    while True:
        image = device.screenshot(error_ok=False)
        info = observe(device, image)
        if info["ready_for_automation"] or time.monotonic() >= deadline:
            return image, info
        time.sleep(1)


def archive_diagnostics(output):
    """Preserve prior captures under another name so failure cannot look current."""
    output = Path(output)
    for name in ("device.json", "screen.png"):
        old = output / name
        if old.exists():
            previous = output / (name + f".previous-{time.time_ns()}")
            old.rename(previous)
