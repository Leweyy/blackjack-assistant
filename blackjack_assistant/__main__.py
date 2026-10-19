"""Command-line version: python -m blackjack_assistant (the desktop app lives in desktop/)."""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

from .advisor import Advice, BetSettings, advise
from .capture import MAX_SIDE, CaptureError, Region, ScreenGrabber, WindowGrabber, to_jpeg
from .counting import HiLoCounter, RoundTracker
from .engine import watch_loop
from .strategy import Rules
from .vision import DEFAULT_MODEL, TableReader


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="blackjack_assistant",
        description="Watches your screen while you play blackjack and recommends the basic-strategy move.",
    )
    p.add_argument("--interval", type=float, default=1.5, help="Seconds between screen checks (default 1.5)")
    p.add_argument("--region", type=Region.parse, help="Screen area to watch: left,top,width,height")
    p.add_argument("--window", metavar="TITLE", help="Watch the window with this title (Windows only)")
    p.add_argument("--monitor", type=int, default=1, help="Monitor number when no region is given (default 1)")
    p.add_argument("--h17", action="store_true", help="Dealer hits soft 17 (default: stands)")
    p.add_argument("--no-das", action="store_true", help="Double after split NOT allowed")
    p.add_argument("--no-surrender", action="store_true", help="Surrender not offered")
    p.add_argument("--decks", type=int, default=8, help="Decks in the shoe, for the true count (default 8)")
    p.add_argument("--unit", type=float, help="Money per betting unit, e.g. 10 (shows bet amounts)")
    p.add_argument("--max-units", type=int, default=8, help="Biggest bet in units: your bet spread (default 8)")
    p.add_argument("--no-count", action="store_true", help="Turn off card counting (basic strategy only)")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model (default {DEFAULT_MODEL})")
    p.add_argument("--local-url", metavar="URL",
                   help="Use a local model server instead of Claude, e.g. http://localhost:11434/v1 (Ollama)")
    p.add_argument("--local-model", metavar="NAME", help="Model name on the local server, e.g. qwen2.5vl:7b")
    p.add_argument("--local-api-key", default="", help="API key for the local server, if it needs one")
    p.add_argument("--image", type=Path, help="Analyse one screenshot file and exit (handy for testing)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    rules = Rules(
        dealer_hits_soft_17=args.h17,
        double_after_split=not args.no_das,
        surrender_allowed=not args.no_surrender,
    )
    if args.local_url:
        if not args.local_model:
            print("--local-model is required with --local-url", file=sys.stderr)
            return 2
        from .local_vision import LocalReader
        reader = LocalReader(args.local_url, args.local_model, args.local_api_key)
    else:
        reader = TableReader(model=args.model)
    bets = BetSettings(unit=args.unit, max_units=args.max_units)
    tracker = None if args.no_count else RoundTracker(HiLoCounter(decks=args.decks))

    if args.image:
        from PIL import Image
        with Image.open(args.image) as img:
            state = reader.read(to_jpeg(img, getattr(reader, "max_side", MAX_SIDE)))
        if tracker:
            tracker.observe(state)
        advice = advise(state, rules, tracker.snapshot() if tracker else None, bets)
        print(f"{advice.headline}\n{advice.detail}\n{advice.count_line}")
        print(state.model_dump_json(indent=2))
        return 0

    if args.window:
        try:
            grabber = WindowGrabber(0, args.window)
        except CaptureError as e:
            print(e, file=sys.stderr)
            return 1
    else:
        grabber = ScreenGrabber(region=args.region, monitor=args.monitor)
    stop = threading.Event()

    def emit(item):
        if isinstance(item, Advice):
            print(f"\n>>> {item.headline}   {item.detail}", flush=True)
            if item.count_line:
                print(f"    {item.count_line}", flush=True)
        elif item.startswith("Error"):
            print(item, file=sys.stderr, flush=True)

    try:
        watch_loop(grabber, reader, rules, args.interval, emit, stop, tracker, bets)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
