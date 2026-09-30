"""Read-only Android diagnostics. No taps, swipes, app launches or API calls."""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--address', default='127.0.0.1:5555')
    parser.add_argument('--output', default='debug/android-diagnostics')
    args = parser.parse_args()
    import adbutils
    try:
        adbutils.adb.connect(args.address, timeout=5)
        connected = {device.serial for device in adbutils.adb.device_list()}
        if args.address not in connected:
            print(f'No connected Android device at {args.address}. Open BlueStacks, enable ADB, then run adb connect {args.address} and adb devices. No diagnostic files were saved.')
            return 2
        device = adbutils.device(args.address)
        image = device.screenshot(error_ok=False)
    except Exception as exc:
        print(f'Cannot capture Android screenshot ({type(exc).__name__}). Check BlueStacks and adb devices, then retry. No diagnostic files were saved.')
        return 2
    info = {'address': args.address, 'screenshot_size': list(image.size),
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
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    image.save(output / 'screen.png')
    (output / 'device.json').write_text(json.dumps(info, indent=2))
    print(json.dumps(info, indent=2))
    print(f'Saved local screenshot: {output / "screen.png"}. Review private information before sharing.')
    return 0 if info['resolution_matches'] else 1


if __name__ == '__main__':
    sys.exit(main())
