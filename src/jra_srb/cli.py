from __future__ import annotations

import argparse
import asyncio
from datetime import date
import os
from pathlib import Path
from typing import Sequence

from .analysis_collector import AnalysisCollectionOptions, AnalysisCollector
from .analysis_store import AnalysisSQLiteStore
from .batch import JsonlRaceResultStorage, PastResultCollector, ResultStorage, SQLiteRaceResultStorage
from .normalization import normalize_course
from .service import JraService, SUPPORTED_JRA_BET_TYPES


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "collect-results":
        if args.from_date > args.to_date:
            parser.error("--from-date must be earlier than or equal to --to-date")
        asyncio.run(collect_results(args))
        return 0
    if args.command == "collect-analysis":
        if args.from_date > args.to_date:
            parser.error("--from-date must be earlier than or equal to --to-date")
        asyncio.run(collect_analysis(args))
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

    analysis = subparsers.add_parser("collect-analysis", help="Collect analysis data into a local SQLite database.")
    analysis.add_argument("--from-date", type=date.fromisoformat, required=True)
    analysis.add_argument("--to-date", type=date.fromisoformat, required=True)
    analysis.add_argument("--courses", required=True, help="Comma-separated course names or codes. Example: nakayama,hanshin")
    analysis.add_argument("--db", type=Path, default=Path(os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/analysis.sqlite")))
    analysis.add_argument("--include-card", action="store_true")
    analysis.add_argument("--include-odds", action="store_true")
    analysis.add_argument("--include-results", action="store_true")
    analysis.add_argument("--bet-types", default=",".join(SUPPORTED_JRA_BET_TYPES))
    analysis.add_argument("--odds-timing", default="final_or_near_final")
    analysis.add_argument("--retries", type=int, default=0)
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


async def collect_analysis(args: argparse.Namespace, service: JraService | None = None) -> str:
    courses = [str(normalize_course(item)) for item in args.courses.split(",") if item.strip()]
    bet_types = [item.strip() for item in args.bet_types.split(",") if item.strip()]
    store = AnalysisSQLiteStore(args.db)
    collector = AnalysisCollector(service=service or JraService(), store=store)
    return await collector.collect(
        AnalysisCollectionOptions(
            from_date=args.from_date,
            to_date=args.to_date,
            courses=courses,
            include_card=args.include_card,
            include_odds=args.include_odds,
            include_results=args.include_results,
            odds_timing=args.odds_timing,
            bet_types=bet_types,
            retries=args.retries,
        )
    )


def build_storage(kind: str, path: Path) -> ResultStorage:
    if kind == "sqlite":
        return SQLiteRaceResultStorage(path)
    return JsonlRaceResultStorage(path)


if __name__ == "__main__":
    raise SystemExit(main())
