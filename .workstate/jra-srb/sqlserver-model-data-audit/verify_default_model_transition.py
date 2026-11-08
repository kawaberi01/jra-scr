"""概要: 既定移行の実モデル・新旧予想保持・API読戻し・全日一覧を監査する。
作成日: 2026-10-25
入力: 検証済み新予想フォルダー、旧予想、稼働ローカルAPI。
出力: 新規監査フォルダーの検証結果と全日snapshot index。
実行例: uv run --extra ml python .workstate/jra-srb/sqlserver-model-data-audit/verify_default_model_transition.py --output artifacts/predictions/20261025-default-model-audit
注意事項: GETとファイル新規作成だけ。SQL更新・結果取得・再学習なし。
"""

import argparse
import json
from pathlib import Path

import httpx

from jra_srb.jra_model_selection import read_json, resolve_model, sha256

ROOT = Path(__file__).resolve().parents[3]


def run(output):
    """新旧予想全文と固定モデルを照合し、一覧上の未分析を保持する。"""
    output.mkdir(parents=True, exist_ok=False)
    folder = ROOT / "artifacts/predictions/20261025-default-model-verification-v2"
    payload = read_json(folder / "prediction_payload.json")
    old_folders = ["20261025-early-D0", "20261025-early-H2", "20261025-D0-template", "20261025-attribute-chimera-v2"]
    model = resolve_model()
    assert model["id"] == payload["prediction_json"]["selected_model"]["id"]
    assert sha256(ROOT / model["artifact"]) == model["sha256"]
    receipts = []
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=20) as client:
        for source in [folder, *[ROOT / "artifacts/predictions" / name for name in old_folders]]:
            original = read_json(source / "prediction_payload.json")
            response = client.get("/jra/predictions/" + original["prediction_id"])
            response.raise_for_status()
            actual = response.json()
            assert actual["prediction"] == original["prediction_json"]
            assert actual["pre_race_snapshot"] == original["pre_race_snapshot"]
            assert not actual["prediction_tickets"] and actual["budget"] == 0
            receipts.append({"prediction_id": original["prediction_id"], "full_equal": True})
        early = read_json(ROOT / "artifacts/predictions/20261025-early-D0/forecast.json")
        new = payload["prediction_json"]["forecast"]
        assert new["horse_ranking"] == early["horse_ranking"] and new["pair_ranking"] == early["pair_ranking"]
        assert payload["prediction_json"]["presentation_markdown"] == (folder / "presentation.md").read_text(encoding="utf-8")
        response = client.get("/races", params={"date": "2026-10-25"})
        response.raise_for_status()
        summaries = response.json()
        index = {"date": "2026-10-25", "source": "local_API_official_schedule", "races": []}
        for row in summaries:
            race = {"race_id": row["race_id"], "course": row["course"], "race_no": int(row["race_id"][-2:]),
                    "race_name": row["name"], "start_time": row["start_time"]}
            if race["race_id"] == payload["race_id"]:
                race["snapshot_dir"] = str(ROOT / "artifacts/predictions/20261025-early-snapshot")
            index["races"].append(race)
        with (output / "snapshot-index.json").open("x", encoding="utf-8") as stream:
            json.dump(index, stream, ensure_ascii=False, indent=2)
    report = {"status": "passed", "model": model["id"], "model_sha256_unchanged": True,
              "new_and_old_predictions_equal": receipts, "D0_distribution_equal_to_early_input": True,
              "presentation_equal": True, "official_schedule_races": len(summaries),
              "input_label": "03:41早朝束の動作検証。直前最新ではない", "outcome_reads": 0,
              "training_runs": 0, "purchase_yen": 0}
    with (output / "verification.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
