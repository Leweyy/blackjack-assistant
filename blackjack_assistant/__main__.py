"""Entry point: python -m blackjack_assistant"""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from pathlib import Path

import anthropic

from .advisor import Advice, BetSettings, advise
from .capture import ChangeDetector, Region, ScreenGrabber, to_png
from .counting import HiLoCounter, RoundTracker
from .strategy import Rules
from .vision import DEFAULT_MODEL, TableReader, VisionError


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="blackjack_assistant",
        description="Watches your screen while you play blackjack and recommends the basic-strategy move.",
    )
    p.add_argument("--interval", type=float, default=1.5, help="Seconds between screen checks (default 1.5)")
    p.add_argument("--region", type=Region.parse, help="Screen area to watch: left,top,width,height")
    p.add_argument("--select-region", action="store_true", help="Drag a box around the table at startup")
    p.add_argument("--monitor", type=int, default=1, help="Monitor number when no region is given (default 1)")
    p.add_argument("--h17", action="store_true", help="Dealer hits soft 17 (default: stands)")
    p.add_argument("--no-das", action="store_true", help="Double after split NOT allowed")
    p.add_argument("--no-surrender", action="store_true", help="Surrender not offered")
    p.add_argument("--decks", type=int, default=8, help="Decks in the shoe, for the true count (default 8)")
    p.add_argument("--unit", type=float, help="Money per betting unit, e.g. 10 (shows bet amounts)")
    p.add_argument("--max-units", type=int, default=8, help="Biggest bet in units: your bet spread (default 8)")
    p.add_argument("--no-count", action="store_true", help="Turn off card counting (basic strategy only)")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model (default {DEFAULT_MODEL})")
    p.add_argument("--terminal", action="store_true", help="Print advice in the terminal instead of an overlay window")
    p.add_argument("--image", type=Path, help="Analyse one screenshot file and exit (handy for testing)")
    return p.parse_args(argv)


def watch_loop(grabber, reader, rules, interval, emit, stop: threading.Event,
               tracker: RoundTracker | None = None, bets: BetSettings = BetSettings()):
    detector = ChangeDetector()
    last_headline_detail = None
    while not stop.is_set():
        started = time.monotonic()
        try:
            img = grabber.grab()
            if detector.changed(img):
                emit("Reading table…")
                state = reader.read(to_png(img))
                count = None
                if tracker:
                    tracker.observe(state)
                    count = tracker.snapshot()
                advice = advise(state, rules, count, bets)
                key = (advice.headline, advice.detail, advice.count_line)
                if key != last_headline_detail:
                    emit(advice)
                    last_headline_detail = key
                emit(f"Updated {time.strftime('%H:%M:%S')}")
        except (VisionError, anthropic.APIError) as e:
            emit(f"Error: {e}")
        stop.wait(max(0.0, interval - (time.monotonic() - started)))


def main(argv=None) -> int:
    args = parse_args(argv)
    rules = Rules(
        dealer_hits_soft_17=args.h17,
        double_after_split=not args.no_das,
        surrender_allowed=not args.no_surrender,
    )
    reader = TableReader(model=args.model)
    bets = BetSettings(unit=args.unit, max_units=args.max_units)
    tracker = None if args.no_count else RoundTracker(HiLoCounter(decks=args.decks))

    if args.image:
        state = reader.read(args.image.read_bytes())
        if tracker:
            tracker.observe(state)
        advice = advise(state, rules, tracker.snapshot() if tracker else None, bets)
        print(f"{advice.headline}\n{advice.detail}\n{advice.count_line}")
        print(state.model_dump_json(indent=2))
        return 0

    region = args.region
    if args.select_region:
        from .overlay import select_region
        region = select_region()
        if region is None:
            print("No region selected.", file=sys.stderr)
            return 1
        print(f"Watching region {region.left},{region.top},{region.width},{region.height} "
              f"(pass --region to reuse it)")

    grabber = ScreenGrabber(region=region, monitor=args.monitor)
    stop = threading.Event()

    if args.terminal:
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

    from .overlay import Overlay
    updates: queue.Queue = queue.Queue()
    overlay = Overlay(updates, on_reset_count=tracker.reset if tracker else None)
    worker = threading.Thread(
        target=watch_loop, args=(grabber, reader, rules, args.interval, updates.put, stop, tracker, bets),
        daemon=True,
    )
    worker.start()
    try:
        overlay.run()
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
