"""概要: マイルCS追加比較と今年の海外接続参考予想を新規保存する。
作成日: 2026-11-21
入力: --dataset、--card、--history、--foreign、--output。
出力: 時系列比較、選択、参考予想、寄与、来歴SHA、失敗時非0。
実行例: uv run python scripts/run_jra_mile_extension.py --help
注意事項: 結果APIを呼ばず、DB・旧出力を変更しない。保存先は未使用先限定。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from jra_srb.jra_mile_extension import evaluate, forecast, options
from jra_srb.jra_specific_patterns import mean_metrics
from jra_srb.jra_race_conditions import require


def read(path: Path):
    """UTF-8 JSONを読む。"""
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value) -> None:
    """新規JSONを作り、不正な浮動小数値を拒否する。"""
    with path.open("x",encoding="utf-8") as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False)


def report(result: dict) -> str:
    """候補を全件列挙し、選択と既知期間の限界を固定形式で示す。"""
    lines = ["# マイルCS H/C/W追加比較", "",f"開発年選択: {result['selection']['selected']['pattern']}。2008〜2020年の捕捉非悪化制約付きBrier最小。", "",
             "2021〜2025年は参照済みの探索的確認。本採用・未知性能の実証ではない。", "",
             "|方式|開発Brier|開発上位3捕捉|確認Brier|確認上位3捕捉|確認上位6捕捉|", "|---|---:|---:|---:|---:|---:|"]
    for o in options():
        p = o["pattern"]; d = result["selection"]["development"][p]
        m = mean_metrics([r for r in result["annual"] if r["pattern"] == p and "2021" <= r["race_date"][:4] <= "2025"])
        lines.append(f"|{p}|{d['brier']:.6f}|{d['top3_captured']:.3f}|{m['brier']:.6f}|{m['top3_captured']:.3f}|{m['top6_captured']:.3f}|")
    c = result["confirmation"]
    lines += ["",f"選択版の対G Brier相対改善: {c['brier_relative_improvement']:.2%}。改善{c['improved_years']}/5年。差の参考95%区間: {c['interval95']}。",f"参考条件: {c['checks']}。条件全充足: {c['reference_conditions_met']}。本採用False。", "",
              "N=専用近況、G=一般5群、H=国内直接対決、C=格×着順、W=再対戦相対斤量。各追加0.5、縮約20、730日・±200m・±1kg固定。",
              "海外は歴年の網羅がなく、今年の実前走を接続する感度を別保存。組確率・期待収益を算出していない。結果を見た候補追加/係数調整は行わない。", ""]
    return "\n".join(lines)


def main() -> int:
    """入力SHAと旧基準の再現を確認し、発走前に新規研究成果物を保存する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("dataset","card","history","foreign","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args = parser.parse_args()
    require(not args.output.exists(),"mile_output_exists")
    args.output.mkdir(parents=True)
    try:
        config_path = ROOT/"configs/research/mile_extension_v1.json"
        specific_path = ROOT/"configs/research/graded_specific_patterns_v1.json"
        general_path = ROOT/"configs/research/race_conditions_elizabeth_v1.json"
        cfg,sc,gc = read(config_path),read(specific_path),read(general_path)
        require((cfg["addition_scale"],cfg["lookback_days"],cfg["distance_tolerance_m"],cfg["weight_band_kg"]) == (.5,730,200,1),"mile_protocol")
        dataset = read(args.dataset)
        sha = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
        require(read(args.dataset.parent/"manifest.json")["files"][args.dataset.name] == sha,"mile_dataset_sha")
        result = evaluate(dataset,cfg,sc,gc)
        old_path = ROOT/"artifacts/jra_research/mile_specific_v1_1_20261120/predictions.json"
        old = {(r["race_key"],r["pattern"]):r for r in read(old_path)}
        checked = 0
        for p in result["predictions"]:
            if p["pattern"] in ("G","N"):
                prior = old[(p["race_key"],"general" if p["pattern"] == "G" else "S04-only")]
                require(p["runners"] == prior["runners"],"mile_old_baseline_mismatch")
                checked += 1
        require(checked == 36 and len(result["predictions"]) == 288,"mile_count")
        card = read(args.card)
        require(datetime.now(timezone.utc) < datetime.fromisoformat(card["start_at"]),"mile_after_start")
        live = forecast(result,card,read(args.history),read(args.foreign),cfg,sc,gc)
        for key in ("predictions","annual","evidence","sets"):
            save(args.output/(key+".json"),result[key])
        save(args.output/"summary.json",{k:v for k,v in result.items() if k not in ("predictions","annual","evidence","sets")})
        save(args.output/"live-comparison.json",live)
        (args.output/"report.md").write_text(report(result),encoding="utf-8")
        inputs = [Path(__file__),args.dataset,args.dataset.parent/"manifest.json",args.card,args.history,args.foreign,config_path,specific_path,general_path,old_path,
                  *[ROOT/"src/jra_srb"/n for n in ("jra_mile_extension.py","jra_context_interactions.py","jra_head_to_head.py","jra_specific_patterns.py","jra_conditions_refinement.py","jra_race_conditions.py","jra_graded_patterns.py")]]
        save(args.output/"manifest.json",{"created_at":datetime.now(timezone.utc).isoformat(),"baseline_reproduced":checked,
            "inputs":{str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs},
            "outputs":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}})
        print(json.dumps({"selected":result["selection"]["selected"],"confirmation":result["confirmation"]["checks"],
            "top6":live["international_connected"]["forecast"]["runners"][:6]},ensure_ascii=False))
        return 0
    except Exception as error:
        save(args.output/"failure.json",{"type":type(error).__name__,"reason":getattr(error,"reason",str(error))})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
