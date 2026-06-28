from __future__ import annotations

from datetime import date
import logging
import os
import time
from pathlib import Path as FilePath
from typing import Annotated
from uuid import uuid4

from fastapi import BackgroundTasks, Depends, FastAPI, Path, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi_mcp import FastApiMCP

from .batch import JsonlRaceResultStorage, ResultStorage, SQLiteRaceResultStorage
from .cache import SQLiteTTLCache
from .errors import BadRequestError, JraApiError
from .jobs import ResultCollectionJobRegistry
from .models import (
    ApiError,
    ApiErrorResponse,
    BetType,
    CourseCode,
    RaceSearchItem,
    RaceSearchPage,
    ResultCollectionJobCreated,
    ResultCollectionJobPage,
    ResultCollectionJobRequest,
    ResultCollectionJobSummary,
    ResultStorageKind,
    StoredRaceResultPage,
)
from .normalization import normalize_race_input, parse_bet_types
from .provider import HttpProvider, ProviderError
from .service import JraService

logger = logging.getLogger(__name__)

RaceIdPath = Annotated[str, Path(pattern=r"^\d{12}$", description="12桁のrace_id")]
RaceNoPath = Annotated[int, Path(ge=1, le=12, description="1から12までのレース番号")]
DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 500

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
        {"name": "search", "description": "race_id を探すための検索 API"},
        {"name": "jobs", "description": "長時間処理を非同期に実行する job API"},
        {"name": "mcp", "description": "FastAPI API を公開する MCP HTTP 入口"},
    ],
)


def build_service() -> JraService:
    cache_path = os.environ.get("JRA_SRB_CACHE_PATH")
    provider = HttpProvider(
        max_concurrency=_env_int("JRA_SRB_UPSTREAM_MAX_CONCURRENCY", default=5, minimum=1),
        min_interval_seconds=_env_float("JRA_SRB_UPSTREAM_MIN_INTERVAL_SECONDS", default=0.0, minimum=0.0),
    )
    if cache_path:
        return JraService(provider=provider, cache=SQLiteTTLCache(cache_path))
    return JraService(provider=provider)


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
result_collection_jobs = ResultCollectionJobRegistry()


def get_service() -> JraService:
    return service


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


def build_result_storage(storage_kind: ResultStorageKind, output: str) -> ResultStorage:
    path = FilePath(output)
    if storage_kind == ResultStorageKind.jsonl:
        return JsonlRaceResultStorage(path)
    if storage_kind == ResultStorageKind.sqlite:
        return SQLiteRaceResultStorage(path)
    raise BadRequestError(f"unsupported results storage={storage_kind}")


def get_result_storage() -> ResultStorage:
    return build_result_storage(_default_result_storage_kind(), _default_result_storage_path())


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
    summary="日本語入力を API 用コードへ正規化",
    description="例: course=中山, race=11R, bet_type=3連単 を course=nakayama, race_no=11, bet_type=trifecta に変換します。",
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
    summary="開催日からレースを検索",
    description="開催日、開催場、キーワードから race_id を探します。",
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
    summary="開催一覧を取得",
    description="開催日と開催地を指定して、その開催の 1R から 12R の一覧を取得します。",
)
async def get_meeting(
    date_: date,
    course: CourseCode,
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
    summary="開催日・開催地・レース番号で出馬表を取得",
    description="開催日、開催地、レース番号を指定して、そのレースの出馬表を取得します。",
)
async def get_race_card_by_number(
    date_: date,
    course: CourseCode,
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
    summary="開催日・開催地・レース番号でオッズを取得",
    description=(
        "開催日、開催地、レース番号からオッズを取得します。"
        " `bet_type` は必須です。必要なら `combination` で一点に絞り込めます。"
    ),
)
async def get_race_odds_by_number(
    date_: date,
    course: CourseCode,
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
    summary="開催日・開催地・レース番号で結果を取得",
    description="開催日、開催地、レース番号から結果と払戻を取得します。",
)
async def get_race_result_by_number(
    date_: date,
    course: CourseCode,
    race_no: RaceNoPath,
    svc: JraService = Depends(get_service),
):
    return await svc.get_race_result_by_number(date_, str(course), race_no)


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


mcp = FastApiMCP(app)
mcp.mount_http(mount_path="/mcp")
