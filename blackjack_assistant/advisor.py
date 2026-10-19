"""Turn a TableState into advice the player can act on."""

from __future__ import annotations

from dataclasses import dataclass, field

from .counting import CountSnapshot, bet_advice
from .strategy import Action, Rules, hand_total, recommend, should_take_insurance
from .vision import TableState


@dataclass(frozen=True)
class BetSettings:
    unit: float | None = None  # money per betting unit, for display only
    max_units: int = 8


@dataclass(frozen=True)
class Advice:
    headline: str           # e.g. "DOUBLE" or "Waiting…"
    detail: str             # e.g. "Hard 11 vs 6  ·  You: 5 6  ·  Dealer: 6"
    action: Action | None   # None when there's no playing decision
    count_line: str = ""    # e.g. "RC +6  ·  TC +1.5  ·  4.0 decks left  ·  edge +0.3%"
    bet_units: int | None = None  # set during the betting phase
    reason: str = ""        # short explanation, e.g. "Hard 11 vs 6"
    player_cards: list[str] = field(default_factory=list)  # the hand being played, e.g. ["9♥", "5♠"]
    dealer_cards: list[str] = field(default_factory=list)
    player_total: str = ""  # e.g. "14" or "soft 18"
    dealer_total: str = ""
    hand_label: str = ""    # e.g. "hand 2 of 2" after a split


def format_count(c: CountSnapshot) -> str:
    return (f"RC {c.running:+d}  ·  TC {c.true_count:+.1f}  ·  "
            f"{c.decks_remaining:.1f} decks left  ·  edge {c.edge_percent:+.1f}%")


def _total(cards: list[str]) -> str:
    if not cards:
        return ""
    try:
        total, soft = hand_total(cards)
    except ValueError:
        return ""
    return f"soft {total}" if soft and total < 21 else str(total)


def advise(state: TableState, rules: Rules, count: CountSnapshot | None = None,
           bets: BetSettings = BetSettings()) -> Advice:
    count_line = format_count(count) if count else ""
    tc = count.true_count if count else None

    idx = min(max(state.active_hand_index, 0), len(state.player_hands) - 1) if state.player_hands else 0
    hand = state.player_hands[idx] if state.player_hands else []
    table = {
        "player_cards": list(hand), "dealer_cards": list(state.dealer_cards),
        "player_total": _total(hand), "dealer_total": _total(state.dealer_cards),
        "hand_label": f"hand {idx + 1} of {len(state.player_hands)}" if len(state.player_hands) > 1 else "",
    }

    def out(headline, detail, action=None, bet_units=None, reason="", show_table=True) -> Advice:
        return Advice(headline, detail, action, count_line, bet_units, reason or detail,
                      **(table if show_table else {}))

    if not state.table_visible:
        return out("No table", "Couldn't find a blackjack table on screen", show_table=False)
    if state.shuffle_detected:
        return out("Shuffle", "New shoe: count reset to 0", show_table=False)

    if state.is_betting_phase or not state.player_hands:
        if count:
            b = bet_advice(count.true_count, bets.max_units, bets.unit)
            money = f" ({b.amount:g})" if b.amount is not None else ""
            return out(b.headline, f"Place {b.units} unit{'s' if b.units != 1 else ''}{money} "
                                   f"at TC {count.true_count:+.1f}", bet_units=b.units, show_table=False)
        return out("Waiting…", "Waiting for cards to be dealt")
    if not state.dealer_cards:
        return out("Waiting…", "Waiting for cards to be dealt")

    up = state.dealer_cards[0]
    if state.insurance_offered:
        if tc is None:
            return out("NO INSURANCE", "Insurance is a losing bet without a count", Action.NO_INSURANCE)
        if should_take_insurance(tc):
            return out("TAKE INSURANCE", f"TC {tc:+.1f} ≥ +3: insurance is profitable", Action.INSURANCE)
        return out("NO INSURANCE", f"TC {tc:+.1f} < +3: insurance loses money", Action.NO_INSURANCE)

    if len(hand) < 2:
        return out("Waiting…", "Waiting for your second card")

    offered = {a.strip().lower() for a in state.available_actions}

    def flag(name: str) -> bool | None:
        return (name in offered) if offered else None

    try:
        r = recommend(hand, up, rules, can_double=flag("double"), can_split=flag("split"),
                      can_surrender=flag("surrender"), true_count=tc)
    except ValueError as e:
        return out("Can't read", str(e))

    hand_label = f" (hand {idx + 1}/{len(state.player_hands)})" if len(state.player_hands) > 1 else ""
    detail = f"{r.reason}  ·  You: {' '.join(hand)}{hand_label}  ·  Dealer: {up}"
    reason = r.reason
    if not state.confident:
        detail += "  ·  ⚠ low confidence, double-check cards"
        reason += "  ·  ⚠ low confidence, check the cards"
    if state.round_complete or not state.is_player_turn:
        return out("Waiting…", "Not your turn  ·  " + detail,
                   reason="Round over" if state.round_complete else "Waiting for your turn")
    return out(r.action.value, detail, r.action, reason=reason)
