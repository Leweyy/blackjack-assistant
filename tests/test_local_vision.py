import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from blackjack_assistant.local_vision import LocalReader, list_models, parse_table
from blackjack_assistant.vision import VisionError


class FakeServer:
    """A tiny OpenAI-compatible server: /v1/models and /v1/chat/completions."""

    def __init__(self, reply: str, reject_schema: bool = False):
        self.reply = reply
        self.reject_schema = reject_schema
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._send(200, {"object": "list", "data": [
                    {"id": "qwen2.5vl:7b", "object": "model", "created": 0, "owned_by": "me"},
                    {"id": "gemma3:12b", "object": "model", "created": 0, "owned_by": "me"}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                if outer.reject_schema and body["response_format"]["type"] == "json_schema":
                    return self._send(400, {"error": {"message": "response_format json_schema not supported"}})
                self._send(200, {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                                 "choices": [{"index": 0, "finish_reason": "stop",
                                              "message": {"role": "assistant", "content": outer.reply}}]})

        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()


GOOD = {"table_visible": True, "dealer_cards": ["10C"], "player_hands": [["K of spades", "4h", "4h"]],
        "player_hand_totals": ["14"], "dealer_total_shown": "10", "active_hand_index": 0, "is_player_turn": True,
        "available_actions": ["hit", "stand"], "other_players_cards": [], "is_betting_phase": False,
        "round_complete": False, "shuffle_detected": False, "insurance_offered": False, "confident": True}


@pytest.fixture
def server(request):
    s = FakeServer(**request.param)
    yield s
    s.close()


@pytest.mark.parametrize("server", [{"reply": json.dumps(GOOD)}], indirect=True)
def test_reads_and_cleans_cards(server):
    assert list_models(server.url) == ["gemma3:12b", "qwen2.5vl:7b"]
    reader = LocalReader(server.url, "qwen2.5vl:7b")
    state = reader.read(b"\xff\xd8fakejpeg", seat_marked=True)
    assert state.player_hands == [["K♠", "4♥"]]  # normalised and de-duplicated against the shown 14
    assert state.dealer_cards == ["10♣"]
    req = server.requests[-1]
    assert req["response_format"]["type"] == "json_schema" and req["temperature"] == 0
    content = req["messages"][1]["content"]
    assert content[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "magenta box" in content[1]["text"]


@pytest.mark.parametrize("server", [{"reply": "<think>hmm</think>```json\n" + json.dumps(
    {"dealer_cards": ["Q♦"], "player_hands": ["9♥", "5♠"], "is_player_turn": True}) + "\n```",
    "reject_schema": True}], indirect=True)
def test_falls_back_to_json_mode_and_tolerates_messy_replies(server):
    reader = LocalReader(server.url, "llava")
    state = reader.read(b"jpeg")
    assert state.player_hands == [["9♥", "5♠"]] and state.dealer_cards == ["Q♦"]
    kinds = [r["response_format"]["type"] for r in server.requests]
    assert kinds == ["json_schema", "json_object"]
    assert "matching this schema" in server.requests[-1]["messages"][1]["content"][1]["text"]
    reader.read(b"jpeg")  # remembers that json_schema isn't supported
    assert [r["response_format"]["type"] for r in server.requests][-1] == "json_object"
    assert len(server.requests) == 3


@pytest.mark.parametrize("server", [{"reply": "Sorry, I can't see any cards."}], indirect=True)
def test_no_json_is_a_vision_error(server):
    with pytest.raises(VisionError, match="didn't return any JSON"):
        LocalReader(server.url, "m").read(b"jpeg")


def test_unreachable_server():
    with pytest.raises(VisionError, match="Can't reach"):
        list_models("http://127.0.0.1:9/v1")
    with pytest.raises(VisionError, match="Can't reach"):
        LocalReader("http://127.0.0.1:9/v1", "m").read(b"jpeg")


def test_parse_table_defaults():
    state = parse_table({"dealer_cards": ["A"], "player_hands": [["8", "8"]]})
    assert state.table_visible and state.confident and state.available_actions == []


def test_evaluate_scores_a_reader(tmp_path):
    from blackjack_assistant import evaluate
    from blackjack_assistant.strategy import Rules

    (tmp_path / "f1.jpg").write_bytes(b"jpeg")
    (tmp_path / "f1.label.json").write_text(json.dumps({**GOOD, "player_hands": [["K♠", "4♥"]]}), encoding="utf-8")
    (tmp_path / "f2.jpg").write_bytes(b"jpeg")
    (tmp_path / "f2.label.json").write_text(json.dumps({**GOOD, "player_hands": [["9♠", "7♥"]]}), encoding="utf-8")

    class Reader:
        def read(self, jpeg, seat_marked=False):
            return parse_table({**GOOD, "player_hands": [["K♦", "4♣"]]})

    report = evaluate.score(evaluate.load_cases(tmp_path), Reader(), Rules())
    assert report["frames"] == 2 and report["player_hand_correct"] == 0.5 and report["dealer_correct"] == 1.0
