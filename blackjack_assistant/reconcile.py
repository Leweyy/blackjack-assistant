"""Fix hands where the same card was read twice.

Live-dealer games show each card twice (the real card on video and a digital copy
next to it), so the vision model occasionally reports "K 4 4" or "K K 4 4" for K 4.
The hand total the game displays is the referee: pick the reading that matches it.
"""

from __future__ import annotations

import re

from .strategy import hand_total, normalize_rank


_SUIT_WORDS = {
    "♠": "♠", "♣": "♣", "♥": "♥", "♦": "♦", "♤": "♠", "♧": "♣", "♡": "♥", "♢": "♦",
    "s": "♠", "c": "♣", "h": "♥", "d": "♦",
    "spade": "♠", "spades": "♠", "club": "♣", "clubs": "♣",
    "heart": "♥", "hearts": "♥", "diamond": "♦", "diamonds": "♦",
}
_RANK_WORDS = {
    "a": "A", "ace": "A", "1": "A", "k": "K", "king": "K", "q": "Q", "queen": "Q", "j": "J", "jack": "J",
    "t": "10", "ten": "10", "10": "10", "two": "2", "three": "3", "four": "4", "five": "5",
    "six": "6", "seven": "7", "eight": "8", "nine": "9", **{str(n): str(n) for n in range(2, 10)},
}


def normalize_card(card: str) -> str:
    """Write a card as rank + suit symbol ("9♥"), or the rank alone if there's no suit.

    Accepts the variations models produce: "9H", "9 of hearts", "Ten♣", "T♠", "10 ♦".
    Anything unrecognisable is returned unchanged (and later reported as unreadable).
    """
    text = str(card).strip()
    t = text.lower().replace(" of ", " ")
    m = re.fullmatch(r"([a-z]+|\d+)\s*([♠♣♥♦♤♧♡♢]|[a-z]+)?", t)
    if not m:
        return text
    rank_word, suit_word = m.group(1), m.group(2)
    if suit_word is None and rank_word not in _RANK_WORDS and len(rank_word) == 2:
        rank_word, suit_word = rank_word[0], rank_word[1]  # "kh", "th"
    rank = _RANK_WORDS.get(rank_word)
    suit = _SUIT_WORDS.get(suit_word, "") if suit_word else ""
    if rank is None or (suit_word and not suit):
        return text
    return rank + suit


def shown_totals(text: str) -> set[int]:
    """Values a displayed hand total allows: "14" -> {14}, "4/14" or "Soft 14" -> {4, 14}, "BJ" -> {21}."""
    t = (text or "").strip().lower()
    if not t:
        return set()
    if "bj" in t or "blackjack" in t:
        return {21}
    nums = {int(n) for n in re.findall(r"\d+", t)}
    if "soft" in t:
        nums |= {n - 10 for n in nums if n > 11}
    return {n for n in nums if 2 <= n <= 31}


def _values(cards: list[str]) -> set[int] | None:
    """Totals a hand can be shown as (soft hands have two), or None if a card is unreadable."""
    try:
        total, soft = hand_total(cards)
    except ValueError:
        return None
    return {total, total - 10} if soft else {total}


def _candidates(cards: list[str]) -> list[list[str]]:
    """Readings with duplicated cards removed, most likely first."""
    out: list[list[str]] = []
    n = len(cards)
    ranks = []
    for c in cards:
        try:
            ranks.append(normalize_rank(c))
        except ValueError:
            ranks.append(c)
    if n >= 4 and n % 2 == 0:
        half = n // 2
        if ranks[:half] == ranks[half:]:  # K 4 K 4: the whole hand listed twice
            out.append(cards[:half])
        if all(ranks[i] == ranks[i + 1] for i in range(0, n, 2)):  # K K 4 4: every card doubled
            out.append(cards[::2])
    for i in range(n):  # one card listed twice: drop a repeat
        if ranks[i] in ranks[:i] and (i == n - 1 or ranks[i] != ranks[i + 1]):
            out.append(cards[:i] + cards[i + 1:])
    return [c for c in out if len(c) >= 1]


def reconcile_hand(cards: list[str], shown: str = "", must_be_live: bool = False) -> tuple[list[str], bool]:
    """Return (cards, trustworthy).

    With a displayed total, keep the reading that matches it. Without one, a hand
    that would be bust while the player still has to act (`must_be_live`) is
    treated as a double read. `trustworthy` is False when the cards contradict
    the displayed total and no de-duplicated reading fixes it.
    """
    totals = shown_totals(shown)
    values = _values(cards)
    if totals:
        if values is None or values & totals:
            return cards, True
        for cand in _candidates(cards):
            v = _values(cand)
            if v and v & totals:
                return cand, True
        return cards, False
    if must_be_live and values is not None and min(values) > 21:
        for cand in _candidates(cards):
            v = _values(cand)
            if v and min(v) <= 21:
                return cand, True
    return cards, True


def reconcile_table(state):
    """Normalise card names, then apply reconcile_hand to the player's hands and the dealer's cards."""
    state = state.model_copy(update={
        "player_hands": [[normalize_card(c) for c in hand] for hand in state.player_hands],
        "dealer_cards": [normalize_card(c) for c in state.dealer_cards],
        "other_players_cards": [normalize_card(c) for c in state.other_players_cards],
    })
    totals = list(state.player_hand_totals) + [""] * len(state.player_hands)
    trustworthy = True
    hands = []
    for i, hand in enumerate(state.player_hands):
        live = state.is_player_turn and i == state.active_hand_index
        fixed, ok = reconcile_hand(list(hand), totals[i], must_be_live=live)
        hands.append(fixed)
        trustworthy &= ok
    dealer, ok = reconcile_hand(list(state.dealer_cards), state.dealer_total_shown)
    trustworthy &= ok
    return state.model_copy(update={
        "player_hands": hands,
        "dealer_cards": dealer,
        "confident": state.confident and trustworthy,
    })
