from PIL import Image

from blackjack_assistant.advisor import advise
from blackjack_assistant.capture import ChangeDetector, Region
from blackjack_assistant.strategy import Action, Rules
from blackjack_assistant.vision import TableState


def state(**kw):
    base = dict(table_visible=True, dealer_cards=["6"], player_hands=[["5", "6"]], active_hand_index=0,
                is_player_turn=True, available_actions=[], confident=True)
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
