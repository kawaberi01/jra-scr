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
    start_time: str | None = None
    runners: list[Runner] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False


class MeetingRace(BaseModel):
    race_no: int
    race_id: str
    race_name: str | None = None
    start_time: str | None = None
    card_cname: str | None = None
    odds_cname: str | None = None
    result_cname: str | None = None


class MeetingSnapshot(BaseModel):
    date: date
    course: str
    races: list[MeetingRace] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False


class RaceOdds(BaseModel):
    race_id: str
    bet_type: str | None = None
    entries: list[OddsEntry] = Field(default_factory=list)
    odds: dict[str, list[OddsEntry]] = Field(default_factory=dict)
    fetched_at: datetime
    source: str
    cache_hit: bool = False


class RaceResult(BaseModel):
    race_id: str
    race_name: str | None = None
    results: list[ResultEntry] = Field(default_factory=list)
    payouts: list[PayoutEntry] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False


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


class BetRecordCreateRequest(BaseModel):
    race_id: str = Field(pattern=r"^\d{12}$")
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
