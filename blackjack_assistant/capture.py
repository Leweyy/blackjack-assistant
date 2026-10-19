"""Screen capture and change detection."""

from __future__ import annotations

import io
from dataclasses import dataclass

import mss
from PIL import Image, ImageChops

# Longest side sent to the API. Cards stay legible and requests stay cheap.
MAX_SIDE = 1568


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    @classmethod
    def parse(cls, text: str) -> "Region":
        """Parse 'left,top,width,height'."""
        parts = [int(p) for p in text.split(",")]
        if len(parts) != 4:
            raise ValueError("Region must be left,top,width,height")
        return cls(*parts)


class ScreenGrabber:
    def __init__(self, region: Region | None = None, monitor: int = 1):
        self.region = region
        self.monitor = monitor
        self._sct = mss.MSS() if hasattr(mss, "MSS") else mss.mss()

    def grab(self) -> Image.Image:
        if self.region:
            area = {"left": self.region.left, "top": self.region.top,
                    "width": self.region.width, "height": self.region.height}
        else:
            area = self._sct.monitors[self.monitor]
        shot = self._sct.grab(area)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def to_png(img: Image.Image) -> bytes:
    img = img.copy()
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


class ChangeDetector:
    """Says whether the screen changed enough to be worth another API call."""

    def __init__(self, threshold: float = 0.01):
        self.threshold = threshold
        self._last: Image.Image | None = None

    def changed(self, img: Image.Image) -> bool:
        small = img.convert("L").resize((160, 90))
        if self._last is None:
            self._last = small
            return True
        diff = ImageChops.difference(small, self._last).point(lambda p: 255 if p > 24 else 0)
        frac = sum(diff.histogram()[255:]) / (160 * 90)
        if frac >= self.threshold:
            self._last = small
            return True
        return False
