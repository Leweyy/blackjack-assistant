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
and say which one is currently being played. "The player" is the person whose screen \
this is (their seat/hand is usually highlighted, at the bottom, or labelled with their \
balance or "You"). If everyone at the table shares one hand (e.g. Infinite Blackjack), \
that shared hand is the player's hand.
- Report every other face-up card on the table (other seats/players) in \
other_players_cards. Include each physical card once. This is used for card counting, \
so be complete and do not double-list cards already in dealer_cards or player_hands.
- Once the dealer turns over the hole card and draws, dealer_cards should list all of \
the dealer's face-up cards in order, upcard first.
- Set is_player_turn to true only when the game is waiting for the player to choose \
an action (action buttons visible/enabled, or a timer running for the player).
- For available_actions, list the action buttons that are visible and enabled. \
Leave it empty if you cannot tell.
- is_betting_phase: true while bets are being placed for the next round (betting \
timer / "place your bets" shown, no cards dealt yet).
- round_complete: true once the round is over: the dealer has finished drawing and \
results/payouts are shown, with the cards still on the table.
- shuffle_detected: true if the screen shows the shoe being shuffled or replaced \
("shuffling", "new shoe", the cut card has come out, dealer visibly shuffling).
- insurance_offered: true if the game is currently asking whether to take insurance \
or even money.
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
    other_players_cards: list[str] = Field(description="Face-up card ranks of every other seat at the table")
    is_betting_phase: bool = Field(description="True while bets are being placed and no cards are dealt")
    round_complete: bool = Field(description="True when the dealer has finished and results are shown")
    shuffle_detected: bool = Field(description="True if the shoe is being shuffled or replaced")
    insurance_offered: bool = Field(description="True if insurance / even money is being offered now")
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
