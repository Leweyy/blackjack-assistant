import pytest

from blackjack_assistant.reconcile import reconcile_hand, reconcile_table, shown_totals
from blackjack_assistant.vision import TableState


@pytest.mark.parametrize("text,expected", [
    ("14", {14}), ("4/14", {4, 14}), ("Soft 17", {7, 17}), ("BJ", {21}), ("Blackjack", {21}), ("", set()),
])
def test_shown_totals(text, expected):
    assert shown_totals(text) == expected


@pytest.mark.parametrize("cards,shown,expected", [
    (["K♠", "4♥", "4♥"], "14", ["K♠", "4♥"]),             # one card read twice
    (["K♠", "K♠", "4♥", "4♥"], "14", ["K♠", "4♥"]),       # every card doubled
    (["K♠", "4♥", "K♠", "4♥"], "14", ["K♠", "4♥"]),       # whole hand listed twice
    (["K♠", "4♥", "4♦"], "18", ["K♠", "4♥", "4♦"]),       # a genuine third card is kept
    (["A♠", "6♥", "6♥"], "7/17", ["A♠", "6♥"]),           # soft totals
    (["9♥", "5♠"], "14", ["9♥", "5♠"]),
])
def test_reconcile_with_shown_total(cards, shown, expected):
    assert reconcile_hand(cards, shown)[0] == expected


def test_mismatch_without_fix_is_not_trustworthy():
    cards, ok = reconcile_hand(["9♥", "5♠"], "17")
    assert cards == ["9♥", "5♠"] and ok is False


def test_bust_while_live_is_a_double_read():
    assert reconcile_hand(["K♠", "K♠", "4♥", "4♥"], "", must_be_live=True)[0] == ["K♠", "4♥"]
    # different cards are never treated as duplicates, even if the hand is bust
    assert reconcile_hand(["K♠", "Q♠", "4♥"], "", must_be_live=True)[0] == ["K♠", "Q♠", "4♥"]
    # a real bust after the round (not live) is left alone
    assert reconcile_hand(["K♠", "K♠", "4♥"], "", must_be_live=False)[0] == ["K♠", "K♠", "4♥"]


def test_reconcile_table():
    state = TableState(table_visible=True, dealer_cards=["10♣", "10♣"], player_hands=[["K♠", "4♥", "4♥"]],
                       player_hand_totals=["14"], dealer_total_shown="10", active_hand_index=0, is_player_turn=True,
                       available_actions=[], other_players_cards=[], is_betting_phase=False, round_complete=False,
                       shuffle_detected=False, insurance_offered=False, confident=True)
    fixed = reconcile_table(state)
    assert fixed.player_hands == [["K♠", "4♥"]] and fixed.dealer_cards == ["10♣"] and fixed.confident


@pytest.mark.parametrize("raw,expected", [
    ("9♥", "9♥"), ("9H", "9♥"), ("9h", "9♥"), ("9 of hearts", "9♥"), ("Nine of Hearts", "9♥"),
    ("10 ♠", "10♠"), ("T♣", "10♣"), ("Ten", "10"), ("ten of diamonds", "10♦"), ("KH", "K♥"), ("kd", "K♦"),
    ("Ace of Spades", "A♠"), ("A", "A"), ("q♡", "Q♥"), ("j", "J"), ("4", "4"), ("10", "10"),
    ("??", "??"), ("joker", "joker"), ("9 of stars", "9 of stars"),
])
def test_normalize_card(raw, expected):
    from blackjack_assistant.reconcile import normalize_card
    assert normalize_card(raw) == expected
