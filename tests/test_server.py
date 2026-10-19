import io
import json

from blackjack_assistant import config
from blackjack_assistant.server import Server


def make_server(tmp_path):
    out = io.StringIO()
    server = Server(out)
    server._config_path = tmp_path / "settings.json"
    return server, out


def call(server, out, method, **params):
    out.seek(0)
    out.truncate()
    server.handle_line(json.dumps({"id": 7, "method": method, "params": params}))
    return [json.loads(line) for line in out.getvalue().splitlines()]


def test_ping_and_unknown(tmp_path):
    s, out = make_server(tmp_path)
    assert call(s, out, "ping") == [{"id": 7, "result": "pong"}]
    assert "Unknown method" in call(s, out, "nope")[0]["error"]
    out.seek(0)
    out.truncate()
    s.handle_line("not json")
    assert json.loads(out.getvalue())["error"] == "Malformed request"


def test_settings_round_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s, out = make_server(tmp_path)
    got = call(s, out, "get_settings")[0]["result"]
    assert got["settings"]["decks"] == 8 and got["env_api_key"] is False
    saved = call(s, out, "save_settings", settings={**got["settings"], "decks": 6, "unit": 5})[0]
    assert saved["result"]["decks"] == 6 and saved["result"]["unit"] == 5
    assert config.load(s._config_path).decks == 6


def test_save_rejects_invalid(tmp_path):
    s, out = make_server(tmp_path)
    resp = call(s, out, "save_settings", settings={"decks": 12})[0]
    assert "Decks must be between 1 and 8" in resp["error"]
    assert not s._config_path.exists()


def test_start_requires_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    s, out = make_server(tmp_path)
    assert "API key" in call(s, out, "start")[0]["error"]


def test_stop_and_reset_without_session(tmp_path):
    s, out = make_server(tmp_path)
    assert call(s, out, "stop")[0]["result"] is True
    assert call(s, out, "reset_count")[0]["result"] is True


def test_set_seat_saves_and_validates(tmp_path):
    s, out = make_server(tmp_path)
    assert call(s, out, "set_seat", seat=[0.3, 0.6, 0.1, 0.15])[0]["result"] == [0.3, 0.6, 0.1, 0.15]
    assert config.load(s._config_path).seat == [0.3, 0.6, 0.1, 0.15]
    assert "too small" in call(s, out, "set_seat", seat=[0.3, 0.6, 0.0, 0.15])[0]["error"]
    assert call(s, out, "set_seat", seat=None)[0]["result"] is None
    assert config.load(s._config_path).seat is None


def test_model_options_per_model():
    from blackjack_assistant.vision import model_options

    opus = model_options("claude-opus-5-5")
    assert "thinking" not in opus and opus["fallbacks"] == "default" and opus["output_config"] == {"effort": "low"}
    sonnet = model_options("claude-sonnet-5-5")
    assert sonnet["thinking"] == {"type": "between_tools"} and sonnet["fallbacks"] == "default"
    haiku = model_options("claude-haiku-5-5")
    assert haiku["thinking"] == {"type": "disabled"} and "fallbacks" not in haiku and "betas" not in haiku
