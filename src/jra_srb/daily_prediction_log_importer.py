from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from pathlib import Path

from .analysis_store import AnalysisSQLiteStore


COURSE_NAME_MAP = {
    "川崎": "kawasaki",
    "大井": "ohi",
    "船橋": "funabashi",
    "浦和": "urawa",
}


@dataclass
class DailyPredictionLogEntry:
    entry_timestamp: datetime
    entry_type: str
    race_date: str | None
    course: str | None
    race_no: int | None
    topic: str | None
    prediction_mode: str | None
    payload: dict[str, object]
    raw_markdown: str


@dataclass
class DailyPredictionLogDocument:
    log_date: str | None
    venue: str | None
    entries: list[DailyPredictionLogEntry]


@dataclass
class DailyPredictionLogImportSummary:
    source_path: str
    log_date: str | None
    venue: str | None
    imported_entries: int
    resolved_race_ids: int


def parse_daily_prediction_log(text: str) -> DailyPredictionLogDocument:
    lines = text.splitlines()
    log_date = None
    venue = None
    if lines:
        header_match = re.match(r"^#\s+(\d{4}-\d{2}-\d{2})\s+(.+?)\s+予想ログ\s*$", lines[0].strip())
        if header_match:
            log_date = header_match.group(1)
            venue = header_match.group(2)

    blocks = []
    current_header: str | None = None
    current_lines: list[str] = []
    for line in lines:
        if line.startswith("### "):
            if current_header is not None:
                blocks.append((current_header, current_lines))
            current_header = line[4:].strip()
            current_lines = []
            continue
        if current_header is not None:
            current_lines.append(line)
    if current_header is not None:
        blocks.append((current_header, current_lines))

    entries = [parse_log_block(header, block_lines, log_date) for header, block_lines in blocks]
    return DailyPredictionLogDocument(log_date=log_date, venue=venue, entries=entries)


def parse_log_block(header: str, block_lines: list[str], default_date: str | None) -> DailyPredictionLogEntry:
    timestamp = datetime.fromisoformat(header.replace(" ", "T"))
    fields: dict[str, object] = {}
    current_key: str | None = None

    for raw_line in block_lines:
        line = raw_line.rstrip()
        top_level_match = re.match(r"^- ([^:]+):\s*(.*)$", line)
        if top_level_match:
            key = top_level_match.group(1).strip()
            value = top_level_match.group(2).strip()
            current_key = key
            fields[key] = value if value else []
            continue
        sub_match = re.match(r"^  - (.+)$", line)
        if sub_match and current_key is not None:
            current_value = fields.get(current_key)
            if not isinstance(current_value, list):
                current_value = [] if current_value in ("", None) else [str(current_value)]
            current_value.append(sub_match.group(1).strip())
            fields[current_key] = current_value

    topic = _as_optional_string(fields.get("対象"))
    course, race_no = _extract_course_and_race_no(topic)
    prediction_mode = _as_optional_string(fields.get("予想モード"))
    raw_markdown = "\n".join([f"### {header}", *block_lines]).strip()

    return DailyPredictionLogEntry(
        entry_timestamp=timestamp,
        entry_type=_as_optional_string(fields.get("種別")) or "unknown",
        race_date=default_date,
        course=course,
        race_no=race_no,
        topic=topic,
        prediction_mode=prediction_mode,
        payload=fields,
        raw_markdown=raw_markdown,
    )


def import_daily_prediction_log(
    store: AnalysisSQLiteStore,
    source_path: str | Path,
) -> DailyPredictionLogImportSummary:
    path = Path(source_path)
    document = parse_daily_prediction_log(path.read_text(encoding="utf-8"))
    result = store.replace_daily_prediction_log_entries(
        source_path=str(path),
        log_date=document.log_date,
        venue=document.venue,
        entries=[
            {
                "entry_timestamp": entry.entry_timestamp,
                "entry_type": entry.entry_type,
                "race_date": entry.race_date,
                "course": entry.course,
                "race_no": entry.race_no,
                "topic": entry.topic,
                "prediction_mode": entry.prediction_mode,
                "payload": entry.payload,
                "raw_markdown": entry.raw_markdown,
            }
            for entry in document.entries
        ],
    )
    return DailyPredictionLogImportSummary(
        source_path=str(path),
        log_date=document.log_date,
        venue=document.venue,
        imported_entries=result["imported_entries"],
        resolved_race_ids=result["resolved_race_ids"],
    )


def _extract_course_and_race_no(topic: str | None) -> tuple[str | None, int | None]:
    if not topic:
        return None, None
    match = re.search(r"(川崎|大井|船橋|浦和)\s+(\d+)R", topic)
    if not match:
        return None, None
    return COURSE_NAME_MAP.get(match.group(1)), int(match.group(2))


def _as_optional_string(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return None
    text = str(value).strip()
    return text or None
