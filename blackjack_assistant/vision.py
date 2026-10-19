"""Read the blackjack table from a screenshot using Claude's vision."""

from __future__ import annotations

import base64

import anthropic
from pydantic import BaseModel, Field

from .reconcile import reconcile_table

DEFAULT_MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = """You read screenshots of blackjack games (online casino, app, or \
video of a live table) and report exactly what cards are visible.

Rules:
- Write each card as its rank (A, 2-10, J, Q, K) followed by its suit symbol \
(♠ ♥ ♦ ♣), e.g. "10♣", "A♥", "7♠". If a card's suit can't be made out, write the rank alone.
- List each physical card exactly ONCE. Live-dealer games usually show every card twice: \
the real card in the video and again as a digital card graphic, card icon or "card \
history" next to the seat or the dealer. These are the same card, not two cards: never \
list both. A hand that looks like "K 4 4" or "K K 4 4" is almost always "K 4" seen twice.
- The dealer normally shows one face-up card (the upcard) and one face-down card. \
Report only the face-up card(s).
- player_hand_totals: for each of the player's hands, the hand value the game itself \
displays (e.g. "14", "4/14", "Soft 17", "BJ"), copied exactly; "" if none is shown. \
dealer_total_shown: the same for the dealer. These are used to double-check the cards.
- player_hands is ONLY the hand(s) of "the player": the person whose screen this is. \
Never put another seat's cards in player_hands. If the player has split, list each of \
their hands separately and say which one is currently being played.
- Finding the player's seat: in live-dealer games there are several seats. The player's \
own seat is usually highlighted or outlined, shows their bet chips and hand total in a \
larger bubble, or is labelled "You", with their name or with their balance. When the \
decision buttons are showing, the hand the game is asking about is the player's. If \
everyone shares one hand (e.g. Infinite Blackjack), that shared hand is the player's.
- If you cannot tell which seat is the player's, leave player_hands empty and set \
confident to false. Do not guess, because the advice would be for someone else's hand.
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

SEAT_MARKER_NOTE = """The player's seat has been marked on this screenshot with a bright \
magenta box labelled "YOU". That is the player's seat for certain: player_hands must \
contain only the cards inside that box (including split hands there). Cards outside the \
box belong to other seats, even if they are close to it: put them in other_players_cards. \
The box itself is not part of the game."""


class TableState(BaseModel):
    table_visible: bool = Field(description="Whether a blackjack table is on screen")
    dealer_cards: list[str] = Field(description="Dealer's face-up cards, e.g. ['K♠']")
    player_hands: list[list[str]] = Field(description="Each of the player's hands as a list of cards, e.g. [['9♥', '5♠']]")
    player_hand_totals: list[str] = Field(
        description="Hand value displayed by the game for each player hand, e.g. ['14'] or ['4/14']; '' if not shown")
    dealer_total_shown: str = Field(description="Dealer hand value displayed by the game, e.g. '10'; '' if not shown")
    active_hand_index: int = Field(description="Index into player_hands of the hand being played; 0 if not split")
    is_player_turn: bool = Field(description="True if the game is waiting for the player's decision")
    available_actions: list[str] = Field(
        description="Enabled action buttons, lowercase: hit, stand, double, split, surrender"
    )
    other_players_cards: list[str] = Field(description="Face-up cards of every other seat at the table")
    is_betting_phase: bool = Field(description="True while bets are being placed and no cards are dealt")
    round_complete: bool = Field(description="True when the dealer has finished and results are shown")
    shuffle_detected: bool = Field(description="True if the shoe is being shuffled or replaced")
    insurance_offered: bool = Field(description="True if insurance / even money is being offered now")
    confident: bool = Field(description="False if any relevant card was hard to read")


class VisionError(RuntimeError):
    pass


def model_options(model: str) -> dict:
    """Request options tuned for speed on each model family.

    Reading cards is a perception task, so extended thinking only adds latency:
    turn it off where the model allows it (Opus 5.5 can't disable thinking, so it
    runs at low effort instead). Server-side refusal fallbacks are supported on
    Opus and Sonnet but not on Haiku, where the parameter must be left out.
    """
    opts: dict = {"output_config": {"effort": "low"}}
    if model.startswith("claude-sonnet-5-5"):
        opts["thinking"] = {"type": "between_tools"}  # Sonnet 5.5's "thinking off"
    elif model.startswith("claude-haiku"):
        opts["thinking"] = {"type": "disabled"}
    if not model.startswith("claude-haiku"):
        opts["betas"] = ["server-side-fallback-2026-07-01"]
        opts["fallbacks"] = "default"
    return opts


class TableReader:
    def __init__(self, model: str = DEFAULT_MODEL, client: anthropic.Anthropic | None = None):
        self.model = model
        self.client = client or anthropic.Anthropic()

    def read(self, jpeg_bytes: bytes, seat_marked: bool = False) -> TableState:
        image_b64 = base64.standard_b64encode(jpeg_bytes).decode("ascii")
        response = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM_PROMPT,
            **model_options(self.model),
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                    {"type": "text", "text": (SEAT_MARKER_NOTE + "\n\n" if seat_marked else "")
                     + "Read the current blackjack table state."},
                ],
            }],
            output_format=TableState,
        )
        if response.stop_reason == "refusal":
            raise VisionError("The model declined to read this screenshot")
        if response.stop_reason == "max_tokens" or response.parsed_output is None:
            raise VisionError(f"Could not parse table state (stop_reason={response.stop_reason})")
        return reconcile_table(response.parsed_output)
