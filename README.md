# Blackjack Assistant

Watches your screen while you play blackjack and tells you the best move (hit, stand,
double, split or surrender) in a small always-on-top window. For live-dealer games it
also **counts cards** (Hi-Lo) and tells you when to raise or lower your bet.

```
┌──────────────────────────────┐
│           DOUBLE             │
│ Hard 11 vs 6 · You: 5 6 · Dealer: 6 │
└──────────────────────────────┘
```

## How it works

1. **Capture**: grabs the screen (or just the area you choose) every ~1.5 s with `mss`.
   If nothing on screen has changed, no API call is made.
2. **Read the table**: when the screen changes, the screenshot goes to Claude's vision
   model. It returns structured JSON: the dealer's upcard, your hand(s), whether it's
   your turn, and which action buttons are showing.
3. **Decide**: a local, deterministic **basic-strategy engine** (`strategy.py`) picks the
   move. The AI only reads the cards; it doesn't choose the move. So the advice always
   follows the mathematically correct chart for your table rules.
4. **Show**: the overlay changes colour and beeps when it's your turn to act.

## Card counting (live-dealer games)

Counting is on by default. It is designed for **live-dealer tables dealt from a shoe**.
Standard computer-dealt online blackjack shuffles every hand, so counting does nothing
there; turn it off with `--no-count`.

- **How cards are counted:** at the end of each round, when all cards are face up, it
  adds every card on the table to a Hi-Lo running count: yours, the dealer's
  (including the hole card) and other players'. Cards 2–6 add 1, 7–9 add 0, and 10s
  and aces subtract 1. Each round is counted once. If the end-of-round screen is
  missed, the last view of that round is counted when betting opens again.
- **True count:** the running count ÷ decks left in the shoe (set the shoe size with
  `--decks`; most live tables use 8).
- **Bet advice:** shown during the betting phase. It's a standard 1–8 ramp: minimum
  bet until the true count reaches +2, then 2 units for each extra +1, up to
  `--max-units`. Pass `--unit 10` to show the amounts in money. At a true count of
  −2 or below it suggests sitting out if the table lets you.
- **Count-based plays:** the move advice uses the *Illustrious 18* and *Fab 4*
  surrender index plays, e.g. stand on 16 vs 10 at TC ≥ 0, double 11 vs A at TC ≥ +1,
  take insurance only at TC ≥ +3.
- **Shuffles:** when the screen shows a shuffle or new shoe, the count resets to 0.
  If it misses one, press **R** in the overlay to reset the count yourself.

The yellow line in the overlay shows: running count, true count, decks left, and an
estimate of your edge.

**Accuracy matters:** a missed or misread card stays in the count for the rest of the
shoe. Watch the first few shoes and compare its count with your own. Burn cards and
cards hidden by the video framing can't be counted. Choosing a region that shows the
whole table (`--select-region`) helps.

Supported: multi-deck (4–8 deck) basic strategy, dealer stands or hits on soft 17,
double after split on or off, late surrender on or off, and split hands (it advises
on the hand being played). If the table doesn't offer a move (for example, no Double
button after 3 cards), it falls back to the correct alternative.

## Setup

Requires Python 3.10+ with Tk. Tk is included with the python.org installers for
macOS and Windows. On Linux, run `sudo apt install python3-tk`.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...   # Windows: set ANTHROPIC_API_KEY=...
```

**macOS:** grant your terminal *Screen Recording* permission
(System Settings → Privacy & Security → Screen Recording), then restart the terminal.

## Usage

```bash
# Recommended: drag a box around the game table first
blackjack-assistant --select-region

# Reuse a region it printed earlier (left,top,width,height)
blackjack-assistant --region 200,150,1100,700

# Match your table's rules
blackjack-assistant --select-region --h17 --no-surrender

# No window, just print advice in the terminal
blackjack-assistant --select-region --terminal

# Test on a saved screenshot
blackjack-assistant --image table.png
```

| Option | Meaning |
|---|---|
| `--select-region` | Drag a rectangle around the table at startup (more accurate, cheaper) |
| `--region L,T,W,H` | Watch a fixed screen area |
| `--monitor N` | Which monitor to watch when no region is set (default 1) |
| `--interval S` | Seconds between checks (default 1.5) |
| `--h17` | Dealer hits soft 17 (default: stands) |
| `--no-das` | Double after split not allowed |
| `--no-surrender` | Surrender not offered |
| `--decks N` | Decks in the shoe for the true count (default 8) |
| `--unit X` | Money per betting unit, e.g. `10`, so bet advice shows amounts |
| `--max-units N` | Your largest bet in units, i.e. your bet spread (default 8) |
| `--no-count` | Turn off card counting |
| `--terminal` | Print to the terminal instead of showing the overlay |
| `--image FILE` | Analyse one screenshot and exit |
| `--model ID` | Claude model to use (default `claude-opus-5-5`) |

In the overlay, drag the window to move it, press **R** to reset the count at a new
shoe, and press **Esc** to quit.

Overlay colours: green = HIT, red = STAND, yellow = DOUBLE, blue = SPLIT,
purple = SURRENDER, teal = raise your bet, grey = waiting / minimum bet.

## Cost and speed

Each time the screen changes, the app makes one vision request at low effort. A live
video feed changes almost every frame, so expect roughly **one request per
`--interval`** (40 per minute at the default 1.5 s). With the default
`claude-opus-5-5` model, that can add up to tens of dollars per hour of play. To
reduce it:

- `--interval 3` halves the number of calls. Counting still works because each round
  is counted at its end, but advice will appear a little later.
- `--select-region` sends smaller images.
- `--model claude-haiku-5-5` costs a small fraction as much but may misread cards
  more often. Try it with `--image` on a few screenshots first.

Check your usage in the Anthropic Console during your first session.

## Notes

- Basic strategy reduces the house edge but **does not remove it**. Over time you
  should still expect to lose money. Play responsibly.
- Counting only gives an edge on shoe games with deep penetration, and only if the
  count is accurate. Live casinos may limit or ban players they think are counting.
- Many online casinos ban third-party assistance software in their terms of service.
  Check the rules of wherever you play.
- When the overlay shows ⚠ low confidence, check the cards yourself before acting.

## Development

```bash
pip install -e ".[dev]"
pytest
```
