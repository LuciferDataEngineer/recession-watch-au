"""Command line entry point used by Make, Kestra and CI."""

from __future__ import annotations

import argparse
from pathlib import Path

from recession_watch.ingest import download
from recession_watch.pipeline import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Australian recession watch pipeline")
    parser.add_argument("command", choices=["snapshot", "run"])
    parser.add_argument("--from-snapshot", action="store_true", help="Use the committed parquet snapshot")
    parser.add_argument("--max-em-iter", type=int, default=12)
    parser.add_argument("--backtest-iter", type=int, default=8)
    parser.add_argument("--snapshot-dir", type=Path, default=None)
    args = parser.parse_args()
    if args.command == "snapshot" or not args.from_snapshot and args.command == "run" and args.snapshot_dir is None and not (Path("data/snapshot/manifest.json")).exists():
        print(download())
    if args.command == "run":
        path = run(args.snapshot_dir, max_em_iter=args.max_em_iter, backtest_iter=args.backtest_iter)
        print(path)


if __name__ == "__main__":
    main()
