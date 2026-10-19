"""Backend for the desktop app.

The Electron front end starts this process and talks to it with one JSON object
per line: requests on stdin, responses and events on stdout.

  request:   {"id": 1, "method": "start", "params": {}}
  response:  {"id": 1, "result": ...}  or  {"id": 1, "error": "message"}
  event:     {"event": "advice" | "status" | "error" | "stopped", "data": ...}

stdout is reserved for the protocol; anything else goes to stderr.
"""

from __future__ import annotations

import json
import sys
import threading
from dataclasses import asdict
from typing import Any, TextIO

import anthropic

from . import config
from .advisor import Advice, advise
from .counting import HiLoCounter, RoundTracker
from .engine import Session
from .vision import VisionError


class RequestError(Exception):
    """An error whose message is shown to the user as-is."""


def png_data_url(img) -> str:
    import base64
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def advice_to_dict(a: Advice) -> dict:
    d = asdict(a)
    d["action"] = a.action.name if a.action else None
    return d


class Server:
    def __init__(self, out: TextIO):
        self._out = out
        self._lock = threading.Lock()
        self._session: Session | None = None
        self._config_path = None  # override in tests

    # ---- output -------------------------------------------------------------

    def send(self, msg: dict) -> None:
        line = json.dumps(msg, ensure_ascii=False)
        with self._lock:
            self._out.write(line + "\n")
            self._out.flush()

    def event(self, name: str, data: Any = None) -> None:
        self.send({"event": name, "data": data})

    # ---- requests -----------------------------------------------------------

    def handle_line(self, line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            req = json.loads(line)
            req_id, method, params = req.get("id"), req["method"], req.get("params") or {}
        except (ValueError, KeyError, AttributeError):
            self.send({"id": None, "error": "Malformed request"})
            return

        handler = getattr(self, f"rpc_{method}", None)
        if handler is None:
            self.send({"id": req_id, "error": f"Unknown method: {method}"})
            return
        slow = method in ("test_screenshot", "capture_bounds", "local_models")

        def run():
            try:
                self.send({"id": req_id, "result": handler(**params)})
            except RequestError as e:
                self.send({"id": req_id, "error": str(e)})
            except Exception as e:  # noqa: BLE001 - never let one request kill the backend
                print(f"Error handling {method}: {e!r}", file=sys.stderr)
                self.send({"id": req_id, "error": f"Unexpected error: {e}"})

        if slow:
            threading.Thread(target=run, daemon=True).start()
        else:
            run()

    def serve(self, inp: TextIO) -> None:
        self.event("ready")
        for line in inp:
            self.handle_line(line)
        self.rpc_stop()

    # ---- methods ------------------------------------------------------------

    def rpc_ping(self) -> str:
        return "pong"

    def rpc_get_settings(self) -> dict:
        s = config.load(self._config_path)
        return {"settings": asdict(s), "config_path": str(self._config_path or config.config_path()),
                "frames_dir": str(config.frames_dir()),
                "env_api_key": bool(config.Settings().effective_api_key())}

    def rpc_local_models(self, url: str, api_key: str = "") -> list[str]:
        """Models offered by a local server; doubles as a connection test."""
        from .local_vision import list_models
        try:
            return list_models(url.strip(), api_key.strip())
        except VisionError as e:
            raise RequestError(str(e)) from e

    def rpc_save_settings(self, settings: dict) -> dict:
        s = config.from_dict(settings)
        problems = config.validate(s)
        if problems:
            raise RequestError(" ".join(problems))
        try:
            config.save(s, self._config_path)
        except OSError as e:
            raise RequestError(f"Couldn't save settings: {e}") from e
        return asdict(s)

    def rpc_start(self) -> bool:
        if self._session and self._session.running:
            return True
        s = config.load(self._config_path)
        problems = config.validate(s)
        if problems:
            raise RequestError(" ".join(problems))
        if missing := s.missing_credentials():
            raise RequestError(missing)

        def emit(item):
            if isinstance(item, Advice):
                self.event("advice", advice_to_dict(item))
            elif item.startswith("Error"):
                self.event("error", item.removeprefix("Error: "))
            else:
                self.event("status", item)

        session: Session | None = None

        def on_exit():
            # A session replaced by a newer one (stop then quick restart) exits silently.
            if self._session is session:
                self._session = None
                self.event("stopped")

        session = Session(reader=s.reader(), save_dir=config.frames_dir() if s.save_frames else None,
                          rules=s.rules(), bets=s.bets(),
                          interval=s.interval, make_grabber=s.grabber,
                          counting=s.counting, decks=s.decks, emit=emit, seat=s.seat,
                          max_in_flight=2 if s.fast_reads else 1, on_exit=on_exit)
        self._session = session
        session.start()
        return True

    def rpc_stop(self) -> bool:
        if self._session:
            self._session.stop()
        return True

    def rpc_reset_count(self) -> bool:
        if self._session:
            self._session.reset_count()
        return True

    def rpc_capture_bounds(self) -> list[int]:
        """Where the watched area currently is on screen: [left, top, width, height] in capture pixels."""
        from .capture import CaptureError

        s = config.load(self._config_path)
        try:
            b = s.grabber().bounds()  # created and used on this request's thread, as mss requires
        except CaptureError as e:
            raise RequestError(str(e)) from e
        return [b.left, b.top, b.width, b.height]

    def rpc_set_seat(self, seat: list[float] | None) -> list[float] | None:
        """Save the player's seat box, and apply it straight away if the assistant is running."""
        s = config.load(self._config_path)
        s.seat = config.clean_seat(seat) if seat is not None else None
        if seat is not None and s.seat is None:
            raise RequestError("That box is too small. Drag a box around your cards.")
        try:
            config.save(s, self._config_path)
        except OSError as e:
            raise RequestError(f"Couldn't save settings: {e}") from e
        if self._session:
            self._session.seat = s.seat
        return s.seat

    def rpc_test_screenshot(self, path: str) -> dict:
        from PIL import Image, UnidentifiedImageError

        from .capture import mark_seat, to_jpeg

        s = config.load(self._config_path)
        if missing := s.missing_credentials():
            raise RequestError(missing)
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
        except (OSError, UnidentifiedImageError) as e:
            raise RequestError(f"Couldn't open that image: {e}") from e
        if s.seat:
            img = mark_seat(img, s.seat)
        try:
            reader = s.reader()
            state = reader.read(to_jpeg(img, getattr(reader, "max_side", 1568)), seat_marked=bool(s.seat))
        except anthropic.AuthenticationError as e:
            raise RequestError("The API key was rejected.") from e
        except (VisionError, anthropic.APIError) as e:
            raise RequestError(str(e)) from e
        tracker = RoundTracker(HiLoCounter(s.decks)) if s.counting else None
        if tracker:
            tracker.observe(state)
        a = advise(state, s.rules(), tracker.snapshot() if tracker else None, s.bets())
        preview = img.copy()
        preview.thumbnail((640, 640))
        return {"advice": advice_to_dict(a), "table": state.model_dump(), "image": png_data_url(preview)}


def enable_dpi_awareness() -> None:
    """Capture in physical pixels on scaled Windows displays (matches the region picker)."""
    if sys.platform != "win32":
        return
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        pass


def self_test() -> int:
    """Used by CI on the packaged backend: exercise imports and screen capture."""
    from .capture import ScreenGrabber, to_jpeg
    enable_dpi_awareness()
    assert to_jpeg(ScreenGrabber().grab())
    if sys.platform == "win32":
        # Exercise the window-capture calls (ctypes signatures only show up on real Windows).
        from .windows import Win32Windows
        api = Win32Windows()
        handle = api.find("Program Manager")  # the desktop window, present in every session
        if handle:
            assert api.is_window(handle)
            api.is_minimized(handle)
            api.rect(handle)
    anthropic.Anthropic(api_key="self-test")
    from .local_vision import LocalReader  # makes sure the openai package was bundled
    LocalReader("http://localhost:11434/v1", "self-test")
    print("self-test ok", file=sys.stderr)
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    enable_dpi_awareness()
    # Protocol is UTF-8 JSON lines regardless of the Windows code page.
    stdin = open(sys.stdin.fileno(), "r", encoding="utf-8", closefd=False)
    stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", closefd=False)
    sys.stdout = sys.stderr  # stray prints must not corrupt the protocol
    Server(stdout).serve(stdin)
    return 0


if __name__ == "__main__":
    sys.exit(main())
