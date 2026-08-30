from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from .models import (
    JraRecentRace,
    MeetingRace,
    OddsEntry,
    PayoutEntry,
    RaceSummary,
    ResultEntry,
    Runner,
    RunnerStatus,
    RunnerStatusSource,
)


_JRA_WEATHER = {
    "晴": "sunny",
    "曇": "cloudy",
    "雨": "rainy",
    "小雨": "light_rain",
    "雪": "snowy",
    "小雪": "light_snow",
}
_JRA_TRACK_CONDITION = {
    "良": "good",
    "稍重": "slightly_heavy",
    "重": "heavy",
    "不良": "bad",
}


def _select_text(node: Tag, selector: str | None, default: str | None = None) -> str | None:
    if selector is None:
        return default
    target = node.select_one(selector)
    if target is None:
        return default
    return target.get_text(" ", strip=True) or default


def _select_attr(node: Tag, selector: str, attr: str, default: str | None = None) -> str | None:
    target = node.select_one(selector)
    if target is None:
        return default
    return target.get(attr, default)


def _parse_race_grade(row: Tag) -> str | None:
    grade_node = row.select_one("td.race_name .grade_icon")
    if grade_node is None:
        return None
    image = grade_node.select_one("img[alt]")
    raw = image.get("alt") if image is not None else grade_node.get_text(" ", strip=True)
    if not raw:
        return None
    normalized = (
        str(raw).strip().upper()
        .replace("Ⅰ", "1")
        .replace("Ⅱ", "2")
        .replace("Ⅲ", "3")
        .replace("・", ".")
        .replace(" ", "")
    )
    if normalized in {"リステッド", "LISTED", "L"}:
        return "L"
    if normalized == "OP":
        return "OP"
    match = re.fullmatch(r"(G|JPN|J\.G)([123])", normalized)
    if match is None:
        return None
    prefix, number = match.groups()
    return {"G": "G", "JPN": "Jpn", "J.G": "J.G"}[prefix] + number


def _parse_collection(soup: BeautifulSoup, collection_cfg: dict[str, Any]) -> list[Tag]:
    root_selector = collection_cfg["selector"]
    if "item_selector" in collection_cfg:
        root = soup.select_one(root_selector)
        return root.select(collection_cfg["item_selector"]) if root else []
    return soup.select(root_selector)


def _parse_field(node: Tag, rule: dict[str, Any]) -> str | None:
    if "selector" in rule and "attr" in rule:
        return _select_attr(node, rule["selector"], rule["attr"], rule.get("default"))
    if "selector" in rule:
        return _select_text(node, rule["selector"], rule.get("default"))
    if "text" in rule:
        return rule["text"]
    return rule.get("default")


def _runner_status(row: Tag) -> tuple[RunnerStatus, RunnerStatusSource | None]:
    row_text = row.get_text(" ", strip=True)
    if any(marker in row_text for marker in ("出走取消", "競走除外", "取消", "除外")):
        return RunnerStatus.withdrawn, RunnerStatusSource.explicit
    return RunnerStatus.active, None


def _race_card_data_status(
    rows: list[Tag],
    runners: list[Runner],
    *,
    source_kind: str,
) -> dict[str, str | None]:
    horse_numbers = [runner.horse_no for runner in runners]
    complete = (
        bool(rows)
        and len(rows) == len(runners)
        and all(horse_numbers)
        and len(set(horse_numbers)) == len(horse_numbers)
    )
    if complete:
        runner_set = "complete"
        runner_set_reason = "all candidate rows were parsed with unique horse numbers"
    elif not rows:
        runner_set = "incomplete"
        runner_set_reason = "runner table or candidate rows were not found"
    else:
        runner_set = "incomplete"
        runner_set_reason = (
            "candidate rows were not fully parsed with unique horse numbers"
        )

    if any(runner.horse_weight or runner.horse_weight_diff for runner in runners):
        horse_weight = "available"
        horse_weight_reason = (
            "at least one runner has horse_weight or horse_weight_diff"
        )
    elif rows:
        horse_weight = "unpublished"
        horse_weight_reason = (
            "all parsed runners have null horse_weight before official publication"
        )
    else:
        horse_weight = "unavailable"
        horse_weight_reason = "runner table or candidate rows were not found"
    return {
        "horse_weight": horse_weight,
        "horse_weight_reason": horse_weight_reason,
        "runner_set": runner_set,
        "runner_set_reason": runner_set_reason,
        "source_kind": source_kind,
    }


def parse_race_summaries(html: str, config: dict[str, Any]) -> list[RaceSummary]:
    soup = BeautifulSoup(html, "html.parser")
    items = _parse_collection(soup, config["collection"])
    summaries: list[RaceSummary] = []
    for item in items:
        fields = {name: _parse_field(item, rule) for name, rule in config["fields"].items()}
        summaries.append(RaceSummary(**fields))
    return summaries


def parse_race_card(html: str, config: dict[str, Any]) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    metadata = {
        name: _select_text(soup, selector)
        for name, selector in config["metadata"].items()
    }
    if metadata.get("race_name") is None and soup.select_one(".race_header .race_name"):
        return _parse_jra_race_card(soup)
    rows = _parse_collection(soup, config["runners"])
    runners = []
    for row in rows:
        data = {name: _parse_field(row, rule) for name, rule in config["runner_fields"].items()}
        if not data.get("horse_name"):
            continue
        status, status_source = _runner_status(row)
        data["status"] = status
        data["status_source"] = status_source
        runners.append(Runner(**data))
    metadata["runners"] = runners
    metadata["data_status"] = _race_card_data_status(
        rows,
        runners,
        source_kind="pre_race_card",
    )
    return metadata


def parse_result_page_as_race_card(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("#race_result .race_result_unit > table") is None:
        raise ValueError("race result table not found")

    course_text = _select_text(soup, ".race_header .type .course")
    start_time = _select_text(soup, ".race_header .date_line .time strong")
    rows = soup.select("#race_result .race_result_unit > table tbody tr")
    runners = []
    for row in rows:
        horse_no = _select_text(row, "td.num")
        horse_name = _select_text(row, "td.horse a") or _select_text(row, "td.horse")
        if horse_name is None:
            continue
        status, status_source = _runner_status(row)
        runners.append(
            Runner(
                frame_no=_select_text(row, "td.waku"),
                horse_no=horse_no,
                horse_name=horse_name,
                sex_age=_select_text(row, "td.age"),
                weight_carried=_select_text(row, "td.weight"),
                jockey=_select_text(row, "td.jockey"),
                trainer=_select_text(row, "td.trainer"),
                status=status,
                status_source=status_source,
            )
        )

    distance = None
    surface = None
    if course_text:
        distance_match = re.search(r"(\d{1,4}(?:,\d{3})?)", course_text)
        distance = distance_match.group(1) if distance_match else None
        surface = "ダート" if "ダート" in course_text else "芝" if "芝" in course_text else None
    return {
        "race_name": _select_text(soup, ".race_header .race_name"),
        "course": course_text,
        "distance": distance,
        "surface": surface,
        "start_time": start_time,
        "runners": runners,
        "data_status": _race_card_data_status(
            rows,
            runners,
            source_kind="result_page",
        ),
    }


def _parse_horse_weight_text(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    compact = re.sub(r"\s+", "", value)
    match = re.search(r"(?P<weight>\d+)\s*kg(?:\((?P<diff>[+-]?\d+)\))?", compact, flags=re.IGNORECASE)
    if match is None:
        return None, None
    return match.group("weight"), match.group("diff")


def _parse_int(value: str | None) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else None


def _parse_float(value: str | None) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", value or "")
    return float(match.group()) if match else None


def _parse_final_3f(value: str | None) -> float | None:
    match = re.search(r"(?:3F\s*)?(\d{2}(?:\.\d+)?)", value or "", flags=re.IGNORECASE)
    return float(match.group(1)) if match else None


def _parse_jra_frame_no(row: Tag) -> str | None:
    image = row.select_one("td.waku img")
    if image is not None:
        for value in (image.get("alt"), image.get("src")):
            match = re.search(r"(?:枠|/waku/)([1-8])", str(value or ""))
            if match:
                return match.group(1)
    return str(_parse_int(_select_text(row, "td.waku"))) if _parse_int(_select_text(row, "td.waku")) else None


def _parse_jra_recent_date(value: str | None) -> date | None:
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", value or "")
    if match is None:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _parse_jra_recent_races(row: Tag) -> list[JraRecentRace]:
    races: list[JraRecentRace] = []
    for node in row.select("td.past")[:4]:
        href = _select_attr(node, ".race_line .name a", "href")
        distance_text = _select_text(node, ".info_line2 .dist")
        source_race_no = None
        if href and (match := re.search(r"(?P<race>\d{2})(?P<date>\d{8})/[0-9A-F]+$", href, re.IGNORECASE)):
            source_race_no = int(match.group("race"))
        corner_positions = [
            number
            for item in node.select(".info_line3 .corner_list li")
            if (number := _parse_int(item.get_text(" ", strip=True))) is not None
        ]
        source_url = f"https://www.jra.go.jp{href}" if href and href.startswith("/") else href
        races.append(
            JraRecentRace(
                source_date=_parse_jra_recent_date(_select_text(node, ".date_line .date")),
                source_course=_select_text(node, ".date_line .rc"),
                source_race_no=source_race_no,
                surface="芝" if distance_text and "芝" in distance_text else "ダート" if distance_text and "ダ" in distance_text else None,
                distance=_parse_int(distance_text),
                track_condition=_select_text(node, ".info_line2 .condition"),
                finish_rank=_parse_int(_select_text(node, ".place_line .place")),
                field_size=_parse_int(_select_text(node, ".place_line .num .max")),
                finish_time=_select_text(node, ".info_line2 .time"),
                final_3f=_parse_final_3f(_select_text(node, ".info_line3 .f3")),
                corner_positions=corner_positions,
                weight_carried=_parse_float(_select_text(node, ".info_line1 .weight")),
                jockey=_select_text(node, ".info_line1 .jockey"),
                popularity=_parse_int(_select_text(node, ".place_line .num .pop")),
                source="jra_official_card",
                source_url=source_url,
            )
        )
    return races


def _parse_jra_conditions(soup: BeautifulSoup, surface: str | None) -> dict[str, str | None]:
    weather_label = _select_text(soup, ".race_header .date_line .cell.baba .weather .txt")
    track_selector = ".turf .txt" if surface == "芝" else ".dirt .txt" if surface == "ダート" else None
    track_condition_label = _select_text(soup, f".race_header .date_line .cell.baba {track_selector}") if track_selector else None
    return {
        "surface_label": surface,
        "weather": _JRA_WEATHER.get(weather_label or ""),
        "weather_label": weather_label,
        "track_condition": _JRA_TRACK_CONDITION.get(track_condition_label or ""),
        "track_condition_label": track_condition_label,
    }


def _parse_jra_race_card(soup: BeautifulSoup) -> dict[str, Any]:
    course_text = _select_text(soup, ".race_header .type .course")
    start_time = _select_text(soup, ".race_header .date_line .time strong")
    distance = None
    surface = None
    if course_text:
        distance_match = re.search(r"(\d{1,4}(?:,\d{3})?)", course_text)
        distance = distance_match.group(1) if distance_match else None
        surface = "ダート" if "ダート" in course_text else "芝" if "芝" in course_text else None
    conditions = _parse_jra_conditions(soup, surface)
    runners = []
    rows = soup.select("table.basic.narrow-xy.mt20 tbody tr")
    for row in rows:
        horse_no = _select_text(row, "td.num")
        horse_name = _select_text(row, "td.horse .name a")
        if horse_name is None:
            continue
        jockey_text = _select_text(row, "td.jockey")
        sex_age = None
        weight_carried = None
        jockey = None
        if jockey_text:
            parts = [part.strip() for part in jockey_text.split() if part.strip()]
            if len(parts) >= 1:
                sex_age = parts[0]
            if len(parts) >= 3:
                weight_carried = f"{parts[1]} {parts[2]}".strip()
            if len(parts) >= 4:
                jockey = "".join(parts[3:])
        popularity = _select_text(row, "td.horse .pop_rank")
        if popularity:
            popularity = re.sub(r"\D", "", popularity) or None
        horse_weight, horse_weight_diff = _parse_horse_weight_text(
            _select_text(row, "td.horse .result_line .cell.weight")
        )
        status, status_source = _runner_status(row)
        runners.append(
            Runner(
                frame_no=_parse_jra_frame_no(row),
                horse_no=horse_no,
                horse_name=horse_name,
                sex_age=sex_age,
                weight_carried=weight_carried,
                jockey=jockey,
                trainer=_select_text(row, "td.horse p.trainer a"),
                horse_weight=horse_weight,
                horse_weight_diff=horse_weight_diff,
                odds=_select_text(row, "td.horse .odds strong"),
                popularity=popularity,
                official_recent_races=_parse_jra_recent_races(row),
                status=status,
                status_source=status_source,
            )
        )
    return {
        "race_name": _select_text(soup, ".race_header .race_name"),
        "course": course_text,
        "distance": distance,
        "surface": surface,
        **conditions,
        "start_time": start_time,
        "runners": runners,
        "data_status": _race_card_data_status(
            rows,
            runners,
            source_kind="pre_race_card",
        ),
    }


def parse_meeting_races(html: str) -> list[MeetingRace]:
    soup = BeautifulSoup(html, "html.parser")
    races: list[MeetingRace] = []
    for row in soup.select("table tbody tr"):
        race_link = row.select_one("th.race_num a[href*='CNAME=']")
        if race_link is None:
            continue
        href = race_link.get("href", "")
        cname_match = re.search(r"CNAME=(pw01dde\d+/\w+)", href)
        if cname_match is None:
            continue
        decoded = cname_match.group(1)
        parts = re.match(r"pw01dde\d{2}(?P<course>\d{2})\d{8}(?P<race>\d{2})(?P<date>\d{8})/", decoded)
        if parts is None:
            continue
        race_no = int(parts.group("race"))
        race_id = f"{parts.group('date')}{parts.group('course')}{parts.group('race')}"
        odds_cname = None
        odds_link = row.select_one("td.odds a[onclick*='doAction']")
        if odds_link is not None:
            odds_match = re.search(r"doAction\(\s*'[^']+'\s*,\s*'([^']+)'", odds_link.get("onclick", ""))
            if odds_match is not None:
                odds_cname = odds_match.group(1)
        result_cname = None
        result_link = row.select_one("td.result a[href*='CNAME=']")
        if result_link is not None:
            result_match = re.search(r"CNAME=([^&]+)", result_link.get("href", ""))
            if result_match is not None:
                result_cname = result_match.group(1)
        races.append(
            MeetingRace(
                race_no=race_no,
                race_id=race_id,
                race_name=_select_text(row, "td.race_name .stakes") or _select_text(row, "td.race_name div div"),
                race_grade=_parse_race_grade(row),
                start_time=_select_text(row, "td.time"),
                card_cname=decoded,
                odds_cname=odds_cname,
                result_cname=result_cname,
            )
        )
    return races


def parse_jra_meeting_coordinates(html: str) -> tuple[int, int] | None:
    """Extract meeting number/day from an official JRA race link in the meeting HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.select("a[href*='CNAME=pw01dde']"):
        match = re.search(
            r"CNAME=pw01dde\d{2}\d{2}\d{4}(?P<meeting>\d{2})(?P<day>\d{2})\d{2}\d{8}/",
            link.get("href", ""),
        )
        if match is not None:
            return int(match.group("meeting")), int(match.group("day"))
    return None


def parse_race_odds(html: str, config: dict[str, Any]) -> dict[str, list[OddsEntry]]:
    soup = BeautifulSoup(html, "html.parser")
    parsed: dict[str, list[OddsEntry]] = {}
    for bet_type, bet_cfg in config["bet_types"].items():
        entries = []
        for row in _parse_collection(soup, bet_cfg["collection"]):
            combination = []
            for selector in bet_cfg["combination_selectors"]:
                value = _select_text(row, selector)
                if value:
                    combination.append(value)
            odds = _select_text(row, bet_cfg["odds_selector"])
            if odds is None:
                continue
            entries.append(
                OddsEntry(
                    bet_type=bet_type,
                    combination=combination,
                    odds=odds,
                    popularity=_select_text(row, bet_cfg.get("popularity_selector")),
                )
            )
        parsed[bet_type] = entries
    return parsed


def parse_odds_navigation(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    mapping: dict[str, str] = {}
    prefixes = {
        "pw151": "win",
        "pw154": "quinella",
        "pw155": "wide",
        "pw156": "exacta",
        "pw157": "trio",
        "pw158": "trifecta",
    }
    for link in soup.select("ul.nav.pills a[onclick*='doAction']"):
        match = re.search(r"doAction\(\s*'[^']+'\s*,\s*'([^']+)'", link.get("onclick", ""))
        if match is None:
            continue
        cname = match.group(1)
        for prefix, bet_type in prefixes.items():
            if cname.startswith(prefix):
                mapping[bet_type] = cname
                break
    return mapping


def parse_result_month_navigation(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    mapping: dict[str, str] = {}
    for link in soup.select("a[onclick*='pw01skl10']"):
        onclick = link.get("onclick", "")
        match = re.search(r"(pw01skl10(?P<year>\d{4})(?P<month>\d{2})/\w+)", onclick)
        if match is None:
            continue
        mapping[f"{match.group('year')}-{match.group('month')}"] = match.group(1)
    return mapping


def parse_result_race_navigation(html: str) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for cname in re.findall(r"(pw01sde\d+/\w+)", html):
        race_no_match = re.search(r"pw01sde\d{2}\d{2}\d{4}\d{2}\d{2}(?P<race_no>\d{2})\d{8}/", cname)
        if race_no_match is None:
            continue
        mapping[int(race_no_match.group("race_no"))] = cname
    return mapping


def parse_jra_win_place_odds(html: str) -> list[OddsEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries: list[OddsEntry] = []
    for row in soup.select("table.tanpuku tbody tr"):
        horse_no = _select_text(row, "td.num")
        if horse_no is None:
            continue
        entries.append(
            OddsEntry(
                bet_type="win",
                combination=[horse_no],
                odds=_select_text(row, "td.odds_tan"),
                odds_min=_select_text(row, "td.odds_fuku .min"),
                odds_max=_select_text(row, "td.odds_fuku .max"),
            )
        )
    return entries


def parse_jra_trifecta_odds(html: str) -> list[OddsEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries: list[OddsEntry] = []
    for unit in soup.select(".tan3_unit"):
        first = _select_text(unit, "h4 .num")
        if first is None:
            continue
        for item in unit.select("ul.tan3_list > li"):
            second = _select_text(item, ".p_line + .p_line .num")
            if second is None:
                continue
            for row in item.select("table.tan3 tbody tr"):
                third = _select_text(row, "th")
                odds = _select_text(row, "td")
                if third is None or odds in (None, ""):
                    continue
                entries.append(
                    OddsEntry(
                        bet_type="trifecta",
                        combination=[first, second, third],
                        odds=odds,
                    )
                )
    return entries


def parse_jra_table_odds(html: str, bet_type: str, leg_count: int) -> list[OddsEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries: list[OddsEntry] = []
    for row in soup.select("#odds_list table.odds_table tbody tr"):
        combination = [node.get_text(" ", strip=True) for node in row.select(".num")]
        if len(combination) != leg_count:
            continue
        odds = _select_text(row, ".odds")
        if odds in (None, ""):
            continue
        entries.append(
            OddsEntry(
                bet_type=bet_type,
                combination=combination,
                odds=odds,
                popularity=_select_text(row, ".popularity"),
            )
        )
    if entries:
        return entries

    table_classes = {
        "quinella": "umaren",
        "wide": "wide",
        "exacta": "umatan",
        "trio": "fuku3",
    }
    table_class = table_classes.get(bet_type)
    if table_class is None:
        return entries

    for table in soup.select(f"#odds_list table.{table_class}"):
        caption = _select_text(table, "caption")
        if caption is None:
            continue
        caption_legs = [item.strip() for item in caption.split("-") if item.strip()]
        for row in table.select("tbody tr"):
            final_leg = _select_text(row, "th")
            combination = [*caption_legs, final_leg] if final_leg is not None else caption_legs
            if len(combination) != leg_count:
                continue
            odds_min = _select_text(row, ".min")
            odds_max = _select_text(row, ".max")
            odds = None if bet_type == "wide" else _select_text(row, "td")
            if bet_type == "wide" and odds_min in (None, "") and odds_max in (None, ""):
                continue
            if bet_type != "wide" and odds in (None, ""):
                continue
            entries.append(
                OddsEntry(
                    bet_type=bet_type,
                    combination=combination,
                    odds=odds,
                    odds_min=odds_min,
                    odds_max=odds_max,
                )
            )
    return entries


def parse_race_result(html: str, config: dict[str, Any]) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    race_name = _select_text(soup, config["race_name_selector"])
    if race_name is None and soup.select_one("li[id^='harai_'] .race_name"):
        raise ValueError("use parse_meeting_payout_result for meeting payout pages")
    if race_name is None and soup.select_one(".race_header .race_name"):
        return _parse_jra_race_result(soup)
    results = []
    for row in _parse_collection(soup, config["results"]):
        data = {name: _parse_field(row, rule) for name, rule in config["result_fields"].items()}
        results.append(ResultEntry(**data))
    payouts = []
    for row in _parse_collection(soup, config["payouts"]):
        data = {name: _parse_field(row, rule) for name, rule in config["payout_fields"].items()}
        payouts.append(PayoutEntry(**data))
    return {"race_name": race_name, "results": results, "payouts": payouts}


def _parse_jra_race_result(soup: BeautifulSoup) -> dict[str, Any]:
    results = []
    for row in soup.select("#race_result .race_result_unit > table tbody tr"):
        rank = _select_text(row, "td.place")
        horse_name = _select_text(row, "td.horse")
        if rank is None or horse_name is None:
            continue
        results.append(
            ResultEntry(
                rank=rank,
                horse_no=_select_text(row, "td.num"),
                horse_name=horse_name,
                jockey=_select_text(row, "td.jockey"),
                time=_select_text(row, "td.time"),
            )
        )

    bet_type_map = {
        "win": "単勝",
        "place": "複勝",
        "wakuren": "枠連",
        "wide": "ワイド",
        "umaren": "馬連",
        "umatan": "馬単",
        "trio": "3連複",
        "tierce": "3連単",
    }
    payouts = []
    for item in soup.select(".refund_area li"):
        css_classes = set(item.get("class", []))
        bet_type = next((bet_type_map[name] for name in bet_type_map if name in css_classes), None)
        if bet_type is None:
            continue
        for line in item.select("dd .line"):
            combination = _select_text(line, ".num")
            payout = _select_text(line, ".yen")
            if combination is None or payout is None:
                continue
            payouts.append(
                PayoutEntry(
                    bet_type=bet_type,
                    combination=combination,
                    payout=re.sub(r"[^\d,]", "", payout),
                    popularity=re.sub(r"\D", "", _select_text(line, ".pop") or "") or None,
                )
            )

    return {
        "race_name": _select_text(soup, ".race_header .race_name"),
        "results": results,
        "payouts": payouts,
    }


def parse_calendar_meetings(
    content: str,
    target_date: date,
    course_name_map: dict[str, str],
    race_count: int = 12,
) -> list[dict[str, Any]]:
    payload = json.loads(content)
    target_day = str(target_date.day)
    meetings: list[dict[str, Any]] = []
    seen: set[str] = set()

    for month_block in payload:
        for day_block in month_block.get("data", []):
            if day_block.get("date") != target_day:
                continue
            for info in day_block.get("info", []):
                for race in info.get("race", []):
                    meeting_name = race.get("name", "")
                    course = _resolve_course_from_calendar_name(meeting_name, course_name_map)
                    if course is None or course in seen:
                        continue
                    seen.add(course)
                    meetings.append(
                        {
                            "course": course,
                            "label": meeting_name,
                            "races": [
                                MeetingRace(
                                    race_no=race_no,
                                    race_id="",
                                )
                                for race_no in range(1, race_count + 1)
                            ],
                        }
                    )
    return meetings


def _resolve_course_from_calendar_name(name: str, course_name_map: dict[str, str]) -> str | None:
    for course, course_name in course_name_map.items():
        if course_name in name:
            return course
    return None


def parse_meeting_payout_result(html: str, race_no: int) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    block = soup.select_one(f"li#harai_{race_no}R")
    if block is None:
        raise LookupError(f"payout block not found for race_no={race_no}")
    results = []
    for row in block.select("table tbody tr"):
        rank = _select_text(row, "td.place")
        horse_name = _select_text(row, "td.horse")
        if rank is None or horse_name is None:
            continue
        results.append(
            ResultEntry(
                rank=rank,
                horse_no=_select_text(row, "td.num"),
                horse_name=horse_name,
                time=_select_text(row, "td.time"),
            )
        )
    payouts = []
    type_map = {
        "単勝": "単勝",
        "複勝": "複勝",
        "枠連": "枠連",
        "馬連": "馬連",
        "馬単": "馬単",
        "ワイド": "ワイド",
        "3連複": "3連複",
        "3連単": "3連単",
    }
    for item in block.select(".refund_unit li"):
        bet_type = _select_text(item, "dt")
        mapped = type_map.get(bet_type or "")
        if mapped is None:
            continue
        for line in item.select("dd .line"):
            combination = _select_text(line, ".num")
            payout = _select_text(line, ".yen")
            if combination is None or payout is None:
                continue
            payouts.append(
                PayoutEntry(
                    bet_type=mapped,
                    combination=combination,
                    payout=payout.replace("円", ""),
                    popularity=_select_text(line, ".pop"),
                )
            )
    return {
        "race_name": _select_text(block, ".race_title .race_name"),
        "results": results,
        "payouts": payouts,
    }
