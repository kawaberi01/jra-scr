"""概要: 20仮説研究の保存成果物を照合し、検証証跡と壁打ち台帳を保存する。
作成日: 2026-10-17
入力: 固定した初回runと是正runのJSON、圧縮予測、学習モデル。
出力: theory-twenty-20261017内のverification.json、round-ledger.md、初回不採用記録。
実行例: uv run --frozen --extra ml python .workstate/jra-srb/sqlserver-model-data-audit/verify_tipster_twenty.py
注意事項: SQL接続・再学習・旧データ参照なし。既存runを変更しない。
"""

import ast
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np

from jra_srb.jra_research_contracts import canonical_json, digest

ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
INITIAL = "20261017T100721Z_2e6121154a2f420ab3e86a2270d752a4"
FINAL = "20261017T101337Z_24a898f583fd464093472afb87a88f28"


def load(path):
    """UTF-8の保存JSONを読む。"""
    return json.loads(path.read_text(encoding="utf-8"))


def verify():
    """保存hash・再利用モデル・会計・20件の一致を確認して証跡を保存する。"""
    runs = ROOT / "artifacts/jra_research/runs"
    old, new = runs / INITIAL, runs / FINAL
    original, metrics = load(old / "metrics.json"), load(new / "metrics.json")
    manifest = load(new / "manifest.json")
    assert manifest["status"] == "complete" and metrics["status"] == "passed"
    assert metrics["theory_count_completed"] == 20 and len(metrics["ledger"]) == 20
    assert not metrics["sqlite_used"] and not metrics["live_adopted"]
    assert digest(metrics) == manifest["metrics_sha256"]
    for name in ("input_digest", "market_digest", "adopted_by_split", "trained_rows"):
        assert metrics["coverage"][name] == original["coverage"][name]
    assert metrics["coverage"]["new_fits"] == 0
    assert set(metrics["alphas"].values()) == {0.0}
    for directory, expected in ((old, original["model_sha256"]), (new, metrics["model_sha256"])):
        assert hashlib.sha256((directory / "models.joblib").read_bytes()).hexdigest() == expected
    before, after = joblib.load(old / "models.joblib"), joblib.load(new / "models.joblib")
    assert before["features"] == after["features"] and before["columns"] == after["columns"]
    for key in before["models"]:
        for attribute in ("coef_", "intercept_", "classes_"):
            np.testing.assert_array_equal(getattr(before["models"][key], attribute), getattr(after["models"][key], attribute))
        assert before["models"][key].get_params() == after["models"][key].get_params()
    stream, variants, grouped, accounting = hashlib.sha256(b"["), Counter(), defaultdict(list), defaultdict(Counter)
    with gzip.open(new / "predictions.jsonl.gz", "rt", encoding="utf-8") as handle:
        for i, line in enumerate(handle):
            row = json.loads(line)
            if i:
                stream.update(b",")
            stream.update(canonical_json(row).encode())
            assert set(row) == {"race_key", "race_date", "venue", "variant", "split", "horses", "probability", "target", "ticket"}
            ticket = row["ticket"]
            assert ticket["kind"] == "quinella" and ticket["stake_yen"] == 600
            assert 0 < row["probability"] <= 1 and row["target"] in (0, 1)
            assert (ticket["payout_yen"] > 0) == bool(row["target"])
            variants[row["variant"]] += 1
            grouped[row["race_key"]].append((row["horses"], row["probability"]))
            for period in (row["split"], "all", *(["reused_2026"] if row["race_date"].startswith("2026") else [])):
                accounting[row["variant"], period].update(races=1, stake_yen=600, payout_yen=ticket["payout_yen"])
    stream.update(b"]")
    assert stream.hexdigest() == manifest["predictions_sha256"]
    assert len(variants) == 21 and set(variants.values()) == {1567}
    assert len(grouped) == 1567
    assert all(len(rows) == 21 and all(row == rows[0] for row in rows) for rows in grouped.values())
    for (variant, period), counts in accounting.items():
        expected = metrics["results"][variant][period]
        for key, value in counts.items():
            assert expected[key] == value
        assert np.isclose(expected["return_rate"], counts["payout_yen"] / counts["stake_yen"])
    ast_functions = 0
    for name in ("src/jra_srb/jra_research_tipster_twenty.py", "scripts/run_jra_tipster_twenty.py"):
        source = ROOT / name
        tree = ast.parse(source.read_text(encoding="utf-8"))
        assert ast.get_docstring(tree)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                assert ast.get_docstring(node), node.name
                ast_functions += 1
        if name in manifest["code_sha256"]:
            assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest["code_sha256"][name]
    output = BASE / "theory-twenty-20261017"
    output.mkdir(exist_ok=True)
    report = {"status": "passed", "run_id": FINAL, "initial_run": INITIAL,
              "prediction_rows": sum(variants.values()), "races": len(grouped), "variants_including_market_control": 21,
              "theories": 20, "identical_market_control_choices_verified": True,
              "accounting_groups": len(accounting), "models_unchanged": len(after["models"]), "new_fits": 0,
              "source_digests_unchanged": True, "prediction_hash_verified": True, "metrics_hash_verified": True,
              "source_ast_documented_objects": ast_functions, "input_digest": metrics["coverage"]["input_digest"],
              "market_digest": metrics["coverage"]["market_digest"], "pytest_executed": False}
    (output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rejection = {"run_id": INITIAL, "scientific_acceptance": False,
                 "reason": "校正最適化が端点0を評価せず微小係数を残し、理論上同点のEVを数値誤差で順位付けした。初回の理論別回収率は採用しない。",
                 "resolution": "端点0/1明示比較・EV同点安定化。学習済19モデルと入力を維持して是正runで再評価。20件の追加試行とは数えない。",
                 "superseded_by": FINAL, "original_artifacts_preserved": True}
    (output / "initial-run-not-accepted.json").write_text(json.dumps(rejection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ledger = ["# 理論壁打ち・検証20件台帳", "", "各案はT01基準に対する独立の仮説比較。20回の逐次最適化ではない。数値は2026年の再使用1082競走。対数損失は小さいほどよい。市場混合前の診断値であり、全19案の市場混合係数は0。T20は校正済3案の合成。", ""]
    for entry in metrics["ledger"]:
        key = entry["id"]
        raw = entry["reused_2026"].get("raw_content_logloss")
        comparison = metrics["raw_content_comparisons"].get(key)
        judgment = "基準として保持。購入採用なし。"
        if key == "T02":
            judgment = "2020年以降への短縮は悪化。今回の固定方式では2003年以降を含む学習を保持。履歴自体は両案とも2003年以降。"
        elif key == "T20":
            judgment = "校正後の損失は全案同点。ID順でT01/T02/T03を選択したため独立した改善なし。優秀な3理論を選べたとは扱わない。"
        elif comparison:
            low, high = comparison["day_bootstrap_95"]
            judgment = "基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。" if high < 0 else "今回の基準との差は小さく、区間は0を含む。単独での優先度を下げる。"
        ledger.extend([f"## {entry['round']:02d} {key} {entry['hypothesis']}", "", f"- 仮説：{entry['hypothesis']}を予測要因として比較する。", f"- 反論・制約：{entry['criticism']}", f"- 検証方法：学習開始年{entry.get('training_from_year', '合成')}、特徴 `{', '.join(entry.get('features', []))}`。", f"- 結果：市場混合前の対数損失 {raw:.6f}。" if raw is not None else "- 結果：校正済合成の対数損失3.374066（市場と同一）。生モデルの値なし。"])
        if comparison:
            ledger.append(f"- 基準T01との差：{comparison['raw_logloss_difference_vs_T01']:+.6f}、日単位bootstrap 95%区間 [{comparison['day_bootstrap_95'][0]:+.6f}, {comparison['day_bootstrap_95'][1]:+.6f}]。事後診断・多重比較未補正。")
        ledger.extend([f"- 判断：{judgment}", ""])
    (output / "round-ledger.md").write_text("\n".join(ledger), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    verify()
