from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import UTC, datetime
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Iterable

from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler

from jra_srb.jra_history_dataset import build_history_dataset


POLICY_VERSION = "history_win_ev_revalidation_v1"
GRID = {
    "min_expected_return": (1.05, 1.10, 1.20),
    "min_market_edge": (0.02, 0.03, 0.05),
    "max_win_odds": (20.0, 30.0, 50.0),
    "max_model_rank": (1, 3, 5),
    "min_history_starts": (2, 5),
}
ODDS_BANDS = (
    (0.0, 2.0, "lt_2"),
    (2.0, 5.0, "2_to_lt_5"),
    (5.0, 10.0, "5_to_lt_10"),
    (10.0, 20.0, "10_to_lt_20"),
    (20.0, 30.0, "20_to_lt_30"),
    (30.0, 50.0, "30_to_lt_50"),
    (50.0, math.inf, "ge_50"),
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_value(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def load_revalidation_rows(
    db_path: Path, from_date: str, to_date: str
) -> tuple[list[dict], dict[str, dict]]:
    """Return race IDs that have final odds for every non-cancelled runner."""
    path = db_path.resolve()
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            with normal as (
                select r.race_id, r.race_date, r.course, r.surface, r.race_name
                from races r
                where r.race_date between ? and ? and length(r.race_id) = 12
                  and substr(r.race_id, 9, 2) between '01' and '10'
                  and r.source like 'https://www.jra.go.jp/%'
                  and coalesce(r.race_name, '') not like '%新馬%'
                  and coalesce(r.race_name, '') not like '%メイクデビュー%'
                  and coalesce(r.race_name, '') not like '%障害%'
            ), valid_race as (
                select n.*
                from normal n
                where exists(select 1 from payouts p where p.race_id=n.race_id and p.bet_type in ('win', '単勝') and p.payout is not null)
                  and (select count(*) from runners ru where ru.race_id=n.race_id) =
                      (select count(*) from netkeiba_race_mappings m join netkeiba_result_entries ne on ne.netkeiba_race_id=m.netkeiba_race_id where m.jra_race_id=n.race_id)
                  and (select count(*) from result_entries re where re.race_id=n.race_id) =
                      (select count(*) from result_entries re join netkeiba_race_mappings m on m.jra_race_id=re.race_id join netkeiba_result_entries ne on ne.netkeiba_race_id=m.netkeiba_race_id and ne.horse_no=re.horse_no where re.race_id=n.race_id and ne.win_odds > 0)
            )
            select vr.race_id, vr.race_date, vr.course, vr.surface, re.horse_no, ne.win_odds,
                   re.rank, p.payout as win_payout
            from valid_race vr
            join result_entries re on re.race_id=vr.race_id
            join netkeiba_race_mappings m on m.jra_race_id=vr.race_id
            join netkeiba_result_entries ne on ne.netkeiba_race_id=m.netkeiba_race_id and ne.horse_no=re.horse_no
            left join payouts p on p.race_id=vr.race_id and p.bet_type in ('win', '単勝') and p.combination=re.horse_no
            order by vr.race_date, vr.race_id, cast(re.horse_no as integer)
            """,
            (from_date, to_date),
        ).fetchall()
    metadata: dict[str, dict] = {}
    for row in rows:
        metadata.setdefault(
            str(row["race_id"]),
            {
                "race_date": row["race_date"],
                "course": row["course"],
                "surface": row["surface"],
                "odds": {},
                "payout": 0,
            },
        )
        metadata[str(row["race_id"])]["odds"][str(row["horse_no"])] = float(
            row["win_odds"]
        )
        if row["rank"] == 1 and row["win_payout"] is not None:
            metadata[str(row["race_id"])]["payout"] = int(row["win_payout"])
    return [dict(row) for row in rows], metadata


def split_dates(race_metadata: dict[str, dict]) -> dict[str, list[str]]:
    by_date: dict[str, int] = defaultdict(int)
    for value in race_metadata.values():
        by_date[value["race_date"]] += 1
    dates = sorted(by_date)
    if len(dates) < 3:
        raise ValueError("at least three race dates are required")
    total = sum(by_date.values())
    first_boundary = _boundary(dates, by_date, total * 0.70)
    second_boundary = _boundary(dates, by_date, total * 0.85, start=first_boundary + 1)
    return {
        "train": dates[: first_boundary + 1],
        "calibration": dates[first_boundary + 1 : second_boundary + 1],
        "external": dates[second_boundary + 1 :],
    }


def _boundary(
    dates: list[str], by_date: dict[str, int], target: float, start: int = 0
) -> int:
    running = sum(by_date[day] for day in dates[:start])
    for index in range(start, len(dates) - 1):
        running += by_date[dates[index]]
        if running >= target:
            return index
    raise ValueError("time split produced an empty partition")


def predict(
    records: list[dict], date_sets: dict[str, list[str]]
) -> tuple[dict, list[dict]]:
    train_dates = set(date_sets["train"])
    train = [row for row in records if row["race_date"] in train_dates]
    if not train:
        raise ValueError("training partition is empty")
    scaler = StandardScaler().fit([row["features"] for row in train])
    model = LogisticRegression(max_iter=1000, solver="lbfgs").fit(
        scaler.transform([row["features"] for row in train]),
        [row["label_win"] for row in train],
    )
    probabilities = model.predict_proba(
        scaler.transform([row["features"] for row in records])
    )[:, 1]
    artifact = {
        "model_version": "jra-history-logistic-v1-revalidation",
        "policy_version": POLICY_VERSION,
        "trained_through": max(train_dates),
        "training_runner_rows": len(train),
        "training_races": len({row["race_id"] for row in train}),
        "scaler": {"mean": scaler.mean_.tolist(), "scale": scaler.scale_.tolist()},
        "intercept": float(model.intercept_[0]),
        "coefficients": model.coef_[0].tolist(),
    }
    artifact["artifact_hash"] = sha256_value(artifact)
    return artifact, [
        {**row, "raw_win_probability": float(probability)}
        for row, probability in zip(records, probabilities)
    ]


def enrich_predictions(rows: list[dict], race_metadata: dict[str, dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if row["race_id"] in race_metadata:
            grouped[row["race_id"]].append(row)
    enriched: list[dict] = []
    for race_id, runners in grouped.items():
        odds = race_metadata[race_id]["odds"]
        raw_total = sum(row["raw_win_probability"] for row in runners)
        market_raw = {number: 1 / value for number, value in odds.items()}
        market_total = sum(market_raw.values())
        for row in runners:
            horse_no = row["horse_no"]
            enriched.append(
                {
                    **row,
                    "race_normalized_probability": row["raw_win_probability"]
                    / raw_total
                    if raw_total
                    else 0.0,
                    "market_probability_raw": market_raw[horse_no],
                    "market_probability_normalized": market_raw[horse_no] / market_total
                    if market_total
                    else 0.0,
                    "win_odds": odds[horse_no],
                    "win_payout": race_metadata[race_id]["payout"],
                    "history_starts": int(round(math.expm1(row["features"][8]))),
                }
            )
    return enriched


def calibration(rows: list[dict]) -> tuple[dict[str, object], dict[str, object]]:
    labels = [row["label_win"] for row in rows]
    raw = [row["raw_win_probability"] for row in rows]
    market = [row["market_probability_normalized"] for row in rows]
    platt_model = LogisticRegression(max_iter=1000, solver="lbfgs").fit(
        [[value] for value in raw], labels
    )
    isotonic_model = IsotonicRegression(out_of_bounds="clip").fit(raw, labels)
    platt = platt_model.predict_proba([[value] for value in raw])[:, 1].tolist()
    isotonic = isotonic_model.predict(raw).tolist()
    for row, platt_value, isotonic_value in zip(rows, platt, isotonic):
        row["platt_probability"] = float(platt_value)
        row["isotonic_probability"] = float(isotonic_value)
    methods = {"raw": raw, "platt": platt, "isotonic": isotonic, "market": market}
    metrics = {
        name: calibration_metrics(rows, values) for name, values in methods.items()
    }
    eligible = [
        name
        for name in ("platt", "isotonic")
        if metrics[name]["brier"] <= metrics["raw"]["brier"]
        and metrics[name]["log_loss"] <= metrics["raw"]["log_loss"]
        and metrics[name]["ece_bins_established"]
    ]
    return {"metrics": metrics, "eligible_probability_methods": eligible}, {
        "platt": platt_model,
        "isotonic": isotonic_model,
    }


def calibration_metrics(rows: list[dict], probabilities: list[float]) -> dict:
    labels = [row["label_win"] for row in rows]
    ordered = sorted(zip(probabilities, labels), key=lambda item: item[0])
    bins = []
    for index in range(10):
        part = ordered[index * len(ordered) // 10 : (index + 1) * len(ordered) // 10]
        if part:
            bins.append(
                {
                    "count": len(part),
                    "mean_probability": sum(item[0] for item in part) / len(part),
                    "win_rate": sum(item[1] for item in part) / len(part),
                }
            )
    ece = sum(
        abs(item["mean_probability"] - item["win_rate"]) * item["count"]
        for item in bins
    ) / len(rows)
    by_band = {}
    for lower, upper, name in ODDS_BANDS:
        pairs = [
            (probability, row["label_win"])
            for row, probability in zip(rows, probabilities)
            if lower <= row["win_odds"] < upper
        ]
        count = len(pairs)
        by_band[name] = {"count": count, "reference_only": count < 100}
        if count:
            values, band_labels = zip(*pairs)
            by_band[name].update(
                {
                    "brier": float(brier_score_loss(band_labels, values)),
                    "log_loss": float(log_loss(band_labels, values, labels=[0, 1])),
                    "mean_probability": sum(values) / count,
                    "win_rate": sum(band_labels) / count,
                }
            )
    return {
        "count": len(rows),
        "brier": float(brier_score_loss(labels, probabilities)),
        "log_loss": float(log_loss(labels, probabilities, labels=[0, 1])),
        "ece_10_equal_frequency": ece,
        "ece_bins_established": len(bins) == 10
        and all(item["count"] >= 100 for item in bins),
        "bins": bins,
        "odds_bands": by_band,
    }


def apply_calibrators(rows: list[dict], models: dict[str, object]) -> None:
    raw = [row["raw_win_probability"] for row in rows]
    platt = models["platt"].predict_proba([[value] for value in raw])[:, 1]
    isotonic = models["isotonic"].predict(raw)
    for row, platt_value, isotonic_value in zip(rows, platt, isotonic):
        row["platt_probability"] = float(platt_value)
        row["isotonic_probability"] = float(isotonic_value)


def policy_candidates(
    rows: list[dict], probability_key: str, config: dict
) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["race_id"]].append(row)
    output = []
    for runners in grouped.values():
        ranked = sorted(
            runners, key=lambda item: (-item[probability_key], item["horse_no"])
        )
        selected = [
            {
                **row,
                "model_rank": rank,
                "expected_return": row[probability_key] * row["win_odds"],
                "market_edge": row[probability_key]
                - row["market_probability_normalized"],
            }
            for rank, row in enumerate(ranked, 1)
            if row["win_odds"] <= config["max_win_odds"]
            and rank <= config["max_model_rank"]
            and row["history_starts"] >= config["min_history_starts"]
            and row[probability_key] * row["win_odds"] >= config["min_expected_return"]
            and row[probability_key] - row["market_probability_normalized"]
            >= config["min_market_edge"]
        ]
        if selected:
            output.append(
                max(
                    selected,
                    key=lambda item: (
                        item["expected_return"],
                        item["market_edge"],
                        -int(item["horse_no"]),
                    ),
                )
            )
    return output


def policy_metrics(candidates: list[dict], evaluated_races: int) -> dict:
    returns = [item["win_payout"] if item["label_win"] else 0 for item in candidates]
    stakes = len(candidates) * 100
    def roi(values: Iterable[int]) -> float:
        values = list(values)
        return sum(values) / (len(values) * 100) if values else 0.0

    balance = peak = 0
    drawdown = losing_streak = max_losing_streak = 0
    for amount in returns:
        balance += amount - 100
        peak = max(peak, balance)
        drawdown = min(drawdown, balance - peak)
        losing_streak = losing_streak + 1 if amount == 0 else 0
        max_losing_streak = max(max_losing_streak, losing_streak)
    by_band = {}
    for lower, upper, name in ODDS_BANDS:
        values = [item for item in candidates if lower <= item["win_odds"] < upper]
        by_band[name] = {
            "count": len(values),
            "hits": sum(item["label_win"] for item in values),
            "roi": sum(
                item["win_payout"] if item["label_win"] else 0 for item in values
            )
            / (len(values) * 100)
            if values
            else 0.0,
        }
    dates = {item["race_date"] for item in candidates}

    def breakdown(key: str) -> dict:
        groups: dict[str, list[dict]] = defaultdict(list)
        for item in candidates:
            groups[item["race_date"][:7] if key == "month" else str(item[key])].append(
                item
            )
        return {
            name: {
                "candidate_count": len(items),
                "hits": sum(item["label_win"] for item in items),
                "roi": sum(
                    item["win_payout"] if item["label_win"] else 0 for item in items
                )
                / (len(items) * 100)
                if items
                else 0.0,
            }
            for name, items in sorted(groups.items())
        }

    return {
        "race_count": evaluated_races,
        "candidate_count": len(candidates),
        "recommendation_rate": len(candidates) / evaluated_races
        if evaluated_races
        else 0.0,
        "hits": sum(item["label_win"] for item in candidates),
        "hit_rate": sum(item["label_win"] for item in candidates) / len(candidates)
        if candidates
        else 0.0,
        "total_stake": stakes,
        "total_return": sum(returns),
        "roi": roi(returns),
        "roi_excluding_max_return": roi(returns[1:]),
        "roi_excluding_top3_returns": roi(returns[3:]),
        "max_return_share": max(returns) / sum(returns) if sum(returns) else 0.0,
        "max_drawdown": -drawdown,
        "max_losing_streak": max_losing_streak,
        "mean_odds": sum(item["win_odds"] for item in candidates) / len(candidates)
        if candidates
        else 0.0,
        "median_odds": sorted(item["win_odds"] for item in candidates)[
            len(candidates) // 2
        ]
        if candidates
        else 0.0,
        "over_30_rate": sum(item["win_odds"] > 30 for item in candidates)
        / len(candidates)
        if candidates
        else 0.0,
        "over_50_rate": sum(item["win_odds"] > 50 for item in candidates)
        / len(candidates)
        if candidates
        else 0.0,
        "candidate_days": len(dates),
        "odds_bands": by_band,
        "by_month": breakdown("month"),
        "by_course": breakdown("course"),
        "by_surface": breakdown("surface"),
    }


def select_policy(
    rows: list[dict], methods: list[str]
) -> tuple[dict | None, list[dict]]:
    comparisons = []
    for method in methods:
        key = f"{method}_probability"
        for expected in GRID["min_expected_return"]:
            for edge in GRID["min_market_edge"]:
                for odds in GRID["max_win_odds"]:
                    for rank in GRID["max_model_rank"]:
                        for starts in GRID["min_history_starts"]:
                            config = {
                                "probability_method": method,
                                "min_expected_return": expected,
                                "min_market_edge": edge,
                                "max_win_odds": odds,
                                "max_model_rank": rank,
                                "min_history_starts": starts,
                                "stake": 100,
                                "max_candidates_per_race": 1,
                            }
                            metrics = policy_metrics(
                                policy_candidates(rows, key, config),
                                len({row["race_id"] for row in rows}),
                            )
                            comparisons.append({"policy": config, "metrics": metrics})
    qualified = [
        item for item in comparisons if item["metrics"]["candidate_count"] >= 200
    ]
    if not qualified:
        return None, comparisons
    return min(
        qualified,
        key=lambda item: (
            -item["metrics"]["roi_excluding_top3_returns"],
            -item["metrics"]["roi_excluding_max_return"],
            item["metrics"]["max_return_share"],
            item["metrics"]["max_drawdown"],
            -item["metrics"]["roi"],
        ),
    ), comparisons


def external_decision(rows: list[dict], policy: dict | None) -> dict:
    if policy is None:
        return {
            "status": "shadow_only",
            "promotion_eligible": False,
            "reason": "校正期間で候補数200件以上の固定方策を選べません",
        }
    candidates = policy_candidates(
        rows, f"{policy['probability_method']}_probability", policy
    )
    metrics = policy_metrics(candidates, len({row["race_id"] for row in rows}))
    checks = {
        "candidate_count": metrics["candidate_count"] >= 100,
        "roi": metrics["roi"] >= 1.0,
        "roi_excluding_max": metrics["roi_excluding_max_return"] >= 0.95,
        "roi_excluding_top3": metrics["roi_excluding_top3_returns"] >= 0.90,
        "max_return_share": metrics["max_return_share"] <= 0.25,
        "over_30_rate": metrics["over_30_rate"] <= 0.10,
        "over_50_rate": metrics["over_50_rate"] == 0.0,
        "candidate_days": metrics["candidate_days"] >= 20,
    }
    return {
        "status": "external_passed_live_shadow_required"
        if all(checks.values())
        else "shadow_only",
        "promotion_eligible": all(checks.values()),
        "checks": checks,
        "metrics": metrics,
        "policy": policy,
    }


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\r\n",
    )


def write_markdown(
    path: Path, title: str, common: dict, json_name: str, status: str
) -> None:
    path.write_text(
        "\n".join(
            (
                f"# {title}",
                "",
                f"- 作成日時: {common['created_at']}",
                f"- dataset hash: `{common['dataset_hash']}`",
                f"- model artifact hash: `{common['model_artifact_hash']}`",
                f"- policy version: `{common['policy_version']}`",
                f"- 状態: `{status}`",
                f"- 詳細: `{json_name}`",
                "",
            )
        ),
        encoding="utf-8",
        newline="\r\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Leakage-safe JRA history win-EV revalidation."
    )
    parser.add_argument("--db", type=Path, default=Path("data/db/analysis.sqlite"))
    parser.add_argument("--from-date", default="2025-01-01")
    parser.add_argument("--to-date", default="2026-05-31")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(".workstate/jra-srb/jra-win-ev-revalidation/artifacts"),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _, race_metadata = load_revalidation_rows(args.db, args.from_date, args.to_date)
    all_records, _ = build_history_dataset(args.db)
    records = [row for row in all_records if row["race_id"] in race_metadata]
    dates = split_dates(race_metadata)
    artifact, predicted = predict(records, dates)
    enriched = enrich_predictions(predicted, race_metadata)
    calibration_rows = [
        row for row in enriched if row["race_date"] in set(dates["calibration"])
    ]
    external_rows = [
        row for row in enriched if row["race_date"] in set(dates["external"])
    ]
    calibration_report, calibrators = calibration(calibration_rows)
    apply_calibrators(external_rows, calibrators)
    policy, comparisons = select_policy(
        calibration_rows, calibration_report["eligible_probability_methods"]
    )
    external = external_decision(external_rows, policy["policy"] if policy else None)
    common = {
        "created_at": datetime.now(UTC).isoformat(),
        "dataset_hash": sha256_file(args.db.resolve()),
        "model_artifact_hash": artifact["artifact_hash"],
        "policy_version": POLICY_VERSION,
    }
    split = {
        **common,
        "date_sets": dates,
        "races": {
            name: len(
                {
                    race_id
                    for race_id, value in race_metadata.items()
                    if value["race_date"] in set(values)
                }
            )
            for name, values in dates.items()
        },
    }
    write_json(args.output_dir / "split-metadata.json", split)
    write_json(args.output_dir / "model-artifact.json", artifact)
    with gzip.open(
        args.output_dir / "runner-predictions.jsonl.gz",
        "wt",
        encoding="utf-8",
        newline="\n",
    ) as stream:
        for row in enriched:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    write_json(
        args.output_dir / "calibration-comparison.json",
        {**common, **calibration_report},
    )
    write_markdown(
        args.output_dir / "calibration-comparison.md",
        "確率校正比較",
        common,
        "calibration-comparison.json",
        ",".join(calibration_report["eligible_probability_methods"])
        or "no_adoptable_method",
    )
    write_json(
        args.output_dir / "policy-grid-comparison.json",
        {**common, "comparisons": comparisons},
    )
    write_markdown(
        args.output_dir / "policy-grid-comparison.md",
        "方策グリッド比較",
        common,
        "policy-grid-comparison.json",
        "policy_frozen" if policy else "no_policy",
    )
    write_json(args.output_dir / "frozen-policy.json", {**common, "policy": policy})
    write_json(args.output_dir / "external-evaluation.json", {**common, **external})
    write_markdown(
        args.output_dir / "external-evaluation.md",
        "外部評価",
        common,
        "external-evaluation.json",
        external["status"],
    )
    write_json(
        args.output_dir / "live-shadow.json",
        {
            **common,
            "status": "not_started",
            "reason": "外部評価合格後も30開催日かつ200候補のライブ記録が必要",
        },
    )
    write_markdown(
        args.output_dir / "live-shadow.md",
        "ライブシャドー",
        common,
        "live-shadow.json",
        "not_started",
    )
    write_json(
        args.output_dir / "adoption-decision.json",
        {
            **common,
            "ticket_status": "shadow_only",
            "external": external,
            "reason": "自動昇格は禁止。live-shadow合格と採用レポートの両方が必要",
        },
    )
    write_markdown(
        args.output_dir / "adoption-decision.md",
        "最終採用判定",
        common,
        "adoption-decision.json",
        "shadow_only",
    )
    print(f"REVALIDATION_STATUS={external['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
