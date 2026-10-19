import pytest

from blackjack_assistant import capture
from blackjack_assistant.capture import CaptureError, Region, WindowGrabber, make_grabber


class FakeShot:
    def __init__(self, area):
        self.area = area
        self.size = (area["width"], area["height"])
        self.bgra = b"\x00" * (area["width"] * area["height"] * 4)


class FakeMss:
    monitors = [{"left": 0, "top": 0, "width": 1920, "height": 1080}]

    def __init__(self):
        self.grabbed = []

    def grab(self, area):
        self.grabbed.append(area)
        return FakeShot(area)


class FakeWindows:
    def __init__(self):
        self.windows = {7: ("Live Blackjack - Chrome", Region(100, 50, 800, 600), False)}

    def is_window(self, h):
        return h in self.windows

    def is_minimized(self, h):
        return self.windows[h][2]

    def rect(self, h):
        return self.windows[h][1]

    def find(self, title):
        return next((h for h, (t, _, _) in self.windows.items() if title in t), None)


@pytest.fixture
def grabber(monkeypatch):
    monkeypatch.setattr(capture, "_mss", FakeMss)
    api = FakeWindows()
    return WindowGrabber(7, "Live Blackjack - Chrome", api=api), api


def test_follows_window_position(grabber):
    g, api = grabber
    assert g.grab().size == (800, 600)
    api.windows[7] = ("Live Blackjack - Chrome", Region(300, 200, 640, 480), False)
    g.grab()
    assert g._sct.grabbed[-1] == {"left": 300, "top": 200, "width": 640, "height": 480}


def test_clips_to_screen(grabber):
    g, api = grabber
    api.windows[7] = ("Live Blackjack - Chrome", Region(1600, -20, 800, 600), False)
    g.grab()
    assert g._sct.grabbed[-1] == {"left": 1600, "top": 0, "width": 320, "height": 580}


def test_reopened_window_found_by_title(grabber):
    g, api = grabber
    api.windows = {99: ("Live Blackjack - Chrome", Region(0, 0, 500, 400), False)}
    g.grab()
    assert g.handle == 99


def test_errors(grabber):
    g, api = grabber
    api.windows[7] = ("Live Blackjack - Chrome", Region(0, 0, 500, 400), True)
    with pytest.raises(CaptureError, match="minimised"):
        g.grab()
    api.windows[7] = ("Live Blackjack - Chrome", Region(5000, 5000, 500, 400), False)
    with pytest.raises(CaptureError, match="off-screen"):
        g.grab()
    api.windows = {}
    with pytest.raises(CaptureError, match="Can't find"):
        g.grab()


def test_make_grabber_requires_window():
    with pytest.raises(CaptureError, match="No window chosen"):
        make_grabber("window", window=None)


def test_mark_seat_draws_ring_at_point():
    from PIL import Image

    from blackjack_assistant.capture import SEAT_MARKER_COLOR, mark_seat

    img = Image.new("RGB", (1000, 600), (10, 90, 40))
    out = mark_seat(img, [0.5, 0.75])
    assert img.getpixel((500, 450)) == (10, 90, 40)  # original untouched
    r = int(600 * 0.12)
    ring = [out.getpixel((500 + dx, 450)) for dx in range(r - 6, r + 6)]
    assert SEAT_MARKER_COLOR in ring
    assert out.getpixel((500, 450)) == (10, 90, 40)  # centre left clear so cards stay visible


def test_watch_loop_marks_seat_for_reader():
    import threading

    from PIL import Image

    from blackjack_assistant.engine import watch_loop
    from blackjack_assistant.strategy import Rules

    stop = threading.Event()
    calls = []

    class Grabber:
        def grab(self):
            return Image.new("RGB", (400, 300), "green")

    class Reader:
        def read(self, png, seat_marked=False):
            calls.append(seat_marked)
            stop.set()
            raise capture.CaptureError("stop here")

    watch_loop(Grabber(), Reader(), Rules(), 0.01, lambda _x: None, stop, seat=[0.5, 0.5])
    assert calls == [True]
