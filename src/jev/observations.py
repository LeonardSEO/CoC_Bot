"""Screenshot observations gated by a locally calibrated, validated profile.

No built-in game coordinates are claimed to recognize loot or deployment areas.
The profile supplies real screenshot crops and a playable-terrain mask. Dynamic
red boundaries exclude the current base footprint from that mask.
"""
import hashlib
import json
from pathlib import Path
import re
import time

from .attacks import DeploymentPlan
from .policy import Observation


def parse_amount(text):
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not re.fullmatch(r'(?:\d+|\d{1,3}(?:[ ,.\u00a0]\d{3})+)', text):
        return None
    result = int(re.sub(r'[ ,.\u00a0]', '', text))
    return result if result <= 1_000_000_000 else None


class ScreenObserver:
    def __init__(self, profile=None, *, root=None, ocr=None):
        self.profile = profile or {}
        self.root = Path(root or '.')
        self.ocr = ocr
        self._images = {}

    @classmethod
    def from_config(cls, config, ocr):
        path = getattr(config, 'JEV_SCREEN_PROFILE_PATH', '')
        if not path:
            return cls(ocr=ocr)
        try:
            target = Path(path).expanduser().resolve()
            profile = json.loads(target.read_text())
            if not isinstance(profile, dict):
                raise ValueError('Profile must be an object')
            return cls(profile, root=target.parent, ocr=ocr)
        except (ValueError, OSError):
            from log import logger
            logger.warning('Jev screen profile unavailable; attack decisions use legacy behavior')
            return cls(ocr=ocr)

    def _ready(self, frame):
        resolution = self.profile.get('resolution')
        return (self.profile.get('validated') is True and self.profile.get('version') == 1
            and frame is not None and len(frame.shape) == 3 and frame.shape[2] == 3
            and resolution == [frame.shape[1], frame.shape[0]])

    def _crop(self, frame, region):
        if not isinstance(region, list) or len(region) != 4:
            return None
        x1, y1, x2, y2 = region
        if not all(isinstance(v, (int, float)) for v in region) or not 0 <= x1 < x2 <= 1 or not 0 <= y1 < y2 <= 1:
            return None
        h, w = frame.shape[:2]
        return frame[int(y1*h):int(y2*h), int(x1*w):int(x2*w)]

    def _image(self, path, gray=False):
        import cv2
        key = (path, gray)
        if key not in self._images:
            target = self.root / path
            image = cv2.imread(str(target), cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)
            if image is not None and not gray:
                image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            self._images[key] = image
        return self._images[key]

    def _match(self, frame, spec):
        import cv2
        import numpy as np
        if not isinstance(spec, dict) or not isinstance(spec.get('path'), str):
            return None
        crop = self._crop(frame, spec.get('region'))
        template = self._image(spec['path'])
        if crop is None or template is None or crop.shape[0] < template.shape[0] or crop.shape[1] < template.shape[1] or np.std(template) < 1:
            return None
        _, confidence, _, location = cv2.minMaxLoc(cv2.matchTemplate(crop, template, cv2.TM_CCOEFF_NORMED))
        if confidence < max(.9, float(spec.get('threshold', .95))):
            return None
        h, w = frame.shape[:2]
        x, y = location
        region = spec['region']
        return (region[0] + (x+template.shape[1]/2)/w, region[1] + (y+template.shape[0]/2)/h, confidence)

    def _amount(self, frame, region):
        crop = self._crop(frame, region)
        if crop is None or self.ocr is None:
            return None
        texts = self.ocr(crop)
        # Multiple OCR blocks may be a grouped number, never a second label.
        return parse_amount(' '.join(texts)) if isinstance(texts, list) and all(isinstance(t, str) for t in texts) else None

    def scout(self, frame):
        if not self._ready(frame):
            return None
        try:
            import cv2
            observed_at = time.time()
            templates = self.profile.get('templates', {})
            scouting = self._match(frame, templates.get('scouting'))
            next_button = self._match(frame, templates.get('next'))
            if scouting is None or next_button is None:
                return None
            regions = self.profile.get('loot_regions', {})
            loot = {key: self._amount(frame, regions.get(key)) for key in ('gold', 'elixir', 'dark_elixir')}
            cost = self._amount(frame, regions.get('search_cost'))
            base = self._crop(frame, self.profile.get('base_region'))
            if loot['gold'] is None or loot['elixir'] is None or cost is None or base is None:
                return None
            # Quantized map texture avoids timer digits and transient button states.
            texture = cv2.resize(cv2.cvtColor(base, cv2.COLOR_RGB2GRAY), (16, 16)) // 32
            signature = hashlib.sha256(texture.tobytes()).hexdigest()
            return Observation({'loot': loot, 'search_cost': cost, 'signature': signature, 'next_position': list(next_button[:2])}, source='validated_scouting_profile', quality=min(scouting[2], next_button[2]), observed_at=observed_at)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return None

    def _legal_mask(self, frame, village):
        import cv2
        import numpy as np
        if not self._ready(frame):
            return None
        spec = self.profile.get('deployment', {}).get(village)
        if not isinstance(spec, dict) or self._match(frame, spec.get('anchor')) is None:
            return None
        playable = self._image(spec.get('playable_mask', ''), gray=True)
        if playable is None or playable.shape != frame.shape[:2]:
            return None
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        red = cv2.inRange(hsv, np.array([0, 130, 120]), np.array([10, 255, 255])) | cv2.inRange(hsv, np.array([170, 130, 120]), np.array([179, 255, 255]))
        red = cv2.bitwise_and(red, playable)
        red = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        h, w = playable.shape
        boundaries = [c for c in contours if .02*h*w < cv2.contourArea(c) < .7*h*w and cv2.contourArea(c) > .6*cv2.contourArea(cv2.convexHull(c))]
        if len(boundaries) != 1:
            return None
        footprint = np.zeros_like(playable)
        cv2.drawContours(footprint, boundaries, -1, 255, cv2.FILLED)
        margin = max(3, int(min(h, w)*.02))
        kernel = np.ones((2*margin+1, 2*margin+1), np.uint8)
        footprint = cv2.dilate(footprint, kernel)
        legal = cv2.erode(playable, kernel) & cv2.bitwise_not(footprint)
        legal[:int(h*.12)] = 0
        legal[int(h*.8):] = 0
        legal[:, :int(w*.05)] = 0
        legal[:, int(w*.95):] = 0
        return legal

    def deployment(self, frame, village):
        if not self._ready(frame):
            return None
        try:
            import numpy as np
            observed_at = time.time()
            legal = self._legal_mask(frame, village)
            if legal is None:
                return None
            ys, xs = np.nonzero(legal)
            if len(xs) < 100:
                return None
            h, w = legal.shape
            points = []
            for target in (.3, .5, .7):
                distance = (xs/w-target)**2 + (ys/h-.72)**2
                i = int(np.argmin(distance))
                point = (float(xs[i]/w), float(ys[i]/h))
                if all(abs(point[0]-p[0]) + abs(point[1]-p[1]) >= .08 for p in points):
                    points.append(point)
            if not points:
                return None
            plans = [DeploymentPlan('concentrated', (points[len(points)//2],))]
            if len(points) >= 2:
                plans.append(DeploymentPlan('distributed', tuple(points)))
            return Observation({'village': village, 'legal_points': points}, source='validated_terrain_mask_and_red_boundary', quality=.95, observed_at=observed_at), plans
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            return None

    def points_valid(self, frame, village, points):
        try:
            legal = self._legal_mask(frame, village)
            if legal is None:
                return False
            h, w = legal.shape
            return all(0 < x < 1 and 0 < y < .8 and legal[min(h-1, int(y*h)), min(w-1, int(x*w))] > 0 for x, y in points)
        except Exception:
            return False
