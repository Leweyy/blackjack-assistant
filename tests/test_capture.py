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


def test_mark_seat_draws_box_outside_area():
    from PIL import Image

    from blackjack_assistant.capture import SEAT_MARKER_COLOR, mark_seat

    img = Image.new("RGB", (1000, 600), (10, 90, 40))
    out = mark_seat(img, [0.4, 0.5, 0.2, 0.25])  # x 400-600, y 300-450
    assert img.getpixel((400, 380)) == (10, 90, 40)  # original untouched
    left_edge = [out.getpixel((x, 380)) for x in range(385, 400)]
    assert SEAT_MARKER_COLOR in left_edge
    assert out.getpixel((402, 380)) == (10, 90, 40)  # inside the box stays clear
    assert out.getpixel((500, 380)) == (10, 90, 40)


class _Grabber:
    def __init__(self, frames):
        self.frames = frames

    def grab(self):
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]


def _run_loop(reader, frames, **kw):
    import threading

    from blackjack_assistant.engine import watch_loop
    from blackjack_assistant.strategy import Rules

    stop = threading.Event()
    reader.stop = stop
    threading.Timer(5, stop.set).start()  # safety net so a bug can't hang the test run
    emitted = []
    watch_loop(_Grabber(frames), reader, Rules(), 0.01, emitted.append, stop, **kw)
    return emitted


def _frame(color):
    from PIL import Image
    return Image.new("RGB", (400, 300), color)


def _table(dealer):
    from blackjack_assistant.vision import TableState
    return TableState(table_visible=True, dealer_cards=[dealer], player_hands=[["9♥", "5♠"]], player_hand_totals=[], dealer_total_shown="", active_hand_index=0,
                      is_player_turn=True, available_actions=[], other_players_cards=[], is_betting_phase=False,
                      round_complete=False, shuffle_detected=False, insurance_offered=False, confident=True)


def test_watch_loop_marks_seat_for_reader():
    calls = []

    class Reader:
        def read(self, jpeg, seat_marked=False):
            calls.append(seat_marked)
            self.stop.set()
            return _table("6♣")

    _run_loop(Reader(), [_frame("green")], seat=[0.4, 0.5, 0.2, 0.2])
    assert calls == [True]


def test_watch_loop_overlaps_reads_and_drops_stale_results():
    import threading

    from blackjack_assistant.advisor import Advice

    release_first = threading.Event()

    class Reader:
        def __init__(self):
            self.n = 0

        def read(self, jpeg, seat_marked=False):
            self.n += 1
            if self.n == 1:  # first read is slow...
                release_first.wait(3)
                return _table("2♦")
            # ...the second, newer frame comes back first; the old one finishes afterwards.
            threading.Timer(0.3, release_first.set).start()
            threading.Timer(1.0, self.stop.set).start()
            return _table("10♣")

    emitted = _run_loop(Reader(), [_frame("green"), _frame("white")])
    shown = [e.dealer_cards for e in emitted if isinstance(e, Advice)]
    assert shown == [["10♣"]]  # the stale result for the older frame was dropped
