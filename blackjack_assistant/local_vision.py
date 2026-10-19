"""Read the table with a locally hosted vision model (Ollama, vLLM, LM Studio...).

These servers speak the OpenAI-compatible chat API, so one reader covers them all.
It sends the same prompt and JSON schema as the Claude reader and returns the
same TableState, so counting, strategy and the overlay don't care which is used.
"""

from __future__ import annotations

import base64
import json
import re

import openai
from pydantic import ValidationError

from .reconcile import reconcile_table
from .vision import SEAT_MARKER_NOTE, SYSTEM_PROMPT, TableState, VisionError

OLLAMA_URL = "http://localhost:11434/v1"
VLLM_URL = "http://localhost:8000/v1"
DEFAULT_MAX_SIDE = 1024  # smaller than for Claude: image processing dominates local latency


def _client(base_url: str, api_key: str = "", timeout: float = 60) -> openai.OpenAI:
    # Local servers ignore the key unless started with one (vLLM --api-key), but the SDK needs a value.
    return openai.OpenAI(base_url=base_url.rstrip("/"), api_key=api_key or "local", timeout=timeout, max_retries=0)


def list_models(base_url: str, api_key: str = "") -> list[str]:
    """Model ids the server offers (also serves as a connection test)."""
    try:
        return sorted(m.id for m in _client(base_url, api_key, timeout=10).models.list())
    except openai.AuthenticationError as e:
        raise VisionError("The local server rejected the API key.") from e
    except openai.APIConnectionError as e:
        raise VisionError(f"Can't reach a model server at {base_url}. Is Ollama or vLLM running?") from e
    except openai.APIStatusError as e:
        raise VisionError(f"The server at {base_url} answered with an error: {e.message}") from e


def _extract_json(text: str) -> dict:
    """Pull the JSON object out of a reply that may include <think> blocks or ``` fences."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise VisionError("The local model didn't return any JSON.")
    try:
        data = json.loads(text[start:end + 1])
    except ValueError as e:
        raise VisionError("The local model returned malformed JSON.") from e
    if not isinstance(data, dict):
        raise VisionError("The local model returned JSON that isn't an object.")
    return data


_DEFAULTS = {
    "table_visible": True, "dealer_cards": [], "player_hands": [], "player_hand_totals": [],
    "dealer_total_shown": "", "active_hand_index": 0, "is_player_turn": False, "available_actions": [],
    "other_players_cards": [], "is_betting_phase": False, "round_complete": False,
    "shuffle_detected": False, "insurance_offered": False, "confident": True,
}


def parse_table(data: dict) -> TableState:
    """Lenient TableState: smaller models sometimes leave fields out or use loose types."""
    merged = {**_DEFAULTS, **{k: v for k, v in data.items() if k in _DEFAULTS and v is not None}}
    hands = merged["player_hands"]
    if hands and all(isinstance(c, str) for c in hands):  # ["9♥", "5♠"] instead of [["9♥", "5♠"]]
        merged["player_hands"] = [hands]
    for key in ("dealer_cards", "other_players_cards", "available_actions", "player_hand_totals"):
        merged[key] = [str(v) for v in merged[key]] if isinstance(merged[key], list) else []
    merged["player_hands"] = [[str(c) for c in h] for h in merged["player_hands"] if isinstance(h, list)]
    merged["dealer_total_shown"] = str(merged["dealer_total_shown"])
    try:
        return TableState.model_validate(merged)
    except ValidationError as e:
        raise VisionError(f"The local model's answer didn't fit the expected format: {e.errors()[0]['msg']}") from e


class LocalReader:
    def __init__(self, base_url: str, model: str, api_key: str = "", max_side: int = DEFAULT_MAX_SIDE):
        self.base_url = base_url
        self.model = model
        self.max_side = max_side
        self.client = _client(base_url, api_key)
        self._schema_supported = True  # flips off if the server rejects json_schema output

    def _request(self, messages: list, use_schema: bool):
        if use_schema:
            fmt = {"type": "json_schema",
                   "json_schema": {"name": "table_state", "schema": TableState.model_json_schema(), "strict": True}}
        else:
            fmt = {"type": "json_object"}
        return self.client.chat.completions.create(
            model=self.model, messages=messages, response_format=fmt, temperature=0, max_tokens=2000)

    def read(self, jpeg_bytes: bytes, seat_marked: bool = False) -> TableState:
        image_b64 = base64.standard_b64encode(jpeg_bytes).decode("ascii")
        text = (SEAT_MARKER_NOTE + "\n\n" if seat_marked else "") + "Read the current blackjack table state."
        if not self._schema_supported:
            text += "\n\nReply with only a JSON object matching this schema:\n" + json.dumps(TableState.model_json_schema())
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                {"type": "text", "text": text},
            ]},
        ]
        try:
            try:
                response = self._request(messages, self._schema_supported)
            except openai.BadRequestError:
                if not self._schema_supported:
                    raise
                # Older servers don't support JSON-schema output: fall back to plain JSON mode.
                self._schema_supported = False
                return self.read(jpeg_bytes, seat_marked)
        except openai.APIConnectionError as e:
            raise VisionError(f"Can't reach the local model at {self.base_url}. Is the server running?") from e
        except openai.AuthenticationError as e:
            raise VisionError("The local server rejected the API key.") from e
        except openai.APIStatusError as e:
            raise VisionError(f"Local model error: {e.message}") from e
        if not response.choices:
            raise VisionError("The local model returned no answer.")
        return reconcile_table(parse_table(_extract_json(response.choices[0].message.content or "")))
