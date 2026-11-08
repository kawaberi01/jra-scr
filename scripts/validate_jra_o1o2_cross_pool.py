"""Validate frozen O1/O2 cross-pool models without fitting or policy tuning."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
import math
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from evaluate_jra_o1o2_cross_pool import samples
from evaluate_jra_o1o2_movement import market, read_races, sha256


ODDS_BAND = (2.0, 30.0)
MIN_EXPECTED_RETURN = 1.05
BOOTSTRAP_DRAWS = 3000


def grouped_scores(rows: list[dict], model_dir: Path) -> list[dict]:
    models = {name: joblib.load(model_dir / f"{name}.joblib") for name in ("basic", "cross")}
    raw = {
        name: models[name].predict_proba(np.asarray([row[name] for row in rows]))[:, 1]
        for name in models
    }
    raw["market"] = np.asarray([row["market_probability"] for row in rows])
    groups: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        groups[row["race_id"]].append(index)
    result = []
    for race_id, indices in groups.items():
        race_rows = [rows[index] for index in indices]
        winner_count = sum(row["label"] for row in race_rows)
        if winner_count < 1:
            raise ValueError(f"winner missing from market: {race_id}")
        record = {
            "race_id": race_id,
            "date": race_rows[0]["race_date"],
            "winning_horses": winner_count,
            "turf_sprint": race_rows[0]["surface"] == "turf" and race_rows[0]["distance"] <= 1400,
            "scores": {},
        }
        labels = np.asarray([row["label"] for row in race_rows])
        for name, values in raw.items():
            probability = np.asarray([values[index] for index in indices], dtype=float)
            probability /= probability.sum()
            winner_probability = float(probability[labels == 1].sum())
            candidates = [
                (local_index, float(probability[local_index] * row["price"]))
                for local_index, row in enumerate(race_rows)
                if ODDS_BAND[0] <= row["price"] <= ODDS_BAND[1]
            ]
            choice = max(candidates, key=lambda item: item[1]) if candidates else None
            ticket = race_rows[choice[0]] if choice and choice[1] >= MIN_EXPECTED_RETURN else None
            record["scores"][name] = {
                "log_loss": -math.log(max(winner_probability, 1e-12)),
                "brier": float(np.square(probability - labels / winner_count).sum()),
                "top1_hit": int(labels[int(np.argmax(probability))]),
                "stake": 100 if ticket else 0,
                "return": ticket["payout"] if ticket else 0,
                "ticket_odds": ticket["price"] if ticket else None,
            }
        result.append(record)
    return result


def percentile_interval(draws: np.ndarray) -> list[float] | None:
    finite = draws[np.isfinite(draws)]
    if not len(finite):
        return None
    return [round(float(value), 5) for value in np.quantile(finite, (0.025, 0.975))]


def summarize_group(records: list[dict], seed: int) -> dict:
    if not records:
        return {"races": 0}
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(records), size=(BOOTSTRAP_DRAWS, len(records)))
    by_day: dict[str, list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        by_day[record["date"]].append(index)
    days = list(by_day.values())
    day_draws = rng.integers(0, len(days), size=(BOOTSTRAP_DRAWS, len(days)))
    result: dict = {"races": len(records), "models": {}, "paired_log_loss_improvement": {}}
    for name in ("market", "basic", "cross"):
        scores = [record["scores"][name] for record in records]
        loss = np.asarray([score["log_loss"] for score in scores])
        brier = np.asarray([score["brier"] for score in scores])
        hit = np.asarray([score["top1_hit"] for score in scores])
        stakes = np.asarray([score["stake"] for score in scores])
        returns = np.asarray([score["return"] for score in scores])
        total_stake = int(stakes.sum())
        bootstrap_stake = stakes[indices].sum(axis=1)
        bootstrap_return = returns[indices].sum(axis=1)
        bootstrap_roi = np.divide(
            bootstrap_return, bootstrap_stake,
            out=np.full(BOOTSTRAP_DRAWS, np.nan), where=bootstrap_stake > 0,
        )
        daily_stake = np.asarray([stakes[day].sum() for day in days])
        daily_return = np.asarray([returns[day].sum() for day in days])
        daily_bootstrap_stake = daily_stake[day_draws].sum(axis=1)
        daily_bootstrap_roi = np.divide(
            daily_return[day_draws].sum(axis=1), daily_bootstrap_stake,
            out=np.full(BOOTSTRAP_DRAWS, np.nan), where=daily_bootstrap_stake > 0,
        )
        result["models"][name] = {
            "mean_race_log_loss": round(float(loss.mean()), 6),
            "mean_race_brier": round(float(brier.mean()), 6),
            "top1_hit_rate": round(float(hit.mean()), 5),
            "tickets": int(np.count_nonzero(stakes)),
            "hits": int(np.count_nonzero(returns)),
            "stake_yen": total_stake,
            "return_yen": int(returns.sum()),
            "roi": round(float(returns.sum() / total_stake), 5) if total_stake else None,
            "roi_bootstrap_ci95": percentile_interval(bootstrap_roi),
            "roi_day_block_bootstrap_ci95": percentile_interval(daily_bootstrap_roi),
        }
    cross_loss = np.asarray([record["scores"]["cross"]["log_loss"] for record in records])
    for baseline in ("market", "basic"):
        base_loss = np.asarray([record["scores"][baseline]["log_loss"] for record in records])
        gain = base_loss - cross_loss
        draws = gain[indices].mean(axis=1)
        daily_gain = np.asarray([gain[day].sum() for day in days])
        daily_count = np.asarray([len(day) for day in days])
        day_draw_gain = daily_gain[day_draws].sum(axis=1) / daily_count[day_draws].sum(axis=1)
        result["paired_log_loss_improvement"][f"cross_vs_{baseline}"] = {
            "mean": round(float(gain.mean()), 6),
            "bootstrap_ci95": percentile_interval(draws),
            "day_block_bootstrap_ci95": percentile_interval(day_draw_gain),
            "bootstrap_probability_positive": round(float(np.mean(draws > 0)), 4),
        }
    return result


def selected_odds_bands(records: list[dict]) -> dict:
    bands = ((2.0, 5.0), (5.0, 10.0), (10.0, 30.000001))
    result = {}
    for lower, upper in bands:
        tickets = [
            record["scores"]["cross"] for record in records
            if record["scores"]["cross"]["ticket_odds"] is not None
            and lower <= record["scores"]["cross"]["ticket_odds"] < upper
        ]
        stake = sum(ticket["stake"] for ticket in tickets)
        returned = sum(ticket["return"] for ticket in tickets)
        result[f"{lower:g}_to_{upper:g}"] = {
            "tickets": len(tickets),
            "hits": sum(ticket["return"] > 0 for ticket in tickets),
            "stake_yen": stake,
            "return_yen": returned,
            "roi": round(returned / stake, 5) if stake else None,
        }
    return result


def audit_asof(root: Path) -> dict:
    statuses = Counter()
    evidence = Counter()
    issues = Counter()
    ages = []
    deadheat_races = 0
    for race in read_races(root):
        statuses[(race["race"].get("start_time_status"), race["inputs"].get("card_asof_status"))] += 1
        cutoff = datetime.fromisoformat(race["race"]["start_at"]) - timedelta(minutes=30)
        history_as_of = datetime.fromisoformat(race["inputs"]["history_as_of"])
        if history_as_of.date() > datetime.fromisoformat(race["race"]["start_at"]).date():
            issues["history_after_race_date"] += 1
        odds = race["inputs"]["odds"]["T-30m"]
        win = market(odds["win"], "win")
        pairs = market(odds["quinella"], "quinella")
        if len(pairs) != len(win) * (len(win) - 1) // 2:
            issues["incomplete_quinella_pair_matrix"] += 1
        for kind in ("win", "quinella"):
            item = odds[kind]
            evidence[item.get("availability_evidence")] += 1
            ages.append(float(item["age_minutes"]))
            if datetime.fromisoformat(item["announced_at"]) > cutoff:
                issues[f"{kind}_announced_after_cutoff"] += 1
            if not item.get("raw_sha256") or not item.get("raw_path"):
                issues[f"{kind}_missing_raw_reference"] += 1
            if item.get("retrieved_at"):
                retrieval = datetime.fromisoformat(item["retrieved_at"].replace("Z", "+00:00"))
                if retrieval > datetime.fromisoformat(race["race"]["start_at"]):
                    issues[f"{kind}_retrieved_after_race"] += 1
        if odds["win"]["announced_at"] != odds["quinella"]["announced_at"]:
            issues["o1_o2_announcement_mismatch"] += 1
        rank_one = {str(number) for number, rank in race["result"]["ranks_by_horse"].items() if rank == 1}
        paid_winners = {str(item["horse_no"]) for item in race["result"]["win_payout_per_100_yen"]}
        if rank_one != paid_winners:
            issues["win_payout_rank_mismatch"] += 1
        deadheat_races += len(paid_winners) > 1
    return {
        "races": sum(statuses.values()),
        "deadheat_races": deadheat_races,
        "card_and_start_status": [{"start": a, "card": b, "races": n} for (a, b), n in statuses.most_common()],
        "availability_evidence": dict(evidence),
        "t30_age_minutes": {"min": min(ages), "median": float(np.median(ages)), "p95": float(np.quantile(ages, 0.95)), "max": max(ages)},
        "issues_or_constraints": dict(issues),
    }


def manifest_coverage(root: Path) -> dict:
    output = {}
    for year in (2023, 2024, 2025, 2026):
        manifest = json.loads((root / str(year) / "manifest.json").read_text(encoding="utf-8"))
        all_races = int(manifest["all_races"])
        adopted = int(manifest["adopted_races"])
        output[str(year)] = {
            "all_races": all_races,
            "adopted_races": adopted,
            "coverage": round(adopted / all_races, 5) if all_races else None,
            "excluded_by_reason": manifest["excluded_by_reason"],
            "monthly": {
                month: {"all": item["all"], "adopted": item["adopted"]}
                for month, item in manifest["monthly"].items()
            },
        }
    return output


def ablation_train_only(data: dict[str, list[dict]]) -> dict:
    """Isolate the O2 feature from historical-card features."""
    train = data["train"]
    labels = np.asarray([row["label"] for row in train])
    feature_sets = {
        "o1_only": lambda row: row["basic"][:2],
        "o1_plus_o2": lambda row: (*row["basic"][:2], row["cross"][-1]),
    }
    models = {}
    for name, select in feature_sets.items():
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, solver="lbfgs"))
        model.fit(np.asarray([select(row) for row in train]), labels)
        models[name] = model
    result = {}
    for period in ("dev", "holdout", "later"):
        rows = data[period]
        groups: dict[str, list[int]] = defaultdict(list)
        for index, row in enumerate(rows):
            groups[row["race_id"]].append(index)
        period_losses = {}
        for name, select in feature_sets.items():
            predicted = models[name].predict_proba(np.asarray([select(row) for row in rows]))[:, 1]
            losses = []
            for indices in groups.values():
                probabilities = predicted[indices]
                probabilities /= probabilities.sum()
                winner_probability = sum(
                    probabilities[local_index]
                    for local_index, index in enumerate(indices) if rows[index]["label"]
                )
                losses.append(-math.log(max(winner_probability, 1e-12)))
            period_losses[name] = np.asarray(losses)
        gain = period_losses["o1_only"] - period_losses["o1_plus_o2"]
        rng = np.random.default_rng(4400 + len(rows))
        indices = rng.integers(0, len(gain), size=(BOOTSTRAP_DRAWS, len(gain)))
        result[period] = {
            "races": len(groups),
            "mean_race_log_loss": {name: round(float(values.mean()), 6) for name, values in period_losses.items()},
            "o2_feature_gain": round(float(gain.mean()), 6),
            "o2_feature_gain_bootstrap_ci95": percentile_interval(gain[indices].mean(axis=1)),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=Path("data/training/jra_o1o2_asof_v1"))
    parser.add_argument("--model-dir", type=Path, default=Path(".workstate/jra-srb/jra-o1o2-cross-pool-v1"))
    args = parser.parse_args()
    data, sample_audit = samples(args.data_root, include_later=True)
    report = {
        "purpose": "frozen-model validation; no refitting or betting-policy tuning",
        "model_sha256": {name: sha256(args.model_dir / f"{name}.joblib") for name in ("basic", "cross")},
        "sample_audit": sample_audit,
        "manifest_coverage": manifest_coverage(args.data_root),
        "source_asof_audit": audit_asof(args.data_root),
        "o1_o2_feature_ablation": ablation_train_only(data),
        "periods": {},
        "monthly": {},
        "limitations": [
            "2026 January-June was already examined and is not a pristine holdout",
            "2026 July-September has only 19 races",
            "historical cards and start times are mostly unverified",
            "published odds were recovered after racing",
            "bootstrap intervals reflect race sampling only, not source-data uncertainty",
        ],
    }
    for period, name, seed in (
        ("dev", "2025_september_december", 202509),
        ("holdout", "2026_january_june_exploratory", 202601),
        ("later", "2026_july_september_fresh_small", 202607),
    ):
        scored = grouped_scores(data[period], args.model_dir)
        report["periods"][name] = {
            "all": summarize_group(scored, seed),
            "turf_sprint": summarize_group([r for r in scored if r["turf_sprint"]], seed + 1),
            "selected_odds_bands": selected_odds_bands(scored),
        }
        if period == "dev":
            for month in sorted({record["date"][:7] for record in scored}):
                report["monthly"][month] = summarize_group(
                    [record for record in scored if record["date"].startswith(month)], seed + int(month[-2:])
                )
    path = args.model_dir / "validation_report.json"
    path.write_bytes((json.dumps(report, ensure_ascii=False, indent=2).replace("\n", "\r\n") + "\r\n").encode("utf-8"))
    print(json.dumps({
        "asof": report["source_asof_audit"],
        "periods": {name: {
            key: {"races": value["races"], "cross": value.get("models", {}).get("cross"),
                  "cross_vs_market": value.get("paired_log_loss_improvement", {}).get("cross_vs_market")}
            for key, value in period.items() if key in ("all", "turf_sprint")
        } for name, period in report["periods"].items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
