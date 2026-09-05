from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import re

from .jra_history_dataset import COURSE_CODES


_COURSE_CODE = {value: key for key, value in COURSE_CODES.items()}
_MAIN_COURSES = {"tokyo", "nakayama", "kyoto", "hanshin"}
_AUTUMN_SHADOW_COURSES = {"tokyo", "nakayama"}
_SUMMER_COURSES = {"sapporo", "hakodate", "fukushima", "niigata", "kokura"}


def build_v_theory_prediction(
    db_path: str | Path,
    *,
    target_date: date,
    course: str,
    card,
    win_odds: dict[str, float],
    race_odds=None,
) -> dict:
    """Run the frozen venue-routed V theory as a shadow prediction.

    The V branch is not an adopted betting theory. It is intentionally returned
    separately from the two live models so its future snapshots can be evaluated.
    """
    route = _route(course)
    if route["status"] == "unavailable":
        return route
    category = _race_category(card)
    if course in _AUTUMN_SHADOW_COURSES and category != "flat_general":
        return {
            **route,
            "status": "excluded",
            "reason": f"separate_race_category:{category}",
            "ranking": [],
            "head_candidates": [],
            "axis_candidates": [],
            "partner_candidates": [],
            "ticket_candidates": [],
            "ticket_status": "excluded",
        }
    history = _load_history(db_path, target_date)
    if not history["rows"]:
        return {**route, "status": "unavailable", "reason": "no_prior_official_history"}
    field_size = len(card.runners)
    market_as_of_valid = _market_is_pre_race(race_odds, target_date, card)
    candidates = []
    for runner in card.runners:
        horse_no = str(runner.horse_no or "")
        features = _features(history, runner, course, card, field_size)
        if features["starts"] < 2:
            continue
        odds = (win_odds.get(horse_no) or _float(getattr(runner, "odds", None))) if market_as_of_valid else None
        popularity = _integer(getattr(runner, "popularity", None)) if market_as_of_valid else None
        weight_diff = _integer(getattr(runner, "horse_weight_diff", None))
        base_score = _base_score(features)
        candidates.append({
            "horse_no": horse_no,
            "horse_name": runner.horse_name,
            "win_odds": odds,
            "popularity": popularity,
            "horse_weight_diff": weight_diff,
            "features": features,
            "base_score": round(base_score, 3),
            "axis_score": round(base_score + _axis_adjustment(features), 3),
            "middle_score": round(base_score + _middle_adjustment(features, odds), 3),
        })
    if len(candidates) < 6:
        return {**route, "status": "unavailable", "reason": f"few_history_candidates:{len(candidates)}", "ranking": []}

    axis_ranked = sorted(candidates, key=lambda item: (-item["axis_score"], _horse_no(item["horse_no"])))
    axis = next((item for item in axis_ranked if _axis_eligible(item)), axis_ranked[0])
    race_no = _integer(str(card.race_id)[-2:]) or 0
    middles = _select_middles(candidates, axis, field_size, race_no)
    eligible_middles = [item for item in middles if _ticket_allowed(axis, item)]
    wide_market = _wide_market(race_odds) if market_as_of_valid else {}
    ticket_candidates = []
    for item in eligible_middles:
        combination = tuple(sorted((axis["horse_no"], item["horse_no"]), key=_horse_no))
        market = wide_market.get(combination)
        if market is None:
            continue
        ticket_candidates.append(
            {
                "bet_type": "wide",
                "selection": "-".join(combination),
                "selection_json": list(combination),
                "odds": market["odds"],
                "odds_min": market["odds_min"],
                "odds_max": market["odds_max"],
                "odds_as_of": market["fetched_at"],
                "reason": "v89条件を通過し、発走前に実取得したワイドオッズあり",
            }
        )
    ranking = sorted(candidates, key=lambda item: (-item["base_score"], _horse_no(item["horse_no"])))
    for index, item in enumerate(ranking, start=1):
        item["rank"] = index
        item["reasons"] = _reasons(item)
        item.pop("features")

    return {
        **route,
        "history_as_of": f"{target_date.isoformat()}T00:00:00",
        "market_as_of_valid": market_as_of_valid,
        "race_category": category,
        "ranking": ranking,
        "axis": axis["horse_no"],
        "middle_horse_numbers": [item["horse_no"] for item in middles],
        "head_candidates": ranking[:3],
        "axis_candidates": [_candidate_view(axis)],
        "partner_candidates": [_candidate_view(item) for item in eligible_middles],
        "ticket_candidates": ticket_candidates,
        "ticket_status": "shadow_only" if ticket_candidates else (
            "no_candidate_actual_wide_odds_unavailable" if eligible_middles else "no_candidate"
        ),
        "ticket_policy_version": "v89-autumn-shadow-wide-asof-v1",
        "limitations": [
            "2026年秋の未使用holdoutが30買い目未満のため正式採用ではない",
            "過去検証には発走前odds snapshotがなく、ROIは昇格根拠に再利用しない",
            "確率・校正済み期待値・利益保証ではない",
        ],
    }


def build_v_theory_prediction_record(db_path: str | Path, bundle, amount_per_ticket: int = 100) -> dict | None:
    """Build a persistable pre-race shadow record from an already fetched bundle."""
    prediction = build_v_theory_prediction(
        db_path,
        target_date=bundle.date,
        course=bundle.course,
        card=bundle.card,
        win_odds=_win_market(bundle.odds_summary),
        race_odds=bundle.odds_summary,
    )
    if prediction.get("status") != "available" or not prediction.get("ranking"):
        return None
    created_at = datetime.now(UTC).isoformat()
    tickets = [
        {
            "ticket_id": f"v89-shadow-{bundle.race_id}-wide-{index}",
            "bucket": "shadow",
            "bet_type": item["bet_type"],
            "selection": item["selection"],
            "selection_json": item["selection_json"],
            "amount": amount_per_ticket,
            "reason": f"{item['reason']} odds={item['odds_min'] or item['odds']}-{item['odds_max'] or item['odds']}",
        }
        for index, item in enumerate(prediction["ticket_candidates"], 1)
    ]
    return {
        "prediction_id": f"v89-shadow-{bundle.race_id}-{created_at.replace(':', '').replace('+', '-')}",
        "race_id": bundle.race_id,
        "theory_version": "v89_autumn_2026_shadow",
        "mode": "paper_validation",
        "budget": len(tickets) * amount_per_ticket,
        "created_at": created_at,
        "race_context": {
            "race_id": bundle.race_id,
            "race_date": bundle.date.isoformat(),
            "course": bundle.course,
            "race_no": bundle.race_no,
            "race_name": bundle.card.race_name,
        },
        "pre_race_snapshot": bundle.model_dump(mode="json"),
        "prediction_json": {
            **prediction,
            "generated_before_result": True,
            "promotion_target_tickets": 30,
        },
        "prediction_tickets": tickets,
    }


def build_three_way_consensus(materials: list[dict], history: list[dict], v_theory: dict) -> dict:
    """Return an explainable rank-consensus, not a merged probability model."""
    sources = {
        "materials": materials,
        "history": history,
        "v_theory": v_theory.get("ranking", []) if v_theory.get("status") == "available" else [],
    }
    entries: dict[str, dict] = {}
    for source, rows in sources.items():
        for rank, row in enumerate(rows, start=1):
            horse_no = str(row.get("horse_no") or "")
            if not horse_no:
                continue
            entry = entries.setdefault(horse_no, {"horse_no": horse_no, "horse_name": row.get("horse_name"), "source_ranks": {}})
            entry["source_ranks"][source] = rank
    ranking = []
    for entry in entries.values():
        # 1st/2nd/3rd receive 3/2/1; lower ranks are recorded but add no vote.
        score = sum(max(0, 4 - rank) for rank in entry["source_ranks"].values())
        entry["consensus_score"] = score
        entry["agreement_count"] = sum(rank <= 3 for rank in entry["source_ranks"].values())
        ranking.append(entry)
    ranking.sort(key=lambda item: (-item["consensus_score"], -item["agreement_count"], _horse_no(item["horse_no"])))
    return {
        "kind": "transparent_rank_consensus_v1",
        "status": "reference_only" if v_theory.get("status") != "available" else "three_way_reference",
        "note": "順位票の集計であり、確率の合算や購入推奨ではない",
        "ranking": ranking,
    }


def _route(course: str) -> dict:
    if course in _AUTUMN_SHADOW_COURSES:
        return {
            "status": "available",
            "theory_version": "v89",
            "application": "autumn_2026_shadow",
            "model_status": "shadow",
            "betting_status": "shadow_only",
        }
    if course in _MAIN_COURSES:
        return {"status": "available", "theory_version": "v89", "application": "main_venue_candidate", "betting_status": "not_final"}
    if course in _SUMMER_COURSES:
        return {"status": "available", "theory_version": "v90", "application": "summer_shadow", "betting_status": "rejected_for_purchase"}
    if course == "chukyo":
        return {"status": "unavailable", "theory_version": None, "reason": "chukyo_v_branch_rejected"}
    return {"status": "unavailable", "theory_version": None, "reason": f"unsupported_course:{course}"}


def _load_history(db_path: str | Path, target_date: date) -> dict:
    path = Path(db_path).resolve()
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select r.race_id, r.race_date, r.surface, r.distance, ru.horse_name, ru.jockey, ru.trainer, re.rank
            from races r join runners ru on ru.race_id = r.race_id
            join result_entries re on re.race_id = r.race_id and re.horse_no = ru.horse_no
            where r.source like 'https://www.jra.go.jp/%' and r.race_date < ?
              and exists (select 1 from payouts p where p.race_id = r.race_id)
            order by r.race_date, r.race_id
            """,
            (target_date.isoformat(),),
        ).fetchall()
    finally:
        conn.close()
    valid = [dict(row) for row in rows if _integer(row["rank"]) is not None and row["horse_name"]]
    by_horse, by_jockey, by_trainer = defaultdict(list), defaultdict(list), defaultdict(list)
    for row in valid:
        by_horse[row["horse_name"]].append(row)
        if row["jockey"]:
            by_jockey[row["jockey"]].append(row)
        if row["trainer"]:
            by_trainer[row["trainer"]].append(row)
    return {"rows": valid, "horse": by_horse, "jockey": by_jockey, "trainer": by_trainer}


def _features(history: dict, runner, course: str, card, field_size: int) -> dict:
    past = history["horse"][runner.horse_name]
    surface = _surface(card.surface)
    distance = _integer(card.distance) or 0
    same_surface = [row for row in past if _surface(row["surface"]) == surface]
    same_course = [row for row in past if row["race_id"][8:10] == _COURSE_CODE[course]]
    same_distance = [row for row in past if abs((_integer(row["distance"]) or 0) - distance) <= 200]
    jockey = history["jockey"][runner.jockey][-20:] if runner.jockey else []
    trainer = history["trainer"][runner.trainer][-20:] if runner.trainer else []
    return {
        "starts": len(past), "top3_rate": _top3_rate(past), "recent_top3_rate": _top3_rate(past[-5:]),
        "recent_avg_rank": _average_rank(past[-5:]), "same_surface_top3_rate": _top3_rate_or_none(same_surface),
        "same_course_top3_rate": _top3_rate_or_none(same_course), "same_dist_top3_rate": _top3_rate_or_none(same_distance),
        "jockey_recent_top3_rate": _top3_rate_or_none(jockey), "trainer_recent_top3_rate": _top3_rate_or_none(trainer),
        "field_size": field_size,
    }


def _base_score(f: dict) -> float:
    return 45 * f["recent_top3_rate"] + 25 * f["top3_rate"] + 20 * (f["same_surface_top3_rate"] if f["same_surface_top3_rate"] is not None else f["top3_rate"]) + 20 * (f["same_dist_top3_rate"] if f["same_dist_top3_rate"] is not None else f["top3_rate"]) + min(f["starts"], 8) * 0.8 - f["recent_avg_rank"] * 1.8


def _axis_adjustment(f: dict) -> float:
    return (5 if _bucket(f["same_dist_top3_rate"]) == "ge_0_35" else -4 if _bucket(f["same_dist_top3_rate"]) == "lt_0_15" else 2 if _bucket(f["same_dist_top3_rate"]) == "0_25_0_35" else 0) + (3 if _bucket(f["jockey_recent_top3_rate"]) == "ge_0_35" else -2 if _bucket(f["jockey_recent_top3_rate"]) == "lt_0_15" else 0) + (2 if _bucket(f["trainer_recent_top3_rate"]) == "ge_0_35" else -2 if _bucket(f["trainer_recent_top3_rate"]) == "lt_0_15" else 0)


def _middle_adjustment(f: dict, odds: float | None) -> float:
    return (8 if _bucket(f["same_dist_top3_rate"]) == "lt_0_15" else -6 if _bucket(f["same_dist_top3_rate"]) == "ge_0_35" else 2 if _bucket(f["same_dist_top3_rate"]) == "missing" else 0) + (2 if f["field_size"] >= 14 else -6 if f["field_size"] <= 10 else 0) - (2 if f["field_size"] >= 14 and odds and odds > 10 else 0)


def _axis_eligible(item: dict) -> bool:
    return bool(item["win_odds"] and item["win_odds"] <= 10 and item["popularity"] and item["popularity"] <= 3)


def _select_middles(candidates: list[dict], axis: dict, field_size: int, race_no: int) -> list[dict]:
    if field_size < 14 or race_no > 8:
        return []
    selected = []
    for item in sorted((row for row in candidates if row is not axis), key=lambda row: (-row["middle_score"], _horse_no(row["horse_no"]))):
        if not item["win_odds"] or not 8 <= item["win_odds"] <= 20:
            continue
        if item["horse_weight_diff"] is not None and abs(item["horse_weight_diff"]) > 4:
            continue
        if selected and axis["base_score"] - item["base_score"] <= 5:
            continue
        selected.append(item)
        if len(selected) == 2:
            break
    return selected


def _ticket_allowed(axis: dict, middle: dict) -> bool:
    return bool(axis["popularity"] in {1, 2} and middle["popularity"] in {4, 5} and _axis_odds_bucket(axis["win_odds"]) in {"le_2_5", "2_5_4", "gt_6"} and _bucket(middle["features"]["jockey_recent_top3_rate"]) in {"lt_0_15", "0_25_0_35", "ge_0_35", "missing"})


def _race_category(card) -> str:
    name = str(getattr(card, "race_name", "") or "")
    surface = str(getattr(card, "surface", "") or "")
    if "障害" in name or "障" in surface:
        return "obstacle"
    if "新馬" in name or "メイクデビュー" in name:
        return "newcomer"
    return "flat_general"


def _candidate_view(item: dict) -> dict:
    return {
        "horse_no": item["horse_no"],
        "horse_name": item["horse_name"],
        "score": item["base_score"],
        "win_odds": item["win_odds"],
        "popularity": item["popularity"],
    }


def _win_market(race_odds) -> dict[str, float]:
    if race_odds is None:
        return {}
    entries = race_odds.odds.get("win", []) or (
        race_odds.entries if race_odds.bet_type == "win" else []
    )
    return {
        str(entry.combination[0]): value
        for entry in entries
        if entry.combination and (value := _float(entry.odds)) is not None
    }


def _wide_market(race_odds) -> dict[tuple[str, str], dict]:
    if race_odds is None:
        return {}
    entries = race_odds.odds.get("wide", []) or (
        race_odds.entries if race_odds.bet_type == "wide" else []
    )
    fetched_at = getattr(race_odds, "fetched_at", None)
    fetched_at_text = fetched_at.isoformat() if fetched_at is not None else None
    result = {}
    for entry in entries:
        if len(entry.combination) != 2:
            continue
        result[tuple(sorted((str(entry.combination[0]), str(entry.combination[1])), key=_horse_no))] = {
            "odds": _float(entry.odds),
            "odds_min": _float(entry.odds_min),
            "odds_max": _float(entry.odds_max),
            "fetched_at": fetched_at_text,
        }
    return result


def _market_is_pre_race(race_odds, target_date: date, card) -> bool:
    fetched_at = getattr(race_odds, "fetched_at", None) if race_odds is not None else None
    match = re.search(r"(\d{1,2})(?:時|:)(\d{2})(?:分)?", str(getattr(card, "start_time", "") or ""))
    if not isinstance(fetched_at, datetime) or match is None:
        return False
    japan_time = timezone(timedelta(hours=9))
    race_start = datetime.combine(target_date, datetime.min.time(), tzinfo=japan_time).replace(
        hour=int(match.group(1)), minute=int(match.group(2))
    )
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=japan_time)
    return fetched_at < race_start


def _reasons(item: dict) -> list[str]:
    return [f"近5走複勝率 {item['features']['recent_top3_rate']:.2f}", f"通算複勝率 {item['features']['top3_rate']:.2f}", f"V系スコア {item['base_score']:.1f}"]


def _top3_rate(rows: list[dict]) -> float:
    return sum((_integer(row["rank"]) or 99) <= 3 for row in rows) / len(rows) if rows else 0.0


def _top3_rate_or_none(rows: list[dict]) -> float | None:
    return _top3_rate(rows) if rows else None


def _average_rank(rows: list[dict]) -> float:
    return sum(_integer(row["rank"]) or 99 for row in rows) / len(rows) if rows else 99.0


def _bucket(value: float | None) -> str:
    if value is None:
        return "missing"
    return "lt_0_15" if value < .15 else "0_15_0_25" if value < .25 else "0_25_0_35" if value < .35 else "ge_0_35"


def _axis_odds_bucket(value: float | None) -> str:
    if value is None:
        return "missing"
    return "le_2_5" if value <= 2.5 else "2_5_4" if value <= 4 else "4_6" if value <= 6 else "gt_6"


def _surface(value) -> str:
    text = str(value or "")
    return "turf" if "芝" in text else "dirt" if "ダ" in text else text


def _integer(value) -> int | None:
    try:
        return int(str(value).replace(",", "").replace("+", ""))
    except (TypeError, ValueError):
        return None


def _float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _horse_no(value: str) -> int:
    return int(value) if value.isdigit() else 999
