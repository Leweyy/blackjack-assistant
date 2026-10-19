import pytest

from blackjack_assistant.counting import HiLoCounter, RoundTracker, bet_advice, hilo_sum
from blackjack_assistant.strategy import Action, Rules, recommend, should_take_insurance
from blackjack_assistant.vision import TableState


def test_hilo_values():
    assert hilo_sum(["2", "3", "4", "5", "6"]) == 5
    assert hilo_sum(["7", "8", "9"]) == 0
    assert hilo_sum(["10", "J", "Q", "K", "A"]) == -5
    assert hilo_sum(["?", "5"]) == 1  # unreadable cards are ignored


def test_true_count():
    c = HiLoCounter(decks=6)
    c.add(["2", "3", "4", "5", "6", "5"] * 26)  # 156 low cards = 3 decks seen, RC +156
    snap = c.snapshot()
    assert snap.decks_remaining == pytest.approx(3.0)
    assert snap.true_count == pytest.approx(52.0)


def test_decks_remaining_floor():
    c = HiLoCounter(decks=1)
    c.add(["5"] * 60)
    assert c.snapshot().decks_remaining == 0.5


@pytest.mark.parametrize("tc,units,headline", [
    (-3, 1, "MIN BET / SIT OUT"), (0, 1, "MIN BET"), (1.9, 1, "MIN BET"),
    (2.0, 2, "BET 2 UNITS"), (3.5, 4, "BET 4 UNITS"), (5, 8, "BET 8 UNITS"), (12, 8, "BET 8 UNITS"),
])
def test_bet_ramp(tc, units, headline):
    b = bet_advice(tc, max_units=8, unit=25)
    assert (b.units, b.headline, b.amount) == (units, headline, units * 25)


def table(**kw):
    base = dict(table_visible=True, dealer_cards=[], player_hands=[], player_hand_totals=[], dealer_total_shown="", active_hand_index=0, is_player_turn=False,
                available_actions=[], other_players_cards=[], is_betting_phase=False, round_complete=False,
                shuffle_detected=False, insurance_offered=False, confident=True)
    base.update(kw)
    return TableState(**base)


def test_round_counted_once_at_end():
    t = RoundTracker(HiLoCounter(8))
    t.observe(table(is_betting_phase=True))
    t.observe(table(dealer_cards=["K"], player_hands=[["5", "6"]], other_players_cards=["2"]))
    assert t.counter.snapshot().running == 0          # not committed yet...
    assert t.snapshot().running == 2                  # ...but included live: K -1, 5 6 2 +3
    done = table(dealer_cards=["K", "4", "Q"], player_hands=[["5", "6", "9"]], other_players_cards=["2", "3"],
                 round_complete=True)
    t.observe(done)
    t.observe(done)                                   # same end screen seen again
    assert t.counter.snapshot().running == 3          # K4Q -1, 569 +2, 23 +2
    assert t.counter.snapshot().cards_seen == 8


def test_missed_end_screen_counts_last_snapshot():
    t = RoundTracker(HiLoCounter(8))
    t.observe(table(dealer_cards=["K"], player_hands=[["5", "6"]]))
    t.observe(table(dealer_cards=["K", "4"], player_hands=[["5", "6", "10"]]))
    t.observe(table(is_betting_phase=True))
    snap = t.counter.snapshot()
    assert (snap.running, snap.cards_seen) == (1, 5)


def test_next_round_counts_again():
    t = RoundTracker(HiLoCounter(8))
    for _ in range(2):
        t.observe(table(dealer_cards=["5", "6"], player_hands=[["2", "3"]], round_complete=True))
        t.observe(table(is_betting_phase=True))
    assert t.counter.snapshot().running == 8


def test_shuffle_resets():
    t = RoundTracker(HiLoCounter(8))
    t.observe(table(dealer_cards=["5", "6"], player_hands=[["2", "3"]], round_complete=True))
    t.observe(table(shuffle_detected=True, is_betting_phase=True))
    assert t.snapshot().running == 0
    t.reset()
    assert t.snapshot().cards_seen == 0


@pytest.mark.parametrize("cards,up,tc,expected", [
    (["10", "6"], "10", -1, Action.SURRENDER),  # 16 v 10 always surrenders when allowed
    (["10", "5"], "10", -0.5, Action.HIT),      # Fab 4: surrender 15 v 10 only at TC >= 0
    (["10", "5"], "10", 0, Action.SURRENDER),
    (["10", "4"], "10", 3, Action.SURRENDER),
    (["10", "4"], "10", 2, Action.HIT),
    (["10", "5"], "9", 2, Action.SURRENDER),
    (["10", "5"], "A", 1, Action.SURRENDER),
    (["10", "5"], "A", 0, Action.HIT),
    (["10", "10"], "6", 4, Action.SPLIT),
    (["10", "10"], "6", 3.9, Action.STAND),
    (["10", "10"], "5", 5, Action.SPLIT),
    (["6", "5"], "A", 1, Action.DOUBLE),
    (["6", "5"], "A", 0.5, Action.HIT),
    (["6", "4"], "10", 4, Action.DOUBLE),
    (["5", "4"], "2", 1, Action.DOUBLE),
    (["5", "4"], "7", 3, Action.DOUBLE),
    (["10", "2"], "3", 2, Action.STAND),
    (["10", "2"], "2", 3, Action.STAND),
    (["10", "2"], "4", -0.5, Action.HIT),
    (["10", "3"], "2", -1.5, Action.HIT),
])
def test_index_plays(cards, up, tc, expected):
    assert recommend(cards, up, true_count=tc).action == expected


def test_index_plays_without_surrender():
    rules = Rules(surrender_allowed=False)
    assert recommend(["10", "6"], "10", rules, true_count=0).action == Action.STAND
    assert recommend(["10", "6"], "10", rules, true_count=-1).action == Action.HIT
    assert recommend(["10", "6"], "9", rules, true_count=5).action == Action.STAND
    assert recommend(["10", "5"], "10", rules, true_count=4).action == Action.STAND
    # three-card 16 v 10 uses the stand index too
    assert recommend(["10", "2", "4"], "10", true_count=1).action == Action.STAND


def test_soft_hands_ignore_hard_indices():
    assert recommend(["A", "5"], "10", true_count=10).action == Action.HIT


def test_insurance_index():
    assert should_take_insurance(3) and not should_take_insurance(2.9) and not should_take_insurance(None)
