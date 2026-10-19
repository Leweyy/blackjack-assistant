"""Hi-Lo card counting: running count, true count, bet sizing, and round tracking."""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

from .strategy import card_value

# Rough rule of thumb for Hi-Lo: each +1 of true count is worth ~0.5% to the
# player, and the base game (good rules, basic strategy) starts ~0.5% down.
EDGE_PER_TRUE_COUNT = 0.5
BASE_HOUSE_EDGE = 0.5


def hilo_value(card: str) -> int:
    v = card_value(card)
    if v <= 6:
        return 1
    if v >= 10:  # tens and aces (ace = 11)
        return -1
    return 0


def hilo_sum(cards: list[str]) -> int:
    total = 0
    for c in cards:
        try:
            total += hilo_value(c)
        except ValueError:
            pass  # unreadable card: ignore rather than crash the count
    return total


@dataclass(frozen=True)
class CountSnapshot:
    running: int
    cards_seen: int
    decks_remaining: float
    true_count: float

    @property
    def edge_percent(self) -> float:
        return EDGE_PER_TRUE_COUNT * self.true_count - BASE_HOUSE_EDGE


@dataclass(frozen=True)
class BetAdvice:
    units: int
    amount: float | None
    headline: str


class HiLoCounter:
    """Thread-safe Hi-Lo counter for one shoe."""

    def __init__(self, decks: int = 8):
        self.decks = decks
        self._lock = threading.Lock()
        self._running = 0
        self._seen = 0

    def reset(self) -> None:
        with self._lock:
            self._running = 0
            self._seen = 0

    def add(self, cards: list[str]) -> None:
        with self._lock:
            self._running += hilo_sum(cards)
            self._seen += len(cards)

    def snapshot(self, extra_cards: list[str] = ()) -> CountSnapshot:
        """Current count, optionally including cards on the table not yet added."""
        with self._lock:
            running = self._running + hilo_sum(list(extra_cards))
            seen = self._seen + len(extra_cards)
        # Never estimate below half a deck so the true count can't blow up late in a shoe.
        remaining = max(0.5, self.decks - seen / 52)
        return CountSnapshot(running, seen, remaining, running / remaining)


def bet_advice(true_count: float, max_units: int = 8, unit: float | None = None) -> BetAdvice:
    """Standard 1-to-N bet ramp: min bet until TC +2, then 2 units per extra true count."""
    tc = math.floor(true_count)
    units = 1 if tc < 2 else min(max_units, 2 * (tc - 1))
    amount = units * unit if unit else None
    if units > 1:
        headline = f"BET {units} UNITS"
    elif tc <= -2:
        headline = "MIN BET / SIT OUT"
    else:
        headline = "MIN BET"
    return BetAdvice(units, amount, headline)


def table_cards(state) -> list[str]:
    """Every face-up card on the table in a TableState."""
    cards = list(state.dealer_cards)
    for hand in state.player_hands:
        cards.extend(hand)
    cards.extend(state.other_players_cards)
    return cards


class RoundTracker:
    """Feeds each round's cards into the counter exactly once.

    A round is counted when the screen shows it finished (all cards face up),
    or, if that screen was missed, when the next betting phase starts, using
    the last snapshot of the round. A detected shuffle resets the count.
    """

    def __init__(self, counter: HiLoCounter):
        self.counter = counter
        self._round_cards: list[str] = []
        self._counted = False
        self._shuffling = False
        self._lock = threading.Lock()

    def observe(self, state) -> None:
        with self._lock:
            self._observe(state)

    def _observe(self, state) -> None:
        if state.shuffle_detected and not self._shuffling:
            self.counter.reset()
            self._round_cards = []
            self._counted = False
        self._shuffling = state.shuffle_detected

        cards = table_cards(state) if state.table_visible else []
        if not state.table_visible:
            return
        if state.is_betting_phase or not cards:
            if self._round_cards and not self._counted:
                self.counter.add(self._round_cards)
            self._round_cards = []
            self._counted = False
            return
        if self._counted:
            return
        # Cards only accumulate during a round; keep the fullest view of it.
        if len(cards) >= len(self._round_cards):
            self._round_cards = cards
        if state.round_complete:
            self.counter.add(self._round_cards)
            self._counted = True

    def reset(self) -> None:
        """Start a new shoe (safe to call from another thread)."""
        with self._lock:
            self.counter.reset()
            self._round_cards = []
            self._counted = False

    def snapshot(self) -> CountSnapshot:
        """Count including cards of the round in progress (for mid-hand decisions)."""
        with self._lock:
            pending = [] if self._counted else list(self._round_cards)
        return self.counter.snapshot(pending)
