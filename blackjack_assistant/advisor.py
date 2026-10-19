"""Turn a TableState into advice the player can act on."""

from __future__ import annotations

from dataclasses import dataclass

from .strategy import Action, Rules, recommend
from .vision import TableState


@dataclass(frozen=True)
class Advice:
    headline: str          # e.g. "DOUBLE" or "Waiting…"
    detail: str            # e.g. "Hard 11 vs 6  ·  You: 5 6  ·  Dealer: 6"
    action: Action | None  # None when there's nothing to do


def advise(state: TableState, rules: Rules) -> Advice:
    if not state.table_visible:
        return Advice("No table", "Couldn't find a blackjack table on screen", None)
    if not state.player_hands or not state.dealer_cards:
        return Advice("Waiting…", "Waiting for cards to be dealt", None)

    idx = min(max(state.active_hand_index, 0), len(state.player_hands) - 1)
    hand = state.player_hands[idx]
    up = state.dealer_cards[0]
    if len(hand) < 2:
        return Advice("Waiting…", "Waiting for your second card", None)

    offered = {a.strip().lower() for a in state.available_actions}

    def flag(name: str) -> bool | None:
        return (name in offered) if offered else None

    try:
        r = recommend(hand, up, rules, can_double=flag("double"),
                      can_split=flag("split"), can_surrender=flag("surrender"))
    except ValueError as e:
        return Advice("Can't read", str(e), None)

    hand_label = f" (hand {idx + 1}/{len(state.player_hands)})" if len(state.player_hands) > 1 else ""
    detail = f"{r.reason}  ·  You: {' '.join(hand)}{hand_label}  ·  Dealer: {up}"
    if not state.confident:
        detail += "  ·  ⚠ low confidence, double-check cards"
    if not state.is_player_turn:
        return Advice("Waiting…", "Not your turn  ·  " + detail, None)
    return Advice(r.action.value, detail, r.action)
