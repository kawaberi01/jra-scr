"""概要: 保存済み三重賞予想のワイド・3連複を固定規則で精算する。
作成日: 2026-11-14
入力: 固定予想、SQL払戻監査JSON、過去成績JSON。
出力: graded_tickets_20261114_baseline配下の明細・集計・入力hash。
実行例: uv run python scripts/evaluate_graded_ticket_baseline.py
注意事項: 外部通信・DB変更なし。同期間で選んだモデルの探索的評価。
"""

import hashlib
import json
from collections import defaultdict
from itertools import combinations
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "artifacts/jra_research"


def load(relative):
    """研究成果物のUTF-8 JSONを読む。"""
    return json.loads((BASE / relative).read_text(encoding="utf-8"))


def selection(raw, size):
    """HRの2桁馬番連結を順不同の組に正規化する。"""
    assert len(raw) == size * 2 and raw.isdigit(), "invalid_selection"
    values = tuple(sorted(int(raw[i:i + 2]) for i in range(0, len(raw), 2)))
    assert len(set(values)) == size and min(values) >= 1, "invalid_horse_numbers"
    return values


def summarize(rows):
    """券種・系列別に購入額と実払戻を合算する。"""
    groups = defaultdict(list)
    for row in rows:
        groups[(row["pattern"], row["series_id"], row["policy"])].append(row)
        groups[(row["pattern"], "all", row["policy"])].append(row)
    result = []
    for (pattern, series, policy), values in sorted(groups.items()):
        stake = sum(v["stake_yen"] for v in values)
        paid = sum(v["payout_yen"] for v in values)
        result.append(dict(pattern=pattern, series_id=series, policy=policy,
                           races=len(values), hit_races=sum(v["payout_yen"] > 0 for v in values),
                           tickets=sum(len(v["tickets"]) for v in values),
                           hit_tickets=sum(t["payout_yen"] > 0 for v in values for t in v["tickets"]),
                           torigami_races=sum(0 < v["payout_yen"] < v["stake_yen"] for v in values),
                           stake_yen=stake, payout_yen=paid, profit_yen=paid-stake,
                           return_rate=paid/stake))
    return result


def main():
    """入力を照合し、固定した各100円購入規則の全明細を保存する。

    Raises:
        AssertionError: 払戻・成績・開催範囲に欠落や不整合がある場合。
    Notes:
        結果は精算・整合確認だけに使い、選ぶ馬には使用しない。
    """
    files = ["graded_patterns_20261114_verified/predictions.json",
             "graded_tickets_20261114_audit/coverage.json",
             "graded_patterns_20261114_export_v2/dataset.json",
             "elizabeth_conditions_v1_20261108_export_v4/dataset.json"]
    predictions, audit, additional, elizabeth = [load(p) for p in files]
    races = {r["race_key"]: r for d in (additional, elizabeth) for r in d["races"]}
    keys = set(audit["target_keys"])
    assert len(keys) == 54
    payouts = defaultdict(dict)
    for row in audit["payouts"]:
        market = row["market"]
        if market not in {"wide", "trio"} or row["slot_status"] == "empty_slot":
            continue
        assert row["slot_status"] == "published", "unsupported_payout_status"
        pair = selection(row["selection_raw"], 2 if market == "wide" else 3)
        assert pair not in payouts[(row["race_key"], market)], "duplicate_payout"
        assert isinstance(row["payout_yen"], int) and row["payout_yen"] > 0
        payouts[(row["race_key"], market)][pair] = row["payout_yen"]
    for key in keys:
        actual = sorted(int(r["horse_no"]) for r in races[key]["runners"] if 1 <= int(r["rank"] or 0) <= 3)
        assert len(actual) == 3, "tied_or_missing_results_require_separate_settlement"
        assert set(payouts[(key, "wide")]) == set(combinations(actual, 2)), "wide_result_mismatch"
        assert set(payouts[(key, "trio")]) == {tuple(actual)}, "trio_result_mismatch"
    ledger = []
    for prediction in predictions:
        if prediction["pattern"] not in {"route", "frozen_v2"}:
            continue
        key = prediction["race_key"]
        runners = sorted(prediction["runners"], key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
        top = sorted(int(r["horse_no"]) for r in runners[:3])
        tickets = {}
        for market, size in (("wide", 2), ("trio", 3)):
            tickets[market] = [dict(market=market, horses=list(c), stake_yen=100,
                                   payout_yen=payouts[(key, market)].get(c, 0))
                               for c in combinations(top, size)]
        for policy, bets in (("W3", tickets["wide"]), ("T1", tickets["trio"]),
                             ("WT", tickets["wide"] + tickets["trio"])):
            ledger.append(dict(pattern=prediction["pattern"], series_id=prediction["series_id"],
                               race_key=key, policy=policy, selected_horses=top, tickets=bets,
                               stake_yen=100*len(bets), payout_yen=sum(t["payout_yen"] for t in bets)))
    assert len(ledger) == 54*2*3
    result = dict(scope="exploratory_same_period_no_pre_race_price_filter",
                  summary=summarize(ledger), inputs={p: hashlib.sha256((BASE/p).read_bytes()).hexdigest() for p in files},
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    out = BASE / "graded_tickets_20261114_baseline"
    out.mkdir(parents=True, exist_ok=True)
    for name, value in (("ledger.json", ledger), ("summary.json", result)):
        (out/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
