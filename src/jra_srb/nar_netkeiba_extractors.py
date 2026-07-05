from __future__ import annotations

from datetime import date
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

from .models import MeetingRace, NetkeibaResultEntry, NarCalendarEntry, OddsEntry, PayoutEntry, Runner


NAR_ODDS_TYPE_TO_BET_TYPE = {
    "b1": ("win", "place"),
    "b3": ("bracket_quinella",),
    "b4": ("quinella",),
    "b5": ("wide",),
    "b6": ("exacta",),
    "b7": ("trio",),
    "b8": ("trifecta",),
}

NAR_BET_TYPE_TO_ODDS_TYPE = {
    "win": "b1",
    "place": "b1",
    "bracket_quinella": "b3",
    "quinella": "b4",
    "wide": "b5",
    "exacta": "b6",
    "trio": "b7",
    "trifecta": "b8",
}

NAR_PAYOUT_CLASS_MAP = {
    "Tansho": "win",
    "Fukusho": "place",
    "Wakuren": "bracket_quinella",
    "Umaren": "quinella",
    "Wide": "wide",
    "Wakutan": "bracket_exacta",
    "Umatan": "exacta",
    "Fuku3": "trio",
    "Tan3": "trifecta",
}

NAR_COURSE_MAP = {
    "門別": "monbetsu",
    "盛岡": "morioka",
    "水沢": "mizusawa",
    "浦和": "urawa",
    "船橋": "funabashi",
    "大井": "oi",
    "川崎": "kawasaki",
    "金沢": "kanazawa",
    "笠松": "kasamatsu",
    "名古屋": "nagoya",
    "園田": "sonoda",
    "姫路": "himeji",
    "高知": "kochi",
    "佐賀": "saga",
    "帯広ば": "obihiro",
    "帯広(ば)": "obihiro",
}


def normalize_nar_course_key(value: str) -> str:
    normalized = _clean(value).replace("競馬場", "")
    if normalized in NAR_COURSE_MAP:
        return NAR_COURSE_MAP[normalized]
    reverse = {course_key: course_name for course_name, course_key in NAR_COURSE_MAP.items()}
    if normalized in reverse:
        return normalized
    raise LookupError(f"unsupported nar course={value}")


def parse_nar_calendar(html: str) -> list[NarCalendarEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries: list[NarCalendarEntry] = []
    for cell in soup.select(".Calendar_Table td.RaceCellBox.HaveData"):
        for block in cell.select(".kaisai_1"):
            link = block.select_one("a[href*='kaisai_id=']")
            href = _attr(link, "href")
            if not href:
                continue
            query = parse_qs(urlparse(href).query)
            kaisai_date = _first(query.get("kaisai_date"))
            kaisai_id = _first(query.get("kaisai_id"))
            course_name = _text(block.select_one(".JyoName"))
            if not (kaisai_date and kaisai_id and course_name):
                continue
            tags = [
                _clean(tag.get_text())
                for tag in block.select(".Dart_calendar_Tag01, .Dart_calendar_Tag02")
                if _clean(tag.get_text())
            ]
            entries.append(
                NarCalendarEntry(
                    date=date.fromisoformat(f"{kaisai_date[:4]}-{kaisai_date[4:6]}-{kaisai_date[6:8]}"),
                    course=course_name,
                    course_key=normalize_nar_course_key(course_name),
                    kaisai_id=kaisai_id,
                    race_list_url=href,
                    tags=tags,
                )
            )
    return entries


def parse_nar_meeting(html: str, kaisai_id: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    target = _find_meeting_block(soup, kaisai_id)
    header = target.select_one("dt.RaceList_DataHeader")
    title = _text(header.select_one(".RaceList_DataTitle")) or ""
    title = re.sub(r"\s+", " ", title)
    course_match = re.search(r"(門別|盛岡|水沢|浦和|船橋|大井|川崎|金沢|笠松|名古屋|園田|姫路|高知|佐賀|帯広\(ば\)|帯広ば)", title)
    course = course_match.group(1) if course_match else None
    races = []
    for item in target.select("li.RaceList_DataItem"):
        anchor = item.select_one("a[href*='race_id=']")
        href = _attr(anchor, "href") or ""
        query = parse_qs(urlparse(href).query)
        race_id = _first(query.get("race_id"))
        if not race_id:
            continue
        race_no = _digits(_text(item.select_one(".Race_Num")))
        races.append(
            MeetingRace(
                race_no=int(race_no) if race_no else 0,
                race_id=race_id,
                race_name=_text(item.select_one(".ItemTitle")),
                start_time=_first(_text(item.select_one(".RaceData")).split()) if _text(item.select_one(".RaceData")) else None,
            )
        )
    return {"course": course, "races": races}


def parse_nar_race_card(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    race_data = _parse_race_data01(_text(soup.select_one(".RaceData01")) or "")
    return {
        "race_name": _text(soup.select_one(".RaceName")),
        "course": _active_course_name(soup),
        "distance": race_data["distance"],
        "surface": race_data["surface"],
        "start_time": race_data["start_time"],
        "runners": [_parse_card_row(row) for row in soup.select("div.RaceTableArea.Shutuba_HorseList table.ShutubaTable tr.HorseList")],
    }


def parse_nar_race_result(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    race_data = _parse_race_data01(_text(soup.select_one(".RaceData01")) or "")
    race_date, course, race_no = _parse_description_meta(_attr(soup.select_one("meta[name='description']"), "content"))
    results = []
    for row in soup.select("table.RaceCommon_Table tbody tr"):
        entry = _parse_result_row(row)
        if entry is not None:
            results.append(entry)
    return {
        "race_name": _text(soup.select_one(".RaceName")),
        "date": race_date,
        "course": course or _active_course_name(soup),
        "race_no": race_no,
        "surface": race_data["surface"],
        "distance": race_data["distance"],
        "direction": race_data["direction"],
        "weather": race_data["weather"],
        "track_condition": race_data["track_condition"],
        "results": results,
        "payouts": _parse_payouts(soup),
        "corner_passages": _parse_corner_passages(soup),
    }


def parse_nar_odds(html: str) -> dict[str, list[OddsEntry]]:
    soup = BeautifulSoup(html, "html.parser")
    odds_type = _odds_type_from_html(soup)
    if odds_type == "b1":
        return _parse_single_odds_page(soup)
    bet_types = NAR_ODDS_TYPE_TO_BET_TYPE.get(odds_type, ())
    if not bet_types:
        return {}
    bet_type = bet_types[0]
    entries = []
    for node in soup.select("td.Odds[cart-item]"):
        cart_item = node.get("cart-item")
        if not cart_item:
            continue
        combination = cart_item.split("_c0_")[-1].split("_")
        odds_text = _clean(node.get_text(" ", strip=True))
        odds_text = odds_text.replace(" ", "")
        if bet_type == "wide":
            odds_min, odds_max = _split_odds_range(odds_text)
            entries.append(
                OddsEntry(
                    bet_type=bet_type,
                    combination=combination,
                    odds_min=odds_min,
                    odds_max=odds_max,
                )
            )
            continue
        entries.append(
            OddsEntry(
                bet_type=bet_type,
                combination=combination,
                odds=odds_text,
            )
        )
    return {bet_type: entries}


def _find_meeting_block(soup: BeautifulSoup, kaisai_id: str) -> Tag:
    for block in soup.select("dl.RaceList_DataList"):
        payback_link = block.select_one(f"a[href*='kaisai_id={kaisai_id}']")
        if payback_link is not None:
            return block
        first_race_link = block.select_one("li.RaceList_DataItem a[href*='race_id=']")
        href = _attr(first_race_link, "href") or ""
        if kaisai_id and f"race_id={kaisai_id}" in href:
            return block
    raise LookupError(f"nar meeting block not found for kaisai_id={kaisai_id}")


def _parse_card_row(row: Tag) -> Runner:
    horse_weight, horse_weight_diff = _parse_weight_cell(row.select_one("td.Weight"))
    return Runner(
        frame_no=_digits(_text(row.select_one("td[class^='Waku']"))),
        horse_no=_digits(_text(row.select_one("td[class^='Umaban']"))),
        horse_name=_text(row.select_one(".HorseName")),
        sex_age=_text(row.select_one(".Age")),
        weight_carried=_clean(_text(row.select_one("td.Txt_C"))),
        jockey=_text(row.select_one(".Jockey a")) or _text(row.select_one(".Jockey")),
        trainer=_text(row.select_one(".Trainer a")) or _text(row.select_one(".Trainer")),
        horse_weight=horse_weight,
        horse_weight_diff=horse_weight_diff,
        odds=_first(_text_lines(row.select_one("td.Popular.Txt_R"))),
        popularity=_digits(_text(row.select_one(".Popular.Txt_C span"))),
    )


def _parse_result_row(row: Tag) -> NetkeibaResultEntry | None:
    rank = _digits(_text(row.select_one(".Result_Num .Rank")))
    horse_name = _text(row.select_one(".Horse_Name a")) or _text(row.select_one(".Horse_Name"))
    if rank is None or horse_name is None:
        return None
    horse_weight, horse_weight_diff = _parse_weight_cell(row.select_one("td.Weight"))
    return NetkeibaResultEntry(
        rank=rank,
        frame_no=_digits(_text(row.select("td.Num div")[0]) if len(row.select("td.Num div")) >= 1 else None),
        horse_no=_digits(_text(row.select("td.Num div")[1]) if len(row.select("td.Num div")) >= 2 else None),
        horse_name=horse_name,
        sex_age=_text(row.select_one(".Detail_Left")),
        weight_carried=_text(row.select_one(".JockeyWeight")),
        jockey=_text(row.select_one(".Jockey a")) or _text(row.select_one(".Jockey")),
        trainer=_text(row.select_one(".Trainer a")) or _text(row.select_one(".Trainer")),
        horse_weight=horse_weight,
        horse_weight_diff=horse_weight_diff,
        finish_time=_text(row.select_one("td.Time .RaceTime")),
        margin=_nth_text(row.select("td.Time .RaceTime"), 1),
        final_3f=_clean(_text(row.select_one("td.Time.BgBlue02, td.Time.BgYellow, td.Time.BgRed, td.Time.BgGreen"))),
        win_odds=_clean(_text(row.select_one(".Odds_Ninki"))),
        popularity=_digits(_text(row.select_one(".OddsPeople"))),
    )


def _parse_payouts(soup: BeautifulSoup) -> list[PayoutEntry]:
    payouts: list[PayoutEntry] = []
    for row in soup.select(".Payout_Detail_Table tr"):
        bet_type = None
        for class_name, normalized in NAR_PAYOUT_CLASS_MAP.items():
            if class_name in row.get("class", []):
                bet_type = normalized
                break
        if bet_type is None:
            continue
        combinations = _payout_combinations(row.select_one("td.Result"))
        payout_values = _split_lines(row.select_one("td.Payout"))
        popularity_values = [_digits(value) for value in _split_lines(row.select_one("td.Ninki"))]
        for index, combination in enumerate(combinations):
            payout = payout_values[index] if index < len(payout_values) else None
            if payout is None:
                continue
            payouts.append(
                PayoutEntry(
                    bet_type=bet_type,
                    combination=combination,
                    payout=payout.replace("円", "").replace(",", ""),
                    popularity=popularity_values[index] if index < len(popularity_values) else None,
                )
            )
    return payouts


def _parse_corner_passages(soup: BeautifulSoup) -> list[str]:
    passages = []
    for row in soup.select("table.Corner_Num td"):
        text = _clean(row.get_text(" ", strip=True))
        if text:
            passages.append(text)
    return passages


def _parse_single_odds_page(soup: BeautifulSoup) -> dict[str, list[OddsEntry]]:
    result: dict[str, list[OddsEntry]] = {}
    for section in soup.select(".RaceOdds_HorseList"):
        label = _text(section.select_one(".Type_Sec h2"))
        if label == "単勝":
            bet_type = "win"
        elif label == "複勝":
            bet_type = "place"
        else:
            continue
        entries = []
        for row in section.select("table.RaceOdds_HorseList_Table tr")[1:]:
            cells = row.select("td")
            if len(cells) < 5:
                continue
            combination = [_digits(_text(cells[1])) or _clean(cells[1].get_text())]
            odds_text = _clean(cells[4].get_text(" ", strip=True)).replace(" ", "")
            if bet_type == "place":
                odds_min, odds_max = _split_odds_range(odds_text)
                entries.append(OddsEntry(bet_type=bet_type, combination=combination, odds_min=odds_min, odds_max=odds_max))
            else:
                entries.append(OddsEntry(bet_type=bet_type, combination=combination, odds=odds_text))
        result[bet_type] = entries
    return result


def _parse_race_data01(text: str) -> dict[str, str | None]:
    start_time_match = re.search(r"(\d{1,2}:\d{2})発走", text)
    course_match = re.search(r"/\s*([ダ芝])(\d{3,4})m\s*\(([^)]+)\)", text)
    weather_match = re.search(r"天候:([^\s/]+)", text)
    track_match = re.search(r"馬場:([^\s/]+)", text)
    surface = None
    distance = None
    direction = None
    if course_match:
        surface = "ダート" if course_match.group(1) == "ダ" else "芝"
        distance = course_match.group(2)
        direction = course_match.group(3)
    return {
        "start_time": start_time_match.group(1) if start_time_match else None,
        "surface": surface,
        "distance": distance,
        "direction": direction,
        "weather": weather_match.group(1) if weather_match else None,
        "track_condition": track_match.group(1) if track_match else None,
    }


def _parse_description_meta(value: str | None) -> tuple[str | None, str | None, str | None]:
    if not value:
        return None, None, None
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+([^\d]+?)(\d{1,2})R", value)
    if not match:
        return None, None, None
    race_date = f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return race_date, match.group(4).strip(), match.group(5)


def _active_course_name(soup: BeautifulSoup) -> str | None:
    return _text(soup.select_one(".RaceKaisaiWrap li.Active a"))


def _parse_weight_cell(node: Tag | None) -> tuple[str | None, str | None]:
    text = _clean(node.get_text(" ", strip=True)) if node is not None else ""
    match = re.search(r"(\d+)\s*\(([-+]?\d+)\)", text)
    if match:
        return match.group(1), match.group(2)
    digits = _digits(text)
    return digits, None


def _odds_type_from_html(soup: BeautifulSoup) -> str:
    canonical = _attr(soup.select_one("link[rel='canonical']"), "href") or ""
    query = parse_qs(urlparse(canonical).query)
    odds_type = _first(query.get("type"))
    if odds_type:
        return odds_type
    for link in soup.select(".RaceInfo_Odds_Menu02 a[href*='type=']"):
        href = _attr(link, "href") or ""
        match = re.search(r"type=(b\d+)", href)
        if match and "Active" in (link.parent.get("class", []) if link.parent else []):
            return match.group(1)
    raise LookupError("nar odds type not found")


def _split_odds_range(value: str) -> tuple[str | None, str | None]:
    parts = [part.strip() for part in value.split("-")]
    if len(parts) == 2:
        return parts[0], parts[1]
    return value or None, None


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
    return [value for value in [_text(span) for span in node.select("span")] if value]


def _split_lines(node: Tag | None) -> list[str]:
    if node is None:
        return []
    return [_clean(item).replace(",", "") for item in node.get_text("\n", strip=True).splitlines() if _clean(item)]


def _text_lines(node: Tag | None) -> list[str]:
    if node is None:
        return []
    return [_clean(line) for line in node.get_text("\n", strip=True).splitlines() if _clean(line)]


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


def _digits(value: str | None) -> str | None:
    digits = re.sub(r"\D", "", value or "")
    return digits or None


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _first(values: list[str] | None) -> str | None:
    if not values:
        return None
    return values[0]


def _nth_text(nodes: list[Tag], index: int) -> str | None:
    if index >= len(nodes):
        return None
    return _clean(nodes[index].get_text(" ", strip=True)) or None
