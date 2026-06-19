"""Command-line entrypoint: ``python -m radar``.

Examples:
  python -m radar                     # one autonomous cycle (used by CI)
  python -m radar --once --dry-run    # local test: print instead of sending
  python -m radar --force-digest      # send the digest now regardless of time
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Config
from .logging_setup import configure_logging
from .pipeline import RunOptions, run
from .state import State

log = logging.getLogger("radar")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radar", description="Kansai Radar — free autonomous Kansai event bot."
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--state", default="state.json", help="Path to state.json")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle and exit (default behaviour; here for clarity).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print messages instead of sending; performs no Telegram I/O.",
    )
    parser.add_argument(
        "--force-digest",
        action="store_true",
        help="Send the digest now, ignoring the once-per-day / hour gate.",
    )
    parser.add_argument(
        "--skip-collect",
        action="store_true",
        help="Skip source collection; operate on existing state only.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run forever, answering commands instantly (for a free 24/7 host).",
    )
    parser.add_argument(
        "--serve-interval",
        type=int,
        default=1800,
        help="Seconds between full pipeline runs in --serve mode (default 1800).",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.verbose)

    try:
        cfg = Config.load(args.config)
    except FileNotFoundError:
        log.error("Config file not found: %s", args.config)
        return 2

    if args.serve:
        from .serve import serve

        return serve(cfg, args.state, args.serve_interval)

    state = State.load(args.state)
    opts = RunOptions(
        dry_run=args.dry_run,
        force_digest=args.force_digest,
        skip_collect=args.skip_collect,
    )
    try:
        run(cfg, state, opts)
    except Exception as exc:  # noqa: BLE001 - top-level safety net
        log.exception("Run failed: %s", exc)
        return 1
    log.info("Run complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
