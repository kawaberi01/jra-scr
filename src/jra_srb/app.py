from __future__ import annotations

from datetime import date

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi_mcp import FastApiMCP

from .errors import JraApiError
from .provider import ProviderError
from .service import JraService

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
        {"name": "mcp", "description": "FastAPI API を公開する MCP HTTP 入口"},
    ],
)
service = JraService()


def get_service() -> JraService:
    return service


@app.exception_handler(JraApiError)
async def handle_jra_api_error(_: Request, exc: JraApiError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(LookupError)
async def handle_lookup_error(_: Request, exc: LookupError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ProviderError)
async def handle_provider_error(_: Request, exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/health", tags=["health"], summary="ヘルスチェック", description="API プロセスが起動しているか確認します。")
async def health() -> dict[str, str]:
    return {"status": "ok"}


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
    course: str | None = Query(
        default=None,
        description="開催地コードを指定します。例: nakayama, hanshin",
        examples=["nakayama"],
    ),
    svc: JraService = Depends(get_service),
):
    return await svc.get_races(date_, course=course)


@app.get(
    "/meetings/{date_}/{course}",
    tags=["meetings"],
    summary="開催一覧を取得",
    description="開催日と開催地を指定して、その開催の 1R から 12R の一覧を取得します。",
)
async def get_meeting(
    date_: date,
    course: str,
    svc: JraService = Depends(get_service),
):
    return await svc.get_meeting(date_, course)


@app.get(
    "/races/{race_id}/card",
    tags=["races"],
    summary="race_id で出馬表を取得",
    description="race_id を指定して出馬表を取得します。主に既存の race_id ベース導線です。",
)
async def get_race_card(race_id: str, svc: JraService = Depends(get_service)):
    return await svc.get_race_card(race_id)


@app.get(
    "/meetings/{date_}/{course}/races/{race_no}/card",
    tags=["meetings"],
    summary="開催日・開催地・レース番号で出馬表を取得",
    description="開催日、開催地、レース番号を指定して、そのレースの出馬表を取得します。",
)
async def get_race_card_by_number(
    date_: date,
    course: str,
    race_no: int,
    svc: JraService = Depends(get_service),
):
    return await svc.get_race_card_by_number(date_, course, race_no)


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
    race_id: str,
    bet_type: str | None = Query(
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
    parsed = [item.strip() for item in bet_types.split(",")] if bet_types else None
    parsed_combination = [item.strip() for item in combination.split(",")] if combination else None
    return await svc.get_race_odds(
        race_id,
        bet_types=parsed,
        bet_type=bet_type,
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
    course: str,
    race_no: int,
    bet_type: str = Query(
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
    return await svc.get_race_odds_by_number(date_, course, race_no, bet_type, parsed_combination, refresh)


@app.get(
    "/races/{race_id}/result",
    tags=["races"],
    summary="race_id で結果を取得",
    description="race_id を指定して結果と払戻を取得します。",
)
async def get_race_result(race_id: str, svc: JraService = Depends(get_service)):
    return await svc.get_race_result(race_id)


@app.get(
    "/meetings/{date_}/{course}/races/{race_no}/result",
    tags=["meetings"],
    summary="開催日・開催地・レース番号で結果を取得",
    description="開催日、開催地、レース番号から結果と払戻を取得します。",
)
async def get_race_result_by_number(
    date_: date,
    course: str,
    race_no: int,
    svc: JraService = Depends(get_service),
):
    return await svc.get_race_result_by_number(date_, course, race_no)


mcp = FastApiMCP(app)
mcp.mount_http(mount_path="/mcp")
