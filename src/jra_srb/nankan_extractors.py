from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import re
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from .models import (
    MeetingRace,
    NankanBestTimeRunner,
    NankanClosingSpeedRunner,
    NankanLeadingJockeyItem,
    NankanTrendBloodlineEntry,
    NankanTrendFrameEntry,
    NankanTrendPayoutSummary,
    NankanTrendPersonEntry,
    NankanTrendRunningStyleSummary,
    NankanTrendSummary,
    OddsEntry,
    PayoutEntry,
    ResultEntry,
    Runner,
    NankanStyleRecentRace,
)


NANKAN_COURSE_NAME_TO_CODE = {
    "浦和": "urawa",
    "船橋": "funabashi",
    "大井": "ohi",
    "川崎": "kawasaki",
}

NANKAN_PAYOUT_BET_TYPE_MAP = {
    "単勝": "win",
    "複勝": "place",
    "普通馬複": "quinella",
    "馬複": "quinella",
    "ワイド": "wide",
    "馬単": "exacta",
    "三連複": "trio",
    "三連単": "trifecta",
}

NANKAN_SURFACE_LABEL_TO_CODE = {
    "ダ": "dirt",
    "ダート": "dirt",
    "芝": "turf",
    "障": "obstacle",
    "障害": "obstacle",
}

NANKAN_TRACK_CONDITION_LABEL_TO_CODE = {
    "良": "good",
    "稍重": "slightly_heavy",
    "重": "heavy",
    "不良": "bad",
}

NANKAN_WEATHER_LABEL_TO_CODE = {
    "晴": "sunny",
    "曇": "cloudy",
    "雨": "rainy",
    "小雨": "light_rain",
    "雪": "snowy",
}


def parse_nankan_calendar_meeting_ids(html: str) -> list[str]:
    return sorted(set(re.findall(r"/program/(\d{14})\.do", html)))


def parse_nankan_meeting(html: str, target_date: date, course: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    conditions = _meeting_conditions(soup)
    races = []
    for link in soup.select("a[href*='/syousai/']"):
        href = str(link.get("href") or "")
        match = re.search(r"/syousai/(\d{16})\.do", href)
        if match is None:
            continue
        race_id = match.group(1)
        race_no = int(race_id[-2:])
        item = link.find_parent("li")
        text = _clean(item.get_text(" ", strip=True) if item is not None else link.get_text(" ", strip=True))
        race_meta = _race_meta_from_text(text)
        name = _clean(link.get_text(" ", strip=True))
        if name in {"結果", "変更"}:
            continue
        races.append(
            MeetingRace(
                race_no=race_no,
                race_id=race_id,
                race_name=name or None,
                start_time=race_meta["start_time"],
                surface=race_meta["surface"] or conditions["surface"],
                surface_label=race_meta["surface_label"] or conditions["surface_label"],
                distance=race_meta["distance"],
                weather=conditions["weather"],
                weather_label=conditions["weather_label"],
                track_condition=conditions["track_condition"],
                track_condition_label=conditions["track_condition_label"],
            )
        )
    unique = {race.race_id: race for race in races}
    return {
        "date": target_date,
        "course": str(course),
        "races": sorted(unique.values(), key=lambda race: race.race_no),
        **conditions,
    }


def parse_nankan_meeting_conditions(html: str) -> dict[str, str | None]:
    return _meeting_conditions(BeautifulSoup(html, "html.parser"))


def parse_nankan_race_card(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    title = _race_title(soup)
    table = _find_table_with_headers(soup, ["枠", "馬", "馬名"])
    runners = [_parse_runner_row(row) for row in table.select("tr") if _parse_runner_row(row) is not None] if table else []
    meta = _clean(_race_meta_text(soup) or title or soup.get_text(" ", strip=True))
    race_meta = _race_meta_from_text(meta)
    conditions = _meeting_conditions(soup)
    return {
        "race_name": _race_name_from_card_page(soup) or _race_name_from_title(title),
        "course": _course_from_text(meta),
        "distance": race_meta["distance"],
        "surface": race_meta["surface"] or conditions["surface"],
        "surface_label": race_meta["surface_label"] or conditions["surface_label"],
        "start_time": race_meta["start_time"],
        "weather": conditions["weather"],
        "weather_label": conditions["weather_label"],
        "track_condition": conditions["track_condition"],
        "track_condition_label": conditions["track_condition_label"],
        "runners": runners,
        "data_status": _race_card_data_status(table, runners),
    }


def parse_nankan_odds(html: str, bet_type: str) -> dict[str, list[OddsEntry]]:
    soup = BeautifulSoup(html, "html.parser")
    if _has_not_on_sale(soup):
        return {bet_type: []}
    if bet_type in {"win", "place"}:
        return _parse_win_place(soup, bet_type)
    if bet_type in {"quinella", "wide"}:
        tables = soup.select("table.nk23_c-table02__table")
        index = 0 if bet_type == "quinella" else 1
        return {bet_type: _parse_matrix_table(tables[index], bet_type, unordered=True) if len(tables) > index else []}
    if bet_type == "exacta":
        table = _first_matrix_table(soup)
        return {bet_type: _parse_matrix_table(table, bet_type, unordered=False) if table else []}
    if bet_type in {"trio", "trifecta"}:
        entries = []
        for table in soup.select("table.nk23_c-table02__table"):
            entries.extend(_parse_matrix_table(table, bet_type, unordered=(bet_type == "trio")))
        return {bet_type: entries}
    return {bet_type: []}


def parse_nankan_race_result(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    result_table = _find_result_table(soup)
    if result_table is None:
        raise LookupError("nankan result table not found")
    return {
        "race_name": _race_name_from_result_page(soup),
        "results": _parse_result_entries(result_table),
        "payouts": _parse_payout_entries(soup),
    }


def parse_nankan_meeting_trend(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one(".seiseki1") or soup
    race_count_completed = _trend_race_count_completed(root)
    if race_count_completed == 0 and "表示するレース傾向がありません" in _clean(root.get_text(" ", strip=True)):
        return {
            "updated_at": _trend_updated_at(soup),
            "race_count_completed": 0,
            "summary": NankanTrendSummary(),
        }
    return {
        "updated_at": _trend_updated_at(soup),
        "race_count_completed": race_count_completed,
        "summary": NankanTrendSummary(
            frame=_parse_trend_frames(root),
            running_style=_parse_trend_running_style(root),
            jockey=_parse_trend_people(root, "騎手傾向"),
            trainer=_parse_trend_people(root, "厩舎傾向"),
            sire=_parse_trend_bloodline(root, "血統傾向(父)"),
            broodmare_sire=_parse_trend_bloodline(root, "血統傾向(母父)"),
            payout=_parse_trend_payout(root),
        ),
    }


def parse_nankan_best_time(html: str, target_course: str | None = None, target_distance: int | None = None) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    runners: list[NankanBestTimeRunner] = []
    table = _best_table(soup, "タイム")
    if table is None:
        return {"runners": runners}
    for row in table.select("tr")[1:]:
        cells = row.find_all(["th", "td"], recursive=False)
        values = [_clean(cell.get_text(" ", strip=True)) for cell in cells]
        if len(values) < 8 or not values[1].isdigit():
            continue
        distance = _distance_int_from_text(values[7])
        course = _normalize_nankan_course_label(values[5])
        runners.append(
            NankanBestTimeRunner(
                horse_no=values[1],
                horse_name=values[2],
                best_time=values[4] if values[4] != "-" else None,
                best_time_rank=int(values[0]) if values[0].isdigit() else None,
                best_time_source_course=course,
                best_time_source_distance=distance,
                same_course_flag=(course == target_course) if course and target_course else None,
                same_distance_flag=(distance == target_distance) if distance and target_distance else None,
                track_condition=_normalize_track_condition(values[6]),
                horse_profile_id=_horse_profile_id_from_cells(cells),
            )
        )
    return {"runners": runners}


def parse_nankan_closing_speed(
    html: str, target_course: str | None = None, target_distance: int | None = None
) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    runners: list[NankanClosingSpeedRunner] = []
    table = _best_table(soup, "3F")
    if table is None:
        return {"runners": runners}
    for row in table.select("tr")[1:]:
        cells = row.find_all(["th", "td"], recursive=False)
        values = [_clean(cell.get_text(" ", strip=True)) for cell in cells]
        if len(values) < 8 or not values[1].isdigit():
            continue
        distance = _distance_int_from_text(values[7])
        course = _normalize_nankan_course_label(values[5])
        runners.append(
            NankanClosingSpeedRunner(
                horse_no=values[1],
                horse_name=values[2],
                best_closing_time=values[4] if values[4] != "-" else None,
                best_closing_rank=int(values[0]) if values[0].isdigit() else None,
                same_course_flag=(course == target_course) if course and target_course else None,
                same_distance_flag=(distance == target_distance) if distance and target_distance else None,
                track_condition=_normalize_track_condition(values[6]),
                horse_profile_id=_horse_profile_id_from_cells(cells),
            )
        )
    return {"runners": runners}


def parse_nankan_horse_recent_races(html: str) -> list[NankanStyleRecentRace]:
    soup = BeautifulSoup(html, "html.parser")
    table = _horse_results_table(soup)
    if table is None:
        return []
    rows = table.select("tr")
    if not rows:
        return []
    headers = [_clean(cell.get_text(" ", strip=True)) for cell in rows[0].find_all(["th", "td"], recursive=False)]
    indexes = {
        "date": _header_index(headers, ["年月日", "年 月日"]),
        "course": _header_index(headers, ["場名"]),
        "race_no": _header_index(headers, ["R"]),
        "distance": _header_index(headers, ["距離"]),
        "track": _header_index(headers, ["天候 馬場", "天候馬場"]),
        "finish": _header_index(headers, ["着/頭数"]),
        "corner": _header_index(headers, ["コーナー 通過順", "通過順"]),
    }
    if indexes["corner"] is None:
        return []
    recent: list[NankanStyleRecentRace] = []
    for row in rows[1:]:
        cells = [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"], recursive=False)]
        corner_positions = _corner_positions(_cell(cells, indexes["corner"]) or "")
        if not corner_positions:
            continue
        finish_rank, field_size = _finish_and_field_size(_cell(cells, indexes["finish"]) or "")
        recent.append(
            NankanStyleRecentRace(
                source_date=_nankan_short_date(_cell(cells, indexes["date"]) or ""),
                course=_normalize_nankan_course_label((_cell(cells, indexes["course"]) or "").replace("☆", "")),
                race_no=_number_from_text(_cell(cells, indexes["race_no"]) or ""),
                corner_positions=corner_positions,
                field_size=field_size,
                distance=_distance_int_from_text(_cell(cells, indexes["distance"]) or ""),
                track_condition=_track_condition_from_weather_track(_cell(cells, indexes["track"]) or ""),
                finish_rank=finish_rank,
            )
        )
    return recent


def parse_nankan_leading_jockeys(html: str) -> list[NankanLeadingJockeyItem]:
    soup = BeautifulSoup(html, "html.parser")
    table = _find_leading_jockey_table(soup)
    if table is None:
        return []
    rows = table.select("tr")
    if not rows:
        return []
    headers = [_clean(cell.get_text(" ", strip=True)) for cell in rows[0].find_all(["th", "td"], recursive=False)]
    index = _leading_jockey_header_index(headers)
    items: list[NankanLeadingJockeyItem] = []
    for row in rows[1:]:
        cells = row.find_all(["th", "td"], recursive=False)
        values = [_clean(cell.get_text(" ", strip=True)) for cell in cells]
        name = _value_by_header(values, index, "jockey_name")
        if not name:
            continue
        items.append(
            NankanLeadingJockeyItem(
                rank=_int_value(_value_by_header(values, index, "rank")),
                jockey_code=_jockey_code_from_cells(cells),
                jockey_name=name,
                rides=_int_value(_value_by_header(values, index, "rides")),
                wins=_int_value(_value_by_header(values, index, "wins")),
                seconds=_int_value(_value_by_header(values, index, "seconds")),
                thirds=_int_value(_value_by_header(values, index, "thirds")),
                win_rate=_float_value(_value_by_header(values, index, "win_rate")),
                quinella_rate=_float_value(_value_by_header(values, index, "quinella_rate")),
                trio_rate=_float_value(_value_by_header(values, index, "trio_rate")),
            )
        )
    return items


def _trend_updated_at(soup: BeautifulSoup) -> datetime | None:
    text = _clean(soup.get_text(" ", strip=True))
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})現在", text)
    if match is None:
        return None
    year, month, day, hour, minute = (int(value) for value in match.groups())
    return datetime(year, month, day, hour, minute, tzinfo=timezone(timedelta(hours=9)))


def _trend_race_count_completed(root: Tag | BeautifulSoup) -> int:
    text = _clean(root.get_text(" ", strip=True))
    match = re.search(r"(\d+)レース終了時", text)
    return int(match.group(1)) if match else 0


def _trend_item_by_heading(root: Tag | BeautifulSoup, heading: str) -> Tag | None:
    for item in root.select("li.nk23_c-list08__item"):
        title = _clean(item.select_one(".nk23_c-list08__col1").get_text(" ", strip=True)) if item.select_one(".nk23_c-list08__col1") else ""
        if heading in title:
            return item
    return None


def _parse_trend_frames(root: Tag | BeautifulSoup) -> list[NankanTrendFrameEntry]:
    item = _trend_item_by_heading(root, "枠番傾向")
    if item is None:
        return []
    scope = item.select_one("p.nk23_c-list08__col.is-colorGroup.pc") or item
    entries: list[NankanTrendFrameEntry] = []
    for node in scope.select("span.nk23_c-list08__colornum"):
        frame_no_node = node.select_one(".nk23_c-list08__colorItem")
        count_node = node.select_one(".numbottom")
        frame_no = _clean(frame_no_node.get_text(" ", strip=True)) if frame_no_node else ""
        count = _number_from_text(_clean(count_node.get_text(" ", strip=True)) if count_node else "")
        if frame_no and count is not None:
            entries.append(NankanTrendFrameEntry(frame_no=frame_no, top3_count=count))
    return entries


def _parse_trend_running_style(root: Tag | BeautifulSoup) -> NankanTrendRunningStyleSummary:
    item = _trend_item_by_heading(root, "脚質傾向")
    if item is None:
        return NankanTrendRunningStyleSummary()
    values = _trend_rows(item)
    return NankanTrendRunningStyleSummary(
        front_group_top3_count=values.get("前方集団"),
        back_group_top3_count=values.get("後方集団"),
    )


def _parse_trend_people(root: Tag | BeautifulSoup, heading: str) -> list[NankanTrendPersonEntry]:
    item = _trend_item_by_heading(root, heading)
    if item is None:
        return []
    entries: list[NankanTrendPersonEntry] = []
    for title, count in _trend_rows(item).items():
        match = re.match(r"(.+?)\((.*?)\)$", title)
        name = match.group(1).strip() if match else title
        affiliation = match.group(2).strip() if match else None
        entries.append(NankanTrendPersonEntry(name=name, affiliation=affiliation, top3_count=count))
    return entries


def _parse_trend_bloodline(root: Tag | BeautifulSoup, heading: str) -> list[NankanTrendBloodlineEntry]:
    item = _trend_item_by_heading(root, heading)
    if item is None:
        return []
    return [NankanTrendBloodlineEntry(name=name, top3_count=count) for name, count in _trend_rows(item).items()]


def _parse_trend_payout(root: Tag | BeautifulSoup) -> NankanTrendPayoutSummary:
    item = _trend_item_by_heading(root, "払戻金傾向")
    if item is None:
        return NankanTrendPayoutSummary()
    text = _clean(item.get_text(" ", strip=True))
    match = re.search(r"([\d,]+)円\((\d+)R\)", text)
    if match is None:
        return NankanTrendPayoutSummary()
    return NankanTrendPayoutSummary(
        trifecta_max_payout=int(match.group(1).replace(",", "")),
        trifecta_max_payout_race_no=int(match.group(2)),
    )


def _trend_rows(item: Tag) -> dict[str, int]:
    values: dict[str, int] = {}
    for row in item.select("p.nk23_c-list08__colrow"):
        title_node = row.select_one(".nk23_c-list08__coltitle")
        count_node = row.select_one(".nk23_c-list08__coltext")
        title = _clean(title_node.get_text(" ", strip=True)) if title_node else ""
        count = _number_from_text(_clean(count_node.get_text(" ", strip=True)) if count_node else "")
        if title and count is not None:
            values[title] = count
    return values


def _number_from_text(value: str) -> int | None:
    digits = "".join(re.findall(r"\d+", value))
    return int(digits) if digits else None


def _best_table(soup: BeautifulSoup, value_header: str) -> Tag | None:
    for table in soup.select("table"):
        headers = [_clean(cell.get_text(" ", strip=True)) for cell in table.select("tr:first-child th, tr:first-child td")]
        if "順位" in headers and "馬番" in headers and "馬名" in headers and value_header in headers:
            return table
    return None


def _horse_profile_id_from_cells(cells: list[Tag]) -> str | None:
    for cell in cells:
        link = cell.select_one("a[href*='/uma_info/']")
        if link is None:
            continue
        match = re.search(r"/uma_info/(\d+)\.do", str(link.get("href") or ""))
        if match:
            return match.group(1)
    return None


def _horse_results_table(soup: BeautifulSoup) -> Tag | None:
    for table in soup.select("table"):
        text = _clean(table.get_text(" ", strip=True))
        if "コーナー 通過順" in text and "着/頭数" in text:
            return table
    return None


def _normalize_nankan_course_label(value: str | None) -> str | None:
    mapping = {
        "浦和": "urawa",
        "船橋": "funabashi",
        "大井": "ohi",
        "川崎": "kawasaki",
    }
    cleaned = _clean(value).replace("☆", "")
    return mapping.get(cleaned) or _course_from_text(cleaned)


def _distance_int_from_text(value: str | None) -> int | None:
    digits = "".join(re.findall(r"\d+", value or ""))
    return int(digits) if digits else None


def _nankan_short_date(value: str) -> date | None:
    match = re.search(r"(\d{2})/(\d{2})/(\d{2})", value)
    if match:
        year, month, day = (int(item) for item in match.groups())
        return date(2000 + year, month, day)
    match = re.search(r"(\d{4})\s+(\d{2})/(\d{2})", value)
    if match:
        year, month, day = (int(item) for item in match.groups())
        return date(year, month, day)
    return None


def _finish_and_field_size(value: str) -> tuple[int | None, int | None]:
    match = re.search(r"(\d+)\s*着\s*/\s*(\d+)\s*頭", value)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def _corner_positions(value: str) -> list[int]:
    return [int(item) for item in re.findall(r"\d+", value)]


def _track_condition_from_weather_track(value: str) -> str | None:
    label = value.split("/")[-1].strip() if "/" in value else value.strip()
    mapping = {
        "良": "good",
        "稍重": "slightly_heavy",
        "重": "heavy",
        "不良": "bad",
    }
    return mapping.get(label) or _normalize_track_condition(label)


def _parse_result_entries(table: Tag) -> list[ResultEntry]:
    rows = table.select("tr")
    if not rows:
        return []
    header_cells = [_clean(cell.get_text(" ", strip=True)) for cell in rows[0].find_all(["th", "td"], recursive=False)]
    indexes = {
        "rank": _header_index(header_cells, ["着順", "着"]),
        "horse_no": _header_index(header_cells, ["馬番"]),
        "horse_name": _header_index(header_cells, ["馬名"]),
        "jockey": _header_index(header_cells, ["騎手"]),
        "time": _header_index(header_cells, ["タイム", "時計"]),
    }
    if indexes["rank"] is None or indexes["horse_name"] is None:
        indexes = {"rank": 0, "horse_no": 1, "horse_name": 2, "jockey": 3, "time": 4}

    entries: list[ResultEntry] = []
    for row in rows[1:]:
        cells = [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"], recursive=False)]
        rank = _cell(cells, indexes["rank"])
        horse_name = _cell(cells, indexes["horse_name"])
        if not rank or not horse_name or not re.search(r"\d", rank):
            continue
        entries.append(
            ResultEntry(
                rank=rank,
                horse_no=_cell(cells, indexes["horse_no"]),
                horse_name=horse_name,
                jockey=_cell(cells, indexes["jockey"]),
                time=_cell(cells, indexes["time"]),
            )
        )
    return entries


def _parse_payout_entries(soup: BeautifulSoup) -> list[PayoutEntry]:
    grouped = _parse_grouped_payout_entries(soup)
    if grouped:
        return _deduplicate_payouts(grouped)

    entries: list[PayoutEntry] = []
    for table in _find_payout_tables(soup):
        for row in table.select("tr"):
            cells = [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"], recursive=False)]
            if len(cells) < 3:
                continue
            bet_type = NANKAN_PAYOUT_BET_TYPE_MAP.get(cells[0])
            if bet_type is None:
                continue
            combination = _normalize_payout_combination(cells[1])
            payout = _normalize_payout_amount(cells[2])
            if not combination or not payout:
                continue
            entries.append(
                PayoutEntry(
                    bet_type=bet_type,
                    combination=combination,
                    payout=payout,
                    popularity=_normalize_popularity(cells[3]) if len(cells) > 3 else None,
                )
            )
    return _deduplicate_payouts(entries)


def _parse_grouped_payout_entries(soup: BeautifulSoup) -> list[PayoutEntry]:
    entries: list[PayoutEntry] = []
    for table in _find_payout_tables(soup):
        rows = table.select("tr")
        if len(rows) < 3:
            continue
        bet_types = [_clean(cell.get_text(" ", strip=True)) for cell in rows[0].find_all(["th", "td"], recursive=False)]
        sub_headers = [_clean(cell.get_text(" ", strip=True)) for cell in rows[1].find_all(["th", "td"], recursive=False)]
        if not bet_types or not sub_headers or "組番" not in sub_headers or "金額" not in sub_headers:
            continue
        for group_index, raw_bet_type in enumerate(bet_types):
            bet_type = NANKAN_PAYOUT_BET_TYPE_MAP.get(raw_bet_type)
            if bet_type is None:
                continue
            start = group_index * 3
            for row in rows[2:]:
                cells = [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"], recursive=False)]
                if len(cells) <= start + 2:
                    continue
                combination = _normalize_payout_combination(cells[start])
                payout = _normalize_payout_amount(cells[start + 1])
                if not combination or not payout:
                    continue
                entries.append(
                    PayoutEntry(
                        bet_type=bet_type,
                        combination=combination,
                        payout=payout,
                        popularity=_normalize_popularity(cells[start + 2]),
                    )
                )
    return entries


def _deduplicate_payouts(entries: list[PayoutEntry]) -> list[PayoutEntry]:
    unique: dict[tuple[str, str, str, str | None], PayoutEntry] = {}
    for entry in entries:
        unique[(entry.bet_type, entry.combination, entry.payout, entry.popularity)] = entry
    return list(unique.values())


def _parse_win_place(soup: BeautifulSoup, bet_type: str) -> dict[str, list[OddsEntry]]:
    table = _find_table_with_headers(soup, ["枠番", "馬番", "馬名", "単勝", "複勝"])
    if table is None:
        return {bet_type: []}
    entries: list[OddsEntry] = []
    for row in table.select("tr"):
        cells = [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"], recursive=False)]
        if len(cells) >= 5 and cells[1].isdigit():
            horse_no = cells[1]
            win_odds = cells[3]
            place_odds = cells[4]
        elif len(cells) >= 4 and cells[0].isdigit():
            horse_no = cells[0]
            win_odds = cells[2]
            place_odds = cells[3]
        else:
            continue
        if bet_type == "win":
            entries.append(OddsEntry(bet_type="win", combination=[horse_no], odds=win_odds if _is_valid_odds(win_odds) else None))
        if bet_type == "place" and _is_valid_odds(place_odds):
            odds_min, odds_max = _split_odds_range(place_odds)
            entries.append(OddsEntry(bet_type="place", combination=[horse_no], odds_min=odds_min, odds_max=odds_max))
    return {
        bet_type: sorted(
            entries,
            key=lambda entry: int(entry.combination[0]) if entry.combination and entry.combination[0].isdigit() else 999,
        )
    }


def _parse_matrix_table(table: Tag, bet_type: str, unordered: bool) -> list[OddsEntry]:
    rows = table.select("tr")
    if not rows:
        return []
    headers = [_clean(cell.get_text(" ", strip=True)) for cell in rows[0].find_all(["th", "td"], recursive=False)]
    entries: list[OddsEntry] = []
    for row in rows[1:]:
        cells = row.find_all(["th", "td"], recursive=False)
        for index in range(0, len(cells), 2):
            if index // 2 >= len(headers) or index + 1 >= len(cells):
                continue
            prefix = _split_combination(headers[index // 2])
            last = _clean(cells[index].get_text(" ", strip=True))
            odds_text = _clean(cells[index + 1].get_text(" ", strip=True)).replace(" ", "")
            if not prefix or not last or not _is_valid_odds(odds_text):
                continue
            combination = prefix + [last]
            if len(set(combination)) != len(combination):
                continue
            if unordered:
                combination = sorted(combination, key=lambda item: int(item) if item.isdigit() else 999)
            if bet_type == "wide" and "-" in odds_text:
                odds_min, odds_max = _split_odds_range(odds_text)
                entries.append(OddsEntry(bet_type=bet_type, combination=combination, odds_min=odds_min, odds_max=odds_max))
            else:
                entries.append(OddsEntry(bet_type=bet_type, combination=combination, odds=odds_text))
    return entries


def _parse_runner_row(row: Tag) -> Runner | None:
    cells = [_clean(cell.get_text(" ", strip=True)) for cell in row.find_all(["th", "td"], recursive=False)]
    if len(cells) < 6 or not cells[0].isdigit():
        return None
    has_frame_no = len(cells) > 1 and cells[1].isdigit()
    if len(cells) in {11, 12}:
        offset = 0 if has_frame_no else -1
        horse_weight, horse_weight_diff = _split_weight_diff(cells[5 + offset])
        return Runner(
            frame_no=cells[0] if has_frame_no else None,
            horse_no=cells[1] if has_frame_no else cells[0],
            horse_name=_strip_birth_date(cells[2 + offset]),
            sex_age=_first_token(cells[3 + offset]),
            weight_carried=cells[6 + offset],
            jockey=cells[7 + offset],
            trainer=cells[9 + offset],
            horse_weight=horse_weight,
            horse_weight_diff=horse_weight_diff,
            odds=cells[4 + offset] if _is_valid_odds(cells[4 + offset]) else None,
        )
    if not has_frame_no:
        return None
    return Runner(
        frame_no=cells[0],
        horse_no=cells[1],
        horse_name=cells[2],
        sex_age=cells[4] if len(cells) > 4 else None,
        odds=cells[6] if len(cells) > 6 and _is_valid_odds(cells[6]) else None,
        horse_weight=cells[7] if len(cells) > 7 and cells[7].isdigit() else None,
        horse_weight_diff=cells[8].replace("＋", "+").replace("－", "-") if len(cells) > 8 else None,
        weight_carried=cells[9] if len(cells) > 9 else None,
        jockey=cells[10] if len(cells) > 10 else None,
        trainer=cells[13] if len(cells) > 13 else None,
    )


def _race_card_data_status(table: Tag | None, runners: list[Runner]) -> dict[str, str | None]:
    if not runners:
        return {
            "horse_weight": "unavailable",
            "horse_weight_reason": "runner table could not be parsed",
        }
    if any(runner.horse_weight or runner.horse_weight_diff for runner in runners):
        return {
            "horse_weight": "available",
            "horse_weight_reason": "at least one runner has horse_weight or horse_weight_diff",
        }
    if table is None:
        return {
            "horse_weight": "unavailable",
            "horse_weight_reason": "runner table was not found",
        }
    headers = [_clean(cell.get_text(" ", strip=True)) for cell in table.select("tr:first-child th, tr:first-child td")]
    has_weight_header = any("馬体重" in header or "増減" in header for header in headers)
    if has_weight_header:
        return {
            "horse_weight": "unpublished",
            "horse_weight_reason": "all runners have null horse_weight before official publication",
        }
    return {
        "horse_weight": "unavailable",
        "horse_weight_reason": "horse_weight column could not be identified",
    }


def _find_table_with_headers(soup: BeautifulSoup, expected: list[str]) -> Tag | None:
    candidates = []
    for table in soup.select("table"):
        text = _clean(table.get_text(" ", strip=True))
        if all(item in text for item in expected):
            candidates.append(table)
    for table in candidates:
        if any(_parse_runner_row(row) is not None for row in table.select("tr")):
            return table
    return candidates[0] if candidates else None


def _find_result_table(soup: BeautifulSoup) -> Tag | None:
    for table in soup.select("table"):
        headers = [_clean(cell.get_text(" ", strip=True)) for cell in table.select("tr:first-child th, tr:first-child td")]
        if _header_index(headers, ["着順", "着"]) is not None and _header_index(headers, ["馬番"]) is not None and _header_index(
            headers, ["馬名"]
        ) is not None:
            return table
    return None


def _find_payout_tables(soup: BeautifulSoup) -> list[Tag]:
    tables = []
    for table in soup.select("table"):
        text = _clean(table.get_text(" ", strip=True))
        if any(label in text for label in NANKAN_PAYOUT_BET_TYPE_MAP) and ("組番" in text or "払戻" in text or "金額" in text):
            tables.append(table)
    return tables


def _find_leading_jockey_table(soup: BeautifulSoup) -> Tag | None:
    for table in soup.select("table"):
        headers = [_clean(cell.get_text(" ", strip=True)) for cell in table.select("tr:first-child th, tr:first-child td")]
        index = _leading_jockey_header_index(headers)
        if index.get("jockey_name") is not None and (
            index.get("wins") is not None or index.get("win_rate") is not None
        ):
            return table
    return None


def _leading_jockey_header_index(headers: list[str]) -> dict[str, int | None]:
    return {
        "rank": _header_index(headers, ["順位", "rank"]),
        "jockey_name": _header_index(headers, ["騎手", "jockey"]),
        "rides": _header_index(headers, ["騎乗", "rides"]),
        "wins": _header_index(headers, ["1着", "勝", "wins"]),
        "seconds": _header_index(headers, ["2着", "seconds"]),
        "thirds": _header_index(headers, ["3着", "thirds"]),
        "win_rate": _header_index(headers, ["勝率", "win_rate"]),
        "quinella_rate": _header_index(headers, ["連対率", "quinella_rate"]),
        "trio_rate": _header_index(headers, ["3着内率", "3連対率", "三連対率", "複勝率", "trio_rate"]),
    }


def _value_by_header(values: list[str], index: dict[str, int | None], key: str) -> str | None:
    current = index.get(key)
    if current is None or current >= len(values):
        return None
    return values[current] or None


def _jockey_code_from_cells(cells: list[Tag]) -> str | None:
    for cell in cells:
        link = cell.select_one("a[href]")
        if link is None:
            continue
        href = str(link.get("href") or "")
        match = re.search(r"(\d{4,})", href)
        if match:
            return match.group(1)
    return None


def _int_value(value: str | None) -> int | None:
    if not value:
        return None
    digits = "".join(re.findall(r"\d+", value.replace(",", "")))
    return int(digits) if digits else None


def _float_value(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"\d+(?:\.\d+)?", value.replace(",", ""))
    return float(match.group(0)) if match else None


def _header_index(headers: list[str], labels: list[str]) -> int | None:
    for index, header in enumerate(headers):
        normalized = header.casefold()
        if any(label.casefold() in normalized for label in labels):
            return index
    return None


def _cell(cells: list[str], index: int | None) -> str | None:
    if index is None or index >= len(cells):
        return None
    return cells[index] or None


def _first_matrix_table(soup: BeautifulSoup) -> Tag | None:
    tables = soup.select("table.nk23_c-table02__table")
    return tables[0] if tables else None


def _race_title(soup: BeautifulSoup) -> str | None:
    for node in soup.select(".nk23_c-tab1__subtitle, .nk23_l-title__text, h1, h2, h3"):
        text = _clean(node.get_text(" ", strip=True))
        if re.search(r"\d+R", text):
            return text
    return None


def _race_meta_text(soup: BeautifulSoup) -> str | None:
    for node in soup.select(".nk23_c-tab1__subtitle, .nk23_l-title__text, h1, h2, h3"):
        text = _clean(node.get_text(" ", strip=True))
        if re.search(r"\d+R", text) and (_distance_from_text(text) or _start_time_from_text(text)):
            return text
    return None


def _race_name_from_title(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"^\d+R\s+", "", value)
    text = re.sub(r"\d{4}年.*$", "", text).strip()
    return text or None


def _race_name_from_card_page(soup: BeautifulSoup) -> str | None:
    for node in soup.select(".nk23_c-tab1__title"):
        text = _clean(node.get_text(" ", strip=True))
        text = re.sub(r"\s*詳細$", "", text).strip()
        if text:
            return text
    return None


def _race_name_from_result_page(soup: BeautifulSoup) -> str | None:
    for node in soup.select(".nk23_c-tab1__title"):
        text = _clean(node.get_text(" ", strip=True))
        text = re.sub(r"\s*詳細$", "", text).strip()
        if text:
            return text
    return _race_name_from_title(_race_title(soup))


def _course_from_text(value: str) -> str | None:
    for name, code in NANKAN_COURSE_NAME_TO_CODE.items():
        if name in value:
            return code
    return None


def _distance_from_text(value: str) -> str | None:
    match = re.search(r"([\d,]+)m", value)
    return match.group(1).replace(",", "") if match else None


def _race_meta_from_text(value: str) -> dict[str, str | None]:
    surface_label = _surface_label_from_text(value)
    return {
        "surface": _normalize_surface(surface_label),
        "surface_label": surface_label,
        "distance": _distance_from_text(value),
        "start_time": _start_time_from_text(value),
    }


def _meeting_conditions(soup: BeautifulSoup) -> dict[str, str | None]:
    text = _clean(soup.get_text(" ", strip=True))
    weather_label = _weather_label_from_text(text)
    surface_label, track_condition_label = _track_surface_and_condition_from_text(text)
    return {
        "weather": _normalize_weather(weather_label),
        "weather_label": weather_label,
        "track_condition": _normalize_track_condition(track_condition_label),
        "track_condition_label": track_condition_label,
        "surface": _normalize_surface(surface_label),
        "surface_label": surface_label,
    }


def _weather_label_from_text(value: str) -> str | None:
    match = re.search(r"天候[:：]\s*([^\s　]+)", value)
    return match.group(1) if match else None


def _track_surface_and_condition_from_text(value: str) -> tuple[str | None, str | None]:
    match = re.search(r"馬場[:：]\s*([芝ダ障]+(?:ート)?)(良|稍重|重|不良)", value)
    if match:
        return match.group(1), match.group(2)
    match = re.search(r"馬場[:：]\s*(良|稍重|重|不良)", value)
    if match:
        return None, match.group(1)
    return None, None


def _surface_label_from_text(value: str) -> str | None:
    match = re.search(r"(ダート|ダ|芝|障害|障)\s*[\d,]+m", value)
    return match.group(1) if match else None


def _normalize_surface(value: str | None) -> str | None:
    if not value:
        return None
    return NANKAN_SURFACE_LABEL_TO_CODE.get(value)


def _normalize_track_condition(value: str | None) -> str | None:
    if not value:
        return None
    return NANKAN_TRACK_CONDITION_LABEL_TO_CODE.get(value)


def _normalize_weather(value: str | None) -> str | None:
    if not value:
        return None
    return NANKAN_WEATHER_LABEL_TO_CODE.get(value)


def _start_time_from_text(value: str) -> str | None:
    match = re.search(r"発走時刻\s*(\d{1,2}:\d{2})|(\d{1,2}:\d{2})\s*発走", value)
    if match:
        return match.group(1) or match.group(2)
    match = re.search(r"\d{1,2}R\s+(\d{1,2}:\d{2})", value)
    if match:
        return match.group(1)
    match = re.search(r"(\d{1,2}:\d{2})", value)
    return match.group(1) if match else None


def _split_combination(value: str) -> list[str]:
    return [item for item in re.split(r"[-－]", value) if item.isdigit()]


def _split_weight_diff(value: str) -> tuple[str | None, str | None]:
    match = re.search(r"(?P<weight>\d+)\s*(?P<diff>[+＋\-－]?\d+|-)?", value)
    if not match:
        return None, None
    diff = match.group("diff")
    if diff:
        diff = diff.replace("＋", "+").replace("－", "-")
    return match.group("weight"), diff


def _strip_birth_date(value: str) -> str:
    return re.sub(r"\s+\d{2}\.\d{1,2}\.\d{1,2}$", "", value).strip()


def _first_token(value: str) -> str | None:
    return value.split()[0] if value.split() else None


def _split_odds_range(value: str) -> tuple[str | None, str | None]:
    parts = [part.strip() for part in re.split(r"\s*[-－]\s*", value)]
    if len(parts) == 2:
        return parts[0], parts[1]
    return value or None, None


def _normalize_payout_combination(value: str) -> str | None:
    numbers = re.findall(r"\d+", value)
    return "-".join(numbers) if numbers else None


def _normalize_payout_amount(value: str) -> str | None:
    digits = "".join(re.findall(r"\d+", value))
    return digits or None


def _normalize_popularity(value: str) -> str | None:
    digits = "".join(re.findall(r"\d+", value))
    return digits or None


def _has_not_on_sale(soup: BeautifulSoup) -> bool:
    return (
        "発売なし" in soup.get_text(" ", strip=True)
        and soup.select_one("table.nk23_c-table04__table, table.nk23_c-table02__table") is None
    )


def _is_valid_odds(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip()
    return normalized not in {"−", "－", "-", ""}


def _clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
