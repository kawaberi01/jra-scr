from __future__ import annotations

from datetime import UTC, date, datetime
from itertools import combinations
import json
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from .errors import BadRequestError
from .models import (
    BetRecord,
    BetRecordCreateRequest,
    BetRecordPage,
    BetRecordResult,
    BetRecordSettlement,
    BetRecordResultTicket,
    BetRecordTicket,
    MeetingRace,
    NetkeibaRaceResult,
    OddsEntry,
    RaceCard,
    RaceOdds,
    RaceResult,
)


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

                create table if not exists netkeiba_race_results (
                    netkeiba_race_id text primary key,
                    jra_race_id text,
                    race_date text,
                    course text,
                    race_no integer,
                    race_name text,
                    surface text,
                    distance text,
                    direction text,
                    weather text,
                    track_condition text,
                    source text not null,
                    fetched_at text not null,
                    raw_json text
                );
                create index if not exists idx_netkeiba_race_results_jra_race
                on netkeiba_race_results (jra_race_id);
                create index if not exists idx_netkeiba_race_results_date_course
                on netkeiba_race_results (race_date, course, race_no);

                create table if not exists netkeiba_result_entries (
                    netkeiba_race_id text not null,
                    jra_race_id text,
                    rank integer,
                    frame_no text,
                    horse_no text,
                    horse_name text not null,
                    sex_age text,
                    weight_carried text,
                    jockey text,
                    trainer text,
                    horse_weight integer,
                    horse_weight_diff integer,
                    finish_time text,
                    margin text,
                    corner_order text,
                    final_3f real,
                    win_odds real,
                    popularity integer,
                    primary key (netkeiba_race_id, rank, horse_no)
                );
                create index if not exists idx_netkeiba_result_entries_jra_race
                on netkeiba_result_entries (jra_race_id);

                create table if not exists netkeiba_payouts (
                    netkeiba_race_id text not null,
                    jra_race_id text,
                    bet_type text not null,
                    combination text not null,
                    payout integer,
                    popularity integer
                );
                create index if not exists idx_netkeiba_payouts_race_bet
                on netkeiba_payouts (netkeiba_race_id, bet_type);

                create table if not exists netkeiba_odds_entries (
                    netkeiba_race_id text not null,
                    jra_race_id text,
                    bet_type text not null,
                    combination text not null,
                    combination_json text not null,
                    odds real,
                    odds_min real,
                    odds_max real,
                    popularity integer,
                    fetched_at text not null,
                    source text not null,
                    primary key (netkeiba_race_id, bet_type, combination)
                );
                create index if not exists idx_netkeiba_odds_entries_jra_race
                on netkeiba_odds_entries (jra_race_id);

                create table if not exists netkeiba_race_mappings (
                    jra_race_id text primary key,
                    netkeiba_race_id text,
                    race_date text,
                    course text,
                    race_no integer,
                    mapping_status text,
                    mapping_note text,
                    created_at text not null,
                    updated_at text not null
                );
                create index if not exists idx_netkeiba_race_mappings_date
                on netkeiba_race_mappings (race_date, course, race_no);
                create index if not exists idx_netkeiba_race_mappings_status
                on netkeiba_race_mappings (mapping_status);

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

                create table if not exists bet_records (
                    bet_record_id text primary key,
                    race_id text not null,
                    prediction_id text,
                    theory_version text,
                    decision_source text not null,
                    purchased_at text,
                    total_amount integer not null,
                    note text,
                    created_at text not null,
                    updated_at text not null
                );
                create index if not exists idx_bet_records_race
                on bet_records (race_id);
                create index if not exists idx_bet_records_prediction
                on bet_records (prediction_id);

                create table if not exists bet_record_tickets (
                    bet_ticket_id text primary key,
                    bet_record_id text not null,
                    race_id text not null,
                    prediction_ticket_id text,
                    bucket text,
                    bet_type text not null,
                    selection text not null,
                    selection_json text not null,
                    amount integer not null,
                    odds_at_buy real,
                    is_box_expanded integer not null,
                    reason text,
                    created_at text not null
                );
                create index if not exists idx_bet_record_tickets_record
                on bet_record_tickets (bet_record_id);
                create index if not exists idx_bet_record_tickets_race_bet
                on bet_record_tickets (race_id, bet_type, selection);

                create table if not exists bet_record_results (
                    bet_record_result_id text primary key,
                    bet_record_id text not null unique,
                    race_id text not null,
                    total_bet integer not null,
                    total_payout integer not null,
                    return_rate real not null,
                    hit integer not null,
                    settled_at text not null,
                    result_json text not null,
                    created_at text not null
                );
                create index if not exists idx_bet_record_results_race
                on bet_record_results (race_id);
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

    def has_card(self, race_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                select 1
                from races r
                where r.race_id = ?
                  and exists (
                    select 1
                    from runners ru
                    where ru.race_id = r.race_id
                  )
                limit 1
                """,
                (race_id,),
            ).fetchone()
        return row is not None

    def has_result(self, race_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                select 1
                from race_results rr
                where rr.race_id = ?
                  and exists (
                    select 1
                    from result_entries re
                    where re.race_id = rr.race_id
                  )
                  and exists (
                    select 1
                    from payouts p
                    where p.race_id = rr.race_id
                  )
                limit 1
                """,
                (race_id,),
            ).fetchone()
        return row is not None

    def has_odds_snapshot(self, race_id: str, bet_type: str, odds_timing: str = "final_or_near_final") -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                select 1
                from odds_snapshots os
                where os.race_id = ?
                  and os.bet_type = ?
                  and os.odds_timing = ?
                  and exists (
                    select 1
                    from odds_entries oe
                    where oe.snapshot_id = os.snapshot_id
                  )
                limit 1
                """,
                (race_id, bet_type, odds_timing),
            ).fetchone()
        return row is not None

    def has_netkeiba_result(self, netkeiba_race_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                select 1
                from netkeiba_race_results rr
                where rr.netkeiba_race_id = ?
                  and exists (
                    select 1
                    from netkeiba_result_entries re
                    where re.netkeiba_race_id = rr.netkeiba_race_id
                  )
                  and exists (
                    select 1
                    from netkeiba_payouts p
                    where p.netkeiba_race_id = rr.netkeiba_race_id
                  )
                limit 1
                """,
                (netkeiba_race_id,),
            ).fetchone()
        return row is not None

    def write_netkeiba_result(
        self,
        result: NetkeibaRaceResult,
        jra_race_id: str | None = None,
        raw_json: str | None = None,
    ) -> None:
        raw_payload = raw_json
        if raw_payload is None:
            raw_payload = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                insert into netkeiba_race_results
                (netkeiba_race_id, jra_race_id, race_date, course, race_no, race_name,
                 surface, distance, direction, weather, track_condition, source, fetched_at, raw_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(netkeiba_race_id) do update set
                    jra_race_id = coalesce(excluded.jra_race_id, netkeiba_race_results.jra_race_id),
                    race_date = coalesce(excluded.race_date, netkeiba_race_results.race_date),
                    course = coalesce(excluded.course, netkeiba_race_results.course),
                    race_no = coalesce(excluded.race_no, netkeiba_race_results.race_no),
                    race_name = excluded.race_name,
                    surface = excluded.surface,
                    distance = excluded.distance,
                    direction = excluded.direction,
                    weather = excluded.weather,
                    track_condition = excluded.track_condition,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at,
                    raw_json = excluded.raw_json
                """,
                (
                    result.race_id,
                    jra_race_id,
                    result.date,
                    result.course,
                    _parse_int(result.race_no),
                    result.race_name,
                    result.surface,
                    result.distance,
                    result.direction,
                    result.weather,
                    result.track_condition,
                    result.source,
                    _dt(result.fetched_at),
                    raw_payload,
                ),
            )
            conn.execute("delete from netkeiba_result_entries where netkeiba_race_id = ?", (result.race_id,))
            for entry in result.results:
                conn.execute(
                    """
                    insert into netkeiba_result_entries
                    (netkeiba_race_id, jra_race_id, rank, frame_no, horse_no, horse_name,
                     sex_age, weight_carried, jockey, trainer, horse_weight, horse_weight_diff,
                     finish_time, margin, corner_order, final_3f, win_odds, popularity)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.race_id,
                        jra_race_id,
                        _parse_int(entry.rank),
                        entry.frame_no,
                        entry.horse_no,
                        entry.horse_name,
                        entry.sex_age,
                        entry.weight_carried,
                        entry.jockey,
                        entry.trainer,
                        _parse_int(entry.horse_weight),
                        _parse_signed_int(entry.horse_weight_diff),
                        entry.finish_time,
                        entry.margin,
                        entry.corner_order,
                        _parse_float(entry.final_3f),
                        _parse_float(entry.win_odds),
                        _parse_int(entry.popularity),
                    ),
                )
            conn.execute("delete from netkeiba_payouts where netkeiba_race_id = ?", (result.race_id,))
            for payout in result.payouts:
                conn.execute(
                    """
                    insert into netkeiba_payouts
                    (netkeiba_race_id, jra_race_id, bet_type, combination, payout, popularity)
                    values (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result.race_id,
                        jra_race_id,
                        payout.bet_type,
                        payout.combination,
                        _parse_int(payout.payout),
                        _parse_int(payout.popularity),
                    ),
                )

    def has_netkeiba_odds_entry(self, netkeiba_race_id: str, bet_type: str, combination: list[str]) -> bool:
        stored_combination = "-".join(_normalize_combination_items(combination))
        with self._connect() as conn:
            row = conn.execute(
                """
                select 1
                from netkeiba_odds_entries
                where netkeiba_race_id = ? and bet_type = ? and combination = ?
                limit 1
                """,
                (netkeiba_race_id, bet_type, stored_combination),
            ).fetchone()
        return row is not None

    def write_netkeiba_odds(
        self,
        odds: RaceOdds,
        jra_race_id: str | None = None,
        bet_type: str | None = None,
    ) -> None:
        entries_by_type = _netkeiba_odds_entries_by_type(odds, bet_type)
        with self._connect() as conn:
            for current_bet_type, entries in entries_by_type.items():
                for entry in entries:
                    normalized_combination = _normalize_combination_items(entry.combination)
                    combination = "-".join(normalized_combination)
                    conn.execute(
                        """
                        insert into netkeiba_odds_entries
                        (netkeiba_race_id, jra_race_id, bet_type, combination, combination_json,
                         odds, odds_min, odds_max, popularity, fetched_at, source)
                        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        on conflict(netkeiba_race_id, bet_type, combination) do update set
                            jra_race_id = coalesce(excluded.jra_race_id, netkeiba_odds_entries.jra_race_id),
                            combination_json = excluded.combination_json,
                            odds = excluded.odds,
                            odds_min = excluded.odds_min,
                            odds_max = excluded.odds_max,
                            popularity = excluded.popularity,
                            fetched_at = excluded.fetched_at,
                            source = excluded.source
                        """,
                        (
                            odds.race_id,
                            jra_race_id,
                            current_bet_type,
                            combination,
                            json.dumps(normalized_combination, ensure_ascii=False),
                            _parse_float(entry.odds),
                            _parse_float(entry.odds_min),
                            _parse_float(entry.odds_max),
                            _parse_int(entry.popularity),
                            _dt(odds.fetched_at),
                            odds.source,
                        ),
                    )

    def write_netkeiba_race_mappings(self, mappings: list[dict[str, str]]) -> None:
        now = _now()
        with self._connect() as conn:
            for mapping in mappings:
                conn.execute(
                    """
                    insert into netkeiba_race_mappings
                    (jra_race_id, netkeiba_race_id, race_date, course, race_no,
                     mapping_status, mapping_note, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    on conflict(jra_race_id) do update set
                        netkeiba_race_id = excluded.netkeiba_race_id,
                        race_date = excluded.race_date,
                        course = excluded.course,
                        race_no = excluded.race_no,
                        mapping_status = excluded.mapping_status,
                        mapping_note = excluded.mapping_note,
                        updated_at = excluded.updated_at
                    """,
                    (
                        mapping["jra_race_id"],
                        mapping.get("netkeiba_race_id") or None,
                        mapping.get("race_date") or None,
                        mapping.get("course") or None,
                        _parse_int(mapping.get("race_no")),
                        mapping.get("mapping_status") or None,
                        mapping.get("mapping_note") or None,
                        now,
                        now,
                    ),
                )

    def list_netkeiba_race_mappings(
        self,
        from_date: date,
        to_date: date,
        limit: int | None = None,
    ) -> list[dict]:
        params: list[object] = [from_date.isoformat(), to_date.isoformat()]
        limit_sql = ""
        if limit is not None:
            limit_sql = "limit ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select jra_race_id, netkeiba_race_id, race_date, course, race_no,
                       mapping_status, mapping_note
                from netkeiba_race_mappings
                where race_date >= ? and race_date <= ?
                order by race_date, course, race_no
                {limit_sql}
                """,
                params,
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def create_bet_record(self, request: BetRecordCreateRequest | dict) -> BetRecord:
        request = BetRecordCreateRequest.model_validate(request)
        expanded_tickets = _expand_bet_record_tickets(request)
        total_amount = sum(ticket["amount"] for ticket in expanded_tickets)
        if total_amount != request.total_amount:
            raise BadRequestError(
                f"total_amount mismatch: request={request.total_amount} expanded={total_amount}"
            )

        bet_record_id = str(uuid4())
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into bet_records
                (bet_record_id, race_id, prediction_id, theory_version, decision_source,
                 purchased_at, total_amount, note, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bet_record_id,
                    request.race_id,
                    request.prediction_id,
                    request.theory_version,
                    str(request.decision_source),
                    _dt(request.purchased_at),
                    request.total_amount,
                    request.note,
                    now,
                    now,
                ),
            )
            for ticket in expanded_tickets:
                conn.execute(
                    """
                    insert into bet_record_tickets
                    (bet_ticket_id, bet_record_id, race_id, prediction_ticket_id, bucket,
                     bet_type, selection, selection_json, amount, odds_at_buy,
                     is_box_expanded, reason, created_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ticket["bet_ticket_id"],
                        bet_record_id,
                        request.race_id,
                        ticket["prediction_ticket_id"],
                        ticket["bucket"],
                        ticket["bet_type"],
                        ticket["selection"],
                        json.dumps(ticket["selection_json"], ensure_ascii=False),
                        ticket["amount"],
                        ticket["odds_at_buy"],
                        int(ticket["is_box_expanded"]),
                        ticket["reason"],
                        now,
                    ),
                )
        return self.get_bet_record(bet_record_id)

    def get_bet_record(self, bet_record_id: str) -> BetRecord:
        with self._connect() as conn:
            record = conn.execute(
                "select * from bet_records where bet_record_id = ?",
                (bet_record_id,),
            ).fetchone()
            if record is None:
                raise LookupError(f"bet record not found for bet_record_id={bet_record_id}")

            ticket_rows = conn.execute(
                """
                select *
                from bet_record_tickets
                where bet_record_id = ?
                order by rowid
                """,
                (bet_record_id,),
            ).fetchall()

            prediction = None
            prediction_tickets: list[dict] = []
            if record["prediction_id"]:
                prediction_row = conn.execute(
                    """
                    select prediction_id, race_id, theory_version, mode, budget,
                           pre_race_snapshot_json, prediction_json, created_at
                    from predictions
                    where prediction_id = ?
                    """,
                    (record["prediction_id"],),
                ).fetchone()
                if prediction_row is not None:
                    prediction = _row_to_dict(prediction_row)
                    prediction["pre_race_snapshot_json"] = json.loads(prediction["pre_race_snapshot_json"])
                    prediction["prediction_json"] = json.loads(prediction["prediction_json"])
                    prediction_tickets = [
                        _row_to_dict(row)
                        for row in conn.execute(
                            """
                            select ticket_id, prediction_id, race_id, bucket, bet_type,
                                   selection, selection_json, amount, reason
                            from prediction_tickets
                            where prediction_id = ?
                            order by bucket, bet_type, selection
                            """,
                            (record["prediction_id"],),
                        ).fetchall()
                    ]
                    for ticket in prediction_tickets:
                        ticket["selection_json"] = json.loads(ticket["selection_json"])

            result_row = conn.execute(
                """
                select *
                from bet_record_results
                where bet_record_id = ?
                """,
                (bet_record_id,),
            ).fetchone()

        tickets = [
            BetRecordTicket(
                bet_ticket_id=row["bet_ticket_id"],
                bet_record_id=row["bet_record_id"],
                race_id=row["race_id"],
                prediction_ticket_id=row["prediction_ticket_id"],
                bucket=row["bucket"],
                bet_type=row["bet_type"],
                selection=row["selection"],
                selection_json=json.loads(row["selection_json"]),
                amount=int(row["amount"]),
                odds_at_buy=row["odds_at_buy"],
                is_box_expanded=bool(row["is_box_expanded"]),
                reason=row["reason"],
                created_at=_parse_datetime(row["created_at"]),
            )
            for row in ticket_rows
        ]
        result = _bet_record_result_from_row(result_row) if result_row is not None else None
        return BetRecord(
            bet_record_id=record["bet_record_id"],
            race_id=record["race_id"],
            prediction_id=record["prediction_id"],
            theory_version=record["theory_version"],
            decision_source=record["decision_source"],
            purchased_at=_parse_datetime(record["purchased_at"]),
            total_amount=int(record["total_amount"]),
            note=record["note"],
            created_at=_parse_datetime(record["created_at"]),
            updated_at=_parse_datetime(record["updated_at"]),
            tickets=tickets,
            prediction=prediction,
            prediction_tickets=prediction_tickets,
            result=result,
        )

    def list_bet_records(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
        race_id: str | None = None,
        course: str | None = None,
        theory_version: str | None = None,
        decision_source: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> BetRecordPage:
        where: list[str] = []
        params: list[object] = []
        if from_date is not None:
            where.append("r.race_date >= ?")
            params.append(from_date.isoformat())
        if to_date is not None:
            where.append("r.race_date <= ?")
            params.append(to_date.isoformat())
        if race_id is not None:
            where.append("br.race_id = ?")
            params.append(race_id)
        if course is not None:
            where.append("r.course = ?")
            params.append(course)
        if theory_version is not None:
            where.append("br.theory_version = ?")
            params.append(theory_version)
        if decision_source is not None:
            where.append("br.decision_source = ?")
            params.append(decision_source)
        where_sql = f"where {' and '.join(where)}" if where else ""

        with self._connect() as conn:
            total = int(
                conn.execute(
                    f"""
                    select count(1)
                    from bet_records br
                    left join races r on r.race_id = br.race_id
                    {where_sql}
                    """,
                    params,
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"""
                select br.bet_record_id
                from bet_records br
                left join races r on r.race_id = br.race_id
                {where_sql}
                order by coalesce(br.purchased_at, br.created_at) desc, br.bet_record_id desc
                limit ? offset ?
                """,
                [*params, limit, offset],
            ).fetchall()

        items = [self.get_bet_record(row["bet_record_id"]) for row in rows]
        return BetRecordPage(items=items, total=total, limit=limit, offset=offset)

    def settle_bet_record(self, bet_record_id: str, settled_at: datetime | None = None) -> BetRecordSettlement:
        record = self.get_bet_record(bet_record_id)
        payout_index = self._load_payout_index(record.race_id)
        ticket_results: list[BetRecordResultTicket] = []
        total_payout = 0
        for ticket in record.tickets:
            payout = payout_index.get((ticket.bet_type, ticket.selection), 0)
            ticket_result = BetRecordResultTicket(
                bet_type=ticket.bet_type,
                selection=ticket.selection,
                selection_json=ticket.selection_json,
                amount=ticket.amount,
                hit=payout > 0,
                payout=payout,
            )
            total_payout += payout
            ticket_results.append(ticket_result)

        current_settled_at = settled_at or datetime.now(UTC)
        settlement = BetRecordSettlement(
            bet_record_id=record.bet_record_id,
            race_id=record.race_id,
            total_bet=record.total_amount,
            total_payout=total_payout,
            return_rate=(total_payout / record.total_amount) if record.total_amount else 0.0,
            hit=any(ticket.hit for ticket in ticket_results),
            settled_at=current_settled_at,
            ticket_results=ticket_results,
        )
        result_json = settlement.model_dump(mode="json")

        with self._connect() as conn:
            existing = conn.execute(
                """
                select bet_record_result_id, created_at
                from bet_record_results
                where bet_record_id = ?
                """,
                (bet_record_id,),
            ).fetchone()
            bet_record_result_id = existing["bet_record_result_id"] if existing is not None else str(uuid4())
            created_at = existing["created_at"] if existing is not None else _now()
            conn.execute(
                """
                insert into bet_record_results
                (bet_record_result_id, bet_record_id, race_id, total_bet, total_payout,
                 return_rate, hit, settled_at, result_json, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(bet_record_id) do update set
                    race_id = excluded.race_id,
                    total_bet = excluded.total_bet,
                    total_payout = excluded.total_payout,
                    return_rate = excluded.return_rate,
                    hit = excluded.hit,
                    settled_at = excluded.settled_at,
                    result_json = excluded.result_json
                """,
                (
                    bet_record_result_id,
                    bet_record_id,
                    record.race_id,
                    settlement.total_bet,
                    settlement.total_payout,
                    settlement.return_rate,
                    int(settlement.hit),
                    _dt(settlement.settled_at),
                    json.dumps(result_json, ensure_ascii=False),
                    created_at,
                ),
            )
            conn.execute(
                "update bet_records set updated_at = ? where bet_record_id = ?",
                (_now(), bet_record_id),
            )
        return settlement

    def _load_payout_index(self, race_id: str) -> dict[tuple[str, str], int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select bet_type, combination, payout
                from payouts
                where race_id = ?
                """,
                (race_id,),
            ).fetchall()
            if not rows:
                rows = conn.execute(
                    """
                    select bet_type, combination, payout
                    from netkeiba_payouts
                    where jra_race_id = ?
                    """,
                    (race_id,),
                ).fetchall()

        payout_index: dict[tuple[str, str], int] = {}
        for row in rows:
            normalized_bet_type = _normalize_payout_bet_type(row["bet_type"])
            if normalized_bet_type is None:
                continue
            combination = _normalize_selection_string(normalized_bet_type, row["combination"])
            payout_index[(normalized_bet_type, combination)] = int(row["payout"] or 0)
        return payout_index

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

    def list_races_for_netkeiba_mapping(
        self,
        from_date: date,
        to_date: date,
        limit: int | None = None,
    ) -> list[dict]:
        params: list[object] = [from_date.isoformat(), to_date.isoformat()]
        limit_sql = ""
        if limit is not None:
            limit_sql = "limit ?"
            params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select race_id, race_date, course, race_no
                from races
                where race_date >= ? and race_date <= ?
                order by race_date, course, race_no
                {limit_sql}
                """,
                params,
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_races_for_runner_backfill(
        self,
        from_date: date,
        to_date: date,
        courses: list[str],
        only_missing: bool,
        limit: int | None = None,
    ):
        from .analysis_maintenance import AnalysisRaceTarget

        where = ["r.race_date >= ?", "r.race_date <= ?"]
        params: list[object] = [from_date.isoformat(), to_date.isoformat()]
        if not _is_all_courses(courses):
            placeholders = ",".join("?" for _ in courses)
            where.append(f"r.course in ({placeholders})")
            params.extend(courses)
        having = "having count(ru.horse_no) = 0" if only_missing else ""
        limit_sql = ""
        if limit is not None:
            limit_sql = "limit ?"
            params.append(limit)

        sql = f"""
            select r.race_id, r.race_date, r.course, r.race_no, count(ru.horse_no) as runner_count
            from races r
            left join runners ru on ru.race_id = r.race_id
            where {" and ".join(where)}
            group by r.race_id, r.race_date, r.course, r.race_no
            {having}
            order by r.race_date, r.course, r.race_no
            {limit_sql}
        """
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            AnalysisRaceTarget(
                race_id=row["race_id"],
                race_date=date.fromisoformat(row["race_date"]),
                course=row["course"],
                race_no=int(row["race_no"]),
                runner_count=int(row["runner_count"]),
            )
            for row in rows
        ]

    def verify_analysis_joins(self, from_date: date, to_date: date, sample_size: int):
        from .analysis_maintenance import AnalysisJoinSample, AnalysisJoinVerification

        params = (from_date.isoformat(), to_date.isoformat())
        with self._connect() as conn:
            counts = {
                "races": _scalar(
                    conn,
                    "select count(1) from races where race_date >= ? and race_date <= ?",
                    params,
                ),
                "runners": _scalar(
                    conn,
                    """
                    select count(1)
                    from runners ru
                    join races r on r.race_id = ru.race_id
                    where r.race_date >= ? and r.race_date <= ?
                    """,
                    params,
                ),
                "race_results": _scalar(
                    conn,
                    """
                    select count(1)
                    from race_results rr
                    join races r on r.race_id = rr.race_id
                    where r.race_date >= ? and r.race_date <= ?
                    """,
                    params,
                ),
                "result_entries": _scalar(
                    conn,
                    """
                    select count(1)
                    from result_entries re
                    join races r on r.race_id = re.race_id
                    where r.race_date >= ? and r.race_date <= ?
                    """,
                    params,
                ),
                "payouts": _scalar(
                    conn,
                    """
                    select count(1)
                    from payouts p
                    join races r on r.race_id = p.race_id
                    where r.race_date >= ? and r.race_date <= ?
                    """,
                    params,
                ),
                "races_with_runners": _scalar(
                    conn,
                    """
                    select count(1)
                    from (
                        select r.race_id
                        from races r
                        join runners ru on ru.race_id = r.race_id
                        where r.race_date >= ? and r.race_date <= ?
                        group by r.race_id
                    )
                    """,
                    params,
                ),
                "result_runner_join_rows": _scalar(
                    conn,
                    """
                    select count(1)
                    from result_entries re
                    join races r on r.race_id = re.race_id
                    join runners ru on ru.race_id = re.race_id and ru.horse_no = re.horse_no
                    where r.race_date >= ? and r.race_date <= ?
                    """,
                    params,
                ),
                "payout_runner_race_join_rows": _scalar(
                    conn,
                    """
                    select count(1)
                    from payouts p
                    join races r on r.race_id = p.race_id
                    join runners ru on ru.race_id = p.race_id
                    where r.race_date >= ? and r.race_date <= ?
                    """,
                    params,
                ),
                "missing_runner_races": _scalar(
                    conn,
                    """
                    select count(1)
                    from (
                        select r.race_id
                        from races r
                        left join runners ru on ru.race_id = r.race_id
                        where r.race_date >= ? and r.race_date <= ?
                        group by r.race_id
                        having count(ru.horse_no) = 0
                    )
                    """,
                    params,
                ),
            }
            latest_run = conn.execute(
                """
                select run_id
                from collection_runs
                order by created_at desc
                limit 1
                """
            ).fetchone()
            latest_run_errors = []
            if latest_run is not None:
                latest_run_errors = [
                    _row_to_dict(row)
                    for row in conn.execute(
                        """
                        select race_id, race_date, course, race_no, stage, error_type, error_message, created_at
                        from collection_errors
                        where run_id = ?
                        order by created_at desc
                        limit 10
                        """,
                        (latest_run["run_id"],),
                    )
                ]
            samples = [
                AnalysisJoinSample(
                    race_id=row["race_id"],
                    horse_no=row["horse_no"],
                    horse_name=row["horse_name"],
                    jockey=row["jockey"],
                    trainer=row["trainer"],
                    sex_age=row["sex_age"],
                    weight_carried=row["weight_carried"],
                )
                for row in conn.execute(
                    """
                    select ru.race_id, ru.horse_no, ru.horse_name, ru.jockey,
                           ru.trainer, ru.sex_age, ru.weight_carried
                    from runners ru
                    join races r on r.race_id = ru.race_id
                    where r.race_date >= ? and r.race_date <= ?
                    order by ru.race_id, cast(ru.horse_no as integer), ru.horse_no
                    limit ?
                    """,
                    (*params, sample_size),
                )
            ]
        return AnalysisJoinVerification(
            races=counts["races"],
            runners=counts["runners"],
            race_results=counts["race_results"],
            result_entries=counts["result_entries"],
            payouts=counts["payouts"],
            races_with_runners=counts["races_with_runners"],
            result_runner_join_rows=counts["result_runner_join_rows"],
            payout_runner_race_join_rows=counts["payout_runner_race_join_rows"],
            missing_runner_races=counts["missing_runner_races"],
            latest_run_errors=latest_run_errors,
            samples=samples,
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def _odds_entries_by_type(odds: RaceOdds, bet_type: str | None) -> dict[str, list[OddsEntry]]:
    if odds.odds:
        return {key: list(value) for key, value in odds.odds.items()}
    current_bet_type = bet_type or odds.bet_type or "unknown"
    return {current_bet_type: list(odds.entries)}


def _netkeiba_odds_entries_by_type(odds: RaceOdds, bet_type: str | None) -> dict[str, list[OddsEntry]]:
    if odds.odds:
        if bet_type is not None:
            return {bet_type: list(odds.odds.get(bet_type, []))}
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


def _parse_signed_int(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.replace(",", "").strip()
    match = re.search(r"[+-]?\d+", normalized)
    if match is None:
        return None
    return int(match.group(0))


def _normalize_combination_items(combination: list[str]) -> list[str]:
    normalized = []
    for item in combination:
        value = item.strip()
        normalized.append(str(int(value)) if value.isdigit() else value)
    return normalized


UNORDERED_BET_TYPES = {"quinella", "wide", "trio"}
ORDERED_BET_TYPES = {"exacta", "trifecta"}
SINGLE_BET_TYPES = {"win", "place"}
BOX_SUPPORTED_BET_TYPES = {"quinella", "wide", "trio"}
PAYOUT_BET_TYPE_MAP = {
    "単勝": "win",
    "複勝": "place",
    "馬連": "quinella",
    "ワイド": "wide",
    "馬単": "exacta",
    "3連複": "trio",
    "3連単": "trifecta",
}


def _expand_bet_record_tickets(request: BetRecordCreateRequest) -> list[dict[str, object]]:
    expanded: list[dict[str, object]] = []
    for ticket in request.tickets:
        bet_type = str(ticket.bet_type)
        if ticket.mode == "box":
            if bet_type not in BOX_SUPPORTED_BET_TYPES:
                raise BadRequestError(f"box mode is not supported for bet_type={bet_type}")
            if len(ticket.selection) < 2:
                raise BadRequestError("box mode requires at least 2 selections")
            leg_count = 3 if bet_type == "trio" else 2
            if len(ticket.selection) < leg_count:
                raise BadRequestError(f"box mode requires at least {leg_count} selections for bet_type={bet_type}")
            for selection in combinations(ticket.selection, leg_count):
                normalized_items = _normalize_selection_items(bet_type, list(selection))
                expanded.append(
                    {
                        "bet_ticket_id": str(uuid4()),
                        "prediction_ticket_id": ticket.prediction_ticket_id,
                        "bucket": ticket.bucket,
                        "bet_type": bet_type,
                        "selection": "-".join(normalized_items),
                        "selection_json": normalized_items,
                        "amount": ticket.amount_per_ticket,
                        "odds_at_buy": ticket.odds_at_buy,
                        "is_box_expanded": True,
                        "reason": ticket.reason,
                    }
                )
            continue

        normalized_items = _normalize_selection_items(bet_type, ticket.selection)
        expanded.append(
            {
                "bet_ticket_id": str(uuid4()),
                "prediction_ticket_id": ticket.prediction_ticket_id,
                "bucket": ticket.bucket,
                "bet_type": bet_type,
                "selection": "-".join(normalized_items),
                "selection_json": normalized_items,
                "amount": ticket.amount,
                "odds_at_buy": ticket.odds_at_buy,
                "is_box_expanded": False,
                "reason": ticket.reason,
            }
        )
    return expanded


def _normalize_selection_items(bet_type: str, selection: list[str]) -> list[str]:
    normalized = _normalize_combination_items(selection)
    expected_count = _expected_selection_count(bet_type)
    if expected_count is not None and len(normalized) != expected_count:
        raise BadRequestError(f"bet_type={bet_type} requires {expected_count} selections")
    if bet_type in SINGLE_BET_TYPES:
        return normalized
    if bet_type in UNORDERED_BET_TYPES:
        return sorted(normalized, key=_selection_sort_key)
    if bet_type in ORDERED_BET_TYPES:
        return normalized
    raise BadRequestError(f"unsupported bet_type={bet_type}")


def _normalize_selection_string(bet_type: str, selection: str) -> str:
    items = [item.strip() for item in re.split(r"[-,]", selection) if item.strip()]
    normalized = _normalize_selection_items(bet_type, items)
    return "-".join(normalized)


def _expected_selection_count(bet_type: str) -> int | None:
    if bet_type in SINGLE_BET_TYPES:
        return 1
    if bet_type in {"quinella", "wide", "exacta"}:
        return 2
    if bet_type in {"trio", "trifecta"}:
        return 3
    return None


def _selection_sort_key(value: str) -> tuple[int, object]:
    return (0, int(value)) if value.isdigit() else (1, value)


def _normalize_payout_bet_type(value: str | None) -> str | None:
    if value is None:
        return None
    return PAYOUT_BET_TYPE_MAP.get(value, value if value in SINGLE_BET_TYPES | UNORDERED_BET_TYPES | ORDERED_BET_TYPES else None)


def _bet_record_result_from_row(row: sqlite3.Row) -> BetRecordResult:
    return BetRecordResult(
        bet_record_result_id=row["bet_record_result_id"],
        bet_record_id=row["bet_record_id"],
        race_id=row["race_id"],
        total_bet=int(row["total_bet"]),
        total_payout=int(row["total_payout"]),
        return_rate=float(row["return_rate"]),
        hit=bool(row["hit"]),
        settled_at=_parse_datetime(row["settled_at"]),
        result_json=json.loads(row["result_json"]),
        created_at=_parse_datetime(row["created_at"]),
    )


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _is_all_courses(courses: list[str]) -> bool:
    return len(courses) == 1 and courses[0].strip().lower() in {"all", "*", "auto"}
