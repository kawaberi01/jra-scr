from __future__ import annotations

import re

from .errors import BadRequestError
from .models import BetType, CourseCode, NormalizedRaceInput


COURSE_ALIASES: dict[str, CourseCode] = {
    "sapporo": CourseCode.sapporo,
    "札幌": CourseCode.sapporo,
    "hakodate": CourseCode.hakodate,
    "函館": CourseCode.hakodate,
    "fukushima": CourseCode.fukushima,
    "福島": CourseCode.fukushima,
    "niigata": CourseCode.niigata,
    "新潟": CourseCode.niigata,
    "tokyo": CourseCode.tokyo,
    "東京": CourseCode.tokyo,
    "nakayama": CourseCode.nakayama,
    "中山": CourseCode.nakayama,
    "chukyo": CourseCode.chukyo,
    "中京": CourseCode.chukyo,
    "kyoto": CourseCode.kyoto,
    "京都": CourseCode.kyoto,
    "hanshin": CourseCode.hanshin,
    "阪神": CourseCode.hanshin,
    "kokura": CourseCode.kokura,
    "小倉": CourseCode.kokura,
}

BET_TYPE_ALIASES: dict[str, BetType] = {
    "win": BetType.win,
    "単勝": BetType.win,
    "複勝": BetType.win,
    "quinella": BetType.quinella,
    "馬連": BetType.quinella,
    "wide": BetType.wide,
    "ワイド": BetType.wide,
    "exacta": BetType.exacta,
    "馬単": BetType.exacta,
    "trio": BetType.trio,
    "3連複": BetType.trio,
    "三連複": BetType.trio,
    "trifecta": BetType.trifecta,
    "3連単": BetType.trifecta,
    "三連単": BetType.trifecta,
}


def normalize_course(value: str) -> CourseCode:
    key = value.strip()
    course = COURSE_ALIASES.get(key) or COURSE_ALIASES.get(key.lower())
    if course is None:
        raise BadRequestError(f"unsupported course={value}")
    return course


def normalize_bet_type(value: str) -> BetType:
    key = value.strip()
    bet_type = BET_TYPE_ALIASES.get(key) or BET_TYPE_ALIASES.get(key.lower())
    if bet_type is None:
        raise BadRequestError(f"unsupported bet_type={value}")
    return bet_type


def normalize_race_no(value: str | int) -> int:
    if isinstance(value, int):
        race_no = value
    else:
        match = re.search(r"(\d{1,2})\s*(?:R|r|レース)?", value.strip())
        if match is None:
            raise BadRequestError(f"unsupported race={value}")
        race_no = int(match.group(1))
    if race_no < 1 or race_no > 12:
        raise BadRequestError(f"race_no must be between 1 and 12: {race_no}")
    return race_no


def normalize_combination(value: str | None) -> list[str]:
    if value is None or not value.strip():
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def normalize_race_input(
    course: str,
    race: str | int,
    bet_type: str | None = None,
    combination: str | None = None,
) -> NormalizedRaceInput:
    return NormalizedRaceInput(
        course=normalize_course(course),
        race_no=normalize_race_no(race),
        bet_type=normalize_bet_type(bet_type) if bet_type else None,
        combination=normalize_combination(combination),
    )


def parse_bet_types(value: str | None) -> list[BetType] | None:
    if value is None:
        return None
    parsed = [normalize_bet_type(item) for item in value.split(",") if item.strip()]
    return parsed
