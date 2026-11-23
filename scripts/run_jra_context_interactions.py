"""概要: 福島記念の格×着順・再対戦斤量を8固定方式で追加検証する。
作成日: 2026-11-21
入力: --dataset、--reference（直接対決の旧出力）、--output（未使用先）。
出力: 144予測、特徴・根拠・追加除去比較・レポート・SHA、失敗時は非0。
実行例: uv run python scripts/run_jra_context_interactions.py --help
注意事項: オフライン。最良候補の自動選択・未知性能の認定・実購入なし。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jra_srb.jra_context_interactions import evaluate
from jra_srb.jra_race_conditions import require
from jra_srb.jra_specific_patterns import mean_metrics


def read(path: Path):
    """UTF-8のJSONを読み込む。"""
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value) -> None:
    """JSONをUTF-8で保存する。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def report(result: dict) -> str:
    """8方式の精度、主比較、年度差、欠測を固定構成で表示する。"""
    lines = ["# 福島記念 格×着順・相対斤量変化の追加検証", "", "## 定義と範囲", "",
             "C=直近走の確認済み格×着順カテゴリ。非ABCは非重賞等を一括しており、条件戦の細かなクラスまでは分けていない。",
             "W=過去730日以内の芝・今回距離±200mで相手ごとの最新対戦を使い、今回の斤量差−過去の斤量差を計算。過去先着/後着相手に分けて平均し、±1kgで分類。負が相対軽化。",
             "G=既存一般評価、H=既存直接対決。H/C/Wの追加倍率各0.5、縮約20を固定。8方式×18年=144予測。最良方式を選び直していない。", "",
             "## 参照済み2021〜2025年の精度", "", "低いBrier/loglossほど良い。上位捕捉は同率を按分。今回の再検証は探索的であり、本採用・独立確認済みとはしない。", "",
             "| 方式 | Brier | logloss | 最上位3着内率 | 上位3捕捉/開催 | 上位6捕捉/開催 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    patterns = list(dict.fromkeys(r["pattern"] for r in result["annual"]))
    for pattern in patterns:
        rows = [r for r in result["annual"] if r["pattern"] == pattern and "2021" <= r["race_date"][:4] <= "2025"]
        m = mean_metrics(rows)
        lines.append(f"| {pattern} | {m['brier']:.6f} | {m['logloss']:.6f} | {m['top1_top3_hit']:.1%} | {m['top3_captured']:.3f} | {m['top6_captured']:.3f} |")
    lines += ["", "## 事前に固定した主比較", ""]
    for key in result["primary_comparison_keys"]:
        c = result["comparisons"][key]
        added, base = key.split("_vs_")
        lines += [f"### {key}", "", f"Brier相対改善 {c['brier_relative_improvement']:.2%}、改善{c['improved_years']}/5年、参考95%区間 {c['interval95']}。",
                  f"参考基準を全て満たす: {c['reference_conditions_met']}。本採用False（参照済み期間）。", "",
                  "| 年 | 追加ありBrier | 追加なしBrier | 差 | 追加あり上位3捕捉 | 追加なし上位3捕捉 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for a,b in zip(c["annual"][added],c["annual"][base],strict=True):
            lines.append(f"| {a['race_date']} | {a['brier']:.6f} | {b['brier']:.6f} | {a['brier']-b['brier']:+.6f} | {a['top3_captured']:.3f} | {b['top3_captured']:.3f} |")
        lines += ["", "開発2008〜2020年の参考値。ここから追加係数や方式を選択し直していない。", ""]
        for p,m in c["development"].items():
            lines.append(f"- {p}: Brier {m['brier']:.6f}、上位3捕捉 {m['top3_captured']:.3f}。")
        lines.append("")
    lines += ["## 条件を固定した追加除去比較", "", "H/Wを固定したCの有無、H/Cを固定したWの有無もsummary.jsonへ全件保存した。主比較以外から結果の良い方式だけを取り上げて採用しない。", "",
              "## パーツのカバー率", "", "| 年 | 頭数 | 格×着順あり | 後着相手の斤量比較あり | 先着相手の斤量比較あり |", "| --- | ---: | ---: | ---: | ---: |"]
    for r in result["coverage"]:
        lines.append(f"| {r['race_date']} | {r['runners']} | {r['class_known']} | {r['lost_weight_known']} | {r['won_weight_known']} |")
    lines += ["", "## 限界と次の扱い", "", "格は実際の相手能力の代理で、16カテゴリの小標本や既存格/着順との情報重複がある。斤量変化は秒数や勝敗逆転へ換算しない。未対戦・欠測は差分0。頭数・展開・馬場・調子などの条件差は残る。",
              "データは保存済みの事後属性。海外等の履歴欠落と2003年の左端欠落に注意。2021〜2025年は既に仮説検討に参照している。参考基準を満たしても未知性能の実証としない。",
              "対戦相手全頭の能力推定・ペース/位置取り・時計/着差の学習特徴は未実装。2026当日予想・価格・買い目・回収率は今回作成していない。", ""]
    return "\n".join(lines)


def main() -> int:
    """入力と旧比較出力のSHAを確認し、新規出力先に検証結果を保存する。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",type=Path,required=True)
    parser.add_argument("--reference",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    require(not args.output.exists(),"interaction_output_exists")
    args.output.mkdir(parents=True)
    try:
        dataset_manifest=args.dataset.parent/"manifest.json"
        source_sha=hashlib.sha256(args.dataset.read_bytes()).hexdigest()
        require(args.dataset.name=="fukushima-normalized.json" and read(dataset_manifest)["files"][args.dataset.name]==source_sha,"interaction_dataset_sha")
        previous_manifest=args.reference/"manifest.json"
        pm=read(previous_manifest)
        require(any(Path(k).resolve()==args.dataset.resolve() and v==source_sha for k,v in pm["inputs"].items()),"interaction_reference_dataset")
        reference={}
        reference_paths=[]
        for key in ("examples","evidence","predictions","uniform_reference"):
            path=args.reference/(key+".json")
            require(hashlib.sha256(path.read_bytes()).hexdigest()==pm["outputs"][path.name],"interaction_reference_sha")
            reference[key]=read(path)
            reference_paths.append(path)
        config_path=ROOT/"configs/research/fukushima_context_interactions_v1.json"
        general_path=ROOT/"configs/research/race_conditions_elizabeth_v1.json"
        config=read(config_path)
        result=evaluate(read(args.dataset),reference,config,read(general_path))
        for key in ("predictions","annual","class_examples","weight_examples","evidence","coverage"):
            save(args.output/(key+".json"),result[key])
        save(args.output/"summary.json",{k:v for k,v in result.items() if k not in ("predictions","annual","class_examples","weight_examples","evidence","coverage")})
        (args.output/"report.md").write_text(report(result),encoding="utf-8")
        paths=[Path(__file__),args.dataset,dataset_manifest,previous_manifest,config_path,general_path,*reference_paths,
               *[ROOT/"src/jra_srb"/name for name in ("jra_context_interactions.py","jra_head_to_head.py","jra_specific_patterns.py","jra_conditions_refinement.py","jra_conditions_search.py","jra_race_conditions.py","jra_graded_patterns.py")]]
        save(args.output/"manifest.json",{"inputs":{str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
             "outputs":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()},"baseline_predictions_exactly_reproduced":36})
        print(json.dumps({k:{"brier_improvement":result["comparisons"][k]["brier_relative_improvement"],"reference_conditions_met":result["comparisons"][k]["reference_conditions_met"],"adopted":False} for k in result["primary_comparison_keys"]},ensure_ascii=False))
        return 0
    except Exception as error:
        value={"error_type":type(error).__name__,"reason":getattr(error,"reason","interaction_execution_failed")}
        save(args.output/"failure.json",value)
        print(json.dumps(value))
        return 4


if __name__=="__main__":
    raise SystemExit(main())
