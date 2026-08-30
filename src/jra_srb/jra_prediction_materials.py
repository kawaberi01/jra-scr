from __future__ import annotations

from datetime import date, datetime, UTC
import re
import unicodedata

from .models import (
    JraLiteMaterial,
    JraLiteRunnerMaterial,
    JraMaterialStatus,
    JraPublicAnalysis,
    JraPublicRunnerAnalysis,
    JraRecentRace,
    JraSourceKeys,
    RaceCard,
)


COURSE_CODES = {
    "sapporo": "01",
    "hakodate": "02",
    "fukushima": "03",
    "niigata": "04",
    "tokyo": "05",
    "nakayama": "06",
    "chukyo": "07",
    "kyoto": "08",
    "hanshin": "09",
    "kokura": "10",
}


def build_source_keys(target_date: date, course: str, race_no: int, meeting_no: int, meeting_day: int) -> JraSourceKeys:
    if course not in COURSE_CODES:
        raise ValueError(f"unsupported JRA course={course}")
    if not 1 <= race_no <= 12:
        raise ValueError("race_no must be between 1 and 12")
    if not 1 <= meeting_no <= 99 or not 1 <= meeting_day <= 99:
        raise ValueError("meeting_no and meeting_day must be between 1 and 99")
    course_code = COURSE_CODES[course]
    ymd = target_date.strftime("%Y%m%d")
    return JraSourceKeys(
        jra_internal_race_id=f"{ymd}{course_code}{race_no:02d}",
        netkeiba_race_id=f"{target_date.year:04d}{course_code}{meeting_no:02d}{meeting_day:02d}{race_no:02d}",
        keibalab_race_code=f"{ymd}{course_code}{race_no:02d}",
        umanity_race_code=f"{ymd}{course_code}{meeting_no:02d}{meeting_day:02d}{race_no:02d}",
    )


def build_best_time_lite(card: RaceCard, public: JraPublicAnalysis) -> JraLiteMaterial:
    target_distance = _int(card.distance)
    runners = []
    ranked: list[tuple[float, JraLiteRunnerMaterial]] = []
    public_by_horse = _public_runner_index(public, card)
    for card_runner in card.runners:
        source_runner = _match_runner(card_runner.horse_no, card_runner.horse_name, public_by_horse)
        candidates = _same_surface(source_runner, card.surface)
        candidates = [race for race in candidates if _time_seconds(race.finish_time) is not None]
        selected = _select_condition_race(candidates, card.course, target_distance, key=lambda race: _time_seconds(race.finish_time))
        item = JraLiteRunnerMaterial(
            horse_no=card_runner.horse_no or "",
            horse_name=card_runner.horse_name,
            status=JraMaterialStatus.available if selected else JraMaterialStatus.unavailable,
            value=selected.finish_time if selected else None,
            sample_size=len(candidates),
            source_race=selected,
            details={
                "same_course": bool(selected and _normalize(selected.source_course) == _normalize(card.course)),
                "same_distance": bool(selected and selected.distance == target_distance),
            },
            reason=None if selected else "visible_recent_racesに有効な走破時計なし",
        )
        runners.append(item)
        if selected and (seconds := _time_seconds(selected.finish_time)) is not None:
            ranked.append((seconds, item))
    _assign_ranks(ranked)
    return _material(card.race_id, "best_time_lite", runners, public)


def build_closing_speed_lite(card: RaceCard, public: JraPublicAnalysis) -> JraLiteMaterial:
    target_distance = _int(card.distance)
    runners = []
    ranked: list[tuple[float, JraLiteRunnerMaterial]] = []
    public_by_horse = _public_runner_index(public, card)
    for card_runner in card.runners:
        source_runner = _match_runner(card_runner.horse_no, card_runner.horse_name, public_by_horse)
        candidates = [race for race in _same_surface(source_runner, card.surface) if race.final_3f is not None]
        selected = _select_condition_race(candidates, card.course, target_distance, key=lambda race: race.final_3f)
        item = JraLiteRunnerMaterial(
            horse_no=card_runner.horse_no or "",
            horse_name=card_runner.horse_name,
            status=JraMaterialStatus.available if selected else JraMaterialStatus.unavailable,
            value=selected.final_3f if selected else None,
            sample_size=len(candidates),
            source_race=selected,
            details={"same_distance": bool(selected and selected.distance == target_distance)},
            reason=None if selected else "visible_recent_racesに上がり時計なし",
        )
        runners.append(item)
        if selected and selected.final_3f is not None:
            ranked.append((selected.final_3f, item))
    _assign_ranks(ranked)
    return _material(card.race_id, "closing_speed_lite", runners, public)


def build_style_profile_lite(card: RaceCard, public: JraPublicAnalysis) -> JraLiteMaterial:
    runners = []
    public_by_horse = _public_runner_index(public, card)
    for card_runner in card.runners:
        source_runner = _match_runner(card_runner.horse_no, card_runner.horse_name, public_by_horse)
        counts = {"front": 0, "stalker": 0, "midpack": 0, "closer": 0}
        valid = []
        for race in (source_runner.recent_races if source_runner else [])[:5]:
            if not race.corner_positions or not race.field_size:
                continue
            ratio = race.corner_positions[-1] / race.field_size
            key = "front" if ratio <= 0.25 else "stalker" if ratio <= 0.45 else "midpack" if ratio <= 0.70 else "closer"
            counts[key] += 1
            valid.append(race)
        scores = {key: round(value / len(valid), 4) if valid else 0.0 for key, value in counts.items()}
        max_score = max(scores.values(), default=0.0)
        leaders = [key for key, value in scores.items() if value == max_score and value > 0]
        expected = leaders[0] if len(leaders) == 1 else None
        runners.append(
            JraLiteRunnerMaterial(
                horse_no=card_runner.horse_no or "",
                horse_name=card_runner.horse_name,
                status=JraMaterialStatus.available if valid else JraMaterialStatus.unavailable,
                value=expected,
                sample_size=len(valid),
                source_race=valid[0] if valid else None,
                details={"style_scores": scores, "ambiguous": len(leaders) > 1},
                reason=None if valid else "visible_recent_racesに通過順または頭数なし",
            )
        )
    return _material(card.race_id, "style_profile_lite", runners, public)


def normalize_horse_name(value: str) -> str:
    return re.sub(r"[\s　]+", "", unicodedata.normalize("NFKC", value)).casefold()


def _material(race_id: str, kind: str, runners: list[JraLiteRunnerMaterial], public: JraPublicAnalysis) -> JraLiteMaterial:
    available = sum(item.status == JraMaterialStatus.available for item in runners)
    status = JraMaterialStatus.available if available == len(runners) and runners else JraMaterialStatus.partial if available else JraMaterialStatus.unavailable
    return JraLiteMaterial(
        race_id=race_id,
        kind=kind,
        status=status,
        runners=runners,
        fetched_at=datetime.now(UTC),
        source="jra_official_card+public_race_pages",
        cache_hit=public.cache_hit,
    )


def _public_runner_index(public: JraPublicAnalysis, card: RaceCard) -> dict[str, JraPublicRunnerAnalysis]:
    result: dict[str, JraPublicRunnerAnalysis] = {}
    for source in public.sources.values():
        for runner in source.runners:
            result.setdefault(f"no:{runner.horse_no}", runner)
            result.setdefault(f"name:{normalize_horse_name(runner.horse_name)}", runner)
    for card_runner in card.runners:
        if not card_runner.official_recent_races:
            continue
        existing = _match_runner(card_runner.horse_no, card_runner.horse_name, result)
        recent_races = list(card_runner.official_recent_races)
        seen = {_recent_race_key(race) for race in recent_races}
        if existing is not None:
            recent_races.extend(
                race for race in existing.recent_races
                if _recent_race_key(race) not in seen
            )
        merged = JraPublicRunnerAnalysis(
            horse_no=card_runner.horse_no or (existing.horse_no if existing else ""),
            horse_name=card_runner.horse_name,
            omega_index=existing.omega_index if existing else None,
            recent_races=recent_races[:5],
        )
        if card_runner.horse_no:
            result[f"no:{card_runner.horse_no}"] = merged
        result[f"name:{normalize_horse_name(card_runner.horse_name)}"] = merged
    return result


def _recent_race_key(race: JraRecentRace) -> tuple[object, ...]:
    return (race.source_date, _normalize(race.source_course), race.source_race_no, race.surface, race.distance)


def _match_runner(horse_no: str | None, horse_name: str, index: dict[str, JraPublicRunnerAnalysis]) -> JraPublicRunnerAnalysis | None:
    if horse_no and (runner := index.get(f"no:{horse_no}")):
        return runner
    return index.get(f"name:{normalize_horse_name(horse_name)}")


def _same_surface(runner: JraPublicRunnerAnalysis | None, surface: str | None) -> list[JraRecentRace]:
    if runner is None:
        return []
    normalized = _normalize_surface(surface)
    return [race for race in runner.recent_races[:5] if _normalize_surface(race.surface) == normalized]


def _select_condition_race(candidates, course: str | None, distance: int | None, key):
    if not candidates:
        return None
    def priority(race):
        same_course = _normalize(race.source_course) == _normalize(course)
        same_distance = race.distance == distance
        distance_gap = abs((race.distance or 99999) - (distance or 99999))
        return (0 if same_course and same_distance else 1 if same_distance else 2, distance_gap, key(race) or 99999)
    return min(candidates, key=priority)


def _assign_ranks(ranked: list[tuple[float, JraLiteRunnerMaterial]]) -> None:
    for rank, (_, item) in enumerate(sorted(ranked, key=lambda pair: pair[0]), start=1):
        item.rank = rank


def _time_seconds(value: str | None) -> float | None:
    if not value:
        return None
    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2})\.(\d)", value.strip())
    if not match:
        return None
    minutes = int(match.group(1) or 0)
    return minutes * 60 + int(match.group(2)) + int(match.group(3)) / 10


def _int(value: str | int | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+", str(value).replace(",", ""))
    return int(match.group()) if match else None


def _normalize(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").replace("競馬場", "").strip().casefold()


def _normalize_surface(value: str | None) -> str:
    normalized = _normalize(value)
    return "turf" if normalized in {"芝", "turf"} else "dirt" if normalized in {"ダ", "ダート", "dirt"} else normalized
