from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


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
