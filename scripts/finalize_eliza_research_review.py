"""概要: 当日女王杯の固定v2予想へ追加検証の採否と市場比較買い目を添えて保存する。
作成日: 2026-11-15
入力: --prediction（最新の保存予想）、--output（新規保存先）、固定した追加検証成果物。
出力: 同一値の全頭評価・主案・非採用比較案を含むJSON、固定10節、SHA。
実行例: uv run python scripts/finalize_eliza_research_review.py --prediction artifacts/jra_research/elizabeth_live_20261115_reference_v3 --output artifacts/jra_research/elizabeth_live_20261115_reviewed_v1
注意事項: 外部通信・結果取得・DB更新・実購入なし。新規事前保存は発走前・観測15分以内に限る。
"""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import argparse
from uuid import uuid4

from run_jra_miss_refinement import ROOT, BASE, read
from run_jra_graded_live import render, table, observed_price, jst
from run_jra_plan_consensus import select_horses


def sha(path):
    """保存したバイト列のSHA-256を返す。"""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    """既存成果物を上書きせずJSONを保存し、読み戻し照合する。"""
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
    assert read(path) == value


def presentation(result):
    """既存の10節と列を維持し、研究の留保と比較4券だけを追加する。"""
    text = render(result)
    review = result["research_review"]
    shared, consensus = review["shared_parts"], review["market_consensus"]
    extra = (f"追加検証：共通条件の共有4案は女王杯の時系列13開催でBrier約{shared['relative_improvement']:.2%}改善だが、"
             f"WT回収率{shared['baseline_money']['return_rate']:.2%}→{shared['selected_money']['return_rate']:.2%}で非採用。"
             f"市場との合意による4選抜規則も捕捉{consensus['baseline_capture']}→{consensus['selected_capture']}頭、"
             f"WT{consensus['baseline_money']['return_rate']:.2%}→{consensus['selected_money']['return_rate']:.2%}で主案変更基準未達。単勝人気から期待値は計算していない。\n\n"
             "公式2年258件の参照は保持し、今年とID一致した03/10/17の過去成績を確率に直接加算しない。"
             "11番の175日間隔、馬場・調教・仕上がり未評価の留保は残る。上位5頭は基準比+5ptの上限に達しており、小さな部品変更で順位が変わらないことを精度の証明としない。\n\n")
    assert text.count("## 5. 市場比較と採否") == 1
    text = text.replace("## 5. 市場比較と採否", extra+"## 5. 市場比較と採否")
    runners = result["forecast"]["runners"]
    quote = {int(r["combination"][0]): r for r in result["odds"]["odds"]["win"]}
    popular = {n:i for i,n in enumerate(sorted(quote, key=lambda n:(float(quote[n]["odds"]),n)),1)}
    alternate = result["condition_parts_alternatives"][0]
    text = text.replace("|補助券種オッズ|未取得|補助案なし|",
                        f"|補助券種オッズ|{jst(result['odds']['fetched_at'])}|比較案のワイド・3連複4点は取得。馬連・3連単は未取得|")
    policy_label = {"market": "単勝人気上位3頭", "half": "市場上位半分からモデル順", "third": "市場上位3分の1からモデル順"}[alternate["selection_policy"]]
    alternative_set = set(alternate["selected_horses"])
    rows = []
    for r in runners:
        n = int(r["horse_no"])
        if r["rank"]>3 and n not in alternative_set:
            continue
        rows.append([f"{n} {r['horse_name']}",f"{r['rank']}位・{r['probability_top3']:.1%}",
                     f"{quote[n]['odds']}倍・{popular[n]}人気",
                     "主案に含める" if r["rank"]<=3 else "比較案のみ・主案非採用",
                     "固定v2上位3頭" if r["rank"]<=3 else "市場選抜案。過去検証基準未達のため主案へ追加しない"])
    start, end = text.index("## 5. 市場比較と採否"), text.index("## 6. 主案の検証用仮想買い目")
    text = text[:start]+"## 5. 市場比較と採否\n\n"+table(["対象馬","モデル評価","市場評価","扱い","理由"],rows)+"\n\n"+text[end:]
    rows = [[alternate["plan_id"],("ワイド" if t["bet_type"]=="wide" else "3連複")+" "+"−".join(str(int(n)) for n in t["selection"]),
             t["display_odds"],"別枠仮想100円" if t["observed_odds"] is not None else "基準100円・価格不足で保留",
             f"{policy_label}による比較。確率・印を変更しない", "非採用・主案に非合算"] for t in alternate["tickets"]]
    start, end = text.index("## 7. 補助案・追加仮説"), text.index("## 8. 保存状況")
    block = "## 7. 補助案・追加仮説\n\n"+table(["案ID","券種・組合せ","実オッズ","仮想金額","仮説・根拠","評価上の扱い"],rows)
    block += f"\n\n比較案は別枠の仮想400円。主案400円と合わせて買う提案ではありません。価格観測：{jst(result['odds']['fetched_at'])}。\n\n"
    text = text[:start]+block+text[end:]
    text = text.replace("|補助仮説|追加案なし|", "|補助仮説|市場比較案は非採用・別検証。結果未確定|")
    assert text.count("\n## ") == 10
    assert review["new_probability_model_adopted"] is False
    return text


def main():
    """発走時刻・資料SHA・価格鮮度を確認して新規版だけを凍結する。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    assert not args.output.exists()
    original=read(args.prediction/"prediction.json")
    now=datetime.now(timezone.utc)
    post=datetime.fromisoformat(original["card"]["start_at"])
    assert now<post and original["generated_before_result"] and original["outcome_reads"]==0
    for observed in (original["odds"]["fetched_at"],original["final_card"]["fetched_at"]):
        assert 0<=(now-datetime.fromisoformat(observed.replace("Z","+00:00"))).total_seconds()<=900
    manifest=read(args.prediction/"manifest.json")
    assert sha(args.prediction/"prediction.json")==manifest["prediction_sha256"]
    for file,expected in manifest["files"].items():
        assert sha(Path(file))==expected
    shared_dir=BASE/"shared_parts_20261115_analysis"
    plan_dir=BASE/"plan_consensus_20261115_analysis"
    for directory in (shared_dir,plan_dir):
        for file,expected in read(directory/"manifest.json")["files"].items():
            assert sha(Path(file))==expected
    shared=read(shared_dir/"summary.json")["policies"]["elizabeth"]
    plan=read(plan_dir/"summary.json")["policies"]["elizabeth"]
    assert not shared["plan_qualifies"] and not plan["qualifies"], "主案変更基準通過時は別途その規則を実装する"
    result=deepcopy(original)
    result["source_artifact_id"]=original["artifact_id"]
    result["source_created_at"]=original["created_at"]
    result["created_at"]=now.isoformat()
    result["artifact_id"]="condition-parts-v2-reviewed-"+original["card"]["race_key"]+"-"+str(uuid4())
    result["condition_parts_plan"]["plan_id"]=result["artifact_id"]+"-main"
    win={int(r["combination"][0]):float(r["odds"]) for r in original["odds"]["odds"]["win"]}
    selected=select_horses(original["forecast"]["runners"],win,plan["comparison_policy"])
    from itertools import combinations
    tickets=[]
    for kind,size in (("wide",2),("trio",3)):
        for combination in combinations(sorted(selected),size):
            raw=observed_price(original["odds"],kind,combination)
            shown="未取得" if raw is None else (f"{raw['odds_min']}〜{raw['odds_max']}倍" if kind=="wide" else f"{raw['odds']}倍")
            tickets.append(dict(bet_type=kind,selection=[str(n).zfill(2) for n in combination],amount=100,
                                observed_odds=raw,display_odds=shown,observed_at=original["odds"]["fetched_at"]))
    result["condition_parts_alternatives"]=[dict(plan_id=result["artifact_id"]+"-comparison",selection_policy=plan["comparison_policy"],
         selected_horses=selected,adopted=False,virtual_only=True,reference_stake_yen=400,tickets=tickets,
         reason="過去だけで選抜した規則の主案変更基準未達。価格付き比較として保存し主案に合算しない")]
    result["research_review"]=dict(shared_parts=shared,market_consensus=plan,new_probability_model_adopted=False,
         primary_plan_changed=False,official_reference=str(BASE/"elizabeth_live_20261115_supplement_v2/official-reference.json"),
         saturated_upper_horses=[r["horse_no"] for r in original["forecast"]["runners"] if abs(r["probability_top3"]-r["baseline_probability_top3"]-.05)<1e-9])
    result["presentation"]=presentation(result)
    assert result["forecast"]==original["forecast"]
    assert result["condition_parts_plan"]["tickets"]==original["condition_parts_plan"]["tickets"]
    args.output.mkdir(parents=True)
    save(args.output/"prediction.json",result)
    save(args.output/"normalized-used-history.json",read(args.prediction/"normalized-used-history.json"))
    with (args.output/"presentation.md").open("x",encoding="utf-8",newline="\n") as stream:
        stream.write(result["presentation"])
    assert (args.output/"presentation.md").read_text(encoding="utf-8")==result["presentation"]
    assert datetime.now(timezone.utc)<post
    sources=[args.prediction/"prediction.json",args.prediction/"manifest.json",Path(__file__),ROOT/"scripts/run_jra_graded_live.py",
             BASE/"elizabeth_live_20261115_supplement_v2/official-reference.json",*shared_dir.glob("*.json"),*plan_dir.glob("*.json")]
    save(args.output/"manifest.json",dict(created_at=now.isoformat(),files={str(p):sha(p) for p in sources},
         prediction_sha256=sha(args.output/"prediction.json"),presentation_sha256=sha(args.output/"presentation.md"),
         outcome_reads=0,generated_before_result=True,sql_saved=False,file_readback_verified=True))
    print(json.dumps(dict(artifact_id=result["artifact_id"],main=[r["horse_no"] for r in result["forecast"]["runners"][:3]],
                         comparison_policy=plan["comparison_policy"],comparison=selected,created_at=result["created_at"]),ensure_ascii=False))


if __name__=="__main__":
    main()
