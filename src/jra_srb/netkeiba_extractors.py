from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from .models import NetkeibaResultEntry, OddsEntry, PayoutEntry


NETKEIBA_ODDS_TYPE_MAP = {
    "1": ("win", 1, False),
    "2": ("place", 1, True),
    "3": ("bracket_quinella", 2, False),
    "4": ("quinella", 2, False),
    "5": ("wide", 2, True),
    "6": ("exacta", 2, False),
    "7": ("trio", 3, False),
    "8": ("trifecta", 3, False),
}

NETKEIBA_PAYOUT_CLASS_MAP = {
    "Tansho": "win",
    "Fukusho": "place",
    "Wakuren": "bracket_quinella",
    "Umaren": "quinella",
    "Wide": "wide",
    "Umatan": "exacta",
    "Fuku3": "trio",
    "Tan3": "trifecta",
}


def parse_netkeiba_race_result(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    race_name = _text(soup.select_one(".Race_Name"))
    metadata = _parse_race_metadata(soup)
    results = [_parse_result_row(row) for row in soup.select("#All_Result_Table tr") if "Header" not in row.get("class", [])]
    results = [entry for entry in results if entry is not None]
    payouts = _parse_payouts(soup)
    return {
        "race_name": race_name,
        **metadata,
        "results": results,
        "payouts": payouts,
        "corner_passages": _parse_corner_passages(soup),
    }


def parse_netkeiba_odds_payload(content: str) -> dict[str, list[OddsEntry]]:
    payload = _load_json_or_jsonp(content)
    data = payload.get("data") or {}
    odds = data.get("odds") or {}
    parsed: dict[str, list[OddsEntry]] = {}
    for raw_type, rows in odds.items():
        type_info = NETKEIBA_ODDS_TYPE_MAP.get(str(raw_type))
        if type_info is None or not isinstance(rows, dict):
            continue
        bet_type, leg_count, has_range = type_info
        entries = [_parse_odds_row(bet_type, leg_count, has_range, row) for row in rows.values()]
        parsed[bet_type] = [entry for entry in entries if entry is not None]
    return parsed


def _parse_race_metadata(soup: BeautifulSoup) -> dict[str, str | None]:
    meta_text = _attr(soup.select_one("meta[name='description']"), "content")
    race_data = _text(soup.select_one(".Race_Data")) or ""
    date_text = None
    course = None
    race_no = None
    if meta_text:
        match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+([^0-9\s]+)(\d{1,2})R", meta_text)
        if match:
            date_text = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
            course = match.group(4)
            race_no = match.group(5)

    surface = None
    surface_node = soup.select_one(".Race_Data .Turf, .Race_Data .Dirt")
    if surface_node is not None:
        surface = _text(surface_node)
    distance_match = re.search(r"(\d{3,4})m", race_data)
    direction_match = re.search(r"\(([^)]+)\)", race_data)
    weather_node = soup.select_one(".Race_Data .WeatherData")
    track_node = soup.select_one(".Race_Data .Item03")
    return {
        "date": date_text,
        "course": course,
        "race_no": race_no,
        "surface": surface,
        "distance": distance_match.group(1) if distance_match else None,
        "direction": direction_match.group(1).replace("\xa0", " ") if direction_match else None,
        "weather": _clean_weather(_text(weather_node)),
        "track_condition": _text(track_node),
    }


def _parse_result_row(row: Tag) -> NetkeibaResultEntry | None:
    rank = _digits(_text(row.select_one(".Result_Num .Rank")) or _text(row.select_one(".Result_Num")))
    horse_name = _text(row.select_one(".Horse_Info .Horse_Name a")) or _text(row.select_one(".Horse_Info .Horse_Name"))
    if rank is None or horse_name is None:
        return None
    nums = [_text(node.select_one("div")) or _text(node) for node in row.select("td.Num")]
    detail_left = [_clean(line) for line in _text_lines(row.select_one(".Horse_Info_Detail .Detail_Left")) if _clean(line)]
    detail_right = [_clean(line) for line in _text_lines(row.select_one(".Horse_Info_Detail .Detail_Right")) if _clean(line)]
    horse_weight, horse_weight_diff = _parse_horse_weight(next((item for item in detail_left if "kg" in item), None))
    jockey, weight_carried = _parse_jockey_weight(detail_right[0] if detail_right else None)
    time_node = row.select_one("td.Time")
    time_lines = [_clean(line) for line in _text_lines(time_node) if _clean(line)]
    finish_time = time_lines[0] if time_lines else None
    margin = time_lines[1] if len(time_lines) >= 2 and not time_lines[1].startswith("(") else None
    final_3f = next((line.strip("()") for line in time_lines if line.startswith("(")), None)
    odds_text = _text(row.select_one("td.Odds dt"))
    popularity_text = _text(row.select_one("td.Odds dd"))
    return NetkeibaResultEntry(
        rank=rank,
        frame_no=nums[0] if len(nums) >= 1 else None,
        horse_no=nums[1] if len(nums) >= 2 else None,
        horse_name=horse_name,
        sex_age=detail_left[0] if detail_left else None,
        weight_carried=weight_carried,
        jockey=jockey,
        trainer=detail_right[1] if len(detail_right) >= 2 else None,
        horse_weight=horse_weight,
        horse_weight_diff=horse_weight_diff,
        finish_time=finish_time,
        margin=margin,
        final_3f=final_3f,
        win_odds=_strip_unit(odds_text, "倍"),
        popularity=_digits(popularity_text),
    )


def _parse_payouts(soup: BeautifulSoup) -> list[PayoutEntry]:
    payouts: list[PayoutEntry] = []
    for row in soup.select(".Payout_Detail_Table tr"):
        bet_type = _payout_bet_type(row)
        if bet_type is None:
            continue
        combinations = _payout_combinations(row.select_one("td.Result"))
        payout_values = _split_lines(row.select_one("td.Payout"))
        popularity_values = [_digits(item) for item in _split_lines(row.select_one("td.Ninki"))]
        for index, combination in enumerate(combinations):
            payout = payout_values[index] if index < len(payout_values) else None
            if payout is None:
                continue
            payouts.append(
                PayoutEntry(
                    bet_type=bet_type,
                    combination=combination,
                    payout=_strip_unit(payout, "円") or payout,
                    popularity=popularity_values[index] if index < len(popularity_values) else None,
                )
            )
    return payouts


def _payout_bet_type(row: Tag) -> str | None:
    classes = set(row.get("class", []))
    for class_name, bet_type in NETKEIBA_PAYOUT_CLASS_MAP.items():
        if class_name in classes:
            return bet_type
    return None


def _payout_combinations(node: Tag | None) -> list[str]:
    if node is None:
        return []
    groups = []
    for group in node.select("ul"):
        values = [_text(span) for span in group.select("span")]
        values = [value for value in values if value]
        if values:
            groups.append("-".join(values))
    if groups:
        return groups
    values = [_text(span) for span in node.select("span")]
    return [value for value in values if value]


def _parse_corner_passages(soup: BeautifulSoup) -> list[str]:
    passages = []
    for table in soup.select(".Result_Box_01 table, .Corner_Num"):
        text = _text(table)
        if text and text not in passages:
            passages.append(text)
    return passages


def _parse_odds_row(bet_type: str, leg_count: int, has_range: bool, row: Any) -> OddsEntry | None:
    if not isinstance(row, list) or len(row) < 4:
        return None
    combination = _split_encoded_combination(str(row[3]), leg_count)
    if not combination:
        return None
    if has_range:
        odds = None
        odds_min = str(row[0])
        odds_max = str(row[1])
    else:
        odds = str(row[0])
        odds_min = None
        odds_max = None
    return OddsEntry(
        bet_type=bet_type,
        combination=combination,
        odds=odds,
        odds_min=odds_min,
        odds_max=odds_max,
        popularity=str(row[2]) if row[2] not in (None, "") else None,
    )


def _split_encoded_combination(value: str, leg_count: int) -> list[str]:
    if leg_count == 1:
        return [str(int(value))]
    if len(value) != leg_count * 2 or not value.isdigit():
        return []
    return [str(int(value[index : index + 2])) for index in range(0, len(value), 2)]


def _load_json_or_jsonp(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1]
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("netkeiba odds payload must be a JSON object")
    return payload


def _parse_horse_weight(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    match = re.search(r"(\d+)kg(?:\(([-+]?\d+)\))?", value)
    if match is None:
        return value, None
    return match.group(1), match.group(2)


def _parse_jockey_weight(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    match = re.match(r"(.+?)\s+(\d+(?:\.\d+)?)$", value)
    if match is None:
        return value, None
    return _clean(match.group(1)), match.group(2)


def _split_lines(node: Tag | None) -> list[str]:
    if node is None:
        return []
    return [_clean(item) for item in node.get_text("\n", strip=True).splitlines() if _clean(item)]


def _text_lines(node: Tag | None) -> list[str]:
    if node is None:
        return []
    return node.get_text("\n", strip=True).splitlines()


def _text(node: Tag | None) -> str | None:
    if node is None:
        return None
    text = _clean(node.get_text(" ", strip=True))
    return text or None


def _attr(node: Tag | None, name: str) -> str | None:
    if node is None:
        return None
    value = node.get(name)
    return str(value) if value is not None else None


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _digits(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    return digits or None


def _strip_unit(value: str | None, unit: str) -> str | None:
    if value is None:
        return None
    return _clean(value).replace(unit, "")


def _clean_weather(value: str | None) -> str | None:
    if value is None:
        return None
    return re.sub(r"\s+", "", value)
