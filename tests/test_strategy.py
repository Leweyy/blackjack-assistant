import pytest

from blackjack_assistant.strategy import Action, Rules, hand_total, normalize_rank, recommend

H, S, D, P, R = Action.HIT, Action.STAND, Action.DOUBLE, Action.SPLIT, Action.SURRENDER
H17 = Rules(dealer_hits_soft_17=True)


@pytest.mark.parametrize("card,rank", [("10♠", "10"), ("kh", "K"), ("Ace", "A"), ("T", "10"), (" 7 ", "7")])
def test_normalize_rank(card, rank):
    assert normalize_rank(card) == rank


def test_normalize_rank_rejects_junk():
    with pytest.raises(ValueError):
        normalize_rank("?")


@pytest.mark.parametrize("cards,expected", [
    (["A", "6"], (17, True)),
    (["A", "6", "10"], (17, False)),
    (["A", "A"], (12, True)),
    (["A", "A", "9"], (21, True)),
    (["K", "Q", "5"], (25, False)),
])
def test_hand_total(cards, expected):
    assert hand_total(cards) == expected


@pytest.mark.parametrize("cards,up,expected", [
    # hard totals
    (["10", "7"], "A", S),
    (["10", "6"], "6", S),
    (["10", "6"], "7", H),
    (["10", "2"], "3", H),
    (["10", "2"], "4", S),
    (["6", "5"], "10", D),
    (["6", "5"], "A", H),
    (["6", "4"], "9", D),
    (["6", "4"], "10", H),
    (["5", "4"], "2", H),
    (["5", "4"], "3", D),
    (["5", "3"], "6", H),
    # soft totals
    (["A", "8"], "6", S),
    (["A", "7"], "2", S),
    (["A", "7"], "4", D),
    (["A", "7"], "9", H),
    (["A", "6"], "3", D),
    (["A", "6"], "2", H),
    (["A", "2"], "5", D),
    (["A", "2"], "4", H),
    # pairs
    (["A", "A"], "10", P),
    (["8", "8"], "10", P),
    (["K", "Q"], "6", S),
    (["9", "9"], "7", S),
    (["9", "9"], "8", P),
    (["5", "5"], "6", D),
    (["4", "4"], "5", P),
    (["2", "2"], "7", P),
    (["2", "2"], "8", H),
    # surrender
    (["10", "6"], "10", R),
    (["9", "7"], "A", R),
    (["10", "5"], "10", R),
    (["10", "5"], "A", H),
])
def test_s17_chart(cards, up, expected):
    assert recommend(cards, up).action == expected


@pytest.mark.parametrize("cards,up,expected", [
    (["6", "5"], "A", D),
    (["A", "7"], "2", D),
    (["A", "8"], "6", D),
    (["10", "5"], "A", R),
    (["10", "7"], "A", R),
    (["8", "8"], "A", R),
])
def test_h17_differences(cards, up, expected):
    assert recommend(cards, up, H17).action == expected


def test_no_das_changes_small_pairs():
    rules = Rules(double_after_split=False)
    assert recommend(["2", "2"], "2", rules).action == H
    assert recommend(["4", "4"], "5", rules).action == H
    assert recommend(["6", "6"], "2", rules).action == H


def test_no_surrender_falls_back():
    assert recommend(["10", "6"], "10", Rules(surrender_allowed=False)).action == H


def test_three_card_hands_cannot_double_or_surrender():
    assert recommend(["3", "3", "5"], "6").action == H        # hard 11, can't double
    assert recommend(["A", "2", "4"], "4").action == H        # soft 17, can't double
    assert recommend(["2", "4", "10"], "10").action == H       # 16 vs 10, no surrender


def test_soft_18_cant_double_stands():
    assert recommend(["A", "3", "4"], "5").action == S


def test_table_flags_override_inference():
    assert recommend(["6", "5"], "6", can_double=False).action == H
    assert recommend(["8", "8"], "10", can_split=False, can_surrender=False).action == H


def test_bust():
    assert recommend(["10", "9", "5"], "6").action == S


def test_cards_with_suit_symbols():
    from blackjack_assistant.counting import hilo_sum
    assert recommend(["9♥", "5♠"], "10♣").action == H
    assert recommend(["A♦", "7♣"], "9♠").action == H
    assert hand_total(["A♥", "K♠"]) == (21, True)
    assert hilo_sum(["10♣", "5♦", "A♥", "8♠"]) == -1
