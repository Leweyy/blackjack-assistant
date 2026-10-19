"""User settings, saved as JSON in the user's app-data folder."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .advisor import BetSettings
from .capture import Region
from .strategy import Rules
from .vision import DEFAULT_MODEL


def config_dir() -> Path:
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "BlackjackAssistant"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "blackjack-assistant"


def config_path() -> Path:
    return config_dir() / "settings.json"


PROVIDERS = ("anthropic", "local")


@dataclass
class Settings:
    provider: str = "anthropic"  # who reads the cards: "anthropic" (Claude) or "local" (Ollama/vLLM...)
    api_key: str = ""
    model: str = DEFAULT_MODEL
    local_url: str = "http://localhost:11434/v1"  # OpenAI-compatible endpoint of the local server
    local_model: str = ""
    local_api_key: str = ""  # only if the server requires one (e.g. vLLM --api-key)
    local_max_side: int = 1024  # longest image side sent to a local model
    save_frames: bool = False  # keep every screenshot sent + the model's answer, for comparing models
    interval: float = 1.5
    fast_reads: bool = True  # overlap up to two reads: advice sooner, up to ~2x the API calls
    monitor: int = 1
    capture: str = "monitor"  # what to watch: "monitor", "region" or "window"
    region: list[int] | None = None  # [left, top, width, height], used when capture == "region"
    window: dict | None = None  # {"handle": int, "title": str}, used when capture == "window"
    seat: list[float] | None = None  # player's seat box [x, y, w, h] as fractions of the captured image; None = auto
    dealer_hits_soft_17: bool = False
    double_after_split: bool = True
    surrender_allowed: bool = True
    counting: bool = True
    decks: int = 8
    unit: float | None = None
    max_units: int = 8

    def rules(self) -> Rules:
        return Rules(self.dealer_hits_soft_17, self.double_after_split, self.surrender_allowed)

    def bets(self) -> BetSettings:
        return BetSettings(unit=self.unit, max_units=self.max_units)

    def screen_region(self) -> Region | None:
        return Region(*self.region) if self.region else None

    def grabber(self):
        """A screen grabber for the chosen capture mode. Create it on the thread that uses it."""
        from .capture import make_grabber
        return make_grabber(self.capture, self.screen_region(), self.monitor, self.window)

    def effective_api_key(self) -> str:
        return self.api_key.strip() or os.environ.get("ANTHROPIC_API_KEY", "")

    def reader(self):
        """The card reader for the chosen provider."""
        if self.provider == "local":
            from .local_vision import LocalReader
            return LocalReader(self.local_url.strip(), self.local_model.strip(), self.local_api_key.strip(),
                               self.local_max_side)
        import anthropic

        from .vision import TableReader
        return TableReader(model=self.model, client=anthropic.Anthropic(api_key=self.effective_api_key() or None))

    def missing_credentials(self) -> str | None:
        """Why the assistant can't start reading yet, or None."""
        if self.provider == "local":
            if not self.local_url.strip():
                return "Enter the address of your local model server in Settings → Connection."
            if not self.local_model.strip():
                return "Choose a local model in Settings → Connection."
            return None
        if not self.effective_api_key():
            return "Add your Anthropic API key in Settings → Connection first."
        return None


def frames_dir() -> Path:
    return config_dir() / "frames"


CAPTURE_MODES = ("monitor", "region", "window")


def clean_seat(seat) -> list[float] | None:
    """A valid [x, y, w, h] seat box (fractions of the image), or None.

    Seats saved by 0.4.0 were a single point [x, y]; they become a small box around it.
    """
    if not isinstance(seat, list) or not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) for v in seat):
        return None
    if len(seat) == 2:
        x, y = seat
        seat = [x - 0.06, y - 0.08, 0.12, 0.16]
    if len(seat) != 4:
        return None
    x, y, w, h = seat
    x0, y0 = max(0.0, x), max(0.0, y)
    x1, y1 = min(1.0, x + w), min(1.0, y + h)
    if x1 - x0 < 0.01 or y1 - y0 < 0.01:
        return None
    return [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]


def from_dict(data) -> Settings:
    """Build Settings from a dict; missing, unknown or wrongly-typed entries fall back to defaults."""
    if not isinstance(data, dict):
        return Settings()
    defaults = Settings()
    kwargs = {}
    for f in fields(Settings):
        if f.name not in data:
            continue
        value, default = data[f.name], getattr(defaults, f.name)
        if isinstance(default, bool) or isinstance(value, bool):
            ok = isinstance(value, bool) and isinstance(default, bool)
        else:
            # Only accept values of a sensible type so a hand-edited file can't crash the app.
            ok = default is None or value is None or isinstance(value, type(default)) or (
                isinstance(default, float) and isinstance(value, int))
        if ok:
            kwargs[f.name] = value
    s = Settings(**kwargs)
    if s.region is not None and not (isinstance(s.region, list) and len(s.region) == 4
                                     and all(isinstance(v, int) for v in s.region)):
        s.region = None
    if s.window is not None and not (isinstance(s.window, dict) and isinstance(s.window.get("handle"), int)
                                     and isinstance(s.window.get("title"), str)):
        s.window = None
    s.seat = clean_seat(s.seat)
    if "capture" not in data:  # settings saved before window capture existed
        s.capture = "region" if s.region else "monitor"
    if s.capture not in CAPTURE_MODES:
        s.capture = "monitor"
    if s.provider not in PROVIDERS:
        s.provider = "anthropic"
    return s


def validate(s: Settings) -> list[str]:
    """Human-readable problems with the settings; empty when they're usable."""
    problems = []
    if not 1 <= s.decks <= 8:
        problems.append("Decks must be between 1 and 8.")
    if s.max_units < 1:
        problems.append("Max bet must be at least 1 unit.")
    if s.interval < 0.5:
        problems.append("Check interval must be at least 0.5 seconds.")
    if s.monitor < 1:
        problems.append("Monitor must be 1 or higher.")
    if s.unit is not None and s.unit <= 0:
        problems.append("Betting unit must be greater than 0.")
    if not 256 <= s.local_max_side <= 2048:
        problems.append("Local image size must be between 256 and 2048 pixels.")
    if s.provider == "local" and s.local_url.strip() and not s.local_url.strip().startswith(("http://", "https://")):
        problems.append("The local server address must start with http:// or https://.")
    if s.region is not None and (s.region[2] < 20 or s.region[3] < 20):
        problems.append("The selected screen area is too small.")
    if s.capture == "region" and not s.region:
        problems.append("Select a table area in Screen, or choose another capture option.")
    if s.capture == "window":
        if not s.window:
            problems.append("Choose a window in Screen, or choose another capture option.")
        elif sys.platform != "win32":
            problems.append("Window capture is only available on Windows. Use a table area instead.")
    return problems


def load(path: Path | None = None) -> Settings:
    path = path or config_path()
    try:
        return from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return Settings()


def save(settings: Settings, path: Path | None = None) -> Path:
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return path
