"""Read the blackjack table from a screenshot using Claude's vision."""

from __future__ import annotations

import base64

import anthropic
from pydantic import BaseModel, Field

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You read screenshots of blackjack games (online casino, app, or \
video of a live table) and report exactly what cards are visible.

Rules:
- Report card ranks only: A, 2-10, J, Q, K. Ignore suits.
- The dealer normally shows one face-up card (the upcard) and one face-down card. \
Report only the face-up card(s).
- Report the player's hand(s). If the player has split, list each hand separately \
and say which one is currently being played.
- Set is_player_turn to true only when the game is waiting for the player to choose \
an action (action buttons visible/enabled, or a timer running for the player).
- For available_actions, list the action buttons that are visible and enabled. \
Leave it empty if you cannot tell.
- If no blackjack table is visible, set table_visible to false.
- Never guess a card you cannot read; set confident to false instead."""


class TableState(BaseModel):
    table_visible: bool = Field(description="Whether a blackjack table is on screen")
    dealer_cards: list[str] = Field(description="Dealer's face-up card ranks, e.g. ['K']")
    player_hands: list[list[str]] = Field(description="Each player hand as a list of ranks")
    active_hand_index: int = Field(description="Index into player_hands of the hand being played; 0 if not split")
    is_player_turn: bool = Field(description="True if the game is waiting for the player's decision")
    available_actions: list[str] = Field(
        description="Enabled action buttons, lowercase: hit, stand, double, split, surrender"
    )
    confident: bool = Field(description="False if any relevant card was hard to read")


class VisionError(RuntimeError):
    pass


class TableReader:
    def __init__(self, model: str = DEFAULT_MODEL, client: anthropic.Anthropic | None = None):
        self.model = model
        self.client = client or anthropic.Anthropic()

    def read(self, png_bytes: bytes) -> TableState:
        image_b64 = base64.standard_b64encode(png_bytes).decode("ascii")
        response = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            # Reading cards is a simple perception task: low effort keeps it fast.
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                    {"type": "text", "text": "Read the current blackjack table state."},
                ],
            }],
            output_format=TableState,
        )
        if response.stop_reason == "refusal":
            raise VisionError("The model declined to read this screenshot")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise VisionError(f"Could not parse table state (stop_reason={response.stop_reason})")
        return response.parsed_output
