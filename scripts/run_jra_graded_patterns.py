"""概要: 三重賞の固定4パターンを取得・比較し、汎用候補を保存する。
作成日: 2026-11-14。
入力: export/analyze、--output未使用フォルダー、保存dataset。
出力: dataset、全馬確率、年別指標、系列外選択、比較レポート・SHA。
実行例: uv run python scripts/run_jra_graded_patterns.py export --output artifacts/graded_export
注意事項: exportは研究reader SELECTのみ。analyzeはオフライン。2026結果・DB更新なし。
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jra_srb.jra_graded_patterns import export_additional, evaluate, selection_comparison
from jra_srb.jra_race_conditions import load_config, require
from jra_srb.jra_race_conditions_sql import ConditionsReader
from jra_srb.jra_research_contracts import digest


def save(path: Path, value: object) -> None:
    """JSONをUTF-8で保存する。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def report(result: dict, config: dict) -> str:
    """同名競走の成績と系列外選択を区別して日本語表にまとめる。"""
    names = {s["id"]: s["name"] for s in config["series"]}
    lines = ["# 三重賞・共通パターンの検証", "", "対象: エリザベス女王杯、武蔵野S、デイリー杯2歳S。",
             "2003〜2025の同名競走ごとに以前の年だけで集計。2026結果は含めない。事後属性を用いた探索的研究で、普遍性・利益・校正を証明しない。", "",
             "固定候補はroute=B+C、aptitude=D+E、attributes=A+C+D、balanced=全5群。採用群内で等配分、倍率1。旧32構成の分母5固定とは少数群の強度が異なる。",
             "A基本属性/B前走経路/C直近成績・間隔/D条件変更/E過去実績。一律と、エリザベスで凍結したv2も別の参照として保存。", "",
             "## 収録と評価", "", "| 系列 | 保存開催 | 出走行 | 保存履歴 | 評価開催 |", "|---|---:|---:|---:|---:|"]
    for s, d in result["diagnostics"].items():
        lines.append(f"| {names[s]} | {d['editions']} | {d['runners']} | {d['history_rows']} | {result['summary'][s]['balanced']['races']} |")
    lines += ["", "武蔵野/デイリー杯の保存履歴5,908行は共有の対象馬履歴で、二重に合算しない。", "",
              "## 固定パターンの比較（全評価年・探索値）", "", "| 系列 | パターン | Brier | 一律比改善 | logloss | 最上位の3着内率 |", "|---|---|---:|---:|---:|---:|"]
    for s, patterns in result["summary"].items():
        for p, m in patterns.items():
            skill = 1-m["brier"]/patterns["uniform"]["brier"]
            lines.append(f"| {names[s]} | {p} | {m['brier']:.6f} | {skill:.2%} | {m['logloss']:.6f} | {m['top1_top3_hit']:.1%} |")
    lines += ["", "## 過去だけでパターンを選んだ比較", "",
              "各評価年の前年までの検証5年以上で選択。他系列の同年結果も選択へ使わない。other_seriesは対象系列を選択から完全に外す。", "",
              "| 選択方式 | 評価年 | 系列均等の一律比改善 | 年ブロック参考95%区間 |", "|---|---|---:|---|"]
    for policy, outcome in result["outer"].items():
        lo, hi = outcome["macro_skill_interval95"]
        lines.append(f"| {policy} | {outcome['years'][0]}〜{outcome['years'][-1]} | {outcome['macro_skill_vs_uniform']:.2%} | [{lo:.2%}, {hi:.2%}] |")
    lines += ["", "| 系列 | 他2系列で選択した方式のBrier | 同期間の総合型 | 同期間の凍結v2 | 同期間の一律 |", "|---|---:|---:|---:|---:|"]
    for s, metrics in result["outer"]["other_series"]["series"].items():
        lines.append(f"| {names[s]} | {metrics['selected']['brier']:.6f} | {metrics['balanced']['brier']:.6f} | {metrics['frozen_v2']['brier']:.6f} | {metrics['uniform']['brier']:.6f} |")
    lines += ["", "## 候補と判定", "", f"全過去年を使った次回用共通候補: {result['final_common_choice']}。この選択自体は探索値。",
              f"非劣解の代表候補: {', '.join(result['representatives'])}。", f"共通優位の事前条件: {result['verdict']}。", "",
              "代表候補は固定4候補の中の非劣解。別枠の凍結v2は、強化総合型の参考として維持し、結果が良いことを省略しない。",
              "| 対象系列 | 系列外選択で採られた構成の回数 |", "|---|---|"]
    for s in names:
        counts = Counter(r["selected_pattern"] for r in result["selection"] if r["policy"] == "other_series" and r["series_id"] == s)
        lines.append(f"| {names[s]} | {dict(counts)} |")
    lines += ["", "## 特徴の識別力と制約", ""]
    for s, d in result["diagnostics"].items():
        constant = [f for f, v in d["features"].items() if v["distinct"] <= 1]
        unknown = {f: v["unknown"] for f, v in d["features"].items() if v["unknown"]}
        lines.append(f"- {names[s]}: 単一カテゴリ以下={constant}。未知件数={unknown}。")
    lines += ["- 2歳戦では年齢・同名前年実績等が識別に寄与しにくい。ダートでは過去実績もダート同条件だけを数える。",
              "- previous_gradeの未知件数には、原コード空欄の非重賞を旧方式がNoneへ変換する場合も含む。原条件が未確認という意味と同一ではない。",
              "- 保存内直近走であり、地方/海外の欠落や左端2003年より前の履歴は保証しない。長い休養と履歴不足を取り違えない。",
              "- 3系列だけの比較。代表候補を他の重賞・平場にも有効と認定しない。",
              "- 凍結v2はエリザベスの既使用過去から得た設定であり、同系列の独立未知成績ではない。",
              "- 数値は未校正の3着内周辺確率で、当日の購入候補・勝率ではない。", ""]
    return "\n".join(lines)


def main() -> int:
    """新規フォルダーに取得/比較の証跡を保存し、失敗は秘密なしで残す。"""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("export", "analyze"):
        child = sub.add_parser(command)
        child.add_argument("--output", type=Path, required=True)
        if command == "analyze":
            child.add_argument("--additional", type=Path, required=True)
            child.add_argument("--elizabeth", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "graded_output_exists")
    args.output.mkdir(parents=True)
    config = json.loads((ROOT / "configs/research/graded_common_patterns_v1.json").read_text(encoding="utf-8"))
    base = load_config(ROOT / "configs/research/race_conditions_elizabeth_v1.json")
    try:
        if args.command == "export":
            with ConditionsReader(base) as reader:
                value = export_additional(reader, config)
            save(args.output / "dataset.json", value)
            print(json.dumps({"status": "complete", "races": len(value["races"]), "history_rows": len(value["history"]), "RA_missing": len(value["provenance"]["raw_audit"]["missing_keys"])}))
        else:
            additional = json.loads(args.additional.read_text(encoding="utf-8"))
            require(additional["input_sha256"] == digest({k: v for k, v in additional.items() if k != "input_sha256"}), "graded_additional_sha")
            elizabeth = json.loads(args.elizabeth.read_text(encoding="utf-8"))
            datasets = {"elizabeth": elizabeth}
            for series in ("musashino", "daily2"):
                dataset = {"races": [r for r in additional["races"] if r["series_id"] == series], "history": additional["history"]}
                dataset["input_sha256"] = digest(dataset)
                datasets[series] = dataset
            value = evaluate(datasets, base, config)
            value["outer"] = selection_comparison(value, config)
            skills = {p["id"]: [1-value["summary"][s][p["id"]]["brier"]/value["summary"][s]["uniform"]["brier"] for s in datasets] for p in config["patterns"]}
            frontier = [p for p in skills if not any(all(a >= b-1e-12 for a, b in zip(skills[q], skills[p])) and any(a > b+1e-12 for a, b in zip(skills[q], skills[p])) for q in skills if q != p)]
            value["representatives"] = sorted(frontier, key=lambda p: (-sum(skills[p]), p))[:3]
            external = value["outer"]["other_series"]
            all_positive = all(m["selected"]["brier"] < m["uniform"]["brier"] for m in external["series"].values())
            value["verdict"] = "promising_within_three_series" if all_positive and external["macro_skill_interval95"][0] > 0 else "common_advantage_not_established"
            for key in ("predictions", "annual", "selection", "diagnostics"):
                save(args.output / (key+".json"), value[key])
            save(args.output / "summary.json", {k: v for k, v in value.items() if k not in ("predictions", "annual", "selection")})
            with (args.output / "annual.csv").open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(value["annual"][0]))
                writer.writeheader(); writer.writerows(value["annual"])
            (args.output / "report.md").write_text(report(value, config), encoding="utf-8")
            print(json.dumps({"status": "complete", "verdict": value["verdict"], "choice": value["final_common_choice"], "representatives": value["representatives"], "prediction_count": len(value["predictions"])}))
        sources = [Path(__file__), ROOT / "configs/research/graded_common_patterns_v1.json", ROOT / "configs/research/race_conditions_elizabeth_v1.json",
                   *[ROOT / "src/jra_srb" / name for name in ("jra_graded_patterns.py", "jra_race_conditions.py", "jra_race_conditions_sql.py",
                      "jra_conditions_refinement.py", "jra_conditions_search.py", "jra_conditions_stability.py", "jra_research_reader.py")]]
        if args.command == "analyze":
            sources += [args.additional, args.elizabeth]
        save(args.output / "manifest.json", {"config_sha256": digest(config), "inputs": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
            "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}})
        return 0
    except Exception as error:
        safe = {"status": "failed", "reason": getattr(error, "reason", "graded_execution_failed"), "error_type": type(error).__name__}
        save(args.output / "failure.json", safe)
        print(json.dumps(safe)); return 4


if __name__ == "__main__":
    raise SystemExit(main())
