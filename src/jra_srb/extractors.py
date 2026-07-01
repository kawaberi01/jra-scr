from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from .models import MeetingRace, OddsEntry, PayoutEntry, RaceSummary, ResultEntry, Runner


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
    runners = []
    for row in _parse_collection(soup, config["runners"]):
        data = {name: _parse_field(row, rule) for name, rule in config["runner_fields"].items()}
        runners.append(Runner(**data))
    metadata["runners"] = runners
    return metadata


def parse_result_page_as_race_card(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("#race_result .race_result_unit > table") is None:
        raise ValueError("race result table not found")

    course_text = _select_text(soup, ".race_header .type .course")
    start_time = _select_text(soup, ".race_header .date_line .time strong")
    runners = []
    for row in soup.select("#race_result .race_result_unit > table tbody tr"):
        horse_no = _select_text(row, "td.num")
        horse_name = _select_text(row, "td.horse a") or _select_text(row, "td.horse")
        if horse_name is None:
            continue
        runners.append(
            Runner(
                frame_no=_select_text(row, "td.waku"),
                horse_no=horse_no,
                horse_name=horse_name,
                sex_age=_select_text(row, "td.age"),
                weight_carried=_select_text(row, "td.weight"),
                jockey=_select_text(row, "td.jockey"),
                trainer=_select_text(row, "td.trainer"),
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
    }


def _parse_jra_race_card(soup: BeautifulSoup) -> dict[str, Any]:
    course_text = _select_text(soup, ".race_header .type .course")
    start_time = _select_text(soup, ".race_header .date_line .time strong")
    runners = []
    for row in soup.select("table.basic.narrow-xy.mt20 tbody tr"):
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
        runners.append(
            Runner(
                horse_no=horse_no,
                horse_name=horse_name,
                sex_age=sex_age,
                weight_carried=weight_carried,
                jockey=jockey,
                trainer=_select_text(row, "td.horse p.trainer a"),
                odds=_select_text(row, "td.horse .odds strong"),
                popularity=popularity,
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
                start_time=_select_text(row, "td.time"),
                card_cname=decoded,
                odds_cname=odds_cname,
                result_cname=result_cname,
            )
        )
    return races


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
