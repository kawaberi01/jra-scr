from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import sqlite3


LAP_STYLE_FEATURE_NAMES = [
    "style_log_starts", "style_mean_early_position", "style_last_early_position",
    "style_mean_closing_strength", "style_last_closing_strength", "style_mean_lap_shape",
    "field_expected_early_position", "style_vs_field_early_position",
    "style_pace_interaction", "style_has_position_history", "style_has_closing_history",
    "pace_condition_log_races", "pace_condition_mean_lap_shape", "field_front_runner_share",
    "field_early_position_spread", "pace_front_runner_interaction",
]


@dataclass
class StyleHistory:
    starts: int = 0
    position_sum: float = 0.0
    closing_sum: float = 0.0
    lap_shape_sum: float = 0.0
    position_count: int = 0
    closing_count: int = 0
    lap_shape_count: int = 0
    last_position: float | None = None
    last_closing: float | None = None

    def mean_position(self) -> float:
        return self.position_sum / self.position_count if self.position_count else 0.5

    def mean_closing(self) -> float:
        return self.closing_sum / self.closing_count if self.closing_count else 0.5

    def mean_lap_shape(self) -> float:
        return self.lap_shape_sum / self.lap_shape_count if self.lap_shape_count else 0.0

    def update(self, position: float | None, closing: float | None, lap_shape: float | None) -> None:
        self.starts += 1
        if position is not None:
            self.position_sum += position
            self.position_count += 1
            self.last_position = position
        if closing is not None:
            self.closing_sum += closing
            self.closing_count += 1
            self.last_closing = closing
        if lap_shape is not None:
            self.lap_shape_sum += lap_shape
            self.lap_shape_count += 1


@dataclass
class PaceHistory:
    races: int = 0
    lap_shape_sum: float = 0.0

    def mean_lap_shape(self) -> float:
        return self.lap_shape_sum / self.races if self.races else 0.0

    def update(self, lap_shape: float | None) -> None:
        if lap_shape is not None:
            self.races += 1
            self.lap_shape_sum += lap_shape


def append_lap_style_features(records: list[dict], db_path: str | Path) -> tuple[list[dict], dict]:
    """Append leakage-safe historical pace/style features to history records.

    All records on a race date are featurized before that date's observed results
    update the horse histories. The target race's lap and passage data therefore
    never enter its own feature vector.
    """
    extras = _load_extras(db_path)
    by_date: dict[str, list[dict]] = defaultdict(list)
    by_race: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_date[record["race_date"]].append(record)
        by_race[record["race_id"]].append(record)
    race_observations = {race_id: _race_observations(runners, extras) for race_id, runners in by_race.items()}
    histories: dict[str, StyleHistory] = defaultdict(StyleHistory)
    pace_histories: dict[tuple[str, str, str], PaceHistory] = defaultdict(PaceHistory)
    output: list[dict] = []

    for race_date in sorted(by_date):
        day_records = by_date[race_date]
        for race_id, runners in _group_by_race(day_records).items():
            expected = _field_expected_position(runners, histories)
            front_share, position_spread = _field_style_shape(runners, histories)
            condition_history = pace_histories[_pace_condition(runners[0])]
            for record in runners:
                history = histories[record["horse_name"]]
                position = history.mean_position()
                closing = history.mean_closing()
                features = [
                    math.log1p(history.starts), position, history.last_position if history.last_position is not None else 0.5,
                    closing, history.last_closing if history.last_closing is not None else 0.5, history.mean_lap_shape(),
                    expected, position - expected, (position - expected) * history.mean_lap_shape(),
                    float(history.position_count > 0), float(history.closing_count > 0),
                    math.log1p(condition_history.races), condition_history.mean_lap_shape(), front_share,
                    position_spread, condition_history.mean_lap_shape() * front_share,
                ]
                output.append({**record, "features": [*record["features"], *features]})

        for race_id, runners in _group_by_race(day_records).items():
            observed = race_observations[race_id]
            for record in runners:
                values = observed["horses"].get(str(record["horse_no"]), {})
                histories[record["horse_name"]].update(values.get("position"), values.get("closing"), observed["lap_shape"])
            pace_histories[_pace_condition(runners[0])].update(observed["lap_shape"])

    lap_races = len({race_id for (race_id, _), extra in extras.items() if _lap_shape(extra["laps"]) is not None})
    return output, {"feature_names": LAP_STYLE_FEATURE_NAMES, "runner_extras": len(extras), "race_lap_races": lap_races}


def _load_extras(db_path: str | Path) -> dict[tuple[str, str], dict]:
    path = Path(db_path).resolve()
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            """
            select m.jra_race_id, ne.horse_no, ne.corner_order, ne.final_3f, rr.race_laps_json
            from netkeiba_race_mappings m
            join netkeiba_result_entries ne on ne.netkeiba_race_id=m.netkeiba_race_id
            join netkeiba_race_results rr on rr.netkeiba_race_id=ne.netkeiba_race_id
            where m.jra_race_id is not null and m.mapping_status='mapped'
            """
        ).fetchall()
    return {(str(row[0]), str(row[1])): {"corner_order": row[2], "final_3f": row[3], "laps": row[4]} for row in rows}


def _race_observations(runners: list[dict], extras: dict[tuple[str, str], dict]) -> dict:
    race_id = runners[0]["race_id"]
    field_size = len(runners)
    by_horse: dict[str, dict] = {}
    finals: list[tuple[str, float]] = []
    laps = None
    for record in runners:
        extra = extras.get((race_id, str(record["horse_no"])), {})
        position = _first_position(extra.get("corner_order"))
        by_horse[str(record["horse_no"])] = {"position": position / field_size if position is not None else None}
        if extra.get("final_3f") is not None:
            finals.append((str(record["horse_no"]), float(extra["final_3f"])))
        if laps is None:
            laps = _lap_shape(extra.get("laps"))
    if len(finals) >= 2:
        ordered = sorted(finals, key=lambda item: item[1])
        for index, (horse_no, _) in enumerate(ordered):
            by_horse[horse_no]["closing"] = 1.0 - index / (len(ordered) - 1)
    return {"horses": by_horse, "lap_shape": laps}


def _field_expected_position(runners: list[dict], histories: dict[str, StyleHistory]) -> float:
    values = [histories[record["horse_name"]].mean_position() for record in runners if histories[record["horse_name"]].position_count]
    return sum(values) / len(values) if values else 0.5


def _field_style_shape(runners: list[dict], histories: dict[str, StyleHistory]) -> tuple[float, float]:
    values = [histories[record["horse_name"]].mean_position() for record in runners if histories[record["horse_name"]].position_count]
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    return sum(value <= 0.35 for value in values) / len(values), math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _pace_condition(record: dict) -> tuple[str, str, str]:
    distance = int(record.get("distance") or 0)
    distance_band = "short" if distance <= 1400 else "mile" if distance <= 1800 else "middle" if distance <= 2200 else "long"
    return str(record.get("course") or "unknown"), str(record.get("surface") or "unknown"), distance_band


def _group_by_race(records: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        grouped[record["race_id"]].append(record)
    return grouped


def _first_position(value: object) -> int | None:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group()) if match else None


def _lap_shape(value: object) -> float | None:
    try:
        laps = [float(item) for item in json.loads(str(value or "[]"))]
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if len(laps) < 4:
        return None
    midpoint = len(laps) // 2
    return sum(laps[midpoint:]) / len(laps[midpoint:]) - sum(laps[:midpoint]) / len(laps[:midpoint])
