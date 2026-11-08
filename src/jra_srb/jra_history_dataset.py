"""概要: 保存済み公式結果から時点を守った履歴特徴量を生成する。
作成日: 不明
入力: 対象日、出馬表、選択backendの過去結果、任意の実行単位の履歴context。
出力: 履歴特徴量、明示dataset export。
実行例: uv run jra-srb --help
注意事項: 取得・保存を呼ぶ操作は外部通信やDB更新を伴う。SQL障害時に旧SQLiteへ切り替えない。
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, timedelta
import gzip
import json
import math
from pathlib import Path
import re
import sqlite3
from threading import Lock
from .storage import open_analysis_read
from .storage_config import storage_backend
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


@dataclass(frozen=True)
class LiveHistorySnapshot:
    """1回の実行で共有する対象日前の履歴行・生涯集計・近走集計を保持する。"""

    rows: list[dict]
    states: dict
    recent: dict[str, tuple[tuple[float, int], ...]]


class LiveHistoryContext:
    """同じ実行・日付・DBの履歴を初回だけ取得し、接続を共有せず集計を再利用する。"""

    def __init__(self, db_path: str | Path, *, target_date: date):
        """対象DBと日付を固定し、初回利用までSQLを実行しない。"""
        self.db_path = Path(db_path).resolve()
        self.target_date = target_date
        self._snapshot: LiveHistorySnapshot | None = None
        self._error: Exception | None = None
        self._lock = Lock()

    def get(self, db_path: str | Path, target_date: date) -> LiveHistorySnapshot:
        """日付・DBを照合し、最初の利用者だけがSQL取得と集計を行う。

        Args:
            db_path: context作成時と同じDBパス。
            target_date: 履歴に含めない当日。作成時の日付との一致が必要。
        Returns:
            呼出元で変更せず参照する共通履歴と集計。
        Raises:
            ValueError: 別の日付またはDBにcontextを流用した場合。
            RuntimeError: 同じ実行内で履歴取得が既に失敗した場合。
        Notes:
            初回失敗の元例外は呼出元へ伝え、後続利用時は再取得しない。
        """
        if self.db_path != Path(db_path).resolve() or self.target_date != target_date:
            raise ValueError("live history context date/database mismatch")
        with self._lock:
            if self._error is not None:
                raise RuntimeError("shared live history is unavailable for this run") from self._error
            if self._snapshot is None:
                try:
                    rows = _load_live_history_rows(self.db_path, target_date)
                    from .jra_recent_form_dataset import _result
                    recent = defaultdict(lambda: deque(maxlen=5))
                    for row in rows:
                        if row["rank"] is not None:
                            recent[str(row["horse_name"])].append(
                                _result(int(row["rank"]), int(row["history_field_size"])))
                    self._snapshot = LiveHistorySnapshot(
                        rows, _build_history_states(rows), {name: tuple(runs) for name, runs in recent.items()},
                    )
                except Exception as error:
                    self._error = error
                    raise
            return self._snapshot


def _load_live_history_rows(db_path: Path, target_date: date) -> list[dict]:
    """対象日前の共通履歴と結果表の頭数を1回のSELECTで読み、接続を閉じる。

    Args:
        db_path: 選択backendへ渡す解析DBのパス。
        target_date: この日以降の履歴行を返さない排他的な上限。
    Returns:
        日付・競走・馬番順の履歴行。history_field_sizeは結果表の全頭数。
    Notes:
        結果頭数はrunnerと結合する前に数え、近走特徴の従来の分母を維持する。
        SQL Serverだけ明示的にHASH JOINを指定し、SQLiteへfallbackしない。
    """
    query = """
        select r.race_id, r.race_date, r.race_name, r.surface, r.distance,
               ru.horse_no, ru.frame_no, ru.horse_name, ru.sex_age,
               ru.weight_carried, ru.jockey, ru.trainer, re.rank, re.history_field_size
        from races r
        join runners ru on ru.race_id = r.race_id
        join (select race_id, horse_no, rank,
                     count(*) over (partition by race_id) as history_field_size
              from result_entries) re
          on re.race_id = r.race_id and re.horse_no = ru.horse_no
        where length(r.race_id) = 12
          and substr(r.race_id, 9, 2) between '01' and '10'
          and r.source like 'https://www.jra.go.jp/%'
          and r.race_date < ?
          and exists (select 1 from payouts p where p.race_id = r.race_id)
        order by r.race_date, r.race_id, cast(ru.horse_no as integer)
    """
    connection = open_analysis_read(db_path)
    try:
        options = {"hash_join": True} if storage_backend() == "sqlserver" else {}
        return [dict(row) for row in connection.execute(query, (target_date.isoformat(),), **options).fetchall()]
    finally:
        connection.close()


def build_history_dataset(
    db_path: str | Path, *, through_date: date | None = None,
    history_context: LiveHistoryContext | None = None,
) -> tuple[list[dict], dict]:
    """過去datasetを作り、当日context指定時は取得済み行を使ってSQL再取得を避ける。

    Notes:
        context利用時のthrough_dateは対象日の前日に一致する必要がある。
        contextなしの既存学習/export経路は従来どおり独立して取得する。
    """
    if history_context is not None:
        if through_date != history_context.target_date - timedelta(days=1):
            raise ValueError("history dataset cutoff does not match live context")
        snapshot = history_context.get(db_path, history_context.target_date)
        records, metadata = build_history_dataset_from_rows(snapshot.rows)
        metadata["source_through_date"] = through_date.isoformat()
        return records, metadata
    path = Path(db_path).resolve()
    conn = open_analysis_read(path)
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
    history_context: LiveHistoryContext | None = None,
) -> list[dict]:
    """対象日前の集計から43特徴を作り、context指定時は同じ履歴を再取得しない。

    Args:
        db_path: 解析DBのパス。context作成時と一致する必要がある。
        target_date: 履歴へ含めない対象日。
        course: 対象レースの競馬場コード。
        card: レースごとの最新カード。
        history_context: 同じ実行内で共有する履歴。省略時は今回だけ取得する。
    Returns:
        馬別の43特徴、履歴件数と履歴上限を持つrecord。
    Notes:
        当日結果を除外する。共有集計へ当日馬の情報や欠測馬を追加しない。
    """
    if course not in COURSE_CODES.values():
        raise ValueError(f"unsupported JRA course={course}")
    context = history_context or LiveHistoryContext(db_path, target_date=target_date)
    states = context.get(db_path, target_date).states
    field_size = len(card.runners)
    surface = _surface(card.surface)
    distance = _number(card.distance) or 0
    distance_band = _distance_band(distance, card.race_name)
    records = []
    for runner in card.runners:
        horse_name = _text(runner.horse_name, "unknown")
        jockey = _text(runner.jockey, "unknown")
        trainer = _text(runner.trainer, "unknown")
        horse = states["horse"].get(horse_name, HistoryStat())
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
                horse_course=states["horse_course"].get((horse_name, course), HistoryStat()),
                horse_surface=states["horse_surface"].get((horse_name, surface), HistoryStat()),
                horse_distance=states["horse_distance"].get((horse_name, distance_band), HistoryStat()),
                jockey=states["jockey"].get(jockey, HistoryStat()),
                trainer=states["trainer"].get(trainer, HistoryStat()),
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
