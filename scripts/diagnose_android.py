"""Android diagnostics. Read-only by default; --open-clash launches only Clash."""
import argparse
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', default='127.0.0.1:5555')
    parser.add_argument('--output', default='debug/android-diagnostics')
    parser.add_argument('--open-clash', action='store_true', help='Open installed Clash and wait for its landscape screen; no taps or purchases')
    parser.add_argument('--wait-seconds', type=float, default=60)
    args = parser.parse_args()
    if not 0 < args.wait_seconds <= 120:
        parser.error('--wait-seconds must be greater than zero and at most 120')
    import adbutils
    try:
        adbutils.adb.connect(args.address, timeout=5)
        connected = {device.serial for device in adbutils.adb.device_list()}
        if args.address not in connected:
            print(f'No connected Android device at {args.address}. Open BlueStacks, enable ADB, then run adb connect {args.address} and adb devices. No diagnostic files were saved.')
            return 2
        device = adbutils.device(args.address)
        if args.open_clash:
            installed = device.shell(['pm', 'path', 'com.supercell.clashofclans'])
            if not installed.strip().startswith('package:'):
                print('Clash is not installed for this Android device. Install/open Clash in this BlueStacks instance first. No diagnostic files were saved.')
                return 2
            result = device.shell(['am', 'start', '-W', '-n', 'com.supercell.clashofclans/com.supercell.titan.GameApp'])
            if 'Error:' in result or 'Exception' in result:
                print('Android could not open the Clash activity. Open Clash manually in BlueStacks and retry without --open-clash.')
                return 2
            deadline = time.monotonic() + args.wait_seconds
            while True:
                image = device.screenshot(error_ok=False)
                try:
                    foreground = device.app_current().package
                except Exception:
                    foreground = None
                if image.size == (1920,1080) and foreground == 'com.supercell.clashofclans':
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(1)
        image = device.screenshot(error_ok=False)
    except Exception as exc:
        print(f'Cannot capture Android screenshot ({type(exc).__name__}). Check BlueStacks and adb devices, then retry. No diagnostic files were saved.')
        return 2
    try:
        foreground = device.app_current().package
    except Exception:
        foreground = None
    info = {'address': args.address, 'screenshot_size': list(image.size),
            'foreground_package': foreground,
            'rotation': device.rotation(),
            'display_size': device.shell('wm size').strip(),
            'expected_screenshot_size': [1920, 1080],
            'resolution_matches': image.size == (1920, 1080)}
    if info['resolution_matches']:
        import cv2
        import numpy as np
        slash = cv2.imread(str(Path(__file__).resolve().parents[1] / 'assets/misc/slash.png'), cv2.IMREAD_GRAYSCALE)
        gray = cv2.cvtColor(np.array(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
        gray[gray < 200] = 0
        info['hud_confidence'] = {}
        for name, left, right in [('home_base', .49, .545), ('builder_base', .57, .617)]:
            crop = gray[int(1080*.04):int(1080*.08), int(1920*left):int(1920*right)]
            result = cv2.matchTemplate(crop, slash, cv2.TM_CCOEFF_NORMED)
            info['hud_confidence'][name] = float(cv2.minMaxLoc(result)[1])
    info['village_recognized'] = max(info.get('hud_confidence', {}).values(), default=0) >= .9
    info['ready_for_automation'] = bool(info['resolution_matches'] and info['village_recognized'] and foreground == 'com.supercell.clashofclans')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    image.save(output / 'screen.png')
    (output / 'device.json').write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    print(f'Saved local screenshot: {output / "screen.png"}. Review private information before sharing.')
    if not info['ready_for_automation']:
        print('Automation is not ready. Inspect screen.png; complete loading/login manually and retry. No gameplay inputs were sent.')
    return 0 if info['ready_for_automation'] else 1


if __name__ == '__main__':
    sys.exit(main())
