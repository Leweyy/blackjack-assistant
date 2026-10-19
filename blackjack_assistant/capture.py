"""Screen capture and change detection."""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from typing import Protocol

import mss
from PIL import Image, ImageChops, ImageDraw

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


class CaptureError(RuntimeError):
    """The screen couldn't be captured right now (e.g. the chosen window is minimised)."""


def _mss():
    return mss.MSS() if hasattr(mss, "MSS") else mss.mss()


class ScreenGrabber:
    def __init__(self, region: Region | None = None, monitor: int = 1):
        self.region = region
        self.monitor = monitor
        self._sct = _mss()

    def bounds(self) -> Region:
        """The screen rectangle being captured, in capture (physical) pixels."""
        if self.region:
            return self.region
        m = self._sct.monitors[self.monitor]
        return Region(m["left"], m["top"], m["width"], m["height"])

    def grab(self) -> Image.Image:
        b = self.bounds()
        shot = self._sct.grab({"left": b.left, "top": b.top, "width": b.width, "height": b.height})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


class WindowApi(Protocol):
    def is_window(self, handle: int) -> bool: ...
    def is_minimized(self, handle: int) -> bool: ...
    def rect(self, handle: int) -> Region: ...
    def find(self, title: str) -> int | None: ...


class WindowGrabber:
    """Captures one window wherever it is on screen, following moves and resizes.

    The window is found by its handle; if that window has gone (e.g. the
    browser was restarted) it is looked up again by title. The window has to
    be visible on screen, not minimised.
    """

    def __init__(self, handle: int, title: str, api: WindowApi | None = None):
        if api is None:
            if sys.platform != "win32":
                raise CaptureError("Window capture is only available on Windows. Use a table area instead.")
            from .windows import Win32Windows
            api = Win32Windows()
        self.api = api
        self.handle = handle
        self.title = title
        self._sct = _mss()

    def _resolve(self) -> int:
        if self.handle and self.api.is_window(self.handle):
            return self.handle
        found = self.api.find(self.title) if self.title else None
        if not found:
            raise CaptureError(f"Can't find the window “{self.title}”. Is it still open? "
                               "You can choose it again in Settings → Screen.")
        self.handle = found
        return found

    def bounds(self) -> Region:
        """Where the window currently is on screen (clipped to the screens), in capture pixels."""
        handle = self._resolve()
        if self.api.is_minimized(handle):
            raise CaptureError(f"The window “{self.title}” is minimised. Restore it so the table is visible.")
        r = self.api.rect(handle)
        screen = self._sct.monitors[0]  # bounding box of all monitors
        left, top = max(r.left, screen["left"]), max(r.top, screen["top"])
        right = min(r.left + r.width, screen["left"] + screen["width"])
        bottom = min(r.top + r.height, screen["top"] + screen["height"])
        if right - left < 20 or bottom - top < 20:
            raise CaptureError(f"The window “{self.title}” is off-screen.")
        return Region(left, top, right - left, bottom - top)

    def grab(self) -> Image.Image:
        b = self.bounds()
        shot = self._sct.grab({"left": b.left, "top": b.top, "width": b.width, "height": b.height})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def make_grabber(capture: str, region: Region | None = None, monitor: int = 1,
                 window: dict | None = None):
    """Grabber for the capture mode chosen in settings: 'monitor', 'region' or 'window'."""
    if capture == "window":
        if not window:
            raise CaptureError("No window chosen. Choose one in Settings → Screen.")
        return WindowGrabber(int(window.get("handle") or 0), str(window.get("title") or ""))
    if capture == "region":
        return ScreenGrabber(region=region)
    return ScreenGrabber(monitor=monitor)


SEAT_MARKER_COLOR = (255, 0, 255)


def mark_seat(img: Image.Image, seat: list[float] | tuple[float, ...]) -> Image.Image:
    """Copy of `img` with a magenta box labelled "YOU" around the player's seat.

    `seat` is [x, y, width, height] as fractions of the image. Drawing the seat onto
    the screenshot is the most reliable way to tell the vision model which hand is the
    player's at a table with several seats.
    """
    out = img.convert("RGB").copy()
    w, h = out.size
    x0, y0 = seat[0] * w, seat[1] * h
    x1, y1 = x0 + seat[2] * w, y0 + seat[3] * h
    line = max(2, round(min(w, h) / 220))
    d = ImageDraw.Draw(out)
    # Drawn just outside the box the player chose, so it never covers the cards inside it.
    pad = line + 1
    d.rectangle((x0 - pad - 1, y0 - pad - 1, x1 + pad + 1, y1 + pad + 1), outline=(0, 0, 0), width=line + 2)
    d.rectangle((x0 - pad, y0 - pad, x1 + pad, y1 + pad), outline=SEAT_MARKER_COLOR, width=line)
    size = max(12, round(min(w, h) / 30))
    try:
        from PIL import ImageFont
        font = ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 has no sized default font
        font = None
    label_y = y0 - pad - size // 2 - 6
    if label_y < size:  # no room above the box: put the label below it
        label_y = y1 + pad + size // 2 + 6
    d.text(((x0 + x1) / 2, label_y), "YOU", fill=SEAT_MARKER_COLOR, font=font, anchor="mm",
           stroke_width=max(2, size // 6), stroke_fill=(0, 0, 0))
    return out


def to_jpeg(img: Image.Image, max_side: int = MAX_SIDE) -> bytes:
    """Scaled-down JPEG for the API.

    JPEG at this quality keeps card indices sharp while being ~10x smaller than PNG
    for a video frame, which matters: the upload is part of every read's latency.
    """
    img = img.convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
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
