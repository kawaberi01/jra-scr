"""概要: 不的中後2研究の指標・過年選択・市場確率・入力不変を独立検算する。
作成日: 2026-11-15
入力: 2研究成果物、元dataset・T30市場・保存v2予想。
出力: 各成果物フォルダーのverification.json。
実行例: uv run python scripts/verify_jra_miss_studies.py
注意事項: 標準ライブラリのみ。予測モジュールをimportせず、外部通信なし。
"""

import hashlib
from itertools import permutations
import json
import math
from pathlib import Path
import random

BASE=Path(__file__).resolve().parents[1]/"artifacts/jra_research"


def read(path):
    """検証用JSONを読む。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def weighted(rows,key):
    """開催指標を出走頭数で加重する。"""
    return sum(r[key]*r["runners"] for r in rows)/sum(r["runners"] for r in rows)


def bootstrap(first,second):
    """予測コードを使わず同一開催の対差を復元抽出する。"""
    assert [r["race_key"] for r in first]==[r["race_key"] for r in second]
    rng=random.Random(20261113)
    differences=[]
    for repeat in range(5000):
        indices=rng.choices(range(len(first)),k=len(first))
        differences.append(sum((first[i]["brier"]-second[i]["brier"])*first[i]["runners"] for i in indices)
                           /sum(first[i]["runners"] for i in indices))
    differences.sort()
    return [differences[int(.025*4999)],differences[int(.975*4999)]]


def main():
    """実際の着順と保存値から全指標・選択・市場確率を再計算する。"""
    datasets=[read(BASE/p) for p in ("elizabeth_conditions_v1_20261108_export_v4/dataset.json",
                                    "graded_patterns_20261114_export_v2/dataset.json")]
    truth={r["race_key"]:{h["horse_no"]:int(bool(h.get("rank") and h["rank"]<=3)) for h in r["runners"] if h["status"]=="active"}
           for d in datasets for r in d["races"]}
    original={(p["series_id"],p["race_key"]):p for p in read(BASE/"graded_patterns_20261114_verified/predictions.json") if p["pattern"]=="frozen_v2"}
    observations=read(BASE/"graded_tickets_20261114_market_audit/market.json")["rows"]
    market={}
    for row in observations:
        if row["market"]!="win":continue
        entries=[e for e in json.loads(row["entries_json"]) if e["market"]=="win" and e["odds_status_low"]=="numeric"]
        weights={int(e["selection_key"]):1/e["odds_low_x10"] for e in entries}
        total=sum(weights.values())
        marginal={h:0. for h in weights}
        for a,b,c in permutations(weights,3):
            p=weights[a]/total*weights[b]/(total-weights[a])*weights[c]/(total-weights[a]-weights[b])
            for h in (a,b,c):marginal[h]+=p
        market[row["race_key"]]=marginal
    for study,parameter in (("graded_misses_20261115_analysis","mask"),("market_assistance_20261115_analysis","alpha")):
        folder=BASE/study
        summary=read(folder/"summary.json")
        predictions=read(folder/"predictions.json")
        annual=read(folder/"annual.json")
        indexed={(r["series_id"],r["race_key"],r[parameter]):r for r in annual}
        nprob=0
        for pred in predictions:
            variant=pred[parameter]
            rows=pred["runners"]
            actual=truth[pred["race_key"]]
            assert set(actual)=={r["horse_no"] for r in rows}
            pairs=[(r["probability_top3"],actual[r["horse_no"]]) for r in rows]
            assert abs(sum(p for p,y in pairs)-3)<1e-9
            metric=indexed[(pred["series_id"],pred["race_key"],variant)]
            brier=sum((p-y)**2 for p,y in pairs)/len(pairs)
            loss=-sum(y*math.log(max(p,1e-12))+(1-y)*math.log(max(1-p,1e-12)) for p,y in pairs)/len(pairs)
            assert abs(brier-metric["brier"])<1e-12 and abs(loss-metric["logloss"])<1e-12
            old={r["horse_no"]:r["probability_top3"] for r in original[(pred["series_id"],pred["race_key"])]["runners"]}
            for r in rows:
                if parameter=="alpha":
                    expected=(1-variant)*old[r["horse_no"]]+variant*market[pred["race_key"]][int(r["horse_no"])]
                    assert abs(expected-r["probability_top3"])<1e-12
                elif variant==0:assert abs(old[r["horse_no"]]-r["probability_top3"])<1e-12
            nprob+=len(rows)
        for series,policy in summary["policies"].items():
            rows=[r for r in annual if r["series_id"]==series]
            for selected in policy["selected_rows"]:
                past=[r for r in rows if r["race_date"]<selected["race_date"]]
                assert max(r["race_date"] for r in past)==selected["selection_latest_date"]
                means={v:weighted([r for r in past if r[parameter]==v],"brier") for v in sorted({r[parameter] for r in past})}
                eligible=[v for v in means if means[v]<=min(means.values())+1e-12]
                chosen=min(eligible,key=lambda v:(v.bit_count(),v)) if parameter=="mask" else min(eligible)
                assert selected[parameter]==chosen
            selected=policy["selected_rows"]
            baseline=[next(r for r in rows if r["race_key"]==s["race_key"] and r[parameter]==0) for s in selected]
            assert abs(weighted(selected,"brier")-policy["selected"]["brier"])<1e-12
            assert all(abs(a-b)<1e-12 for a,b in zip(bootstrap(selected,baseline),policy["interval"]["interval95"],strict=True))
        if parameter=="alpha":
            for path,digest in summary["inputs"].items():assert hashlib.sha256((BASE/path).read_bytes()).hexdigest()==digest
        else:
            for audit in summary["misses"]:
                assert audit["virtual_stake_yen"]==400 and audit["virtual_payout_yen"]==0
                assert all(t["payout_yen"]==0 for t in audit["tickets"])
        verification=dict(status="passed",prediction_records=len(predictions),probabilities=nprob,metric_records=len(annual),
                          selections=sum(len(p["selected_rows"]) for p in summary["policies"].values()),
                          full_probability_recalculation=(parameter=="alpha"),note="頭数/粒度変更の非baseline確率は対象単体テストで検証。全指標・選択・区間は独立再計算。")
        (folder/"verification.json").write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding="utf-8")
        print(study,verification)


if __name__=="__main__":main()
