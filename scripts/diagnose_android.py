"""Automatic BlueStacks/Clash diagnostics; never send gameplay taps or purchases."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from android_startup import ACTIVITY, PACKAGE, archive_diagnostics, ensure_android, wait_for_village


def observe(device, image):
    try:
        foreground = device.app_current().package
    except Exception:
        foreground = None
    info = {
        "timestamp": time.time(),
        "screenshot_size": list(image.size),
        "foreground_package": foreground,
        "expected_screenshot_size": [1920, 1080],
        "resolution_matches": image.size == (1920, 1080),
        "hud_confidence": {},
    }
    if info["resolution_matches"]:
        import cv2
        import numpy as np
        slash = cv2.imread(str(Path(__file__).resolve().parents[1] / "assets/misc/slash.png"), cv2.IMREAD_GRAYSCALE)
        if slash is None:
            raise RuntimeError("Missing village recognition template")
        gray = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
        gray[gray < 200] = 0
        for name, left, right in [("home_base", .49, .545), ("builder_base", .57, .617)]:
            crop = gray[int(1080*.04):int(1080*.08), int(1920*left):int(1920*right)]
            result = cv2.matchTemplate(crop, slash, cv2.TM_CCOEFF_NORMED)
            info["hud_confidence"][name] = float(cv2.minMaxLoc(result)[1])
    info["village_recognized"] = max(info["hud_confidence"].values(), default=0) >= .9
    info["ready_for_automation"] = bool(
        info["resolution_matches"] and info["village_recognized"] and foreground == PACKAGE)
    return info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default=None, help="ADB address; otherwise discover BlueStacks Air's configured port")
    parser.add_argument("--instance", default="BlueStacks Air")
    parser.add_argument("--output", default="debug/android-diagnostics")
    parser.add_argument("--no-start", action="store_true", help="Do not launch BlueStacks when disconnected")
    parser.add_argument("--open-clash", dest="open_clash", action="store_true", help="Open Clash (the default)")
    parser.add_argument("--no-open-clash", dest="open_clash", action="store_false", help="Read the current screen immediately without launching Clash")
    parser.set_defaults(open_clash=True)
    parser.add_argument("--wait-seconds", type=float, default=60)
    args = parser.parse_args()
    if not 0 < args.wait_seconds <= 120:
        parser.error("--wait-seconds must be greater than zero and at most 120")
    output = Path(args.output)
    archive_diagnostics(output)
    import adbutils
    try:
        address = ensure_android(adbutils.adb, address=args.address, instance=args.instance,
                                 start=not args.no_start, timeout=args.wait_seconds)
        device = adbutils.device(address)
        if args.open_clash:
            installed = device.shell(["pm", "path", PACKAGE])
            if not installed.strip().startswith("package:"):
                raise RuntimeError("Clash is not installed in this Android instance")
            result = device.shell(["am", "start", "-W", "-n", ACTIVITY])
            if "Error:" in result or "Exception" in result:
                raise RuntimeError("Android could not open Clash; open it manually")
            image, info = wait_for_village(device, observe, timeout=args.wait_seconds)
        else:
            image = device.screenshot(error_ok=False)
            info = observe(device, image)
        info.update(address=address, rotation=device.rotation(),
                    display_size=device.shell("wm size").strip())
        output.mkdir(parents=True, exist_ok=True)
        image.save(output / "screen.png")
        info["screenshot_file"] = "screen.png"
        (output / "device.json").write_text(json.dumps(info, indent=2))
    except Exception as exc:
        output.mkdir(parents=True, exist_ok=True)
        info = {"timestamp": time.time(), "status": "diagnostic_failed",
                "ready_for_automation": False, "screenshot_file": None,
                "error_type": type(exc).__name__}
        (output / "device.json").write_text(json.dumps(info, indent=2))
        print(f"Diagnostic failed ({type(exc).__name__}): {exc}. No new screenshot was saved; previous captures were archived.")
        return 2
    print(json.dumps(info, indent=2))
    print(f"Saved local screenshot: {output / 'screen.png'}. Review private information before sharing.")
    if not info["ready_for_automation"]:
        print("Village not ready before the deadline. Complete loading/login manually and retry. No gameplay inputs were sent.")
    return 0 if info["ready_for_automation"] else 1


if __name__ == "__main__":
    sys.exit(main())
