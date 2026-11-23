"""概要: 5条件群の中央値・中央3群平均で外れ値への耐性を検証する。
作成日: 2026-11-13。
入力: --source 先行69比較、--dataset 元保存JSON、--output 未使用フォルダー。
出力: 13候補の全予測/年度指標/選択、採否、研究レポート、SHA。正常0・失敗非0。
実行例: uv run python scripts/run_jra_conditions_robust.py --source artifacts/refinement --dataset artifacts/input/dataset.json --output artifacts/robust
注意事項: 後ろ向きの追加探索。外部取得・DB・購入・既存出力上書きなし。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from run_jra_conditions_stability import load_source
from jra_srb.jra_conditions_refinement import BASELINE, choose_candidate, qualify
from jra_srb.jra_conditions_search import bootstrap_difference, score_prediction
from jra_srb.jra_conditions_stability import bounded_probabilities
from jra_srb.jra_race_conditions import aggregate, examples, load_config, probabilities, require
from jra_srb.jra_race_conditions_report import Outputs
from jra_srb.jra_research_contracts import ResearchError, digest


def run_robust(source: dict, evidence: list[dict], dataset: dict, repeats: int = 5000) -> dict:
    """事前固定した12候補と旧方式を予測し、過去だけの選択を評価する。"""
    require(dataset["input_sha256"] == source["input_sha256"] and dataset["input_sha256"] ==
            digest({k: v for k, v in dataset.items() if k != "input_sha256"}), "robust_input_sha")
    candidates = [{"pattern": BASELINE, "group_count": 5, "order": 0, "aggregation": "mean", "scale": 1, "cap": None}]
    for aggregation in ("median", "trimmed"):
        for scale in (1, 2, 4):
            for cap in (None, .05):
                candidates.append({"pattern": f"{aggregation}-S{scale}-C{cap}", "group_count": 5, "order": len(candidates),
                                   "aggregation": aggregation, "scale": scale, "cap": cap})
    targets = {r["race_key"]: r for r in examples(dataset)}
    original = {p["race_key"]: p for p in source["predictions"] if p["pattern"] == BASELINE}
    annual, predictions = [], []
    for ev in evidence:
        if (ev["shrinkage"], ev["half_life"], ev["pooling"]) != (20, None, "hierarchical"):
            continue
        target = targets[ev["race_key"]]
        old = {r["horse_no"]: r["probability_top3"] for r in original[ev["race_key"]]["runners"]}
        for c in candidates:
            values = []
            for horse in ev["runners"]:
                values.append(robust_delta(horse["deltas"], c["aggregation"]) * c["scale"])
            estimated = probabilities(values)
            if c["cap"] is not None:
                estimated = bounded_probabilities(estimated, [old[r["horse_no"]] for r in ev["runners"]], c["cap"])
            rows = [{k: r[k] for k in ("horse_no", "horse_name", "horse_id")} | {"probability_top3": p}
                    for r, p in zip(ev["runners"], estimated, strict=True)]
            rows.sort(key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
            prediction = {"pattern": c["pattern"], "race_key": ev["race_key"], "race_date": ev["race_date"],
                          "venue_code": target["venue_code"], "prior_latest_date": ev["prior_latest_date"], "runners": rows}
            predictions.append(prediction)
            annual.append({k: prediction[k] for k in ("pattern", "race_key", "race_date", "venue_code")} | score_prediction(prediction, target))
    selection = []
    for day in sorted({r["race_date"] for r in annual}):
        past = [r for r in annual if r["race_date"] < day]
        if len({r["race_key"] for r in past}) < 5:
            continue
        choice = choose_candidate(past, candidates)
        current = next(r for r in annual if r["race_date"] == day and r["pattern"] == choice["candidate"]["pattern"])
        selection.append({**current, "selection_latest_date": max(r["race_date"] for r in past), "candidate_brier": choice["candidate_brier"]})
    days = {r["race_date"] for r in selection}
    old = [r for r in annual if r["race_date"] in days and r["pattern"] == BASELINE]
    interval = bootstrap_difference(selection, old, repeats)
    m, base = aggregate(selection), aggregate(old)
    wins = sum(a["brier"] < b["brier"]-1e-12 for a, b in zip(selection, old, strict=True))
    return {"protocol": "elizabeth-robust-groups-v1", "candidates": candidates, "input_sha256": dataset["input_sha256"],
            "annual": annual, "predictions": predictions, "selection": selection,
            "summary": [{**c, "all": aggregate([r for r in annual if r["pattern"] == c["pattern"]])} for c in candidates],
            "outer": {"selected": m, "baseline": base, "interval": interval, "improved_years": wins,
                      "qualifies": qualify(m, base, interval, wins)}, "final_candidate": choose_candidate(annual, candidates)}


def robust_delta(values: list[float], aggregation: str) -> float:
    """固定した5群から平均・中央値・中央3群平均のいずれかを返す。"""
    require(len(values) == 5 and aggregation in ("mean", "median", "trimmed"), "robust_delta_contract")
    return sum(values)/5 if aggregation == "mean" else median(values) if aggregation == "median" else sum(sorted(values)[1:4])/3


def main(argv: list[str] | None = None) -> int:
    """保存根拠を検証して外れ値耐性の固定比較を新規成果物へ保存する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    outputs = None
    try:
        config = load_config(ROOT / "configs/research/race_conditions_elizabeth_v1.json")
        outputs = Outputs(args.output, "robust-conditions", config)
        source = load_source(args.source)
        evidence = json.loads((args.source/"evidence.json").read_text(encoding="utf-8"))
        dataset = json.loads(args.dataset.read_text(encoding="utf-8-sig"))
        result = run_robust(source, evidence, dataset)
        for key in ("predictions", "selection"):
            outputs.json(key+".json", result[key])
        outputs.json("summary.json", {k: v for k, v in result.items() if k not in ("predictions", "annual", "selection")})
        outputs.csv("annual.csv", result["annual"], ["pattern", "race_key", "race_date", "venue_code", "races", "runners",
                    "brier", "logloss", "top1_top3_hit", "top3_captured"])
        outputs.markdown("# 5条件群の外れ値耐性比較\n\n後ろ向き追加探索。事前4基準を維持。\n\n```json\n"+
                         json.dumps({"outer": result["outer"], "final_candidate": result["final_candidate"], "summary": result["summary"]},
                                    ensure_ascii=False, indent=2)+"\n```\n")
        code = [ROOT/"src/jra_srb"/name for name in ("jra_conditions_search.py", "jra_conditions_refinement.py", "jra_conditions_stability.py")]
        code += [Path(__file__), ROOT/"scripts/run_jra_conditions_stability.py"]
        outputs.finish(input_sha256=dataset["input_sha256"], availability="retrospective_research_only",
                       source_manifest_sha256=source["source_manifest_sha256"],
                       robust_code_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code})
        print(json.dumps({"status": "complete", "outer": result["outer"], "candidate": result["final_candidate"]["candidate"]["pattern"]}))
        return 0
    except Exception as error:
        if outputs is not None:
            outputs.fail(error)
        print(json.dumps({"status": "failed", "reason": getattr(error, "reason", "robust_execution_failed"), "type": type(error).__name__}), file=sys.stderr)
        return error.exit_code if isinstance(error, ResearchError) else 4


if __name__ == "__main__":
    raise SystemExit(main())
