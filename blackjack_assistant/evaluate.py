"""Compare card readers on your own labelled screenshots.

1. Turn on "Save screenshots for testing" (Settings → Connection) and play a few rounds.
   Each read is saved in the frames folder as NAME.jpg plus NAME.json (what was read).
2. For frames you want to test, copy NAME.json to NAME.label.json and correct
   player_hands and dealer_cards (and active_hand_index / is_player_turn if needed).
3. Run a reader over the labelled frames:

   python -m blackjack_assistant.evaluate FRAMES_DIR                       # Claude (default model)
   python -m blackjack_assistant.evaluate FRAMES_DIR --model claude-sonnet-5-5
   python -m blackjack_assistant.evaluate FRAMES_DIR --local-url http://localhost:11434/v1 --local-model qwen2.5vl:7b

Cards are compared by rank only (suits don't change the advice).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

from .advisor import advise
from .strategy import Rules, normalize_rank
from .vision import DEFAULT_MODEL, TableState, VisionError


def ranks(cards: list[str]) -> Counter:
    out = Counter()
    for c in cards:
        try:
            out[normalize_rank(c)] += 1
        except ValueError:
            out[str(c)] += 1
    return out


def load_cases(folder: Path) -> list[tuple[Path, dict, bool]]:
    cases = []
    for label in sorted(folder.glob("*.label.json")):
        image = label.with_name(label.name.replace(".label.json", ".jpg"))
        if not image.exists():
            print(f"skipping {label.name}: no {image.name}", file=sys.stderr)
            continue
        truth = json.loads(label.read_text(encoding="utf-8"))
        seat_marked = bool(truth.get("seat_marked", False))
        cases.append((image, truth, seat_marked))
    return cases


def as_state(data: dict) -> TableState:
    from .local_vision import parse_table
    return parse_table(data)


def score(cases, reader, rules: Rules) -> dict:
    rows, times = [], []
    for image, truth, seat_marked in cases:
        expected = as_state(truth)
        started = time.monotonic()
        try:
            got = reader.read(image.read_bytes(), seat_marked=seat_marked)
            error = ""
        except VisionError as e:
            got, error = None, str(e)
        times.append(time.monotonic() - started)
        if got is None:
            rows.append({"frame": image.stem, "player": False, "dealer": False, "advice": False, "error": error})
            continue
        player_ok = [ranks(h) for h in got.player_hands] == [ranks(h) for h in expected.player_hands]
        dealer_ok = ranks(got.dealer_cards) == ranks(expected.dealer_cards)
        advice_ok = advise(got, rules).headline == advise(expected, rules).headline
        rows.append({"frame": image.stem, "player": player_ok, "dealer": dealer_ok, "advice": advice_ok,
                     "got_player": got.player_hands, "want_player": expected.player_hands,
                     "got_dealer": got.dealer_cards, "want_dealer": expected.dealer_cards, "error": ""})
    n = len(rows) or 1
    return {
        "frames": len(rows),
        "player_hand_correct": sum(r["player"] for r in rows) / n,
        "dealer_correct": sum(r["dealer"] for r in rows) / n,
        "advice_correct": sum(r["advice"] for r in rows) / n,
        "seconds_median": statistics.median(times) if times else 0,
        "seconds_max": max(times) if times else 0,
        "rows": rows,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="blackjack_assistant.evaluate", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("frames", type=Path, help="Folder with NAME.jpg + NAME.label.json pairs")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Claude model to test (default: %(default)s)")
    p.add_argument("--local-url", help="Test a local OpenAI-compatible server instead of Claude")
    p.add_argument("--local-model", help="Model name on the local server")
    p.add_argument("--local-api-key", default="")
    p.add_argument("--json", type=Path, help="Also write the full report here")
    args = p.parse_args(argv)

    cases = load_cases(args.frames)
    if not cases:
        print(f"No labelled frames (*.label.json next to a .jpg) in {args.frames}", file=sys.stderr)
        return 1
    if args.local_url:
        if not args.local_model:
            print("--local-model is required with --local-url", file=sys.stderr)
            return 2
        from .local_vision import LocalReader
        reader, name = LocalReader(args.local_url, args.local_model, args.local_api_key), args.local_model
    else:
        from .vision import TableReader
        reader, name = TableReader(model=args.model), args.model

    print(f"Testing {name} on {len(cases)} labelled frames…")
    report = score(cases, reader, Rules())
    for r in report["rows"]:
        if not (r["player"] and r["dealer"]):
            detail = r["error"] or f"you {r['got_player']} (want {r['want_player']}), dealer {r['got_dealer']} (want {r['want_dealer']})"
            print(f"  ✗ {r['frame']}: {detail}")
    print(f"\n{name}")
    print(f"  your hand correct   {report['player_hand_correct']:6.0%}")
    print(f"  dealer correct      {report['dealer_correct']:6.0%}")
    print(f"  same advice         {report['advice_correct']:6.0%}")
    print(f"  seconds per read    {report['seconds_median']:6.1f} median, {report['seconds_max']:.1f} max")
    if args.json:
        args.json.write_text(json.dumps({"model": name, **report}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
