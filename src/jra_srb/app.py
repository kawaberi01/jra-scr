from __future__ import annotations

from datetime import date

from fastapi import Depends, FastAPI, Query

from .service import JraService

app = FastAPI(title="jra-srb", version="0.1.0")
service = JraService()


def get_service() -> JraService:
    return service


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/races")
async def get_races(
    date_: date = Query(alias="date"),
    course: str | None = None,
    svc: JraService = Depends(get_service),
):
    return await svc.get_races(date_, course=course)


@app.get("/meetings/{date_}/{course}")
async def get_meeting(
    date_: date,
    course: str,
    svc: JraService = Depends(get_service),
):
    return await svc.get_meeting(date_, course)


@app.get("/races/{race_id}/card")
async def get_race_card(race_id: str, svc: JraService = Depends(get_service)):
    return await svc.get_race_card(race_id)


@app.get("/meetings/{date_}/{course}/races/{race_no}/card")
async def get_race_card_by_number(
    date_: date,
    course: str,
    race_no: int,
    svc: JraService = Depends(get_service),
):
    return await svc.get_race_card_by_number(date_, course, race_no)


@app.get("/races/{race_id}/odds")
async def get_race_odds(
    race_id: str,
    bet_type: str | None = None,
    bet_types: str | None = None,
    combination: str | None = None,
    refresh: bool = False,
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


@app.get("/meetings/{date_}/{course}/races/{race_no}/odds")
async def get_race_odds_by_number(
    date_: date,
    course: str,
    race_no: int,
    bet_type: str,
    combination: str | None = None,
    refresh: bool = False,
    svc: JraService = Depends(get_service),
):
    parsed_combination = [item.strip() for item in combination.split(",")] if combination else None
    return await svc.get_race_odds_by_number(date_, course, race_no, bet_type, parsed_combination, refresh)


@app.get("/races/{race_id}/result")
async def get_race_result(race_id: str, svc: JraService = Depends(get_service)):
    return await svc.get_race_result(race_id)


@app.get("/meetings/{date_}/{course}/races/{race_no}/result")
async def get_race_result_by_number(
    date_: date,
    course: str,
    race_no: int,
    svc: JraService = Depends(get_service),
):
    return await svc.get_race_result_by_number(date_, course, race_no)
