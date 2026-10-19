"""Screen capture and change detection."""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from typing import Protocol

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


class CaptureError(RuntimeError):
    """The screen couldn't be captured right now (e.g. the chosen window is minimised)."""


def _mss():
    return mss.MSS() if hasattr(mss, "MSS") else mss.mss()


class ScreenGrabber:
    def __init__(self, region: Region | None = None, monitor: int = 1):
        self.region = region
        self.monitor = monitor
        self._sct = _mss()

    def grab(self) -> Image.Image:
        if self.region:
            area = {"left": self.region.left, "top": self.region.top,
                    "width": self.region.width, "height": self.region.height}
        else:
            area = self._sct.monitors[self.monitor]
        shot = self._sct.grab(area)
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

    def grab(self) -> Image.Image:
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
        shot = self._sct.grab({"left": left, "top": top, "width": right - left, "height": bottom - top})
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
