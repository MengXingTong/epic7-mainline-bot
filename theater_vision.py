"""Position-limited Theater UI glyph matching, normalized to 1600x900."""
from pathlib import Path
import cv2
import numpy as np

ASSETS = Path(__file__).resolve().parent / 'assets' / 'theater'
THRESHOLDS = {'story': .72, 'battle': .70}


def final_wave_counter(text):
    """Only an explicit equal, positive 1..99 current/total wave counter."""
    import re
    from theater_core import norm
    if not isinstance(text, str):
        return False
    match = re.fullmatch(r'([1-9][0-9]?)/([1-9][0-9]?)', norm(text))
    return bool(match and match[1] == match[2])


def complete_clear_overlay(image, observation):
    """Multi-part overlay proof, NOT a standalone word/green-pixel count.

    The complete, fixed-position golden star and both wings must be present,
    together with an explicit final N/N counter and battle controls in this same frame.
    This licenses only dismissing the overlay, never a completed episode.
    """
    from theater_core import norm, confident
    o = observation
    clear = [t for t in o.tokens if norm(t.text) == 'clear']
    waves = [t for t in o.tokens if t.source == 'theater_wave_ocr']
    if ('theater_battle' not in o.visuals or len(clear) != 1 or not confident(clear[0])
            or clear[0].score < .94 or not o.in_region(clear[0], (.40, .33, .62, .45))
            or len(waves) != 1 or not final_wave_counter(waves[0].text) or not confident(waves[0])
            or waves[0].score < .94 or not o.in_region(waves[0], (.12, 0, .18, .06))):
        return False
    raw = np.asarray(image.convert('RGB').resize((1600, 900)))
    hsv = cv2.cvtColor(raw, cv2.COLOR_RGB2HSV)
    gold = cv2.inRange(hsv, (10, 65, 170), (40, 255, 255)) > 0
    def fill(box):
        x0, y0, x1, y1 = box
        return float(gold[y0:y1, x0:x1].mean())
    parts = ((780,45,825,110), (735,110,865,210), (735,190,865,275),
             (750,300,850,375), (780,375,825,430),
             (520,205,720,250), (880,205,1080,250))
    corners = ((430,190,505,270), (600,360,700,425), (900,360,1000,425))
    return all(fill(box) > .18 for box in parts) and all(fill(box) < .12 for box in corners)


class TheaterVision:
    def __init__(self, root=ASSETS):
        self.templates = {}
        for name in THRESHOLDS:
            path = Path(root) / (name + '.png')
            if not path.is_file():
                raise RuntimeError('缺少月光剧场识别素材；不会在未知画面翻页。')
            template = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_GRAYSCALE)
            if template is None or template.std() < 2:
                raise RuntimeError('月光剧场识别素材无效。')
            self.templates[name] = template

    def apply(self, image, observation):
        from theater_directory import apply_directory_visuals
        observation = apply_directory_visuals(image, observation)
        gray = cv2.cvtColor(np.asarray(image.resize((1600, 900))), cv2.COLOR_RGB2GRAY)
        patch = gray[:130, 1200:1600]
        for name, template in self.templates.items():
            if patch.shape[0] < template.shape[0] or patch.shape[1] < template.shape[1]:
                continue
            score = float(cv2.matchTemplate(patch, template, cv2.TM_CCOEFF_NORMED).max())
            if score >= THRESHOLDS[name]:
                observation.visuals.add('theater_' + name)
        if complete_clear_overlay(image, observation):
            observation.visuals.add('theater_clear_overlay')
        return observation
