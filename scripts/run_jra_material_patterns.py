"""概要: 公式時計差P・末脚Fの4固定比較と、今年18頭の予想差を保存する。
作成日: 2026-11-22
入力: --dataset、--reference、--facts、--card、--history、--foreign、--output。
出力: 72予測・年別成績・選択・今年4方式比較・根拠・レポート・SHA。
実行例: uv run python scripts/run_jra_material_patterns.py --help
注意事項: オフライン探索研究。既存予想やDBを変更せず、2026結果を取得しない。
"""

import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from jra_srb.jra_material_patterns import evaluate,feature,combine,GROUPS,OPTIONS
from jra_srb.jra_conditions_refinement import group_deltas
from jra_srb.jra_specific_patterns import mean_metrics
from jra_srb.jra_race_conditions import require


def read(path):
    """UTF-8 JSONを読む。"""
    return json.loads(path.read_text(encoding="utf-8"))


def save(path,value):
    """新規JSONへ検証値を保存する。"""
    with path.open("x",encoding="utf-8") as f:json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)


def report(result,current,coverage):
    """期間別精度と今年全頭の差を同じ列で表示する。"""
    lines=["# 公式時計差・末脚の追加検証", "", "## 固定条件", "",
        "基準N+C+WにP（直近730日の芝1400〜1800m国際GIの勝ち馬との時計差）、F（同レース内の上がり順位帯）を各0.5追加。欠測は中立、古い好走へ戻らない。封印予想入力ではなく固定採用値を使う探索的研究。", "",
        "|方式|開発Brier|開発上位3捕捉|確認Brier|確認上位3捕捉|確認上位6捕捉|", "|---|---:|---:|---:|---:|---:|"]
    for p,_ in OPTIONS:
        d=result["selection"]["development"][p]; c=mean_metrics([r for r in result["annual"] if r["pattern"]==p and "2021"<=r["race_date"][:4]<="2025"])
        lines.append(f"|{p}|{d['brier']:.6f}|{d['top3_captured']:.3f}|{c['brier']:.6f}|{c['top3_captured']:.3f}|{c['top6_captured']:.3f}|")
    lines += ["",f"開発だけの選択: {result['selection']['pattern']}。研究予想変更の参考条件充足: {result['research_change_eligible']}。独立優位/本採用/収益実証はFalse。", ""]
    for p,c in result["comparisons"].items():
        lines.append(f"- {p}: 対基準Brier改善{c['brier_relative_improvement']:.2%}、改善{c['improved_years']}/5年、参考区間{c['interval95']}、条件{c['checks']}。")
    lines += ["", "## 充足", "",json.dumps(coverage,ensure_ascii=False), "", "## 保存2026カードの4方式全頭比較", "",
        "|馬番・馬名|基準順位/確率|P追加順位/確率|F追加順位/確率|両追加順位/確率|", "|---|---:|---:|---:|---:|"]
    lookup={p:{r["horse_id"]:(i,r["probability_top3"]) for i,r in enumerate(pred["runners"],1)} for p,pred in current["predictions"].items()}
    for r in current["predictions"]["baseline"]["runners"]:
        cells=[f"{lookup[p][r['horse_id']][0]}位/{lookup[p][r['horse_id']][1]:.1%}" for p,_ in OPTIONS]
        lines.append(f"|{int(r['horse_no'])} {r['horse_name']}|"+"|".join(cells)+"|")
    lines += ["", "## 限界", "", "GⅠ以外の時計/上がり・馬場補正・相手全頭の事前能力・ラップ/位置取りは未追加。海外後着の時計差/末脚は不明。対象日前でも資料の厳密な当時可用性は未証明。2021〜2025は参照済み。今回だけで当日の体重/馬場/価格を更新したことにしない。", ""]
    return "\n".join(lines)


def main():
    """旧基準を照合して4方式を比較し、選択と現在順位差を新規保存する。"""
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ("dataset","reference","facts","card","history","foreign","output"):parser.add_argument("--"+key,type=Path,required=True)
    args=parser.parse_args();require(not args.output.exists(),"material_output_exists");args.output.mkdir(parents=True)
    try:
        oldmanifest=read(args.reference/"manifest.json")
        for filename in ("sets.json","predictions.json","live-comparison.json"):
            require(hashlib.sha256((args.reference/filename).read_bytes()).hexdigest()==oldmanifest["outputs"][filename],"material_reference_sha")
        fmanifest=read(args.facts/"manifest.json")
        for filename in ("facts.json","links.json"):
            require(hashlib.sha256((args.facts/filename).read_bytes()).hexdigest()==fmanifest["outputs"][filename],"material_facts_sha")
        dataset=read(args.dataset); facts=read(args.facts/"facts.json");links=read(args.facts/"links.json")
        config=read(ROOT/"configs/research/race_conditions_elizabeth_v1.json")
        result=evaluate(read(args.reference/"sets.json")["N"],read(args.reference/"predictions.json"),dataset["history"],facts,links,config)
        require(len(result["predictions"])==72,"material_prediction_count")
        old=read(args.reference/"live-comparison.json")["international_connected"]["forecast"]
        card=read(args.card);foreign=read(args.foreign); history=read(args.history)
        require(card["race_key"]==old["race_key"] and {r["horse_id"] for r in card["runners"] if r["status"]=="active"}=={r["horse_id"] for r in old["runners"]},"material_live_identity")
        require(datetime.now(timezone.utc)<datetime.fromisoformat(card["start_at"]),"material_live_after_start")
        current_rows=[{**r,**feature(card,r,history,facts,links,foreign)} for r in card["runners"] if r["status"]=="active"]
        target={**{k:v for k,v in card.items() if k!="runners"},"rows":current_rows}
        evidence=group_deltas(result["examples"],target,{**config,"groups":GROUPS},{"half_life":None,"pooling":"hierarchical","shrinkage":20})
        current={"predictions":{p:combine(old,evidence,p,indices) for p,indices in OPTIONS},"features":current_rows,"evidence":evidence}
        require(current["predictions"]["baseline"]["runners"]==old["runners"],"material_live_baseline_changed")
        cov={"historic_runners":sum(len(t["rows"]) for t in result["examples"]),
            "historic_P":sum(r["values"]["g1_gap"] is not None for t in result["examples"] for r in t["rows"]),
            "historic_F":sum(r["values"]["g1_final3f"] is not None for t in result["examples"] for r in t["rows"]),
            "current_P":sum(r["values"]["g1_gap"] is not None for r in current_rows),"current_F":sum(r["values"]["g1_final3f"] is not None for r in current_rows)}
        for key in ("examples","predictions","annual","evidence"):save(args.output/(key+".json"),result[key])
        save(args.output/"summary.json",{k:v for k,v in result.items() if k not in ("examples","predictions","annual","evidence")})
        save(args.output/"current.json",current);save(args.output/"coverage.json",cov)
        (args.output/"report.md").write_text(report(result,current,cov),encoding="utf-8")
        inputs=[Path(__file__),ROOT/"src/jra_srb/jra_material_patterns.py",args.dataset,args.card,args.history,args.foreign,args.reference/"sets.json",args.reference/"predictions.json",args.reference/"live-comparison.json",args.facts/"facts.json",args.facts/"links.json",ROOT/"configs/research/race_conditions_elizabeth_v1.json",ROOT/".workstate/jra-srb/mile-championship-specific-research/spec/060-公式成績の時計差と末脚パーツ追加検証.md"]
        save(args.output/"manifest.json",{"inputs":{str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},"outputs":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}})
        print(json.dumps({"selection":result["selection"]["pattern"],"change_eligible":result["research_change_eligible"],"coverage":cov,
            "top3":{p:[r["horse_no"] for r in pred["runners"][:3]] for p,pred in current["predictions"].items()}},ensure_ascii=False))
    except Exception as error:
        save(args.output/"failure.json",{"type":type(error).__name__,"reason":getattr(error,"reason",str(error))});raise


if __name__=="__main__":main()
