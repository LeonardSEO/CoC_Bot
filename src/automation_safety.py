"""Fatal observation failures must bypass legacy catch-and-continue handlers."""
import math


class AutomationStopped(SystemExit):
    """Stop this worker without retrying inputs or restarting the emulator."""


class PortraitFrame(AutomationStopped):
    """A loading screen may be portrait; gameplay must never use this frame."""


def validate_frame(frame, expected):
    import numpy as np
    if frame.ndim != 3 or frame.shape[2] < 3:
        raise AutomationStopped('Invalid screenshot; automation stopped')
    height, width = frame.shape[:2]
    if (width, height) != tuple(expected):
        if (width, height) == tuple(reversed(expected)):
            raise PortraitFrame('Android is still in portrait; waiting for the landscape village')
        raise AutomationStopped(f'Screenshot is {width}x{height}; expected {expected[0]}x{expected[1]}. Set the Android display resolution before restarting.')
    if not np.any(frame):
        raise AutomationStopped('Black screenshot; automation stopped')


def raw_touch(x, y, width, height, rotation):
    if any(not math.isfinite(v) or not 0 <= v <= 1 for v in (x, y)):
        raise AutomationStopped('Invalid touch coordinate; automation stopped')
    if width <= 0 or height <= 0 or type(rotation) is not int or rotation not in range(4):
        raise AutomationStopped('Unknown touch geometry; automation stopped')
    coordinates = ((x, y), (1-y, x), (1-x, 1-y), (y, 1-x))
    u, v = coordinates[rotation]
    return int(u*width), int(v*height)
