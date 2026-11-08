"""概要: 保存済み予測から内容不足時の履歴切替1案を事後探索として比較する。
作成日: 2026-10-17
入力: spec125、spec120成功runのmetrics.json。
出力: 同じフォルダーのswitch-results.json、標準出力の集計。
実行例: uv run --frozen --extra ml python .workstate/jra-srb/sqlserver-model-data-audit/content-research-20261017/evaluate_switch.py
注意事項: 元データ・SQLを読まず、新規学習・削除・元成果物変更なし。独立検証ではない。
"""

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np

from jra_srb.jra_research_tipster_experiment import summary


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "artifacts/jra_research/runs/20261017T091533Z_631037c77cb34fd895c779df1ba77e8d"


def difference_interval(rows, baseline):
    """開催日単位で予測損失と収益の差を再標本化する。"""
    groups = defaultdict(list)
    for row in rows:
        groups[row["race_date"]].append(row)
    daily = []
    for _, values in sorted(groups.items()):
        difference = sum(row["loss_switch"] - row["loss_" + baseline] for row in values)
        profit = sum(row["payout_switch"] - row["payout_" + baseline] for row in values)
        daily.append((difference, profit, len(values)))
    data = np.asarray(daily)
    rng = np.random.default_rng(42)
    samples = data[rng.integers(0, len(data), size=(1000, len(data)))].sum(axis=1)
    return {"logloss_difference_95": np.quantile(samples[:, 0] / samples[:, 2], [.025, .975]).tolist(),
            "roi_difference_95": np.quantile(samples[:, 1] / (600 * samples[:, 2]), [.025, .975]).tolist(),
            "interpretation": "探索的・多重比較補正なし。ROI差は正が新案有利、損失差は負が新案有利"}


def main():
    """事前固定した観測区分だけでモデルを選び、結果は評価のみに使う。"""
    raw = (SOURCE / "metrics.json").read_bytes()
    source = json.loads(raw)
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete" and source["status"] == "passed"
    assert len(source["race_diagnostics"]) == 1594
    rows, tickets = [], defaultdict(list)
    for item in source["race_diagnostics"]:
        chosen = "full" if item["stratum"] == "rich" else "history"
        row = {"race_key": item["race_key"], "race_date": item["race_date"], "period": item["period"], "stratum": item["stratum"], "chosen": chosen}
        for variant, actual in (("switch", chosen), ("history", "history"), ("full", "full")):
            current = item["tickets"][actual]
            assert len(current) == 1 and current[0]["stake_yen"] == 600
            row["loss_" + variant] = item["logloss"][actual]
            row["brier_" + variant] = item["brier"][actual]
            row["payout_" + variant] = current[0]["payout_yen"]
            tickets[variant].append({**current[0], "race_date": item["race_date"], "period": item["period"], "race_key": item["race_key"], "stratum": item["stratum"]})
        rows.append(row)
    results = {}
    for variant in ("history", "full", "switch"):
        results[variant] = {}
        for part in ("all", "evaluation_2025", "evaluation_early", "evaluation_late", "rich", "sparse"):
            selected = [r for r in rows if part == "all" or r["period"] == part or r["stratum"] == part]
            actual = [t for t in tickets[variant] if part == "all" or t["period"] == part or t["stratum"] == part]
            results[variant][part] = {**summary(actual), "logloss": float(np.mean([r["loss_" + variant] for r in selected])),
                                    "brier": float(np.mean([r["brier_" + variant] for r in selected]))}
    for variant in ("history", "full"):
        for field in ("races", "stake_yen", "payout_yen", "logloss", "brier"):
            assert np.isclose(results[variant]["all"][field], source["results"][variant]["all"][field], atol=1e-12, rtol=0)
    output = {"status": "complete", "completed_at_utc": datetime.now(timezone.utc).isoformat(), "protocol": "spec125-posthoc-switch-v1",
              "source_run": SOURCE.name, "source_metrics_sha256": hashlib.sha256(raw).hexdigest(),
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "posthoc": True, "unseen_test": False, "live_adopted": False, "new_fits": 0, "sql_queries": 0,
              "rule": "rich:full; sparse:history; richは通過/ラップの両馬観測ペア割合がともに50%以上",
              "results": results, "paired_intervals": {baseline: difference_interval(rows, baseline) for baseline in ("history", "full")}, "choices": rows}
    Path(__file__).with_name("switch-results.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "complete", "results": {k: {part: {"roi": v["return_rate"], "logloss": v["logloss"]} for part, v in values.items()} for k, values in results.items()}, "intervals": output["paired_intervals"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
