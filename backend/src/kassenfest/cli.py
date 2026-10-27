import argparse
import asyncio
import sys

from kassenfest.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="kassenfest")
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("smoke", help="check Muse Spark + SAM 3.1 end to end")
    smoke.add_argument("--mode", choices=["live", "record", "replay"], help="override LLM_MODE")
    spike = sub.add_parser("spike", help="run spikes S1-S4 and print their numbers")
    spike.add_argument("which", choices=["s1", "s2", "s3", "all"])
    spike.add_argument("--muster12", type=int, default=8, help="Muster 12 documents (x3 variants)")
    spike.add_argument("--visit-logs", type=int, default=4, help="visit logs (x2 variants)")
    spike.add_argument("--mode", choices=["live", "record", "replay"], help="override LLM_MODE")
    args = parser.parse_args()

    from kassenfest.llm import CacheMiss

    settings = Settings(llm_mode=args.mode) if args.mode else Settings()
    try:
        if args.command == "smoke":
            from kassenfest import smoke as smoke_mod

            sys.exit(asyncio.run(smoke_mod.run(settings)))
        if args.command == "spike":
            from kassenfest import spikes

            sys.exit(asyncio.run(spikes.run(settings, args.which, args.muster12, args.visit_logs)))
    except (CacheMiss, RuntimeError) as exc:
        sys.exit(f"error: {exc}")
