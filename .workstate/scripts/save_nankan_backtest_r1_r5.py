from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from jra_srb.app import app


DB_PATH = Path("data/analysis.sqlite")
DATE = "2026-07-06"
COURSE = "kawasaki"
MEETING_NO = 4
MEETING_DAY = 1
THEORY_VERSION = "nankan-race-predictor:integrated_betting:final_odds_backtest:v1"
NOW = datetime.now(UTC).isoformat()


def distance_bucket(distance: int) -> str:
    if distance <= 1200:
        return "short"
    if distance <= 1800:
        return "medium"
    return "long"


def season_key(month: int) -> str:
    if month <= 3:
        return "jan_to_mar"
    if month <= 6:
        return "apr_to_jun"
    if month <= 9:
        return "jul_to_sep"
    return "oct_to_dec"


def frame_group(frame_no: str | None) -> str | None:
    if frame_no in (None, ""):
        return None
    frame = int(frame_no)
    if frame <= 2:
        return "frame_1_2"
    if frame <= 4:
        return "frame_3_4"
    if frame <= 6:
        return "frame_5_6"
    return "frame_7_8"


def shrink(rate_obj: dict | None, k: float) -> float | None:
    if not rate_obj:
        return None
    rate = rate_obj.get("rate")
    starts = rate_obj.get("starts")
    if rate is None or starts in (None, 0):
        return None
    reliability = starts / (starts + k)
    return (rate / 100.0) * reliability


def norm_from_rank(rank: int | None, total: int) -> float | None:
    if rank is None or total <= 1:
        return None
    return max(0.0, 1.0 - ((rank - 1) / (total - 1)))


def fetch_json(client: TestClient, path: str) -> dict:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def build_records() -> list[dict]:
    client = TestClient(app)
    records: list[dict] = []

    for race_no in range(1, 6):
        race_id = f"20260706210401{race_no:02d}"
        base = f"/nankan/meetings/{DATE}/{COURSE}/races/{race_no}"
        card = fetch_json(client, f"{base}/card")
        win_odds = fetch_json(client, f"{base}/odds?bet_type=win")["entries"]
        best = fetch_json(client, f"{base}/best-time")["runners"]
        closing = fetch_json(client, f"{base}/closing-speed")["runners"]
        style = fetch_json(client, f"{base}/style-profile")["runners"]
        pattern = fetch_json(
            client,
            f"/nankankeiba/pattern/meetings/{DATE}/{COURSE}/races/{race_no}?meeting_no={MEETING_NO}&meeting_day={MEETING_DAY}",
        )["runners"]
        result = fetch_json(client, f"{base}/result")

        distance = int(card["distance"])
        bucket = distance_bucket(distance)
        condition = card["track_condition"]
        season = season_key(7)

        odds_map = {
            entry["combination"][0]: float(entry["odds"])
            for entry in win_odds
            if entry.get("odds") not in (None, "", "---.-")
        }
        inverse_odds = {horse_no: 1.0 / odds for horse_no, odds in odds_map.items() if odds > 0}
        inv_min = min(inverse_odds.values()) if inverse_odds else 0.0
        inv_max = max(inverse_odds.values()) if inverse_odds else 1.0

        def odds_score(horse_no: str) -> float:
            value = inverse_odds.get(horse_no)
            if value is None:
                return 0.0
            if inv_max == inv_min:
                return 1.0
            return (value - inv_min) / (inv_max - inv_min)

        best_map = {row["horse_no"]: row for row in best}
        closing_map = {row["horse_no"]: row for row in closing}
        style_map = {row["horse_no"]: row for row in style}
        pattern_map = {row["horse_no"]: row for row in pattern}

        scored: list[dict] = []
        field_size = len(card["runners"])

        for runner in card["runners"]:
            horse_no = runner["horse_no"]
            categories = pattern_map.get(horse_no, {}).get("categories", {})
            pattern_uma = categories.get("pattern_uma", {})
            pattern_kis = categories.get("pattern_kis", {})
            pattern_cho = categories.get("pattern_cho", {})
            pattern_kis_cho = categories.get("pattern_kis_cho", {})

            components: list[tuple[float, float]] = []

            def add_component(value: float | None, weight: float) -> None:
                if value is not None:
                    components.append((value, weight))

            add_component(shrink(pattern_uma.get("track_condition_rates", {}).get(condition), 3), 0.22)
            add_component(shrink(pattern_uma.get("rates", {}).get("kawasaki"), 4), 0.14)
            add_component(shrink(pattern_uma.get("rates", {}).get(bucket), 4), 0.14)
            add_component(shrink(pattern_uma.get("rates", {}).get("lifetime"), 6), 0.10)
            add_component(shrink(pattern_uma.get("season_rates", {}).get(season), 3), 0.05)
            group = frame_group(runner.get("frame_no"))
            if group:
                add_component(shrink(pattern_uma.get("frame_group_rates", {}).get(group), 3), 0.05)
            add_component(shrink(pattern_kis_cho.get("rates", {}).get("kawasaki"), 20), 0.10)
            add_component(shrink(pattern_kis_cho.get("rates", {}).get(bucket), 15), 0.06)
            add_component(shrink(pattern_cho.get("rates", {}).get("kawasaki"), 30), 0.07)
            add_component(shrink(pattern_kis.get("rates", {}).get("kawasaki"), 30), 0.07)
            pattern_score = (
                sum(value * weight for value, weight in components) / sum(weight for _, weight in components)
                if components
                else 0.0
            )

            best_row = best_map.get(horse_no)
            best_score = 0.0
            if best_row:
                best_score = norm_from_rank(best_row.get("best_time_rank"), field_size) or 0.0
                if best_row.get("same_course_flag"):
                    best_score += 0.08
                if best_row.get("same_distance_flag"):
                    best_score += 0.08
                if best_row.get("track_condition") == condition:
                    best_score += 0.04
                best_score = min(best_score, 1.0)

            closing_row = closing_map.get(horse_no)
            closing_score = 0.0
            if closing_row:
                closing_score = norm_from_rank(closing_row.get("best_closing_rank"), field_size) or 0.0
                if closing_row.get("same_course_flag"):
                    closing_score += 0.05
                if closing_row.get("same_distance_flag"):
                    closing_score += 0.05
                if closing_row.get("track_condition") == condition:
                    closing_score += 0.03
                closing_score = min(closing_score, 1.0)

            style_row = style_map.get(horse_no)
            style_score = 0.0
            if style_row and style_row.get("sample_size", 0) > 0:
                style_scores = style_row["style_scores"]
                style_score = (
                    style_scores.get("front", 0.0) * 1.0
                    + style_scores.get("stalker", 0.0) * 0.85
                    + style_scores.get("midpack", 0.0) * 0.55
                    + style_scores.get("closer", 0.0) * 0.3
                )
                if condition in ("heavy", "bad"):
                    style_score += style_scores.get("front", 0.0) * 0.1
                    style_score += style_scores.get("stalker", 0.0) * 0.05
                style_score = min(style_score, 1.0)

            diff_raw = runner.get("horse_weight_diff")
            body_score = 0.55
            if diff_raw not in (None, ""):
                diff = abs(int(diff_raw))
                if diff <= 4:
                    body_score = 1.0
                elif diff <= 8:
                    body_score = 0.82
                elif diff <= 12:
                    body_score = 0.65
                else:
                    body_score = 0.45

            total_score = (
                0.42 * pattern_score
                + 0.28 * odds_score(horse_no)
                + 0.12 * body_score
                + 0.10 * best_score
                + 0.05 * closing_score
                + 0.03 * style_score
            )

            scored.append(
                {
                    "horse_no": horse_no,
                    "horse_name": runner["horse_name"],
                    "odds": odds_map.get(horse_no),
                    "pattern_score": round(pattern_score, 4),
                    "odds_score": round(odds_score(horse_no), 4),
                    "body_score": round(body_score, 4),
                    "best_score": round(best_score, 4),
                    "closing_score": round(closing_score, 4),
                    "style_score": round(style_score, 4),
                    "total_score": round(total_score, 4),
                }
            )

        scored.sort(key=lambda row: (-row["total_score"], row["odds"] if row["odds"] is not None else 9999.0, row["horse_no"]))
        predicted_top3 = scored[:3]
        actual_top3 = result["results"][:3]
        predicted_nos = [row["horse_no"] for row in predicted_top3]
        actual_nos = [row["horse_no"] for row in actual_top3]
        top1 = scored[0]
        top2 = scored[1] if len(scored) > 1 else None
        hot = (
            "熱い！"
            if top2
            and (top1["total_score"] - top2["total_score"] >= 0.06)
            and ((top1["odds"] or 99) <= 6.0)
            and (top1["pattern_score"] >= top2["pattern_score"])
            else "通常"
        )

        missing_win_odds = [runner["horse_no"] for runner in card["runners"] if runner["horse_no"] not in odds_map]
        prediction_id = f"pred-nankan-20260706-kawasaki-r{race_no:02d}-final-odds-backtest-v1"
        evaluation_id = f"eval-nankan-20260706-kawasaki-r{race_no:02d}-final-odds-backtest-v1"

        pre_race_snapshot = {
            "race_id": race_id,
            "date": DATE,
            "course": COURSE,
            "race_no": race_no,
            "meeting_no": MEETING_NO,
            "meeting_day": MEETING_DAY,
            "mode": "integrated_betting",
            "data_policy": {
                "trend_used": False,
                "trend_exclusion_reason": "開催終了後の集計であり当時点へ戻せないため",
                "final_odds_used_for_backtest": True,
            },
            "card": card,
            "win_odds": win_odds,
            "best_time": best,
            "closing_speed": closing,
            "style_profile": style,
            "pattern": pattern,
        }

        prediction_json = {
            "prediction_id": prediction_id,
            "race_id": race_id,
            "theory_version": THEORY_VERSION,
            "mode": "integrated_betting",
            "prediction_date": DATE,
            "course": COURSE,
            "race_no": race_no,
            "hot": hot,
            "predicted_top3": predicted_top3,
            "actual_top3_hidden_at_prediction_time": True,
            "notes": [
                "主軸: 勝ちパターン分析 + 最終単勝オッズ + 馬場 + 馬体重",
                "補正: 持ち時計 + 上がり + 脚質",
                "当日傾向(trend)は情報漏洩回避のため不使用",
            ],
            "missing_win_odds_horses": missing_win_odds,
        }

        evaluation_json = {
            "prediction_id": prediction_id,
            "race_id": race_id,
            "theory_version": THEORY_VERSION,
            "summary": {
                "winner_hit": predicted_nos[0] == actual_nos[0],
                "top3_box_hit": sorted(predicted_nos) == sorted(actual_nos),
                "axis_in_top3": predicted_nos[0] in actual_nos,
                "predicted_top3_contains_winner": actual_nos[0] in predicted_nos,
            },
            "predicted_top3": predicted_top3,
            "actual_top3": actual_top3,
            "payouts": result["payouts"],
            "review": {
                "final_odds_backtest": True,
                "ticket_strategy_saved": False,
                "missing_win_odds_horses": missing_win_odds,
            },
        }

        records.append(
            {
                "race_id": race_id,
                "prediction_id": prediction_id,
                "evaluation_id": evaluation_id,
                "pre_race_snapshot": pre_race_snapshot,
                "prediction_json": prediction_json,
                "evaluation_json": evaluation_json,
                "hit": 1 if predicted_nos[0] == actual_nos[0] else 0,
                "axis_in_top3": 1 if predicted_nos[0] in actual_nos else 0,
                "gami": 0,
                "return_rate": 0.0,
                "middle_hole_in_top3": None,
                "firework_hit": 0,
                "max_odds_selected": max((row["odds"] for row in predicted_top3 if row["odds"] is not None), default=None),
            }
        )

    return records


def save_records(records: list[dict]) -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("begin")
        conn.execute(
            """
            insert into theory_versions
            (theory_version, parent_version, status, theory_yaml, notes, created_at, promoted_at)
            values (?, ?, ?, ?, ?, ?, ?)
            on conflict(theory_version) do update set
              status=excluded.status,
              theory_yaml=excluded.theory_yaml,
              notes=excluded.notes
            """,
            (
                THEORY_VERSION,
                "nankan-race-predictor:integrated_betting:v1",
                "candidate",
                json.dumps(
                    {
                        "mode": "integrated_betting",
                        "main_axes": ["pattern", "final_win_odds", "track_condition", "horse_weight"],
                        "corrections": ["best_time", "closing_speed", "style_profile"],
                        "trend_used": False,
                        "use_case": "2026-07-06 kawasaki races 1-5 final odds backtest",
                    },
                    ensure_ascii=False,
                ),
                "API only backtest for Kawasaki races 1-5 on 2026-07-06 using final win odds.",
                NOW,
                None,
            ),
        )

        for record in records:
            conn.execute("delete from evaluation_ticket_results where evaluation_id = ?", (record["evaluation_id"],))
            conn.execute("delete from evaluations where evaluation_id = ?", (record["evaluation_id"],))
            conn.execute("delete from prediction_tickets where prediction_id = ?", (record["prediction_id"],))
            conn.execute("delete from predictions where prediction_id = ?", (record["prediction_id"],))

            conn.execute(
                """
                insert into predictions
                (prediction_id, race_id, theory_version, mode, budget, pre_race_snapshot_json, prediction_json, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["prediction_id"],
                    record["race_id"],
                    THEORY_VERSION,
                    "integrated_betting",
                    0,
                    json.dumps(record["pre_race_snapshot"], ensure_ascii=False),
                    json.dumps(record["prediction_json"], ensure_ascii=False),
                    NOW,
                ),
            )

            conn.execute(
                """
                insert into evaluations
                (evaluation_id, prediction_id, race_id, theory_version, total_bet, total_payout, return_rate, hit, gami,
                 axis_in_top3, middle_hole_in_top3, firework_hit, max_odds_selected, evaluation_json, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["evaluation_id"],
                    record["prediction_id"],
                    record["race_id"],
                    THEORY_VERSION,
                    0,
                    0,
                    record["return_rate"],
                    record["hit"],
                    record["gami"],
                    record["axis_in_top3"],
                    record["middle_hole_in_top3"],
                    record["firework_hit"],
                    record["max_odds_selected"],
                    json.dumps(record["evaluation_json"], ensure_ascii=False),
                    NOW,
                ),
            )

        conn.commit()
    finally:
        conn.close()


def main() -> None:
    records = build_records()
    save_records(records)
    print(
        json.dumps(
            {
                "db_path": str(DB_PATH),
                "theory_version": THEORY_VERSION,
                "saved_predictions": [record["prediction_id"] for record in records],
                "saved_evaluations": [record["evaluation_id"] for record in records],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
