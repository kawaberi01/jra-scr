"""概要: 同名レースの主軸を残し、一般条件2群の系列間共有を4案で比較する。
作成日: 2026-11-15
入力: --output、--live-prediction、保存済み三系列dataset・予測・払戻。
出力: 新規保存先へ216予測・年別指標・時系列採否・精算・当日参考・SHA。
実行例: uv run python scripts/run_jra_shared_parts.py --live-prediction artifacts/jra_research/elizabeth_live_20261115_reference_v2 --output artifacts/jra_research/shared_parts_20261115_analysis
注意事項: 外部通信・DB更新・実購入なし。2026の結果を取得せず、過去探索値を利益保証にしない。
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from itertools import combinations
import json
from pathlib import Path

from run_jra_miss_refinement import ROOT, BASE, CANDIDATE, adjusted_deltas, read
from evaluate_graded_ticket_baseline import selection
from jra_srb.jra_graded_patterns import build_examples
from jra_srb.jra_race_conditions import aggregate, load_config
from jra_srb.jra_conditions_refinement import group_deltas, candidate_prediction, qualify
from jra_srb.jra_conditions_stability import bounded_probabilities
from jra_srb.jra_conditions_search import score_prediction, bootstrap_difference
from run_jra_graded_live import table


def share_config(config):
    """共有可能と固定した相対条件だけを元の5群の位置に残す。"""
    result = deepcopy(config)
    groups = list(result["groups"])
    result["groups"] = {g: (["previous_rank", "interval"] if i == 2 else
                            ["distance_change", "weight_change"] if i == 3 else []) for i, g in enumerate(groups)}
    return result


def shared_pool(races, target):
    """対象年より前の三系列だけを共有し、同年の結果を排除する。"""
    return [r for r in races if r["race_date"][:4] < target["race_date"][:4] and r["evaluation_eligible"]]


def forecasts(own, all_races, target, baseline, config):
    """元v2の寄与を保持し、指定2群だけ半分補完した4予測を返す。"""
    local = group_deltas(own, target, config, CANDIDATE)
    pool = shared_pool(all_races, target)
    shared = adjusted_deltas(pool, target, share_config(config), 1)
    assert [r["horse_no"] for r in local] == [r["horse_no"] for r in shared]
    anchors = {r["horse_no"]: r["probability_top3"] for r in baseline["runners"]}
    result = []
    for mask in range(4):
        evidence = deepcopy(local)
        for row, other in zip(evidence, shared, strict=True):
            for bit, index in ((1, 2), (2, 3)):
                if mask & bit:
                    row["deltas"][index] = (row["deltas"][index]+other["deltas"][index])/2
        prediction = candidate_prediction(evidence, target, {**CANDIDATE, "pattern": "S"+str(mask)})
        probabilities = bounded_probabilities([r["probability_top3"] for r in prediction["runners"]],
                                              [anchors[r["horse_no"]] for r in prediction["runners"]], .05)
        prediction["runners"] = sorted([{**r, "probability_top3": p} for r, p in zip(prediction["runners"], probabilities, strict=True)],
                                       key=lambda r: (-r["probability_top3"], int(r["horse_no"])))
        assert abs(sum(r["probability_top3"] for r in prediction["runners"])-3)<1e-9
        assert all(abs(r["probability_top3"]-anchors[r["horse_no"]])<=.050000001 for r in prediction["runners"])
        prediction.update(mask=mask, shared_latest_year=max(r["race_date"][:4] for r in pool), shared_races=len(pool),
                          shared_series=sorted({r["series_id"] for r in pool}), own_latest_date=max(r["race_date"] for r in own))
        result.append(prediction)
    return result


def choose(rows):
    """過去だけのBrier最小を選び、同率は共有を少なくする。"""
    values = {m: aggregate([r for r in rows if r["mask"] == m])["brier"] for m in range(4)}
    best = min(values.values())
    return min((m for m, v in values.items() if v<=best+1e-12), key=lambda m: (m.bit_count(), m))


def settle(prediction, payouts):
    """選抜後の上位3頭の固定4券を公式払戻で精算する。"""
    selected = sorted(int(r["horse_no"]) for r in prediction["runners"][:3])
    bets = [dict(bet_type=kind, selection=list(c), amount=100,
                 payout_yen=payouts[(prediction["race_key"], kind)].get(c, 0))
            for kind, size in (("wide", 2), ("trio", 3)) for c in combinations(selected, size)]
    return dict(tickets=bets, stake_yen=400, payout_yen=sum(t["payout_yen"] for t in bets))


def money(rows):
    """固定主案の回収・的中と、最大払戻1開催を除いた値を返す。"""
    stake = sum(r["stake_yen"] for r in rows)
    paid = sum(r["payout_yen"] for r in rows)
    worst_dependency = max(rows, key=lambda r: (r["payout_yen"], r["race_key"]))
    return dict(races=len(rows), stake_yen=stake, payout_yen=paid, return_rate=paid/stake,
                hit_races=sum(r["payout_yen"]>0 for r in rows),
                largest_payout_race=worst_dependency["race_key"], largest_payout_yen=worst_dependency["payout_yen"],
                return_rate_without_largest=(paid-worst_dependency["payout_yen"])/(stake-worst_dependency["stake_yen"]))


def main():
    """時点順に有限比較し、未達時も当日参考の採否理由を保存する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-prediction", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    paths = [BASE/"elizabeth_conditions_v1_20261108_export_v4/dataset.json",
             BASE/"graded_patterns_20261114_export_v2/dataset.json", BASE/"graded_patterns_20261114_verified/predictions.json",
             BASE/"graded_tickets_20261114_audit/coverage.json", args.live_prediction/"prediction.json"]
    eliza, extra, old, audit, live = map(read, paths)
    assert live["outcome_reads"] == 0 and live["generated_before_result"]
    config = load_config(ROOT/"configs/research/race_conditions_elizabeth_v1.json")
    datasets = {"elizabeth": eliza, **{s: dict(races=[r for r in extra["races"] if r["series_id"] == s], history=extra["history"]) for s in ("musashino", "daily2")}}
    examples = {}
    for series, data in datasets.items():
        examples[series] = build_examples(data, True)
        for race in examples[series]:
            race["series_id"] = series
    all_races = [r for races in examples.values() for r in races]
    originals = {(p["series_id"], p["race_key"], p["pattern"]): p for p in old}
    payouts = {}
    for row in audit["payouts"]:
        if row["slot_status"] == "published" and row["market"] in ("wide", "trio"):
            payouts.setdefault((row["race_key"], row["market"]), {})[selection(row["selection_raw"], 3 if row["market"] == "trio" else 2)] = row["payout_yen"]
    for race in all_races:
        if race["race_key"] not in audit["target_keys"]:
            continue
        truth = sorted(int(r["horse_no"]) for r in race["rows"] if r["outcome"]["top3"])
        assert len(truth) == 3
        for kind, size in (("wide", 2), ("trio", 3)):
            assert set(payouts[(race["race_key"], kind)]) == set(combinations(truth, size))
    annual, predictions = [], []
    max_error = 0.
    for series, races in examples.items():
        for i, target in enumerate(races):
            if i<5 or not target["evaluation_eligible"]:
                continue
            for prediction in forecasts(races[:i], all_races, target, originals[(series, target["race_key"], "balanced")], config):
                prediction["series_id"] = series
                if prediction["mask"] == 0:
                    reference = {r["horse_no"]: r["probability_top3"] for r in originals[(series, target["race_key"], "frozen_v2")]["runners"]}
                    max_error = max(max_error, max(abs(r["probability_top3"]-reference[r["horse_no"]]) for r in prediction["runners"]))
                predictions.append(prediction)
                annual.append(dict(series_id=series, mask=prediction["mask"], race_key=target["race_key"], race_date=target["race_date"],
                                   **score_prediction(prediction, target), **settle(prediction, payouts)))
    assert max_error<1e-12
    policies = {}
    for series in examples:
        rows = [r for r in annual if r["series_id"] == series]
        selected, baseline = [], []
        for day in sorted({r["race_date"] for r in rows}):
            past = [r for r in rows if r["race_date"]<day]
            if len({r["race_date"] for r in past})<5:
                continue
            mask = choose(past)
            selected.append({**next(r for r in rows if r["race_date"] == day and r["mask"] == mask), "selection_latest_date": max(r["race_date"] for r in past)})
            baseline.append(next(r for r in rows if r["race_date"] == day and r["mask"] == 0))
        a, b = aggregate(selected), aggregate(baseline)
        interval = bootstrap_difference(selected, baseline)
        wins = sum(x["brier"]<y["brier"]-1e-12 for x, y in zip(selected, baseline, strict=True))
        cash, basecash = money(selected), money(baseline)
        score_ok = qualify(a, b, interval, wins)
        plan_ok = score_ok and a["top3_captured"]>=b["top3_captured"] and cash["return_rate"]>=basecash["return_rate"]
        policies[series] = dict(selected=a, baseline=b, interval=interval, improved_years=wins,
                                relative_improvement=1-a["brier"]/b["brier"], probability_qualifies=score_ok, plan_qualifies=plan_ok,
                                selected_money=cash, baseline_money=basecash, final_mask=choose(rows), selected_rows=selected)
    card = live["card"]
    assert max(r["race_date"] for r in all_races)<card["race_date"]
    target = {**{k:v for k,v in card.items() if k != "runners"}, "rows": live["forecast"]["features"]}
    anchors = dict(runners=[{**r, "probability_top3":r["baseline_probability_top3"]} for r in live["forecast"]["runners"]])
    current = forecasts(examples["elizabeth"], all_races, target, anchors, config)
    summary = dict(policies=policies, baseline_max_error=max_error,
                   fixed_summary={s: {str(m): aggregate([r for r in annual if r["series_id"] == s and r["mask"] == m]) for m in range(4)} for s in examples},
                   outcome_2026_read=False, live_reference_artifact_id=live["artifact_id"],
                   adoption="eligible_shared_comparison" if policies["elizabeth"]["plan_qualifies"] else "keep_frozen_v2")
    args.output.mkdir(parents=True)
    for name, value in (("summary", summary), ("annual", annual), ("predictions", predictions), ("live-comparison", current)):
        with (args.output/(name+".json")).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
    text = "# 共通条件パーツの系列間共有検証\n\n"+table(["系列", "Brier改善", "改善年", "確率基準", "主案変更基準", "WT回収率：基準→案"], [
        [s, f"{p['relative_improvement']:.2%}", p["improved_years"], p["probability_qualifies"], p["plan_qualifies"],
         f"{p['baseline_money']['return_rate']:.2%}→{p['selected_money']['return_rate']:.2%}"] for s,p in policies.items()])
    text += "\n\n"+table(["案", "共有群", "当日上位6頭"], [[p["mask"], ["なし", "直近成績・間隔", "距離・斤量変更", "両方"][p["mask"]], "・".join(str(int(r["horse_no"])) for r in p["runners"][:6])] for p in current])
    text += "\n\n確率基準は旧来の4条件。主案変更には上位3頭捕捉とWT回収率の非悪化も必要。同年の他系列結果は共有せず、直近成績/間隔と相対条件変更だけ半分補完。元v2の確率も比較用として全件保存。反復探索の同期間評価であり、未知優位・校正・利益を証明しない。主案変更基準が未達なら本日も元v2を維持する。\n"
    with (args.output/"report.md").open("x", encoding="utf-8") as stream:
        stream.write(text)
    sources = paths+[ROOT/"configs/research/race_conditions_elizabeth_v1.json", Path(__file__), ROOT/"scripts/run_jra_miss_refinement.py",
                     ROOT/"src/jra_srb/jra_conditions_refinement.py", ROOT/"src/jra_srb/jra_graded_patterns.py"]
    manifest = dict(created_at=datetime.now(timezone.utc).isoformat(), files={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources+sorted(args.output.glob("*"))})
    with (args.output/"manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
    print(json.dumps({s:{k:v for k,v in p.items() if k not in ("selected_rows","selected","baseline")} for s,p in policies.items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
