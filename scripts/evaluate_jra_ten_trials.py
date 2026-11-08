"""Run ten prespecified hypotheses with chronological policy selection."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from evaluate_jra_o1o2_movement import payout_map, read_races, sha256
from evaluate_jra_v91 import audit_and_load
from jra_ten_trials_model import EXPERIMENTS, GROUPS, THRESHOLDS, fit_suite, pick_ticket, prepare, score_suite

DEV_WINDOWS = (("2024-04-01", "2024-05-31"), ("2025-01-01", "2025-02-28"), ("2025-09-01", "2025-12-31"))
EVAL_WINDOWS = (("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30"))
SUPPLEMENT = (("2026-09-01", "2026-09-26"),)
BOOTSTRAPS = 20000
SEARCHES = len(EXPERIMENTS) * len(GROUPS) * len(THRESHOLDS)


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_records(root, excluded_months):
    _, source_audit = audit_and_load(root)
    records, excluded = [], Counter()
    for race in read_races(root):
        if int(race["race_date"][5:7]) in excluded_months:
            excluded[race["race_date"][:7]] += 1
            continue
        r = prepare(race)
        ranks = {str(k): int(v) for k, v in race["result"]["ranks_by_horse"].items()}
        winners = {k for k, v in ranks.items() if v == 1}
        payout = payout_map(race["result"]["win_payout_per_100_yen"], "win")
        r["target"] = np.array([float(k in winners) / len(winners) for k in r["keys"]])
        r["payout"] = np.array([payout.get(k, 0) for k in r["keys"]])
        if r["pair"] is not None:
            pair_payout = payout_map(race["result"]["quinella_payout_per_100_yen"], "quinella")
            values = {"-".join(k): v for k, v in pair_payout.items()}
            q = r["pair"]
            if not values or not set(values).issubset(q["keys"]):
                raise ValueError(f"incomplete quinella result {r['race_id']}")
            q["target"] = np.array([float(k in values) / len(values) for k in q["keys"]])
            q["payout"] = np.array([values.get(k, 0) for k in q["keys"]])
        records.append(r)
    audit = {"source": source_audit, "summer_excluded_by_month": dict(sorted(excluded.items())),
             "remaining": len(records), "remaining_by_month": dict(sorted(Counter(r["race_date"][:7] for r in records).items()))}
    return sorted(records, key=lambda r: (r["race_date"], r["race_id"])), audit


def windows(records, definitions):
    return [(start, end, [r for r in records if r["race_date"] < start],
             [r for r in records if start <= r["race_date"] <= end]) for start, end in definitions]


def evaluate_windows(records, definitions, months, root, stage, progress):
    output = {key: [] for key in EXPERIMENTS}
    for start, end, train, test in windows(records, definitions):
        if not train or not test:
            raise ValueError(f"empty window: {start} / {end}")
        assert max(r["race_date"] for r in train) < min(r["race_date"] for r in test)
        suite = fit_suite(train, months, as_of=start)
        model_path = root / "fold_models" / f"{stage}_{start}.joblib"
        joblib.dump(suite, model_path)
        fold = {"stage": stage, "start": start, "end": end, "training_races": len(train),
                "training_max_date": train[-1]["race_date"], "evaluation_races": len(test),
                "artifact_sha256": sha256(model_path)}
        progress.append(fold)
        for r in test:
            scores = score_suite(suite, r)
            for key, (_, kind, _) in EXPERIMENTS.items():
                if key not in scores:
                    continue
                data = r if kind == "win" else r["pair"]
                output[key].append({"record": data, "score": scores[key], "fold": start})
        write_json(root / "progress.json", progress)
        print(json.dumps({"stage": stage, "window": start, "train": len(train), "evaluate": len(test)}, ensure_ascii=False), flush=True)
    return output


def scored_rows(entries, kind, policy):
    rows = []
    for entry in entries:
        r, s = entry["record"], entry["score"]
        p = s["probability"]
        if not np.isfinite(p).all() or abs(p.sum() - 1) > 1e-8:
            raise ValueError("invalid normalized probabilities")
        ticket = pick_ticket(r, s, kind, policy)
        if ticket is not None:
            ticket = {**ticket, "payout": int(r["payout"][ticket["index"]])}
        rows.append({"race_id": r["race_id"], "race_date": r["race_date"], "fold": entry["fold"],
                     "surface": r["surface"], "distance": r["distance"], "course": r["course"],
                     "loss": -float(r["target"] @ np.log(np.maximum(p, 1e-15))), "ticket": ticket})
    return rows


def summarize(rows, correction=1, bootstrap=True):
    tickets = [r for r in rows if r["ticket"] is not None]
    returns = [r["ticket"]["payout"] for r in tickets]
    count = len(tickets)
    spent = count * 100
    equity = np.cumsum([v - 100 for v in returns])
    drawdown = np.max(np.maximum.accumulate(np.r_[0, equity])[1:] - equity) if count else 0
    result = {"races": len(rows), "tickets": count, "bet_days": len({r["race_date"] for r in tickets}),
              "hits": sum(v > 0 for v in returns), "stake_yen": spent, "return_yen": sum(returns),
              "profit_yen": sum(returns) - spent, "roi": sum(returns) / spent if spent else None,
              "mean_race_log_loss": float(np.mean([r["loss"] for r in rows])) if rows else None,
              "roi_without_top3": sum(sorted(returns)[:-3]) / ((count - 3) * 100) if count > 3 else None,
              "max_drawdown_yen": int(drawdown)}
    if bootstrap and count:
        dates = sorted({r["race_date"] for r in rows})
        stakes = Counter(r["race_date"] for r in tickets)
        payouts = Counter()
        for r in tickets:
            payouts[r["race_date"]] += r["ticket"]["payout"]
        denominator = np.array([100 * stakes[d] for d in dates], dtype=float)
        numerator = np.array([payouts[d] for d in dates], dtype=float)
        draws = np.random.default_rng(101).integers(0, len(dates), size=(BOOTSTRAPS, len(dates)))
        den = denominator[draws].sum(axis=1)
        num = numerator[draws].sum(axis=1)
        # A resample with no bets provides no profit evidence; conservatively score 0.
        rois = np.divide(num, den, out=np.zeros_like(num), where=den > 0)
        result.update(roi_ci95=np.quantile(rois, [.025, .975]).tolist(),
                      roi_lower_one_sided=float(np.quantile(rois, .05)),
                      roi_lower_search_adjusted=float(np.quantile(rois, .05 / correction)),
                      bootstrap_day_blocks=len(dates), bootstrap_repeats=BOOTSTRAPS,
                      search_correction=correction)
    else:
        result.update(roi_ci95=None, roi_lower_one_sided=0., roi_lower_search_adjusted=0.)
    return result


def gate(summary, folds, stage):
    min_fold = 20 if stage == "development" else 30
    checks = {
        "at_least_100_tickets": summary["tickets"] >= 100,
        "at_least_20_bet_days": summary["bet_days"] >= 20,
        "roi_at_least_105pct": (summary["roi"] or 0) >= 1.05,
        "without_top3_profitable": (summary["roi_without_top3"] or 0) > 1,
        "search_adjusted_lower_above_100pct": summary["roi_lower_search_adjusted"] > 1,
        "each_fold_sufficient_and_profitable": bool(folds) and all(
            s["tickets"] >= min_fold and (s["roi"] or 0) > 1 for s in folds.values()),
    }
    return {"passed": all(checks.values()), "checks": checks,
            "failed": [key for key, value in checks.items() if not value]}


def evaluate_policy(entries, kind, policy, correction):
    rows = scored_rows(entries, kind, policy)
    summary = summarize(rows, correction)
    folds = {f: summarize([r for r in rows if r["fold"] == f], bootstrap=False) for f in sorted({r["fold"] for r in rows})}
    return {"policy": policy, "summary": summary, "folds": folds}, rows


def selection_key(result):
    s = result["summary"]
    return (s["tickets"] >= 50 and s["bet_days"] >= 10, s["roi_lower_one_sided"], s["tickets"])


def freeze_policies(dev, root):
    output = {}
    all_policies = {}
    for key, (_, kind, description) in EXPERIMENTS.items():
        candidates = []
        for group in GROUPS:
            for threshold in THRESHOLDS:
                policy = {"group": group, "threshold": threshold}
                result, _ = evaluate_policy(dev[key], kind, policy, SEARCHES)
                candidates.append(result)
        best = max(candidates, key=selection_key)
        best["gate"] = gate(best["summary"], best["folds"], "development")
        best["hypothesis"] = description
        best["bet_type"] = kind
        output[key] = best
        all_policies[key] = candidates
        print(json.dumps({"trial": key, "selected_policy": best["policy"],
                          "dev_tickets": best["summary"]["tickets"], "dev_roi": best["summary"]["roi"],
                          "dev_gate": best["gate"]["passed"]}, ensure_ascii=False), flush=True)
    winner = max(output, key=lambda k: (output[k]["gate"]["passed"], *selection_key(output[k])))
    write_json(root / "all_development_policies.json", all_policies)
    frozen = {"created_at": datetime.now(timezone.utc).isoformat(), "selected_before_2026_evaluation": True,
              "development_champion": winner, "experiments": output,
              "selection_rule": "Prioritize >=50 bets/10 days; maximize development one-sided 95% ROI lower bound.",
              "total_policy_candidates": SEARCHES}
    write_json(root / "frozen_policies.json", frozen)
    return frozen


def save_predictions(path, stage_data):
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        for stage, experiments in stage_data.items():
            for key, entries in experiments.items():
                for e in entries:
                    r, s = e["record"], e["score"]
                    stream.write(json.dumps({"stage": stage, "trial": key, "fold": e["fold"],
                                             "race_id": r["race_id"], "race_date": r["race_date"],
                                             "keys": r["keys"], "probability": s["probability"].tolist(),
                                             "projected_return": s["projected_return"].tolist()}, ensure_ascii=False) + "\n")


def run(args):
    if args.output_dir.exists():
        raise ValueError("output directory already exists; select a new output path")
    months = tuple(int(v) for v in args.exclude_months.split(","))
    records, audit = load_records(args.data_root, months)
    root = args.output_dir
    (root / "fold_models").mkdir(parents=True)
    protocol = {"decision_time": "T-30m", "excluded_months": months, "development_windows": DEV_WINDOWS,
                "exploratory_windows": EVAL_WINDOWS, "supplement_windows": SUPPLEMENT,
                "hypotheses": EXPERIMENTS, "groups": GROUPS, "thresholds": THRESHOLDS,
                "bootstrap_repeats": BOOTSTRAPS, "total_policy_candidates": SEARCHES,
                "future_evaluation_required": True, "data_audit": audit}
    write_json(root / "protocol.json", protocol)
    progress = []
    dev = evaluate_windows(records, DEV_WINDOWS, months, root, "development", progress)
    frozen = freeze_policies(dev, root)
    frozen_sha = sha256(root / "frozen_policies.json")
    # All design and policy selection ends here. No subsequent tuning on 2026.
    exploratory = evaluate_windows(records, EVAL_WINDOWS, months, root, "exploratory_2026", progress)
    supplement = evaluate_windows(records, SUPPLEMENT, months, root, "sparse_september", progress)
    report = {"protocol": protocol, "frozen_policies_sha256": frozen_sha, "development_champion": frozen["development_champion"],
              "trials": {}, "limitations": [
                  "2026 is reused exploratory data, never an independent unused test.",
                  "Historical cards/start times mostly unverified; odds reconstructed after racing.",
                  "Bootstrap bounds with search correction are approximate and do not remove selection bias or population missingness.",
                  "A successful historical gate is a candidate only; no real-time forward results exist.",
                  "September has only one adopted race after summer exclusion; supplemental only.",
                  "Policies use T-30m odds; actual final payouts settle returns.",
              ]}
    for key, (_, kind, description) in EXPERIMENTS.items():
        selected = frozen["experiments"][key]
        policy = selected["policy"]
        evaluation, rows = evaluate_policy(exploratory[key], kind, policy, len(EXPERIMENTS))
        evaluation["gate"] = gate(evaluation["summary"], evaluation["folds"], "exploratory")
        evaluation["monthly"] = {m: summarize([r for r in rows if r["race_date"].startswith(m)], bootstrap=False)
                                 for m in sorted({r["race_date"][:7] for r in rows})}
        supplementary, _ = evaluate_policy(supplement[key], kind, policy, len(EXPERIMENTS))
        passed = selected["gate"]["passed"] and evaluation["gate"]["passed"]
        # Additional group diagnostics are descriptive only, never alter the fixed policy.
        descriptive = {}
        for group in GROUPS:
            d, _ = evaluate_policy(exploratory[key], kind, {**policy, "group": group}, SEARCHES)
            descriptive[group] = d["summary"]
        report["trials"][key] = {"hypothesis": description, "bet_type": kind, "development": selected,
                                  "exploratory_2026": evaluation, "supplement": supplementary,
                                  "candidate_gate_passed": passed, "exploratory_descriptive_groups": descriptive}
        write_json(root / f"{key}_tickets.json", {"policy": policy, "rows": rows})
        print(json.dumps({"trial": key, "test_tickets": evaluation["summary"]["tickets"],
                          "test_roi": evaluation["summary"]["roi"], "candidate_gate": passed}, ensure_ascii=False), flush=True)
    final = fit_suite(records, months)
    final.update(policies={key: v["policy"] for key, v in frozen["experiments"].items()},
                 development_champion=frozen["development_champion"],
                 candidate_gate_passed={k: v["candidate_gate_passed"] for k, v in report["trials"].items()},
                 input_hashes={y: a["hashes"] for y, a in audit["source"]["years"].items()})
    joblib.dump(final, root / "ten_trials_suite.joblib")
    loaded = joblib.load(root / "ten_trials_suite.joblib")
    expected, actual = score_suite(final, records[-1]), score_suite(loaded, records[-1])
    for key in expected:
        np.testing.assert_allclose(expected[key]["probability"], actual[key]["probability"])
    save_predictions(root / "predictions.jsonl.gz", {"development": dev, "exploratory": exploratory, "supplement": supplement})
    for year, a in audit["source"]["years"].items():
        for name, info in a["hashes"].items():
            if sha256(args.data_root / year / name) != info["sha256"]:
                raise ValueError("source file changed during training")
        if sha256(args.data_root / year / "manifest.json") != a["manifest_sha256"]:
            raise ValueError("manifest changed during training")
    assert sha256(root / "frozen_policies.json") == frozen_sha
    report.update(input_hashes_unchanged=True, policies_unchanged_after_2026=True,
                  final_model={"file": "ten_trials_suite.joblib", "sha256": sha256(root / "ten_trials_suite.joblib"),
                               "training_races": len(records), "training_max_date": final["training_max_date"]})
    source = root / "source"
    source.mkdir()
    hashes = {}
    for name in ("evaluate_jra_ten_trials.py", "jra_ten_trials_model.py", "score_jra_ten_trials.py",
                 "evaluate_jra_v91.py", "jra_v91_model.py", "evaluate_jra_o1o2_movement.py"):
        path = Path(__file__).with_name(name)
        shutil.copyfile(path, source / name)
        hashes[name] = sha256(path)
    report["source_hashes"] = hashes
    write_json(root / "report.json", report)
    summary = {"development_champion": report["development_champion"], "training_races": len(records),
               "excluded_summer_races": sum(audit["summer_excluded_by_month"].values()),
               "trials": {k: {"policy": v["development"]["policy"],
                               "development": v["development"]["summary"],
                               "exploratory": v["exploratory_2026"]["summary"],
                               "passed": v["candidate_gate_passed"]} for k, v in report["trials"].items()}}
    write_json(root / "summary.json", summary)
    print(json.dumps({"complete": True, "trials": len(report["trials"]),
                      "passed": [k for k, v in report["trials"].items() if v["candidate_gate_passed"]]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data/training/jra_o1o2_asof_v1"))
    parser.add_argument("--output-dir", type=Path, default=Path(".workstate/jra-srb/jra-ten-trials-nosummer-v1"))
    parser.add_argument("--exclude-months", default="6,7,8")
    with threadpool_limits(limits=1):
        run(parser.parse_args())
