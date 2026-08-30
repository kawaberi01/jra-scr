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
    EvaluationRecord,
    EvaluationRecordPage,
    EvaluationSummary,
    EvaluationTicketResultRecord,
    JraDayRaceScoutResult,
    JraLiveShadowObservation,
    JraLiveShadowObservationPage,
    BetRecordResultTicket,
    BetRecordTicket,
    MeetingRace,
    NetkeibaRaceResult,
    OddsEntry,
    PredictionRecord,
    PredictionRecordPage,
    PredictionTicketRecord,
    RaceCard,
    RaceCardRunnerSetStatus,
    RaceCardSourceKind,
    RaceOdds,
    RaceResult,
    RunnerStatus,
    RunnerStatusSource,
    StoredOddsEntry,
    StoredOddsSnapshot,
    StoredOddsTimeline,
    StoredPreRace,
    StoredPreRaceRunner,
    StoredPreRaceSnapshot,
    StoredPreRaceSnapshotMeta,
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
                    meeting_no integer,
                    meeting_day integer,
                    race_no integer not null,
                    race_name text,
                    race_grade text,
                    start_time text,
                    surface text,
                    surface_label text,
                    distance text,
                    weather text,
                    weather_label text,
                    track_condition text,
                    track_condition_label text,
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
                    horse_weight integer,
                    horse_weight_diff integer,
                    card_odds real,
                    card_popularity integer,
                    status text not null default 'active',
                    status_source text,
                    primary key (race_id, horse_no)
                );

                create table if not exists race_card_snapshots (
                    card_snapshot_id text primary key,
                    race_id text not null,
                    race_date text not null,
                    course text not null,
                    meeting_no integer,
                    meeting_day integer,
                    race_no integer not null,
                    race_name text,
                    start_time text,
                    surface text,
                    surface_label text,
                    distance text,
                    weather text,
                    weather_label text,
                    track_condition text,
                    track_condition_label text,
                    source text not null,
                    source_kind text not null,
                    runner_set_status text not null,
                    runner_set_reason text,
                    runner_count integer not null,
                    fetched_at text not null
                );

                create table if not exists race_card_snapshot_runners (
                    card_snapshot_id text not null,
                    race_id text not null,
                    horse_no text not null,
                    frame_no text,
                    horse_name text not null,
                    sex_age text,
                    weight_carried text,
                    jockey text,
                    trainer text,
                    horse_weight integer,
                    horse_weight_diff integer,
                    card_odds real,
                    card_popularity integer,
                    status text not null,
                    status_source text,
                    primary key (card_snapshot_id, horse_no),
                    foreign key (card_snapshot_id)
                        references race_card_snapshots(card_snapshot_id)
                        on delete cascade
                );

                create table if not exists odds_snapshots (
                    snapshot_id text primary key,
                    race_id text not null,
                    bet_type text not null,
                    odds_timing text not null,
                    fetched_at text not null,
                    source text not null
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
                    race_laps_json text,
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

                create table if not exists daily_prediction_log_imports (
                    import_id text primary key,
                    source_path text not null,
                    log_date text,
                    venue text,
                    imported_at text not null,
                    unique (source_path, log_date)
                );

                create table if not exists daily_prediction_log_entries (
                    entry_id text primary key,
                    import_id text not null,
                    race_id text,
                    race_date text,
                    course text,
                    race_no integer,
                    entry_timestamp text not null,
                    entry_type text not null,
                    topic text,
                    prediction_mode text,
                    raw_markdown text not null,
                    payload_json text not null
                );
                create index if not exists idx_daily_prediction_log_entries_import
                on daily_prediction_log_entries (import_id);
                create index if not exists idx_daily_prediction_log_entries_race
                on daily_prediction_log_entries (race_date, course, race_no);

                create table if not exists jra_scout_runs (
                    run_id text primary key,
                    race_date text not null,
                    observed_at text not null,
                    phase text not null,
                    status text not null,
                    race_count integer not null,
                    analyzed_count integer not null,
                    candidates_json text not null,
                    errors_json text not null
                );

                create table if not exists jra_scout_entries (
                    run_id text not null,
                    race_id text not null,
                    course text not null,
                    race_no integer not null,
                    grade text not null,
                    entry_json text not null,
                    primary key (run_id, race_id),
                    foreign key (run_id) references jra_scout_runs(run_id)
                );
                create index if not exists idx_jra_scout_entries_run_grade
                on jra_scout_entries (run_id, grade);

                create table if not exists jra_live_shadow_observations (
                    observation_id text primary key,
                    run_id text not null,
                    race_id text not null,
                    race_date text not null,
                    course text not null,
                    race_no integer not null,
                    observed_at text not null,
                    model_version text not null,
                    policy_version text,
                    decision_status text not null,
                    ticket_status text not null,
                    payload_json text not null,
                    unique (run_id, race_id),
                    foreign key (run_id) references jra_scout_runs(run_id)
                );
                create index if not exists idx_jra_live_shadow_observations_race_time
                on jra_live_shadow_observations (race_id, observed_at desc);
                """
            )
            _migrate_odds_snapshots_to_append_only(conn)
            conn.execute(
                """
                create index if not exists idx_odds_snapshots_lookup
                on odds_snapshots (race_id, bet_type, odds_timing, fetched_at)
                """
            )
            _ensure_column(conn, "races", "meeting_no", "integer")
            _ensure_column(conn, "races", "meeting_day", "integer")
            _ensure_column(conn, "races", "race_grade", "text")
            _ensure_column(conn, "races", "surface_label", "text")
            _ensure_column(conn, "races", "weather", "text")
            _ensure_column(conn, "races", "weather_label", "text")
            _ensure_column(conn, "races", "track_condition", "text")
            _ensure_column(conn, "races", "track_condition_label", "text")
            _ensure_column(conn, "runners", "horse_weight", "integer")
            _ensure_column(conn, "runners", "horse_weight_diff", "integer")
            _ensure_column(
                conn,
                "runners",
                "status",
                "text not null default 'active'",
            )
            _ensure_column(conn, "runners", "status_source", "text")
            _ensure_column(conn, "netkeiba_race_results", "race_laps_json", "text")

    def save_jra_scout_result(
        self,
        result: JraDayRaceScoutResult,
        *,
        observations: list[JraLiveShadowObservation] | None = None,
    ) -> dict[str, object]:
        payload = result.model_dump(mode="json")
        observations = observations or []
        with self._connect() as conn:
            conn.execute("pragma foreign_keys = on")
            conn.execute(
                """
                insert into jra_scout_runs
                (run_id, race_date, observed_at, phase, status, race_count, analyzed_count, candidates_json, errors_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(run_id) do update set
                    observed_at=excluded.observed_at, status=excluded.status,
                    race_count=excluded.race_count, analyzed_count=excluded.analyzed_count,
                    candidates_json=excluded.candidates_json, errors_json=excluded.errors_json
                """,
                (
                    result.run_id, result.date.isoformat(), result.observed_at.isoformat(), result.phase,
                    result.status, result.race_count, result.analyzed_count,
                    json.dumps(payload["candidates"], ensure_ascii=False),
                    json.dumps(payload["errors"], ensure_ascii=False),
                ),
            )
            conn.execute("delete from jra_scout_entries where run_id = ?", (result.run_id,))
            conn.executemany(
                """
                insert into jra_scout_entries (run_id, race_id, course, race_no, grade, entry_json)
                values (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        result.run_id, entry.race_id, entry.course, entry.race_no, entry.grade,
                        json.dumps(entry.model_dump(mode="json"), ensure_ascii=False),
                    )
                    for entry in result.entries
                ],
            )
            conn.executemany(
                """
                insert into jra_live_shadow_observations
                (observation_id, run_id, race_id, race_date, course, race_no, observed_at,
                 model_version, policy_version, decision_status, ticket_status, payload_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(run_id, race_id) do update set
                    observation_id=excluded.observation_id,
                    race_date=excluded.race_date,
                    course=excluded.course,
                    race_no=excluded.race_no,
                    observed_at=excluded.observed_at,
                    model_version=excluded.model_version,
                    policy_version=excluded.policy_version,
                    decision_status=excluded.decision_status,
                    ticket_status=excluded.ticket_status,
                    payload_json=excluded.payload_json
                """,
                [
                    (
                        observation.observation_id,
                        observation.run_id,
                        observation.race_id,
                        observation.race_date.isoformat(),
                        observation.course,
                        observation.race_no,
                        observation.observed_at.isoformat(),
                        observation.model_version,
                        observation.policy_version,
                        observation.decision_status,
                        observation.ticket_status,
                        json.dumps(observation.model_dump(mode="json"), ensure_ascii=False),
                    )
                    for observation in observations
                ],
            )
        return {
            "run_id": result.run_id,
            "entries": len(result.entries),
            "observations": len(observations),
        }

    def list_jra_live_shadow_observations(
        self,
        race_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> JraLiveShadowObservationPage:
        with self._connect() as conn:
            known_race = conn.execute(
                """
                select 1 from races where race_id = ?
                union all
                select 1 from jra_scout_entries where race_id = ?
                limit 1
                """,
                (race_id, race_id),
            ).fetchone()
            if known_race is None:
                raise LookupError(f"stored race not found for race_id={race_id}")
            total = int(
                conn.execute(
                    "select count(*) from jra_live_shadow_observations where race_id = ?",
                    (race_id,),
                ).fetchone()[0]
            )
            rows = conn.execute(
                """
                select payload_json
                from jra_live_shadow_observations
                where race_id = ?
                order by observed_at desc, observation_id desc
                limit ? offset ?
                """,
                (race_id, limit, offset),
            ).fetchall()
        return JraLiveShadowObservationPage(
            race_id=race_id,
            items=[
                JraLiveShadowObservation.model_validate(json.loads(row["payload_json"]))
                for row in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
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
        meeting_no, meeting_day = _parse_meeting_fields_from_race_id(race.race_id)
        with self._connect() as conn:
            conn.execute(
                """
                insert into races
                (race_id, race_date, course, meeting_no, meeting_day, race_no, race_name, race_grade, start_time, source, fetched_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(race_id) do update set
                    race_date = excluded.race_date,
                    course = excluded.course,
                    meeting_no = coalesce(excluded.meeting_no, races.meeting_no),
                    meeting_day = coalesce(excluded.meeting_day, races.meeting_day),
                    race_no = excluded.race_no,
                    race_name = coalesce(excluded.race_name, races.race_name),
                    race_grade = coalesce(excluded.race_grade, races.race_grade),
                    start_time = coalesce(excluded.start_time, races.start_time),
                    source = coalesce(excluded.source, races.source),
                    fetched_at = coalesce(excluded.fetched_at, races.fetched_at)
                """,
                (
                    race.race_id,
                    target_date.isoformat(),
                    course,
                    meeting_no,
                    meeting_day,
                    race.race_no,
                    race.race_name,
                    race.race_grade,
                    race.start_time,
                    source,
                    _dt(fetched_at),
                ),
            )

    def write_card(self, target_date: date, course: str, race_no: int, card: RaceCard) -> None:
        meeting_no, meeting_day = _parse_meeting_fields_from_race_id(card.race_id)
        horse_numbers = [runner.horse_no for runner in card.runners]
        structurally_complete = (
            bool(card.runners)
            and all(horse_numbers)
            and len(set(horse_numbers)) == len(horse_numbers)
        )
        data_status = card.data_status
        runner_set_status = (
            str(data_status.runner_set)
            if data_status is not None and data_status.runner_set is not None
            else (
                RaceCardRunnerSetStatus.complete
                if structurally_complete
                else RaceCardRunnerSetStatus.incomplete
            )
        )
        if runner_set_status == RaceCardRunnerSetStatus.complete and not structurally_complete:
            runner_set_status = RaceCardRunnerSetStatus.incomplete
        runner_set_reason = (
            data_status.runner_set_reason
            if data_status is not None and data_status.runner_set_reason
            else (
                "all runners have unique horse numbers"
                if runner_set_status == RaceCardRunnerSetStatus.complete
                else "runner collection is empty or has missing/duplicate horse numbers"
            )
        )
        source_kind = (
            str(data_status.source_kind)
            if data_status is not None
            else RaceCardSourceKind.unknown
        )
        if source_kind == RaceCardSourceKind.unknown:
            source_kind = RaceCardSourceKind.pre_race_card
        is_complete_pre_race = (
            runner_set_status == RaceCardRunnerSetStatus.complete
            and source_kind == RaceCardSourceKind.pre_race_card
        )

        current_runners: dict[str, dict[str, object | None]] = {}
        for runner in card.runners:
            horse_no = runner.horse_no or runner.horse_name
            current_runners[horse_no] = {
                "race_id": card.race_id,
                "horse_no": horse_no,
                "frame_no": runner.frame_no,
                "horse_name": runner.horse_name,
                "sex_age": runner.sex_age,
                "weight_carried": runner.weight_carried,
                "jockey": runner.jockey,
                "trainer": runner.trainer,
                "horse_weight": _parse_int(runner.horse_weight),
                "horse_weight_diff": _parse_signed_int(runner.horse_weight_diff),
                "card_odds": _parse_float(runner.odds),
                "card_popularity": _parse_int(runner.popularity),
                "status": str(runner.status),
                "status_source": (
                    str(runner.status_source)
                    if runner.status_source is not None
                    else None
                ),
            }

        with self._connect() as conn:
            conn.execute(
                """
                insert into races
                (race_id, race_date, course, meeting_no, meeting_day, race_no,
                 race_name, start_time, surface, surface_label, distance,
                 weather, weather_label, track_condition, track_condition_label,
                 source, fetched_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(race_id) do update set
                    race_date = excluded.race_date,
                    course = excluded.course,
                    meeting_no = coalesce(excluded.meeting_no, races.meeting_no),
                    meeting_day = coalesce(excluded.meeting_day, races.meeting_day),
                    race_no = excluded.race_no,
                    race_name = coalesce(excluded.race_name, races.race_name),
                    start_time = coalesce(excluded.start_time, races.start_time),
                    surface = coalesce(excluded.surface, races.surface),
                    surface_label = coalesce(excluded.surface_label, races.surface_label),
                    distance = coalesce(excluded.distance, races.distance),
                    weather = coalesce(excluded.weather, races.weather),
                    weather_label = coalesce(excluded.weather_label, races.weather_label),
                    track_condition = coalesce(excluded.track_condition, races.track_condition),
                    track_condition_label = coalesce(
                        excluded.track_condition_label,
                        races.track_condition_label
                    ),
                    source = excluded.source,
                    fetched_at = excluded.fetched_at
                """,
                (
                    card.race_id,
                    target_date.isoformat(),
                    # The caller's meeting course is authoritative.  Some JRA card
                    # pages expose the distance label in card.course, which must not
                    # replace the normalized venue persisted from the meeting page.
                    course,
                    meeting_no,
                    meeting_day,
                    race_no,
                    card.race_name,
                    card.start_time,
                    card.surface,
                    card.surface_label,
                    card.distance,
                    card.weather,
                    card.weather_label,
                    card.track_condition,
                    card.track_condition_label,
                    card.source,
                    _dt(card.fetched_at),
                ),
            )

            snapshot_runners = dict(current_runners)
            if is_complete_pre_race:
                previous_snapshot = conn.execute(
                    """
                    select card_snapshot_id
                    from race_card_snapshots
                    where race_id = ?
                      and runner_set_status = 'complete'
                      and source_kind = 'pre_race_card'
                    order by julianday(fetched_at) desc, card_snapshot_id desc
                    limit 1
                    """,
                    (card.race_id,),
                ).fetchone()
                if previous_snapshot is not None:
                    previous_runners = conn.execute(
                        """
                        select *
                        from race_card_snapshot_runners
                        where card_snapshot_id = ?
                        """,
                        (previous_snapshot["card_snapshot_id"],),
                    ).fetchall()
                    for previous in previous_runners:
                        horse_no = str(previous["horse_no"])
                        if horse_no in snapshot_runners:
                            continue
                        carried = _row_to_dict(previous)
                        carried.pop("card_snapshot_id", None)
                        carried["status"] = RunnerStatus.withdrawn
                        if carried.get("status_source") is None:
                            carried["status_source"] = RunnerStatusSource.derived
                        snapshot_runners[horse_no] = carried

            if source_kind != RaceCardSourceKind.result_page:
                card_snapshot_id = uuid4().hex
                conn.execute(
                    """
                    insert into race_card_snapshots
                    (card_snapshot_id, race_id, race_date, course, meeting_no,
                     meeting_day, race_no, race_name, start_time, surface,
                     surface_label, distance, weather, weather_label,
                     track_condition, track_condition_label, source, source_kind,
                     runner_set_status, runner_set_reason, runner_count, fetched_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        card_snapshot_id,
                        card.race_id,
                        target_date.isoformat(),
                        course,
                        meeting_no,
                        meeting_day,
                        race_no,
                        card.race_name,
                        card.start_time,
                        card.surface,
                        card.surface_label,
                        card.distance,
                        card.weather,
                        card.weather_label,
                        card.track_condition,
                        card.track_condition_label,
                        card.source,
                        source_kind,
                        runner_set_status,
                        runner_set_reason,
                        len(snapshot_runners),
                        _dt(card.fetched_at),
                    ),
                )
                conn.executemany(
                    """
                    insert into race_card_snapshot_runners
                    (card_snapshot_id, race_id, horse_no, frame_no, horse_name,
                     sex_age, weight_carried, jockey, trainer, horse_weight,
                     horse_weight_diff, card_odds, card_popularity, status,
                     status_source)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            card_snapshot_id,
                            row["race_id"],
                            row["horse_no"],
                            row["frame_no"],
                            row["horse_name"],
                            row["sex_age"],
                            row["weight_carried"],
                            row["jockey"],
                            row["trainer"],
                            row["horse_weight"],
                            row["horse_weight_diff"],
                            row["card_odds"],
                            row["card_popularity"],
                            row["status"],
                            row["status_source"],
                        )
                        for row in snapshot_runners.values()
                    ],
                )

            latest_runners = (
                snapshot_runners if is_complete_pre_race else current_runners
            )
            if is_complete_pre_race:
                conn.execute("delete from runners where race_id = ?", (card.race_id,))
            conn.executemany(
                """
                insert into runners
                (race_id, horse_no, frame_no, horse_name, sex_age, weight_carried,
                 jockey, trainer, horse_weight, horse_weight_diff, card_odds,
                 card_popularity, status, status_source)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(race_id, horse_no) do update set
                    frame_no = excluded.frame_no,
                    horse_name = excluded.horse_name,
                    sex_age = excluded.sex_age,
                    weight_carried = excluded.weight_carried,
                    jockey = excluded.jockey,
                    trainer = excluded.trainer,
                    horse_weight = excluded.horse_weight,
                    horse_weight_diff = excluded.horse_weight_diff,
                    card_odds = excluded.card_odds,
                    card_popularity = excluded.card_popularity,
                    status = excluded.status,
                    status_source = excluded.status_source
                """,
                [
                    (
                        row["race_id"],
                        row["horse_no"],
                        row["frame_no"],
                        row["horse_name"],
                        row["sex_age"],
                        row["weight_carried"],
                        row["jockey"],
                        row["trainer"],
                        row["horse_weight"],
                        row["horse_weight_diff"],
                        row["card_odds"],
                        row["card_popularity"],
                        row["status"],
                        row["status_source"],
                    )
                    for row in latest_runners.values()
                ],
            )

    def write_odds(self, odds: RaceOdds, bet_type: str | None = None, odds_timing: str = "final_or_near_final") -> None:
        entries_by_type = _odds_entries_by_type(odds, bet_type)
        with self._connect() as conn:
            for current_bet_type, entries in entries_by_type.items():
                snapshot_id = (
                    f"{odds.race_id}:{current_bet_type}:{odds_timing}:{uuid4().hex}"
                )
                conn.execute(
                    """
                    insert into odds_snapshots
                    (snapshot_id, race_id, bet_type, odds_timing, fetched_at, source)
                    values (?, ?, ?, ?, ?, ?)
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
                 surface, distance, direction, weather, track_condition, race_laps_json, source, fetched_at, raw_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    race_laps_json = excluded.race_laps_json,
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
                    json.dumps(result.race_laps, ensure_ascii=False),
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

    def upsert_prediction_record(self, payload: dict) -> dict[str, object]:
        prediction_id = str(payload["prediction_id"])
        race_id = str(payload["race_id"])
        theory_version = str(payload["theory_version"])
        mode = payload.get("mode")
        budget = int(payload["budget"]) if payload.get("budget") is not None else None
        pre_race_snapshot = payload.get("pre_race_snapshot") or {}
        prediction_json = payload.get("prediction_json") or {}
        created_at = _coerce_datetime_text(payload.get("created_at")) or _now()
        prediction_tickets = payload.get("prediction_tickets") or []
        race_context = _extract_prediction_race_context(payload, race_id)

        with self._connect() as conn:
            if race_context is not None:
                _upsert_race_context(conn, race_context)
            conn.execute(
                """
                insert into predictions
                (prediction_id, race_id, theory_version, mode, budget, pre_race_snapshot_json, prediction_json, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(prediction_id) do update set
                    race_id = excluded.race_id,
                    theory_version = excluded.theory_version,
                    mode = excluded.mode,
                    budget = excluded.budget,
                    pre_race_snapshot_json = excluded.pre_race_snapshot_json,
                    prediction_json = excluded.prediction_json,
                    created_at = excluded.created_at
                """,
                (
                    prediction_id,
                    race_id,
                    theory_version,
                    mode,
                    budget,
                    json.dumps(pre_race_snapshot, ensure_ascii=False),
                    json.dumps(prediction_json, ensure_ascii=False),
                    created_at,
                ),
            )
            conn.execute("delete from prediction_tickets where prediction_id = ?", (prediction_id,))
            for ticket in prediction_tickets:
                normalized = _normalize_prediction_ticket(ticket, prediction_id, race_id)
                conn.execute(
                    """
                    insert into prediction_tickets
                    (ticket_id, prediction_id, race_id, bucket, bet_type, selection, selection_json, amount, reason)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        normalized["ticket_id"],
                        prediction_id,
                        race_id,
                        normalized["bucket"],
                        normalized["bet_type"],
                        normalized["selection"],
                        json.dumps(normalized["selection_json"], ensure_ascii=False),
                        normalized["amount"],
                        normalized["reason"],
                    ),
                )
            prediction_count = int(
                conn.execute("select count(*) from predictions where prediction_id = ?", (prediction_id,)).fetchone()[0]
            )
            ticket_count = int(
                conn.execute("select count(*) from prediction_tickets where prediction_id = ?", (prediction_id,)).fetchone()[0]
            )
        return {
            "prediction_id": prediction_id,
            "race_id": race_id,
            "predictions": prediction_count,
            "prediction_tickets": ticket_count,
        }

    def evaluate_prediction_record(self, payload: dict) -> dict[str, object]:
        prediction_id = str(payload["prediction_id"])
        evaluation_id = str(payload.get("evaluation_id") or f"eval-{prediction_id}")
        created_at = _coerce_datetime_text(payload.get("created_at")) or _now()

        with self._connect() as conn:
            prediction_row = conn.execute(
                """
                select prediction_id, race_id, theory_version, mode, budget, pre_race_snapshot_json, prediction_json, created_at
                from predictions
                where prediction_id = ?
                """,
                (prediction_id,),
            ).fetchone()
            if prediction_row is None:
                raise LookupError(f"prediction not found for prediction_id={prediction_id}")

            prediction = _row_to_dict(prediction_row)
            prediction["pre_race_snapshot_json"] = json.loads(prediction["pre_race_snapshot_json"])
            prediction["prediction_json"] = json.loads(prediction["prediction_json"])
            race_id = prediction["race_id"]
            ticket_rows = conn.execute(
                """
                select ticket_id, prediction_id, race_id, bucket, bet_type, selection, selection_json, amount, reason
                from prediction_tickets
                where prediction_id = ?
                order by rowid
                """,
                (prediction_id,),
            ).fetchall()
            result_rows = conn.execute(
                """
                select rank, horse_no, horse_name, jockey, finish_time
                from result_entries
                where race_id = ?
                  and rank is not null
                order by rank
                """,
                (race_id,),
            ).fetchall()
            if not result_rows:
                raise LookupError(f"result_entries not found for race_id={race_id}")

            payout_rows = conn.execute(
                """
                select bet_type, combination, payout, popularity
                from payouts
                where race_id = ?
                order by rowid
                """,
                (race_id,),
            ).fetchall()
            if not payout_rows:
                payout_rows = conn.execute(
                    """
                    select bet_type, combination, payout, popularity
                    from netkeiba_payouts
                    where jra_race_id = ?
                    order by rowid
                    """,
                    (race_id,),
                ).fetchall()

            payout_index = self._load_payout_index(race_id)
            ticket_results = []
            total_bet = 0
            total_payout = 0
            firework_ticket_hit = False
            for row in ticket_rows:
                payout = _scale_payout_for_amount(
                    int(payout_index.get((row["bet_type"], row["selection"]), 0)),
                    int(row["amount"]),
                )
                total_bet += int(row["amount"])
                total_payout += payout
                bucket = row["bucket"]
                hit = payout > 0
                if bucket in {"festival", "firework", "mini_firework"} and hit:
                    firework_ticket_hit = True
                ticket_results.append(
                    {
                        "ticket_result_id": str(uuid4()),
                        "ticket_id": row["ticket_id"],
                        "bucket": bucket,
                        "bet_type": row["bet_type"],
                        "selection": row["selection"],
                        "amount": int(row["amount"]),
                        "hit": hit,
                        "payout": payout,
                    }
                )

            prediction_json = prediction["prediction_json"]
            predicted_top3 = _extract_predicted_top3(prediction_json)
            predicted_top3_horses = [str(item["horse_no"]) for item in predicted_top3 if item.get("horse_no") is not None]
            actual_top3 = [_row_to_dict(row) for row in result_rows[:3]]
            actual_top3_horses = [str(item["horse_no"]) for item in actual_top3 if item.get("horse_no") is not None]
            axis_horse_numbers = _extract_axis_horse_numbers(prediction_json)
            middle_hole_horse_numbers = _extract_middle_hole_horse_numbers(prediction_json)
            review = payload.get("review") or {}
            winner_hit = bool(actual_top3_horses and actual_top3_horses[0] in predicted_top3_horses)
            top3_box_hit = len(actual_top3_horses) == 3 and set(actual_top3_horses).issubset(set(predicted_top3_horses))
            axis_in_top3 = any(horse_no in actual_top3_horses for horse_no in axis_horse_numbers) if axis_horse_numbers else None
            middle_hole_in_top3 = (
                any(horse_no in actual_top3_horses for horse_no in middle_hole_horse_numbers)
                if middle_hole_horse_numbers
                else None
            )
            firework_hit = payload.get("firework_hit")
            if firework_hit is None:
                firework_hit = firework_ticket_hit if any(ticket["bucket"] in {"festival", "firework", "mini_firework"} for ticket in ticket_results) else None

            review_summary = {
                "winner_hit": winner_hit,
                "top3_box_hit": top3_box_hit,
                "axis_in_top3": axis_in_top3,
                "middle_hole_in_top3": middle_hole_in_top3,
                "firework_hit": firework_hit,
                "predicted_top3_contains_winner": winner_hit,
            }
            review_summary.update(review)
            evaluation_json = {
                "prediction_id": prediction_id,
                "race_id": race_id,
                "theory_version": prediction["theory_version"],
                "summary": review_summary,
                "predicted_top3": predicted_top3,
                "actual_top3": actual_top3,
                "payouts": [_row_to_dict(row) for row in payout_rows],
                "ticket_review": {
                    "total_bet": total_bet,
                    "total_payout": total_payout,
                    "ticket_results": ticket_results,
                },
                "review_notes": payload.get("review_notes") or [],
            }
            gami = total_payout > 0 and total_payout < total_bet
            max_odds_selected = payload.get("max_odds_selected")
            if max_odds_selected is None:
                max_odds_selected = _compute_max_selected_odds(prediction_json)

            conn.execute("delete from evaluation_ticket_results where evaluation_id = ?", (evaluation_id,))
            conn.execute(
                """
                insert into evaluations
                (evaluation_id, prediction_id, race_id, theory_version, total_bet, total_payout,
                 return_rate, hit, gami, axis_in_top3, middle_hole_in_top3, firework_hit,
                 max_odds_selected, evaluation_json, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(evaluation_id) do update set
                    prediction_id = excluded.prediction_id,
                    race_id = excluded.race_id,
                    theory_version = excluded.theory_version,
                    total_bet = excluded.total_bet,
                    total_payout = excluded.total_payout,
                    return_rate = excluded.return_rate,
                    hit = excluded.hit,
                    gami = excluded.gami,
                    axis_in_top3 = excluded.axis_in_top3,
                    middle_hole_in_top3 = excluded.middle_hole_in_top3,
                    firework_hit = excluded.firework_hit,
                    max_odds_selected = excluded.max_odds_selected,
                    evaluation_json = excluded.evaluation_json,
                    created_at = excluded.created_at
                """,
                (
                    evaluation_id,
                    prediction_id,
                    race_id,
                    prediction["theory_version"],
                    total_bet,
                    total_payout,
                    (total_payout / total_bet) if total_bet else 0.0,
                    int(total_payout > 0),
                    int(gami),
                    _to_db_bool(axis_in_top3),
                    _to_db_bool(middle_hole_in_top3),
                    _to_db_bool(firework_hit),
                    max_odds_selected,
                    json.dumps(evaluation_json, ensure_ascii=False),
                    created_at,
                ),
            )
            for ticket_result in ticket_results:
                conn.execute(
                    """
                    insert into evaluation_ticket_results
                    (ticket_result_id, evaluation_id, ticket_id, bucket, bet_type, selection, amount, hit, payout)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ticket_result["ticket_result_id"],
                        evaluation_id,
                        ticket_result["ticket_id"],
                        ticket_result["bucket"],
                        ticket_result["bet_type"],
                        ticket_result["selection"],
                        ticket_result["amount"],
                        int(ticket_result["hit"]),
                        ticket_result["payout"],
                    ),
                )

            evaluation_count = int(
                conn.execute("select count(*) from evaluations where evaluation_id = ?", (evaluation_id,)).fetchone()[0]
            )
            ticket_result_count = int(
                conn.execute("select count(*) from evaluation_ticket_results where evaluation_id = ?", (evaluation_id,)).fetchone()[0]
            )
        return {
            "evaluation_id": evaluation_id,
            "prediction_id": prediction_id,
            "race_id": race_id,
            "evaluations": evaluation_count,
            "evaluation_ticket_results": ticket_result_count,
            "total_bet": total_bet,
            "total_payout": total_payout,
            "return_rate": (total_payout / total_bet) if total_bet else 0.0,
            "hit": total_payout > 0,
        }

    def get_prediction_record(self, prediction_id: str) -> PredictionRecord:
        with self._connect() as conn:
            return self._get_prediction_record(conn, prediction_id)

    def _get_prediction_record(self, conn: sqlite3.Connection, prediction_id: str) -> PredictionRecord:
        row = conn.execute(
            """
            select prediction_id, race_id, theory_version, mode, budget,
                   pre_race_snapshot_json, prediction_json, created_at
            from predictions
            where prediction_id = ?
            """,
            (prediction_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"prediction not found for prediction_id={prediction_id}")

        ticket_rows = conn.execute(
            """
            select ticket_id, prediction_id, race_id, bucket, bet_type,
                   selection, selection_json, amount, reason
            from prediction_tickets
            where prediction_id = ?
            order by rowid
            """,
            (prediction_id,),
        ).fetchall()
        return PredictionRecord(
            prediction_id=row["prediction_id"],
            race_id=row["race_id"],
            theory_version=row["theory_version"],
            mode=row["mode"],
            budget=int(row["budget"]) if row["budget"] is not None else None,
            pre_race_snapshot=json.loads(row["pre_race_snapshot_json"]),
            prediction=json.loads(row["prediction_json"]),
            created_at=_parse_datetime(row["created_at"]),
            prediction_tickets=[
                PredictionTicketRecord(
                    ticket_id=ticket["ticket_id"],
                    prediction_id=ticket["prediction_id"],
                    race_id=ticket["race_id"],
                    bucket=ticket["bucket"],
                    bet_type=ticket["bet_type"],
                    selection=ticket["selection"],
                    selection_json=json.loads(ticket["selection_json"]),
                    amount=int(ticket["amount"]),
                    reason=ticket["reason"],
                )
                for ticket in ticket_rows
            ],
        )

    def list_prediction_records(
        self,
        race_id: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        theory_version: str | None = None,
        mode: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> PredictionRecordPage:
        where: list[str] = []
        params: list[object] = []
        if race_id is not None:
            where.append("p.race_id = ?")
            params.append(race_id)
        if from_date is not None:
            where.append("r.race_date >= ?")
            params.append(from_date.isoformat())
        if to_date is not None:
            where.append("r.race_date <= ?")
            params.append(to_date.isoformat())
        if theory_version is not None:
            where.append("p.theory_version = ?")
            params.append(theory_version)
        if mode is not None:
            where.append("p.mode = ?")
            params.append(mode)
        where_sql = f"where {' and '.join(where)}" if where else ""

        with self._connect() as conn:
            total = int(
                conn.execute(
                    f"""
                    select count(1)
                    from predictions p
                    left join races r on r.race_id = p.race_id
                    {where_sql}
                    """,
                    params,
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"""
                select p.prediction_id
                from predictions p
                left join races r on r.race_id = p.race_id
                {where_sql}
                order by p.created_at desc, p.prediction_id desc
                limit ? offset ?
                """,
                [*params, limit, offset],
            ).fetchall()
            items = [self._get_prediction_record(conn, row["prediction_id"]) for row in rows]
        return PredictionRecordPage(items=items, total=total, limit=limit, offset=offset)

    def get_evaluation_record(self, evaluation_id: str) -> EvaluationRecord:
        with self._connect() as conn:
            return self._get_evaluation_record(conn, evaluation_id)

    def _get_evaluation_record(self, conn: sqlite3.Connection, evaluation_id: str) -> EvaluationRecord:
        row = conn.execute(
            """
            select evaluation_id, prediction_id, race_id, theory_version, total_bet,
                   total_payout, return_rate, hit, gami, axis_in_top3,
                   middle_hole_in_top3, firework_hit, max_odds_selected,
                   evaluation_json, created_at
            from evaluations
            where evaluation_id = ?
            """,
            (evaluation_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f"evaluation not found for evaluation_id={evaluation_id}")

        ticket_rows = conn.execute(
            """
            select ticket_result_id, evaluation_id, ticket_id, bucket, bet_type,
                   selection, amount, hit, payout
            from evaluation_ticket_results
            where evaluation_id = ?
            order by rowid
            """,
            (evaluation_id,),
        ).fetchall()
        return EvaluationRecord(
            evaluation_id=row["evaluation_id"],
            prediction_id=row["prediction_id"],
            race_id=row["race_id"],
            theory_version=row["theory_version"],
            total_bet=int(row["total_bet"]),
            total_payout=int(row["total_payout"]),
            return_rate=float(row["return_rate"]),
            hit=bool(row["hit"]),
            gami=bool(row["gami"]),
            axis_in_top3=bool(row["axis_in_top3"]) if row["axis_in_top3"] is not None else None,
            middle_hole_in_top3=(
                bool(row["middle_hole_in_top3"]) if row["middle_hole_in_top3"] is not None else None
            ),
            firework_hit=bool(row["firework_hit"]) if row["firework_hit"] is not None else None,
            max_odds_selected=(
                float(row["max_odds_selected"]) if row["max_odds_selected"] is not None else None
            ),
            evaluation=json.loads(row["evaluation_json"]),
            created_at=_parse_datetime(row["created_at"]),
            ticket_results=[
                EvaluationTicketResultRecord(
                    ticket_result_id=ticket["ticket_result_id"],
                    evaluation_id=ticket["evaluation_id"],
                    ticket_id=ticket["ticket_id"],
                    bucket=ticket["bucket"],
                    bet_type=ticket["bet_type"],
                    selection=ticket["selection"],
                    amount=int(ticket["amount"]),
                    hit=bool(ticket["hit"]),
                    payout=int(ticket["payout"]),
                )
                for ticket in ticket_rows
            ],
        )

    def list_evaluation_records(
        self,
        prediction_id: str | None = None,
        race_id: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        theory_version: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> EvaluationRecordPage:
        where, params = _evaluation_filters(
            prediction_id=prediction_id,
            race_id=race_id,
            from_date=from_date,
            to_date=to_date,
            theory_version=theory_version,
        )
        where_sql = f"where {' and '.join(where)}" if where else ""
        with self._connect() as conn:
            total = int(
                conn.execute(
                    f"""
                    select count(1)
                    from evaluations e
                    left join races r on r.race_id = e.race_id
                    {where_sql}
                    """,
                    params,
                ).fetchone()[0]
            )
            rows = conn.execute(
                f"""
                select e.evaluation_id
                from evaluations e
                left join races r on r.race_id = e.race_id
                {where_sql}
                order by e.created_at desc, e.evaluation_id desc
                limit ? offset ?
                """,
                [*params, limit, offset],
            ).fetchall()
            items = [self._get_evaluation_record(conn, row["evaluation_id"]) for row in rows]
        return EvaluationRecordPage(items=items, total=total, limit=limit, offset=offset)

    def summarize_evaluations(
        self,
        from_date: date | None = None,
        to_date: date | None = None,
        theory_version: str | None = None,
    ) -> EvaluationSummary:
        where, params = _evaluation_filters(
            from_date=from_date,
            to_date=to_date,
            theory_version=theory_version,
        )
        where_sql = f"where {' and '.join(where)}" if where else ""
        with self._connect() as conn:
            row = conn.execute(
                f"""
                select count(1) as evaluation_count,
                       coalesce(sum(e.total_bet), 0) as total_bet,
                       coalesce(sum(e.total_payout), 0) as total_payout,
                       coalesce(sum(e.hit), 0) as hit_count,
                       coalesce(sum(e.gami), 0) as gami_count,
                       coalesce(sum(case when e.axis_in_top3 = 1 then 1 else 0 end), 0) as axis_in_top3_count,
                       count(e.axis_in_top3) as axis_in_top3_total,
                       coalesce(sum(case when e.middle_hole_in_top3 = 1 then 1 else 0 end), 0) as middle_hole_in_top3_count,
                       count(e.middle_hole_in_top3) as middle_hole_in_top3_total,
                       coalesce(sum(case when e.firework_hit = 1 then 1 else 0 end), 0) as firework_hit_count,
                       count(e.firework_hit) as firework_hit_total
                from evaluations e
                left join races r on r.race_id = e.race_id
                {where_sql}
                """,
                params,
            ).fetchone()
            max_single_payout = int(
                conn.execute(
                    f"""
                    select coalesce(max(etr.payout), 0)
                    from evaluation_ticket_results etr
                    join evaluations e on e.evaluation_id = etr.evaluation_id
                    left join races r on r.race_id = e.race_id
                    {where_sql}
                    """,
                    params,
                ).fetchone()[0]
            )

        evaluation_count = int(row["evaluation_count"])
        total_bet = int(row["total_bet"])
        total_payout = int(row["total_payout"])
        hit_count = int(row["hit_count"])
        gami_count = int(row["gami_count"])
        axis_count = int(row["axis_in_top3_count"])
        axis_total = int(row["axis_in_top3_total"])
        middle_count = int(row["middle_hole_in_top3_count"])
        middle_total = int(row["middle_hole_in_top3_total"])
        firework_count = int(row["firework_hit_count"])
        firework_total = int(row["firework_hit_total"])
        return EvaluationSummary(
            evaluation_count=evaluation_count,
            total_bet=total_bet,
            total_payout=total_payout,
            return_rate=(total_payout / total_bet) if total_bet else 0.0,
            hit_count=hit_count,
            hit_rate=(hit_count / evaluation_count) if evaluation_count else 0.0,
            gami_count=gami_count,
            gami_rate=(gami_count / evaluation_count) if evaluation_count else 0.0,
            axis_in_top3_count=axis_count,
            axis_in_top3_rate=(axis_count / axis_total) if axis_total else 0.0,
            middle_hole_in_top3_count=middle_count,
            middle_hole_in_top3_rate=(middle_count / middle_total) if middle_total else 0.0,
            firework_hit_count=firework_count,
            firework_hit_rate=(firework_count / firework_total) if firework_total else 0.0,
            max_single_payout=max_single_payout,
            return_rate_without_max_payout=(
                (total_payout - max_single_payout) / total_bet if total_bet else 0.0
            ),
        )

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
            payout = _scale_payout_for_amount(
                int(payout_index.get((ticket.bet_type, ticket.selection), 0)),
                int(ticket.amount),
            )
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

    def get_pre_race_snapshot(
        self,
        race_id: str,
        *,
        include_odds: bool = True,
        odds_timing: str | None = None,
        as_of: datetime | None = None,
    ) -> StoredPreRaceSnapshot:
        if as_of is not None and as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone offset")
        as_of_text = _dt(as_of)
        with self._connect() as conn:
            race_exists = conn.execute(
                "select 1 from races where race_id = ?",
                (race_id,),
            ).fetchone()
            if race_exists is None:
                raise LookupError(f"race not found for race_id={race_id}")

            card_where = """
                race_id = ?
                and runner_set_status = 'complete'
                and source_kind = 'pre_race_card'
            """
            card_params: list[object] = [race_id]
            if as_of_text is not None:
                card_where += " and julianday(fetched_at) <= julianday(?)"
                card_params.append(as_of_text)
            card_snapshot = conn.execute(
                f"""
                select *
                from race_card_snapshots
                where {card_where}
                order by julianday(fetched_at) desc, card_snapshot_id desc
                limit 1
                """,
                tuple(card_params),
            ).fetchone()
            if card_snapshot is not None:
                race = card_snapshot
                runners = conn.execute(
                    """
                    select *
                    from race_card_snapshot_runners
                    where card_snapshot_id = ?
                    order by cast(horse_no as integer), horse_no
                    """,
                    (card_snapshot["card_snapshot_id"],),
                ).fetchall()
            elif as_of is not None:
                raise LookupError(
                    f"pre-race card snapshot not found for race_id={race_id} as_of={as_of_text}"
                )
            else:
                race = conn.execute(
                    "select * from races where race_id = ?",
                    (race_id,),
                ).fetchone()
                runners = conn.execute(
                    """
                    select *
                    from runners
                    where race_id = ?
                    order by cast(horse_no as integer), horse_no
                    """,
                    (race_id,),
                ).fetchall()

            available_odds_timings: list[str] = []
            snapshots: list[sqlite3.Row] = []
            if include_odds:
                odds_where = "race_id = ?"
                odds_params: list[object] = [race_id]
                if as_of_text is not None:
                    odds_where += " and julianday(fetched_at) <= julianday(?)"
                    odds_params.append(as_of_text)
                timing_rows = conn.execute(
                    f"""
                    select odds_timing, min(julianday(fetched_at)) as first_fetched_at
                    from odds_snapshots
                    where {odds_where}
                    group by odds_timing
                    order by first_fetched_at, odds_timing
                    """,
                    tuple(odds_params),
                ).fetchall()
                available_odds_timings = [row["odds_timing"] for row in timing_rows]
                timing_filter = ""
                timing_params = list(odds_params)
                if odds_timing is not None:
                    timing_filter = " and odds_timing = ?"
                    timing_params.append(odds_timing)
                candidate_snapshots = conn.execute(
                    f"""
                    select *
                    from odds_snapshots
                    where {odds_where}{timing_filter}
                    order by bet_type, julianday(fetched_at) desc, snapshot_id desc
                    """,
                    tuple(timing_params),
                ).fetchall()
                seen_bet_types: set[str] = set()
                for snapshot in candidate_snapshots:
                    if snapshot["bet_type"] in seen_bet_types:
                        continue
                    seen_bet_types.add(snapshot["bet_type"])
                    snapshots.append(snapshot)

            odds: list[StoredOddsSnapshot] = []
            for snapshot in snapshots:
                entries = conn.execute(
                    """
                    select bet_type, combination_json, odds, odds_min, odds_max, popularity
                    from odds_entries
                    where snapshot_id = ?
                    order by popularity is null, popularity, combination
                    """,
                    (snapshot["snapshot_id"],),
                ).fetchall()
                odds.append(
                    _stored_odds_snapshot(snapshot, entries)
                )

        missing_components = []
        if not runners:
            missing_components.append("runners")
        if include_odds and not odds:
            missing_components.append("odds")
        return StoredPreRaceSnapshot(
            race=StoredPreRace.model_validate(_row_to_dict(race)),
            runners=[
                StoredPreRaceRunner.model_validate(_row_to_dict(runner))
                for runner in runners
            ],
            odds=odds,
            meta=StoredPreRaceSnapshotMeta(
                include_odds=include_odds,
                requested_odds_timing=odds_timing,
                requested_as_of=as_of,
                card_snapshot_id=(
                    str(card_snapshot["card_snapshot_id"])
                    if card_snapshot is not None
                    else None
                ),
                card_fetched_at=(
                    _parse_datetime(card_snapshot["fetched_at"])
                    if card_snapshot is not None
                    else None
                ),
                runner_set_status=(
                    card_snapshot["runner_set_status"]
                    if card_snapshot is not None
                    else None
                ),
                available_odds_timings=available_odds_timings,
                missing_components=missing_components,
            ),
        )

    def list_pre_race_race_ids(self, target_date: date) -> list[str]:
        """Return races that have a complete locally stored pre-race card."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                select r.race_id
                from races r
                where r.race_date = ?
                  and exists (
                      select 1
                      from race_card_snapshots cs
                      where cs.race_id = r.race_id
                        and cs.runner_set_status = 'complete'
                        and cs.source_kind = 'pre_race_card'
                  )
                order by r.course, r.race_no, r.race_id
                """,
                (target_date.isoformat(),),
            ).fetchall()
        return [str(row["race_id"]) for row in rows]

    def get_odds_timeline(
        self,
        race_id: str,
        bet_type: str,
        combination: list[str] | None = None,
    ) -> StoredOddsTimeline:
        with self._connect() as conn:
            race = conn.execute(
                "select 1 from races where race_id = ?",
                (race_id,),
            ).fetchone()
            if race is None:
                raise LookupError(f"race not found for race_id={race_id}")
            normalized_combination = (
                _normalize_selection_items(bet_type, combination)
                if combination is not None
                else None
            )
            snapshot_rows = conn.execute(
                """
                select *
                from odds_snapshots
                where race_id = ? and bet_type = ?
                order by fetched_at, snapshot_id
                """,
                (race_id, bet_type),
            ).fetchall()
            snapshots: list[StoredOddsSnapshot] = []
            for snapshot in snapshot_rows:
                entry_rows = conn.execute(
                    """
                    select bet_type, combination_json, odds, odds_min, odds_max, popularity
                    from odds_entries
                    where snapshot_id = ?
                    order by popularity is null, popularity, combination
                    """,
                    (snapshot["snapshot_id"],),
                ).fetchall()
                if normalized_combination is not None:
                    entry_rows = [
                        entry
                        for entry in entry_rows
                        if _normalize_selection_items(
                            bet_type,
                            json.loads(entry["combination_json"]),
                        )
                        == normalized_combination
                    ]
                snapshots.append(_stored_odds_snapshot(snapshot, entry_rows))

        return StoredOddsTimeline(
            race_id=race_id,
            bet_type=bet_type,
            combination=normalized_combination or [],
            snapshots=snapshots,
            total=len(snapshots),
        )

    def count_rows(self, table: str) -> int:
        if not re.fullmatch(r"[a-z_]+", table):
            raise ValueError(f"invalid table name={table}")
        with self._connect() as conn:
            return int(conn.execute(f"select count(*) from {table}").fetchone()[0])

    def replace_daily_prediction_log_entries(
        self,
        source_path: str,
        log_date: str | None,
        venue: str | None,
        entries: list[dict[str, object]],
    ) -> dict[str, int]:
        import_id = str(uuid4())
        imported_at = _now()
        resolved_race_ids = 0
        with self._connect() as conn:
            existing = conn.execute(
                """
                select import_id
                from daily_prediction_log_imports
                where source_path = ? and ((log_date is null and ? is null) or log_date = ?)
                """,
                (source_path, log_date, log_date),
            ).fetchone()
            if existing is not None:
                import_id = existing["import_id"]
                conn.execute("delete from daily_prediction_log_entries where import_id = ?", (import_id,))
                conn.execute(
                    """
                    update daily_prediction_log_imports
                    set venue = ?, imported_at = ?
                    where import_id = ?
                    """,
                    (venue, imported_at, import_id),
                )
            else:
                conn.execute(
                    """
                    insert into daily_prediction_log_imports
                    (import_id, source_path, log_date, venue, imported_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (import_id, source_path, log_date, venue, imported_at),
                )

            for entry in entries:
                race_id = self._resolve_race_id(
                    conn,
                    race_date=str(entry["race_date"]) if entry.get("race_date") else None,
                    course=str(entry["course"]) if entry.get("course") else None,
                    race_no=int(entry["race_no"]) if entry.get("race_no") is not None else None,
                )
                if race_id is not None:
                    resolved_race_ids += 1
                conn.execute(
                    """
                    insert into daily_prediction_log_entries
                    (entry_id, import_id, race_id, race_date, course, race_no,
                     entry_timestamp, entry_type, topic, prediction_mode,
                     raw_markdown, payload_json)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(uuid4()),
                        import_id,
                        race_id,
                        entry.get("race_date"),
                        entry.get("course"),
                        entry.get("race_no"),
                        _dt(entry["entry_timestamp"]),
                        entry["entry_type"],
                        entry.get("topic"),
                        entry.get("prediction_mode"),
                        entry["raw_markdown"],
                        json.dumps(entry["payload"], ensure_ascii=False),
                    ),
                )
        return {"imported_entries": len(entries), "resolved_race_ids": resolved_race_ids}

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

    def _resolve_race_id(
        self,
        conn: sqlite3.Connection,
        race_date: str | None,
        course: str | None,
        race_no: int | None,
    ) -> str | None:
        if race_date is None or course is None or race_no is None:
            return None
        row = conn.execute(
            """
            select race_id
            from races
            where race_date = ? and course = ? and race_no = ?
            order by fetched_at desc
            limit 1
            """,
            (race_date, course, race_no),
        ).fetchone()
        return None if row is None else str(row["race_id"])


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


def _scale_payout_for_amount(base_payout: int, amount: int) -> int:
    if base_payout <= 0 or amount <= 0:
        return 0
    return int(round(base_payout * (amount / 100.0)))


def _coerce_datetime_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _to_db_bool(value: bool | None) -> int | None:
    if value is None:
        return None
    return int(bool(value))


def _normalize_prediction_ticket(ticket: dict, prediction_id: str, race_id: str) -> dict[str, object]:
    bet_type = str(ticket["bet_type"])
    raw_selection = ticket.get("selection")
    if isinstance(raw_selection, list):
        selection_json = _normalize_selection_items(bet_type, [str(item) for item in raw_selection])
        selection = "-".join(selection_json)
    elif raw_selection is not None:
        selection = _normalize_selection_string(bet_type, str(raw_selection))
        selection_json = selection.split("-")
    else:
        raise BadRequestError(f"prediction ticket selection is required for prediction_id={prediction_id}")
    return {
        "ticket_id": str(ticket.get("ticket_id") or str(uuid4())),
        "prediction_id": prediction_id,
        "race_id": race_id,
        "bucket": ticket.get("bucket"),
        "bet_type": bet_type,
        "selection": selection,
        "selection_json": selection_json,
        "amount": int(ticket["amount"]),
        "reason": ticket.get("reason"),
    }


def _extract_prediction_race_context(payload: dict, race_id: str) -> dict[str, object] | None:
    context = payload.get("race_context")
    if isinstance(context, dict):
        merged = dict(context)
        merged.setdefault("race_id", race_id)
        return merged

    snapshot = payload.get("pre_race_snapshot")
    if not isinstance(snapshot, dict):
        return None
    card = snapshot.get("card") if isinstance(snapshot.get("card"), dict) else None
    source = card or snapshot
    race_date = snapshot.get("date") or snapshot.get("race_date")
    course = snapshot.get("course") or (card.get("course") if card else None)
    race_no = snapshot.get("race_no")
    if race_date is None or course is None or race_no is None:
        return None
    runners = None
    if card and isinstance(card.get("runners"), list):
        runners = card.get("runners")
    elif isinstance(snapshot.get("runners"), list):
        runners = snapshot.get("runners")
    return {
        "race_id": str(source.get("race_id") or race_id),
        "race_date": race_date,
        "course": course,
        "meeting_no": snapshot.get("meeting_no"),
        "meeting_day": snapshot.get("meeting_day"),
        "race_no": race_no,
        "race_name": source.get("race_name"),
        "start_time": source.get("start_time"),
        "surface": source.get("surface"),
        "distance": source.get("distance"),
        "source": source.get("source"),
        "fetched_at": source.get("fetched_at"),
        "runners": runners,
    }


def _upsert_race_context(conn: sqlite3.Connection, context: dict[str, object]) -> None:
    race_id = str(context["race_id"])
    conn.execute(
        """
        insert into races
        (race_id, race_date, course, meeting_no, meeting_day, race_no, race_name, race_grade, start_time, surface, distance, source, fetched_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(race_id) do update set
            race_date = excluded.race_date,
            course = excluded.course,
            meeting_no = coalesce(excluded.meeting_no, races.meeting_no),
            meeting_day = coalesce(excluded.meeting_day, races.meeting_day),
            race_no = excluded.race_no,
            race_name = coalesce(excluded.race_name, races.race_name),
            race_grade = coalesce(excluded.race_grade, races.race_grade),
            start_time = coalesce(excluded.start_time, races.start_time),
            surface = coalesce(excluded.surface, races.surface),
            distance = coalesce(excluded.distance, races.distance),
            source = coalesce(excluded.source, races.source),
            fetched_at = coalesce(excluded.fetched_at, races.fetched_at)
        """,
        (
            race_id,
            context.get("race_date"),
            context.get("course"),
            _parse_int(_stringify_optional(context.get("meeting_no"))),
            _parse_int(_stringify_optional(context.get("meeting_day"))),
            _parse_int(_stringify_optional(context.get("race_no"))),
            context.get("race_name"),
            context.get("race_grade"),
            context.get("start_time"),
            context.get("surface"),
            _stringify_optional(context.get("distance")),
            context.get("source"),
            _coerce_datetime_text(context.get("fetched_at")),
        ),
    )
    runners = context.get("runners")
    if not isinstance(runners, list):
        return
    conn.execute("delete from runners where race_id = ?", (race_id,))
    for runner in runners:
        if not isinstance(runner, dict):
            continue
        horse_no = runner.get("horse_no")
        horse_name = runner.get("horse_name")
        if horse_no is None or horse_name is None:
            continue
        conn.execute(
            """
            insert into runners
            (race_id, horse_no, frame_no, horse_name, sex_age, weight_carried, jockey, trainer, card_odds, card_popularity)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                race_id,
                str(horse_no),
                _stringify_optional(runner.get("frame_no")),
                str(horse_name),
                _stringify_optional(runner.get("sex_age")),
                _stringify_optional(runner.get("weight_carried")),
                _stringify_optional(runner.get("jockey")),
                _stringify_optional(runner.get("trainer")),
                _parse_float(_stringify_optional(runner.get("odds"))),
                _parse_int(_stringify_optional(runner.get("popularity"))),
            ),
        )


def _extract_predicted_top3(prediction_json: dict) -> list[dict]:
    top3 = prediction_json.get("predicted_top3")
    if isinstance(top3, list):
        return [item for item in top3 if isinstance(item, dict)]
    ranking = prediction_json.get("predicted_ranking")
    if isinstance(ranking, list):
        return [item for item in ranking if isinstance(item, dict)]
    return []


def _extract_axis_horse_numbers(prediction_json: dict) -> list[str]:
    values: list[str] = []
    axis_numbers = prediction_json.get("axis_horse_numbers")
    if isinstance(axis_numbers, list):
        values.extend(str(item) for item in axis_numbers if item is not None)
    axis = prediction_json.get("axis")
    if isinstance(axis, dict) and axis.get("horse_no") is not None:
        values.append(str(axis["horse_no"]))
    for item in _extract_predicted_top3(prediction_json):
        role = str(item.get("role") or "")
        if role in {"axis", "head_axis", "axis_head"} and item.get("horse_no") is not None:
            values.append(str(item["horse_no"]))
    return list(dict.fromkeys(values))


def _extract_middle_hole_horse_numbers(prediction_json: dict) -> list[str]:
    candidates = prediction_json.get("middle_hole_candidates")
    if not isinstance(candidates, list):
        return []
    return [str(item["horse_no"]) for item in candidates if isinstance(item, dict) and item.get("horse_no") is not None]


def _compute_max_selected_odds(prediction_json: dict) -> float | None:
    values: list[float] = []
    for item in _extract_predicted_top3(prediction_json):
        value = _parse_float(_stringify_optional(item.get("odds")) or _stringify_optional(item.get("win_odds")))
        if value is not None:
            values.append(value)
    contenders = prediction_json.get("other_contenders")
    if isinstance(contenders, list):
        for item in contenders:
            if not isinstance(item, dict):
                continue
            value = _parse_float(_stringify_optional(item.get("odds")) or _stringify_optional(item.get("win_odds")))
            if value is not None:
                values.append(value)
    return max(values) if values else None


def _stringify_optional(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _stored_odds_snapshot(
    snapshot: sqlite3.Row,
    entries: list[sqlite3.Row],
) -> StoredOddsSnapshot:
    return StoredOddsSnapshot(
        snapshot_id=snapshot["snapshot_id"],
        race_id=snapshot["race_id"],
        bet_type=snapshot["bet_type"],
        odds_timing=snapshot["odds_timing"],
        fetched_at=snapshot["fetched_at"],
        source=snapshot["source"],
        entries=[_stored_odds_entry(entry) for entry in entries],
    )


def _stored_odds_entry(entry: sqlite3.Row) -> StoredOddsEntry:
    return StoredOddsEntry(
        bet_type=entry["bet_type"],
        combination=json.loads(entry["combination_json"]),
        odds=entry["odds"],
        odds_min=entry["odds_min"],
        odds_max=entry["odds_max"],
        popularity=entry["popularity"],
    )


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


def _evaluation_filters(
    prediction_id: str | None = None,
    race_id: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    theory_version: str | None = None,
) -> tuple[list[str], list[object]]:
    where: list[str] = []
    params: list[object] = []
    if prediction_id is not None:
        where.append("e.prediction_id = ?")
        params.append(prediction_id)
    if race_id is not None:
        where.append("e.race_id = ?")
        params.append(race_id)
    if from_date is not None:
        where.append("r.race_date >= ?")
        params.append(from_date.isoformat())
    if to_date is not None:
        where.append("r.race_date <= ?")
        params.append(to_date.isoformat())
    if theory_version is not None:
        where.append("e.theory_version = ?")
        params.append(theory_version)
    return where, params


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    existing = {row["name"] for row in conn.execute(f"pragma table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"alter table {table} add column {column} {column_type}")


def _migrate_odds_snapshots_to_append_only(conn: sqlite3.Connection) -> None:
    legacy_unique_columns = ["race_id", "bet_type", "odds_timing"]
    has_legacy_unique = False
    for index in conn.execute("pragma index_list(odds_snapshots)").fetchall():
        if not bool(index["unique"]):
            continue
        index_name = str(index["name"]).replace('"', '""')
        columns = [
            row["name"]
            for row in conn.execute(f'pragma index_info("{index_name}")').fetchall()
        ]
        if columns == legacy_unique_columns:
            has_legacy_unique = True
            break
    if not has_legacy_unique:
        return

    conn.execute("alter table odds_snapshots rename to odds_snapshots_upsert_legacy")
    conn.execute(
        """
        create table odds_snapshots (
            snapshot_id text primary key,
            race_id text not null,
            bet_type text not null,
            odds_timing text not null,
            fetched_at text not null,
            source text not null
        )
        """
    )
    conn.execute(
        """
        insert into odds_snapshots
        (snapshot_id, race_id, bet_type, odds_timing, fetched_at, source)
        select snapshot_id, race_id, bet_type, odds_timing, fetched_at, source
        from odds_snapshots_upsert_legacy
        """
    )
    conn.execute("drop table odds_snapshots_upsert_legacy")


def _parse_meeting_fields_from_race_id(race_id: str) -> tuple[int | None, int | None]:
    if re.fullmatch(r"\d{16}", race_id):
        return int(race_id[10:12]), int(race_id[12:14])
    return None, None


def _is_all_courses(courses: list[str]) -> bool:
    return len(courses) == 1 and courses[0].strip().lower() in {"all", "*", "auto"}
