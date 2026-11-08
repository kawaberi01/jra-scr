"""Additional ten methods; existing data only, no post-2026 parameter search."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil

import joblib
import numpy as np
import scipy
import sklearn
from threadpoolctl import threadpool_limits

from evaluate_jra_o1o2_movement import read_races, sha256
from evaluate_jra_ten_trials import (DEV_WINDOWS, EVAL_WINDOWS, SUPPLEMENT, load_records as previous_load,
                                    evaluate_policy, gate, summarize, write_json, windows)
from jra_second_ten_model import EXPERIMENTS, augment, fit_suite, score_suite

MONTHS = (6, 7, 8)
POLICY = {"group": "all", "threshold": 1.05}


def load_records(root):
    records, audit = previous_load(root, MONTHS)
    index = {r["race_id"]: r for r in records}
    for race in read_races(root):
        if race["race_id"] in index:
            r = augment(index[race["race_id"]], race)
            r["training_ranks"] = np.asarray([int(race["result"]["ranks_by_horse"].get(k, 0)) for k in r["keys"]])
    return records, audit


def run_windows(records, definitions, root, stage, progress):
    output = {k: [] for k in EXPERIMENTS}
    for start, end, train, test in windows(records, definitions):
        if not train or not test or train[-1]["race_date"] >= test[0]["race_date"]:
            raise ValueError("invalid chronological partition")
        suite = fit_suite(train, MONTHS, as_of=start)
        path = root / "fold_models" / f"{stage}_{start}.joblib"
        joblib.dump(suite, path)
        for r in test:
            scores = score_suite(suite, r)
            for key, (_, kind, _) in EXPERIMENTS.items():
                if key in scores:
                    output[key].append({"record": r if kind == "win" else r["pair"],
                                        "score": scores[key], "fold": start})
        item = {"stage": stage, "from": start, "through": end, "train": len(train), "evaluation": len(test),
                "training_max_date": train[-1]["race_date"], "calibration_alpha": suite["calibrated"]["alpha"],
                "calibration_from": suite["calibrated"]["calibration_from"],
                "calibration_base_fit_through": suite["calibrated"]["fit_max_date"],
                "artifact_sha256": sha256(path)}
        progress.append(item)
        write_json(root / "progress.json", progress)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    return output


def comparison_key(item):
    folds = list(item["folds"].values())
    sufficient = all(s["tickets"] >= 20 for s in folds)
    worst = min((s["roi"] or 0) for s in folds)
    return sufficient, worst, item["summary"]["roi_lower_one_sided"]


def descriptive_slices(rows):
    output = {}
    for dimension in ("surface", "distance_band", "course"):
        groups = {}
        for row in rows:
            value = ("sprint" if row["distance"] <= 1400 else "middle" if row["distance"] <= 2000 else "stayer") if dimension == "distance_band" else row[dimension]
            groups.setdefault(value, []).append(row)
        output[dimension] = {value: summarize(group, bootstrap=False) for value, group in sorted(groups.items())}
    return output


def save_predictions(path, datasets):
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for stage, experiments in datasets.items():
            for key, entries in experiments.items():
                for entry in entries:
                    r, score = entry["record"], entry["score"]
                    row = {"stage": stage, "trial": key, "race_id": r["race_id"], "race_date": r["race_date"],
                           "fold": entry["fold"], "keys": r["keys"], "probability": score["probability"].tolist(),
                           "projected_return": score["projected_return"].tolist(),
                           "probability_note": score.get("probability_note")}
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")


def run(args):
    root = args.output_dir
    if root.exists():
        raise ValueError("choose a new output directory")
    records, audit = load_records(args.data_root)
    (root / "fold_models").mkdir(parents=True)
    protocol = {"created_at": datetime.now(timezone.utc).isoformat(), "methods_limit": 10,
                "methods": EXPERIMENTS, "decision_time": "T-30m", "summer_excluded": MONTHS,
                "development": DEV_WINDOWS, "exploratory": EVAL_WINDOWS, "supplement": SUPPLEMENT,
                "fixed_policy": POLICY, "additional_policy_searches": 0, "only_existing_data": True,
                "external_data_or_db_used": False, "audit": audit,
                "limitations": ["2026 is reused exploratory data; hypotheses also informed by previous research.",
                                "Historical card/start-time identities are mostly unverified and odds are retrospectively reconstructed.",
                                "Search-corrected bootstrap is an approximate diagnostic, not full correction of all prior research.",
                                "V108/V111 directly score expected payout; their separate probability displays are not fitted win predictions."]}
    write_json(root / "protocol.json", protocol)
    progress = []
    dev = run_windows(records, DEV_WINDOWS, root, "development", progress)
    development = {}
    development_rows = {}
    for key, (_, kind, description) in EXPERIMENTS.items():
        result, rows = evaluate_policy(dev[key], kind, POLICY, 370)
        result["gate"] = gate(result["summary"], result["folds"], "development")
        result["description"] = description
        development[key] = result
        development_rows[key] = rows
        print(json.dumps({"trial": key, "stage": "development", "tickets": result["summary"]["tickets"],
                          "roi": result["summary"]["roi"]}, ensure_ascii=False), flush=True)
    champion = max(development, key=lambda k: comparison_key(development[k]))
    frozen = {"fixed_policy": POLICY, "development_champion": champion, "methods": development,
              "selection_rule": "At least 20 tickets per dev window first, then highest worst-window ROI, then lower bound.",
              "created_before_2026_evaluation": True}
    write_json(root / "frozen_decision.json", frozen)
    frozen_hash = sha256(root / "frozen_decision.json")
    exploratory = run_windows(records, EVAL_WINDOWS, root, "exploratory_2026", progress)
    supplement = run_windows(records, SUPPLEMENT, root, "sparse_september", progress)
    report = {"protocol": protocol, "development_champion": champion, "frozen_decision_sha256": frozen_hash,
              "trials": {}, "environment": {"numpy": np.__version__, "scipy": scipy.__version__, "sklearn": sklearn.__version__}}
    for key, (_, kind, description) in EXPERIMENTS.items():
        result, rows = evaluate_policy(exploratory[key], kind, POLICY, 20)
        result["gate"] = gate(result["summary"], result["folds"], "exploratory")
        result["monthly"] = {month: summarize([r for r in rows if r["race_date"].startswith(month)], bootstrap=False)
                             for month in sorted({r["race_date"][:7] for r in rows})}
        extra, _ = evaluate_policy(supplement[key], kind, POLICY, 20)
        passed = development[key]["gate"]["passed"] and result["gate"]["passed"]
        report["trials"][key] = {"description": description, "bet_type": kind, "development": development[key],
                                 "exploratory_2026": result, "supplement": extra, "candidate_gate_passed": passed,
                                 "descriptive_slices": {"development": descriptive_slices(development_rows[key]),
                                                        "exploratory": descriptive_slices(rows)}}
        write_json(root / f"{key}_tickets.json", {"policy": POLICY, "development": development_rows[key], "exploratory": rows})
        print(json.dumps({"trial": key, "stage": "exploratory", "tickets": result["summary"]["tickets"],
                          "roi": result["summary"]["roi"], "gate": passed}), flush=True)
    final = fit_suite(records, MONTHS)
    final.update(development_champion=champion, fixed_policy=POLICY,
                 candidate_gate_passed={k: v["candidate_gate_passed"] for k, v in report["trials"].items()})
    final_path = root / "second_ten_suite.joblib"
    joblib.dump(final, final_path)
    reloaded = joblib.load(final_path)
    before, after = score_suite(final, records[-1]), score_suite(reloaded, records[-1])
    for key in before:
        np.testing.assert_allclose(before[key]["probability"], after[key]["probability"])
        np.testing.assert_allclose(before[key]["projected_return"], after[key]["projected_return"])
    save_predictions(root / "predictions.jsonl.gz", {"development": dev, "exploratory": exploratory, "supplement": supplement})
    for year, a in audit["source"]["years"].items():
        for name, info in a["hashes"].items():
            if sha256(args.data_root / year / name) != info["sha256"]:
                raise ValueError("source changed during run")
        if sha256(args.data_root / year / "manifest.json") != a["manifest_sha256"]:
            raise ValueError("manifest changed during run")
    assert sha256(root / "frozen_decision.json") == frozen_hash
    source = root / "source"
    source.mkdir()
    hashes = {}
    for name in ("jra_second_ten_model.py", "evaluate_jra_second_ten.py", "score_jra_second_ten.py",
                 "jra_ten_trials_model.py", "evaluate_jra_ten_trials.py", "jra_v91_model.py",
                 "evaluate_jra_v91.py", "evaluate_jra_o1o2_movement.py"):
        path = Path(__file__).with_name(name)
        shutil.copyfile(path, source / name)
        hashes[name] = sha256(path)
    report.update(input_hashes_unchanged=True, decision_unchanged=True, source_hashes=hashes,
                  final_artifact={"file": final_path.name, "sha256": sha256(final_path),
                                  "training_races": len(records), "training_max_date": final["training_max_date"]})
    write_json(root / "report.json", report)
    write_json(root / "summary.json", {"development_champion": champion,
        "trials": {k: {"development": v["development"]["summary"], "exploratory": v["exploratory_2026"]["summary"],
                        "passed": v["candidate_gate_passed"]} for k, v in report["trials"].items()}})
    print(json.dumps({"complete": True, "methods": len(EXPERIMENTS), "passed": [k for k, v in report["trials"].items() if v["candidate_gate_passed"]]}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data/training/jra_o1o2_asof_v1"))
    parser.add_argument("--output-dir", type=Path, default=Path(".workstate/jra-srb/jra-second-ten-nosummer-v1"))
    with threadpool_limits(limits=1):
        run(parser.parse_args())
