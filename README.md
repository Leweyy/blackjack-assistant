# Blackjack Assistant

Watches your screen while you play blackjack and tells you the best move (hit, stand,
double, split or surrender) in a small always-on-top window.

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
| `--terminal` | Print to the terminal instead of showing the overlay |
| `--image FILE` | Analyse one screenshot and exit |
| `--model ID` | Claude model to use (default `claude-opus-5-5`) |

In the overlay, drag the window to move it and press **Esc** to quit.

Overlay colours: green = HIT, red = STAND, yellow = DOUBLE, blue = SPLIT,
purple = SURRENDER, grey = waiting.

## Cost and speed

Each time the screen changes, the app makes one vision request at low effort. The
change detector skips identical frames, and choosing a region makes the images
smaller. Increase `--interval` to make fewer calls. To use a cheaper or faster model,
pass `--model claude-haiku-5-5` (it may misread cards more often).

## Notes

- Basic strategy reduces the house edge but **does not remove it**. Over time you
  should still expect to lose money. Play responsibly.
- Many online casinos ban third-party assistance software in their terms of service.
  Check the rules of wherever you play.
- When the overlay shows ⚠ low confidence, check the cards yourself before acting.

## Development

```bash
pip install -e ".[dev]"
pytest
```
