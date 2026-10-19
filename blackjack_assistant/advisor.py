"""Turn a TableState into advice the player can act on."""

from __future__ import annotations

from dataclasses import dataclass

from .counting import CountSnapshot, bet_advice
from .strategy import Action, Rules, recommend, should_take_insurance
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


def format_count(c: CountSnapshot) -> str:
    return (f"RC {c.running:+d}  ·  TC {c.true_count:+.1f}  ·  "
            f"{c.decks_remaining:.1f} decks left  ·  edge {c.edge_percent:+.1f}%")


def advise(state: TableState, rules: Rules, count: CountSnapshot | None = None,
           bets: BetSettings = BetSettings()) -> Advice:
    count_line = format_count(count) if count else ""
    tc = count.true_count if count else None

    def out(headline, detail, action=None, bet_units=None) -> Advice:
        return Advice(headline, detail, action, count_line, bet_units)

    if not state.table_visible:
        return out("No table", "Couldn't find a blackjack table on screen")
    if state.shuffle_detected:
        return out("Shuffle", "New shoe: count reset to 0")

    if state.is_betting_phase or not state.player_hands:
        if count:
            b = bet_advice(count.true_count, bets.max_units, bets.unit)
            money = f" ({b.amount:g})" if b.amount is not None else ""
            return out(b.headline, f"Place {b.units} unit{'s' if b.units != 1 else ''}{money} "
                                   f"at TC {count.true_count:+.1f}", bet_units=b.units)
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

    idx = min(max(state.active_hand_index, 0), len(state.player_hands) - 1)
    hand = state.player_hands[idx]
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
    if not state.confident:
        detail += "  ·  ⚠ low confidence, double-check cards"
    if state.round_complete or not state.is_player_turn:
        return out("Waiting…", "Not your turn  ·  " + detail)
    return out(r.action.value, detail, r.action)
