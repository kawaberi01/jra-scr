"""概要: R1校正研究の同じ対象でT30/T10馬連価格を比較する。
作成日: 2026-10-18
入力: --run-id、統合SQL研究reader、保存済み選択ペア。
出力: 対象runのodds-movement-audit.json。標準出力は集計のみ。
実行例: uv run --frozen --extra ml python scripts/audit_jra_r1_odds_movement.py --run-id <run-id>
注意事項: SELECTのみ。T10を予測入力に使用せず、校正・選択・既定を変更しない。
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
from itertools import combinations
import json

import numpy as np

from jra_srb.jra_research_artifacts import ROOT, existing_run
from jra_srb.jra_research_contracts import digest, timestamp
from jra_srb.jra_research_features import numeric_market
from jra_srb.jra_research_history import HistoryConfig
from jra_srb.jra_research_r1_live import read_json, require
from jra_srb.jra_research_r1_calibration import PERIODS, in_period, price_band
from jra_srb.jra_research_tipster_experiment import ExperimentMarketReader
from jra_srb.jra_research_tipster_smoke import FIELDS


def statistics(values):
    """価格比の中央値・分位・下落割合を返し、空標本は欠測とする。"""
    if not values:
        return {"pairs": 0, "mean_ratio": None, "median_ratio": None, "ratio_10_90": None, "fraction_decreased": None}
    values = np.asarray(values)
    return {"pairs": len(values), "mean_ratio": float(values.mean()), "median_ratio": float(np.median(values)),
            "ratio_10_90": np.quantile(values, [.1, .9]).tolist(), "fraction_decreased": float(np.mean(values < 1))}


def compare_markets(rows):
    """同じ競走の2時点の価格と公表条件を検証し、ペア別価格を返す。"""
    require(len(rows) == 2 and {r["horizon"] for r in rows} == {"T30", "T10"}, "movement_missing_horizon")
    values = {r["horizon"]: r for r in rows}
    for row in rows:
        require(row["selection_status"] == "selected" and row["parser_version"] == "jv-o1o2-v2"
                and row["content_sha256"] and timestamp(row["announced_at"]) <= timestamp(row["cutoff_at"]), "movement_invalid_market")
    require((timestamp(values["T10"]["cutoff_at"]) - timestamp(values["T30"]["cutoff_at"])).total_seconds() == 1200,
            "movement_cutoff_difference")
    earlier, later = (numeric_market(values[h], "quinella") for h in ("T30", "T10"))
    require(set(earlier) == set(later), "movement_pair_roster_changed")
    horses = sorted({n for pair in earlier for n in pair})
    require(8 <= len(horses) <= 18 and set(earlier) == set(combinations(horses, 2)), "movement_incomplete_pair_graph")
    return earlier, later


def execute(run_id):
    """対象競走を最大100件ずつ照会し、全体と保存候補の価格感応度を集計する。"""
    path = existing_run(run_id)
    manifest, metrics = read_json(path / "manifest.json"), read_json(path / "metrics.json")
    require(manifest["status"] == "complete" and digest(metrics) == manifest["metrics_sha256"], "movement_run_not_verified")
    require(read_json(path / "verification.json")["status"] == "passed", "movement_missing_verification")
    selected = defaultdict(list)
    with gzip.open(path / "predictions.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            selected[row["race_key"]].append(row)
    race_rows = metrics["race_metrics"]
    keys = [r["race_key"] for r in race_rows]
    races = {r["race_key"]: r for r in race_rows}
    values, rejected = {}, []
    query_count = 0
    config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
    with ExperimentMarketReader(config) as reader:
        # 既存経路の版・権限・hash索引検査を少数の一日で再利用する。
        reader.selected([race_rows[0]["race_date"]])
        for offset in range(0, len(keys), 100):
            batch = keys[offset:offset + 100]
            clause = ",".join(["(CONVERT(binary(32),?),CONVERT(nvarchar(max),?))"] * len(batch))
            params = [value for key in batch for value in (hashlib.sha256(key.encode("utf-16le")).digest(), key)] + [31]
            sql = "SELECT " + ",".join("t.[" + f + "]" for f in FIELDS["market.odds_asof_index"])
            sql += " FROM market.odds_asof_index t JOIN (VALUES " + clause + ") k(hash_value,race_key) ON t.__unified_race_sha256=k.hash_value AND CONVERT(varbinary(max),t.race_key)=CONVERT(varbinary(max),k.race_key) WHERE t.__migration_source_snapshot_id=? AND t.market=N'quinella' AND t.horizon IN (N'T30',N'T10')"
            rows = reader._small("r1_movement:bounded_pairs", sql, params)
            query_count += 1
            grouped = defaultdict(list)
            for row in rows:
                require(row["race_key"] in batch, "movement_hash_mismatch")
                grouped[row["race_key"]].append(row)
            for key in batch:
                try:
                    earlier, later = compare_markets(grouped[key])
                    observations = []
                    for ticket in selected[key]:
                        pair = tuple(ticket["horses"])
                        require(pair in earlier and abs(earlier[pair] - ticket["ticket"]["quoted_odds"]) < 1e-10, "movement_saved_quote_mismatch")
                        observations.append({"variant": ticket["variant"], "ratio": later[pair] / earlier[pair],
                            "frozen_t30_probability": ticket["probability"], "t10_odds": later[pair],
                            "t30_raw_ev": ticket["probability"] * earlier[pair], "t10_raw_ev": ticket["probability"] * later[pair]})
                    values[key] = {"all_pairs": [later[p] / earlier[p] for p in earlier],
                                   "by_band": {i: [later[p] / earlier[p] for p in earlier if price_band(earlier[p]) == i] for i in range(4)},
                                   "selected": observations}
                except Exception as error:
                    from jra_srb.jra_research_contracts import ResearchError
                    if not isinstance(error, ResearchError):
                        raise
                    rejected.append({"race_key": key, "reason": error.reason})
    result = {}
    for period in PERIODS:
        subset = [key for key in values if in_period(races[key], period)]
        result[period] = {"races": len(subset), "all_pairs": statistics([v for key in subset for v in values[key]["all_pairs"]]),
                          "price_bands": {str(i): statistics([v for key in subset for v in values[key]["by_band"][i]]) for i in range(4)}, "selected": {}}
        for variant in metrics["policy_results"]:
            observations = [t for key in subset for t in values[key]["selected"] if t["variant"] == variant]
            result[period]["selected"][variant] = {**statistics([t["ratio"] for t in observations]),
                "frozen_ev_below_1_05_at_t10": sum(t["t10_raw_ev"] < 1.05 for t in observations),
                "raw_ev_above_1_05_at_t30": sum(t["t30_raw_ev"] >= 1.05 for t in observations)}
    report = {"status": "passed", "run_id": run_id, "requested_races": len(keys), "matched_races": len(values),
              "excluded": rejected, "exclusion_counts": dict(Counter(r["reason"] for r in rejected)), "bounded_queries": query_count,
              "periods": result, "new_fits": 0, "t10_used_as_prediction_input": False,
              "interpretation": "price_sensitivity_with_frozen_T30_probability_not_a_T10_forecast",
              "script_sha256": hashlib.sha256((ROOT / "scripts/audit_jra_r1_odds_movement.py").read_bytes()).hexdigest()}
    target = path / "odds-movement-audit.json"
    if target.exists():
        require(digest(read_json(target)) == digest(report), "movement_existing_report_differs")
    else:
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return {k: v for k, v in report.items() if k not in ("excluded", "periods")}


def main():
    """指定runの価格診断を実行し、概要を表示する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    print(json.dumps(execute(parser.parse_args().run_id), ensure_ascii=False))


if __name__ == "__main__":
    main()
