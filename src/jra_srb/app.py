from __future__ import annotations

from datetime import date
import logging
import os
import time
from pathlib import Path as FilePath
from typing import Annotated
from uuid import uuid4

from fastapi import BackgroundTasks, Body, Depends, FastAPI, Path, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi_mcp import FastApiMCP
from pydantic import AwareDatetime

from .analysis_store import AnalysisSQLiteStore
from .batch import JsonlRaceResultStorage, ResultStorage, SQLiteRaceResultStorage
from .cache import SQLiteTTLCache
from .errors import BadRequestError, JraApiError
from .jobs import ResultCollectionJobRegistry
from .models import ( 
    ApiError, 
    ApiErrorResponse, 
    BetRecord, 
    BetRecordCreateRequest,
    BetRecordPage,
    BetRecordSettlement,
    BET_RECORD_RACE_ID_PATTERN,
    BetType,
    CourseCode, 
    EvaluationRecord,
    EvaluationRecordPage,
    EvaluationSummary,
    JraDayRaceScoutResult,
    JraLiveShadowObservationPage,
    JraPredictionBundle,
    NarCalendarPage, 
    NankankeibaPatternBundle, 
    NankanPredictionBundle,
    NankanPredictionSummary,
    NankanCourseCode, 
    NankanLeadingJockeyPage,
    NankanMeetingTrend,
    NankanMeetingTrendContext,
    NankanRaceBestTime, 
    NankanRaceClosingSpeed, 
    NankanRaceStyleProfile, 
    PredictionRecord,
    PredictionRecordPage,
    RaceCard, 
    RaceOdds,
    RaceSearchItem, 
    RaceSearchPage,
    ResultCollectionJobCreated,
    ResultCollectionJobPage,
    ResultCollectionJobRequest,
    ResultCollectionJobSummary,
    ResultStorageKind,
    StoredOddsTimeline,
    StoredPreRaceSnapshot,
    StoredRaceResultPage,
)
from .nankankeiba_pattern_provider import NankankeibaPatternHttpProvider 
from .nankankeiba_pattern_service import NankankeibaPatternCacheTtls, NankankeibaPatternService 
from .nankan_prediction_service import NankanPredictionService
from .jra_prediction_service import JraPredictionService
from .jra_day_race_scout import JraDayRaceScout
from .jra_prediction_engine import build_prediction_record
from .jra_history_model import build_artifact_live_records, load_model_artifact, score_live_records
from .jra_v_theory import build_three_way_consensus, build_v_theory_prediction
from .jra_betting_decision import build_win_betting_decision, is_newcomer_race
from .prediction_trace import (
    build_prediction_trace_logger,
    reset_current_request_trace_id,
    set_current_request_trace_id,
)
from .nar_netkeiba_provider import NarNetkeibaHttpProvider 
from .nar_netkeiba_service import NarNetkeibaService 
from .nankan_provider import NankanHttpProvider 
from .nankan_service import NankanCacheTtls, NankanService, parse_nankan_odds_summary_bet_types
from .netkeiba_provider import NetkeibaHttpProvider
from .netkeiba_service import NetkeibaService
from .normalization import normalize_combination, normalize_race_input, parse_bet_types
from .provider import HttpProvider, ProviderError
from .service import JraService

logger = logging.getLogger(__name__)

RaceIdPath = Annotated[str, Path(pattern=r"^\d{12}$", description="12桁のrace_id")]
NankanRaceIdPath = Annotated[str, Path(pattern=r"^\d{16}$", description="16桁の南関東race_id")]
RaceNoPath = Annotated[int, Path(ge=1, le=12, description="1から12までのレース番号")]
RaceDatePath = Annotated[date, Path(description="開催日。YYYY-MM-DD形式。例: 2026-07-17")]
CourseCodePath = Annotated[CourseCode, Path(description="JRA開催場コード。例: tokyo, nakayama, hanshin")]
DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 500
MCP_OPERATION_IDS = [
    "normalize_race_input",
    "search_jra_races",
    "get_jra_meeting",
    "get_jra_race_card",
    "get_jra_race_odds",
    "get_jra_race_result",
    "get_jra_prediction_bundle",
    "get_jra_odds_summary",
    "compare_jra_prediction_models",
    "get_jra_betting_decision",
]
prediction_trace_logger = build_prediction_trace_logger(os.environ.get("JRA_SRB_PREDICTION_TRACE_PATH"))

app = FastAPI(
    title="JRA レース情報 API",
    version="0.1.0",
    description=(
        "JRA の開催一覧、出馬表、オッズ、結果・払戻を取得する API です。\n\n"
        "Swagger UI から各 endpoint を直接試せます。"
        " `meetings` は開催日と開催地ベース、`races` は race_id ベースの API です。"
        " `/mcp` は MCP HTTP 入口です。"
    ),
    openapi_tags=[
        {"name": "health", "description": "ヘルスチェック用 endpoint"},
        {"name": "races", "description": "race_id ベースまたは fixture ベースの API"},
        {"name": "meetings", "description": "開催日・開催地・レース番号ベースの API"},
        {"name": "jra-analysis", "description": "JRA予想向け当日材料 API"},
        {"name": "nankan", "description": "南関東4競馬場公式サイトの API"},
        {"name": "nankankeiba", "description": "南関東4競馬場サイト由来の分析 API"},
        {"name": "search", "description": "race_id を探すための検索 API"},
        {"name": "jobs", "description": "長時間処理を非同期に実行する job API"},
        {"name": "mcp", "description": "FastAPI API を公開する MCP HTTP 入口"},
    ],
)


def _default_analysis_db_path() -> str:
    return os.environ.get("JRA_SRB_ANALYSIS_DB_PATH", "data/db/analysis.sqlite")


def _default_history_model_path() -> FilePath:
    return FilePath(os.environ.get("JRA_SRB_HISTORY_MODEL_PATH", "data/models/jra_history_recent_form_v2/model.json"))


def build_service() -> JraService:
    cache_path = os.environ.get("JRA_SRB_CACHE_PATH")
    provider = HttpProvider(
        max_concurrency=_env_int("JRA_SRB_UPSTREAM_MAX_CONCURRENCY", default=5, minimum=1),
        min_interval_seconds=_env_float("JRA_SRB_UPSTREAM_MIN_INTERVAL_SECONDS", default=0.0, minimum=0.0),
    )
    if cache_path:
        return JraService(provider=provider, cache=SQLiteTTLCache(cache_path))
    return JraService(provider=provider)


def build_netkeiba_service() -> NetkeibaService:
    cache_path = os.environ.get("JRA_SRB_CACHE_PATH")
    provider = NetkeibaHttpProvider(
        min_interval_seconds=_env_float("JRA_SRB_NETKEIBA_MIN_INTERVAL_SECONDS", default=1.0, minimum=0.0),
    )
    if cache_path:
        return NetkeibaService(provider=provider, cache=SQLiteTTLCache(cache_path))
    return NetkeibaService(provider=provider)


def build_nar_netkeiba_service() -> NarNetkeibaService:
    cache_path = os.environ.get("JRA_SRB_CACHE_PATH")
    provider = NarNetkeibaHttpProvider(
        min_interval_seconds=_env_float("JRA_SRB_NAR_NETKEIBA_MIN_INTERVAL_SECONDS", default=1.0, minimum=0.0),
    )
    if cache_path:
        return NarNetkeibaService(provider=provider, cache=SQLiteTTLCache(cache_path))
    return NarNetkeibaService(provider=provider)


def build_nankan_service() -> NankanService:
    cache_path = os.environ.get("JRA_SRB_CACHE_PATH")
    ttl_config = NankanCacheTtls(
        odds=_env_int("JRA_SRB_NANKAN_ODDS_TTL_SECONDS", default=60, minimum=1),
        trend=_env_int("JRA_SRB_NANKAN_TREND_TTL_SECONDS", default=300, minimum=1),
        card=_env_int("JRA_SRB_NANKAN_CARD_TTL_SECONDS", default=900, minimum=1),
        leading_jockey=_env_int("JRA_SRB_NANKAN_LEADING_JOCKEY_TTL_SECONDS", default=21600, minimum=1),
        static_material=_env_int("JRA_SRB_NANKAN_STATIC_MATERIAL_TTL_SECONDS", default=86400, minimum=1),
        result=_env_int("JRA_SRB_NANKAN_RESULT_TTL_SECONDS", default=86400, minimum=1),
        meeting=_env_int("JRA_SRB_NANKAN_MEETING_TTL_SECONDS", default=900, minimum=1),
        calendar=_env_int("JRA_SRB_NANKAN_CALENDAR_TTL_SECONDS", default=3600, minimum=1),
    )
    provider = NankanHttpProvider(
        max_concurrency=_env_int("JRA_SRB_NANKAN_MAX_CONCURRENCY", default=3, minimum=1),
        min_interval_seconds=_env_float("JRA_SRB_NANKAN_MIN_INTERVAL_SECONDS", default=1.0, minimum=0.0),
        trace_logger=prediction_trace_logger,
    )
    if cache_path:
        return NankanService(
            provider=provider,
            cache=SQLiteTTLCache(cache_path),
            ttl_config=ttl_config,
            analysis_store=lambda: AnalysisSQLiteStore(_default_analysis_db_path()),
        )
    return NankanService(
        provider=provider,
        ttl_config=ttl_config,
        analysis_store=lambda: AnalysisSQLiteStore(_default_analysis_db_path()),
    )


def build_nankankeiba_pattern_service() -> NankankeibaPatternService: 
    cache_path = os.environ.get("JRA_SRB_CACHE_PATH")
    ttl_config = NankankeibaPatternCacheTtls(
        pattern=_env_int("JRA_SRB_NANKAN_STATIC_MATERIAL_TTL_SECONDS", default=86400, minimum=1),
    )
    provider = NankankeibaPatternHttpProvider(
        min_interval_seconds=_env_float("JRA_SRB_NANKANKEIBA_MIN_INTERVAL_SECONDS", default=1.0, minimum=0.0),
        trace_logger=prediction_trace_logger,
    )
    if cache_path: 
        return NankankeibaPatternService(provider=provider, cache=SQLiteTTLCache(cache_path), ttl_config=ttl_config) 
    return NankankeibaPatternService(provider=provider, ttl_config=ttl_config) 


def build_nankan_prediction_service() -> NankanPredictionService:
    return NankanPredictionService(
        nankan_service=nankan_service,
        pattern_service=nankankeiba_pattern_service,
        trace_logger=prediction_trace_logger,
    )


def build_jra_prediction_service() -> JraPredictionService:
    return JraPredictionService(jra_service=service)


def _env_int(name: str, default: int, minimum: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def _env_float(name: str, default: float, minimum: float) -> float:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    parsed = float(value)
    if parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


service = build_service()
netkeiba_service = build_netkeiba_service()
nar_netkeiba_service = build_nar_netkeiba_service()
nankan_service = build_nankan_service() 
nankankeiba_pattern_service = build_nankankeiba_pattern_service() 
nankan_prediction_service = build_nankan_prediction_service()
jra_prediction_service = build_jra_prediction_service()


@app.middleware("http")
async def write_prediction_trace_http_log(request: Request, call_next):
    if not prediction_trace_logger.enabled:
        return await call_next(request)
    request_trace_id = uuid4().hex
    token = set_current_request_trace_id(request_trace_id)
    started_at = time.perf_counter()
    prediction_trace_logger.write(
        "http_request",
        phase="start",
        request_trace_id=request_trace_id,
        method=request.method,
        path=request.url.path,
        query=request.url.query,
    )
    try:
        response = await call_next(request)
    except Exception as exc:
        prediction_trace_logger.write(
            "http_request",
            phase="error",
            request_trace_id=request_trace_id,
            method=request.method,
            path=request.url.path,
            query=request.url.query,
            elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
            error_type=exc.__class__.__name__,
            error=str(exc),
        )
        reset_current_request_trace_id(token)
        raise
    prediction_trace_logger.write(
        "http_request",
        phase="done",
        request_trace_id=request_trace_id,
        method=request.method,
        path=request.url.path,
        query=request.url.query,
        status_code=response.status_code,
        elapsed_ms=round((time.perf_counter() - started_at) * 1000, 3),
    )
    reset_current_request_trace_id(token)
    return response


def get_service() -> JraService:
    return service


def get_netkeiba_service() -> NetkeibaService:
    return netkeiba_service


def get_nar_netkeiba_service() -> NarNetkeibaService:
    return nar_netkeiba_service


def get_nankan_service() -> NankanService:
    return nankan_service


def get_nankankeiba_pattern_service() -> NankankeibaPatternService: 
    return nankankeiba_pattern_service 


def get_nankan_prediction_service() -> NankanPredictionService:
    return nankan_prediction_service


def get_jra_prediction_service() -> JraPredictionService:
    return jra_prediction_service


def get_jra_day_race_scout() -> JraDayRaceScout:
    return JraDayRaceScout(
        jra_service=service,
        prediction_service=jra_prediction_service,
        store=AnalysisSQLiteStore(_default_analysis_db_path()),
        analysis_db_path=_default_analysis_db_path(),
        history_model_path=_default_history_model_path(),
    )


def get_result_collection_job_registry() -> ResultCollectionJobRegistry:
    return result_collection_jobs


def _default_result_storage_kind() -> ResultStorageKind:
    storage_kind = os.environ.get("JRA_SRB_RESULTS_STORAGE", "jsonl").strip().lower()
    try:
        return ResultStorageKind(storage_kind)
    except ValueError as exc:
        raise BadRequestError(f"unsupported results storage={storage_kind}") from exc


def _default_result_storage_path() -> str:
    return os.environ.get("JRA_SRB_RESULTS_PATH", "data/results.jsonl")


def _default_result_collection_jobs_path() -> str:
    return os.environ.get("JRA_SRB_JOBS_PATH", "data/jobs.sqlite")


result_collection_jobs = ResultCollectionJobRegistry(_default_result_collection_jobs_path())


def build_result_storage(storage_kind: ResultStorageKind, output: str) -> ResultStorage:
    path = FilePath(output)
    if storage_kind == ResultStorageKind.jsonl:
        return JsonlRaceResultStorage(path)
    if storage_kind == ResultStorageKind.sqlite:
        return SQLiteRaceResultStorage(path)
    raise BadRequestError(f"unsupported results storage={storage_kind}")


def get_result_storage() -> ResultStorage:
    return build_result_storage(_default_result_storage_kind(), _default_result_storage_path())


def get_analysis_store() -> AnalysisSQLiteStore:
    return AnalysisSQLiteStore(_default_analysis_db_path())


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    request_id = request.headers.get("x-request-id") or str(uuid4())
    request.state.request_id = request_id
    response = None
    try:
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response
    finally:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        logger.info(
            "api_request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": getattr(response, "status_code", 500),
                "elapsed_ms": elapsed_ms,
                "request_id": request_id,
            },
        )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")


def error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": _request_id(request),
            }
        },
        headers={"x-request-id": _request_id(request)},
    )


@app.exception_handler(JraApiError)
async def handle_jra_api_error(request: Request, exc: JraApiError) -> JSONResponse:
    return error_response(request, exc.status_code, exc.error_code, exc.detail)


@app.exception_handler(LookupError)
async def handle_lookup_error(request: Request, exc: LookupError) -> JSONResponse:
    return error_response(request, 404, "not_found", str(exc))


@app.exception_handler(ProviderError)
async def handle_provider_error(request: Request, exc: ProviderError) -> JSONResponse:
    return error_response(request, exc.status_code, "upstream_error", exc.detail)


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return error_response(request, 422, "validation_error", str(exc))


@app.get("/health", tags=["health"], summary="ヘルスチェック", description="API プロセスが起動しているか確認します。")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get(
    "/health/upstream",
    tags=["health"],
    summary="upstream 到達性チェック",
    description="API プロセスの生存確認とは別に、JRA upstream への軽量な到達性を確認します。",
)
async def health_upstream(svc: JraService = Depends(get_service)) -> dict[str, str]:
    return await svc.check_upstream()


@app.get(
    "/normalize",
    tags=["races"],
    operation_id="normalize_race_input",
    summary="日本語入力を API 用コードへ正規化",
    description=(
        "日本語や自然な表記を、後続のJRAツールで使う開催場コード、レース番号、券種コードへ変換します。"
        " 例: course=中山, race=11R, bet_type=3連単 を"
        " course=nakayama, race_no=11, bet_type=trifecta に変換します。"
    ),
)
async def normalize_input(
    course: str = Query(description="開催場名またはコード。例: 中山, nakayama"),
    race: str = Query(description="レース番号。例: 11R, 第11レース"),
    bet_type: str | None = Query(default=None, description="券種名またはコード。例: 3連単, trifecta"),
    combination: str | None = Query(default=None, description="組み合わせをカンマ区切りで指定します。例: 1,2,3"),
):
    return normalize_race_input(course=course, race=race, bet_type=bet_type, combination=combination)


@app.get(
    "/races",
    tags=["races"],
    summary="race summary 一覧を取得",
    description="fixture ベースの race summary 一覧を取得します。主に既存互換またはテスト用途です。",
)
async def get_races(
    date_: date = Query(
        alias="date",
        description="開催日を YYYY-MM-DD 形式で指定します。例: 2026-03-22",
        examples=["2026-03-22"],
    ),
    course: CourseCode | None = Query(
        default=None,
        description="開催地コードを指定します。例: nakayama, hanshin",
        examples=["nakayama"],
    ),
    svc: JraService = Depends(get_service),
):
    return await svc.get_races(date_, course=str(course) if course else None)


@app.get(
    "/search/races",
    tags=["search"],
    operation_id="search_jra_races",
    summary="開催日からレースを検索",
    description=(
        "開催日、開催場、キーワードからJRAレースを検索します。"
        " race_idやレース番号が不明な場合に、最初にこのツールを使用します。"
    ),
    response_model=RaceSearchPage,
)
async def search_races(
    date_: date = Query(alias="date", description="開催日。例: 2026-03-22"),
    course: CourseCode | None = Query(default=None, description="開催場コード。例: nakayama"),
    keyword: str | None = Query(default=None, description="race_id、レース名、開催場、レース番号の部分一致。"),
    limit: int = Query(default=100, ge=1, le=100, description="返却件数。最大100件。"),
    offset: int = Query(default=0, ge=0, description="先頭からスキップする件数。"),
    svc: JraService = Depends(get_service),
):
    races = await svc.get_races(date_, course=str(course) if course else None)
    normalized_keyword = keyword.casefold() if keyword else None
    items = [
        RaceSearchItem(
            race_id=race.race_id,
            date=date_,
            course=_to_course_code(race.course),
            race_no=_extract_race_no(race.race_number),
            race_name=race.name,
            start_time=race.start_time,
        )
        for race in races
        if _matches_race_keyword(race, normalized_keyword)
    ]
    return RaceSearchPage(
        items=items[offset : offset + limit],
        total=len(items),
        limit=limit,
        offset=offset,
    )


@app.get(
    "/meetings/{date_}/{course}",
    tags=["meetings"],
    operation_id="get_jra_meeting",
    summary="開催一覧を取得",
    description="開催日と開催地を指定して、その開催の 1R から 12R の一覧を取得します。",
)
async def get_meeting(
    date_: RaceDatePath,
    course: CourseCodePath,
    svc: JraService = Depends(get_service),
):
    return await svc.get_meeting(date_, str(course))


@app.get(
    "/races/{race_id}/card",
    tags=["races"],
    summary="race_id で出馬表を取得",
    description="race_id を指定して出馬表を取得します。主に既存の race_id ベース導線です。",
)
async def get_race_card(race_id: RaceIdPath, svc: JraService = Depends(get_service)):
    return await svc.get_race_card(race_id)


@app.get(
    "/meetings/{date_}/{course}/races/{race_no}/card",
    tags=["meetings"],
    operation_id="get_jra_race_card",
    summary="開催日・開催地・レース番号で出馬表を取得",
    description=(
        "開催日、開催地、レース番号を指定して出馬表を取得します。"
        " 馬番、馬名、枠番、騎手、斤量など、レース予想の基本情報を確認するために使用します。"
    ),
)
async def get_race_card_by_number(
    date_: RaceDatePath,
    course: CourseCodePath,
    race_no: RaceNoPath,
    svc: JraService = Depends(get_service),
):
    return await svc.get_race_card_by_number(date_, str(course), race_no)


@app.get(
    "/races/{race_id}/odds",
    tags=["races"],
    summary="race_id でオッズを取得",
    description=(
        "race_id を指定してオッズを取得します。"
        " `bet_type` を指定すると単一券種、`bet_types` を指定すると複数券種をまとめて取得します。"
    ),
)
async def get_race_odds(
    race_id: RaceIdPath,
    bet_type: BetType | None = Query(
        default=None,
        description="単一券種コード。例: win, quinella, exacta, wide, trio, trifecta",
        examples=["trifecta"],
    ),
    bet_types: str | None = Query(
        default=None,
        description="複数券種をカンマ区切りで指定します。例: win,trifecta",
        examples=["win,trifecta"],
    ),
    combination: str | None = Query(
        default=None,
        description="組み合わせをカンマ区切りで指定します。例: 1,2,3",
        examples=["1,2,3"],
    ),
    refresh: bool = Query(
        default=False,
        description="true の場合はキャッシュを使わず再取得します。",
    ),
    svc: JraService = Depends(get_service),
):
    parsed = [str(item) for item in parse_bet_types(bet_types)] if bet_types else None
    parsed_combination = [item.strip() for item in combination.split(",")] if combination else None
    return await svc.get_race_odds(
        race_id,
        bet_types=parsed,
        bet_type=str(bet_type) if bet_type else None,
        combination=parsed_combination,
        refresh=refresh,
    )


@app.get(
    "/meetings/{date_}/{course}/races/{race_no}/odds",
    tags=["meetings"],
    operation_id="get_jra_race_odds",
    summary="開催日・開催地・レース番号でオッズを取得",
    description=(
        "開催日、開催地、レース番号からオッズを取得します。"
        " `bet_type` は必須です。必要なら `combination` で一点に絞り込めます。"
    ),
)
async def get_race_odds_by_number(
    date_: RaceDatePath,
    course: CourseCodePath,
    race_no: RaceNoPath,
    bet_type: BetType = Query(
        description="券種コード。例: win, quinella, exacta, wide, trio, trifecta",
        examples=["quinella"],
    ),
    combination: str | None = Query(
        default=None,
        description="組み合わせをカンマ区切りで指定します。例: 10,11 または 4,10,11",
        examples=["10,11"],
    ),
    refresh: bool = Query(
        default=False,
        description="true の場合はキャッシュを使わず再取得します。",
    ),
    svc: JraService = Depends(get_service),
):
    parsed_combination = [item.strip() for item in combination.split(",")] if combination else None
    return await svc.get_race_odds_by_number(date_, str(course), race_no, str(bet_type), parsed_combination, refresh)


@app.get(
    "/races/{race_id}/result",
    tags=["races"],
    summary="race_id で結果を取得",
    description="race_id を指定して結果と払戻を取得します。",
)
async def get_race_result(race_id: RaceIdPath, svc: JraService = Depends(get_service)):
    return await svc.get_race_result(race_id)


@app.get(
    "/meetings/{date_}/{course}/races/{race_no}/result",
    tags=["meetings"],
    operation_id="get_jra_race_result",
    summary="開催日・開催地・レース番号で結果を取得",
    description=(
        "開催日、開催地、レース番号から確定した着順と払戻を取得します。"
        " レース確定前は結果が揃っていない場合があります。"
    ),
)
async def get_race_result_by_number(
    date_: RaceDatePath,
    course: CourseCodePath,
    race_no: RaceNoPath,
    svc: JraService = Depends(get_service),
):
    return await svc.get_race_result_by_number(date_, str(course), race_no)


@app.get(
    "/netkeiba/races/{race_id}/result",
    tags=["netkeiba"],
    summary="netkeiba race_result を取得",
    description="netkeiba の過去レース結果ページから着順、詳細結果、払戻を取得します。",
)
async def get_netkeiba_race_result(
    race_id: RaceIdPath,
    svc: NetkeibaService = Depends(get_netkeiba_service),
):
    return await svc.get_race_result(race_id)


@app.get(
    "/netkeiba/races/{race_id}/odds",
    tags=["netkeiba"],
    summary="netkeiba odds_view を取得",
    description="netkeiba の odds_view とページ内 odds API からオッズを取得します。",
)
async def get_netkeiba_race_odds(
    race_id: RaceIdPath,
    bet_type: str | None = Query(
        default=None,
        description="券種コード。例: wide, quinella, trio, trifecta, win, place",
        examples=["wide"],
    ),
    combination: str | None = Query(
        default=None,
        description="組み合わせをカンマ区切りで指定します。例: 6,10",
        examples=["13,17"],
    ),
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NetkeibaService = Depends(get_netkeiba_service),
):
    parsed_combination = [item.strip() for item in combination.split(",")] if combination else None
    return await svc.get_race_odds(
        race_id,
        bet_type=bet_type,
        combination=parsed_combination,
        refresh=refresh,
    )


@app.get(
    "/nar/calendar",
    tags=["nar"],
    summary="nar calendar",
    response_model=NarCalendarPage,
)
async def get_nar_calendar(
    year: int = Query(description="year"),
    month: int = Query(ge=1, le=12, description="month"),
    course: str | None = Query(default=None, description="course key or Japanese venue name"),
    svc: NarNetkeibaService = Depends(get_nar_netkeiba_service),
):
    return await svc.get_calendar(year=year, month=month, course=course)


@app.get(
    "/nar/meetings/{date_}/{course}",
    tags=["nar"],
    summary="nar meeting races",
)
async def get_nar_meeting(
    date_: date,
    course: str,
    svc: NarNetkeibaService = Depends(get_nar_netkeiba_service),
):
    return await svc.get_meeting(date_, course)


@app.get(
    "/nar/races/{race_id}/card",
    tags=["nar"],
    summary="nar race card",
)
async def get_nar_race_card(
    race_id: RaceIdPath,
    svc: NarNetkeibaService = Depends(get_nar_netkeiba_service),
):
    return await svc.get_race_card(race_id)


@app.get(
    "/nar/races/{race_id}/result",
    tags=["nar"],
    summary="nar race result",
)
async def get_nar_race_result(
    race_id: RaceIdPath,
    svc: NarNetkeibaService = Depends(get_nar_netkeiba_service),
):
    return await svc.get_race_result(race_id)


@app.get(
    "/nar/races/{race_id}/odds",
    tags=["nar"],
    summary="nar race odds",
)
async def get_nar_race_odds(
    race_id: RaceIdPath,
    bet_type: str | None = Query(default=None, description="bet type"),
    combination: str | None = Query(default=None, description="combination"),
    refresh: bool = Query(default=False, description="refresh cache"),
    svc: NarNetkeibaService = Depends(get_nar_netkeiba_service),
):
    parsed_combination = [item.strip() for item in combination.split(",")] if combination else None
    return await svc.get_race_odds(
        race_id,
        bet_type=bet_type,
        combination=parsed_combination,
        refresh=refresh,
    )


@app.get(
    "/nankan/leading/jockeys",
    tags=["nankan"],
    summary="南関東公式のリーディングジョッキーを取得",
    response_model=NankanLeadingJockeyPage,
)
async def get_nankan_leading_jockeys(
    course: NankanCourseCode | None = Query(default=None, description="競馬場。例: kawasaki"),
    distance: int | None = Query(default=None, description="距離。例: 1400"),
    track_condition: str | None = Query(default=None, description="馬場状態。good/slightly_heavy/heavy/bad"),
    period: str = Query(default="recent_3months", description="表示期間。recent_3months/recent_1year/年"),
    sort: str = Query(default="win_rate", description="表示順。wins/earnings/win_rate/quinella_rate"),
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_leading_jockeys(
        course=str(course) if course else None,
        distance=distance,
        track_condition=track_condition,
        period=period,
        sort=sort,
        refresh=refresh,
    )


@app.get(
    "/nankan/meetings/{date_}/{course}",
    tags=["nankan"],
    summary="南関東公式の開催一覧を取得",
)
async def get_nankan_meeting(
    date_: date,
    course: NankanCourseCode,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_meeting(date_, str(course), refresh=refresh)


@app.get(
    "/nankan/meetings/{date_}/{course}/trend",
    tags=["nankan"],
    summary="南関東公式の当日開催傾向を取得",
    response_model=NankanMeetingTrend,
)
async def get_nankan_meeting_trend(
    date_: date,
    course: NankanCourseCode,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_meeting_trend(date_, str(course), refresh=refresh)


@app.get(
    "/nankan/meetings/{date_}/{course}/races/{race_no}/trend-context",
    tags=["nankan"],
    summary="南関東公式の当日開催傾向を対象レースの事前予想用に判定",
    response_model=NankanMeetingTrendContext,
)
async def get_nankan_meeting_trend_context(
    date_: date,
    course: NankanCourseCode,
    race_no: RaceNoPath,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_meeting_trend_context(date_, str(course), race_no, refresh=refresh)


@app.get(
    "/nankan/races/{race_id}/card",
    tags=["nankan"],
    summary="南関東公式の出走表を取得",
    response_model=RaceCard,
)
async def get_nankan_race_card(
    race_id: NankanRaceIdPath,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_race_card(race_id, refresh=refresh)


@app.get(
    "/nankan/races/{race_id}/best-time",
    tags=["nankan"],
    summary="南関東公式の持ち時計を取得",
    response_model=NankanRaceBestTime,
)
async def get_nankan_race_best_time(
    race_id: NankanRaceIdPath,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_race_best_time(race_id, refresh=refresh)


@app.get(
    "/nankan/races/{race_id}/closing-speed",
    tags=["nankan"],
    summary="南関東公式の上がり時計を取得",
    response_model=NankanRaceClosingSpeed,
)
async def get_nankan_race_closing_speed(
    race_id: NankanRaceIdPath,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_race_closing_speed(race_id, refresh=refresh)


@app.get(
    "/nankan/races/{race_id}/style-profile",
    tags=["nankan"],
    summary="南関東公式の近走通過順から脚質傾向を推定",
    response_model=NankanRaceStyleProfile,
)
async def get_nankan_race_style_profile(
    race_id: NankanRaceIdPath,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_race_style_profile(race_id, refresh=refresh)


@app.get(
    "/nankan/races/{race_id}/odds",
    tags=["nankan"],
    summary="南関東公式のオッズを取得",
)
async def get_nankan_race_odds(
    race_id: NankanRaceIdPath,
    bet_type: BetType | None = Query(default=None, description="単一券種コード。例: win, quinella, exacta, wide, trio, trifecta"),
    bet_types: str | None = Query(default=None, description="複数券種をカンマ区切りで指定します。例: win,trifecta"),
    combination: str | None = Query(default=None, description="組み合わせをカンマ区切りで指定します。例: 5,7,6"),
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    parsed = [str(item) for item in parse_bet_types(bet_types)] if bet_types else None
    parsed_combination = [item.strip() for item in combination.split(",")] if combination else None
    return await svc.get_race_odds(
        race_id,
        bet_type=str(bet_type) if bet_type else None,
        bet_types=parsed,
        combination=parsed_combination,
        refresh=refresh,
    )


@app.get(
    "/nankan/races/{race_id}/result",
    tags=["nankan"],
    summary="南関東公式の結果を取得",
)
async def get_nankan_race_result(
    race_id: NankanRaceIdPath,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_race_result(race_id, refresh=refresh)


@app.get(
    "/nankan/meetings/{date_}/{course}/races/{race_no}/card",
    tags=["nankan"],
    summary="南関東公式の出走表を日付・場・Rで取得",
    response_model=RaceCard,
)
async def get_nankan_race_card_by_number(
    date_: date,
    course: NankanCourseCode,
    race_no: RaceNoPath,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_race_card_by_number(date_, str(course), race_no, refresh=refresh)


@app.get(
    "/nankan/meetings/{date_}/{course}/races/{race_no}/best-time",
    tags=["nankan"],
    summary="南関東公式の持ち時計を日付・場・Rで取得",
    response_model=NankanRaceBestTime,
)
async def get_nankan_race_best_time_by_number(
    date_: date,
    course: NankanCourseCode,
    race_no: RaceNoPath,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_race_best_time_by_number(date_, str(course), race_no, refresh=refresh)


@app.get(
    "/nankan/meetings/{date_}/{course}/races/{race_no}/closing-speed",
    tags=["nankan"],
    summary="南関東公式の上がり時計を日付・場・Rで取得",
    response_model=NankanRaceClosingSpeed,
)
async def get_nankan_race_closing_speed_by_number(
    date_: date,
    course: NankanCourseCode,
    race_no: RaceNoPath,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_race_closing_speed_by_number(date_, str(course), race_no, refresh=refresh)


@app.get(
    "/nankan/meetings/{date_}/{course}/races/{race_no}/style-profile",
    tags=["nankan"],
    summary="南関東公式の近走通過順から脚質傾向を日付・場・Rで推定",
    response_model=NankanRaceStyleProfile,
)
async def get_nankan_race_style_profile_by_number(
    date_: date,
    course: NankanCourseCode,
    race_no: RaceNoPath,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    return await svc.get_race_style_profile_by_number(date_, str(course), race_no, refresh=refresh)


@app.get( 
    "/nankan/meetings/{date_}/{course}/races/{race_no}/odds", 
    tags=["nankan"],
    summary="南関東公式のオッズを日付・場・Rで取得",
)
async def get_nankan_race_odds_by_number(
    date_: date,
    course: NankanCourseCode,
    race_no: RaceNoPath,
    bet_type: BetType | None = Query(default=None, description="単一券種コード。例: win, quinella, exacta, wide, trio, trifecta"),
    bet_types: str | None = Query(default=None, description="複数券種をカンマ区切りで指定します。例: win,trifecta"),
    combination: str | None = Query(default=None, description="組み合わせをカンマ区切りで指定します。例: 5,7,6"),
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
):
    parsed = [str(item) for item in parse_bet_types(bet_types)] if bet_types else None
    parsed_combination = [item.strip() for item in combination.split(",")] if combination else None
    return await svc.get_race_odds_by_number( 
        date_, 
        str(course), 
        race_no, 
        bet_type=str(bet_type) if bet_type else None,
        bet_types=parsed,
        combination=parsed_combination,
        refresh=refresh, 
    ) 


@app.get(
    "/nankan/meetings/{date_}/{course}/races/{race_no}/odds-summary",
    tags=["nankan"],
    summary="å—é–¢äºˆæƒ³å‘ã‘ã®è»½é‡ã‚ªãƒƒã‚ºã‚’æ—¥ä»˜ãƒ»å ´ãƒ»Rã§å–å¾—",
    response_model=RaceOdds,
)
async def get_nankan_race_odds_summary_by_number(
    date_: date,
    course: NankanCourseCode,
    race_no: RaceNoPath,
    bet_types: str | None = Query(default=None, description="è¤‡æ•°åˆ¸ç¨®ã‚’ã‚«ãƒ³ãƒžåŒºåˆ‡ã‚Šã§æŒ‡å®šã—ã¾ã™ã€‚ä¾‹: win,wide,quinella"),
    refresh: bool = Query(default=False, description="true ã®å ´åˆã¯ã‚­ãƒ£ãƒƒã‚·ãƒ¥ã‚’ä½¿ã‚ãšå†å–å¾—ã—ã¾ã™ã€‚"),
    svc: NankanService = Depends(get_nankan_service),
):
    parsed = [str(item) for item in parse_bet_types(bet_types)] if bet_types else None
    return await svc.get_race_odds_summary_by_number(
        date_,
        str(course),
        race_no,
        bet_types=parse_nankan_odds_summary_bet_types(parsed),
        refresh=refresh,
    )


@app.get( 
    "/nankan/meetings/{date_}/{course}/races/{race_no}/result", 
    tags=["nankan"],
    summary="南関東公式の結果を日付・場・Rで取得",
)
async def get_nankan_race_result_by_number(
    date_: date,
    course: NankanCourseCode,
    race_no: RaceNoPath,
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanService = Depends(get_nankan_service),
): 
    return await svc.get_race_result_by_number(date_, str(course), race_no, refresh=refresh) 


@app.get(
    "/nankan/meetings/{date_}/{course}/races/{race_no}/prediction-bundle",
    tags=["nankan"],
    summary="å—é–¢äºˆæƒ³å‘ã‘ã®ææ–™ã‚’ 1 å›žã§ã¾ã¨ã‚ã¦å–å¾—",
    response_model=NankanPredictionBundle,
)
async def get_nankan_prediction_bundle(
    date_: date,
    course: NankanCourseCode,
    race_no: RaceNoPath,
    meeting_no: int = Query(ge=1, description="é–‹å‚¬å›žã€‚ä¾‹: 4"),
    meeting_day: int = Query(ge=1, description="é–‹å‚¬æ—¥ã€‚ä¾‹: 1"),
    bet_types: str | None = Query(default=None, description="è¤‡æ•°åˆ¸ç¨®ã‚’ã‚«ãƒ³ãƒžåŒºåˆ‡ã‚Šã§æŒ‡å®šã—ã¾ã™ã€‚ä¾‹: win,wide,quinella"),
    refresh: bool = Query(default=False, description="true ã®å ´åˆã¯ã‚­ãƒ£ãƒƒã‚·ãƒ¥ã‚’ä½¿ã‚ãšå†å–å¾—ã—ã¾ã™ã€‚"),
    svc: NankanPredictionService = Depends(get_nankan_prediction_service),
):
    parsed = [str(item) for item in parse_bet_types(bet_types)] if bet_types else None
    return await svc.get_prediction_bundle(
        date_,
        str(course),
        race_no,
        meeting_no,
        meeting_day,
        bet_types=parse_nankan_odds_summary_bet_types(parsed),
        refresh=refresh,
    )


@app.get(
    "/nankan/meetings/{date_}/{course}/races/{race_no}/prediction-summary",
    tags=["nankan"],
    summary="南関予想向けの主要指標だけをまとめて取得",
    response_model=NankanPredictionSummary,
)
async def get_nankan_prediction_summary(
    date_: date,
    course: NankanCourseCode,
    race_no: RaceNoPath,
    meeting_no: int = Query(ge=1, description="開催回。例: 4"),
    meeting_day: int = Query(ge=1, description="開催日。例: 1"),
    bet_types: str | None = Query(default=None, description="複数券種をカンマ区切りで指定します。例: win,wide,quinella"),
    refresh: bool = Query(default=False, description="true の場合はキャッシュを使わず再取得します。"),
    svc: NankanPredictionService = Depends(get_nankan_prediction_service),
):
    parsed = [str(item) for item in parse_bet_types(bet_types)] if bet_types else None
    return await svc.get_prediction_summary(
        date_,
        str(course),
        race_no,
        meeting_no,
        meeting_day,
        bet_types=parse_nankan_odds_summary_bet_types(parsed),
        refresh=refresh,
    )


@app.get( 
    "/nankankeiba/pattern/meetings/{date_}/{course}/races/{race_no}", 
    tags=["nankankeiba"],
    summary="南関東 勝ちパターン分析を取得",
    response_model=NankankeibaPatternBundle,
)
async def get_nankankeiba_pattern(
    date_: date,
    course: str,
    race_no: RaceNoPath,
    meeting_no: int = Query(ge=1, description="開催回。例: 4"),
    meeting_day: int = Query(ge=1, description="開催日。例: 1"),
    periods: str | None = Query(default="lifetime", description="期間コード。現時点では lifetime または 01。"),
    categories: str | None = Query(default=None, description="カテゴリをカンマ区切りで指定します。"),
    refresh: bool = Query(default=False, description="refresh cache"),
    svc: NankankeibaPatternService = Depends(get_nankankeiba_pattern_service),
):
    return await svc.get_pattern_bundle(
        date_,
        course,
        meeting_no,
        meeting_day,
        race_no,
        periods=_parse_query_csv(periods) or ["lifetime"],
        categories=_parse_query_csv(categories),
        refresh=refresh,
    )


@app.post(
    "/jra/days/{date_}/race-scout",
    tags=["jra-analysis"],
    summary="JRA当日全レースから詳細予想候補を抽出",
    response_model=JraDayRaceScoutResult,
)
async def create_jra_day_race_scout(
    date_: date,
    max_candidates: int = Query(default=5, ge=1, le=10),
    refresh: bool = Query(default=False),
    max_concurrency: int = Query(default=3, ge=1, le=5),
    mode: str = Query(default="quick", pattern="^(quick|deep)$"),
    time_budget_seconds: float = Query(default=45.0, ge=5.0, le=55.0),
    scout: JraDayRaceScout = Depends(get_jra_day_race_scout),
):
    return await scout.run(
        date_, max_candidates=max_candidates, refresh=refresh, max_concurrency=max_concurrency,
        mode=mode, time_budget_seconds=time_budget_seconds,
    )


@app.get(
    "/jra/meetings/{date_}/{course}/races/{race_no}/prediction-bundle",
    tags=["jra-analysis"],
    operation_id="get_jra_prediction_bundle",
    summary="JRA予想向け当日材料をまとめて取得",
    description=(
        "出馬表、オッズ、公開分析、傾向など、JRAレース予想に必要な当日材料をまとめて取得します。"
        " 通常はrefresh=falseで利用し、明示的に最新情報が必要な場合だけ再取得してください。"
    ),
    response_model=JraPredictionBundle,
)
async def get_jra_prediction_bundle(
    date_: RaceDatePath,
    course: CourseCodePath,
    race_no: RaceNoPath,
    meeting_no: int = Query(ge=1, le=99, description="開催回。例: 第2回開催なら2"),
    meeting_day: int = Query(ge=1, le=99, description="開催日数。例: 4日目なら4"),
    sources: str | None = Query(
        default=None,
        description="取得元をカンマ区切りで指定。例: netkeiba,keibalab",
    ),
    bet_types: str | None = Query(
        default=None,
        description="取得するオッズ券種をカンマ区切りで指定。例: win,wide,quinella",
    ),
    refresh: bool = Query(
        default=False,
        description="trueの場合はキャッシュを使わず外部サイトから再取得します。通常はfalseを指定します。",
    ),
    svc: JraPredictionService = Depends(get_jra_prediction_service),
):
    return await svc.get_prediction_bundle(
        date_, str(course), race_no, meeting_no, meeting_day,
        sources=_parse_query_csv(sources),
        odds_bet_types=_parse_query_csv(bet_types),
        refresh=refresh,
    )


@app.get(
    "/jra/meetings/{date_}/{course}/races/{race_no}/public-analysis",
    tags=["jra-analysis"],
    summary="匿名公開範囲の外部分析材料を取得",
)
async def get_jra_public_analysis(
    date_: date,
    course: CourseCode,
    race_no: RaceNoPath,
    meeting_no: int = Query(ge=1, le=99),
    meeting_day: int = Query(ge=1, le=99),
    sources: str | None = Query(default=None),
    refresh: bool = Query(default=False),
    svc: JraPredictionService = Depends(get_jra_prediction_service),
):
    return await svc.get_public_analysis(
        date_, str(course), race_no, meeting_no, meeting_day,
        sources=_parse_query_csv(sources), refresh=refresh,
    )


@app.get(
    "/jra/meetings/{date_}/{course}/races/{race_no}/trend-context",
    tags=["jra-analysis"],
    summary="同日先行レースの確定結果傾向を取得",
)
async def get_jra_trend_context(
    date_: date,
    course: CourseCode,
    race_no: RaceNoPath,
    svc: JraPredictionService = Depends(get_jra_prediction_service),
):
    return await svc.get_trend_context(date_, str(course), race_no)


async def _jra_lite(kind, date_, course, race_no, meeting_no, meeting_day, refresh, svc):
    return await svc.get_lite_material(
        kind, date_, str(course), race_no, meeting_no, meeting_day, refresh,
    )


@app.get("/jra/meetings/{date_}/{course}/races/{race_no}/best-time-lite", tags=["jra-analysis"])
async def get_jra_best_time_lite(
    date_: date, course: CourseCode, race_no: RaceNoPath,
    meeting_no: int = Query(ge=1, le=99), meeting_day: int = Query(ge=1, le=99),
    refresh: bool = Query(default=False), svc: JraPredictionService = Depends(get_jra_prediction_service),
):
    return await _jra_lite("best-time-lite", date_, course, race_no, meeting_no, meeting_day, refresh, svc)


@app.get("/jra/meetings/{date_}/{course}/races/{race_no}/closing-speed-lite", tags=["jra-analysis"])
async def get_jra_closing_speed_lite(
    date_: date, course: CourseCode, race_no: RaceNoPath,
    meeting_no: int = Query(ge=1, le=99), meeting_day: int = Query(ge=1, le=99),
    refresh: bool = Query(default=False), svc: JraPredictionService = Depends(get_jra_prediction_service),
):
    return await _jra_lite("closing-speed-lite", date_, course, race_no, meeting_no, meeting_day, refresh, svc)


@app.get("/jra/meetings/{date_}/{course}/races/{race_no}/style-profile-lite", tags=["jra-analysis"])
async def get_jra_style_profile_lite(
    date_: date, course: CourseCode, race_no: RaceNoPath,
    meeting_no: int = Query(ge=1, le=99), meeting_day: int = Query(ge=1, le=99),
    refresh: bool = Query(default=False), svc: JraPredictionService = Depends(get_jra_prediction_service),
):
    return await _jra_lite("style-profile-lite", date_, course, race_no, meeting_no, meeting_day, refresh, svc)


@app.get(
    "/jra/meetings/{date_}/{course}/races/{race_no}/odds-summary",
    tags=["jra-analysis"],
    operation_id="get_jra_odds_summary",
    summary="JRAオッズを券種別に要約",
    description=(
        "指定レースのオッズを、予想で扱いやすい券種別の要約形式で取得します。"
        " 必要な券種だけをbet_typesで指定すると取得量を抑えられます。"
    ),
)
async def get_jra_odds_summary(
    date_: RaceDatePath,
    course: CourseCodePath,
    race_no: RaceNoPath,
    bet_types: str | None = Query(
        default=None,
        description="券種をカンマ区切りで指定。例: win,wide,quinella",
    ),
    refresh: bool = Query(
        default=False,
        description="trueの場合はキャッシュを使わず再取得します。通常はfalseを指定します。",
    ),
    svc: JraPredictionService = Depends(get_jra_prediction_service),
):
    return await svc.get_odds_summary(date_, str(course), race_no, _parse_query_csv(bet_types), refresh)


@app.get(
    "/jra/meetings/{date_}/{course}/races/{race_no}/model-comparison",
    tags=["jra-analysis"],
    operation_id="compare_jra_prediction_models",
    summary="公開材料モデルと履歴学習モデルを比較",
    description=(
        "公開材料モデル、履歴学習モデル、V理論の順位を比較し、一致度と総合評価を返します。"
        " モデルファイルが利用できない場合は、その構成要素をunavailableとして返します。"
    ),
)
async def get_jra_model_comparison(
    date_: RaceDatePath,
    course: CourseCodePath,
    race_no: RaceNoPath,
    meeting_no: int = Query(ge=1, le=99, description="開催回。例: 第2回開催なら2"),
    meeting_day: int = Query(ge=1, le=99, description="開催日数。例: 4日目なら4"),
    refresh: bool = Query(
        default=False,
        description="trueの場合はキャッシュを使わず再取得します。通常はfalseを指定します。",
    ),
    svc: JraPredictionService = Depends(get_jra_prediction_service),
):
    bundle = await svc.get_prediction_bundle(
        date_, str(course), race_no, meeting_no, meeting_day,
        sources=["netkeiba", "keibalab"], odds_bet_types=["win", "wide"], refresh=refresh,
    )
    materials_record = build_prediction_record(bundle)
    materials_ranking = materials_record["prediction_json"]["predicted_ranking"]
    try:
        artifact = load_model_artifact(_default_history_model_path())
        if artifact["trained_through"] >= date_.isoformat():
            raise BadRequestError(
                "history model training horizon is not before target date; retrain only with earlier data"
            )
        history_records = build_artifact_live_records(
            artifact, _default_analysis_db_path(), target_date=date_, course=str(course), card=bundle.card,
        )
        history_ranking = score_live_records(artifact, history_records)
        history = {
            "status": "available",
            "model_version": artifact["model_version"],
            "trained_through": artifact["trained_through"],
            "artifact_hash": artifact["artifact_hash"],
            "ranking": history_ranking,
        }
        material_top3 = {item["horse_no"] for item in materials_ranking[:3]}
        history_top3 = {item["horse_no"] for item in history_ranking[:3]}
        comparison = {
            "material_top3": sorted(material_top3),
            "history_top3": sorted(history_top3),
            "top3_agreement": sorted(material_top3 & history_top3),
            "top_pick_agrees": bool(materials_ranking and history_ranking and materials_ranking[0]["horse_no"] == history_ranking[0]["horse_no"]),
        }
    except FileNotFoundError as exc:
        history = {"status": "unavailable", "reason": str(exc)}
        comparison = None
    try:
        v_theory = build_v_theory_prediction(
            _default_analysis_db_path(), target_date=date_, course=str(course), card=bundle.card,
            win_odds={item["horse_no"]: item["win_odds"] for item in materials_ranking if item.get("win_odds")},
            race_odds=bundle.odds_summary,
        )
    except (FileNotFoundError, ValueError) as exc:
        v_theory = {"status": "unavailable", "reason": str(exc)}
    total_evaluation = build_three_way_consensus(
        materials_ranking,
        history.get("ranking", []) if history["status"] == "available" else [],
        v_theory,
    )
    return {
        "race_id": bundle.race_id,
        "as_of": bundle.fetched_at,
        "materials_model": {
            "model_version": materials_record["theory_version"],
            "ranking": materials_ranking,
            "component_status": bundle.meta.component_status,
        },
        "history_model": history,
        "v_theory": v_theory,
        "comparison": comparison,
        "total_evaluation": total_evaluation,
    }


@app.get(
    "/jra/meetings/{date_}/{course}/races/{race_no}/betting-decision",
    tags=["jra-analysis"],
    operation_id="get_jra_betting_decision",
    summary="履歴勝率と単勝オッズから期待値を判定",
    description=(
        "履歴モデルの推定勝率と単勝オッズを比較し、指定予算内の購入候補と見送り判断を返します。"
        " 実際の投票や購入記録の保存は行わない読み取り専用ツールです。"
    ),
)
async def get_jra_betting_decision(
    date_: RaceDatePath,
    course: CourseCodePath,
    race_no: RaceNoPath,
    meeting_no: int = Query(ge=1, le=99, description="開催回。例: 第2回開催なら2"),
    meeting_day: int = Query(ge=1, le=99, description="開催日数。例: 4日目なら4"),
    budget: int = Query(default=1000, ge=100, description="購入判断に使用する予算額。100円以上。"),
    refresh: bool = Query(
        default=False,
        description="trueの場合はキャッシュを使わず再取得します。通常はfalseを指定します。",
    ),
    svc: JraPredictionService = Depends(get_jra_prediction_service),
):
    bundle = await svc.get_prediction_bundle(
        date_, str(course), race_no, meeting_no, meeting_day,
        sources=["netkeiba", "keibalab"], odds_bet_types=["win"], refresh=refresh,
    )
    materials_ranking = (
        build_prediction_record(bundle)["prediction_json"]["predicted_ranking"]
        if is_newcomer_race(bundle.card.race_name)
        else []
    )
    try:
        artifact = load_model_artifact(_default_history_model_path())
        if artifact["trained_through"] >= date_.isoformat():
            raise BadRequestError(
                "history model training horizon is not before target date; retrain only with earlier data"
            )
        records = build_artifact_live_records(
            artifact, _default_analysis_db_path(), target_date=date_, course=str(course), card=bundle.card,
        )
        ranking = score_live_records(artifact, records)
        decision = build_win_betting_decision(
            bundle.card.race_name,
            ranking,
            materials_ranking,
            bundle.odds_summary,
            budget=budget,
        )
        model = {
            "status": "available",
            "model_version": artifact["model_version"],
            "trained_through": artifact["trained_through"],
            "artifact_hash": artifact["artifact_hash"],
        }
    except FileNotFoundError as exc:
        ranking = []
        decision = {
            "status": "unavailable",
            "reason": str(exc),
            "tickets": [],
            "candidates": [],
        }
        model = {"status": "unavailable", "reason": str(exc)}
    return {
        "race_id": bundle.race_id,
        "as_of": bundle.fetched_at,
        "history_model": model,
        "ranking": ranking,
        "betting_decision": decision,
    }


@app.post("/jra/meetings/{date_}/{course}/races/{race_no}/predictions", tags=["jra-analysis"])
async def create_jra_prediction(
    date_: date, course: CourseCode, race_no: RaceNoPath,
    meeting_no: int = Query(ge=1, le=99), meeting_day: int = Query(ge=1, le=99),
    budget: int = Query(default=1000, ge=100), refresh: bool = Query(default=True),
    svc: JraPredictionService = Depends(get_jra_prediction_service),
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    bundle = await svc.get_prediction_bundle(
        date_, str(course), race_no, meeting_no, meeting_day,
        sources=["netkeiba", "keibalab"], odds_bet_types=["win", "wide"], refresh=refresh,
    )
    record = build_prediction_record(bundle, budget=budget)
    return {"record": record, "saved": store.upsert_prediction_record(record)}


@app.get(
    "/jra/races/{race_id}/pre-race-snapshot",
    tags=["jra-analysis"],
    summary="保存済みJRA発走前snapshotを取得",
    description="analysis SQLiteに保存済みの発走前レース、出走馬、選択したオッズsnapshotを返します。",
    response_model=StoredPreRaceSnapshot,
)
async def get_jra_pre_race_snapshot(
    race_id: RaceIdPath,
    include_odds: bool = Query(
        default=True,
        description="falseの場合はオッズと利用可能な収集時点を読み込みません。",
    ),
    odds_timing: str | None = Query(
        default=None,
        description="収集時点ラベルの完全一致。省略時は券種ごとの最新snapshotを返します。",
    ),
    as_of: AwareDatetime | None = Query(
        default=None,
        description=(
            "timezone付きISO 8601観測時刻。指定時刻以前の最新出馬表と"
            "券種ごとの最新オッズを返します。"
        ),
    ),
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    return store.get_pre_race_snapshot(
        race_id,
        include_odds=include_odds,
        odds_timing=odds_timing,
        as_of=as_of,
    )


@app.get(
    "/jra/races/{race_id}/odds-timeline",
    tags=["jra-analysis"],
    summary="保存済みJRAオッズ時系列を取得",
    description="analysis SQLiteに保存済みの指定券種のオッズsnapshotを取得時刻順に返します。",
    response_model=StoredOddsTimeline,
)
async def get_jra_odds_timeline(
    race_id: RaceIdPath,
    bet_type: BetType = Query(
        description="券種コード。win, place, quinella, wide, exacta, trio, trifecta。",
    ),
    combination: str | None = Query(
        default=None,
        description="組み合わせをカンマ区切りで指定します。例: 4,10",
    ),
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    normalized_combination = (
        normalize_combination(combination)
        if combination is not None
        else None
    )
    return store.get_odds_timeline(
        race_id,
        str(bet_type),
        normalized_combination,
    )


@app.get(
    "/jra/races/{race_id}/live-shadow-observations",
    tags=["jra-analysis"],
    summary="保存済みJRA発走前ライブシャドー観測を取得",
    description="race-scout実行時に保存した候補、単勝オッズ、モデル版、shadow判断を新しい順に返します。",
    response_model=JraLiveShadowObservationPage,
)
async def list_jra_live_shadow_observations(
    race_id: RaceIdPath,
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    return store.list_jra_live_shadow_observations(
        race_id,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/jra/predictions",
    tags=["jra-analysis"],
    summary="保存済みJRA予想を検索",
    response_model=PredictionRecordPage,
)
async def list_jra_predictions(
    race_id: str | None = Query(default=None, pattern=r"^\d{12}$"),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    theory_version: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    if from_date is not None and to_date is not None and from_date > to_date:
        raise BadRequestError("from_date must be on or before to_date")
    return store.list_prediction_records(
        race_id=race_id,
        from_date=from_date,
        to_date=to_date,
        theory_version=theory_version,
        mode=mode,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/jra/predictions/{prediction_id}",
    tags=["jra-analysis"],
    summary="保存済みJRA予想を取得",
    response_model=PredictionRecord,
)
async def get_jra_prediction(
    prediction_id: str,
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    return store.get_prediction_record(prediction_id)


@app.post("/jra/predictions/{prediction_id}/evaluate", tags=["jra-analysis"])
async def evaluate_jra_prediction(
    prediction_id: str,
    payload: dict = Body(default_factory=dict),
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    return store.evaluate_prediction_record({"prediction_id": prediction_id, **payload})


@app.get(
    "/jra/evaluations/summary",
    tags=["jra-analysis"],
    summary="保存済みJRA予想評価を集計",
    response_model=EvaluationSummary,
)
async def summarize_jra_evaluations(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    theory_version: str | None = Query(default=None),
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    if from_date is not None and to_date is not None and from_date > to_date:
        raise BadRequestError("from_date must be on or before to_date")
    return store.summarize_evaluations(
        from_date=from_date,
        to_date=to_date,
        theory_version=theory_version,
    )


@app.get(
    "/jra/evaluations",
    tags=["jra-analysis"],
    summary="保存済みJRA予想評価を検索",
    response_model=EvaluationRecordPage,
)
async def list_jra_evaluations(
    prediction_id: str | None = Query(default=None),
    race_id: str | None = Query(default=None, pattern=r"^\d{12}$"),
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    theory_version: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    offset: int = Query(default=0, ge=0),
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    if from_date is not None and to_date is not None and from_date > to_date:
        raise BadRequestError("from_date must be on or before to_date")
    return store.list_evaluation_records(
        prediction_id=prediction_id,
        race_id=race_id,
        from_date=from_date,
        to_date=to_date,
        theory_version=theory_version,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/jra/evaluations/{evaluation_id}",
    tags=["jra-analysis"],
    summary="保存済みJRA予想評価を取得",
    response_model=EvaluationRecord,
)
async def get_jra_evaluation(
    evaluation_id: str,
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    return store.get_evaluation_record(evaluation_id)


@app.post("/jra/meetings/{date_}/{course}/races/{race_no}/result/save", tags=["jra-analysis"])
async def save_jra_result(
    date_: date, course: CourseCode, race_no: RaceNoPath,
    svc: JraService = Depends(get_service),
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    result = await svc.get_race_result_by_number(date_, str(course), race_no)
    if not result.results or not result.payouts:
        raise BadRequestError("result or payout is not finalized")
    store.write_result(result)
    return {"race_id": result.race_id, "results": len(result.results), "payouts": len(result.payouts), "fetched_at": result.fetched_at}


@app.get(
    "/stored/results",
    tags=["races"],
    summary="保存済み結果を検索",
    description="JSONL などの保存先に蓄積済みのレース結果を、日付範囲と開催場で検索します。",
    response_model=StoredRaceResultPage,
)
async def list_stored_results(
    from_date: date | None = Query(default=None, description="検索開始日。例: 2026-03-22"),
    to_date: date | None = Query(default=None, description="検索終了日。例: 2026-03-22"),
    course: CourseCode | None = Query(default=None, description="開催地コード。例: nakayama"),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT, description="返却件数。最大500件。"),
    offset: int = Query(default=0, ge=0, description="先頭からスキップする件数。"),
    storage: ResultStorage = Depends(get_result_storage),
):
    return storage.list_results_page(
        from_date=from_date,
        to_date=to_date,
        course=str(course) if course else None,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/stored/results/{race_id}",
    tags=["races"],
    summary="race_id で保存済み結果を取得",
    description="JSONL などの保存先に蓄積済みのレース結果を race_id で取得します。",
)
async def get_stored_result(
    race_id: RaceIdPath,
    storage: ResultStorage = Depends(get_result_storage),
):
    record = storage.get_result(race_id)
    if record is None:
        raise LookupError(f"stored result not found for race_id={race_id}")
    return record


@app.post(
    "/bet-records",
    tags=["analysis"],
    summary="å®Ÿè²·ã„è¨˜éŒ²ã‚’ä¿å­˜",
    response_model=BetRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_bet_record(
    request: BetRecordCreateRequest,
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    return store.create_bet_record(request)


@app.get(
    "/bet-records",
    tags=["analysis"],
    summary="å®Ÿè²·ã„è¨˜éŒ²ã‚’æ¤œç´¢",
    response_model=BetRecordPage,
)
async def list_bet_records(
    from_date: date | None = Query(default=None, description="å¯¾è±¡ãƒ¬ãƒ¼ã‚¹ã®é–‹å‚¬é–‹å§‹æ—¥"),
    to_date: date | None = Query(default=None, description="å¯¾è±¡ãƒ¬ãƒ¼ã‚¹ã®é–‹å‚¬çµ‚äº†æ—¥"),
    race_id: str | None = Query(default=None, pattern=BET_RECORD_RACE_ID_PATTERN, description="race_id ã§çµžã‚Šè¾¼ã¿"),
    course: CourseCode | None = Query(default=None, description="é–‹å‚¬å ´ã‚³ãƒ¼ãƒ‰ã§çµžã‚Šè¾¼ã¿"),
    theory_version: str | None = Query(default=None, description="theory_version ã§çµžã‚Šè¾¼ã¿"),
    decision_source: str | None = Query(default=None, description="agent, manual, agent_plus_manual"),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT, description="è¿”å´ä»¶æ•°ã€‚æœ€å¤§500ä»¶ã€‚"),
    offset: int = Query(default=0, ge=0, description="å…ˆé ­ã‹ã‚‰ã‚¹ã‚­ãƒƒãƒ—ã™ã‚‹ä»¶æ•°ã€‚"),
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    return store.list_bet_records(
        from_date=from_date,
        to_date=to_date,
        race_id=race_id,
        course=str(course) if course else None,
        theory_version=theory_version,
        decision_source=decision_source,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/bet-records/{bet_record_id}",
    tags=["analysis"],
    summary="å®Ÿè²·ã„è¨˜éŒ²ã‚’å–å¾—",
    response_model=BetRecord,
)
async def get_bet_record(
    bet_record_id: str,
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    return store.get_bet_record(bet_record_id)


@app.post(
    "/bet-records/{bet_record_id}/settle",
    tags=["analysis"],
    summary="å®Ÿè²·ã„è¨˜éŒ²ã‚’ç²¾ç®—",
    response_model=BetRecordSettlement,
)
async def settle_bet_record(
    bet_record_id: str,
    store: AnalysisSQLiteStore = Depends(get_analysis_store),
):
    return store.settle_bet_record(bet_record_id)


@app.post(
    "/jobs/result-collections",
    tags=["jobs"],
    summary="結果収集 job を作成",
    description="過去結果の収集を非同期 job として開始します。",
    response_model=ResultCollectionJobCreated,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_result_collection_job(
    request: ResultCollectionJobRequest,
    background_tasks: BackgroundTasks,
    svc: JraService = Depends(get_service),
    registry: ResultCollectionJobRegistry = Depends(get_result_collection_job_registry),
):
    storage = request.storage or _default_result_storage_kind()
    output = request.output or _default_result_storage_path()
    job = registry.create_job(request, storage=storage, output=output)
    background_tasks.add_task(registry.run_job, job.job_id, svc, build_result_storage)
    return ResultCollectionJobCreated(job_id=job.job_id, status=job.status)


@app.get(
    "/jobs/result-collections",
    tags=["jobs"],
    summary="結果収集 job 一覧を取得",
    response_model=ResultCollectionJobPage,
)
async def list_result_collection_jobs(
    registry: ResultCollectionJobRegistry = Depends(get_result_collection_job_registry),
):
    return registry.list_jobs()


@app.get(
    "/jobs/result-collections/{job_id}",
    tags=["jobs"],
    summary="結果収集 job 詳細を取得",
    response_model=ResultCollectionJobSummary,
)
async def get_result_collection_job(
    job_id: str,
    registry: ResultCollectionJobRegistry = Depends(get_result_collection_job_registry),
):
    return registry.get_job(job_id)


def _extract_race_no(race_number: str | None) -> int | None:
    if not race_number:
        return None
    digits = "".join(char for char in race_number if char.isdigit())
    if not digits:
        return None
    return int(digits)


def _parse_query_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def _to_course_code(course: str | None) -> CourseCode | None:
    if course is None:
        return None
    try:
        return CourseCode(course)
    except ValueError:
        return None


def _matches_race_keyword(race, keyword: str | None) -> bool:
    if keyword is None:
        return True
    fields = [
        race.race_id,
        race.race_number or "",
        race.name,
        race.course or "",
    ]
    return any(keyword in field.casefold() for field in fields)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    schemas["ApiError"] = ApiError.model_json_schema(ref_template="#/components/schemas/{model}")
    schemas["ApiErrorResponse"] = ApiErrorResponse.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


mcp = FastApiMCP(
    app,
    name="JRA Race MCP",
    description=(
        "JRAの開催、出馬表、オッズ、結果、予想材料を取得する読み取り専用MCPサーバーです。"
        " 日本語の開催場名や券種は、最初にnormalize_race_inputでAPI用コードへ変換してください。"
        " 外部サイトへの負荷を抑えるため、通常はrefresh=falseを使用してください。"
    ),
    include_operations=MCP_OPERATION_IDS,
)
mcp.mount_http(mount_path="/mcp")
