from __future__ import annotations

import argparse
import asyncio
from datetime import date
import json
import os
from pathlib import Path
import sys
from typing import Sequence

import httpx

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
from .daily_prediction_log_importer import import_daily_prediction_log 
from .jra_odds_timeline import JraOddsTimelineCollector
from .netkeiba_analysis_collector import NetkeibaAnalysisCollector, NetkeibaResultCollectionOptions 
from .netkeiba_mapping import generate_netkeiba_mapping_csv 
from .netkeiba_service import NetkeibaService 
from .nar_netkeiba_service import NarNetkeibaService 
from .nankankeiba_pattern_service import NankankeibaPatternService 
from .nankan_service import DEFAULT_NANKAN_ODDS_SUMMARY_BET_TYPES
from .normalization import normalize_course, normalize_nar_course 
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
    if args.command == "collect-jra-odds-timeline":
        summary = asyncio.run(collect_jra_odds_timeline(args))
        print(
            f"scheduled={summary.scheduled} saved={summary.saved} "
            f"skipped_existing={summary.skipped_existing} skipped_late={summary.skipped_late} "
            f"failed={summary.failed} live_requests={summary.live_requests}"
        )
        return 1 if summary.failed else 0
    if args.command == "collect-netkeiba-results":
        if args.from_date > args.to_date:
            parser.error("--from-date must be earlier than or equal to --to-date")
        if args.mapping_csv is None and not args.use_db_mapping:
            parser.error("either --mapping-csv or --use-db-mapping is required")
        summary = asyncio.run(collect_netkeiba_results(args))
        print(format_netkeiba_collection_summary(summary))
        return 1 if summary.failed_count else 0
    if args.command == "generate-netkeiba-mapping":
        if args.from_date > args.to_date:
            parser.error("--from-date must be earlier than or equal to --to-date")
        if args.output is None and not args.save_to_db:
            parser.error("either --output or --save-to-db is required")
        summary = generate_netkeiba_mapping(args)
        print(
            "output={output} saved_to_db={saved_to_db} total={total} mapped={mapped} unmapped={unmapped}".format(
                output=summary.output or "-",
                saved_to_db=summary.saved_to_db,
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
    if args.command == "fetch-nankankeiba-pattern":
        asyncio.run(fetch_nankankeiba_pattern(args))
        return 0
    if args.command == "call-local-api": 
        asyncio.run(call_local_api(args)) 
        return 0 
    if args.command == "fetch-nankan-prediction-bundle":
        asyncio.run(fetch_nankan_prediction_bundle(args))
        return 0
    if args.command == "import-daily-prediction-log": 
        summary = import_daily_prediction_log(AnalysisSQLiteStore(args.db), args.path) 
        print(
            "source_path={source_path} log_date={log_date} venue={venue} imported_entries={imported_entries} "
            "resolved_race_ids={resolved_race_ids}".format(
                source_path=summary.source_path,
                log_date=summary.log_date or "-",
                venue=summary.venue or "-",
                imported_entries=summary.imported_entries,
                resolved_race_ids=summary.resolved_race_ids,
            )
        )
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
    analysis.add_argument("--db", type=Path, default=Path(os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/db/analysis.sqlite")))
    analysis.add_argument("--include-card", action="store_true")
    analysis.add_argument("--include-odds", action="store_true")
    analysis.add_argument("--include-results", action="store_true")
    analysis.add_argument("--bet-types", default=",".join(SUPPORTED_JRA_BET_TYPES))
    analysis.add_argument("--odds-timing", default="final_or_near_final")
    analysis.add_argument("--retries", type=int, default=0)
    analysis.add_argument("--min-interval-seconds", type=float, default=0.0)
    analysis.add_argument("--max-live-requests", type=int)
    analysis.add_argument("--skip-existing", action="store_true")

    timeline = subparsers.add_parser(
        "collect-jra-odds-timeline",
        help="Save JRA odds at fixed minutes before each race without polling every race.",
    )
    timeline.add_argument("--date", dest="target_date", type=date.fromisoformat, required=True)
    timeline.add_argument("--courses", default="all", help="'all' or comma-separated JRA course names.")
    timeline.add_argument("--db", type=Path, default=Path(os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/db/analysis.sqlite")))
    timeline.add_argument("--bet-types", default="win,wide")
    timeline.add_argument("--offset-minutes", default="30,10,2")
    timeline.add_argument(
        "--bet-type-offsets",
        help="Optional per-bet-type offsets, for example 'win=30,10,2;wide=30,10,2;trio=10,2'.",
    )
    timeline.add_argument("--poll-seconds", type=float, default=20.0)
    timeline.add_argument("--min-interval-seconds", type=float, default=1.0)
    timeline.add_argument("--max-lateness-seconds", type=float, default=90.0)
    timeline.add_argument("--max-live-requests", type=int)
    timeline.add_argument("--dry-run", action="store_true")
    timeline.add_argument(
        "--refresh-existing",
        action="store_true",
        help="Fetch and append a new generation even when the timing label already exists.",
    )

    netkeiba_results = subparsers.add_parser(
        "collect-netkeiba-results",
        help="Collect netkeiba race_result pages into analysis SQLite using a race-id mapping CSV.",
    )
    netkeiba_results.add_argument("--from-date", type=date.fromisoformat, required=True)
    netkeiba_results.add_argument("--to-date", type=date.fromisoformat, required=True)
    netkeiba_results.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/db/analysis.sqlite")),
    )
    netkeiba_results.add_argument("--mapping-csv", type=Path)
    netkeiba_results.add_argument("--use-db-mapping", action="store_true")
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
        default=Path(os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/db/analysis.sqlite")),
    )
    netkeiba_mapping.add_argument("--output", type=Path)
    netkeiba_mapping.add_argument("--meeting-calendar-csv", type=Path)
    netkeiba_mapping.add_argument("--save-to-db", action="store_true")
    netkeiba_mapping.add_argument("--limit", type=int)

    backfill = subparsers.add_parser(
        "backfill-analysis-runners",
        help="Backfill missing runners in analysis SQLite from existing races.",
    )
    backfill.add_argument("--db", type=Path, default=Path(os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/db/analysis.sqlite")))
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
    verify.add_argument("--db", type=Path, default=Path(os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/db/analysis.sqlite")))
    verify.add_argument("--from-date", type=date.fromisoformat, required=True)
    verify.add_argument("--to-date", type=date.fromisoformat, required=True)
    verify.add_argument("--sample-size", type=int, default=10)

    nankankeiba_pattern = subparsers.add_parser(
        "fetch-nankankeiba-pattern",
        help="Fetch and structure nankankeiba win pattern analysis.",
    )
    nankankeiba_pattern.add_argument("--date", dest="target_date", type=date.fromisoformat, required=True)
    nankankeiba_pattern.add_argument("--course", required=True)
    nankankeiba_pattern.add_argument("--meeting", dest="meeting_no", type=int, required=True)
    nankankeiba_pattern.add_argument("--day", dest="meeting_day", type=int, required=True)
    nankankeiba_pattern.add_argument("--race", dest="race_no", type=int, required=True)
    nankankeiba_pattern.add_argument("--periods", default="lifetime")
    nankankeiba_pattern.add_argument("--categories")
    nankankeiba_pattern.add_argument("--output", type=Path)

    call_local_api_parser = subparsers.add_parser(
        "call-local-api",
        help="Call the local HTTP API and print pretty JSON.",
    )
    call_local_api_parser.add_argument("path", help="Request path. Example: /nankan/meetings/2026-07-08/kawasaki/races/8/card")
    call_local_api_parser.add_argument(
        "--base-url",
        default=os.environ.get("JRA_SRB_LOCAL_API_BASE_URL", "http://127.0.0.1:8000"),
        help="Base URL for the local API.",
    )
    call_local_api_parser.add_argument( 
        "--query", 
        action="append", 
        default=[], 
        help="Query parameter in key=value format. Repeatable.", 
    ) 
    call_local_api_parser.add_argument("--output", type=Path) 

    prediction_bundle_parser = subparsers.add_parser(
        "fetch-nankan-prediction-bundle",
        help="Fetch the bundled nankan prediction materials from the local API.",
    )
    prediction_bundle_parser.add_argument("--date", dest="target_date", type=date.fromisoformat, required=True)
    prediction_bundle_parser.add_argument("--course", required=True)
    prediction_bundle_parser.add_argument("--race", dest="race_no", type=int, required=True)
    prediction_bundle_parser.add_argument("--meeting", dest="meeting_no", type=int, required=True)
    prediction_bundle_parser.add_argument("--day", dest="meeting_day", type=int, required=True)
    prediction_bundle_parser.add_argument("--bet-types", default=",".join(DEFAULT_NANKAN_ODDS_SUMMARY_BET_TYPES))
    prediction_bundle_parser.add_argument(
        "--base-url",
        default=os.environ.get("JRA_SRB_LOCAL_API_BASE_URL", "http://127.0.0.1:8000"),
        help="Base URL for the local API.",
    )
    prediction_bundle_parser.add_argument("--refresh", action="store_true")
    prediction_bundle_parser.add_argument("--output", type=Path)

    import_daily_prediction_log_parser = subparsers.add_parser( 
        "import-daily-prediction-log", 
        help="Import a daily prediction markdown log into analysis SQLite.", 
    )
    import_daily_prediction_log_parser.add_argument("path", type=Path)
    import_daily_prediction_log_parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/db/analysis.sqlite")),
    )
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


async def collect_analysis(
    args: argparse.Namespace,
    service: JraService | None = None,
    nar_service: NarNetkeibaService | None = None,
) -> str:
    courses = parse_course_list(args.courses)
    bet_types = [item.strip() for item in args.bet_types.split(",") if item.strip()]
    store = AnalysisSQLiteStore(args.db)
    collector = AnalysisCollector(
        service=service or JraService(),
        store=store,
        nar_service=nar_service or NarNetkeibaService(),
    )
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
            min_interval_seconds=getattr(args, "min_interval_seconds", 0.0),
            max_live_requests=getattr(args, "max_live_requests", None),
            skip_existing=getattr(args, "skip_existing", False),
        )
    )


async def collect_jra_odds_timeline(args: argparse.Namespace):
    courses = set() if args.courses.strip().lower() in AnalysisCollector.AUTO_COURSE_TOKENS else set(parse_course_list(args.courses))
    bet_types = [item.strip() for item in args.bet_types.split(",") if item.strip()]
    bet_type_offsets = parse_jra_bet_type_offsets(args.bet_type_offsets)
    if bet_type_offsets is not None:
        bet_types = list(bet_type_offsets)
    unsupported = sorted(set(bet_types) - set(SUPPORTED_JRA_BET_TYPES))
    if unsupported:
        raise ValueError(f"unsupported JRA bet types: {','.join(unsupported)}")
    offsets = sorted(
        {int(item.strip()) for item in args.offset_minutes.split(",") if item.strip()},
        reverse=True,
    )
    if not offsets or any(offset < 0 for offset in offsets):
        raise ValueError("--offset-minutes must contain non-negative integers")
    collector = JraOddsTimelineCollector(JraService(), AnalysisSQLiteStore(args.db))
    return await collector.collect(
        target_date=args.target_date,
        courses=courses,
        offsets=offsets,
        bet_types=bet_types,
        bet_type_offsets=bet_type_offsets,
        poll_seconds=args.poll_seconds,
        min_interval_seconds=args.min_interval_seconds,
        max_lateness_seconds=args.max_lateness_seconds,
        max_live_requests=args.max_live_requests,
        dry_run=args.dry_run,
        refresh_existing=args.refresh_existing,
    )


async def collect_netkeiba_results(args: argparse.Namespace, service: NetkeibaService | None = None):
    store = AnalysisSQLiteStore(args.db)
    collector = NetkeibaAnalysisCollector(service=service or NetkeibaService(), store=store)
    return await collector.collect_results(
        NetkeibaResultCollectionOptions(
            from_date=args.from_date,
            to_date=args.to_date,
            mapping_csv=args.mapping_csv,
            use_db_mapping=args.use_db_mapping,
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
        save_to_db=args.save_to_db,
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


async def fetch_nankankeiba_pattern(args: argparse.Namespace, service: NankankeibaPatternService | None = None) -> str:
    svc = service or NankankeibaPatternService()
    bundle = await svc.get_pattern_bundle(
        args.target_date,
        args.course,
        args.meeting_no,
        args.meeting_day,
        args.race_no,
        periods=_parse_optional_csv(args.periods) or ["lifetime"],
        categories=_parse_optional_csv(args.categories),
    )
    output = bundle.model_dump_json(indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output + "\n", encoding="utf-8")
    else:
        print(output)
    return output


async def call_local_api(args: argparse.Namespace, client: httpx.AsyncClient | None = None) -> str: 
    params = _parse_key_value_args(args.query)
    url = f"{args.base_url.rstrip('/')}/{args.path.lstrip('/')}"
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=30.0)
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        output = json.dumps(response.json(), ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output + "\n", encoding="utf-8")
        else:
            print(output)
        return output
    finally:
        if owns_client: 
            await client.aclose() 


async def fetch_nankan_prediction_bundle(args: argparse.Namespace, client: httpx.AsyncClient | None = None) -> str:
    query = [
        f"meeting_no={args.meeting_no}",
        f"meeting_day={args.meeting_day}",
        f"bet_types={args.bet_types}",
    ]
    if args.refresh:
        query.append("refresh=true")
    call_args = argparse.Namespace(
        base_url=args.base_url,
        path=f"/nankan/meetings/{args.target_date.isoformat()}/{args.course}/races/{args.race_no}/prediction-bundle",
        query=query,
        output=args.output,
    )
    return await call_local_api(call_args, client=client)


def build_storage(kind: str, path: Path) -> ResultStorage: 
    if kind == "sqlite":
        return SQLiteRaceResultStorage(path)
    return JsonlRaceResultStorage(path)


def parse_course_list(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if len(items) == 1 and items[0].lower() in AnalysisCollector.AUTO_COURSE_TOKENS:
        return [items[0].lower()]
    return [_normalize_analysis_course(item) for item in items]


def parse_jra_bet_type_offsets(value: str | None) -> dict[str, list[int]] | None:
    if value is None:
        return None
    parsed: dict[str, list[int]] = {}
    for group in value.split(";"):
        bet_type, separator, raw_offsets = group.strip().partition("=")
        if not separator or not bet_type or not raw_offsets or bet_type in parsed:
            raise ValueError("--bet-type-offsets must use unique 'bet_type=minutes,minutes' groups")
        if bet_type not in SUPPORTED_JRA_BET_TYPES:
            raise ValueError(f"unsupported JRA bet type: {bet_type}")
        try:
            offsets = sorted(
                {int(item.strip()) for item in raw_offsets.split(",") if item.strip()},
                reverse=True,
            )
        except ValueError as exc:
            raise ValueError("--bet-type-offsets minutes must be integers") from exc
        if not offsets or any(offset < 0 for offset in offsets):
            raise ValueError("--bet-type-offsets minutes must be non-negative integers")
        parsed[bet_type] = offsets
    if not parsed:
        raise ValueError("--bet-type-offsets must not be empty")
    return parsed


def _normalize_analysis_course(value: str) -> str:
    try:
        return str(normalize_course(value))
    except Exception:
        return normalize_nar_course(value)


def _parse_optional_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_key_value_args(values: Sequence[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"query parameter must be key=value: {value}")
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"query parameter key is empty: {value}")
        params[key] = raw
    return params


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
