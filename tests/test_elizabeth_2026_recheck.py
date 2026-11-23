"""概要: 固定v2事前適用の条件確認・未来遮断・変動制限を検証する。
作成日: 2026-11-13。
入力: 合成履歴・カード・条件HTMLとpytest。
出力: 合否。
実行例: uv run pytest -q tests/test_elizabeth_2026_recheck.py
注意事項: DB・外部通信なし。
"""

from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from test_jra_conditions_search import config, data
from jra_srb.jra_race_conditions import verified_conditions
from jra_srb.jra_research_contracts import ResearchError


@pytest.fixture
def recheck():
    """固定適用CLIをメイン処理なしでロードする。"""
    path = Path(__file__).resolve().parents[1] / "scripts/run_elizabeth_2026_recheck.py"
    spec = importlib.util.spec_from_file_location("elizabeth_recheck_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value,expected", [({"ra_verified": True}, True), ({"ra_verified": False}, False),
    ({"ra_verified": False, "conditions_verified": True}, True), ({"ra_verified": True, "conditions_verified": False}, False)])
def test_condition_confirmation_compatibility(value, expected):
    """旧フラグの互換性と、明示された条件確認状態を区別する。"""
    assert verified_conditions(value) is expected


def header(rule="（国際）牝（指定）"):
    """限定変換の対象となる公式ヘッダー形を作る。"""
    return f'<div class="race_header"><h2><span class="race_name">試験競走<span class="grade_icon"><img alt="GⅡ"></span></span></h2><div class="type"><div class="rule">{rule}</div><div class="weight">別定</div><div class="course">コース：1,800 メートル（芝・左）</div></div></div>'


def test_official_condition_mapping_and_unknown(recheck):
    """対応表で確認した条件だけを変換し、未知の記号を推測しない。"""
    result = recheck.html_conditions(header())
    assert (result["race_name"], result["symbol"], result["weight_rule"], result["grade"]) == ("試験競走", "N21", "2", "B")
    assert recheck.html_conditions(header("（国際）牝（特指）"))["symbol"] == "N24"
    with pytest.raises(ResearchError, match="unknown_rule"):
        recheck.html_conditions(header("未知条件"))


def test_frozen_score_future_history_and_conditions(recheck, config):
    """同日以後の履歴が確率を変えず、条件確認済み非重賞を未知にしない。"""
    dataset = data()
    card = {k: deepcopy(v) for k, v in dataset["races"][-1].items() if k != "conditions"}
    for row in card["runners"]:
        row.pop("rank")
    card.update(observed_at="2014-11-14T12:00:00+09:00", start_at="2014-11-15T15:40:00+09:00")
    old = {"race_key": "201410010511", "race_date": "2014-10-01", "race_name": "条件戦", "venue_code": "05",
           "horse_id": card["runners"][0]["horse_id"], "status": "active", "rank": 4,
           "weight_carried": 56., "distance": 1800, "track_code": "11", "grade": "", "weight_rule": "4", "symbol": "A03",
           "ra_verified": False, "conditions_verified": True}
    frozen = {"definition_mask": 2, "score_scale": 4, "probability_change_cap": .05}
    result = recheck.score(dataset, card, [old], config, frozen)
    assert result["features"][0]["values"]["graded_top3"] == "確認なし"
    future = {**old, "race_date": card["race_date"], "race_key": card["race_key"], "rank": 1, "grade": "A"}
    assert result == recheck.score(dataset, card, [old, future], config, frozen)
    unknown = recheck.score(dataset, card, [{**old, "conditions_verified": False}], config, frozen)
    assert unknown["features"][0]["values"]["graded_top3"] is None
    rows = result["v2"]["runners"]
    assert sum(r["probability_top3"] for r in rows) == pytest.approx(3)
    assert all(abs(r["probability_top3"]-r["baseline_probability_top3"]) <= .0500000001 for r in rows)
