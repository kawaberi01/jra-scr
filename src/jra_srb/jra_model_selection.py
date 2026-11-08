"""概要: 明示指定または承認済み設定からJRA予想モデルを選び、成果物を照合する。
作成日: 2026-10-25
入力: 任意のモデル識別子、共通JSON設定。
出力: モデル識別・能力・利用状態。選択不能時は理由付き例外。
実行例: uv run python scripts/jra_selected_model.py resolve
注意事項: 更新日時による探索・代替選択・再学習・設定書換は行わない。
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "configs/jra_prediction_models.json"


def read_json(path: Path) -> dict:
    """UTF-8 JSONを読み、破損・欠落は呼出し元へ伝える。"""
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    """成果物の内容ハッシュを計算する。"""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def resolve_model(requested: str | None = None, config: Path = DEFAULT_CONFIG) -> dict:
    """明示指定を優先し、利用可能な設定だけを返す。

    Args:
        requested: モデルIDまたは設定された別名。未指定なら既定ID。
        config: 一か所で管理するモデル設定のパス。
    Returns:
        選択元、学習期間、能力と利用状態を含むモデル定義。
    Raises:
        ValueError: 未登録、曖昧、利用停止、未検証、不採用、成果物不一致。
        OSError: 設定または必要成果物が存在しない場合。
    """
    registry = read_json(config)
    if registry.get("schema_version") != 1:
        raise ValueError("未対応のモデル設定版です")
    key = requested if requested is not None else registry["default_model"]
    matches = [(identifier, entry) for identifier, entry in registry["models"].items()
               if key.casefold() in [str(value).casefold() for value in [identifier, *entry.get("aliases", [])]]]
    if len(matches) != 1:
        raise ValueError(f"モデルが未登録または曖昧です: {key}。自動代替しません")
    identifier, entry = matches[0]
    if (entry.get("availability") != "enabled" or not entry.get("research_allowed")
            or entry.get("validation") not in {"verified_research", "adopted", "legacy_explicit"}):
        raise ValueError(f"モデルは利用不可・未検証・不採用です: {identifier}")
    if requested is None and not entry.get("default_eligible"):
        raise ValueError(f"既定モデルへの承認がありません: {identifier}")
    if requested is None and entry.get("selection_policy") == "explicit_only":
        raise ValueError(f"明示指定専用モデルを自動選択しません: {identifier}")
    result = deepcopy(entry)
    result.update(id=identifier, selection_source="explicit" if requested is not None else "configured_default")
    if entry["adapter"] == "attribute_chimera":
        if (entry.get("probabilities") != ["quinella", "top2_marginal"]
                or entry.get("ranking_semantics") != "top2_marginal_not_finish_order"):
            raise ValueError("属性キメラの確率能力・順位の意味が設定と一致しません")
        artifact = ROOT / entry["artifact"]
        manifest = read_json(artifact.parent / "model-manifest.json")
        assessment_path = artifact.parent / "assessment.json"
        assessment = read_json(assessment_path)
        verification = read_json(artifact.parent / "independent-verification.json")
        ids = manifest.get("train_ids", [])
        if not (sha256(artifact) == entry["sha256"] == manifest["model_sha256"]
                and sha256(assessment_path) == manifest["assessment_sha256"]
                and verification.get("status") == "passed"
                and assessment.get("replace_H2_as_research_candidate") is True
                and manifest.get("selected") == entry["expected_case"]
                and manifest.get("trained_through") == entry["trained_through"]
                and ids and min(ids)[:8] == entry["training_start"].replace("-", "")
                and max(ids)[:8] == entry["trained_through"].replace("-", "")):
            raise ValueError(f"モデル成果物と承認記録が一致しません: {identifier}")
        if entry.get("purchase_allowed") and not assessment.get("production_adoption"):
            raise ValueError("研究受入だけでは購入推奨を有効にできません")
    elif entry["adapter"] == "j23_frozen":
        cell = read_json(ROOT / entry["model_cell"])
        if not (sha256(ROOT / entry["model_cell"]) == entry["model_cell_sha256"]
                and sha256(ROOT / entry["artifact"]) == entry["sha256"] == cell["model_sha256"]
                and cell.get("model_file") == Path(entry["artifact"]).name
                and cell.get("case") == "J23" and cell.get("status") == "evaluated"
                and cell.get("trained_through") == entry["trained_through"]
                and cell.get("reload_checks", 0) > 0
                and entry.get("selection_policy") == "explicit_only"
                and entry.get("purchase_allowed") is False
                and entry.get("probabilities") == ["quinella", "top2_marginal"]
                and entry.get("ranking_semantics") == "top2_marginal_not_finish_order"):
            raise ValueError("J23の成果物・研究利用契約が一致しません。自動代替しません")
    elif entry["adapter"] != "v_theory":
        raise ValueError(f"未実装のモデルアダプターです: {entry['adapter']}")
    return result
