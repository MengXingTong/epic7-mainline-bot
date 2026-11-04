"""Map a captured PC client to its visible game area without changing the window."""
from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class Viewport:
    x: int
    y: int
    width: int
    height: int

    def point(self, x, y, width=1600, height=900):
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError('点击位置超出当前游戏画面。')
        return (self.x + min(self.width-1, int(x*self.width/width)),
                self.y + min(self.height-1, int(y*self.height/height)))


def pc_viewport(raw):
    """Accept landscape clients; remove only positively visible symmetric black bars.

    A non-16:9 client can render edge to edge or letterbox. Never infer padding
    from the window ratio alone, or from a dark/loading frame with no boundary.
    """
    h, w = raw.shape[:2]
    if w < 640 or h < 360 or not 1.4 <= w/h <= 2.4:
        raise ValueError('请使用至少640×360、宽高比1.4至2.4的横向游戏客户区。')
    full = Viewport(0, 0, w, h)
    if abs(w/h-16/9) <= .03:
        return full
    wide = w/h > 16/9
    size = w if wide else h
    fitted = round(h*16/9) if wide else round(w*9/16)
    expected = (size-fitted)//2
    if expected < 3:
        return full
    # A complete scanline is black; dark artwork alone is insufficient.
    dark = np.mean(np.max(raw, axis=2) <= 8, axis=0 if wide else 1) >= .999
    visible = np.flatnonzero(~dark)
    if not len(visible):
        return full
    start, end = int(visible[0]), int(visible[-1])+1
    if abs(start-expected) > 3 or abs((size-end)-expected) > 3:
        return full
    if abs((end-start)-fitted) > 4:
        return full
    return Viewport(start, 0, end-start, h) if wide else Viewport(0, start, w, end-start)


def crop_viewport(raw, viewport):
    return raw[viewport.y:viewport.y+viewport.height,
               viewport.x:viewport.x+viewport.width].copy()
