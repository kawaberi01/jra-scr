"""概要: 2026-10-25のJRA全日比較を最大5件ずつ補完し、成功と元の失敗理由を保持する。
作成日: 2026-10-25
入力: 初回共通スカウトの36件一覧、既定モデル設定、ローカルAPI。
出力: 新規batch別フォルダー、統合scout.json、進捗status.json。
実行例: uv run --extra ml python .workstate/jra-srb/sqlserver-model-data-audit/scout_20261025_batches.py
注意事項: 予想のSQL保存・結果取得・再学習なし。初回結果と成功入力を再利用し、失敗したAPIを反復しない。
"""

from collections import Counter
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import jra_selected_model as workflow
from jra_srb.jra_model_selection import resolve_model


def save(path, value):
    """進捗JSONをUTF-8で更新する。成果物の予想や入力は上書きしない。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run():
    """未処理を順次補完し、取得不能を元の理由付きで残す。"""
    model = resolve_model()
    base = ROOT / "artifacts/predictions"
    first = base / "20261025-day-confidence-batch01"
    initial = workflow.read_json(first / "scout.json")
    out = base / "20261025-day-confidence-summary"
    out.mkdir(exist_ok=False)
    stable = {}
    pending = []
    for row in initial["entries"]:
        if row["status"] == "analyzed" or row.get("reason") != "取得上限・次回逐次補完対象":
            stable[row["race_id"]] = row
        else:
            pending.append(row)
    # 同日確認済みの京都11R入力だけを時刻を保ったまま再利用する。
    for row in pending:
        if row["race_id"] == "202610250811":
            row["snapshot_dir"] = str(base / "20261025-default-model-live-verification-v2-snapshot/ready")
    batch = 2
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=20) as client:
        while pending:
            # 失敗済みレースは再取得しない。対象分の出力を最終統合時に全36件へ戻す。
            # 条件の揃いやすい古馬戦から比較し、未処理の若駒戦も最後まで列挙する。
            pending.sort(key=lambda row: (row["race_no"] < 6, row["course"], row["race_no"]))
            selected, remaining = [], []
            fetches = 0
            for row in pending:
                if row.get("snapshot_dir") or fetches < 5:
                    selected.append(row)
                    fetches += not bool(row.get("snapshot_dir"))
                else:
                    remaining.append(row)
            index_path = out / f"index-{batch:02d}.json"
            save(index_path, {"date": "2026-10-25", "races": selected, "scope": "全日一覧から未処理分のみ"})
            folder = base / f"20261025-day-confidence-batch{batch:02d}"
            save(out / "status.json", {"stage": "running", "batch": batch, "completed": len(stable),
                 "pending": len(pending), "analyzed": sum(r["status"] == "analyzed" for r in stable.values())})
            print(json.dumps({"batch": batch, "target": len(selected), "remaining_after_batch": len(remaining)}), flush=True)
            report = workflow.scout(SimpleNamespace(output=folder, snapshot_index=index_path,
                date="2026-10-25", max_fetches=5), model, client)
            common_failure = False
            for row in report["entries"]:
                stable[row["race_id"]] = row
                common_failure |= "ローカルAPI接続不能" in row.get("reason", "")
            if common_failure:
                for row in remaining:
                    stable[row["race_id"]] = {**row, "status": "unavailable", "reason": "共通API障害・未取得"}
                break
            pending = remaining
            batch += 1
    entries = [stable[row["race_id"]] for row in initial["entries"]]
    ranked = sorted((row for row in entries if row["status"] == "analyzed"), key=lambda row: (-row["metric"], row["race_id"]))
    report = {"date": "2026-10-25", "selected_model": model, "entries": entries, "ranked": ranked,
        "inventory_count": len(entries), "analyzed_count": len(ranked),
        "reason_counts": dict(Counter(row["reason"] for row in entries if row["status"] != "analyzed")),
        "metric": "top_pair_probability", "purchase_recommendation": False,
        "all_day_highest_confidence_proven": False, "sql_prediction_writes": 0, "outcome_reads": 0}
    save(out / "scout.json", report)
    save(out / "status.json", {"stage": "completed", "inventory": len(entries), "analyzed": len(ranked), "excluded": len(entries)-len(ranked)})
    print(json.dumps({"inventory": len(entries), "analyzed": len(ranked), "reasons": report["reason_counts"]}, ensure_ascii=False), flush=True)


def finalize():
    """取消除外と再観測の結果を全36件へ反映し、対象外理由付きの最終記録を作る。"""
    base = ROOT / "artifacts/predictions"
    out = base / "20261025-day-confidence-summary"
    report = workflow.read_json(out / "scout.json")
    rechecks = ["20261025-day-confidence-kikuka-refresh", "20261025-day-confidence-tokyo10-recheck"]
    replacements = {}
    for name in rechecks:
        rows = workflow.read_json(base / name / "scout.json")["entries"]
        replacements.update({row["race_id"]: row for row in rows})
    entries = [replacements.get(row["race_id"], row) for row in report["entries"]]
    assert len(entries) == len({row["race_id"] for row in entries}) == 36
    ranked = sorted((row for row in entries if row["status"] == "analyzed"), key=lambda row: (-row["metric"], row["race_id"]))
    report.update(entries=entries, ranked=ranked, analyzed_count=len(ranked),
        reason_counts=dict(Counter(row["reason"] for row in entries if row["status"] != "analyzed")),
        recheck_sources=rechecks,
        graded_races=[{"race_id": "202610250811", "race_name": "菊花賞", "grade": "GI",
            "official_source": "https://www.jra.go.jp/keiba/g1/kikka.html"}])
    with (out / "scout-final.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    labels = {"kyoto": "京都", "tokyo": "東京", "niigata": "新潟"}
    model = report["selected_model"]
    lines = ["# 2026-10-25 JRA全レース相対比較", "", "## 実行状況", "",
        f"全36件を確認、分析可能{len(ranked)}件。モデル: {model['name']} / {model['version']}。学習2020-01-05〜2025-12-28。研究参考・購入推奨なし。",
        "", "## 相対指標ランキング", "",
        "分析可能範囲だけの馬連最大予測確率による比較。単勝勝率・全日的中確度順位・購入推奨ではない。",
        "", "| 候補 | レース | 発走 | 馬連最大予測確率 | オッズ観測 |", "| --- | --- | --- | --- | --- |"]
    for i, row in enumerate(ranked, 1):
        lines.append(f"| {i} | {labels[row['course']]}{row['race_no']}R {row['race_name']} | {row['start_time']} | {row['metric']:.2%} | {row['input_state']['odds']['observed_jst']} |")
    lines += ["", "## 重賞", "", "京都11R 菊花賞（GI）を分析済み。京都3000mでのモデル優位は未証明。", "", "## 未分析・除外", ""]
    for course in ("tokyo", "kyoto", "niigata"):
        excluded = [row for row in entries if row["course"] == course and row["status"] != "analyzed"]
        lines.append(labels[course] + ": " + "、".join(f"{row['race_no']}R={row['reason']}" for row in excluded))
    lines += ["", "## 読み方", "", "モデル用履歴は10/4まで。24件は公式カードの直近走との不整合、9件は同定不足、1件は頭数条件で評価不可。低評価と混同しない。",
        "東京10Rは公式取消3番を含むオッズ行だけ除外し、実価格と元の観測時刻を保持。元データは別ファイルに保全。",
        "履歴全場最新性、的中確度の校正、安定利益は未証明。SQL予想保存・結果取得・実購入なし。"]
    with (out / "presentation.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    print(json.dumps({"analyzed": len(ranked), "excluded": 36-len(ranked), "reasons": report["reason_counts"]}, ensure_ascii=False))


if __name__ == "__main__":
    import os
    os.environ.setdefault("JRA_SRB_STORAGE_ENV_FILE", str(ROOT / "data/storage/runtime.env"))
    if "--finalize" in sys.argv:
        finalize()
    else:
        run()
