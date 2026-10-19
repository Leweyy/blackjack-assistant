"""The watch loop: capture -> read table -> count -> advise. Shared by the CLI and the app."""

from __future__ import annotations

import threading
import time
from typing import Callable

import anthropic

from .advisor import Advice, BetSettings, advise
from .capture import ChangeDetector, ScreenGrabber, to_png
from .counting import HiLoCounter, RoundTracker
from .strategy import Rules
from .vision import TableReader, VisionError

Emit = Callable[["Advice | str"], None]


def watch_loop(grabber, reader, rules, interval, emit: Emit, stop: threading.Event,
               tracker: RoundTracker | None = None, bets: BetSettings = BetSettings()):
    detector = ChangeDetector()
    last_key = None
    while not stop.is_set():
        started = time.monotonic()
        try:
            img = grabber.grab()
            if detector.changed(img):
                emit("Reading table…")
                state = reader.read(to_png(img))
                count = None
                if tracker:
                    tracker.observe(state)
                    count = tracker.snapshot()
                advice = advise(state, rules, count, bets)
                key = (advice.headline, advice.detail, advice.count_line)
                if key != last_key:
                    emit(advice)
                    last_key = key
                emit(f"Updated {time.strftime('%H:%M:%S')}")
        except anthropic.AuthenticationError:
            emit("Error: API key was rejected. Check it in Settings.")
            stop.set()
            break
        except (VisionError, anthropic.APIError) as e:
            emit(f"Error: {e}")
        stop.wait(max(0.0, interval - (time.monotonic() - started)))


class Session:
    """One run of the watch loop on a background thread."""

    def __init__(self, *, api_key: str | None, model: str, rules: Rules, bets: BetSettings, interval: float,
                 region=None, monitor: int = 1, counting: bool = True, decks: int = 8, emit: Emit,
                 on_exit: Callable[[], None] | None = None):
        self.reader = TableReader(model=model, client=anthropic.Anthropic(api_key=api_key or None))
        self.tracker = RoundTracker(HiLoCounter(decks=decks)) if counting else None
        self._args = (region, monitor, rules, interval, emit, bets)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_exit = on_exit

    def start(self) -> None:
        region, monitor, rules, interval, emit, bets = self._args

        def run():
            try:
                grabber = ScreenGrabber(region=region, monitor=monitor)  # mss handles are per-thread
                watch_loop(grabber, self.reader, rules, interval, emit, self._stop, self.tracker, bets)
            except Exception as e:  # noqa: BLE001 - e.g. screen capture failing; report, don't die silently
                emit(f"Error: {e}")
            finally:
                self._stop.set()
                if self._on_exit:
                    self._on_exit()

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop.is_set()

    def reset_count(self) -> None:
        if self.tracker:
            self.tracker.reset()
