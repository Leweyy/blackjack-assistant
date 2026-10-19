from PIL import Image

from blackjack_assistant.advisor import BetSettings, advise
from blackjack_assistant.counting import CountSnapshot
from blackjack_assistant.capture import ChangeDetector, Region
from blackjack_assistant.strategy import Action, Rules
from blackjack_assistant.vision import TableState


def state(**kw):
    base = dict(table_visible=True, dealer_cards=["6"], player_hands=[["5", "6"]], active_hand_index=0,
                is_player_turn=True, available_actions=[], other_players_cards=[], is_betting_phase=False,
                round_complete=False, shuffle_detected=False, insurance_offered=False, confident=True)
    base.update(kw)
    return TableState(**base)


def test_basic_advice():
    a = advise(state(), Rules())
    assert a.action == Action.DOUBLE
    assert "Hard 11 vs 6" in a.detail


def test_respects_visible_buttons():
    a = advise(state(available_actions=["hit", "stand"]), Rules())
    assert a.action == Action.HIT


def test_not_players_turn():
    a = advise(state(is_player_turn=False), Rules())
    assert a.action is None and a.headline == "Waiting…"


def test_no_table():
    assert advise(state(table_visible=False), Rules()).headline == "No table"


def test_split_hands_uses_active_hand():
    a = advise(state(player_hands=[["8", "10"], ["8", "3"]], active_hand_index=1), Rules())
    assert a.action == Action.DOUBLE
    assert "hand 2/2" in a.detail


def test_unreadable_card():
    assert advise(state(player_hands=[["?", "5"]]), Rules()).headline == "Can't read"


def test_low_confidence_warning():
    assert "low confidence" in advise(state(confident=False), Rules()).detail


def test_region_parse():
    assert Region.parse("10,20,300,400") == Region(10, 20, 300, 400)


def test_change_detector():
    d = ChangeDetector()
    a = Image.new("RGB", (800, 450), "green")
    assert d.changed(a)
    assert not d.changed(a.copy())
    b = a.copy()
    b.paste((255, 255, 255), (100, 100, 300, 300))
    assert d.changed(b)


def count(tc):
    return CountSnapshot(running=round(tc * 4), cards_seen=208, decks_remaining=4.0, true_count=tc)


def test_betting_phase_bet_ramp():
    a = advise(state(is_betting_phase=True, player_hands=[], dealer_cards=[]), Rules(), count(3.2), BetSettings(unit=10))
    assert a.headline == "BET 4 UNITS" and a.bet_units == 4 and "(40)" in a.detail
    assert "TC +3.2" in a.count_line
    assert advise(state(is_betting_phase=True), Rules(), count(0.5)).headline == "MIN BET"


def test_insurance_by_count():
    s = state(dealer_cards=["A"], insurance_offered=True)
    assert advise(s, Rules(), count(3.0)).action == Action.INSURANCE
    assert advise(s, Rules(), count(2.9)).action == Action.NO_INSURANCE
    assert advise(s, Rules()).action == Action.NO_INSURANCE


def test_count_deviation_reaches_advice():
    s = state(player_hands=[["10", "6"]], dealer_cards=["10"], available_actions=["hit", "stand"])
    assert advise(s, Rules(), count(-1)).action == Action.HIT
    assert advise(s, Rules(), count(0.5)).action == Action.STAND


def test_shuffle_message():
    assert advise(state(shuffle_detected=True), Rules(), count(0)).headline == "Shuffle"
