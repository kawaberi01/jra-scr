from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import gzip
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Iterable


COURSE_CODES = {
    "01": "sapporo", "02": "hakodate", "03": "fukushima", "04": "niigata",
    "05": "tokyo", "06": "nakayama", "07": "chukyo", "08": "kyoto",
    "09": "hanshin", "10": "kokura",
}

FEATURE_NAMES = [
    "distance_scaled", "field_size_scaled", "horse_no_scaled", "frame_no_scaled",
    "age_scaled", "weight_carried_scaled", "days_since_last_scaled",
    "horse_has_history", "horse_log_starts", "horse_win_rate", "horse_top3_rate",
    "horse_finish_strength", "horse_course_log_starts", "horse_course_top3_rate",
    "horse_surface_log_starts", "horse_surface_top3_rate", "horse_distance_log_starts",
    "horse_distance_top3_rate", "jockey_log_starts", "jockey_win_rate",
    "jockey_top3_rate", "trainer_log_starts", "trainer_win_rate", "trainer_top3_rate",
    "sex_male", "sex_female", "sex_gelding", "surface_turf", "surface_dirt",
    "is_obstacle", "is_newcomer", "is_maiden", "is_open_or_stakes",
] + [f"course_{course}" for course in COURSE_CODES.values()]


@dataclass
class HistoryStat:
    starts: int = 0
    wins: int = 0
    top3: int = 0
    finish_fraction_sum: float = 0.0
    last_date: date | None = None

    def update(self, rank: int, field_size: int, race_date: date) -> None:
        self.starts += 1
        self.wins += rank == 1
        self.top3 += rank <= 3
        self.finish_fraction_sum += (rank - 1) / max(field_size - 1, 1)
        self.last_date = race_date


def build_history_dataset(
    db_path: str | Path, *, through_date: date | None = None,
) -> tuple[list[dict], dict]:
    """Read the source DB in read-only mode and build leakage-safe runner rows."""
    path = Path(db_path).resolve()
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select r.race_id, r.race_date, r.race_name, r.surface, r.distance,
                   ru.horse_no, ru.frame_no, ru.horse_name, ru.sex_age,
                   ru.weight_carried, ru.jockey, ru.trainer, re.rank
            from races r
            join runners ru on ru.race_id = r.race_id
            join result_entries re on re.race_id = r.race_id and re.horse_no = ru.horse_no
            where length(r.race_id) = 12
              and substr(r.race_id, 9, 2) between '01' and '10'
              and r.source like 'https://www.jra.go.jp/%'
              and exists (select 1 from payouts p where p.race_id = r.race_id)
              and (? is null or r.race_date <= ?)
            order by r.race_date, r.race_id, cast(ru.horse_no as integer)
            """,
            (
                through_date.isoformat() if through_date else None,
                through_date.isoformat() if through_date else None,
            ),
        ).fetchall()
    finally:
        conn.close()
    records, metadata = build_history_dataset_from_rows(rows)
    metadata["source_through_date"] = through_date.isoformat() if through_date else None
    return records, metadata


def build_history_dataset_from_rows(rows: Iterable[sqlite3.Row | dict]) -> tuple[list[dict], dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for raw in rows:
        row = dict(raw)
        if _valid_row(row):
            grouped[str(row["race_id"])].append(row)

    horse_stats: dict[str, HistoryStat] = defaultdict(HistoryStat)
    horse_course: dict[tuple[str, str], HistoryStat] = defaultdict(HistoryStat)
    horse_surface: dict[tuple[str, str], HistoryStat] = defaultdict(HistoryStat)
    horse_distance: dict[tuple[str, str], HistoryStat] = defaultdict(HistoryStat)
    jockey_stats: dict[str, HistoryStat] = defaultdict(HistoryStat)
    trainer_stats: dict[str, HistoryStat] = defaultdict(HistoryStat)
    records: list[dict] = []
    race_dates: set[str] = set()

    for race_id, race_rows in sorted(grouped.items(), key=lambda item: (item[1][0]["race_date"], item[0])):
        field_size = len(race_rows)
        if field_size < 2:
            continue
        first = race_rows[0]
        race_date = date.fromisoformat(str(first["race_date"]))
        course = COURSE_CODES[race_id[8:10]]
        surface = _surface(first.get("surface"))
        distance = _number(first.get("distance")) or 0
        distance_band = _distance_band(distance, first.get("race_name"))
        race_dates.add(race_date.isoformat())

        pending_updates = []
        for row in race_rows:
            horse_name = _text(row.get("horse_name"), "unknown")
            jockey = _text(row.get("jockey"), "unknown")
            trainer = _text(row.get("trainer"), "unknown")
            rank = int(row["rank"])
            horse = horse_stats[horse_name]
            hc = horse_course[(horse_name, course)]
            hs = horse_surface[(horse_name, surface)]
            hd = horse_distance[(horse_name, distance_band)]
            jockey_stat = jockey_stats[jockey]
            trainer_stat = trainer_stats[trainer]
            features = _feature_vector(
                row=row, race_date=race_date, race_name=_text(first.get("race_name"), ""),
                course=course, surface=surface, distance=distance, field_size=field_size,
                horse=horse, horse_course=hc, horse_surface=hs, horse_distance=hd,
                jockey=jockey_stat, trainer=trainer_stat,
            )
            records.append({
                "race_id": race_id,
                "race_date": race_date.isoformat(),
                "course": course,
                "surface": surface,
                "distance": distance,
                "horse_no": str(row["horse_no"]),
                "horse_name": horse_name,
                "features": features,
                "label_win": int(rank == 1),
                "label_top3": int(rank <= 3),
                "actual_rank": rank,
            })
            pending_updates.append((rank, horse, hc, hs, hd, jockey_stat, trainer_stat))

        # Update only after every runner in the race has been featurized.
        for rank, *stats in pending_updates:
            for stat in stats:
                stat.update(rank, field_size, race_date)

    metadata = {
        "races": len({record["race_id"] for record in records}),
        "runner_rows": len(records),
        "race_dates": len(race_dates),
        "date_min": min(race_dates) if race_dates else None,
        "date_max": max(race_dates) if race_dates else None,
        "feature_names": FEATURE_NAMES,
        "source_db_mutated": False,
    }
    return records, metadata


def write_dataset_jsonl_gz(records: Iterable[dict], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def build_live_feature_records(
    db_path: str | Path,
    *,
    target_date: date,
    course: str,
    card,
) -> list[dict]:
    """Create pre-race features using only races before ``target_date``.

    Same-day results are deliberately excluded. This is conservative but prevents
    an unavailable live result from becoming an accidental future feature.
    """
    if course not in COURSE_CODES.values():
        raise ValueError(f"unsupported JRA course={course}")
    path = Path(db_path).resolve()
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select r.race_id, r.race_date, r.race_name, r.surface, r.distance,
                   ru.horse_no, ru.frame_no, ru.horse_name, ru.sex_age,
                   ru.weight_carried, ru.jockey, ru.trainer, re.rank
            from races r
            join runners ru on ru.race_id = r.race_id
            join result_entries re on re.race_id = r.race_id and re.horse_no = ru.horse_no
            where length(r.race_id) = 12
              and substr(r.race_id, 9, 2) between '01' and '10'
              and r.source like 'https://www.jra.go.jp/%'
              and r.race_date < ?
              and exists (select 1 from payouts p where p.race_id = r.race_id)
            order by r.race_date, r.race_id, cast(ru.horse_no as integer)
            """,
            (target_date.isoformat(),),
        ).fetchall()
    finally:
        conn.close()

    states = _build_history_states(rows)
    field_size = len(card.runners)
    surface = _surface(card.surface)
    distance = _number(card.distance) or 0
    distance_band = _distance_band(distance, card.race_name)
    records = []
    for runner in card.runners:
        horse_name = _text(runner.horse_name, "unknown")
        jockey = _text(runner.jockey, "unknown")
        trainer = _text(runner.trainer, "unknown")
        horse = states["horse"][horse_name]
        records.append({
            "race_id": card.race_id,
            "race_date": target_date.isoformat(),
            "course": course,
            "surface": surface,
            "distance": distance,
            "horse_no": str(runner.horse_no or ""),
            "horse_name": horse_name,
            "jockey": jockey,
            "trainer": trainer,
            "features": _feature_vector(
                row={
                    "horse_no": runner.horse_no,
                    "frame_no": runner.frame_no,
                    "sex_age": runner.sex_age,
                    "weight_carried": runner.weight_carried,
                },
                race_date=target_date,
                race_name=_text(card.race_name, ""),
                course=course,
                surface=surface,
                distance=distance,
                field_size=field_size,
                horse=horse,
                horse_course=states["horse_course"][(horse_name, course)],
                horse_surface=states["horse_surface"][(horse_name, surface)],
                horse_distance=states["horse_distance"][(horse_name, distance_band)],
                jockey=states["jockey"][jockey],
                trainer=states["trainer"][trainer],
            ),
            "history_as_of": f"{target_date.isoformat()}T00:00:00",
            "history_starts": horse.starts,
        })
    return records


def _build_history_states(rows: Iterable[sqlite3.Row | dict]) -> dict:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for raw in rows:
        row = dict(raw)
        if _valid_row(row):
            grouped[str(row["race_id"])].append(row)
    states = {
        "horse": defaultdict(HistoryStat),
        "horse_course": defaultdict(HistoryStat),
        "horse_surface": defaultdict(HistoryStat),
        "horse_distance": defaultdict(HistoryStat),
        "jockey": defaultdict(HistoryStat),
        "trainer": defaultdict(HistoryStat),
    }
    for race_id, race_rows in sorted(grouped.items(), key=lambda item: (item[1][0]["race_date"], item[0])):
        field_size = len(race_rows)
        first = race_rows[0]
        race_date = date.fromisoformat(str(first["race_date"]))
        course = COURSE_CODES[race_id[8:10]]
        surface = _surface(first.get("surface"))
        distance_band = _distance_band(_number(first.get("distance")) or 0, first.get("race_name"))
        pending = []
        for row in race_rows:
            horse_name = _text(row.get("horse_name"), "unknown")
            jockey = _text(row.get("jockey"), "unknown")
            trainer = _text(row.get("trainer"), "unknown")
            pending.append((
                int(row["rank"]), states["horse"][horse_name],
                states["horse_course"][(horse_name, course)],
                states["horse_surface"][(horse_name, surface)],
                states["horse_distance"][(horse_name, distance_band)],
                states["jockey"][jockey], states["trainer"][trainer],
            ))
        for rank, *history_stats in pending:
            for stat in history_stats:
                stat.update(rank, field_size, race_date)
    return states


def _feature_vector(*, row, race_date, race_name, course, surface, distance, field_size,
                    horse, horse_course, horse_surface, horse_distance, jockey, trainer) -> list[float]:
    sex, age = _sex_age(row.get("sex_age"))
    horse_no = _number(row.get("horse_no")) or 0
    frame_no = _number(row.get("frame_no")) or 0
    carried = _float(row.get("weight_carried")) or 0.0
    days = min((race_date - horse.last_date).days, 365) if horse.last_date else 365
    base = [
        min(distance / 4000, 1.0), min(field_size / 18, 1.0), horse_no / max(field_size, 1),
        frame_no / 8, min(age / 10, 1.0), carried / 65, days / 365,
        float(horse.starts > 0), math.log1p(horse.starts), _rate(horse, "wins", 0.08),
        _rate(horse, "top3", 0.25), _finish_strength(horse), math.log1p(horse_course.starts),
        _rate(horse_course, "top3", 0.25), math.log1p(horse_surface.starts),
        _rate(horse_surface, "top3", 0.25), math.log1p(horse_distance.starts),
        _rate(horse_distance, "top3", 0.25), math.log1p(jockey.starts),
        _rate(jockey, "wins", 0.08), _rate(jockey, "top3", 0.25), math.log1p(trainer.starts),
        _rate(trainer, "wins", 0.08), _rate(trainer, "top3", 0.25),
        float(sex == "male"), float(sex == "female"), float(sex == "gelding"),
        float(surface == "turf"), float(surface == "dirt"),
        float("障害" in race_name), float("新馬" in race_name or "メイクデビュー" in race_name),
        float("未勝利" in race_name), float(any(key in race_name for key in ("オープン", "ステークス", "G1", "G2", "G3", "GI", "GII", "GIII"))),
    ]
    base.extend(float(course == value) for value in COURSE_CODES.values())
    return [round(float(value), 8) for value in base]


def _valid_row(row: dict) -> bool:
    race_id = str(row.get("race_id") or "")
    try:
        date.fromisoformat(str(row.get("race_date")))
        rank = int(row.get("rank"))
    except (TypeError, ValueError):
        return False
    return len(race_id) == 12 and race_id[8:10] in COURSE_CODES and rank > 0 and bool(row.get("horse_name"))


def _rate(stat: HistoryStat, field: str, prior: float) -> float:
    strength = 8.0
    return (float(getattr(stat, field)) + prior * strength) / (stat.starts + strength)


def _finish_strength(stat: HistoryStat) -> float:
    return 0.5 if stat.starts == 0 else 1.0 - stat.finish_fraction_sum / stat.starts


def _surface(value) -> str:
    text = str(value or "")
    return "turf" if "芝" in text or text == "turf" else "dirt" if "ダ" in text or text == "dirt" else "other"


def _distance_band(distance: int, race_name) -> str:
    if "障害" in str(race_name or ""):
        return "obstacle"
    return "short" if distance <= 1400 else "middle" if distance <= 2000 else "long"


def _sex_age(value) -> tuple[str, int]:
    text = str(value or "")
    sex = "male" if text.startswith("牡") else "female" if text.startswith("牝") else "gelding" if text.startswith("セ") else "unknown"
    match = re.search(r"\d+", text)
    return sex, int(match.group()) if match else 0


def _number(value) -> int | None:
    match = re.search(r"\d+", str(value or "").replace(",", ""))
    return int(match.group()) if match else None


def _float(value) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
    return float(match.group()) if match else None


def _text(value, default: str) -> str:
    text = str(value or "").strip()
    return text or default
