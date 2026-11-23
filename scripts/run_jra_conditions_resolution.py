"""概要: 前走順位と重賞実績・直近1年の解像度を24候補で比較する。
作成日: 2026-11-13。
入力: --dataset 保存JSON、--output 未使用フォルダー。
出力: 定義別特徴/全確率/年度成績/選択/区間/レポートとSHA。正常0・失敗非0。
実行例: uv run python scripts/run_jra_conditions_resolution.py --dataset artifacts/input/dataset.json --output artifacts/resolution
注意事項: 既使用過去の追加探索。DB・外部取得・通常予想変更なし。
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jra_srb.jra_conditions_refinement import candidate_prediction, choose_candidate, group_deltas, qualify
from jra_srb.jra_conditions_search import bootstrap_difference, score_prediction
from jra_srb.jra_conditions_stability import bounded_probabilities
from jra_srb.jra_race_conditions import aggregate, examples, load_config, require, verified_conditions
from jra_srb.jra_race_conditions_report import Outputs
from jra_srb.jra_research_contracts import ResearchError, digest


def resolution_values(race: dict, row: dict, history: list[dict], mask: int) -> dict:
    """対象日前の履歴だけで、既知特徴3点のON/OFF定義を生成する。"""
    values = dict(row["values"])
    prior = sorted([h for h in history if h["horse_id"] == row["horse_id"] and h["race_date"] < race["race_date"]
                    and h["status"] == "active"], key=lambda h: (h["race_date"], h["race_key"]))
    if mask & 1 and prior:
        rank = prior[-1].get("rank")
        values["previous_rank"] = "1着" if rank == 1 else "2〜3着" if rank and rank <= 3 else values["previous_rank"]
    cutoff = (date.fromisoformat(race["race_date"])-timedelta(days=365)).isoformat()
    relevant = [h for h in prior if h["race_date"] >= cutoff] if mask & 4 else prior
    good = [h for h in relevant if h.get("rank") and h["rank"] <= 3]
    if mask & 4:
        values["repeat_top3"] = ("確認あり" if any(h["race_name"] == race["race_name"] for h in good) else "確認なし") if relevant else None
        values["course_distance_top3"] = ("確認あり" if any(h["venue_code"] == race["venue_code"] and h["distance"] == race["distance"]
            and int(h["track_code"]) < 23 for h in good) else "確認なし") if relevant else None
    if mask & 2:
        labels = ["確認なし", "GIII2〜3着", "GIII勝利", "GII2〜3着", "GII勝利", "GI2〜3着", "GI勝利"]
        quality = max([{"A": 5, "B": 3, "C": 1}[h["grade"]]+int(h["rank"] == 1)
                       for h in good if h.get("grade") in ("A", "B", "C")], default=0)
        values["graded_top3"] = labels[quality] if quality or (relevant and all(verified_conditions(h) for h in relevant)) else None
    elif mask & 4:
        values["graded_top3"] = "確認あり" if any(h.get("grade") in ("A", "B", "C") for h in good) else (
            "確認なし" if relevant and all(verified_conditions(h) for h in relevant) else None)
    return values


def run_resolution(dataset: dict, config: dict, repeats: int = 5000) -> dict:
    """8定義と3倍率の全候補を予測し、過去だけの選択と変動制限を比較する。"""
    require(dataset["input_sha256"] == digest({k: v for k, v in dataset.items() if k != "input_sha256"}), "resolution_input_sha")
    original = examples(dataset)
    candidates = [{"pattern": f"R{mask}-S{scale}", "family": "resolution", "mask": mask, "scale": scale, "weights": [1]*5, "shrinkage": 20,
                   "half_life": None, "pooling": "hierarchical", "group_count": 5, "order": mask*3+i}
                  for mask in range(8) for i, scale in enumerate((1, 2, 4))]
    annual, predictions, feature_rows = [], [], []
    for mask in range(8):
        races = deepcopy(original)
        for race in races:
            for row in race["rows"]:
                row["values"] = resolution_values(race, row, dataset["history"], mask)
                feature_rows.append({"definition": mask, "race_key": race["race_key"], "horse_no": row["horse_no"], "values": row["values"]})
        for target in races:
            prior = [r for r in races if r["race_date"] < target["race_date"] and r["evaluation_eligible"]]
            if not target["evaluation_eligible"] or len(prior) < 5:
                continue
            active = [c for c in candidates if c["mask"] == mask]
            deltas = group_deltas(prior, target, config, active[0])
            for c in active:
                p = candidate_prediction(deltas, target, c)
                predictions.append(p)
                annual.append({k: p[k] for k in ("pattern", "race_key", "race_date", "venue_code")} | score_prediction(p, target))
    annual.sort(key=lambda r: (r["race_date"], r["pattern"]))
    selection, capped, capped_predictions = [], [], []
    lookup = {(p["race_date"], p["pattern"]): p for p in predictions}
    targets = {r["race_date"]: r for r in original}
    for day in sorted({r["race_date"] for r in annual}):
        prior = [r for r in annual if r["race_date"] < day]
        if len({r["race_key"] for r in prior}) < 5:
            continue
        choice = choose_candidate(prior, candidates)
        selected = choice["candidate"]["pattern"]
        row = next(r for r in annual if r["race_date"] == day and r["pattern"] == selected)
        selection.append({**row, "selection_latest_date": max(r["race_date"] for r in prior), "candidate_brier": choice["candidate_brier"]})
        p = lookup[(day, selected)]
        old = {r["horse_no"]: r["probability_top3"] for r in lookup[(day, "R0-S1")]["runners"]}
        transformed = bounded_probabilities([r["probability_top3"] for r in p["runners"]], [old[r["horse_no"]] for r in p["runners"]], .05)
        rows = [{**r, "probability_top3": v} for r, v in zip(p["runners"], transformed, strict=True)]
        rows.sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
        cp = {**p, "pattern": "selected-cap05", "selected_component": selected, "runners": rows}
        capped_predictions.append(cp)
        capped.append({k: cp[k] for k in ("pattern", "race_key", "race_date", "venue_code")} | score_prediction(cp, targets[day]))
    days = {r["race_date"] for r in selection}
    base = [r for r in annual if r["pattern"] == "R0-S1" and r["race_date"] in days]
    outer = {}
    for name, rows in (("selected", selection), ("selected-cap05", capped)):
        m, b = aggregate(rows), aggregate(base)
        ci = bootstrap_difference(rows, base, repeats)
        wins = sum(a["brier"] < c["brier"]-1e-12 for a, c in zip(rows, base, strict=True))
        outer[name] = {"metrics": m, "baseline": b, "interval": ci, "improved_years": wins,
                       "qualifies": qualify(m, b, ci, wins)}
    return {"protocol": "elizabeth-known-resolution-v1", "input_sha256": dataset["input_sha256"], "candidates": candidates,
            "summary": [{**c, "all": aggregate([r for r in annual if r["pattern"] == c["pattern"]])} for c in candidates],
            "annual": annual, "predictions": predictions, "feature_rows": feature_rows, "selection": selection,
            "capped_annual": capped, "capped_predictions": capped_predictions, "outer": outer,
            "final_candidate": choose_candidate(annual, candidates)}


def main(argv: list[str] | None = None) -> int:
    """保存入力だけで実績解像度を比較し、新規出力へ全証跡を保存する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    outputs = None
    try:
        config = load_config(ROOT/"configs/research/race_conditions_elizabeth_v1.json")
        outputs = Outputs(args.output, "resolution-conditions", config)
        dataset = json.loads(args.dataset.read_text(encoding="utf-8-sig"))
        result = run_resolution(dataset, config)
        for key in ("predictions", "feature_rows", "selection", "capped_predictions", "capped_annual"):
            outputs.json(key+".json", result[key])
        summary = {k: v for k, v in result.items() if k not in ("predictions", "feature_rows", "selection", "annual", "capped_predictions", "capped_annual")}
        outputs.json("summary.json", summary)
        outputs.csv("annual.csv", result["annual"], ["pattern", "race_key", "race_date", "venue_code", "races", "runners", "brier", "logloss", "top1_top3_hit", "top3_captured"])
        outputs.markdown("# 既知パーツの実績解像度比較\n\n既使用期間の追加研究。結果を見て日数や区切りを調整しません。\n\n```json\n"+
                         json.dumps(summary, ensure_ascii=False, indent=2)+"\n```\n")
        code = [Path(__file__), *[ROOT/"src/jra_srb"/name for name in
                ("jra_conditions_refinement.py", "jra_conditions_search.py", "jra_conditions_stability.py")]]
        outputs.finish(input_sha256=dataset["input_sha256"], availability="retrospective_research_only",
                       resolution_code_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code})
        print(json.dumps({"status": "complete", "outer": result["outer"], "candidate": result["final_candidate"]["candidate"]["pattern"]}))
        return 0
    except Exception as error:
        if outputs is not None:
            outputs.fail(error)
        print(json.dumps({"status": "failed", "reason": getattr(error, "reason", "resolution_execution_failed"), "type": type(error).__name__}), file=sys.stderr)
        return error.exit_code if isinstance(error, ResearchError) else 4


if __name__ == "__main__":
    raise SystemExit(main())
