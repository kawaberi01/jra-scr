from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from time import monotonic

from .analysis_store import AnalysisSQLiteStore
from .models import MeetingRace, MeetingSnapshot
from .service import JraService


JST = timezone(timedelta(hours=9), name="JST")


@dataclass(frozen=True)
class OddsTimelineTask:
    target_at: datetime
    course: str
    race: MeetingRace
    offset_minutes: int

    @property
    def timing_label(self) -> str:
        return f"t_minus_{self.offset_minutes}m"


@dataclass(frozen=True)
class OddsTimelineSummary:
    scheduled: int
    saved: int
    skipped_existing: int
    skipped_late: int
    failed: int
    live_requests: int


def parse_start_datetime(target_date: date, value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("時", ":").replace("分", "").strip()
    try:
        hour_text, minute_text = normalized.split(":", 1)
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            int(hour_text),
            int(minute_text[:2]),
            tzinfo=JST,
        )
    except (TypeError, ValueError):
        return None


def build_timeline_tasks(
    target_date: date,
    meetings: list[MeetingSnapshot],
    courses: set[str],
    offsets: list[int],
) -> list[OddsTimelineTask]:
    tasks: list[OddsTimelineTask] = []
    for meeting in meetings:
        course = str(meeting.course)
        if courses and course not in courses:
            continue
        for race in meeting.races:
            start_at = parse_start_datetime(target_date, race.start_time)
            if start_at is None:
                continue
            for offset in offsets:
                tasks.append(
                    OddsTimelineTask(
                        target_at=start_at - timedelta(minutes=offset),
                        course=course,
                        race=race,
                        offset_minutes=offset,
                    )
                )
    return sorted(tasks, key=lambda task: (task.target_at, task.course, task.race.race_no))


class JraOddsTimelineCollector:
    def __init__(self, service: JraService, store: AnalysisSQLiteStore) -> None:
        self.service = service
        self.store = store

    async def collect(
        self,
        target_date: date,
        courses: set[str],
        offsets: list[int],
        bet_types: list[str],
        poll_seconds: float = 20.0,
        min_interval_seconds: float = 1.0,
        max_lateness_seconds: float = 90.0,
        max_live_requests: int | None = None,
        dry_run: bool = False,
        refresh_existing: bool = False,
    ) -> OddsTimelineSummary:
        meetings = await self.service.get_meetings_for_date(target_date)
        tasks = build_timeline_tasks(target_date, meetings, courses, offsets)
        if dry_run:
            for task in tasks:
                print(
                    f"{task.target_at.isoformat()} {task.course} "
                    f"{task.race.race_no}R {task.timing_label}",
                    flush=True,
                )
            return OddsTimelineSummary(len(tasks), 0, 0, 0, 0, 0)

        saved = skipped_existing = skipped_late = failed = live_requests = 0
        last_request_at: float | None = None
        for task in tasks:
            now = datetime.now(JST)
            if task.target_at > now:
                await asyncio.sleep(min(max(0.0, (task.target_at - now).total_seconds()), poll_seconds))
                while task.target_at > datetime.now(JST):
                    remaining = max(0.0, (task.target_at - datetime.now(JST)).total_seconds())
                    await asyncio.sleep(min(remaining, poll_seconds))
            lateness = (datetime.now(JST) - task.target_at).total_seconds()
            if lateness > max_lateness_seconds:
                skipped_late += len(bet_types)
                continue

            meeting = next((item for item in meetings if str(item.course) == task.course), None)
            if meeting is not None:
                self.store.write_race(
                    target_date,
                    task.course,
                    task.race,
                    source=meeting.source,
                    fetched_at=meeting.fetched_at,
                )
            pending_bet_types = []
            for bet_type in bet_types:
                if (
                    not refresh_existing
                    and self.store.has_odds_snapshot(
                        task.race.race_id,
                        bet_type,
                        task.timing_label,
                    )
                ):
                    skipped_existing += 1
                    continue
                pending_bet_types.append(bet_type)
            if not pending_bet_types:
                continue

            if max_live_requests is not None and live_requests >= max_live_requests:
                return OddsTimelineSummary(
                    len(tasks), saved, skipped_existing, skipped_late, failed, live_requests
                )
            if last_request_at is not None:
                remaining = last_request_at + min_interval_seconds - monotonic()
                if remaining > 0:
                    await asyncio.sleep(remaining)
            try:
                last_request_at = monotonic()
                card = await self.service.get_race_card_by_number(
                    target_date,
                    task.course,
                    task.race.race_no,
                    refresh=True,
                )
                live_requests += 1
                self.store.write_card(
                    target_date,
                    task.course,
                    task.race.race_no,
                    card,
                )
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(
                    f"failed card {task.course} {task.race.race_no}R "
                    f"{task.timing_label}: {type(exc).__name__}: {exc}",
                    flush=True,
                )

            for bet_type in pending_bet_types:
                if max_live_requests is not None and live_requests >= max_live_requests:
                    return OddsTimelineSummary(
                        len(tasks), saved, skipped_existing, skipped_late, failed, live_requests
                    )
                if last_request_at is not None:
                    remaining = last_request_at + min_interval_seconds - monotonic()
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                try:
                    last_request_at = monotonic()
                    odds = await self.service.get_race_odds_by_number(
                        target_date,
                        task.course,
                        task.race.race_no,
                        bet_type,
                        refresh=True,
                    )
                    live_requests += 1
                    self.store.write_odds(odds, bet_type=bet_type, odds_timing=task.timing_label)
                    saved += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    print(
                        f"failed {task.course} {task.race.race_no}R "
                        f"{task.timing_label} {bet_type}: {type(exc).__name__}: {exc}",
                        flush=True,
                    )
        return OddsTimelineSummary(
            len(tasks), saved, skipped_existing, skipped_late, failed, live_requests
        )
