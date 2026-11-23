"""概要: 福島記念の直接対決パーツ追加を4固定方式で再検証する。
作成日: 2026-11-21
入力: --dataset、--baseline、--output、任意の--current-input。
出力: 72予測、対戦根拠、追加前後の精度・カバー率、SHA、任意の保存時点対戦表。
実行例: uv run python scripts/run_jra_head_to_head.py --help
注意事項: オフライン。既知期間の探索的再検証。SQL/API取得・本採用・実購入なし。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jra_srb.jra_head_to_head import evaluate, features
from jra_srb.jra_race_conditions import require


def read(path: Path):
    """UTF-8のJSONを読む。"""
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value) -> None:
    """JSONをUTF-8で保存する。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def checked(path: Path, manifest: Path, relative: str) -> dict:
    """既存取得manifestの本文SHAを確認してからデータを読む。"""
    require(hashlib.sha256(path.read_bytes()).hexdigest() == read(manifest)["files"][relative], "h2h_input_sha")
    return read(path)


def snapshot(folder: Path, config: dict) -> dict:
    """保存済み2026カードだけで対戦説明と同一競走時計差を作る。最新予想ではない。"""
    card = checked(folder / "official-reviewed/fukushima-card.json", folder / "manifest.json", "official-reviewed/fukushima-card.json")
    history = checked(folder / "fukushima/normalized-jra-history.json", folder / "manifest.json", "fukushima/normalized-jra-history.json")
    raw = checked(folder / "fukushima/profile-history.json", folder / "manifest.json", "fukushima/profile-history.json")
    rows = [r for r in card["runners"] if r["status"] == "active"]
    result = features(card, rows, history, config)
    clocks = {}
    for h in raw:
        match = re.fullmatch(r"(\d+):(\d{2})\.(\d+)", h.get("time_raw") or "")
        if match and h["race_key"]:
            clocks[(h["race_key"], h["horse_id"])] = int(match[1])*60+int(match[2])+float("0."+match[3])
    for hid, record in result.items():
        for meetings in record["meetings"].values():
            for meeting in meetings:
                own = clocks.get((meeting["race_key"], hid))
                other = clocks.get((meeting["race_key"], meeting["opponent_id"]))
                meeting["own_minus_opponent_seconds"] = round(own-other, 3) if own is not None and other is not None else None
    return {"purpose": "saved_snapshot_explanation_not_current_prediction", "observed_at": card["observed_at"],
            "race_date": card["race_date"], "runners": rows, "head_to_head": result,
            "time_gap_is_explanatory_only": True}


def report(result: dict) -> str:
    """追加前後の精度・悪化・カバー率を固定構成で表示する。"""
    lines = ["# 福島記念 直接対決パーツの追加検証", "", "## 比較の範囲", "",
             "過去730日の芝対戦で、今回の相手ごとに直近1回の先着関係を使う。全芝/当該距離±200mの2特徴。対戦なしは欠測・差分0。",
             "一般/一般+対戦/近況/近況+対戦の4方式×18年=72予測。追加強度0.5、縮約20を固定。利益・馬券・相手全頭の能力推定は対象外。", "",
             "## 精度と判定", "", "2021〜2025年は参照済みのため、改善しても探索的候補。本採用や独立確認済みとしない。", ""]
    for key, comparison in result["comparisons"].items():
        lines += [f"### {key}", "", f"確率誤差の相対改善 {comparison['brier_relative_improvement']:.2%}、改善{comparison['improved_years']}/5年、差の参考95%区間 {comparison['interval95']}。",
                  f"既存参考条件を全て満たす: {comparison['reference_conditions_met']}。本採用: False（既知期間の追加検証）。", "",
                  "| 方式 | Brier（低いほど良い） | logloss | 最上位3着内率 | 上位3捕捉/開催 | 上位6捕捉/開催 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for p, m in comparison["summaries"].items():
            lines.append(f"| {p} | {m['brier']:.6f} | {m['logloss']:.6f} | {m['top1_top3_hit']:.1%} | {m['top3_captured']:.3f} | {m['top6_captured']:.3f} |")
        lines += ["", "| 参考条件 | 達成 |", "| --- | --- |"]
        lines += [f"| {name} | {value} |" for name, value in comparison["checks"].items()]
        added, base = key.split("_vs_")
        lines += ["", "| 年 | 追加ありBrier | 追加なしBrier | 差 | 追加あり上位3捕捉 | 追加なし上位3捕捉 |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for a, b in zip(comparison["annual"][added], comparison["annual"][base], strict=True):
            lines.append(f"| {a['race_date']} | {a['brier']:.6f} | {b['brier']:.6f} | {a['brier']-b['brier']:+.6f} | {a['top3_captured']:.3f} | {b['top3_captured']:.3f} |")
        lines += ["", "開発2008〜2020年の参考比較（ここで重みや方式を選び直していない）。", ""]
        for p, m in comparison["development"].items():
            lines.append(f"- {p}: Brier {m['brier']:.6f}、上位3捕捉 {m['top3_captured']:.3f}。")
        lines.append("")
    lines += ["## 対戦カバー率", "", "| 年 | 出走頭数 | 全芝の対戦相手あり | 近距離の対戦相手あり |", "| --- | ---: | ---: | ---: |"]
    for row in result["coverage"]:
        lines.append(f"| {row['race_date']} | {row['runners']} | {row['any_comparison']} | {row['near_comparison']} |")
    lines += ["", "## 限界・次の扱い", "", "直接対決なしを後着扱いしない。少数対戦と特徴同士の相関、斤量・時期・馬場・距離の違いが残る。根拠に条件差を併記したが、その影響を因果的に補正したわけではない。",
              "同じ相手の反復対戦は直近だけにする。時計差は当日スナップショットの説明に限り、歴年へ不均等に投入しない。海外/地方の欠落と2003年の左端欠落も残る。",
              "追加前の一般/近況予測はv1.1保存予測と照合済み。最終5年を見て730日・200m・強度を再調整していない。今回結果だけで今年の買い目へ本採用しない。", ""]
    return "\n".join(lines)


def main() -> int:
    """入力SHAと既存基準の再現を確認して新しい出力先へ検証を保存する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--current-input", type=Path)
    args = parser.parse_args()
    require(not args.output.exists(), "h2h_output_exists")
    args.output.mkdir(parents=True)
    try:
        config_path = ROOT / "configs/research/head_to_head_fukushima_v1.json"
        original_path = ROOT / "configs/research/graded_specific_patterns_v1.json"
        general_path = ROOT / "configs/research/race_conditions_elizabeth_v1.json"
        config = read(config_path)
        require(config["lookback_days"] == 730 and config["distance_tolerance_m"] == 200 and config["head_to_head_scale"] == .5, "h2h_fixed_protocol")
        require(args.dataset.name == "fukushima-normalized.json", "h2h_dataset_scope")
        data = checked(args.dataset, args.dataset.parent / "manifest.json", args.dataset.name)
        result = evaluate(data, config, read(original_path), read(general_path))
        baseline_manifest = read(args.baseline / "manifest.json")
        prior = checked(args.baseline / "predictions.json", args.baseline / "manifest.json", "predictions.json") if "files" in baseline_manifest else read(args.baseline / "predictions.json")
        require(hashlib.sha256((args.baseline / "predictions.json").read_bytes()).hexdigest() == baseline_manifest["outputs"]["predictions.json"], "h2h_baseline_sha")
        old = {(p["race_key"], p["pattern"]): p for p in prior}
        for p in result["predictions"]:
            if p["pattern"] not in ("general", "near"):
                continue
            q = old[(p["race_key"], "S04-only" if p["pattern"] == "near" else "general")]
            require(p["runners"] == q["runners"], "h2h_baseline_changed")
        for key in ("predictions", "annual", "examples", "evidence", "coverage", "uniform_reference"):
            save(args.output / (key+".json"), result[key])
        save(args.output / "summary.json", {k: v for k, v in result.items() if k not in ("predictions", "annual", "examples", "evidence", "coverage", "uniform_reference")})
        if args.current_input:
            save(args.output / "snapshot-explanation.json", snapshot(args.current_input, config))
        (args.output / "report.md").write_text(report(result), encoding="utf-8")
        paths = [Path(__file__), args.dataset, args.dataset.parent / "manifest.json", args.baseline / "predictions.json", args.baseline / "manifest.json",
                 config_path, original_path, general_path, *[ROOT / "src/jra_srb" / n for n in ("jra_head_to_head.py", "jra_specific_patterns.py", "jra_conditions_refinement.py", "jra_race_conditions.py", "jra_conditions_search.py", "jra_graded_patterns.py")]]
        if args.current_input:
            paths += [args.current_input / "manifest.json", args.current_input / "official-reviewed/fukushima-card.json",
                      args.current_input / "fukushima/normalized-jra-history.json", args.current_input / "fukushima/profile-history.json"]
        save(args.output / "manifest.json", {"inputs": {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
             "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}, "baseline_predictions_exactly_reproduced": 36})
        print(json.dumps({k: {"brier_improvement": v["brier_relative_improvement"], "reference_conditions_met": v["reference_conditions_met"], "adopted": False} for k, v in result["comparisons"].items()}, ensure_ascii=False))
        return 0
    except Exception as error:
        safe = {"error_type": type(error).__name__, "reason": getattr(error, "reason", "h2h_execution_failed")}
        save(args.output / "failure.json", safe)
        print(json.dumps(safe))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
