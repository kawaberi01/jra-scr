"""概要: 既知特徴の格・前走順位・365日境界と未来遮断を検証する。
作成日: 2026-11-13。
入力: 合成競走・過去走とpytest。
出力: 合否。
実行例: uv run pytest -q tests/test_jra_conditions_resolution.py
注意事項: DB・外部通信なし。
"""

from copy import deepcopy
from datetime import date, timedelta
import importlib.util
from pathlib import Path

import pytest

from test_jra_conditions_search import config, data
from jra_srb.jra_race_conditions import examples
from jra_srb.jra_research_contracts import digest


@pytest.fixture
def resolution():
    """独立CLIの純計算部分を実行入口を起動せず読み込む。"""
    path = Path(__file__).resolve().parents[1]/"scripts/run_jra_conditions_resolution.py"
    spec = importlib.util.spec_from_file_location("resolution_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run(day, grade="A", rank=1):
    """対象馬の重賞履歴を作る。"""
    return {"horse_id": "2000000001", "race_date": day, "race_key": day.replace("-", "")+"0811",
            "status": "active", "rank": rank, "grade": grade, "ra_verified": True, "race_name": "試験重賞",
            "venue_code": "08", "distance": 2200, "track_code": "18"}


def test_grade_priority_and_year_boundary(resolution):
    """365日前を含み、366日前のGⅠ勝利より期間内GⅡ勝利を優先する。"""
    target = examples(data())[-1]
    row = target["rows"][0]
    day = date.fromisoformat(target["race_date"])
    history = [run((day-timedelta(days=366)).isoformat()), run((day-timedelta(days=365)).isoformat(), "B")]
    assert resolution.resolution_values(target, row, history, 2)["graded_top3"] == "GI勝利"
    changed = resolution.resolution_values(target, row, history, 7)
    assert changed["graded_top3"] == "GII勝利" and changed["previous_rank"] == "1着"
    assert changed == resolution.resolution_values(target, row, [*history, run(target["race_date"]), run("2025-01-01")], 7)


def test_missing_history_stays_unknown(resolution):
    """履歴がない場合は実績なしと断定せず、初版OFFは同じ特徴を返す。"""
    target = examples(data())[-1]
    row = target["rows"][0]
    assert resolution.resolution_values(target, row, [], 0) == row["values"]
    assert resolution.resolution_values(target, row, [], 7)["graded_top3"] is None


def test_resolution_future_results_and_candidate_count(resolution, config):
    """24候補の選択を当該以後の結果で変えず、過去側にも同一定義を適用する。"""
    before = resolution.run_resolution(data(), config, repeats=5)
    assert len(before["candidates"]) == 24 and len(before["predictions"]) == 24*7
    changed = deepcopy(data())
    for row in changed["races"][-1]["runners"]:
        row["rank"] = 7-row["rank"]
    changed.pop("input_sha256")
    changed["input_sha256"] = digest(changed)
    after = resolution.run_resolution(changed, config, repeats=5)
    assert before["predictions"] == after["predictions"]
    assert before["capped_predictions"] == after["capped_predictions"]
    assert before["selection"][-1]["candidate_brier"] == after["selection"][-1]["candidate_brier"]
