from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class CourseCode(StrEnum):
    sapporo = "sapporo"
    hakodate = "hakodate"
    fukushima = "fukushima"
    niigata = "niigata"
    tokyo = "tokyo"
    nakayama = "nakayama"
    chukyo = "chukyo"
    kyoto = "kyoto"
    hanshin = "hanshin"
    kokura = "kokura"


class NankanCourseCode(StrEnum):
    urawa = "urawa"
    funabashi = "funabashi"
    ohi = "ohi"
    kawasaki = "kawasaki"


class BetType(StrEnum):
    win = "win"
    place = "place"
    quinella = "quinella"
    wide = "wide"
    exacta = "exacta"
    trio = "trio"
    trifecta = "trifecta"


class ResultStorageKind(StrEnum):
    jsonl = "jsonl"
    sqlite = "sqlite"


class ResultCollectionJobStatus(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class DecisionSource(StrEnum):
    agent = "agent"
    manual = "manual"
    agent_plus_manual = "agent_plus_manual"


class CachePolicyMeta(BaseModel):
    cache_policy: str = "db_first_ttl"
    data_source: str
    db_hit: bool = False
    ttl_expired: bool = False
    saved: bool = False
    stale: bool = False
    refresh_error: str | None = None
    fetched_at: datetime | None = None


class RaceSummary(BaseModel):
    race_id: str
    race_number: str | None = None
    name: str
    course: str | None = None
    start_time: str | None = None
    url: str | None = None


class Runner(BaseModel):
    frame_no: str | None = None
    horse_no: str | None = None
    horse_name: str
    sex_age: str | None = None
    weight_carried: str | None = None
    jockey: str | None = None
    trainer: str | None = None
    horse_weight: str | None = None
    horse_weight_diff: str | None = None
    odds: str | None = None
    popularity: str | None = None


class RaceCardDataStatus(BaseModel):
    horse_weight: str | None = None
    horse_weight_reason: str | None = None


class OddsEntry(BaseModel):
    bet_type: str | None = None
    combination: list[str] = Field(default_factory=list)
    odds: str | None = None
    odds_min: str | None = None
    odds_max: str | None = None
    popularity: str | None = None


class ResultEntry(BaseModel):
    rank: str
    horse_no: str | None = None
    horse_name: str
    jockey: str | None = None
    time: str | None = None


class PayoutEntry(BaseModel):
    bet_type: str
    combination: str
    payout: str
    popularity: str | None = None


class NetkeibaResultEntry(BaseModel):
    rank: str
    frame_no: str | None = None
    horse_no: str | None = None
    horse_name: str
    sex_age: str | None = None
    weight_carried: str | None = None
    jockey: str | None = None
    trainer: str | None = None
    horse_weight: str | None = None
    horse_weight_diff: str | None = None
    finish_time: str | None = None
    margin: str | None = None
    corner_order: str | None = None
    final_3f: str | None = None
    win_odds: str | None = None
    popularity: str | None = None


class NetkeibaRaceResult(BaseModel):
    race_id: str
    race_name: str | None = None
    date: str | None = None
    course: str | None = None
    race_no: str | None = None
    surface: str | None = None
    distance: str | None = None
    direction: str | None = None
    weather: str | None = None
    track_condition: str | None = None
    results: list[NetkeibaResultEntry] = Field(default_factory=list)
    payouts: list[PayoutEntry] = Field(default_factory=list)
    corner_passages: list[str] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False


class NarCalendarEntry(BaseModel):
    date: date
    course: str
    course_key: str
    kaisai_id: str
    race_list_url: str | None = None
    tags: list[str] = Field(default_factory=list)


class NarCalendarPage(BaseModel):
    year: int
    month: int
    course: str | None = None
    entries: list[NarCalendarEntry] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False


class RaceCard(BaseModel):
    race_id: str
    race_name: str | None = None
    course: str | None = None
    distance: str | None = None
    surface: str | None = None
    surface_label: str | None = None
    start_time: str | None = None
    weather: str | None = None
    weather_label: str | None = None
    track_condition: str | None = None
    track_condition_label: str | None = None
    runners: list[Runner] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False
    meta: CachePolicyMeta | None = None
    data_status: RaceCardDataStatus | None = None


class MeetingRace(BaseModel):
    race_no: int
    race_id: str
    race_name: str | None = None
    start_time: str | None = None
    surface: str | None = None
    surface_label: str | None = None
    distance: str | None = None
    weather: str | None = None
    weather_label: str | None = None
    track_condition: str | None = None
    track_condition_label: str | None = None
    card_cname: str | None = None
    odds_cname: str | None = None
    result_cname: str | None = None


class MeetingSnapshot(BaseModel):
    date: date
    course: str
    races: list[MeetingRace] = Field(default_factory=list)
    weather: str | None = None
    weather_label: str | None = None
    track_condition: str | None = None
    track_condition_label: str | None = None
    surface: str | None = None
    surface_label: str | None = None
    fetched_at: datetime
    source: str
    cache_hit: bool = False
    meta: CachePolicyMeta | None = None


class NankanTrendFrameEntry(BaseModel):
    frame_no: str
    top3_count: int


class NankanTrendPersonEntry(BaseModel):
    name: str
    affiliation: str | None = None
    top3_count: int


class NankanTrendBloodlineEntry(BaseModel):
    name: str
    top3_count: int


class NankanTrendRunningStyleSummary(BaseModel):
    front_group_top3_count: int | None = None
    back_group_top3_count: int | None = None


class NankanTrendPayoutSummary(BaseModel):
    trifecta_max_payout: int | None = None
    trifecta_max_payout_race_no: int | None = None


class NankanTrendSummary(BaseModel):
    frame: list[NankanTrendFrameEntry] = Field(default_factory=list)
    running_style: NankanTrendRunningStyleSummary = Field(default_factory=NankanTrendRunningStyleSummary)
    jockey: list[NankanTrendPersonEntry] = Field(default_factory=list)
    trainer: list[NankanTrendPersonEntry] = Field(default_factory=list)
    sire: list[NankanTrendBloodlineEntry] = Field(default_factory=list)
    broodmare_sire: list[NankanTrendBloodlineEntry] = Field(default_factory=list)
    payout: NankanTrendPayoutSummary = Field(default_factory=NankanTrendPayoutSummary)


class NankanMeetingTrend(BaseModel):
    date: date
    course: str
    meeting_id: str
    open_date: str
    updated_at: datetime | None = None
    race_count_completed: int = 0
    summary: NankanTrendSummary = Field(default_factory=NankanTrendSummary)
    fetched_at: datetime
    source: str
    cache_hit: bool = False
    meta: CachePolicyMeta | None = None


class NankanMeetingTrendContext(BaseModel):
    date: date
    course: str
    race_no: int
    race_count_completed: int
    required_max_completed: int
    usable: bool
    reason: str | None = None
    summary: NankanTrendSummary = Field(default_factory=NankanTrendSummary)
    fetched_at: datetime
    source: str
    trend: NankanMeetingTrend | None = None
    cache_hit: bool = False
    meta: CachePolicyMeta | None = None


class NankanBestTimeRunner(BaseModel):
    horse_no: str
    horse_name: str
    best_time: str | None = None
    best_time_rank: int | None = None
    best_time_source_race_id: str | None = None
    best_time_source_date: date | None = None
    best_time_source_course: str | None = None
    best_time_source_distance: int | None = None
    same_course_flag: bool | None = None
    same_distance_flag: bool | None = None
    track_condition: str | None = None
    horse_profile_id: str | None = None


class NankanRaceBestTime(BaseModel):
    race_id: str
    race_name: str | None = None
    course: str | None = None
    distance: int | None = None
    surface: str | None = None
    runners: list[NankanBestTimeRunner] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False
    meta: CachePolicyMeta | None = None


class NankanClosingSpeedRunner(BaseModel):
    horse_no: str
    horse_name: str
    best_closing_time: str | None = None
    best_closing_rank: int | None = None
    closing_time_source_race_id: str | None = None
    closing_time_source_date: date | None = None
    same_course_flag: bool | None = None
    same_distance_flag: bool | None = None
    track_condition: str | None = None
    closing_section_distance: int | None = 600
    horse_profile_id: str | None = None


class NankanRaceClosingSpeed(BaseModel):
    race_id: str
    race_name: str | None = None
    course: str | None = None
    distance: int | None = None
    surface: str | None = None
    runners: list[NankanClosingSpeedRunner] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False
    meta: CachePolicyMeta | None = None


class NankanStyleScores(BaseModel):
    front: float = 0.0
    stalker: float = 0.0
    midpack: float = 0.0
    closer: float = 0.0


class NankanStyleRecentRace(BaseModel):
    source_date: date | None = None
    course: str | None = None
    race_no: int | None = None
    corner_positions: list[int] = Field(default_factory=list)
    field_size: int | None = None
    distance: int | None = None
    track_condition: str | None = None
    finish_rank: int | None = None


class NankanStyleProfileRunner(BaseModel):
    horse_no: str
    horse_name: str
    style_scores: NankanStyleScores = Field(default_factory=NankanStyleScores)
    expected_style: str | None = None
    sample_size: int = 0
    recent_races: list[NankanStyleRecentRace] = Field(default_factory=list)
    horse_profile_id: str | None = None


class NankanRaceStyleProfile(BaseModel):
    race_id: str
    runners: list[NankanStyleProfileRunner] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False
    meta: CachePolicyMeta | None = None


class NankanLeadingJockeyItem(BaseModel):
    rank: int | None = None
    jockey_code: str | None = None
    jockey_name: str
    rides: int | None = None
    wins: int | None = None
    seconds: int | None = None
    thirds: int | None = None
    win_rate: float | None = None
    quinella_rate: float | None = None
    trio_rate: float | None = None


class NankanLeadingJockeyPage(BaseModel):
    source: str = "nankankeiba"
    source_url: str | None = None
    requested_condition_code: str | None = None
    effective_condition_code: str | None = None
    fallback: bool = False
    course: str | None = None
    distance: int | None = None
    track_condition: str | None = None
    period: str
    sort: str
    generated_at: datetime
    items: list[NankanLeadingJockeyItem] = Field(default_factory=list)
    cache_hit: bool = False
    meta: CachePolicyMeta | None = None


class RaceOdds(BaseModel):
    race_id: str
    bet_type: str | None = None
    entries: list[OddsEntry] = Field(default_factory=list)
    odds: dict[str, list[OddsEntry]] = Field(default_factory=dict)
    fetched_at: datetime
    source: str
    cache_hit: bool = False
    meta: CachePolicyMeta | None = None


class JraMaterialStatus(StrEnum):
    available = "available"
    partial = "partial"
    unavailable = "unavailable"
    upstream_error = "upstream_error"
    disabled = "disabled"


class JraSourceKeys(BaseModel):
    jra_internal_race_id: str
    netkeiba_race_id: str
    keibalab_race_code: str
    umanity_race_code: str


class JraRecentRace(BaseModel):
    source_date: date | None = None
    source_course: str | None = None
    source_race_no: int | None = None
    surface: str | None = None
    distance: int | None = None
    track_condition: str | None = None
    finish_rank: int | None = None
    field_size: int | None = None
    finish_time: str | None = None
    final_3f: float | None = None
    corner_positions: list[int] = Field(default_factory=list)
    weight_carried: float | None = None
    jockey: str | None = None
    popularity: int | None = None
    win_odds: float | None = None
    source: str
    source_url: str | None = None


class JraPublicRunnerAnalysis(BaseModel):
    horse_no: str
    horse_name: str
    omega_index: float | None = None
    recent_races: list[JraRecentRace] = Field(default_factory=list)


class JraPublicSourceAnalysis(BaseModel):
    source: str
    status: JraMaterialStatus
    source_url: str | None = None
    course_analysis: dict[str, list[str]] = Field(default_factory=dict)
    runners: list[JraPublicRunnerAnalysis] = Field(default_factory=list)
    locked_fields: list[str] = Field(default_factory=list)
    reason: str | None = None
    warnings: list[str] = Field(default_factory=list)
    fetched_at: datetime
    cache_hit: bool = False


class JraPublicAnalysis(BaseModel):
    race_id: str
    date: date
    course: str
    race_no: int
    meeting_no: int
    meeting_day: int
    status: JraMaterialStatus
    sources: dict[str, JraPublicSourceAnalysis] = Field(default_factory=dict)
    fetched_at: datetime
    cache_hit: bool = False
    source_keys: JraSourceKeys


class JraLiteRunnerMaterial(BaseModel):
    horse_no: str
    horse_name: str
    status: JraMaterialStatus
    value: str | float | None = None
    rank: int | None = None
    sample_size: int = 0
    source_race: JraRecentRace | None = None
    details: dict[str, object] = Field(default_factory=dict)
    reason: str | None = None


class JraLiteMaterial(BaseModel):
    race_id: str
    kind: str
    scope: str = "visible_recent_races"
    max_recent_races: int = 5
    status: JraMaterialStatus
    runners: list[JraLiteRunnerMaterial] = Field(default_factory=list)
    fetched_at: datetime
    source: str = "public_race_pages"
    cache_hit: bool = False


class JraTrendContext(BaseModel):
    date: date
    course: str
    race_no: int
    race_count_completed: int
    required_max_completed: int
    usable: bool
    status: JraMaterialStatus
    summary: dict[str, object] = Field(default_factory=dict)
    skipped_races: list[int] = Field(default_factory=list)
    reason: str | None = None
    fetched_at: datetime
    source: str = "jra_official_same_day_results"


class JraPredictionBundleMeta(BaseModel):
    parallelized: bool = True
    used_existing_services: bool = True
    source_keys: JraSourceKeys
    component_status: dict[str, str] = Field(default_factory=dict)


class JraPredictionBundle(BaseModel):
    race_id: str
    date: date
    course: str
    race_no: int
    meeting_no: int
    meeting_day: int
    odds_bet_types: list[str] = Field(default_factory=list)
    card: RaceCard
    odds_summary: RaceOdds
    trend_context: JraTrendContext
    public_analysis: JraPublicAnalysis
    best_time_lite: JraLiteMaterial
    closing_speed_lite: JraLiteMaterial
    style_profile_lite: JraLiteMaterial
    fetched_at: datetime
    cache_hit: bool = False
    meta: JraPredictionBundleMeta


class NankanPredictionBundleMeta(BaseModel):
    parallelized: bool = True
    used_existing_services: bool = True


class NankankeibaPatternRate(BaseModel):
    rate: float | None = None
    wins: int | None = None
    starts: int | None = None


class NankankeibaPatternCategoryEntry(BaseModel):
    category: str
    frame_no: str | None = None
    horse_no: str
    horse_name: str
    jockey: str | None = None
    weight_carried: str | None = None
    trainer: str | None = None
    win_odds: str | None = None
    rates: dict[str, NankankeibaPatternRate] = Field(default_factory=dict)
    jockey_riding_rate: NankankeibaPatternRate | None = None
    track_condition_rates: dict[str, NankankeibaPatternRate] = Field(default_factory=dict)
    season_rates: dict[str, NankankeibaPatternRate] = Field(default_factory=dict)
    frame_group_rates: dict[str, NankankeibaPatternRate] = Field(default_factory=dict)


class NankankeibaPatternRunner(BaseModel):
    frame_no: str | None = None
    horse_no: str
    horse_name: str
    jockey: str | None = None
    weight_carried: str | None = None
    trainer: str | None = None
    categories: dict[str, NankankeibaPatternCategoryEntry] = Field(default_factory=dict)


class NankankeibaPatternCategoryPage(BaseModel):
    race_id: str
    category: str
    entries: list[NankankeibaPatternCategoryEntry] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False
    meta: CachePolicyMeta | None = None


class NankankeibaPatternBundle(BaseModel):
    race_id: str
    date: date
    course: str
    meeting_no: int
    meeting_day: int
    race_no: int
    periods: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    runners: list[NankankeibaPatternRunner] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False
    meta: CachePolicyMeta | None = None


class NankanPredictionBundle(BaseModel):
    race_id: str
    date: date
    course: str
    race_no: int
    meeting_no: int
    meeting_day: int
    odds_bet_types: list[str] = Field(default_factory=list)
    card: RaceCard
    odds_summary: RaceOdds
    trend_context: NankanMeetingTrendContext
    best_time: NankanRaceBestTime
    closing_speed: NankanRaceClosingSpeed
    pattern: NankankeibaPatternBundle
    leading_jockeys: NankanLeadingJockeyPage
    fetched_at: datetime
    cache_hit: bool = False
    meta: NankanPredictionBundleMeta | None = None


class NankanPredictionSummaryTrend(BaseModel):
    race_count_completed: int
    required_max_completed: int
    usable: bool
    reason: str | None = None
    frame_top3: list[NankanTrendFrameEntry] = Field(default_factory=list)
    jockey_top3: list[NankanTrendPersonEntry] = Field(default_factory=list)
    trainer_top3: list[NankanTrendPersonEntry] = Field(default_factory=list)


class NankanPredictionSummaryLeadingJockeyItem(BaseModel):
    rank: int | None = None
    jockey_name: str
    win_rate: float | None = None
    quinella_rate: float | None = None
    trio_rate: float | None = None


class NankanPredictionSummaryLeadingJockeys(BaseModel):
    course: str | None = None
    distance: int | None = None
    track_condition: str | None = None
    period: str
    sort: str
    items: list[NankanPredictionSummaryLeadingJockeyItem] = Field(default_factory=list)


class NankanPredictionSummaryBestTime(BaseModel):
    best_time: str | None = None
    best_time_rank: int | None = None
    same_course_flag: bool | None = None
    same_distance_flag: bool | None = None
    track_condition: str | None = None


class NankanPredictionSummaryClosingSpeed(BaseModel):
    best_closing_time: str | None = None
    best_closing_rank: int | None = None
    same_course_flag: bool | None = None
    same_distance_flag: bool | None = None
    track_condition: str | None = None


class NankanPredictionSummaryPattern(BaseModel):
    course_rate: NankankeibaPatternRate | None = None
    distance_rate: NankankeibaPatternRate | None = None
    track_condition_rate: NankankeibaPatternRate | None = None
    jockey_riding_rate: NankankeibaPatternRate | None = None
    jockey_trainer_course_rate: NankankeibaPatternRate | None = None


class NankanPredictionSummaryRunner(BaseModel):
    frame_no: str | None = None
    horse_no: str | None = None
    horse_name: str
    sex_age: str | None = None
    weight_carried: str | None = None
    jockey: str | None = None
    trainer: str | None = None
    horse_weight: str | None = None
    horse_weight_diff: str | None = None
    win_odds: str | None = None
    popularity: str | None = None
    best_time: NankanPredictionSummaryBestTime | None = None
    closing_speed: NankanPredictionSummaryClosingSpeed | None = None
    pattern: NankanPredictionSummaryPattern | None = None


class NankanPredictionSummaryMeta(BaseModel):
    generated_from: str = "prediction_bundle"
    odds_bet_types: list[str] = Field(default_factory=list)
    cache_hit: bool = False


class NankanPredictionSummary(BaseModel):
    race_id: str
    date: date
    course: str
    race_no: int
    meeting_no: int
    meeting_day: int
    distance: str | None = None
    track_condition: str | None = None
    track_condition_label: str | None = None
    data_status: RaceCardDataStatus | None = None
    trend: NankanPredictionSummaryTrend
    leading_jockeys: NankanPredictionSummaryLeadingJockeys
    runners: list[NankanPredictionSummaryRunner] = Field(default_factory=list)
    meta: NankanPredictionSummaryMeta = Field(default_factory=NankanPredictionSummaryMeta)


class RaceResult(BaseModel):
    race_id: str
    race_name: str | None = None
    results: list[ResultEntry] = Field(default_factory=list)
    payouts: list[PayoutEntry] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False
    meta: CachePolicyMeta | None = None


class NormalizedRaceInput(BaseModel):
    course: CourseCode
    race_no: int
    bet_type: BetType | None = None
    combination: list[str] = Field(default_factory=list)


class StoredRaceResultRecord(BaseModel):
    race_id: str
    date: date
    course: CourseCode
    race_no: int
    result: RaceResult


class StoredRaceResultPage(BaseModel):
    items: list[StoredRaceResultRecord] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class ResultCollectionJobRequest(BaseModel):
    from_date: date
    to_date: date
    courses: list[CourseCode] = Field(min_length=1)
    storage: ResultStorageKind | None = None
    output: str | None = None
    retries: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_date_range(self) -> "ResultCollectionJobRequest":
        if self.from_date > self.to_date:
            raise ValueError("from_date must be before or equal to to_date")
        return self


class ResultCollectionJobCreated(BaseModel):
    job_id: str
    status: ResultCollectionJobStatus


class ResultCollectionJobSummary(BaseModel):
    job_id: str
    status: ResultCollectionJobStatus
    from_date: date
    to_date: date
    courses: list[CourseCode]
    storage: ResultStorageKind
    output: str
    retries: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str | None = None
    error: str | None = None


class ResultCollectionJobPage(BaseModel):
    items: list[ResultCollectionJobSummary] = Field(default_factory=list)
    total: int


class RaceSearchItem(BaseModel):
    race_id: str
    date: date
    course: CourseCode | None = None
    race_no: int | None = None
    race_name: str
    start_time: str | None = None


class RaceSearchPage(BaseModel):
    items: list[RaceSearchItem] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class ApiError(BaseModel):
    code: str
    message: str
    request_id: str


class ApiErrorResponse(BaseModel):
    error: ApiError


class BetRecordTicketRequest(BaseModel):
    prediction_ticket_id: str | None = None
    bucket: str | None = None
    bet_type: BetType
    mode: str = "normal"
    selection: list[str] = Field(default_factory=list)
    amount: int | None = Field(default=None, ge=1)
    amount_per_ticket: int | None = Field(default=None, ge=1)
    odds_at_buy: float | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_ticket(self) -> "BetRecordTicketRequest":
        if self.mode not in {"normal", "box"}:
            raise ValueError("mode must be normal or box")
        if not self.selection:
            raise ValueError("selection must not be empty")
        if self.mode == "normal" and self.amount is None:
            raise ValueError("amount is required for normal mode")
        if self.mode == "box" and self.amount_per_ticket is None:
            raise ValueError("amount_per_ticket is required for box mode")
        return self


BET_RECORD_RACE_ID_PATTERN = r"^(\d{12}|\d{16})$"


class BetRecordCreateRequest(BaseModel):
    race_id: str = Field(pattern=BET_RECORD_RACE_ID_PATTERN)
    prediction_id: str | None = None
    theory_version: str | None = None
    decision_source: DecisionSource
    purchased_at: datetime | None = None
    total_amount: int = Field(ge=1)
    note: str | None = None
    tickets: list[BetRecordTicketRequest] = Field(min_length=1)


class BetRecordTicket(BaseModel):
    bet_ticket_id: str
    bet_record_id: str
    race_id: str
    prediction_ticket_id: str | None = None
    bucket: str | None = None
    bet_type: str
    selection: str
    selection_json: list[str] = Field(default_factory=list)
    amount: int
    odds_at_buy: float | None = None
    is_box_expanded: bool
    reason: str | None = None
    created_at: datetime


class BetRecordResultTicket(BaseModel):
    bet_type: str
    selection: str
    selection_json: list[str] = Field(default_factory=list)
    amount: int
    hit: bool
    payout: int


class BetRecordResult(BaseModel):
    bet_record_result_id: str
    bet_record_id: str
    race_id: str
    total_bet: int
    total_payout: int
    return_rate: float
    hit: bool
    settled_at: datetime
    result_json: dict
    created_at: datetime


class BetRecordSettlement(BaseModel):
    bet_record_id: str
    race_id: str
    total_bet: int
    total_payout: int
    return_rate: float
    hit: bool
    settled_at: datetime
    ticket_results: list[BetRecordResultTicket] = Field(default_factory=list)


class BetRecord(BaseModel):
    bet_record_id: str
    race_id: str
    prediction_id: str | None = None
    theory_version: str | None = None
    decision_source: DecisionSource
    purchased_at: datetime | None = None
    total_amount: int
    note: str | None = None
    created_at: datetime
    updated_at: datetime
    tickets: list[BetRecordTicket] = Field(default_factory=list)
    prediction: dict | None = None
    prediction_tickets: list[dict] = Field(default_factory=list)
    result: BetRecordResult | None = None


class BetRecordPage(BaseModel):
    items: list[BetRecord] = Field(default_factory=list)
    total: int
    limit: int
    offset: int
