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
