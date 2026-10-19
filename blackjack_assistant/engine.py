"""The watch loop: capture -> read table -> count -> advise. Shared by the CLI and the app."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Callable

import anthropic

from .advisor import Advice, BetSettings, advise
from .capture import MAX_SIDE, CaptureError, ChangeDetector, mark_seat, to_jpeg
from .counting import HiLoCounter, RoundTracker
from .strategy import Rules
from .vision import VisionError

Emit = Callable[["Advice | str"], None]


def save_frame(save_dir: Path, jpeg: bytes, table, took: float, seat_marked: bool = False) -> None:
    """Keep the screenshot as sent and what the model read, for building a test set.

    To label a frame, copy NAME.json to NAME.label.json and correct the cards.
    """
    try:
        save_dir.mkdir(parents=True, exist_ok=True)
        name = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        (save_dir / f"{name}.jpg").write_bytes(jpeg)
        (save_dir / f"{name}.json").write_text(
            json.dumps({**table.model_dump(), "seconds": round(took, 2), "seat_marked": seat_marked},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
    except OSError:
        pass  # saving is a debugging aid; never let it break play


def watch_loop(grabber, reader, rules, interval, emit: Emit, stop: threading.Event,
               tracker: RoundTracker | None = None, bets: BetSettings = BetSettings(),
               seat: "list[float] | Callable[[], list[float] | None] | None" = None,
               max_in_flight: int = 2, save_dir: Path | None = None):
    """Capture every `interval` seconds and read changed frames, up to `max_in_flight` at once.

    A read takes a few seconds, so waiting for each one before taking the next
    screenshot means a card dealt just after a capture isn't seen until two reads
    later. Overlapping reads roughly halves that delay. Results are applied in
    capture order: a read that finishes after a newer one has been shown is dropped.
    """
    get_seat = seat if callable(seat) else (lambda: seat)
    detector = ChangeDetector()
    lock = threading.Lock()
    slots = threading.BoundedSemaphore(max_in_flight)
    state = {"applied": 0, "last_key": None}
    seq = 0

    def read(frame_seq: int, img, seat_box, captured_at: float):
        try:
            if seat_box:
                img = mark_seat(img, seat_box)
            jpeg = to_jpeg(img, getattr(reader, "max_side", MAX_SIDE))
            table = reader.read(jpeg, seat_marked=bool(seat_box))
            took = time.monotonic() - captured_at
            if save_dir:
                save_frame(save_dir, jpeg, table, took, bool(seat_box))
            with lock:
                if frame_seq < state["applied"] or stop.is_set():
                    return  # a newer screenshot has already been shown
                state["applied"] = frame_seq
                count = None
                if tracker:
                    tracker.observe(table)
                    count = tracker.snapshot()
                advice = advise(table, rules, count, bets)
                if advice != state["last_key"]:
                    emit(advice)
                    state["last_key"] = advice
                emit(f"Updated {time.strftime('%H:%M:%S')}  ·  read in {took:.1f} s")
        except anthropic.AuthenticationError:
            emit("Error: API key was rejected. Check it in Settings.")
            stop.set()
        except (VisionError, anthropic.APIError) as e:
            # Keep going: a network blip usually recovers.
            emit(f"Error: {e}")
        except Exception as e:  # noqa: BLE001 - never let a worker die silently
            emit(f"Error: {e}")
        finally:
            slots.release()

    pool = ThreadPoolExecutor(max_workers=max_in_flight, thread_name_prefix="read")
    try:
        while not stop.is_set():
            started = time.monotonic()
            # Only look at the screen when a read slot is free, so a change seen while
            # both slots are busy is still "new" on the next tick instead of skipped.
            if slots.acquire(blocking=False):
                try:
                    img = grabber.grab()
                    if detector.changed(img):
                        seq += 1
                        pool.submit(read, seq, img, get_seat(), started)
                    else:
                        slots.release()
                except CaptureError as e:
                    slots.release()
                    emit(f"Error: {e}")  # e.g. window minimised: keep trying
            stop.wait(max(0.0, interval - (time.monotonic() - started)))
    finally:
        # Don't wait for reads still in flight: stopping should be instant, and their
        # results are ignored once `stop` is set.
        pool.shutdown(wait=False, cancel_futures=True)


class Session:
    """One run of the watch loop on a background thread."""

    def __init__(self, *, reader, rules: Rules, bets: BetSettings, interval: float,
                 make_grabber: Callable[[], object], counting: bool = True, decks: int = 8, emit: Emit,
                 seat: list[float] | None = None, max_in_flight: int = 2, save_dir: Path | None = None,
                 on_exit: Callable[[], None] | None = None):
        self.reader = reader
        self.save_dir = save_dir
        self.tracker = RoundTracker(HiLoCounter(decks=decks)) if counting else None
        self._args = (make_grabber, rules, interval, emit, bets)
        self.seat = seat  # can be changed while running (e.g. "Mark seat" in the overlay)
        self.max_in_flight = max_in_flight
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._on_exit = on_exit

    def start(self) -> None:
        make_grabber, rules, interval, emit, bets = self._args

        def run():
            try:
                grabber = make_grabber()  # mss handles are per-thread, so create it here
                watch_loop(grabber, self.reader, rules, interval, emit, self._stop, self.tracker, bets,
                           seat=lambda: self.seat, max_in_flight=self.max_in_flight, save_dir=self.save_dir)
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
