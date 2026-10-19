"""Finding and measuring top-level windows on Windows (ctypes, no extra dependencies)."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from .capture import Region

DWMWA_EXTENDED_FRAME_BOUNDS = 9


class Win32Windows:
    def __init__(self):
        self.user32 = ctypes.windll.user32
        self.dwmapi = ctypes.windll.dwmapi
        self.user32.IsWindow.argtypes = [wintypes.HWND]
        self.user32.IsIconic.argtypes = [wintypes.HWND]
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    def is_window(self, handle: int) -> bool:
        return bool(self.user32.IsWindow(handle))

    def is_minimized(self, handle: int) -> bool:
        return bool(self.user32.IsIconic(handle))

    def rect(self, handle: int) -> Region:
        r = wintypes.RECT()
        # The extended frame bounds exclude the invisible resize border Windows 10/11 adds,
        # so the capture doesn't include a strip of whatever is behind the window.
        if self.dwmapi.DwmGetWindowAttribute(wintypes.HWND(handle), DWMWA_EXTENDED_FRAME_BOUNDS,
                                             ctypes.byref(r), ctypes.sizeof(r)) != 0:
            self.user32.GetWindowRect(handle, ctypes.byref(r))
        return Region(r.left, r.top, r.right - r.left, r.bottom - r.top)

    def title(self, handle: int) -> str:
        n = self.user32.GetWindowTextLengthW(handle)
        buf = ctypes.create_unicode_buffer(n + 1)
        self.user32.GetWindowTextW(handle, buf, n + 1)
        return buf.value

    def find(self, title: str) -> int | None:
        """A visible window with exactly this title, else one whose title contains it."""
        exact: list[int] = []
        partial: list[int] = []
        wanted = title.casefold()

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd, _lparam):
            if self.user32.IsWindowVisible(hwnd):
                t = self.title(hwnd)
                if t == title:
                    exact.append(hwnd)
                elif t and (wanted in t.casefold() or t.casefold() in wanted):
                    partial.append(hwnd)
            return True

        self.user32.EnumWindows(callback, 0)
        matches = exact or partial
        return int(matches[0]) if matches else None
