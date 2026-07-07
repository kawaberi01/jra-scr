from __future__ import annotations

import json
from pathlib import Path


DATA = Path("data/nankankeiba_pattern_20260706_kawasaki_1r_live.json")


def get_rate(obj: dict, *path: str) -> float | None:
    cur = obj
    for part in path:
        cur = (cur or {}).get(part)
        if cur is None:
            return None
    return cur.get("rate") if isinstance(cur, dict) else None


def get_starts(obj: dict, *path: str) -> int | None:
    cur = obj
    for part in path:
        cur = (cur or {}).get(part)
        if cur is None:
            return None
    return cur.get("starts") if isinstance(cur, dict) else None


def add_component(components: list[tuple[str, float, float]], label: str, value: float | None, weight: float) -> None:
    if isinstance(value, (int, float)):
        components.append((label, float(value), weight))


def main() -> None:
    bundle = json.loads(DATA.read_text(encoding="utf-8"))
    frame_key_map = {
        "1": "frame_1_2",
        "2": "frame_1_2",
        "3": "frame_3_4",
        "4": "frame_3_4",
        "5": "frame_5_6",
        "6": "frame_5_6",
        "7": "frame_7_8",
        "8": "frame_7_8",
    }
    rows = []
    for runner in bundle["runners"]:
        categories = runner["categories"]
        frame_key = frame_key_map.get(runner["frame_no"])
        components: list[tuple[str, float, float]] = []
        add_component(components, "kis.kawasaki", get_rate(categories, "pattern_kis", "rates", "kawasaki"), 1.0)
        add_component(components, "kis.medium", get_rate(categories, "pattern_kis", "rates", "medium"), 1.0)
        add_component(components, "uma.lifetime", get_rate(categories, "pattern_uma", "rates", "lifetime"), 0.8)
        add_component(components, "uma.medium", get_rate(categories, "pattern_uma", "rates", "medium"), 1.3)
        add_component(components, "uma.season", get_rate(categories, "pattern_uma", "season_rates", "jul_to_sep"), 1.0)
        if frame_key:
            add_component(
                components,
                "uma.frame",
                get_rate(categories, "pattern_uma", "frame_group_rates", frame_key),
                0.9,
            )
        add_component(components, "cho.kawasaki", get_rate(categories, "pattern_cho", "rates", "kawasaki"), 1.0)
        add_component(components, "cho.medium", get_rate(categories, "pattern_cho", "rates", "medium"), 1.0)
        add_component(components, "pair.kawasaki", get_rate(categories, "pattern_kis_cho", "rates", "kawasaki"), 1.4)
        add_component(components, "pair.medium", get_rate(categories, "pattern_kis_cho", "rates", "medium"), 1.4)
        total_weight = sum(weight for _, _, weight in components)
        score = sum(value * weight for _, value, weight in components) / total_weight if total_weight else 0.0
        rows.append(
            {
                "no": runner["horse_no"],
                "horse": runner["horse_name"],
                "jockey": runner["jockey"],
                "trainer": runner["trainer"],
                "frame_no": runner["frame_no"],
                "score": round(score, 2),
                "kis_k": get_rate(categories, "pattern_kis", "rates", "kawasaki"),
                "kis_m": get_rate(categories, "pattern_kis", "rates", "medium"),
                "uma_life": get_rate(categories, "pattern_uma", "rates", "lifetime"),
                "uma_m": get_rate(categories, "pattern_uma", "rates", "medium"),
                "uma_season": get_rate(categories, "pattern_uma", "season_rates", "jul_to_sep"),
                "uma_frame": get_rate(categories, "pattern_uma", "frame_group_rates", frame_key) if frame_key else None,
                "cho_k": get_rate(categories, "pattern_cho", "rates", "kawasaki"),
                "cho_m": get_rate(categories, "pattern_cho", "rates", "medium"),
                "pair_k": get_rate(categories, "pattern_kis_cho", "rates", "kawasaki"),
                "pair_k_starts": get_starts(categories, "pattern_kis_cho", "rates", "kawasaki"),
                "pair_m": get_rate(categories, "pattern_kis_cho", "rates", "medium"),
                "pair_m_starts": get_starts(categories, "pattern_kis_cho", "rates", "medium"),
            }
        )
    rows.sort(key=lambda item: item["score"], reverse=True)
    print("race_id", bundle["race_id"])
    for row in rows:
        print(
            f"{row['no']} {row['horse']} score={row['score']} frame={row['frame_no']} "
            f"kis={row['kis_k']}/{row['kis_m']} "
            f"umaLife={row['uma_life']} umaM={row['uma_m']} season={row['uma_season']} frameRate={row['uma_frame']} "
            f"cho={row['cho_k']}/{row['cho_m']} "
            f"pair={row['pair_k']}({row['pair_k_starts']})/{row['pair_m']}({row['pair_m_starts']})"
        )


if __name__ == "__main__":
    main()
