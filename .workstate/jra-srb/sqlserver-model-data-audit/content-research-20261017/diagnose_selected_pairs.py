"""概要: 保存済みの購入ペアだけで予測確率と実績の差を診断する。
作成日: 2026-10-17
入力: spec130、spec120成功runの選択ペア予測。
出力: 同じフォルダーのselected-pair-calibration.jsonと標準出力の要約。
実行例: uv run --frozen --extra ml python .workstate/jra-srb/sqlserver-model-data-audit/content-research-20261017/diagnose_selected_pairs.py
注意事項: 研究出力の診断のみ。再学習・SQL・旧入力読取・新購入条件の選択なし。
"""

from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "artifacts/jra_research/runs/20261017T091533Z_631037c77cb34fd895c779df1ba77e8d"
BINS = (0, .015, .025, .05, .1, .2, .5, 1)


def summary(rows):
    """選択ペアの予測的中数・実績・会計と開催日単位の誤差区間を返す。"""
    if not rows:
        return {"purchases": 0}
    probability = np.asarray([r["probability"] for r in rows])
    target = np.asarray([r["target"] for r in rows])
    daily = defaultdict(list)
    for row in rows:
        daily[row["race_date"]].append(row["probability"] - row["target"])
    values = np.asarray([(sum(v), len(v)) for _, v in sorted(daily.items())])
    rng = np.random.default_rng(42)
    totals = values[rng.integers(0, len(values), size=(1000, len(values)))].sum(axis=1)
    stake = sum(r["ticket"]["stake_yen"] for r in rows)
    return {"purchases": len(rows), "days": len(daily), "hits": int(target.sum()), "expected_hits": float(probability.sum()),
            "average_probability": float(probability.mean()), "observed_hit_rate": float(target.mean()),
            "selected_brier": float(np.mean((probability - target) ** 2)),
            "probability_minus_hit_rate_95": np.quantile(totals[:, 0] / totals[:, 1], [.025, .975]).tolist(),
            "return_rate": sum(r["ticket"]["payout_yen"] for r in rows) / stake}


def main():
    """全案・全期間・固定全確率帯を省略せず集計する。"""
    sys.stdout.reconfigure(encoding="utf-8")
    path = SOURCE / "predictions.jsonl.gz"
    rows = defaultdict(list)
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            rows[row["variant"]].append(row)
    assert sum(map(len, rows.values())) == 7970
    result = {}
    for name, records in rows.items():
        periods = {part: summary([r for r in records if part == "all" or r["split"] == part]) for part in ("all", "evaluation_2025", "evaluation_early", "evaluation_late")}
        bins = []
        for i, (left, right) in enumerate(zip(BINS, BINS[1:])):
            part = [r for r in records if left <= r["probability"] and (r["probability"] < right or i == len(BINS) - 2 and r["probability"] == right)]
            bins.append({"from_inclusive": left, "through": right, **summary(part)})
        assert sum(b["purchases"] for b in bins) == len(records)
        result[name] = {"periods": periods, "bins": bins}
    output = {"status": "complete", "protocol": "spec130-selected-pair-calibration-v1", "source_run": SOURCE.name,
              "source_gzip_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "completed_at_utc": datetime.now(timezone.utc).isoformat(),
              "exploratory": True, "unseen_test": False, "new_fits": 0, "sql_queries": 0, "results": result}
    Path(__file__).with_name("selected-pair-calibration.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({name: values["periods"] for name, values in result.items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
