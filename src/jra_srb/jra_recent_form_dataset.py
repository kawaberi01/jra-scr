from __future__ import annotations

from collections import defaultdict, deque
from datetime import date
from pathlib import Path
import sqlite3

from .jra_history_dataset import FEATURE_NAMES


RECENT_FORM_FEATURE_NAMES = [
    "form_history_count_scaled",
    "form_last_finish_strength",
    "form_recent3_finish_strength",
    "form_recent5_finish_strength",
    "form_recent3_top3_rate",
    "form_recent3_vs_career_strength",
]
RECENT_FORM_SCHEMA = [*FEATURE_NAMES, *RECENT_FORM_FEATURE_NAMES]


def append_recent_form_features(records: list[dict]) -> list[dict]:
    by_race: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_race[record["race_id"]].append(record)
    histories: dict[str, deque[tuple[float, int]]] = defaultdict(lambda: deque(maxlen=5))
    output = []
    for race_id, runners in sorted(by_race.items(), key=lambda item: (item[1][0]["race_date"], item[0])):
        for record in runners:
            output.append(_append(record, histories[record["horse_name"]]))
        field_size = len(runners)
        for record in runners:
            histories[record["horse_name"]].append(_result(int(record["actual_rank"]), field_size))
    return output


def append_recent_form_live_features(
    records: list[dict], db_path: str | Path, *, target_date: date,
) -> list[dict]:
    horse_names = sorted({record["horse_name"] for record in records})
    histories: dict[str, deque[tuple[float, int]]] = defaultdict(lambda: deque(maxlen=5))
    if horse_names:
        placeholders = ",".join("?" for _ in horse_names)
        path = Path(db_path).resolve()
        with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
            rows = connection.execute(
                f"""
                select ru.horse_name, re.rank,
                       (select count(*) from result_entries x where x.race_id=r.race_id) as field_size
                from races r
                join runners ru on ru.race_id=r.race_id
                join result_entries re on re.race_id=r.race_id and re.horse_no=ru.horse_no
                where r.race_date < ? and ru.horse_name in ({placeholders})
                  and length(r.race_id)=12 and substr(r.race_id,9,2) between '01' and '10'
                  and r.source like 'https://www.jra.go.jp/%'
                  and exists (select 1 from payouts p where p.race_id=r.race_id)
                order by r.race_date, r.race_id
                """,
                (target_date.isoformat(), *horse_names),
            ).fetchall()
        for horse_name, rank, field_size in rows:
            histories[str(horse_name)].append(_result(int(rank), int(field_size)))
    return [_append(record, histories[record["horse_name"]]) for record in records]


def _append(record: dict, recent: deque[tuple[float, int]]) -> dict:
    last_strength = recent[-1][0] if recent else 0.5
    recent3 = list(recent)[-3:]
    recent3_strength = _mean([item[0] for item in recent3], 0.5)
    recent5_strength = _mean([item[0] for item in recent], 0.5)
    recent3_top3 = _mean([float(item[1]) for item in recent3], 0.25)
    career_strength = float(record["features"][FEATURE_NAMES.index("horse_finish_strength")])
    features = [
        min(len(recent), 5) / 5,
        last_strength,
        recent3_strength,
        recent5_strength,
        recent3_top3,
        recent3_strength - career_strength if recent else 0.0,
    ]
    return {**record, "features": [*record["features"], *features]}


def _result(rank: int, field_size: int) -> tuple[float, int]:
    return 1.0 - (rank - 1) / max(field_size - 1, 1), int(rank <= 3)


def _mean(values: list[float], default: float) -> float:
    return sum(values) / len(values) if values else default
