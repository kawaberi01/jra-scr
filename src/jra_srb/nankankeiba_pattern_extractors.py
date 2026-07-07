from __future__ import annotations

from datetime import date
import re

from bs4 import BeautifulSoup
from bs4.element import Tag

from .models import NankankeibaPatternCategoryEntry, NankankeibaPatternRate


NANKANKEIBA_PATTERN_COURSE_CODES = {
    "kawasaki": "21",
    "川崎": "21",
}

NANKANKEIBA_PATTERN_CATEGORIES = {
    "pattern_kis": "騎手",
    "pattern_uma": "出走馬",
    "pattern_cho": "調教師",
    "pattern_kis_cho": "騎手×調教師",
}

NANKANKEIBA_PATTERN_PERIODS = {
    "01": "01",
    "lifetime": "01",
    "生涯": "01",
}

RATE_KEYS = [
    "lifetime",
    "urawa",
    "funabashi",
    "oi",
    "kawasaki",
    "short",
    "medium",
    "long",
    "popularity_1",
    "popularity_2",
    "popularity_3",
    "popularity_4_or_more",
]

DEFAULT_RATE_INDEXES = {key: index for key, index in zip(RATE_KEYS, range(5, 17))}
PATTERN_UMA_RATE_INDEXES = {
    "lifetime": 5,
    "urawa": 7,
    "funabashi": 8,
    "oi": 9,
    "kawasaki": 10,
    "short": 11,
    "medium": 12,
    "long": 13,
    "popularity_1": 14,
    "popularity_2": 15,
    "popularity_3": 16,
    "popularity_4_or_more": 17,
}
PATTERN_UMA_TRACK_CONDITION_INDEXES = {
    "good": 18,
    "slightly_heavy": 19,
    "heavy": 20,
    "bad": 21,
}
PATTERN_UMA_SEASON_INDEXES = {
    "jan_to_mar": 22,
    "apr_to_jun": 23,
    "jul_to_sep": 24,
    "oct_to_dec": 25,
}
PATTERN_UMA_FRAME_GROUP_INDEXES = {
    "frame_1_2": 26,
    "frame_3_4": 27,
    "frame_5_6": 28,
    "frame_7_8": 29,
}
PATTERN_UMA_DATA_COLUMN_TO_KEY = {
    "data-column-rate": ("rates", "lifetime"),
    "data-column-jockey": ("jockey_riding_rate", None),
    "data-column-urawa": ("rates", "urawa"),
    "data-column-funabashi": ("rates", "funabashi"),
    "data-column-oi": ("rates", "oi"),
    "data-column-kawasaki": ("rates", "kawasaki"),
    "data-column-short": ("rates", "short"),
    "data-column-medium": ("rates", "medium"),
    "data-column-long": ("rates", "long"),
    "data-column-1popular": ("rates", "popularity_1"),
    "data-column-2popular": ("rates", "popularity_2"),
    "data-column-3popular": ("rates", "popularity_3"),
    "data-column-4popularless": ("rates", "popularity_4_or_more"),
    "data-column-good": ("track_condition_rates", "good"),
    "data-column-slightlyheavy": ("track_condition_rates", "slightly_heavy"),
    "data-column-heavy": ("track_condition_rates", "heavy"),
    "data-column-bad": ("track_condition_rates", "bad"),
    "data-column-m1m3": ("season_rates", "jan_to_mar"),
    "data-column-m4m6": ("season_rates", "apr_to_jun"),
    "data-column-m7m9": ("season_rates", "jul_to_sep"),
    "data-column-m10m12": ("season_rates", "oct_to_dec"),
    "data-column-12frame": ("frame_group_rates", "frame_1_2"),
    "data-column-34frame": ("frame_group_rates", "frame_3_4"),
    "data-column-56frame": ("frame_group_rates", "frame_5_6"),
    "data-column-78frame": ("frame_group_rates", "frame_7_8"),
}


def normalize_pattern_course(value: str) -> str:
    if value in NANKANKEIBA_PATTERN_COURSE_CODES:
        return value if value == "kawasaki" else "kawasaki"
    raise LookupError(f"unsupported nankankeiba course={value}")


def normalize_pattern_period(value: str) -> str:
    try:
        return NANKANKEIBA_PATTERN_PERIODS[value]
    except KeyError as exc:
        raise LookupError(f"unsupported nankankeiba pattern period={value}") from exc


def normalize_pattern_category(value: str) -> str:
    if value in NANKANKEIBA_PATTERN_CATEGORIES:
        return value
    raise LookupError(f"unsupported nankankeiba pattern category={value}")


def build_pattern_race_id(
    target_date: date,
    course: str,
    meeting_no: int,
    meeting_day: int,
    race_no: int,
    period: str,
) -> str:
    course_key = normalize_pattern_course(course)
    period_code = normalize_pattern_period(period)
    return (
        f"{target_date:%Y%m%d}"
        f"{NANKANKEIBA_PATTERN_COURSE_CODES[course_key]}"
        f"{meeting_no:02d}{meeting_day:02d}{race_no:02d}{period_code}"
    )


def build_pattern_url_path(category: str, race_id: str) -> str:
    category_key = normalize_pattern_category(category)
    return f"/{category_key}/{race_id}.do"


def parse_pattern_rate(value: str | None) -> NankankeibaPatternRate:
    text = _clean(value)
    if not text:
        return NankankeibaPatternRate()
    match = re.search(r"([-+]?\d+(?:\.\d+)?)%\s*\((\d+)\s*/\s*(\d+)\)", text)
    if not match:
        return NankankeibaPatternRate()
    return NankankeibaPatternRate(
        rate=float(match.group(1)),
        wins=int(match.group(2)),
        starts=int(match.group(3)),
    )


def parse_pattern_category_page(html: str, race_id: str, category: str) -> list[NankankeibaPatternCategoryEntry]:
    category_key = normalize_pattern_category(category)
    soup = BeautifulSoup(html, "html.parser")
    table = _find_pattern_table(soup)
    entries = []
    for row in table.select("tr.win_pattern_data"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 17:
            continue
        horse_name = _horse_name(cells[2])
        if not horse_name:
            continue
        jockey, weight_carried, trainer = _parse_connection_cell(cells[3])
        entry = NankankeibaPatternCategoryEntry(
            category=category_key,
            frame_no=_text(cells[0]),
            horse_no=_text(cells[1]) or "",
            horse_name=horse_name,
            jockey=jockey,
            weight_carried=weight_carried,
            trainer=trainer,
            win_odds=_text(cells[4]),
            rates=_empty_rate_group(_rate_keys_for_category(category_key)),
        )
        if category_key == "pattern_uma":
            _populate_pattern_uma_rates(entry, cells)
        else:
            entry.rates = _parse_rate_group(cells, DEFAULT_RATE_INDEXES)
        entries.append(entry)
    return entries


def _rate_keys_for_category(category: str) -> list[str]:
    if category == "pattern_uma":
        return list(PATTERN_UMA_RATE_INDEXES)
    return list(DEFAULT_RATE_INDEXES)


def _parse_rate_group(cells: list[Tag], indexes: dict[str, int]) -> dict[str, NankankeibaPatternRate]:
    return {key: _parse_rate_cell(cells, index) for key, index in indexes.items()}


def _parse_rate_cell(cells: list[Tag], index: int) -> NankankeibaPatternRate:
    if index >= len(cells):
        return NankankeibaPatternRate()
    return parse_pattern_rate(cells[index].get_text(" ", strip=True))


def _empty_rate_group(keys: list[str]) -> dict[str, NankankeibaPatternRate]:
    return {key: NankankeibaPatternRate() for key in keys}


def _populate_pattern_uma_rates(entry: NankankeibaPatternCategoryEntry, cells: list[Tag]) -> None:
    entry.track_condition_rates = _empty_rate_group(list(PATTERN_UMA_TRACK_CONDITION_INDEXES))
    entry.season_rates = _empty_rate_group(list(PATTERN_UMA_SEASON_INDEXES))
    entry.frame_group_rates = _empty_rate_group(list(PATTERN_UMA_FRAME_GROUP_INDEXES))
    for cell in cells[5:]:
        for attr_name, (group_name, key) in PATTERN_UMA_DATA_COLUMN_TO_KEY.items():
            if attr_name not in cell.attrs:
                continue
            parsed = parse_pattern_rate(cell.get_text(" ", strip=True))
            if group_name == "jockey_riding_rate":
                entry.jockey_riding_rate = parsed
            else:
                getattr(entry, group_name)[key] = parsed
            break


def _find_pattern_table(soup: BeautifulSoup) -> Tag:
    for table in soup.select("table.nk23_c-table13__table"):
        if table.select("tr.win_pattern_data"):
            return table
    raise LookupError("nankankeiba pattern table not found")


def _horse_name(cell: Tag) -> str | None:
    values = list(cell.stripped_strings)
    return values[1] if len(values) >= 2 else _text(cell)


def _parse_connection_cell(cell: Tag) -> tuple[str | None, str | None, str | None]:
    values = list(cell.stripped_strings)
    jockey = values[0] if values else None
    weight_index = next((index for index, value in enumerate(values) if re.search(r"\d+(?:\.\d+)?", value)), None)
    weight_carried = values[weight_index] if weight_index is not None else None
    trainer = values[weight_index + 1] if weight_index is not None and weight_index + 1 < len(values) else None
    return jockey, weight_carried, trainer


def _text(node: Tag | None) -> str | None:
    if node is None:
        return None
    text = _clean(node.get_text(" ", strip=True))
    return text or None


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
