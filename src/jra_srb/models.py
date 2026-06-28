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
