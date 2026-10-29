import argparse
import asyncio
import sys

from kassenfest.config import REPO_ROOT, Settings


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
    ingest = sub.add_parser("ingest", help="run files or folders through the pipeline")
    ingest.add_argument("paths", nargs="+", help="images, PDFs or folders of them")
    ingest.add_argument("--label", help="name for this batch")
    ingest.add_argument("--mode", choices=["live", "record", "replay"], help="override LLM_MODE")
    evidence = sub.add_parser("evidence", help="tighten evidence boxes of stored documents")
    evidence.add_argument("--mode", choices=["live", "record", "replay"], help="override LLM_MODE")
    audit = sub.add_parser("audit", help="let the auditor agent attack the clean bills")
    audit.add_argument("claims", nargs="*", help="claim ids (default: every clean bill due)")
    audit.add_argument("--mode", choices=["live", "record", "replay"], help="override LLM_MODE")
    eval_boxes = sub.add_parser("eval-boxes", help="score evidence boxes against ground truth")
    eval_boxes.add_argument(
        "--truth", default=str(REPO_ROOT / "data/synthetic/demo/truth"), help="truth folder"
    )
    synth = sub.add_parser("synth", help="generate a synthetic document set with ground truth")
    synth.add_argument("--set", required=True, choices=["demo", "dev", "test"], dest="set_name")
    synth.add_argument("--out", help="output directory (default data/synthetic/<set>)")
    args = parser.parse_args()

    if args.command == "eval-boxes":  # no model calls
        from pathlib import Path

        from kassenfest.db import create_db
        from kassenfest.eval import boxes

        engine = create_db(Settings().db_path)
        print(boxes.report(boxes.score(engine, Path(args.truth))))
        return

    if args.command == "synth":  # no model calls, no settings
        from kassenfest.synth import generate

        generate.main(args.set_name, args.out)
        return

    from kassenfest.llm import CacheMiss

    settings = Settings(llm_mode=args.mode) if args.mode else Settings()
    try:
        if args.command == "smoke":
            from kassenfest import smoke as smoke_mod

            sys.exit(asyncio.run(smoke_mod.run(settings)))
        if args.command == "spike":
            from kassenfest import spikes

            sys.exit(asyncio.run(spikes.run(settings, args.which, args.muster12, args.visit_logs)))
        if args.command == "ingest":
            from kassenfest import ingest as ingest_mod

            sys.exit(asyncio.run(ingest_mod.run(settings, args.paths, args.label)))
        if args.command == "evidence":
            from kassenfest import ingest as ingest_mod

            sys.exit(asyncio.run(ingest_mod.evidence(settings)))
        if args.command == "audit":
            from kassenfest import ingest as ingest_mod

            sys.exit(asyncio.run(ingest_mod.audit(settings, args.claims)))
    except (CacheMiss, RuntimeError) as exc:
        sys.exit(f"error: {exc}")
