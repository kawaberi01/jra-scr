from __future__ import annotations

from datetime import UTC, date, datetime
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .models import MeetingRace, OddsEntry, RaceCard, RaceOdds, RaceResult


class AnalysisSQLiteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists collection_runs (
                    run_id text primary key,
                    from_date text not null,
                    to_date text not null,
                    courses_json text not null,
                    include_card integer not null,
                    include_odds integer not null,
                    include_results integer not null,
                    odds_timing text not null,
                    status text not null,
                    created_at text not null,
                    finished_at text
                );

                create table if not exists races (
                    race_id text primary key,
                    race_date text not null,
                    course text not null,
                    race_no integer not null,
                    race_name text,
                    start_time text,
                    surface text,
                    distance text,
                    source text,
                    fetched_at text
                );
                create index if not exists idx_analysis_races_date_course
                on races (race_date, course, race_no);

                create table if not exists runners (
                    race_id text not null,
                    horse_no text not null,
                    frame_no text,
                    horse_name text not null,
                    sex_age text,
                    weight_carried text,
                    jockey text,
                    trainer text,
                    card_odds real,
                    card_popularity integer,
                    primary key (race_id, horse_no)
                );

                create table if not exists odds_snapshots (
                    snapshot_id text primary key,
                    race_id text not null,
                    bet_type text not null,
                    odds_timing text not null,
                    fetched_at text not null,
                    source text not null,
                    unique (race_id, bet_type, odds_timing)
                );

                create table if not exists odds_entries (
                    snapshot_id text not null,
                    race_id text not null,
                    bet_type text not null,
                    combination text not null,
                    combination_json text not null,
                    odds real,
                    odds_min real,
                    odds_max real,
                    popularity integer
                );
                create index if not exists idx_analysis_odds_entries_race_bet
                on odds_entries (race_id, bet_type);
                create index if not exists idx_analysis_odds_entries_bet_odds
                on odds_entries (bet_type, odds);
                create index if not exists idx_analysis_odds_entries_bet_popularity
                on odds_entries (bet_type, popularity);

                create table if not exists race_results (
                    race_id text primary key,
                    race_name text,
                    fetched_at text not null,
                    source text not null
                );

                create table if not exists result_entries (
                    race_id text not null,
                    rank integer,
                    horse_no text,
                    horse_name text not null,
                    jockey text,
                    finish_time text,
                    primary key (race_id, rank, horse_no)
                );

                create table if not exists payouts (
                    race_id text not null,
                    bet_type text not null,
                    combination text not null,
                    payout integer,
                    popularity integer
                );
                create index if not exists idx_analysis_payouts_race_bet
                on payouts (race_id, bet_type);

                create table if not exists collection_errors (
                    error_id text primary key,
                    run_id text,
                    race_id text,
                    race_date text not null,
                    course text not null,
                    race_no integer,
                    stage text not null,
                    error_type text not null,
                    error_message text not null,
                    created_at text not null
                );

                create table if not exists theory_versions (
                    theory_version text primary key,
                    parent_version text,
                    status text not null,
                    theory_yaml text not null,
                    notes text,
                    created_at text not null,
                    promoted_at text
                );

                create table if not exists predictions (
                    prediction_id text primary key,
                    race_id text not null,
                    theory_version text not null,
                    mode text,
                    budget integer,
                    pre_race_snapshot_json text not null,
                    prediction_json text not null,
                    created_at text not null
                );

                create table if not exists prediction_tickets (
                    ticket_id text primary key,
                    prediction_id text not null,
                    race_id text not null,
                    bucket text,
                    bet_type text not null,
                    selection text not null,
                    selection_json text not null,
                    amount integer not null,
                    reason text
                );

                create table if not exists evaluations (
                    evaluation_id text primary key,
                    prediction_id text not null,
                    race_id text not null,
                    theory_version text not null,
                    total_bet integer not null,
                    total_payout integer not null,
                    return_rate real not null,
                    hit integer not null,
                    gami integer not null,
                    axis_in_top3 integer,
                    middle_hole_in_top3 integer,
                    firework_hit integer,
                    max_odds_selected real,
                    evaluation_json text not null,
                    created_at text not null
                );

                create table if not exists evaluation_ticket_results (
                    ticket_result_id text primary key,
                    evaluation_id text not null,
                    ticket_id text,
                    bucket text,
                    bet_type text not null,
                    selection text not null,
                    amount integer not null,
                    hit integer not null,
                    payout integer not null
                );
                """
            )

    def create_run(
        self,
        from_date: date,
        to_date: date,
        courses: list[str],
        include_card: bool,
        include_odds: bool,
        include_results: bool,
        odds_timing: str,
    ) -> str:
        run_id = str(uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                insert into collection_runs
                (run_id, from_date, to_date, courses_json, include_card, include_odds,
                 include_results, odds_timing, status, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    from_date.isoformat(),
                    to_date.isoformat(),
                    json.dumps(courses, ensure_ascii=False),
                    int(include_card),
                    int(include_odds),
                    int(include_results),
                    odds_timing,
                    "running",
                    _now(),
                ),
            )
        return run_id

    def finish_run(self, run_id: str, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "update collection_runs set status = ?, finished_at = ? where run_id = ?",
                (status, _now(), run_id),
            )

    def write_race(
        self,
        target_date: date,
        course: str,
        race: MeetingRace,
        source: str | None = None,
        fetched_at: datetime | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into races
                (race_id, race_date, course, race_no, race_name, start_time, source, fetched_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(race_id) do update set
                    race_date = excluded.race_date,
                    course = excluded.course,
                    race_no = excluded.race_no,
                    race_name = coalesce(excluded.race_name, races.race_name),
                    start_time = coalesce(excluded.start_time, races.start_time),
                    source = coalesce(excluded.source, races.source),
                    fetched_at = coalesce(excluded.fetched_at, races.fetched_at)
                """,
                (
                    race.race_id,
                    target_date.isoformat(),
                    course,
                    race.race_no,
                    race.race_name,
                    race.start_time,
                    source,
                    _dt(fetched_at),
                ),
            )

    def write_card(self, target_date: date, course: str, race_no: int, card: RaceCard) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into races
                (race_id, race_date, course, race_no, race_name, start_time, surface, distance, source, fetched_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(race_id) do update set
                    race_date = excluded.race_date,
                    course = excluded.course,
                    race_no = excluded.race_no,
                    race_name = coalesce(excluded.race_name, races.race_name),
                    start_time = coalesce(excluded.start_time, races.start_time),
                    surface = coalesce(excluded.surface, races.surface),
                    distance = coalesce(excluded.distance, races.distance),
                    source = excluded.source,
                    fetched_at = excluded.fetched_at
                """,
                (
                    card.race_id,
                    target_date.isoformat(),
                    card.course or course,
                    race_no,
                    card.race_name,
                    card.start_time,
                    card.surface,
                    card.distance,
                    card.source,
                    _dt(card.fetched_at),
                ),
            )
            for runner in card.runners:
                horse_no = runner.horse_no or runner.horse_name
                conn.execute(
                    """
                    insert into runners
                    (race_id, horse_no, frame_no, horse_name, sex_age, weight_carried, jockey,
                     trainer, card_odds, card_popularity)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(race_id, horse_no) do update set
                        frame_no = excluded.frame_no,
                        horse_name = excluded.horse_name,
                        sex_age = excluded.sex_age,
                        weight_carried = excluded.weight_carried,
                        jockey = excluded.jockey,
                        trainer = excluded.trainer,
                        card_odds = excluded.card_odds,
                        card_popularity = excluded.card_popularity
                    """,
                    (
                        card.race_id,
                        horse_no,
                        runner.frame_no,
                        runner.horse_name,
                        runner.sex_age,
                        runner.weight_carried,
                        runner.jockey,
                        runner.trainer,
                        _parse_float(runner.odds),
                        _parse_int(runner.popularity),
                    ),
                )

    def write_odds(self, odds: RaceOdds, bet_type: str | None = None, odds_timing: str = "final_or_near_final") -> None:
        entries_by_type = _odds_entries_by_type(odds, bet_type)
        with self._connect() as conn:
            for current_bet_type, entries in entries_by_type.items():
                snapshot_id = f"{odds.race_id}:{current_bet_type}:{odds_timing}"
                conn.execute(
                    """
                    insert into odds_snapshots
                    (snapshot_id, race_id, bet_type, odds_timing, fetched_at, source)
                    values (?, ?, ?, ?, ?, ?)
                    on conflict(race_id, bet_type, odds_timing) do update set
                        fetched_at = excluded.fetched_at,
                        source = excluded.source
                    """,
                    (
                        snapshot_id,
                        odds.race_id,
                        current_bet_type,
                        odds_timing,
                        _dt(odds.fetched_at),
                        odds.source,
                    ),
                )
                conn.execute("delete from odds_entries where snapshot_id = ?", (snapshot_id,))
                for entry in entries:
                    combination = "-".join(entry.combination)
                    conn.execute(
                        """
                        insert into odds_entries
                        (snapshot_id, race_id, bet_type, combination, combination_json,
                         odds, odds_min, odds_max, popularity)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            snapshot_id,
                            odds.race_id,
                            current_bet_type,
                            combination,
                            json.dumps(entry.combination, ensure_ascii=False),
                            _parse_float(entry.odds),
                            _parse_float(entry.odds_min),
                            _parse_float(entry.odds_max),
                            _parse_int(entry.popularity),
                        ),
                    )

    def write_result(self, result: RaceResult) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into race_results (race_id, race_name, fetched_at, source)
                values (?, ?, ?, ?)
                on conflict(race_id) do update set
                    race_name = excluded.race_name,
                    fetched_at = excluded.fetched_at,
                    source = excluded.source
                """,
                (result.race_id, result.race_name, _dt(result.fetched_at), result.source),
            )
            conn.execute("delete from result_entries where race_id = ?", (result.race_id,))
            for entry in result.results:
                conn.execute(
                    """
                    insert into result_entries
                    (race_id, rank, horse_no, horse_name, jockey, finish_time)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.race_id,
                        _parse_int(entry.rank),
                        entry.horse_no,
                        entry.horse_name,
                        entry.jockey,
                        entry.time,
                    ),
                )
            conn.execute("delete from payouts where race_id = ?", (result.race_id,))
            for payout in result.payouts:
                conn.execute(
                    """
                    insert into payouts (race_id, bet_type, combination, payout, popularity)
                    values (?, ?, ?, ?, ?)
                    """,
                    (
                        result.race_id,
                        payout.bet_type,
                        payout.combination,
                        _parse_int(payout.payout),
                        _parse_int(payout.popularity),
                    ),
                )

    def write_error(
        self,
        run_id: str | None,
        target_date: date,
        course: str,
        stage: str,
        exc: Exception,
        race_id: str | None = None,
        race_no: int | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into collection_errors
                (error_id, run_id, race_id, race_date, course, race_no, stage,
                 error_type, error_message, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid4()),
                    run_id,
                    race_id,
                    target_date.isoformat(),
                    course,
                    race_no,
                    stage,
                    type(exc).__name__,
                    str(exc),
                    _now(),
                ),
            )

    def get_pre_race_snapshot(self, race_id: str) -> dict:
        with self._connect() as conn:
            race = conn.execute("select * from races where race_id = ?", (race_id,)).fetchone()
            if race is None:
                raise LookupError(f"race not found for race_id={race_id}")
            runners = conn.execute(
                "select * from runners where race_id = ? order by cast(horse_no as integer), horse_no",
                (race_id,),
            ).fetchall()
            snapshots = conn.execute(
                "select * from odds_snapshots where race_id = ? order by bet_type, odds_timing",
                (race_id,),
            ).fetchall()
            odds = []
            for snapshot in snapshots:
                entries = conn.execute(
                    """
                    select bet_type, combination, combination_json, odds, odds_min, odds_max, popularity
                    from odds_entries
                    where snapshot_id = ?
                    order by popularity, combination
                    """,
                    (snapshot["snapshot_id"],),
                ).fetchall()
                odds.append(
                    {
                        "snapshot_id": snapshot["snapshot_id"],
                        "race_id": snapshot["race_id"],
                        "bet_type": snapshot["bet_type"],
                        "odds_timing": snapshot["odds_timing"],
                        "fetched_at": snapshot["fetched_at"],
                        "source": snapshot["source"],
                        "entries": [_row_to_dict(entry) for entry in entries],
                    }
                )
        return {
            "race": _row_to_dict(race),
            "runners": [_row_to_dict(runner) for runner in runners],
            "odds": odds,
        }

    def count_rows(self, table: str) -> int:
        if not re.fullmatch(r"[a-z_]+", table):
            raise ValueError(f"invalid table name={table}")
        with self._connect() as conn:
            return int(conn.execute(f"select count(*) from {table}").fetchone()[0])

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def _odds_entries_by_type(odds: RaceOdds, bet_type: str | None) -> dict[str, list[OddsEntry]]:
    if odds.odds:
        return {key: list(value) for key, value in odds.odds.items()}
    current_bet_type = bet_type or odds.bet_type or "unknown"
    return {current_bet_type: list(odds.entries)}


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    normalized = value.replace(",", "").strip()
    match = re.search(r"\d+(?:\.\d+)?", normalized)
    if match is None:
        return None
    return float(match.group(0))


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.replace(",", "").strip()
    match = re.search(r"\d+", normalized)
    if match is None:
        return None
    return int(match.group(0))


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)
