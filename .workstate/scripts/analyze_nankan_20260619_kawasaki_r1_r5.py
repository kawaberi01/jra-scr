from __future__ import annotations

import json
from collections import defaultdict

from fastapi.testclient import TestClient

from jra_srb.app import app


DATE = "2026-06-19"
COURSE = "kawasaki"
MEETING_NO = 3
MEETING_DAY = 5
RACES = range(1, 6)


def rank_map(rows: list[dict], key: str) -> dict[str, int]:
    valid = []
    for row in rows:
        value = row.get(key)
        if value in (None, "", 0, "0"):
            continue
        try:
            valid.append((row["horse_no"], float(value)))
        except (TypeError, ValueError):
            continue
    valid.sort(key=lambda item: item[1])
    return {horse_no: idx + 1 for idx, (horse_no, _) in enumerate(valid)}


def is_two_year_old(card: dict) -> bool:
    ages = []
    for runner in card["runners"]:
        sex_age = runner.get("sex_age") or ""
        if sex_age and sex_age[-1].isdigit():
            ages.append(int(sex_age[-1]))
    return bool(ages) and max(ages) <= 2


def build_score(card: dict, odds: dict, best_time: dict, closing: dict, style_profile: dict) -> list[dict]:
    odds_map = {}
    for entry in odds["entries"]:
        raw = entry.get("odds")
        if raw in (None, ""):
            continue
        odds_map[entry["combination"][0]] = float(raw)

    odds_rank = {horse_no: idx + 1 for idx, (horse_no, _) in enumerate(sorted(odds_map.items(), key=lambda x: x[1]))}
    best_rank = rank_map(best_time.get("runners", []), "best_time_rank")
    closing_rank = rank_map(closing.get("runners", []), "best_closing_rank")
    style_map = {row["horse_no"]: row for row in style_profile.get("runners", [])}
    best_map = {row["horse_no"]: row for row in best_time.get("runners", [])}
    closing_map = {row["horse_no"]: row for row in closing.get("runners", [])}

    two_year_old = is_two_year_old(card)
    speed_weight = 0.8 if two_year_old else 1.5
    closing_weight = 0.5 if two_year_old else 1.0

    rows: list[dict] = []
    for runner in card["runners"]:
        horse_no = runner["horse_no"]
        score = 0.0
        reasons = []

        if horse_no in odds_rank:
            rank = odds_rank[horse_no]
            score += max(0, 10 - rank) * 1.4
            reasons.append(f"最終単勝{odds_map[horse_no]:.1f}倍")

        if horse_no in best_rank:
            rank = best_rank[horse_no]
            score += max(0, 10 - rank) * speed_weight
            best_row = best_map.get(horse_no, {})
            if best_row.get("same_course_flag"):
                score += 0.6
                reasons.append("持ち時計が同場")
            if best_row.get("same_distance_flag"):
                score += 0.6
                reasons.append("持ち時計が同距離")

        if horse_no in closing_rank:
            rank = closing_rank[horse_no]
            score += max(0, 10 - rank) * closing_weight
            closing_row = closing_map.get(horse_no, {})
            if closing_row.get("same_course_flag"):
                score += 0.3
            if closing_row.get("same_distance_flag"):
                score += 0.3
            reasons.append("上がり順位あり")

        style = style_map.get(horse_no)
        if style:
            expected = style.get("expected_style")
            sample_size = style.get("sample_size") or 0
            if sample_size >= 3:
                if card.get("track_condition") in {"heavy", "bad"}:
                    if expected == "front":
                        score += 0.9
                        reasons.append("重馬場で前寄り")
                    elif expected == "stalker":
                        score += 0.5
                        reasons.append("重馬場で好位寄り")
                elif expected == "closer":
                    score += 0.2

        diff_raw = runner.get("horse_weight_diff")
        try:
            diff = int(str(diff_raw).replace("+", ""))
        except ValueError:
            diff = 0
        if abs(diff) >= 15:
            score -= 0.8
            reasons.append("馬体重増減大きい")
        elif abs(diff) >= 10:
            score -= 0.4

        rows.append(
            {
                "horse_no": horse_no,
                "horse_name": runner["horse_name"],
                "score": round(score, 2),
                "odds": odds_map.get(horse_no),
                "reasons": reasons[:4],
            }
        )

    rows.sort(key=lambda row: (-row["score"], row["odds"] if row["odds"] is not None else 9999, int(row["horse_no"])))
    return rows


def fetch_json(client: TestClient, path: str, required: bool = True) -> dict:
    response = client.get(path)
    if response.status_code >= 400:
        if required:
            response.raise_for_status()
        return {}
    return response.json()


def main() -> None:
    client = TestClient(app)
    report = []
    summary = defaultdict(int)

    for race_no in RACES:
        race_id = f"20260619210305{race_no:02d}"
        card = fetch_json(client, f"/nankan/races/{race_id}/card")
        odds = fetch_json(client, f"/nankan/races/{race_id}/odds?bet_type=win")
        best_time = fetch_json(client, f"/nankan/races/{race_id}/best-time", required=False)
        closing = fetch_json(client, f"/nankan/races/{race_id}/closing-speed", required=False)
        style_profile = fetch_json(client, f"/nankan/races/{race_id}/style-profile", required=False)
        result = fetch_json(client, f"/nankan/races/{race_id}/result")

        ranked = build_score(card, odds, best_time, closing, style_profile)
        predicted = ranked[:3]
        actual = result["results"][:3]
        predicted_nos = [row["horse_no"] for row in predicted]
        actual_nos = [row["horse_no"] for row in actual]

        hit_1 = predicted_nos[0] == actual_nos[0]
        hit_top3 = actual_nos[0] in predicted_nos
        overlap = len(set(predicted_nos) & set(actual_nos))

        summary["races"] += 1
        summary["hit_1"] += int(hit_1)
        summary["winner_in_top3"] += int(hit_top3)
        summary["top3_overlap_total"] += overlap

        report.append(
            {
                "race_no": race_no,
                "race_id": race_id,
                "race_name": card["race_name"],
                "track_condition": card.get("track_condition"),
                "missing_materials": [
                    name
                    for name, payload in (
                        ("best_time", best_time),
                        ("closing_speed", closing),
                        ("style_profile", style_profile),
                    )
                    if not payload
                ],
                "predicted": predicted,
                "actual": actual,
                "hit_1": hit_1,
                "winner_in_top3": hit_top3,
                "top3_overlap": overlap,
            }
        )

    print(
        json.dumps(
            {
                "date": DATE,
                "course": COURSE,
                "meeting_no": MEETING_NO,
                "meeting_day": MEETING_DAY,
                "summary": dict(summary),
                "races": report,
            },
            ensure_ascii=True,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
