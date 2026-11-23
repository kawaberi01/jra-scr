"""概要: JRA共通入口の方式選択の優先順位と矛盾拒否を検査する。
作成日: 2026-11-14
入力: 共通方式JSONと明示/会話内の方式・モデル指定。
出力: pytest結果。
実行例: uv run pytest -q tests/test_jra_prediction_method_routing.py
注意事項: 推論・外部通信・設定変更なし。
"""

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path("C:/Users/main/skills/jra-race-predictor/scripts/resolve_prediction_method.py")
SPEC = importlib.util.spec_from_file_location("jra_method_routing", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def configuration():
    """実際に配置した共通設定を独立した辞書として取得する。"""
    return json.loads(MODULE.DEFAULT_CONFIG.read_text(encoding="utf-8"))


@pytest.mark.parametrize("args,method,source,model", [
    ({}, "normal", "shared_default", None),
    ({"conversation_method": "condition_parts"}, "condition_parts", "conversation", "frozen_v2"),
    ({"method": "normal", "conversation_method": "condition_parts"}, "normal", "explicit_method", None),
    ({"method": "condition_parts", "conversation_method": "normal"}, "condition_parts", "explicit_method", "frozen_v2"),
    ({"model": "V89", "conversation_method": "condition_parts"}, "normal", "explicit_model", "V89"),
    ({"model": "J23", "conversation_method": "condition_parts"}, "normal", "explicit_model", "J23"),
    ({"model": "frozen_v2", "conversation_method": "normal"}, "condition_parts", "explicit_model", "frozen_v2"),
    ({"model": "条件パーツ研究v2"}, "condition_parts", "explicit_model", "frozen_v2"),
    ({"method": "condition_parts", "model": "condition-parts-v2"}, "condition_parts", "explicit_method", "frozen_v2"),
])
def test_selection_priority(args, method, source, model):
    """既定方式を使う設定で、明示指定と会話指定の優先順位を確認する。"""
    config = configuration()
    config["default_method"] = "normal"
    result = MODULE.resolve(config, **args)
    assert (result["method"], result["source"], result["model"]) == (method, source, model)
    assert result["execution_validated"] is False
    assert Path(result["skill_path"]).is_file()


@pytest.mark.parametrize("method,model", [("normal", "frozen_v2"), ("condition_parts", "V90")])
def test_explicit_conflict_is_not_fallback(method, model):
    """今回の明示的な矛盾を黙って一方へ切り替えない。"""
    with pytest.raises(ValueError, match="矛盾"):
        MODULE.resolve(configuration(), method=method, model=model)


def test_config_is_not_mutated_by_conversation():
    """会話の方式選択で他会話の共通既定が変わらない。"""
    config = configuration()
    before = json.dumps(config, sort_keys=True)
    assert config["default_method"] == "ask"
    with pytest.raises(ValueError, match="毎回指定"):
        MODULE.resolve(config, conversation_method="condition_parts")
    assert json.dumps(config, sort_keys=True) == before
    with pytest.raises(ValueError, match="毎回指定"):
        MODULE.resolve(config)
    config["default_method"] = "condition_parts"
    assert MODULE.resolve(config)["method"] == "condition_parts"


@pytest.mark.parametrize("args", [{"method": "mystery"}, {"conversation_method": "mystery"}, {"model": ""}])
def test_invalid_selection_rejected(args):
    """未知の方式や空モデルを通常方式へ握りつぶさない。"""
    with pytest.raises(ValueError):
        MODULE.resolve(configuration(), **args)
