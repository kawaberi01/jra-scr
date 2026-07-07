from __future__ import annotations

import json
from pathlib import Path
from statistics import mean


DATA = Path("data/nankankeiba_pattern_20260706_kawasaki_1r_live.json")


def rate(runner: dict, category: str, key: str) -> float | None:
    return (
        ((runner.get("categories") or {}).get(category) or {})
        .get("rates", {})
        .get(key, {})
        .get("rate")
    )


def starts(runner: dict, category: str, key: str) -> int | None:
    return (
        ((runner.get("categories") or {}).get(category) or {})
        .get("rates", {})
        .get(key, {})
        .get("starts")
    )


def main() -> None:
    bundle = json.loads(DATA.read_text(encoding="utf-8"))
    keys = [
        ("pattern_kis", "kawasaki"),
        ("pattern_kis", "medium"),
        ("pattern_uma", "kawasaki"),
        ("pattern_uma", "medium"),
        ("pattern_uma", "m7m9"),
        ("pattern_cho", "kawasaki"),
        ("pattern_cho", "medium"),
        ("pattern_kis_cho", "kawasaki"),
        ("pattern_kis_cho", "medium"),
    ]
    weights = [
        (("pattern_kis", "kawasaki"), 1.0),
        (("pattern_kis", "medium"), 1.0),
        (("pattern_uma", "kawasaki"), 1.4),
        (("pattern_uma", "medium"), 1.4),
        (("pattern_uma", "m7m9"), 0.8),
        (("pattern_cho", "kawasaki"), 1.0),
        (("pattern_cho", "medium"), 1.0),
        (("pattern_kis_cho", "kawasaki"), 1.5),
        (("pattern_kis_cho", "medium"), 1.5),
    ]
    rows = []
    for runner in bundle["runners"]:
        values = [rate(runner, category, key) for category, key in keys]
        values = [value for value in values if isinstance(value, (int, float))]
        numerator = sum((rate(runner, category, key) or 0) * weight for (category, key), weight in weights)
        rows.append(
            {
                "no": runner["horse_no"],
                "horse": runner["horse_name"],
                "jockey": runner["jockey"],
                "trainer": runner["trainer"],
                "avg": round(mean(values), 2) if values else 0,
                "weighted": round(numerator / sum(weight for _, weight in weights), 2),
                "kis_k": rate(runner, "pattern_kis", "kawasaki"),
                "kis_m": rate(runner, "pattern_kis", "medium"),
                "uma_k": rate(runner, "pattern_uma", "kawasaki"),
                "uma_m": rate(runner, "pattern_uma", "medium"),
                "uma_season": rate(runner, "pattern_uma", "m7m9"),
                "cho_k": rate(runner, "pattern_cho", "kawasaki"),
                "cho_m": rate(runner, "pattern_cho", "medium"),
                "pair_k": rate(runner, "pattern_kis_cho", "kawasaki"),
                "pair_m": rate(runner, "pattern_kis_cho", "medium"),
                "pair_k_starts": starts(runner, "pattern_kis_cho", "kawasaki"),
                "pair_m_starts": starts(runner, "pattern_kis_cho", "medium"),
            }
        )

    rows.sort(key=lambda item: item["weighted"], reverse=True)
    print("race_id", bundle["race_id"], "fetched_at", bundle["fetched_at"])
    print(
        "No\tHorse\tJockey\tTrainer\tWeighted\tAvg\t"
        "KisK/M\tUmaK/M/Season\tChoK/M\tPairK/M starts"
    )
    for row in rows:
        print(
            f"{row['no']}\t{row['horse']}\t{row['jockey']}\t{row['trainer']}\t"
            f"{row['weighted']}\t{row['avg']}\t"
            f"{row['kis_k']}/{row['kis_m']}\t"
            f"{row['uma_k']}/{row['uma_m']}/{row['uma_season']}\t"
            f"{row['cho_k']}/{row['cho_m']}\t"
            f"{row['pair_k']}/{row['pair_m']} {row['pair_k_starts']}/{row['pair_m_starts']}"
        )

    print("\nDETAIL")
    for runner in bundle["runners"]:
        print(f"\n{runner['horse_no']} {runner['horse'] if 'horse' in runner else runner['horse_name']}")
        for category in ("pattern_kis", "pattern_uma", "pattern_cho", "pattern_kis_cho"):
            rates = runner["categories"][category]["rates"]
            values = []
            for key in (
                "lifetime",
                "kawasaki",
                "medium",
                "popularity_1",
                "popularity_2",
                "popularity_3",
                "popularity_4_or_more",
            ):
                item = rates.get(key, {})
                values.append(f"{key}={item.get('rate')}%({item.get('wins')}/{item.get('starts')})")
            print(category, " ".join(values))


if __name__ == "__main__":
    main()
