from __future__ import annotations

import argparse
import asyncio
from datetime import date
import os
from pathlib import Path
import sys
from typing import Sequence

from .analysis_collector import AnalysisCollectionOptions, AnalysisCollector
from .analysis_maintenance import (
    AnalysisJoinVerifier,
    AnalysisRunnerBackfiller,
    RunnerBackfillOptions,
    format_backfill_summary,
    format_join_verification,
)
from .analysis_store import AnalysisSQLiteStore
from .batch import JsonlRaceResultStorage, PastResultCollector, ResultStorage, SQLiteRaceResultStorage
from .netkeiba_analysis_collector import NetkeibaAnalysisCollector, NetkeibaResultCollectionOptions
from .netkeiba_mapping import generate_netkeiba_mapping_csv
from .netkeiba_service import NetkeibaService
from .normalization import normalize_course
from .service import JraService, SUPPORTED_JRA_BET_TYPES


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdout()
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
    if args.command == "collect-netkeiba-results":
        if args.from_date > args.to_date:
            parser.error("--from-date must be earlier than or equal to --to-date")
        summary = asyncio.run(collect_netkeiba_results(args))
        print(format_netkeiba_collection_summary(summary))
        return 1 if summary.failed_count else 0
    if args.command == "generate-netkeiba-mapping":
        if args.from_date > args.to_date:
            parser.error("--from-date must be earlier than or equal to --to-date")
        summary = generate_netkeiba_mapping(args)
        print(
            "output={output} total={total} mapped={mapped} unmapped={unmapped}".format(
                output=summary.output,
                total=summary.total_count,
                mapped=summary.mapped_count,
                unmapped=summary.unmapped_count,
            )
        )
        return 0
    if args.command == "backfill-analysis-runners":
        if args.from_date > args.to_date:
            parser.error("--from-date must be earlier than or equal to --to-date")
        summary = asyncio.run(backfill_analysis_runners(args))
        print(format_backfill_summary(summary))
        return 1 if summary.failed_count else 0
    if args.command == "verify-analysis-joins":
        if args.from_date > args.to_date:
            parser.error("--from-date must be earlier than or equal to --to-date")
        result = verify_analysis_joins(args)
        print(format_join_verification(result))
        return 0 if result.ok else 1
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

    netkeiba_results = subparsers.add_parser(
        "collect-netkeiba-results",
        help="Collect netkeiba race_result pages into analysis SQLite using a race-id mapping CSV.",
    )
    netkeiba_results.add_argument("--from-date", type=date.fromisoformat, required=True)
    netkeiba_results.add_argument("--to-date", type=date.fromisoformat, required=True)
    netkeiba_results.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/analysis.sqlite")),
    )
    netkeiba_results.add_argument("--mapping-csv", type=Path, required=True)
    netkeiba_results.add_argument("--max-live-requests", type=int, default=30)
    netkeiba_results.add_argument("--min-interval-seconds", type=float, default=10.0)
    netkeiba_results.add_argument("--refresh", action="store_true")
    netkeiba_results.add_argument("--retries", type=int, default=0)
    netkeiba_results.add_argument("--dry-run", action="store_true")
    netkeiba_results.add_argument("--limit", type=int)

    netkeiba_mapping = subparsers.add_parser(
        "generate-netkeiba-mapping",
        help="Generate a netkeiba race-id mapping CSV from analysis SQLite races.",
    )
    netkeiba_mapping.add_argument("--from-date", type=date.fromisoformat, required=True)
    netkeiba_mapping.add_argument("--to-date", type=date.fromisoformat, required=True)
    netkeiba_mapping.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/analysis.sqlite")),
    )
    netkeiba_mapping.add_argument("--output", type=Path, required=True)
    netkeiba_mapping.add_argument("--meeting-calendar-csv", type=Path)
    netkeiba_mapping.add_argument("--limit", type=int)

    backfill = subparsers.add_parser(
        "backfill-analysis-runners",
        help="Backfill missing runners in analysis SQLite from existing races.",
    )
    backfill.add_argument("--db", type=Path, default=Path(os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/analysis.sqlite")))
    backfill.add_argument("--from-date", type=date.fromisoformat, required=True)
    backfill.add_argument("--to-date", type=date.fromisoformat, required=True)
    backfill.add_argument("--courses", required=True, help="'all' or comma-separated course names or codes.")
    backfill.add_argument("--only-missing", action="store_true")
    backfill.add_argument("--retries", type=int, default=0)
    backfill.add_argument("--min-interval-seconds", type=float, default=0.0)
    backfill.add_argument("--limit", type=int)
    backfill.add_argument("--dry-run", action="store_true")

    verify = subparsers.add_parser(
        "verify-analysis-joins",
        help="Verify analysis SQLite card/result join health.",
    )
    verify.add_argument("--db", type=Path, default=Path(os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/analysis.sqlite")))
    verify.add_argument("--from-date", type=date.fromisoformat, required=True)
    verify.add_argument("--to-date", type=date.fromisoformat, required=True)
    verify.add_argument("--sample-size", type=int, default=10)
    return parser


async def collect_results(args: argparse.Namespace, service: JraService | None = None) -> None:
    storage = build_storage(args.storage, args.output)
    courses = parse_course_list(args.courses)
    collector = PastResultCollector(
        service=service or JraService(),
        storage=storage,
        retries=args.retries,
    )
    await collector.collect(args.from_date, args.to_date, courses)


async def collect_analysis(args: argparse.Namespace, service: JraService | None = None) -> str:
    courses = parse_course_list(args.courses)
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


async def collect_netkeiba_results(args: argparse.Namespace, service: NetkeibaService | None = None):
    store = AnalysisSQLiteStore(args.db)
    collector = NetkeibaAnalysisCollector(service=service or NetkeibaService(), store=store)
    return await collector.collect_results(
        NetkeibaResultCollectionOptions(
            from_date=args.from_date,
            to_date=args.to_date,
            mapping_csv=args.mapping_csv,
            max_live_requests=args.max_live_requests,
            min_interval_seconds=args.min_interval_seconds,
            refresh=args.refresh,
            retries=args.retries,
            dry_run=args.dry_run,
            limit=args.limit,
        )
    )


def generate_netkeiba_mapping(args: argparse.Namespace):
    store = AnalysisSQLiteStore(args.db)
    return generate_netkeiba_mapping_csv(
        store=store,
        from_date=args.from_date,
        to_date=args.to_date,
        output=args.output,
        meeting_calendar_csv=args.meeting_calendar_csv,
        limit=args.limit,
    )


def format_netkeiba_collection_summary(summary) -> str:
    return (
        "run_id={run_id} dry_run={dry_run} targets={targets} saved={saved} "
        "unsaved={unsaved} planned={planned} unmappable={unmappable} "
        "collected={collected} skipped={skipped} failed={failed} limit_reached={limit}"
    ).format(
        run_id=summary.run_id or "-",
        dry_run=summary.dry_run,
        targets=summary.target_count,
        saved=summary.saved_count,
        unsaved=summary.unsaved_count,
        planned=summary.planned_request_count,
        unmappable=summary.unmappable_count,
        collected=summary.collected_count,
        skipped=summary.skipped_count,
        failed=summary.failed_count,
        limit=summary.live_request_limit_reached,
    )


async def backfill_analysis_runners(args: argparse.Namespace, service: JraService | None = None):
    courses = parse_course_list(args.courses)
    store = AnalysisSQLiteStore(args.db)
    backfiller = AnalysisRunnerBackfiller(service=service or JraService(), store=store)
    return await backfiller.backfill(
        RunnerBackfillOptions(
            from_date=args.from_date,
            to_date=args.to_date,
            courses=courses,
            only_missing=args.only_missing,
            retries=args.retries,
            min_interval_seconds=args.min_interval_seconds,
            limit=args.limit,
            dry_run=args.dry_run,
        )
    )


def verify_analysis_joins(args: argparse.Namespace):
    store = AnalysisSQLiteStore(args.db)
    verifier = AnalysisJoinVerifier(store)
    return verifier.verify(args.from_date, args.to_date, args.sample_size)


def build_storage(kind: str, path: Path) -> ResultStorage:
    if kind == "sqlite":
        return SQLiteRaceResultStorage(path)
    return JsonlRaceResultStorage(path)


def parse_course_list(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if len(items) == 1 and items[0].lower() in AnalysisCollector.AUTO_COURSE_TOKENS:
        return [items[0].lower()]
    return [str(normalize_course(item)) for item in items]


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
