"""Blackjack basic strategy engine.

Pure functions, no I/O. Charts follow standard multi-deck (4-8 deck) basic
strategy, with switches for the common rule variations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Action(str, Enum):
    HIT = "HIT"
    STAND = "STAND"
    DOUBLE = "DOUBLE"
    SPLIT = "SPLIT"
    SURRENDER = "SURRENDER"
    INSURANCE = "TAKE INSURANCE"
    NO_INSURANCE = "NO INSURANCE"


@dataclass(frozen=True)
class Rules:
    dealer_hits_soft_17: bool = False
    double_after_split: bool = True
    surrender_allowed: bool = True


RANK_VALUES = {
    "A": 11, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9,
    "10": 10, "J": 10, "Q": 10, "K": 10,
}


def normalize_rank(card: str) -> str:
    """Turn '10♠', 'Ten', 't', 'kh', 'Ace' etc. into a rank key of RANK_VALUES."""
    c = card.strip().upper()
    for suit in "♠♣♥♦SCHD":
        if len(c) > 1 and c.endswith(suit):
            c = c[:-1].strip()
            break
    aliases = {"T": "10", "ACE": "A", "KING": "K", "QUEEN": "Q", "JACK": "J",
               "TEN": "10", "1": "A", "11": "A"}
    c = aliases.get(c, c)
    if c not in RANK_VALUES:
        raise ValueError(f"Unrecognised card: {card!r}")
    return c


def card_value(card: str) -> int:
    return RANK_VALUES[normalize_rank(card)]


def hand_total(cards: list[str]) -> tuple[int, bool]:
    """Return (best total, is_soft). Soft means an ace is still counted as 11."""
    total = sum(card_value(c) for c in cards)
    aces = sum(1 for c in cards if normalize_rank(c) == "A")
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, aces > 0


@dataclass(frozen=True)
class Recommendation:
    action: Action
    total: int
    soft: bool
    reason: str


def recommend(
    player_cards: list[str],
    dealer_upcard: str,
    rules: Rules = Rules(),
    can_double: bool | None = None,
    can_split: bool | None = None,
    can_surrender: bool | None = None,
    true_count: float | None = None,
) -> Recommendation:
    """Recommend the basic-strategy action.

    The ``can_*`` flags say whether the table currently offers that action.
    ``None`` means "infer it": double/surrender only on a two-card hand,
    split only on a two-card pair.

    With a Hi-Lo ``true_count``, the Illustrious 18 and Fab 4 index plays
    override basic strategy.
    """
    if len(player_cards) < 2:
        raise ValueError("Need at least two player cards")
    total, soft = hand_total(player_cards)
    up = card_value(dealer_upcard)  # 2..11 (ace = 11)
    two_cards = len(player_cards) == 2
    ranks = [normalize_rank(c) for c in player_cards]
    is_pair = two_cards and card_value(ranks[0]) == card_value(ranks[1])

    if can_double is None:
        can_double = two_cards
    if can_split is None:
        can_split = is_pair
    if can_surrender is None:
        can_surrender = two_cards
    can_surrender = can_surrender and rules.surrender_allowed and two_cards
    can_split = can_split and is_pair

    def rec(action: Action, reason: str) -> Recommendation:
        return Recommendation(action, total, soft, reason)

    if total > 21:
        return rec(Action.STAND, "Bust")

    tc = true_count
    hard = not soft

    # 1. Surrender
    if can_surrender:
        index = _surrender_index(total, up, rules) if (tc is not None and hard and not is_pair) else None
        if index is not None:
            if tc >= index:
                return rec(Action.SURRENDER, f"Surrender {total} vs {_up(up)}  ·  count play (TC ≥ {index:+d})")
        elif _should_surrender(total, soft, is_pair, ranks, up, rules):
            return rec(Action.SURRENDER, f"Surrender {total} vs {_up(up)}")

    # 2. Split
    if can_split:
        index = SPLIT_INDEX.get((card_value(ranks[0]), up)) if tc is not None else None
        if index is not None and tc >= index:
            return rec(Action.SPLIT, f"Split {ranks[0]}s vs {_up(up)}  ·  count play (TC ≥ {index:+d})")
        if _should_split(ranks[0], up, rules):
            return rec(Action.SPLIT, f"Split {ranks[0]}s vs {_up(up)}")

    # 3. Soft / hard totals
    code = _soft_action(total, up, rules) if soft else _hard_action(total, up, rules)
    label = f"{'Soft' if soft else 'Hard'} {total} vs {_up(up)}"

    if tc is not None and hard:
        index = STAND_INDEX.get((total, up))
        if index is not None:
            code = "S" if tc >= index else "H"
            label += f"  ·  count play (stand at TC ≥ {index:+d})"
        index = DOUBLE_INDEX.get((total, up))
        if index is not None and code == "H" and tc >= index:
            code = "D"
            label += f"  ·  count play (TC ≥ {index:+d})"

    if code == "D":
        return rec(Action.DOUBLE, label) if can_double else rec(Action.HIT, label + " (can't double)")
    if code == "Ds":
        return rec(Action.DOUBLE, label) if can_double else rec(Action.STAND, label + " (can't double)")
    if code == "S":
        return rec(Action.STAND, label)
    return rec(Action.HIT, label)


def _up(up: int) -> str:
    return "A" if up == 11 else str(up)


# Illustrious 18 index numbers (Hi-Lo, multi-deck). Keys are (hard total, dealer upcard).
STAND_INDEX = {
    (16, 10): 0, (15, 10): 4, (16, 9): 5,
    (13, 2): -1, (13, 3): -2,
    (12, 2): 3, (12, 3): 2, (12, 4): 0, (12, 5): -2, (12, 6): -1,
}
DOUBLE_INDEX = {(11, 11): 1, (10, 10): 4, (10, 11): 4, (9, 2): 1, (9, 7): 3}
SPLIT_INDEX = {(10, 5): 5, (10, 6): 4}  # split tens
INSURANCE_INDEX = 3


def should_take_insurance(true_count: float | None) -> bool:
    """Insurance is a losing bet off the top; take it only at TC ≥ +3."""
    return true_count is not None and true_count >= INSURANCE_INDEX


def _surrender_index(total: int, up: int, rules: Rules) -> int | None:
    """Fab 4 surrender indices; None means use basic strategy."""
    if total == 14 and up == 10:
        return 3
    if total == 15 and up == 10:
        return 0
    if total == 15 and up == 9:
        return 2
    if total == 15 and up == 11:
        return -1 if rules.dealer_hits_soft_17 else 1
    return None


def _should_surrender(total, soft, is_pair, ranks, up, rules) -> bool:
    if soft:
        return False
    h17 = rules.dealer_hits_soft_17
    if is_pair and card_value(ranks[0]) == 8:
        return h17 and up == 11
    if total == 16 and up in (9, 10, 11):
        return True
    if total == 15 and (up == 10 or (h17 and up == 11)):
        return True
    if total == 17 and h17 and up == 11:
        return True
    return False


def _should_split(rank: str, up: int, rules: Rules) -> bool:
    v = card_value(rank)
    das = rules.double_after_split
    if v == 11 or v == 8:
        return True
    if v == 10 or v == 5:
        return False
    if v == 9:
        return up in (2, 3, 4, 5, 6, 8, 9)
    if v == 7:
        return 2 <= up <= 7
    if v == 6:
        return 2 <= up <= 6 if das else 3 <= up <= 6
    if v == 4:
        return das and up in (5, 6)
    if v in (2, 3):
        return 2 <= up <= 7 if das else 4 <= up <= 7
    return False


def _hard_action(total: int, up: int, rules: Rules) -> str:
    if total >= 17:
        return "S"
    if total >= 13:
        return "S" if up <= 6 else "H"
    if total == 12:
        return "S" if 4 <= up <= 6 else "H"
    if total == 11:
        if up == 11:
            return "D" if rules.dealer_hits_soft_17 else "H"
        return "D"
    if total == 10:
        return "D" if up <= 9 else "H"
    if total == 9:
        return "D" if 3 <= up <= 6 else "H"
    return "H"


def _soft_action(total: int, up: int, rules: Rules) -> str:
    h17 = rules.dealer_hits_soft_17
    if total >= 20:
        return "S"
    if total == 19:
        return "Ds" if (h17 and up == 6) else "S"
    if total == 18:
        if (2 if h17 else 3) <= up <= 6:
            return "Ds"
        return "S" if up in (2, 7, 8) else "H"
    if total == 17:
        return "D" if 3 <= up <= 6 else "H"
    if total in (15, 16):
        return "D" if 4 <= up <= 6 else "H"
    if total in (13, 14):
        return "D" if 5 <= up <= 6 else "H"
    return "H"  # soft 12 = A,A when splitting isn't possible
