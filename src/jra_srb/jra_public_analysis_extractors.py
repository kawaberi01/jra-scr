from __future__ import annotations

from datetime import date, datetime, UTC
import re

from bs4 import BeautifulSoup, Tag

from .models import JraMaterialStatus, JraPublicRunnerAnalysis, JraPublicSourceAnalysis, JraRecentRace


_CIRCLED = {char: index for index, char in enumerate("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱", start=1)}
_COURSES = ("札幌", "函館", "福島", "新潟", "東京", "中山", "中京", "京都", "阪神", "小倉")


def parse_netkeiba_data_top(html: str, source_url: str) -> JraPublicSourceAnalysis:
    soup = BeautifulSoup(html, "html.parser")
    course_analysis: dict[str, list[str]] = {}
    root = soup.select_one(".RaceDataPickupList.Not_Premium")
    if root:
        for table in root.select("table.PickupRaceDataTable01"):
            title = _text(table.select_one(".PickupHorseTableTitle"))
            if not title:
                continue
            values = [_text(node) for node in table.select("td .Umaban_Num, td .Txt")]
            values = [value for value in values if value and value != "推奨なし"]
            course_analysis[_normalize_title(title)] = values
    status = JraMaterialStatus.available if course_analysis else JraMaterialStatus.unavailable
    return JraPublicSourceAnalysis(
        source="netkeiba",
        status=status,
        source_url=source_url,
        course_analysis=course_analysis,
        reason=None if course_analysis else "匿名公開のコース分析が見つかりません",
        fetched_at=datetime.now(UTC),
    )


def parse_keibalab_umabashira(html: str, source_url: str) -> JraPublicSourceAnalysis:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.megamoriTable")
    if table is None:
        return JraPublicSourceAnalysis(
            source="keibalab",
            status=JraMaterialStatus.unavailable,
            source_url=source_url,
            reason="匿名公開の馬柱が見つかりません",
            fetched_at=datetime.now(UTC),
        )
    horse_numbers = [_text(node) for node in table.select("tr.umaban i")]
    horse_numbers = [value for value in horse_numbers if value]
    horse_names = []
    for node in table.select("a.bamei"):
        name = _text(node)
        if name and name not in horse_names:
            horse_names.append(name)
        if len(horse_names) == len(horse_numbers):
            break
    runners = [JraPublicRunnerAnalysis(horse_no=no, horse_name=name) for no, name in zip(horse_numbers, horse_names)]
    omega_values = _row_values_before_header(table, "Ω指数", len(runners))
    for runner, value in zip(runners, omega_values):
        runner.omega_index = _float(value)
    recent_rows = [row for row in table.select("tr") if any(cls.startswith("zensou") for cls in row.get("class", []))]
    for row in recent_rows[:5]:
        cells = row.find_all("td", recursive=False)
        for runner, cell in zip(runners, cells):
            if recent := _parse_keibalab_recent_race(cell, source_url):
                runner.recent_races.append(recent)
    status = JraMaterialStatus.available if runners else JraMaterialStatus.unavailable
    return JraPublicSourceAnalysis(
        source="keibalab",
        status=status,
        source_url=source_url,
        runners=runners,
        reason=None if runners else "匿名公開の出走馬が見つかりません",
        fetched_at=datetime.now(UTC),
    )


def parse_umanity_race(html: str, source_url: str) -> JraPublicSourceAnalysis:
    soup = BeautifulSoup(html, "html.parser")
    locked = []
    for node in soup.select("a[onclick*='open_register_vip']"):
        value = _text(node)
        if value and value not in locked:
            locked.append(value)
    return JraPublicSourceAnalysis(
        source="umanity",
        status=JraMaterialStatus.unavailable,
        source_url=source_url,
        locked_fields=locked,
        reason="予想材料は匿名公開範囲外" if locked else "匿名公開の予想材料が見つかりません",
        fetched_at=datetime.now(UTC),
    )


def _parse_keibalab_recent_race(cell: Tag, source_url: str) -> JraRecentRace | None:
    race_table = cell.select_one("table.zensouTable")
    if race_table is None:
        return None
    race_link = cell.select_one("a[href*='/db/race/']")
    race_code_match = re.search(r"/db/race/(\d{12})", race_link.get("href", "") if race_link else "")
    race_code = race_code_match.group(1) if race_code_match else None
    source_date = _date_from_race_code(race_code)
    day_baba = [_text(node) for node in race_table.select(".daybaba li")]
    condition = day_baba[2] if len(day_baba) >= 3 else ""
    course = next((name for name in _COURSES if any(name in value for value in day_baba)), None)
    surface = "turf" if condition.startswith("芝") else "dirt" if condition.startswith("ダ") else None
    distance_match = re.search(r"(?:芝|ダ)(\d{2})", condition)
    distance = int(distance_match.group(1)) * 100 if distance_match else None
    track_condition = _track_condition(condition)
    rank = _int(_text(race_table.select_one(".cyakuJun")))
    all_text = _text(race_table) or ""
    popularity_match = re.search(r"(\d+)人", all_text)
    field_match = re.search(r"(\d+)頭", all_text)
    time_match = re.search(r"\b\d:\d{2}\.\d\b", all_text)
    final_node = race_table.select_one("[class*='bgRise_']")
    corner_node = race_table.select_one("td.zensou span")
    corner_positions = _corner_positions(_text(corner_node) or "")
    jockey = None
    weight_carried = None
    for row in race_table.select("tr"):
        spans = [_text(node) for node in row.select("span")]
        if len(spans) == 2 and _float(spans[1]) is not None and not spans[0].endswith("人"):
            jockey, weight_text = spans
            weight_carried = _float(weight_text)
    return JraRecentRace(
        source_date=source_date,
        source_course=course,
        source_race_no=int(race_code[-2:]) if race_code else None,
        surface=surface,
        distance=distance,
        track_condition=track_condition,
        finish_rank=rank,
        field_size=int(field_match.group(1)) if field_match else None,
        finish_time=time_match.group() if time_match else None,
        final_3f=_float(_text(final_node)),
        corner_positions=corner_positions,
        weight_carried=weight_carried,
        jockey=jockey,
        popularity=int(popularity_match.group(1)) if popularity_match else None,
        source="keibalab",
        source_url=source_url,
    )


def _row_values_before_header(table: Tag, header: str, count: int) -> list[str | None]:
    for row in table.select("tr"):
        if _text(row.find("th")) == header:
            values = [_text(cell) for cell in row.find_all("td", recursive=False)]
            values = values[-count:]
            return values
    return []


def _corner_positions(value: str) -> list[int]:
    result = []
    for char in value:
        if char in _CIRCLED:
            result.append(_CIRCLED[char])
    if result:
        return result
    return [int(item) for item in re.findall(r"\d+", value)]


def _track_condition(value: str) -> str | None:
    if value.endswith("良"):
        return "good"
    if value.endswith("稍"):
        return "slightly_heavy"
    if value.endswith("重"):
        return "heavy"
    if value.endswith("不"):
        return "bad"
    return None


def _date_from_race_code(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:8]}")
    except ValueError:
        return None


def _normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _text(node) -> str | None:
    if node is None:
        return None
    value = node.get_text(" ", strip=True)
    return value or None


def _int(value: str | None) -> int | None:
    match = re.search(r"\d+", value or "")
    return int(match.group()) if match else None


def _float(value: str | None) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", value or "")
    return float(match.group()) if match else None
