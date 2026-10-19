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
from .vision import TableReader, VisionError


class RequestError(Exception):
    """An error whose message is shown to the user as-is."""


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
        slow = method in ("test_screenshot",)

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
                "env_api_key": bool(config.Settings().effective_api_key())}

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
        if not s.effective_api_key():
            raise RequestError("Add your Anthropic API key in Settings → Connection first.")

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

        session = Session(api_key=s.effective_api_key(), model=s.model, rules=s.rules(), bets=s.bets(),
                          interval=s.interval, make_grabber=s.grabber,
                          counting=s.counting, decks=s.decks, emit=emit, on_exit=on_exit)
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

    def rpc_test_screenshot(self, path: str) -> dict:
        from PIL import Image, UnidentifiedImageError

        from .capture import to_png

        s = config.load(self._config_path)
        if not s.effective_api_key():
            raise RequestError("Add your Anthropic API key first.")
        try:
            with Image.open(path) as img:
                png = to_png(img.convert("RGB"))
        except (OSError, UnidentifiedImageError) as e:
            raise RequestError(f"Couldn't open that image: {e}") from e
        try:
            reader = TableReader(model=s.model, client=anthropic.Anthropic(api_key=s.effective_api_key()))
            state = reader.read(png)
        except anthropic.AuthenticationError as e:
            raise RequestError("The API key was rejected.") from e
        except (VisionError, anthropic.APIError) as e:
            raise RequestError(str(e)) from e
        tracker = RoundTracker(HiLoCounter(s.decks)) if s.counting else None
        if tracker:
            tracker.observe(state)
        a = advise(state, s.rules(), tracker.snapshot() if tracker else None, s.bets())
        return {"advice": advice_to_dict(a), "table": state.model_dump()}


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
    from .capture import ScreenGrabber, to_png
    enable_dpi_awareness()
    assert to_png(ScreenGrabber().grab())
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
