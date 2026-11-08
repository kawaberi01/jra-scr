"""概要: 東京10Rの公式取消馬だけを実オッズ集合から除き、別入力として監査保存する。
作成日: 2026-10-25
入力: 公式カード・元オッズ・準備済み履歴特徴。
出力: 取消除外後の新規snapshotと、1競走の再確認用index。
実行例: uv run python .workstate/jra-srb/sqlserver-model-data-audit/filter_official_withdrawn_odds_20261025.py
注意事項: 価格や確率を補完しない。元ファイル・モデルを変更せず、SQL更新・結果取得・購入なし。
"""

import json
from pathlib import Path
import shutil

from jra_srb.jra_model_selection import read_json, sha256

ROOT = Path(__file__).resolve().parents[3]


def run():
    """明示された取消状態と馬集合を照合し、該当する実価格行だけを抽出する。"""
    source = ROOT / "artifacts/predictions/20261025-day-confidence-batch05/202610250510-snapshot/ready"
    target = ROOT / "artifacts/predictions/20261025-day-confidence-tokyo10-normalized-snapshot"
    card, odds = read_json(source / "official-card.json"), read_json(source / "official-odds.json")
    assert card["race_id"] == odds["race_id"] == "202610250510"
    active = {str(r["horse_no"]).zfill(2) for r in card["runners"] if r["status"] == "active"}
    inactive = [r for r in card["runners"] if r["status"] != "active"]
    assert inactive and all(r["status"] in ("withdrawn", "excluded") and r["status_source"] == "explicit" for r in inactive)
    target.mkdir(exist_ok=False)
    (target / "input").mkdir()
    for name in ("official-card.json", "input/input.json", "input/quality.json"):
        shutil.copy2(source / name, target / name)
    shutil.copy2(source / "official-odds.json", target / "official-odds-original.json")
    counts = {}
    for kind, rows in odds["odds"].items():
        keep = [row for row in rows if row["combination"] and all(str(h).zfill(2) in active for h in row["combination"])]
        odds["odds"][kind] = keep
        counts[kind] = {"original": len(rows), "active_only": len(keep)}
    assert len(odds["odds"]["win"]) == len(active)
    assert len(odds["odds"]["quinella"]) == len(active) * (len(active)-1) // 2
    odds["normalization"] = {"rule": "公式に取消・除外が明示された馬を含む行だけ除外。実価格の変更・補完なし",
        "source_sha256": sha256(source / "official-odds.json"),
        "excluded_horses": [{"horse_no": r["horse_no"], "status": r["status"], "status_source": r["status_source"]} for r in inactive],
        "counts": counts, "observation_time_unchanged": True}
    if odds.get("entries"):
        odds["entries"] = [row for row in odds["entries"] if row["combination"] and all(str(h).zfill(2) in active for h in row["combination"])]
    with (target / "official-odds.json").open("x", encoding="utf-8") as stream:
        json.dump(odds, stream, ensure_ascii=False, indent=2)
    index = {"date": "2026-10-25", "scope": "東京10Rのみ取消馬の除外を再確認",
        "races": [{"race_id": card["race_id"], "course": "tokyo", "race_no": 10,
                   "race_name": card["race_name"], "start_time": card["start_time"], "snapshot_dir": str(target)}]}
    with (target / "index.json").open("x", encoding="utf-8") as stream:
        json.dump(index, stream, ensure_ascii=False, indent=2)
    print(json.dumps(odds["normalization"], ensure_ascii=False))


if __name__ == "__main__":
    run()
