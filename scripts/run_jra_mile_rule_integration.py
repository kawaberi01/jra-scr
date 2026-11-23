"""概要: 固定25複合条件を旧マイル版へ統合比較し、根拠と今年の予想差を保存する。
作成日: 2026-11-22
入力: --output 新規出力先。固定研究成果物、当日照合入力、保存履歴。
出力: 全918予測、条件明細/成績、選択、今年全方式、SHA、失敗証跡。
実行例: uv run python scripts/run_jra_mile_rule_integration.py --output artifacts/jra_research/mile_integration_v1_20261122
注意事項: 結果取得・DB書込み・実購入なし。旧版を変更せず未使用先へ保存する。
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from jra_srb.jra_mile_rule_integration import ATOMS, rules, features, evaluate, combine
from jra_srb.jra_conditions_refinement import group_deltas
from jra_srb.jra_specific_patterns import mean_metrics
from jra_srb.jra_race_conditions import require


def read(path):
    """UTF-8 JSONを読み込む。"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(path, value):
    """未使用ファイルへJSONを書き、既存成果物の上書きを拒否する。"""
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def report(result, current):
    """条件の四区分成績と固定探索の選択/非採用を読みやすく表示する。"""
    lines = ["# マイルCS・複合条件統合版v1", "", f"開発選択: {result['selection']['pattern']}。今回予想に使用: {result['forecast_pattern']}。", "",
             "25ルール×単独/統合＋基準＝51方式、18年918予測。参照済み過去の探索的比較で、未知性能や利益を実証していません。", "",
             "## 条件ごとの過去成績", "", "1着－2着－3着－着外。取消は除外。欠測は不明群へ分離。", "",
             "|条件ID・内容|該当|非該当|不明|", "|---|---|---|---|"]
    for record in result["rule_records"]:
        g = record["groups"]
        lines.append(f"|{record['id']}：{record['label']}|{g['true']['record']}|{g['false']['record']}|{g['unknown']['record']}|")
    lines += ["", "救済は親消去群/救済/残る割引候補の内訳をrule-records.jsonへ保存。全馬の原子判定と参照過去走はexamples.json。", "",
              "## 全方式の開発/確認比較", "", "|方式|開発Brier|開発上位3捕捉|確認Brier|確認上位3捕捉|確認上位6捕捉|", "|---|---:|---:|---:|---:|---:|"]
    for name, dev in sorted(result["selection"]["development"].items(), key=lambda x: x[1]["brier"]):
        known = mean_metrics([r for r in result["annual"] if r["pattern"] == name and "2021" <= r["race_date"][:4] <= "2025"])
        lines.append(f"|{name}|{dev['brier']:.6f}|{dev['top3_captured']:.3f}|{known['brier']:.6f}|{known['top3_captured']:.3f}|{known['top6_captured']:.3f}|")
    lines += ["", "## 選択版の参照確認", "", json.dumps(result["comparison"], ensure_ascii=False, indent=2), "",
              "## 今年の全頭判定", "", "|馬番・馬名|"+"|".join(ATOMS.values())+"|", "|---|"+"|".join("---" for _ in ATOMS)+"|"]
    for r in sorted(current["features"], key=lambda r: int(r["horse_no"])):
        lines.append(f"|{int(r['horse_no'])} {r['horse_name']}|"+"|".join("○" if r["atoms"][k] is True else "×（実績は収録内）" if r["atoms"][k] is False else "不明" for k in ATOMS)+"|")
    lines += ["", "## 未実装/限界", "", *["- "+r["condition"]+"："+r["reason"] for r in result["unavailable"]],
              "- 歴年の海外欠落、過去カードの事後属性、条件提案の事後性、探索の多重比較が残る。人気は今回主モデルへ不使用。生産者条件や持続力を推測で埋めない。", ""]
    return "\n".join(lines)


def main():
    """旧版不変を照合して研究を実行し、全ての判定と版を新規保存する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "integration_output_exists")
    args.output.mkdir(parents=True)
    try:
        frozen = ROOT/"artifacts/jra_research/mile_integration_v1_20261122_frozen/manifest.json"
        for filename, expected in read(frozen)["files"].items():
            require(hashlib.sha256((ROOT/filename).read_bytes()).hexdigest() == expected, "integration_frozen_mismatch")
        ref = ROOT/"artifacts/jra_research/mile_extension_v1_20261121"
        datafile = ROOT/"artifacts/jra_research/graded_specific_20261120_coverage/mile-normalized.json"
        configfile = ROOT/"configs/research/mile_rule_integration_v1.json"
        config = read(configfile)
        require(config == {"protocol": "mile-rule-integration-v1", "development": [2008, 2020], "confirmation": [2021, 2025], "rule_count": 25,
                           "method_count": 51, "minimum_support": 20, "minimum_editions": 5, "shrinkage": 20, "addition_scale": .5,
                           "purchase_approved": False, "independent_validation": False}, "integration_config_changed")
        data = read(datafile)
        generalfile = ROOT/"configs/research/race_conditions_elizabeth_v1.json"
        result = evaluate(read(ref/"sets.json")["N"], read(ref/"predictions.json"), data["history"], data["target_rows"], read(generalfile))
        require(len(result["predictions"]) == 18*(1+2*len(rules())), "integration_prediction_count")
        inputs = ROOT/"artifacts/jra_research/mile_integration_v1_20261122_inputs"
        card = read(inputs/"normalized-card.json")
        require(datetime.now(timezone.utc) < datetime.fromisoformat(card["start_at"]), "integration_after_start")
        histfile = ROOT/"artifacts/jra_research/graded_2026_inputs_20261120_audit/mile/normalized-jra-history.json"
        foreignfile = ROOT/"artifacts/jra_research/graded_2026_inputs_20261120_audit/non-jra-reference-records.json"
        history, foreign = read(histfile), read(foreignfile)
        rows = [{**r, **features(card, r, history, foreign)} for r in card["runners"] if r["status"] == "active"]
        target = {**{k: v for k, v in card.items() if k != "runners"}, "rows": rows}
        evidence = group_deltas(result["examples"], target, {**read(generalfile), "groups": {r["id"]: [r["id"]] for r in rules()}},
                                {"half_life": None, "pooling": "hierarchical", "shrinkage": 20})
        base = read(ref/"live-comparison.json")["international_connected"]["forecast"]
        require({r["horse_id"] for r in rows} == {r["horse_id"] for r in base["runners"]}, "integration_live_roster")
        current = {"features": rows, "evidence": evidence, "predictions": {"baseline": combine(base, evidence, 0, "baseline")}}
        for i in range(25):
            for mode in ("rules_only", "integrated"):
                prediction = combine(base, evidence, i, mode)
                current["predictions"][prediction["pattern"]] = prediction
        require(current["predictions"]["baseline"]["runners"] == base["runners"], "integration_old_live_changed")
        for key in ("examples", "predictions", "annual", "evidence"):
            save(args.output/(key+".json"), result[key])
        save(args.output/"rule-records.json", result["rule_records"])
        save(args.output/"summary.json", {k: v for k, v in result.items() if k not in ("examples", "predictions", "annual", "evidence", "rule_records")})
        save(args.output/"current.json", current)
        (args.output/"report.md").write_text(report(result, current), encoding="utf-8")
        sources = [Path(__file__), ROOT/"src/jra_srb/jra_mile_rule_integration.py", configfile, generalfile, datafile, histfile, foreignfile,
                   ref/"sets.json", ref/"predictions.json", ref/"live-comparison.json", frozen, inputs/"normalized-card.json",
                   ROOT/".workstate/jra-srb/mile-championship-specific-research/spec/070-複合条件統合版の検証と当日予想仕様.md"]
        save(args.output/"manifest.json", {"inputs": {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
             "outputs": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()}})
        print(json.dumps({"selected": result["selection"]["pattern"], "forecast": result["forecast_pattern"], "checks": result["comparison"]["checks"] if result["comparison"] else None,
            "top3": {p: [r["horse_no"] for r in current["predictions"][p]["runners"][:3]] for p in {"baseline", result["selection"]["pattern"]}}}, ensure_ascii=False))
    except Exception as error:
        save(args.output/"failure.json", {"type": type(error).__name__, "reason": getattr(error, "reason", str(error))})
        raise


if __name__ == "__main__":
    main()
