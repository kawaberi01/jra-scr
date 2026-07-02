from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .analysis_store import AnalysisSQLiteStore
from .service import COURSE_CODE_TO_NAME, COURSE_NAME_TO_CODE


MAPPING_COLUMNS = [
    "jra_race_id",
    "netkeiba_race_id",
    "race_date",
    "course",
    "race_no",
    "mapping_status",
    "mapping_note",
]


@dataclass(frozen=True)
class NetkeibaMeetingCalendarEntry:
    course: str
    meeting_no: int
    start_date: date
    start_day_no: int = 1


@dataclass(frozen=True)
class NetkeibaMappingGenerationSummary:
    total_count: int
    mapped_count: int
    unmapped_count: int
    output: Path


def generate_netkeiba_mapping_csv(
    store: AnalysisSQLiteStore,
    from_date: date,
    to_date: date,
    output: Path,
    meeting_calendar_csv: Path | None = None,
    limit: int | None = None,
) -> NetkeibaMappingGenerationSummary:
    calendar = _load_meeting_calendar(meeting_calendar_csv) if meeting_calendar_csv is not None else {}
    context_from_date = _context_from_date(from_date, calendar)
    context_rows = store.list_races_for_netkeiba_mapping(context_from_date, to_date)
    rows = [
        row
        for row in context_rows
        if from_date <= date.fromisoformat(str(row["race_date"])) <= to_date
    ]
    if limit is not None:
        rows = rows[:limit]
    race_dates_by_course = _race_dates_by_course(context_rows)

    output.parent.mkdir(parents=True, exist_ok=True)
    mapped = 0
    unmapped = 0
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=MAPPING_COLUMNS)
        writer.writeheader()
        for row in rows:
            generated = _generate_mapping_row(row, calendar, race_dates_by_course)
            if generated["netkeiba_race_id"]:
                mapped += 1
            else:
                unmapped += 1
            writer.writerow(generated)
    return NetkeibaMappingGenerationSummary(
        total_count=len(rows),
        mapped_count=mapped,
        unmapped_count=unmapped,
        output=output,
    )


def _generate_mapping_row(
    row: dict,
    calendar: dict[str, list[NetkeibaMeetingCalendarEntry]],
    race_dates_by_course: dict[str, list[date]],
) -> dict[str, str]:
    jra_race_id = str(row["race_id"])
    race_date = date.fromisoformat(str(row["race_date"]))
    race_no = int(row["race_no"])
    course, course_note = _course_from_jra_race_id(jra_race_id)
    if course is None:
        return _unmapped_row(
            jra_race_id,
            race_date,
            "",
            race_no,
            course_note,
        )
    course_code = COURSE_NAME_TO_CODE[course]

    if course in calendar:
        entry = _find_calendar_entry(calendar[course], race_date)
        if entry is None:
            return _unmapped_row(
                jra_race_id,
                race_date,
                course,
                race_no,
                "meeting calendar has no entry for race date",
            )
        course_dates = [item for item in race_dates_by_course[course] if item >= entry.start_date and item <= race_date]
        day_no = entry.start_day_no + len(course_dates) - 1
        netkeiba_race_id = f"{race_date.year}{course_code}{entry.meeting_no:02d}{day_no:02d}{race_no:02d}"
        return _mapped_row(
            jra_race_id,
            netkeiba_race_id,
            race_date,
            course,
            race_no,
            "mapped",
            f"calendar course={course} meeting={entry.meeting_no} day={day_no}",
        )

    course_dates = race_dates_by_course.get(course, [])
    if race_date not in course_dates:
        return _unmapped_row(jra_race_id, race_date, course, race_no, "race date not found in course date list")
    day_no = course_dates.index(race_date) + 1
    netkeiba_race_id = f"{race_date.year}{course_code}{1:02d}{day_no:02d}{race_no:02d}"
    return _mapped_row(
        jra_race_id,
        netkeiba_race_id,
        race_date,
        course,
        race_no,
        "mapped_estimated",
        "estimated with meeting_no=1 because no meeting calendar CSV was provided",
    )


def _load_meeting_calendar(path: Path) -> dict[str, list[NetkeibaMeetingCalendarEntry]]:
    calendar: dict[str, list[NetkeibaMeetingCalendarEntry]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"course", "meeting_no", "start_date"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError("meeting calendar CSV must include course, meeting_no, start_date")
        for row in reader:
            course = (row.get("course") or "").strip()
            if not course:
                continue
            entry = NetkeibaMeetingCalendarEntry(
                course=course,
                meeting_no=int(str(row["meeting_no"]).strip()),
                start_date=date.fromisoformat(str(row["start_date"]).strip()),
                start_day_no=int(str(row.get("start_day_no") or "1").strip()),
            )
            calendar.setdefault(course, []).append(entry)
    for entries in calendar.values():
        entries.sort(key=lambda item: item.start_date)
    return calendar


def _context_from_date(
    from_date: date,
    calendar: dict[str, list[NetkeibaMeetingCalendarEntry]],
) -> date:
    start_dates = [entry.start_date for entries in calendar.values() for entry in entries]
    if not start_dates:
        return from_date
    return min(from_date, min(start_dates))


def _find_calendar_entry(
    entries: list[NetkeibaMeetingCalendarEntry],
    race_date: date,
) -> NetkeibaMeetingCalendarEntry | None:
    selected: NetkeibaMeetingCalendarEntry | None = None
    for entry in entries:
        if entry.start_date <= race_date:
            selected = entry
        else:
            break
    return selected


def _race_dates_by_course(rows: list[dict]) -> dict[str, list[date]]:
    dates: dict[str, set[date]] = {}
    for row in rows:
        course, _ = _course_from_jra_race_id(str(row["race_id"]))
        if course is None:
            continue
        dates.setdefault(course, set()).add(date.fromisoformat(str(row["race_date"])))
    return {course: sorted(values) for course, values in dates.items()}


def _course_from_jra_race_id(jra_race_id: str) -> tuple[str | None, str]:
    if len(jra_race_id) < 10 or not jra_race_id[8:10].isdigit():
        return None, f"invalid jra_race_id={jra_race_id}: cannot read course code"
    course_code = jra_race_id[8:10]
    course = COURSE_CODE_TO_NAME.get(course_code)
    if course is None:
        return None, f"unsupported course_code={course_code} in jra_race_id={jra_race_id}"
    return course, f"course restored from jra_race_id code={course_code}"


def _mapped_row(
    jra_race_id: str,
    netkeiba_race_id: str,
    race_date: date,
    course: str,
    race_no: int,
    status: str,
    note: str,
) -> dict[str, str]:
    return {
        "jra_race_id": jra_race_id,
        "netkeiba_race_id": netkeiba_race_id,
        "race_date": race_date.isoformat(),
        "course": course,
        "race_no": str(race_no),
        "mapping_status": status,
        "mapping_note": note,
    }


def _unmapped_row(jra_race_id: str, race_date: date, course: str, race_no: int, note: str) -> dict[str, str]:
    return _mapped_row(jra_race_id, "", race_date, course, race_no, "unmapped", note)
