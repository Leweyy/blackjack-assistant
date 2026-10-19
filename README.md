# Blackjack Assistant

A Windows app that watches your blackjack game and tells you the best move (hit, stand,
double, split or surrender) in a small always-on-top window. For live-dealer games it
also **counts cards** (Hi-Lo) and tells you when to raise or lower your bet.

## Install (Windows)

1. Open the latest release from the repository's
   [**Releases**](https://github.com/Leweyy/blackjack-assistant/releases) page and
   download one of these:
   - `BlackjackAssistant-<version>-setup.exe`: an installer that adds Start-menu and
     desktop shortcuts.
   - `BlackjackAssistant-<version>-portable.exe`: a single file you can run without
     installing.
   - `BlackjackAssistant-<version>-linux-x86_64.AppImage`: for Linux.
2. The app isn't code-signed, so Windows SmartScreen may warn you the first time. Click
   **More info → Run anyway**.

There's no auto-update yet. To update, download the new version from Releases.

## Using it

1. **Connection:** paste your Anthropic API key (create one at
   [console.anthropic.com](https://console.anthropic.com/settings/keys)), or choose
   **Local model** to use your own Ollama or vLLM server (see below). Optionally use
   **Test with a screenshot** to check it reads your game correctly.
2. **Table rules:** match your table: whether the dealer hits soft 17, double after
   split, and surrender.
3. **Counting & bets:** decks in the shoe, your betting unit and your maximum bet.
4. **Screen:** choose what to watch:
   - **A window** (Windows only): pick the browser or casino-app window from the list
     of thumbnails. It follows the window when you move or resize it. Keep it visible
     (not minimised).
   - **Table area:** drag a box around the table. Include the other players' seats so
     every card can be counted.
   - **Whole monitor:** simplest option, but costs more and is less accurate.

   The assistant's own windows are hidden from screen captures, so they can sit on top
   of the game.

   **Your seat:** at a table with several players, click **Mark my seat** (or **📍 Seat**
   in the advice window while playing) and drag a box around just your cards, on top of
   the game. Leave room for extra cards but don't include the next seat. A magenta "YOU"
   box is then drawn there on every screenshot, and only the cards inside it are used for
   advice. Other players' cards still count towards the card count. Without a marked seat
   it tries to work out your seat itself, and reports no hand rather than guessing when it
   can't tell.
5. Press **Start**. The advice window appears in the top-right corner. Drag it anywhere.
   It shows the move, your hand and the dealer's as small cards (e.g. ♥9 ♠5 vs ♣10)
   with their totals, and the count. The footer shows the status, including how long the
   last read took, and has these buttons:
   - **📍 Seat** marks your seat (see above).
   - **↺ Shoe** (or **R**) resets the count if a shuffle wasn't detected.
   - **✕** (or **Esc**) stops watching.

Settings save automatically to `%APPDATA%\BlackjackAssistant\settings.json`. The API key
is stored there too, in plain text in your user profile.

Advice colours: green = hit, red = stand, amber = double, blue = split, purple =
surrender, teal = raise your bet, grey = waiting / minimum bet.

## How it works

```
Electron app (React/TSX)  ── JSON over stdin/stdout ──  Python backend
  settings window                                        screen capture (mss)
  advice overlay                                         Claude vision → cards on the table
  table-area picker                                      Hi-Lo count + basic strategy
```

1. **Capture:** the backend grabs the table area every ~1.5 s. Unchanged frames are
   skipped.
2. **Read the table:** the screenshot goes to Claude, which returns structured JSON:
   the dealer's cards, your hand(s), other players' cards, whether it's your turn, the
   betting phase, the end of a round, shuffles, and the visible buttons. Live games show
   each card twice (on video and as a digital copy), so each hand is checked against the
   total the game displays, and a card read twice is dropped.
3. **Decide:** a local, deterministic strategy engine (`strategy.py`) picks the move.
   The AI only reads the cards; it doesn't choose the move. The engine uses basic
   strategy for your rules, adjusted by the true count when counting is on.
4. **Show:** the overlay updates and plays a sound when it's your turn.

## Local models (Ollama, vLLM, LM Studio)

Instead of Claude, the cards can be read by a vision model running on your own machine
or another PC on your network: free, offline, and as fast as your GPU allows. Counting,
strategy and the overlay work the same either way.

1. Run a server with a vision model, for example:
   - **Ollama on Windows:** install from ollama.com, then `ollama pull qwen2.5vl:7b`.
   - **Ollama in Docker:** `docker compose -f docker-compose.ollama.yml up -d`, then
     `docker compose -f docker-compose.ollama.yml exec ollama ollama pull qwen2.5vl:7b`.
     This needs GPU access in Docker: Docker Desktop with WSL2, or the NVIDIA Container
     Toolkit on Linux.
   - **vLLM** (Linux, or WSL2/Docker on Windows): `vllm serve Qwen/Qwen2.5-VL-7B-Instruct`.
     vLLM's options change between versions, so check its docs for image limits and memory
     settings.
2. In the app, open **Connection → Local model**, pick the preset (Ollama
   `http://localhost:11434/v1`, vLLM `http://localhost:8000/v1`, LM Studio
   `http://localhost:1234/v1`) or type another address, then press **Test connection**
   and choose the model.
3. Use **Test with a screenshot** to check it reads your table, then press Start.

Notes:

- **Model size:** smaller models misread cards more often. A 7B model is the minimum
  worth trying; a 32B model (quantised to fit in 24 GB) is a better balance. Marking your
  seat matters more with small models.
- **Image size** (Connection tab) defaults to 1024 px for local models. Lower is faster,
  higher helps if cards are misread.
- **Faster updates:** Ollama only overlaps two reads if started with
  `OLLAMA_NUM_PARALLEL=2` (the compose file sets this). vLLM overlaps them by default.
- **Format quirks:** the app copes with how small models often reply (thinking blocks,
  code fences, "9H" or "9 of hearts" for 9♥). If the server doesn't support strict JSON
  output, it falls back to plain JSON mode automatically.

### Comparing models on your own table

Turn on **Save screenshots for testing** (Connection tab) and play a few rounds. Every
read is saved as `NAME.jpg` plus `NAME.json` (what was read). Use **Open folder** to find
them. To label a frame, copy `NAME.json` to `NAME.label.json` and correct the cards. Then
compare readers on the labelled frames:

```bash
python -m blackjack_assistant.evaluate "%APPDATA%\BlackjackAssistant\frames"
python -m blackjack_assistant.evaluate FRAMES --model claude-sonnet-5-5
python -m blackjack_assistant.evaluate FRAMES --local-url http://localhost:11434/v1 --local-model qwen2.5vl:7b
```

It reports how often your hand, the dealer's cards and the resulting advice were right,
plus the time per read.

## Card counting (live-dealer games)

Counting is on by default and is designed for **live-dealer tables dealt from a shoe**.
Computer-dealt online blackjack usually shuffles every hand, so counting does nothing
there. Turn it off under Counting & bets.

- **Counting:** at the end of each round, when all cards are face up, it adds every card
  on the table to a Hi-Lo running count: yours, the dealer's (including the hole card)
  and other players'. Cards 2–6 add 1, 7–9 add 0, and 10s and aces subtract 1. Each
  round is counted once. If the end-of-round screen is missed, the last view of that
  round is counted when betting opens again.
- **True count:** the running count ÷ decks left in the shoe.
- **Bet advice:** shown during betting. It's a 1-to-N ramp: minimum bet until the true
  count reaches +2, then 2 units for each extra +1, up to your maximum bet. At −2 or
  below it suggests sitting out.
- **Count-based plays:** the move advice uses the Illustrious 18 and Fab 4 surrender
  index plays, e.g. stand on 16 vs 10 at TC ≥ 0, and take insurance only at TC ≥ +3.
- **Shuffles:** a detected shuffle or new shoe resets the count to 0.

**Accuracy matters:** a missed or misread card stays in the count for the rest of the
shoe. Compare its count with your own for the first few shoes. Burn cards and cards
hidden by the video framing can't be counted.

## Speed

Each read is one round trip to Claude. To get advice inside your decision window:

- Screenshots are sent as compact JPEGs, so the upload is quick.
- **Faster updates** (on by default) sends the next screenshot while the previous one is
  still being read, up to two at a time. A card dealt just after a screenshot then shows
  up about one read later instead of two. Late answers that are older than what's already
  shown are dropped.
- Model choice matters most. **Claude Sonnet 5.5** and **Claude Haiku 5.5** run with
  thinking turned off and answer noticeably faster than Opus, which always thinks a
  little. Try Sonnet first: it reads cards well.
- A smaller capture (a window or table area rather than the whole monitor) means less to
  upload and read.

The footer of the advice window shows how long each read took, so you can compare.

## Cost

A live video feed changes almost every frame, so expect about **one API request per
check** (40 per minute at the default 1.5 s), up to about twice that with Faster updates.
With Claude Opus 5.5 that can add up to tens of dollars per hour of play. To reduce it:

- set **Check every** to 3 seconds (about half the cost; counting still works because
  rounds are counted when they finish)
- select a table area rather than the whole monitor
- choose **Claude Haiku 5.5** under Connection (far cheaper, but may misread cards more
  often; try it with a few screenshots first)

Check your usage in the Anthropic Console during your first session.

## Notes

- Basic strategy reduces the house edge but doesn't remove it. Counting only helps on
  shoe games with deep penetration, and only if the count is accurate. Play
  responsibly.
- Many online casinos ban assistance software in their terms of service, and live
  casinos may restrict players they think are counting. Check the rules where you play.
- When the overlay shows ⚠ low confidence, check the cards yourself before acting.

## Development

Requirements: Python 3.10+ and Node 22+.

```bash
# Python backend
pip install -e ".[dev]"
pytest

# Desktop app (runs the backend from source with `python -m blackjack_assistant.server`)
cd desktop
npm install
npm start
```

Set `BJ_PYTHON` to choose the Python interpreter used in development. To build the
installers for your platform locally, build the backend first, then run `npm run dist`:

```bash
pyinstaller --onefile --console --name blackjack-backend --distpath desktop/backend-dist run_backend.py
cd desktop && npm run dist     # output in desktop/release/
```

### CI and releases

- **`build` workflow** runs on every branch push, on pull requests, and on demand
  (Actions → build → Run workflow). It runs the tests, builds the backend and the
  Windows installers, smoke-tests the packaged app, and uploads the `.exe` files as a
  run artifact.
- **`release` workflow** runs when you push a `v*` tag. It builds and smoke-tests on
  Windows and Linux, then creates the GitHub release with generated notes and attaches
  the installers. If the tag already has a release, it replaces the files instead, so
  re-running a failed release is safe.

To release a new version:

```bash
# 1. bump "version" in desktop/package.json (e.g. 0.3.0), then
git commit -am "Release v0.3.0"
git tag v0.3.0
git push origin HEAD v0.3.0
```

The workflow fails early if the tag doesn't match the version in `desktop/package.json`.
You can also skip the tag: bump the version, push, then run **Actions → release → Run
workflow**. It creates the `v<version>` tag on that commit for you.
To publish from your own machine instead, build the backend, then run
`npm run release` in `desktop/`. It does the same thing using the `gh` CLI.

There's also a command-line version that prints advice in a terminal:
`python -m blackjack_assistant --region 200,150,1100,700` or
`--window "Live Blackjack"` (see `--help`).

| Path | What |
|---|---|
| `blackjack_assistant/strategy.py` | Basic strategy + count index plays |
| `blackjack_assistant/counting.py` | Hi-Lo count, bet ramp, round tracking |
| `blackjack_assistant/vision.py` | Claude vision → structured table state |
| `blackjack_assistant/local_vision.py` | Same, via a local OpenAI-compatible server |
| `blackjack_assistant/reconcile.py` | Card-name cleanup and double-read fixes |
| `blackjack_assistant/evaluate.py` | Compare readers on labelled screenshots |
| `blackjack_assistant/server.py` | JSON-lines backend used by the desktop app |
| `desktop/src/main/` | Electron main process and preload bridge |
| `desktop/src/renderer/` | React UI: settings, overlay, area picker |
