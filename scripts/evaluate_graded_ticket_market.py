"""概要: 三重賞の固定予想とT30市場を用い人気馬採否・馬連を比較する。
作成日: 2026-11-14
入力: spec130、保存予想、市場監査JSON、HR監査JSON、保存成績。
出力: graded_tickets_20261114_market_analysis配下の明細・集計・レポート。
実行例: uv run python scripts/evaluate_graded_ticket_market.py
注意事項: 外部通信・DB書込みなし。過去候補の探索的評価で期待値推定ではない。
"""

import hashlib
import json
import math
from datetime import datetime
from itertools import combinations
from pathlib import Path

from evaluate_graded_ticket_baseline import BASE, load, selection, summarize


POLICIES = ("original", "include", "exclude", "consensus")


def choose(runners, favorite, policy):
    """確率順位と事前人気馬だけで採用3頭または見送りを返す。"""
    ranked = [int(r["horse_no"]) for r in sorted(
        runners, key=lambda r: (-r["probability_top3"], int(r["horse_no"])))]
    if policy == "original":
        return sorted(ranked[:3])
    if policy == "include":
        return sorted([favorite] + [h for h in ranked if h != favorite][:2])
    if policy == "exclude":
        return sorted([h for h in ranked if h != favorite][:3])
    if policy == "consensus":
        return sorted(ranked[:3]) if favorite in ranked[:3] else []
    raise ValueError("unknown_policy")


def numeric(row, size):
    """公表済みT30市場を検査し、組から倍率への辞書を返す。"""
    assert row["horizon"] == "T30" and row["selection_status"] == "selected"
    assert row["parser_version"] == "jv-o1o2-v2" and len(row["content_sha256"]) == 64
    announced, cutoff = (datetime.fromisoformat(row[k]) for k in ("announced_at", "cutoff_at"))
    assert announced <= cutoff, "late_market"
    result = {}
    for entry in json.loads(row["entries_json"]):
        # 単勝のO1原観測には複勝・枠連も同梱されるため対象だけ選ぶ。
        if row["market"] == "win" and entry["market"] in {"place", "bracket_quinella"}:
            continue
        assert entry["market"] == row["market"], "unexpected_embedded_market"
        key = selection(entry["selection_key"], size)
        assert key not in result, "duplicate_price"
        if entry["odds_status_low"] == "asterisk_marker":
            # 後段で予想対象の全頭/全ペア一致を要求し、取消以外の欠測は拒否する。
            assert entry["odds_low_x10"] is None and set(entry["odds_raw_low"]) == {"*"}
            continue
        assert entry["odds_status_low"] == "numeric", "nonnumeric_market"
        price = entry["odds_low_x10"] / 10
        assert math.isfinite(price) and price >= 1, "invalid_odds"
        assert int(entry["odds_raw_low"]) == entry["odds_low_x10"]
        result[key] = price
    return result


def tickets(horses, market, prices):
    """選択馬から各100円の券を生成し、馬連だけ事前倍率を添える。"""
    if not horses:
        return []
    return [dict(market=market, horses=list(c), stake_yen=100,
                 pre_odds=prices[c] if market == "quinella" else None)
            for c in combinations(horses, 3 if market == "trio" else 2)]


def settle(bets, payout_maps, race_key):
    """確定HRだけで生成済み買い目を精算し、元の券を変更しない。"""
    return [{**bet, "payout_yen": payout_maps[(race_key, bet["market"])].get(tuple(bet["horses"]), 0)}
            for bet in bets]


def report(summary):
    """固定32構成の比較を、的中数・回収率と留保付きで表示する。"""
    lines = ["# 三重賞の人気馬採否と馬連比較", "", "対象: 2008〜2025年、各18開催、計54開催。2026結果は使用していない。",
             "各点100円。W3=3頭ワイドBOX、T1=3頭3連複1点、Q3=3頭馬連BOX、WT=W3+T1。",
             "人気馬はT30単勝最低オッズの1頭。同率は馬番昇順。", "",
             "original=予想上位3頭、include=人気馬+他の予想上位2頭、exclude=人気馬以外の上位3頭、",
             "consensus=予想上位3頭に人気馬がいる開催だけ購入。見送りは購入0円。", ""]
    for pattern in ("frozen_v2", "route"):
        lines += ["## " + pattern, "", "|条件|購入開催|W3回収率|T1回収率|Q3回収率|WT回収率|", "|---|---:|---:|---:|---:|---:|"]
        rows = {r["policy"]: r for r in summary if r["pattern"] == pattern and r["series_id"] == "all"}
        for policy in POLICIES:
            values = [f"{100*rows[policy+'_'+kind]['return_rate']:.2f}%" for kind in ("W3", "T1", "Q3", "WT")]
            lines.append("|"+policy+"|"+str(rows[policy+"_W3"]["purchased_races"])+"|"+"|".join(values)+"|")
        lines += ["", "|条件・券|的中開催|購入額|払戻額|トリガミ開催|", "|---|---:|---:|---:|---:|"]
        for policy in POLICIES:
            for kind in ("W3", "T1", "Q3", "WT"):
                r = rows[policy+"_"+kind]
                lines.append(f"|{r['policy']}|{r['hit_races']}|{r['stake_yen']:,}|{r['payout_yen']:,}|{r['torigami_races']}|")
        lines.append("")
    lines += ["## 判断", "", "v2初案を保持する。人気馬を機械的に加えると的中開催は増えても回収率が下がる場合がある。",
              "v2の人気馬除外馬連は2的中（2020武蔵野10,790円、2019デイリー10,840円）。最高回収率だけで自動採用しない。",
              "これは同期間で選んだ候補の32構成探索であり、未知期間の収益証明や組合せ確率の校正ではない。",
              "馬連各券のT30価格は明細へ保存。確定払戻は精算のみ。3着内確率の積を期待値計算に使っていない。", "",
              "## 入力と確認", "", "108観測の時刻・版・SHA・価格原値と、全54開催の全頭/全ペアを照合。",
              "O1に同梱の複勝/枠連を分離。2010女王杯の取消11番と関連記号を予想対象外として照合。",
              "2022女王杯は2着同着で馬連の的中2組をHRと照合した。",
              "全1,728明細、128集計。originalは前回24集計の金額と一致。", "",
              "今後は市場との比較を各レースの事前提案として保存し、結果を追記して検証する。",
              "ワイド/3連複/3連単の時点付き価格の保存先調査は、別添storage-investigation.mdを参照。", ""]
    return "\n".join(lines)


def main():
    """全入力を照合し32構成の探索的比較と再現用明細を保存する。

    Raises:
        AssertionError: 時点・馬集合・払戻・成績が不整合の場合。
    Notes:
        見送り開催の購入額は0円。欠測を見送りに偽装しない。
    """
    files = ["graded_patterns_20261114_verified/predictions.json",
             "graded_tickets_20261114_market_audit/market.json",
             "graded_tickets_20261114_audit/coverage.json",
             "graded_patterns_20261114_export_v2/dataset.json",
             "elizabeth_conditions_v1_20261108_export_v4/dataset.json"]
    predictions, market, audit, extra, eliza = [load(p) for p in files]
    races = {r["race_key"]: r for d in (extra, eliza) for r in d["races"]}
    keys = set(audit["target_keys"])
    assert len(keys) == 54 and set(market["target_keys"]) == keys
    quotes = {}
    for row in market["rows"]:
        key = (row["race_key"], row["market"])
        assert key not in quotes and key[0] in keys
        quotes[key] = numeric(row, 1 if key[1] == "win" else 2)
    assert len(quotes) == 108
    payouts = {}
    for row in audit["payouts"]:
        if row["market"] not in {"wide", "trio", "quinella"}:
            continue
        if row["slot_status"] == "empty_slot":
            continue
        assert row["slot_status"] == "published" and row["payout_yen"] > 0
        key = (row["race_key"], row["market"])
        horse_key = selection(row["selection_raw"], 3 if key[1] == "trio" else 2)
        assert horse_key not in payouts.setdefault(key, {})
        payouts[key][horse_key] = row["payout_yen"]
    for key in keys:
        actual = sorted((int(r["rank"] or 99), int(r["horse_no"]))
                        for r in races[key]["runners"] if int(r["rank"] or 0) in (1, 2, 3))
        assert [r for r, h in actual] in ([1, 2, 3], [1, 2, 2]), "unsupported_tied_result"
        top = sorted(h for r, h in actual)
        assert set(payouts[(key, "wide")]) == set(combinations(top, 2))
        assert set(payouts[(key, "trio")]) == {tuple(top)}
        expected_q = {tuple(sorted((h1, h2))) for r1, h1 in actual for r2, h2 in actual
                      if r1 == 1 and r2 == 2}
        assert set(payouts[(key, "quinella")]) == expected_q
    ledger, seen = [], set()
    for pred in predictions:
        if pred["pattern"] not in {"route", "frozen_v2"}:
            continue
        key = pred["race_key"]
        assert (key, pred["pattern"]) not in seen
        seen.add((key, pred["pattern"]))
        win = quotes[(key, "win")]
        runners = {int(r["horse_no"]) for r in pred["runners"]}
        assert {h[0] for h in win} == runners, "market_roster_mismatch"
        assert set(quotes[(key, "quinella")]) == set(combinations(sorted(runners), 2))
        favorite = min(win, key=lambda h: (win[h], h))[0]
        tied = sum(v == min(win.values()) for v in win.values())
        for policy in POLICIES:
            horses = choose(pred["runners"], favorite, policy)
            generated = {m: tickets(horses, m, quotes[(key, "quinella")])
                         for m in ("wide", "trio", "quinella")}
            for kind, bets in (("W3", generated["wide"]), ("T1", generated["trio"]),
                               ("Q3", generated["quinella"]),
                               ("WT", generated["wide"] + generated["trio"])):
                paid = settle(bets, payouts, key)
                ledger.append(dict(pattern=pred["pattern"], series_id=pred["series_id"],
                                   race_key=key, policy=policy+"_"+kind,
                                   favorite=favorite, favorite_tie_count=tied,
                                   favorite_win_odds=win[(favorite,)], selected_horses=horses,
                                   tickets=paid, stake_yen=100*len(paid),
                                   payout_yen=sum(t["payout_yen"] for t in paid)))
    assert len(seen) == 108 and len(ledger) == 1728
    summary = summarize(ledger)
    for row in summary:
        subset = [v for v in ledger if v["pattern"] == row["pattern"] and v["policy"] == row["policy"]
                  and (row["series_id"] == "all" or v["series_id"] == row["series_id"])]
        row["purchased_races"] = sum(v["stake_yen"] > 0 for v in subset)
        row["skipped_races"] = len(subset)-row["purchased_races"]
        row["max_race_payout_yen"] = max(v["payout_yen"] for v in subset)
        row["max_payout_share"] = (row["max_race_payout_yen"]/row["payout_yen"] if row["payout_yen"] else None)
    out = BASE / "graded_tickets_20261114_market_analysis"
    out.mkdir(exist_ok=True)
    result = dict(scope="exploratory_fixed_policy_no_joint_probability_or_EV", summary=summary,
                  inputs={p: hashlib.sha256((BASE/p).read_bytes()).hexdigest() for p in files},
                  script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    for name, value in (("ledger.json", ledger), ("summary.json", result)):
        (out/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    (out/"report.md").write_text(report(summary), encoding="utf-8")
    print(json.dumps([r for r in summary if r["series_id"] == "all"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
