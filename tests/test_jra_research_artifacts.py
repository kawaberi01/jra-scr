"""概要: 元データの複製禁止・失敗状態・モデル契約・replay入口を検証する。
作成日: 2026-10-15
入力: 合成設定、メモリ内成果物、一時フォルダー。
出力: pytest検証結果。
実行例: uv run pytest -q tests/test_jra_research_artifacts.py
注意事項: 一時フォルダーだけに許可成果物を保存する。
"""

import json

import pytest

from jra_research_helpers import config_fixture, dataset_fixture
from jra_srb import jra_research_artifacts as artifacts
from jra_srb.jra_research_contracts import ResearchError, digest
from jra_srb.jra_research_evaluation import evaluate, train_models


def test_artifact_allowlist_and_failure_state(tmp_path, monkeypatch):
    """raw/features exportを拒否しfailedのまま完了へ見せない。"""
    monkeypatch.setattr(artifacts, "RUN_ROOT", tmp_path)
    run = artifacts.RunArtifacts(config_fixture().raw, "run")
    with pytest.raises(ResearchError, match="forbidden_artifact"):
        run.write_json("features.json", {})
    run.fail(ResearchError("missing_O1"))
    manifest = json.loads((run.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert {p.name for p in run.path.iterdir()} == {"config.json", "manifest.json", "failure.json"}
    assert manifest["code_sha256"]


def test_excluded_rows_contain_only_keys_and_reasons(tmp_path, monkeypatch):
    """除外ログに特徴量やraw payloadを混入できない。"""
    monkeypatch.setattr(artifacts, "RUN_ROOT", tmp_path)
    run = artifacts.RunArtifacts(config_fixture().raw, "coverage")
    with pytest.raises(ResearchError, match="forbidden_excluded_payload"):
        run.write_excluded([{"race_key": "x", "reason": "bad", "features": [1, 2]}])
    with pytest.raises(ResearchError, match="invalid_run_id"):
        artifacts.existing_run("../../secrets")


def test_streamed_prediction_hash_matches_canonical_array(tmp_path, monkeypatch):
    """逐次保存のSHAが小規模一括計算と同じになり形式を維持する。"""
    monkeypatch.setattr(artifacts, "RUN_ROOT", tmp_path)
    config, dataset = config_fixture(), dataset_fixture()
    _, predictions = evaluate(dataset, config, train_models(dataset, config))
    run = artifacts.RunArtifacts(config.raw, "run")
    assert run.write_predictions(predictions) == digest(predictions)


def test_replay_does_not_claim_success_when_outputs_change():
    """入力が同じでも計算結果が変わった再実行は終了コード5とする。"""
    original = {"metrics_sha256": digest({"score": 1}), "predictions_sha256": digest([])}
    artifacts.verify_replay_outputs(original, {"score": 1}, digest([]))
    with pytest.raises(ResearchError, match="replay_output_changed") as error:
        artifacts.verify_replay_outputs(original, {"score": 2}, digest([]))
    assert error.value.exit_code == 5
