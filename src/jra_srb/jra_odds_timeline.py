"""概要: 開催一覧から発走前の出馬表・券種別オッズを時点収集する。
作成日: 不明
入力: 開催日、開催場、券種、取得時点、収集上限、JRAサービス。
出力: 選択backendの分析DB、標準出力の収集記録、収集件数の集計。
実行例: uv run jra-srb collect-jra-odds-timeline --date 2026-10-12 --dry-run
注意事項: 本収集はJRAへ通信しDBへ追記する。取得済み時点は原則スキップする。
"""

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
    """収集結果と予定に対する上限・未処理オッズ件数を保持する。"""

    scheduled: int
    saved: int
    skipped_existing: int
    skipped_late: int
    failed: int
    live_requests: int
    planned_requests: int = 0
    request_limit: int = 0
    limit_reached: bool = False
    unprocessed_odds: int = 0


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
    """開催曜日によらず、発走時刻を基準に出馬表とオッズを保存する。"""

    def __init__(self, service: JraService, store: AnalysisSQLiteStore) -> None:
        self.service = service
        self.store = store

    async def collect(
        self,
        target_date: date,
        courses: set[str],
        offsets: list[int],
        bet_types: list[str],
        bet_type_offsets: dict[str, list[int]] | None = None,
        poll_seconds: float = 20.0,
        min_interval_seconds: float = 1.0,
        max_lateness_seconds: float = 90.0,
        max_live_requests: int | None = None,
        dry_run: bool = False,
        refresh_existing: bool = False,
    ) -> OddsTimelineSummary:
        """開催日の指定時点を収集し、非開催日は正常終了する。

        Args:
            target_date: 収集する日本時間の開催日。
            courses: 対象開催場。空集合なら全場。
            offsets: 発走何分前に取得するかの既定値。
            bet_types: 保存対象の券種。
            bet_type_offsets: 券種ごとの取得時点。省略時はoffsetsを使う。
            poll_seconds: 次の取得時点を待つ間の確認間隔（秒）。
            min_interval_seconds: ライブ取得間隔の下限（秒）。
            max_lateness_seconds: 予定時点から許容する遅延（秒）。
            max_live_requests: 出馬表とオッズの取得試行上限。省略時は当日の予定から算出する。
            dry_run: 予定のみを出力し、出馬表・オッズは取得保存しない。
            refresh_existing: 保存済み時点も新しい世代として追記する。

        Returns:
            予定・保存・スキップ・失敗・取得試行数と上限による未処理件数。

        Raises:
            ValueError: 上限が負、または対象開催の有効な発走時刻が一件もない場合。

        Notes:
            開催取得例外は呼び出し元へ伝える。個別収集の失敗は集計する。
            本収集は選択backendへ追記し、未来の取得時点まで待機する。
        """
        if max_live_requests is not None and max_live_requests < 0:
            raise ValueError("--max-live-requests must be non-negative")
        meetings = await self.service.get_meetings_for_date(target_date)
        if not meetings:
            print(f"no_meetings date={target_date.isoformat()}", flush=True)
            return OddsTimelineSummary(0, 0, 0, 0, 0, 0)
        effective_bet_type_offsets = bet_type_offsets or {
            bet_type: offsets for bet_type in bet_types
        }
        task_offsets = sorted(
            {offset for configured_offsets in effective_bet_type_offsets.values() for offset in configured_offsets},
            reverse=True,
        )
        tasks = build_timeline_tasks(target_date, meetings, courses, task_offsets)
        selected_meetings = [meeting for meeting in meetings if not courses or str(meeting.course) in courses]
        if selected_meetings and not tasks:
            raise ValueError(f"meetings exist but no valid start times: {target_date.isoformat()}")
        task_bet_types = [
            [bet_type for bet_type in bet_types
             if task.offset_minutes in effective_bet_type_offsets.get(bet_type, [])]
            for task in tasks
        ]
        planned_odds = sum(len(types) for types in task_bet_types)
        planned_requests = planned_odds + sum(bool(types) for types in task_bet_types)
        request_limit = planned_requests if max_live_requests is None else max_live_requests
        print(
            f"collection_plan planned_odds={planned_odds} planned_requests={planned_requests} "
            f"request_limit={request_limit}",
            flush=True,
        )
        if dry_run:
            for task in tasks:
                print(
                    f"{task.target_at.isoformat()} {task.course} "
                    f"{task.race.race_no}R {task.timing_label}",
                    flush=True,
                )
            return OddsTimelineSummary(
                len(tasks), 0, 0, 0, 0, 0,
                planned_requests=planned_requests, request_limit=request_limit,
            )

        saved = skipped_existing = skipped_late = failed = live_requests = 0
        failed_odds = 0

        def stopped_at_limit() -> OddsTimelineSummary:
            """上限による打切りと、既存確認も含め未処理の予定件数を返す。"""
            unprocessed = planned_odds - saved - skipped_existing - skipped_late - failed_odds
            print(
                f"stopped reason=request_limit_reached live_requests={live_requests} "
                f"request_limit={request_limit} unprocessed_odds={unprocessed}",
                flush=True,
            )
            return OddsTimelineSummary(
                len(tasks), saved, skipped_existing, skipped_late, failed, live_requests,
                planned_requests, request_limit, True, unprocessed,
            )

        last_request_at: float | None = None
        for task, configured_bet_types in zip(tasks, task_bet_types, strict=True):
            now = datetime.now(JST)
            if task.target_at > now:
                await asyncio.sleep(min(max(0.0, (task.target_at - now).total_seconds()), poll_seconds))
                while task.target_at > datetime.now(JST):
                    remaining = max(0.0, (task.target_at - datetime.now(JST)).total_seconds())
                    await asyncio.sleep(min(remaining, poll_seconds))
            lateness = (datetime.now(JST) - task.target_at).total_seconds()
            if lateness > max_lateness_seconds:
                skipped_late += len(configured_bet_types)
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
            for bet_type in configured_bet_types:
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

            if live_requests >= request_limit:
                return stopped_at_limit()
            if last_request_at is not None:
                remaining = last_request_at + min_interval_seconds - monotonic()
                if remaining > 0:
                    await asyncio.sleep(remaining)
            try:
                last_request_at = monotonic()
                live_requests += 1
                card = await self.service.get_race_card_by_number(
                    target_date,
                    task.course,
                    task.race.race_no,
                    refresh=True,
                )
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
                if live_requests >= request_limit:
                    return stopped_at_limit()
                if last_request_at is not None:
                    remaining = last_request_at + min_interval_seconds - monotonic()
                    if remaining > 0:
                        await asyncio.sleep(remaining)
                try:
                    last_request_at = monotonic()
                    live_requests += 1
                    odds = await self.service.get_race_odds_by_number(
                        target_date,
                        task.course,
                        task.race.race_no,
                        bet_type,
                        refresh=True,
                    )
                    self.store.write_odds(odds, bet_type=bet_type, odds_timing=task.timing_label)
                    saved += 1
                except Exception as exc:  # noqa: BLE001
                    failed += 1
                    failed_odds += 1
                    print(
                        f"failed {task.course} {task.race.race_no}R "
                        f"{task.timing_label} {bet_type}: {type(exc).__name__}: {exc}",
                        flush=True,
                    )
        return OddsTimelineSummary(
            len(tasks), saved, skipped_existing, skipped_late, failed, live_requests,
            planned_requests=planned_requests, request_limit=request_limit,
        )
