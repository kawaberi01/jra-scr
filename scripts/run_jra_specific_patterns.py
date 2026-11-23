"""概要: 監査済み履歴から重賞専用30候補を比較し、固定年度で採否を保存する。
作成日: 2026-11-20
入力: --series、--dataset、--output（未使用先）、隣接する取得manifest。
出力: 予測・根拠・年別指標・選択・レポート・SHA、失敗時は非0。
実行例: uv run python scripts/run_jra_specific_patterns.py --series fukushima --dataset artifacts/jra_research/graded_specific_20261120_coverage/fukushima-normalized.json --output artifacts/jra_research/fukushima_specific_v1
注意事項: オフライン専用。SQL/API・DB更新・実購入・旧成果物の上書きなし。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jra_srb.jra_specific_patterns import evaluate
from jra_srb.jra_race_conditions import require


def save(path: Path, data: object) -> None:
    """JSONをUTF-8で保存する。"""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def report(result: dict) -> str:
    """主軸・補助・採否・年度別比較を毎回同じ構成で出力する。"""
    chosen = result["selection"]["candidate"]
    confirm = result["confirmation"]
    selected = chosen["pattern"]
    lines = [f"# {result['race_name']} 専用パーツ検証", "", "## 主軸群", "",
             f"開発2008〜2020年で選択: {selected}。{'＋'.join(chosen['groups'])}。", "",
             "4群15部分集合×固有単独/補助混合=30候補。一般・一律を含む32方式×18年=576予測。", "",
             "## 補助群", "", "既存14特徴の一般基準を1/3加える。" if chosen["blend"] else "選択候補は固有パーツのみ。一般基準は別比較。",
             "一般基準も同名過去年で集計しており、平場の共通モデルではない。", "",
             "## 採否", "", "一般基準に対して有望（将来の利益・校正は未証明）。" if confirm["adopted"] else "専用方式の優位未確認。最終年の最良候補へ切り替えず、一般基準を参考として保持する。",
             f"Brier相対改善: {confirm['brier_relative_improvement']:.2%}。改善年{confirm['improved_years']}/5。差の参考95%区間{confirm['interval95']}。", "",
             "| 採否条件 | 達成 |", "| --- | --- |"]
    lines += [f"| {key} | {value} |" for key, value in confirm["checks"].items()]
    lines += ["", "## 年度別指標", "", "2021〜2025年の最終確認。開催を均等配分。低いBrier/loglossほど良い。", "",
              "| 方式 | Brier | logloss | 最上位の3着内率 | 上位3捕捉/開催 | 上位6捕捉/開催 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for key, row in confirm["summaries"].items():
        lines.append(f"| {key} | {row['brier']:.6f} | {row['logloss']:.6f} | {row['top1_top3_hit']:.1%} | {row['top3_captured']:.3f} | {row['top6_captured']:.3f} |")
    lines += ["", "## 改善と悪化", "", "| 年 | 専用候補Brier | 一般Brier | 差 | 専用上位3捕捉 | 一般上位3捕捉 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for a, b in zip(confirm["annual"][selected], confirm["annual"]["general"], strict=True):
        lines.append(f"| {a['race_date']} | {a['brier']:.6f} | {b['brier']:.6f} | {a['brier']-b['brier']:+.6f} | {a['top3_captured']:.3f} | {b['top3_captured']:.3f} |")
    lines += ["", "### 開催場別（2008〜2025、開発年を含む探索的な参考）", "", "| 場コード | 方式 | 開催 | Brier |", "| --- | --- | ---: | ---: |"]
    for venue, patterns in result["venue_summary"].items():
        for key, m in patterns.items():
            lines.append(f"| {venue} | {key} | {m['races']} | {m['brier']:.6f} |")
    lines += ["", "## 欠測・対象外", "", f"専用特徴の欠測件数: {result['missing_features']}。",
              "事後版属性・初期年の左端欠落・海外/地方履歴不足がある。収録内確認なしは真の実績なしを意味しない。",
              "5年の確認しかなく、同じ過去への反復研究による楽観性の限界も残る。時計・着差・ラップ・当日馬場/体重・オッズは今回の入力に含めない。",
              "群組合せはカテゴリ差分の加算であり、条件交互作用を学習したものではない。適性・実績の相関にも注意。", "",
              "## 次の課題", "", "採否を保持したまま2026年カード・過去走の充足、取消、当日状態、市場価格を確認して初めて当日へ接続する。",
              "今回の出力は過去検証であり、当日予想・購入指示ではない。最終5年を見てから係数や候補を再調整しない。", ""]
    return "\n".join(lines)


def main() -> int:
    """入力SHAを確認して未使用先へ保存し、エラーを秘密なしで記録する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--series", choices=("fukushima", "mile"), required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "specific_output_exists")
    args.output.mkdir(parents=True)
    try:
        manifest_path = args.dataset.parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        require(args.dataset.name == args.series+"-normalized.json", "specific_dataset_series")
        require(hashlib.sha256(args.dataset.read_bytes()).hexdigest() == manifest["files"][args.dataset.name], "specific_input_sha")
        config_path = ROOT / "configs/research/graded_specific_patterns_v1.json"
        general_path = ROOT / "configs/research/race_conditions_elizabeth_v1.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        general = json.loads(general_path.read_text(encoding="utf-8"))
        data = json.loads(args.dataset.read_text(encoding="utf-8"))
        result = evaluate(data, args.series, config, general)
        for key in ("predictions", "annual", "evidence", "examples"):
            save(args.output / (key+".json"), result[key])
        save(args.output / "summary.json", {k: v for k, v in result.items() if k not in ("predictions", "annual", "evidence", "examples")})
        with (args.output / "annual.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(result["annual"][0]))
            writer.writeheader()
            writer.writerows(result["annual"])
        (args.output / "report.md").write_text(report(result), encoding="utf-8")
        sources = [Path(__file__), config_path, general_path, args.dataset, manifest_path,
                   *[ROOT / "src/jra_srb" / f for f in ("jra_specific_patterns.py", "jra_conditions_refinement.py",
                     "jra_conditions_search.py", "jra_race_conditions.py", "jra_graded_patterns.py", "jra_research_contracts.py")]]
        save(args.output / "manifest.json", {"protocol": config["protocol"], "inputs": {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
             "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}})
        print(json.dumps({"series": args.series, "selected": result["selection"]["candidate"]["pattern"],
                          "adopted": result["confirmation"]["adopted"], "confirmation": result["confirmation"]["summaries"]}, ensure_ascii=False))
        return 0
    except Exception as error:
        safe = {"error_type": type(error).__name__, "reason": getattr(error, "reason", "specific_execution_failed")}
        save(args.output / "failure.json", safe)
        print(json.dumps(safe))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
