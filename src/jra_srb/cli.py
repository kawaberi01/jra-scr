from __future__ import annotations

import argparse
import asyncio
from datetime import date
from pathlib import Path
from typing import Sequence

from .batch import JsonlRaceResultStorage, PastResultCollector, ResultStorage, SQLiteRaceResultStorage
from .normalization import normalize_course
from .service import JraService


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "collect-results":
        if args.from_date > args.to_date:
            parser.error("--from-date must be earlier than or equal to --to-date")
        asyncio.run(collect_results(args))
        return 0
    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jra-srb")
    subparsers = parser.add_subparsers(dest="command")

    collect = subparsers.add_parser("collect-results", help="Collect past race results into a storage backend.")
    collect.add_argument("--from-date", type=date.fromisoformat, required=True)
    collect.add_argument("--to-date", type=date.fromisoformat, required=True)
    collect.add_argument("--courses", required=True, help="Comma-separated course names or codes. Example: nakayama,hanshin")
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument("--retries", type=int, default=0)
    collect.add_argument("--storage", choices=("jsonl", "sqlite"), default="jsonl")
    return parser


async def collect_results(args: argparse.Namespace, service: JraService | None = None) -> None:
    storage = build_storage(args.storage, args.output)
    courses = [str(normalize_course(item)) for item in args.courses.split(",") if item.strip()]
    collector = PastResultCollector(
        service=service or JraService(),
        storage=storage,
        retries=args.retries,
    )
    await collector.collect(args.from_date, args.to_date, courses)


def build_storage(kind: str, path: Path) -> ResultStorage:
    if kind == "sqlite":
        return SQLiteRaceResultStorage(path)
    return JsonlRaceResultStorage(path)


if __name__ == "__main__":
    raise SystemExit(main())
