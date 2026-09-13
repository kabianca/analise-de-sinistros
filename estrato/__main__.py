"""Command line entry point: python -m estrato <command>.

Each command is a thin wrapper around one module so that the same functions
are what the tests call. Modules are imported inside the handlers because
matplotlib is slow to import and `generate` should not pay for it.
"""

import argparse
import sys

from estrato import config


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="estrato", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="write the synthetic source extracts into data/")
    gen.add_argument("--seed", type=int, default=config.DEFAULT_SEED)
    gen.add_argument("--scale", type=int, default=config.DEFAULT_SCALE, help="insured persons")
    gen.add_argument("--start", default=config.DEFAULT_START, help="first extract month, YYYY-MM")
    gen.add_argument("--end", default=config.DEFAULT_END, help="last extract month, YYYY-MM")

    sub.add_parser("load", help="COPY every extract in data/ into the raw schema")
    rep = sub.add_parser("replay", help="build every extract not yet seen, in order, then test")
    rep.add_argument("--rebuild", action="store_true", help="drop what dbt built and start over")
    rep.add_argument("--no-test", action="store_true", help="skip `dbt test` at the end")
    stp = sub.add_parser("step", help="build one extract date again, e.g. the latest")
    stp.add_argument("as_of", help="extract date, YYYY-MM-DD")
    sub.add_parser("fingerprint", help="row count and content hash of every mart")
    sub.add_parser("charts", help="draw the README figures into docs/img")

    args = parser.parse_args(argv)

    if args.command == "generate":
        from estrato import generate

        generate.write_source(
            config.RAW_DIR,
            config.TRUTH_DIR,
            seed=args.seed,
            scale=args.scale,
            start=args.start,
            end=args.end,
        )
    elif args.command == "load":
        from estrato import load

        load.load_raw(config.RAW_DIR, config.Postgres())
    elif args.command == "replay":
        from estrato import replay

        return replay.replay(config.Postgres(), from_scratch=args.rebuild, test=not args.no_test)
    elif args.command == "step":
        from estrato import replay

        replay.step(config.Postgres(), args.as_of)
    elif args.command == "fingerprint":
        from estrato import fingerprint

        fingerprint.print_fingerprint(config.Postgres())
    elif args.command == "charts":
        from estrato import charts

        charts.draw_all(config.Postgres(), config.IMG_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
