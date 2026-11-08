"""Audit the immutable 2024-26 dataset and rebuild V91 in a new output directory."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import platform

import joblib
import numpy as np
import scipy
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from evaluate_jra_o1o2_movement import HISTORY_KEYS, history_features, market, payout_map, read_races, sha256
from jra_v91_model import features, fit, forecast, predict

LIMITATIONS = [
    "Historical card identities and start times are unverified for most records.",
    "O1/O2 are reconstructed from publication times after racing; this is not live performance.",
    "2026 was used in prior research and is not an independent unused test set.",
    "Missingness is highly seasonal; these 4400 adopted races do not represent all JRA races.",
    "Adoption requires T-10m and results, so the cohort itself is retrospectively selected.",
    "T-30m expected returns use indicative prices; settlement uses actual final payouts.",
    "History source starts in 2024; early history is incomplete and identities are name-based.",
    "O2 fallback is implemented, but this dataset has no missing T-30m O2 snapshot.",
    "Only win probabilities/tickets are evaluated. Quinella, wide and V90 live rules are not replaced.",
]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def audit_and_load(root):
    audit = {"years": {}, "duplicates": 0}
    for year in (2024, 2025, 2026):
        directory = root / str(year)
        m = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        excluded = []
        for name, info in m["files"].items():
            if sha256(directory / name) != info["sha256"]:
                raise ValueError(f"hash mismatch: {year}/{name}")
        with gzip.open(directory / "excluded.jsonl.gz", "rt", encoding="utf-8") as stream:
            excluded = [json.loads(line) for line in stream]
        reasons = Counter(reason for r in excluded for reason in r["reasons"])
        if len(excluded) != m["excluded_races"] or dict(reasons) != m["excluded_by_reason"]:
            raise ValueError(f"excluded audit mismatch: {year}")
        audit["years"][str(year)] = {
            "adopted": m["adopted_races"], "all": m["all_races"], "excluded": len(excluded),
            "monthly": {k: {a: v[a] for a in ("all", "adopted", "excluded", "excluded_by_reason")}
                        for k, v in m["monthly"].items()},
            "excluded_by_reason": dict(reasons), "hashes": m["files"],
            "manifest_sha256": sha256(directory / "manifest.json"),
            "history_policy": m["history_policy"], "history_source_min_date": m["history_source_min_date"],
        }
    records, seen, months, cards = [], set(), Counter(), Counter()
    missing = 0
    unscored = []
    for race in read_races(root):
        if race["race_id"] in seen:
            raise ValueError(f"duplicate race: {race['race_id']}")
        seen.add(race["race_id"])
        f = features(race)
        if f["unscored_card_keys"]:
            unscored.append({"race_id": race["race_id"], "card_keys": f["unscored_card_keys"],
                             "rule": "Not scored because no matching numeric T-30m odds; nonnumeric O1 evidence required."})
        ranks = {str(k): int(v) for k, v in race["result"]["ranks_by_horse"].items()}
        payouts = payout_map(race["result"]["win_payout_per_100_yen"], "win")
        winners = {k for k, v in ranks.items() if v == 1}
        if not winners or winners != set(payouts) or not winners.issubset(f["keys"]):
            raise ValueError(f"inconsistent winner: {race['race_id']}")
        target = np.array([float(k in winners) / len(winners) for k in f["keys"]])
        pair = market(race["inputs"]["odds"]["T-30m"].get("quinella"), "quinella")
        runners = {str(r["horse_no"]): r for r in race["inputs"]["runners"]}
        pair_total = sum(1 / v for v in pair.values())
        marginal = {k: 0.0 for k in f["keys"]}
        for (a, b), price in pair.items():
            if a in marginal and b in marginal:
                marginal[a] += 1 / price / (2 * pair_total)
                marginal[b] += 1 / price / (2 * pair_total)
        basic = np.asarray([(np.log(f["price"][i]), f["market"][i], *history_features(runners[k]))
                            for i, k in enumerate(f["keys"])])
        cross = np.column_stack((basic, [np.log(max(marginal[k], 1e-12) / f["market"][i])
                                        for i, k in enumerate(f["keys"])]))
        records.append({**f, "race_id": race["race_id"], "race_date": race["race_date"],
                        "surface": race["race"]["surface"], "course": race["race"]["course"],
                        "target": target, "payout": np.asarray([payouts.get(k, 0) for k in f["keys"]]),
                        "basic": basic, "cross": cross})
        months[race["race_date"][:7]] += 1
        cards[race["inputs"]["card_asof_status"]] += 1
        missing += int(not f["o2_complete"])
    for year in audit["years"].values():
        for month, counts in year["monthly"].items():
            if months[month] != counts["adopted"]:
                raise ValueError(f"monthly count mismatch: {month}")
    audit.update(total_races=len(records), o2_incomplete_races=missing, card_status=dict(cards),
                 unscored_card_entries=unscored,
                 history_cutoff_checked=True, t30_announcement_cutoff_checked=True,
                 features_use_t10_or_result=False)
    return sorted(records, key=lambda r: (r["race_date"], r["race_id"])), audit


def losses(records, probabilities):
    return np.array([-float(r["target"] @ np.log(np.maximum(p, 1e-15)))
                     for r, p in zip(records, probabilities, strict=True)])


def metrics(records, probabilities):
    if not records:
        return {"races": 0}
    tickets = []
    for r, p in zip(records, probabilities, strict=True):
        if not np.isfinite(p).all() or (p < 0).any() or abs(p.sum() - 1) > 1e-8:
            raise ValueError("invalid probability simplex")
        candidates = np.where((r["price"] >= 2) & (r["price"] <= 30))[0]
        if len(candidates):
            i = candidates[np.argmax(p[candidates] * r["price"][candidates])]
            if p[i] * r["price"][i] >= 1.05:
                tickets.append({"race_id": r["race_id"], "race_date": r["race_date"],
                                "horse_no": r["keys"][i], "probability": float(p[i]),
                                "odds_t30": float(r["price"][i]), "payout": int(r["payout"][i])})
    returns = sorted(t["payout"] for t in tickets)
    def roi_without(n):
        return sum(returns[:-n]) / (100 * (len(returns) - n)) if len(returns) > n else None
    calibration = []
    flat_p = np.concatenate(probabilities)
    flat_y = np.concatenate([r["target"] for r in records])
    for lo, hi in zip((0, .05, .1, .2, .4), (.05, .1, .2, .4, 1.000001)):
        mask = (flat_p >= lo) & (flat_p < hi)
        calibration.append({"range": [lo, min(hi, 1)], "count": int(mask.sum()),
                            "mean_probability": float(flat_p[mask].mean()) if mask.any() else None,
                            "observed_win_fraction": float(flat_y[mask].mean()) if mask.any() else None})
    return {"races": len(records), "mean_race_log_loss": float(losses(records, probabilities).mean()),
            "race_brier": float(np.mean([np.sum((p-r["target"])**2)
                                          for r, p in zip(records, probabilities, strict=True)])),
            "top1_hit_rate": float(np.mean([r["target"][np.argmax(p)] > 0
                                             for r, p in zip(records, probabilities, strict=True)])),
            "calibration": calibration, "tickets": len(tickets), "hits": sum(v > 0 for v in returns),
            "stake_yen": 100 * len(tickets), "return_yen": sum(returns),
            "roi": sum(returns) / (100 * len(tickets)) if tickets else None,
            "roi_without_max": roi_without(1), "roi_without_top3": roi_without(3),
            "ticket_details": tickets}


def bootstrap(records, values, repeats=1000):
    # Paired differences resampled by race day, preserving all races on that day.
    dates = sorted({r["race_date"] for r in records})
    totals = np.array([sum(v for r, v in zip(records, values, strict=True) if r["race_date"] == d) for d in dates])
    counts = np.array([sum(r["race_date"] == d for r in records) for d in dates])
    draws = np.random.default_rng(91).integers(0, len(dates), size=(repeats, len(dates)))
    estimates = totals[draws].sum(axis=1) / counts[draws].sum(axis=1)
    return {"mean": float(np.mean(values)), "day_blocks": len(dates), "repeats": repeats,
            "ci95": np.quantile(estimates, [.025, .975]).tolist()}


def predict_all(model, records):
    return [predict(model, r) for r in records]


def run(args):
    # Create only a new directory: never overwrite an old research run.
    if args.output_dir.exists():
        raise ValueError(f"output directory already exists: {args.output_dir}")
    records, audit = audit_and_load(args.data_root)
    train = [r for r in records if r["race_date"] <= "2025-02-28"]
    dev = [r for r in records if "2025-09-01" <= r["race_date"] <= "2025-12-31"]
    periods = {"dev_2025": dev,
               "exploratory_2026_h1": [r for r in records if "2026-01-01" <= r["race_date"] <= "2026-06-30"],
               "sparse_2026_jul_sep": [r for r in records if r["race_date"] >= "2026-07-01"]}
    if not train or any(not rs for rs in periods.values()):
        raise ValueError("empty fixed chronological split")
    args.output_dir.mkdir(parents=True)
    report = {"version": "V91", "created_at": datetime.now(timezone.utc).isoformat(),
              "decision_time": "T-30m", "audit": audit, "limitations": LIMITATIONS,
              "environment": {"python": platform.python_version(), "numpy": np.__version__,
                              "scipy": scipy.__version__, "sklearn": sklearn.__version__},
              "selection_rule": "Minimum dev race log loss, fixed candidates; never tune on 2026 ROI.",
              "policy": {"odds_band": [2, 30], "min_projected_return_t30": 1.05,
                         "one_ticket_per_race": True, "stake_yen": 100, "deployment": "shadow_only"},
              "splits": {"train": {"races": len(train), "through": "2025-02-28"},
                         **{k: {"races": len(rs), "min_date": rs[0]["race_date"], "max_date": rs[-1]["race_date"]}
                            for k, rs in periods.items()}}, "candidates": {}, "results": {}}
    models = {}
    for variant in ("market", "temperature", "form", "graph"):
        penalties = (0.01, .1, 1.0) if variant in ("form", "graph") else (.1,)
        for penalty in penalties:
            key = f"{variant}_l2_{penalty}"
            m = fit(train, variant, penalty)
            models[key] = m
            report["candidates"][key] = {"dev_log_loss": float(losses(dev, predict_all(m, dev)).mean()),
                                          "optimizer": m["optimizer"]}
    selected = min(models, key=lambda k: report["candidates"][k]["dev_log_loss"])
    report["selected"] = selected
    best = {v: min((k for k in models if k.startswith(v + "_")),
                   key=lambda k: report["candidates"][k]["dev_log_loss"]) for v in ("form", "graph")}
    comparison = {"market": models["market_l2_0.1"], "selected": models[selected],
                  "V91A_form": models[best["form"]], "V91B_graph": models[best["graph"]]}
    for name, model in comparison.items():
        joblib.dump({**model, "training_max_date": train[-1]["race_date"], "training_races": len(train)},
                    args.output_dir / f"frozen_{name}.joblib")
    baseline_models = {}
    old_report = json.loads((args.legacy_dir / "report.json").read_text(encoding="utf-8"))
    report["legacy_artifact_audit"] = {}
    for v in ("basic", "cross"):
        path = args.legacy_dir / f"{v}.joblib"
        if sha256(path) != old_report["results"][v]["artifact_sha256"]:
            raise ValueError("legacy artifact hash mismatch")
        old = joblib.load(path)
        baseline_models[f"legacy_{v}"] = (old, v)
        m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, solver="lbfgs"))
        m.fit(np.concatenate([r[v] for r in train]), np.concatenate([r["target"] > 0 for r in train]))
        baseline_models[f"refit_{v}"] = (m, v)
        joblib.dump(m, args.output_dir / f"refit_{v}.joblib")
        report["legacy_artifact_audit"][v] = {"sha256": sha256(path), "n_features": int(old.n_features_in_),
                                                "legacy_report_races": old_report["audit"],
                                                "overlap_warning": "Legacy model uses the same historical training period; no independent evaluation claim."}
    predictions = []
    for period, rs in periods.items():
        probs = {name: predict_all(m, rs) for name, m in comparison.items()}
        for name, (m, v) in baseline_models.items():
            ps = [m.predict_proba(r[v])[:, 1] for r in rs]
            probs[name] = [p / p.sum() for p in ps]
        report["results"][period] = {name: metrics(rs, ps) for name, ps in probs.items()}
        report["results"][period]["selected_minus_market_log_loss_day_bootstrap"] = bootstrap(
            rs, losses(rs, probs["selected"]) - losses(rs, probs["market"]))
        for month in sorted({r["race_date"][:7] for r in rs}):
            ix = [i for i, r in enumerate(rs) if r["race_date"].startswith(month)]
            report["results"][period].setdefault("monthly_selected", {})[month] = metrics(
                [rs[i] for i in ix], [probs["selected"][i] for i in ix])
        report["results"][period]["surface_selected"] = {
            surface: metrics([r for r in rs if r["surface"] == surface],
                             [p for r, p in zip(rs, probs["selected"], strict=True) if r["surface"] == surface])
            for surface in sorted({r["surface"] for r in rs})}
        for r, p in zip(rs, probs["selected"], strict=True):
            predictions.append({"race_id": r["race_id"], "race_date": r["race_date"], "period": period,
                                "horse_nos": r["keys"], "probabilities": p.tolist()})
    # Expanding-window 2026 backtests, with hyperparameters frozen by 2025 dev.
    rolling = []
    for start, end in (("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30"),
                       ("2026-07-01", "2026-09-26")):
        prior = [r for r in records if r["race_date"] < start]
        rs = [r for r in records if start <= r["race_date"] <= end]
        template = models[selected]
        m = fit(prior, template["variant"], template["penalty"])
        selected_probs = predict_all(m, rs)
        rolling.append({"start": start, "end": end, "train_races": len(prior),
                        "train_max_date": prior[-1]["race_date"],
                        "selected": metrics(rs, selected_probs), "market": metrics(rs, [r["market"] for r in rs]),
                        "paired_log_loss_ci": bootstrap(rs, losses(rs, selected_probs) - losses(rs, [r["market"] for r in rs]))})
    report["expanding_window_2026"] = rolling
    # Fit all-data shadow artifacts only after completing frozen backtests.
    artifacts = {}
    for name, key in (("V91A", best["form"]), ("V91B", best["graph"]), ("V91_selected", selected)):
        template = models[key]
        final = fit(records, template["variant"], template["penalty"])
        final.update(training_max_date=records[-1]["race_date"], training_races=len(records),
                     selected_by="2025 dev log loss", source_hashes={y: a["hashes"] for y, a in audit["years"].items()},
                     limitations=LIMITATIONS)
        path = args.output_dir / f"{name}.joblib"
        joblib.dump(final, path)
        loaded = joblib.load(path)
        np.testing.assert_allclose(predict(loaded, records[-1]), predict(final, records[-1]))
        artifacts[name] = {"file": path.name, "sha256": sha256(path), "variant": final["variant"],
                           "penalty": final["penalty"], "training_races": len(records),
                           "standardized_coefficients": dict(zip([final["feature_names"][i] for i in final["columns"]],
                                                                   final["coef"].tolist(), strict=True))}
    report["artifacts"] = artifacts
    with gzip.open(args.output_dir / "frozen_predictions.jsonl.gz", "wt", encoding="utf-8") as stream:
        for row in predictions:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    # Verify input hashes again after fitting; no original DB is opened by this script.
    for year in (2024, 2025, 2026):
        for name, info in audit["years"][str(year)]["hashes"].items():
            if sha256(args.data_root / str(year) / name) != info["sha256"]:
                raise ValueError("input changed during research")
        if sha256(args.data_root / str(year) / "manifest.json") != audit["years"][str(year)]["manifest_sha256"]:
            raise ValueError("manifest changed during research")
    report["input_hashes_unchanged_after_training"] = True
    report["script_hashes"] = {p.name: sha256(p) for p in (Path(__file__), Path(__file__).with_name("jra_v91_model.py"))}
    write_json(args.output_dir / "report.json", report)
    summary = {"selected": selected, "races": len(records), "artifact_dir": str(args.output_dir),
               "scores": {period: {name: {k: value[k] for k in ("mean_race_log_loss", "top1_hit_rate", "tickets", "roi")}
                                    for name, value in result.items() if "mean_race_log_loss" in value}
                          for period, result in report["results"].items()}}
    write_json(args.output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data/training/jra_o1o2_asof_v1"))
    parser.add_argument("--legacy-dir", type=Path, default=Path(".workstate/jra-srb/jra-o1o2-cross-pool-v1"))
    parser.add_argument("--output-dir", type=Path, default=Path(".workstate/jra-srb/jra-v91-market-residual-v1"))
    with threadpool_limits(limits=1):
        run(parser.parse_args())
