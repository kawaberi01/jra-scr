from __future__ import annotations

import gzip
import json
from collections import defaultdict
from pathlib import Path


GRID = [(rank, odds, edge) for rank in (1, 2, 3) for odds in (10.0, 15.0, 20.0) for edge in (0.01, 0.02, 0.03)]


def load(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def enrich(rows: list[dict]) -> None:
    races: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        races[row["race_id"]].append(row)
    for runners in races.values():
        for rank, row in enumerate(sorted(runners, key=lambda item: (-item["market_probability_normalized"], item["horse_no"])), 1):
            row["market_rank"] = rank
        for rank, row in enumerate(sorted(runners, key=lambda item: (-item["isotonic_probability"], item["horse_no"])), 1):
            row["model_rank"] = rank


def select(rows: list[dict], config: tuple[int, float, float]) -> list[dict]:
    rank_limit, odds_max, edge_min = config
    races: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if 4 <= row["market_rank"] <= 6 and row["model_rank"] <= rank_limit and row["win_odds"] <= odds_max and row["isotonic_probability"] - row["market_probability_normalized"] >= edge_min:
            races[row["race_id"]].append(row)
    return [max(runners, key=lambda item: (item["isotonic_probability"] - item["market_probability_normalized"], item["isotonic_probability"])) for runners in races.values()]


def metrics(items: list[dict]) -> dict:
    payouts = [item["win_payout"] if item["label_win"] else 0 for item in items]
    ordered = sorted(payouts, reverse=True)
    def roi(values: list[int]) -> float:
        return sum(values) / (100 * len(values)) if values else 0.0
    return {"candidates": len(items), "hits": sum(value > 0 for value in payouts), "roi": roi(payouts), "no_max_roi": roi(ordered[1:]), "no_top3_roi": roi(ordered[3:]), "over_30_rate": sum(item["win_odds"] > 30 for item in items) / len(items) if items else 0.0}


def main() -> None:
    root = Path(".workstate/jra-srb/jra-win-ev-revalidation/artifacts")
    rows = load(root / "runner-predictions.jsonl.gz")
    split = json.loads((root / "split-metadata.json").read_text(encoding="utf-8"))["date_sets"]
    calibration_days, external_days = set(split["calibration"]), set(split["external"])
    calibration = [row for row in rows if row["race_date"] in calibration_days]
    external = [row for row in rows if row["race_date"] in external_days]
    enrich(calibration); enrich(external)
    comparisons = []
    for config in GRID:
        result = metrics(select(calibration, config))
        comparisons.append({"config": {"max_model_rank": config[0], "max_win_odds": config[1], "min_residual": config[2]}, "metrics": result})
    viable = [item for item in comparisons if item["metrics"]["candidates"] >= 100]
    selected = max(viable, key=lambda item: (item["metrics"]["no_top3_roi"], item["metrics"]["no_max_roi"], item["metrics"]["roi"])) if viable else None
    external_metrics = metrics(select(external, (selected["config"]["max_model_rank"], selected["config"]["max_win_odds"], selected["config"]["min_residual"]))) if selected else None
    result = {"hypothesis": "市場4〜6番手だが履歴モデル上位の馬にだけ、市場に未反映の過去適性が残る", "status": "external_evaluated", "selected": selected, "external": external_metrics, "comparisons": comparisons}
    out = Path(".workstate/jra-srb/jra-market-residual-validation"); out.mkdir(parents=True, exist_ok=True)
    (out / "market-residual-validation.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 市場残差・中位人気理論", "", f"- 仮説: {result['hypothesis']}", f"- 固定方策: {selected}", f"- 外部評価: {external_metrics}", ""]
    (out / "market-residual-validation.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"MARKET_RESIDUAL_STATUS=completed external={external_metrics}")


if __name__ == "__main__":
    main()
