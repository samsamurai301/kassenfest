import argparse
import asyncio
import sys

from kassenfest.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="kassenfest")
    sub = parser.add_subparsers(dest="command", required=True)
    smoke = sub.add_parser("smoke", help="check Muse Spark + SAM 3.1 end to end")
    smoke.add_argument("--mode", choices=["live", "record", "replay"], help="override LLM_MODE")
    synth = sub.add_parser("synth", help="generate a synthetic document set with ground truth")
    synth.add_argument("--set", required=True, choices=["demo", "dev", "test"], dest="set_name")
    synth.add_argument("--out", help="output directory (default data/synthetic/<set>)")
    args = parser.parse_args()

    if args.command == "synth":
        from kassenfest.synth import generate

        generate.main(args.set_name, args.out)
        return

    if args.command == "smoke":
        from kassenfest import smoke as smoke_mod
        from kassenfest.llm import CacheMiss

        settings = Settings(llm_mode=args.mode) if args.mode else Settings()
        try:
            sys.exit(asyncio.run(smoke_mod.run(settings)))
        except (CacheMiss, RuntimeError) as exc:
            sys.exit(f"error: {exc}")
