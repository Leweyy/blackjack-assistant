import json

from blackjack_assistant import config


def test_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    s = config.Settings(api_key="k", interval=3.0, region=[1, 2, 300, 400], dealer_hits_soft_17=True,
                        unit=12.5, decks=6, counting=False)
    config.save(s, path)
    loaded = config.load(path)
    assert loaded == s
    assert loaded.rules().dealer_hits_soft_17 and loaded.bets().unit == 12.5
    assert loaded.screen_region().width == 300


def test_missing_or_corrupt_file_gives_defaults(tmp_path):
    assert config.load(tmp_path / "nope.json") == config.Settings()
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert config.load(bad) == config.Settings()
    bad.write_text("[1, 2]")
    assert config.load(bad) == config.Settings()


def test_bad_values_are_ignored(tmp_path):
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"decks": "eight", "interval": 2, "unknown": 1, "region": [1, 2], "counting": False}))
    s = config.load(path)
    assert s.decks == 8 and s.interval == 2 and s.region is None and s.counting is False


def test_env_key_fallback(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert config.Settings().effective_api_key() == "env-key"
    assert config.Settings(api_key=" mine ").effective_api_key() == "mine"


def test_capture_mode_migration_and_validation(monkeypatch):
    assert config.from_dict({"region": [1, 2, 300, 400]}).capture == "region"
    assert config.from_dict({}).capture == "monitor"
    assert config.from_dict({"capture": "nonsense"}).capture == "monitor"
    assert config.from_dict({"window": {"handle": "x", "title": 3}}).window is None

    s = config.from_dict({"capture": "window", "window": {"handle": 42, "title": "Live Blackjack"}})
    assert s.window == {"handle": 42, "title": "Live Blackjack"}
    monkeypatch.setattr(config.sys, "platform", "win32")
    assert config.validate(s) == []
    monkeypatch.setattr(config.sys, "platform", "linux")
    assert any("only available on Windows" in p for p in config.validate(s))

    assert any("Choose a window" in p for p in config.validate(config.Settings(capture="window")))
    assert any("Select a table area" in p for p in config.validate(config.Settings(capture="region")))


def test_seat_validation():
    assert config.from_dict({"seat": [0.25, 0.8]}).seat == [0.25, 0.8]
    assert config.from_dict({"seat": [0, 1]}).seat == [0, 1]
    for bad in ([1.5, 0.2], [0.1], "x", [True, 0.5], [0.2, None]):
        assert config.from_dict({"seat": bad}).seat is None
