"""User settings, saved as JSON in the user's app-data folder."""

from __future__ import annotations

import json
import os
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


@dataclass
class Settings:
    api_key: str = ""
    model: str = DEFAULT_MODEL
    interval: float = 1.5
    monitor: int = 1
    region: list[int] | None = None  # [left, top, width, height]; None = whole monitor
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

    def effective_api_key(self) -> str:
        return self.api_key.strip() or os.environ.get("ANTHROPIC_API_KEY", "")


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
    if s.region is not None and (s.region[2] < 20 or s.region[3] < 20):
        problems.append("The selected screen area is too small.")
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
