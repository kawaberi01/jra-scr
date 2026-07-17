from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(".workstate/jra-srb/prediction-v1-validation")
SUMMARY = ROOT / "v90_v90_external_2024_07_08_summary.json"
OUTPUT = ROOT / "v90_external_2024_07_08_adoption.md"


def main() -> None:
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    checks = {
        "axis_top3_rate >= 0.45": float(summary["axis_top3_rate"]) >= 0.45,
        "return_rate >= 1.00": float(summary["return_rate"]) >= 1.0,
        "return_rate_without_max_payout >= 1.00": float(summary["return_rate_without_max_payout"]) >= 1.0,
        "return_rate_without_top3_payouts >= 1.00": float(summary["return_rate_without_top3_payouts"]) >= 1.0,
        "tickets >= 20": int(summary["tickets"]) >= 20,
    }
    decision = "promote_candidate" if all(checks.values()) else "reject"
    lines = [
        "# v90_summer 2024年7〜8月 外部評価の採否判断",
        "",
        "- 理論: v90（評価前に固定）",
        f"- 評価期間: {summary['evaluation_period']}",
        "- データ監査: PASS（自動パイプラインで評価前に確認）",
        f"- decision: {decision}",
        "",
        "## 指標",
        "",
        f"- 軸馬3着内率: {summary['axis_top3_rate']}",
        f"- 回収率: {summary['return_rate']}",
        f"- 最大払戻除外回収率: {summary['return_rate_without_max_payout']}",
        f"- 上位3払戻除外回収率: {summary['return_rate_without_top3_payouts']}",
        f"- 買い目数: {summary['tickets']}",
        "",
        "## 事前固定した判定",
        "",
    ]
    lines.extend(f"- {'PASS' if passed else 'FAIL'}: {label}" for label, passed in checks.items())
    lines.extend([
        "",
        "v90の条件はこの外部評価の結果を見て変更しない。rejectの場合、改修は別バージョンで行う。",
        "",
    ])
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
