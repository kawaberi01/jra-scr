"""概要: 三系列比較の芝ダート分離・2歳対応・選択時点を検証する。
作成日: 2026-11-14。
入力: 合成競走・固定候補とpytest。
出力: 合否。
実行例: uv run pytest -q tests/test_jra_graded_patterns.py
注意事項: DB・外部通信なし。
"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_jra_conditions_search import config, data
from jra_srb.jra_graded_patterns import feature_values, build_examples, choose, evaluate, selection_comparison
from jra_srb.jra_research_contracts import digest, ResearchError


def test_surface_specific_course_experience():
    """ダート対象へ芝の同場同距離好走歴を混入させない。"""
    race = data()["races"][-1]
    race.update(distance=1600, track_code="23")
    horse = race["runners"][0]
    history = [{"horse_id": horse["horse_id"], "race_key": "201410010811", "race_date": "2014-10-01", "race_name": "試験",
                "venue_code": "08", "distance": 1600, "track_code": "11", "rank": 1, "status": "active",
                "weight_carried": 56., "grade": "C", "ra_verified": True}]
    assert feature_values(race, horse, history)["course_distance_top3"] == "確認なし"
    history[0]["track_code"] = "23"
    assert feature_values(race, horse, history)["course_distance_top3"] == "確認あり"


def test_two_year_old_mixed_sex():
    """2歳・牡牝を専用研究入口で受け入れ、年齢項目は一定になる。"""
    dataset = data()
    for race in dataset["races"]:
        for i, row in enumerate(race["runners"]):
            row.update(age=2, sex="1" if i % 2 else "2")
    rows = build_examples(dataset)
    assert {r["values"]["age"] for race in rows for r in race["rows"]} == {"2"}


def test_series_macro_selection():
    """頭数が違う系列は、一律比改善を系列均等で評価する。"""
    annual = []
    for series, n, losses in (("large", 16, {"uniform": .16, "route": .14, "balanced": .12}),
                              ("small", 8, {"uniform": .24, "route": .20, "balanced": .25})):
        for pattern, loss in losses.items():
            annual.append({"series_id": series, "pattern": pattern, "races": 1, "runners": n, "brier": loss,
                           "logloss": .5, "top1_top3_hit": 0., "top3_captured": 1.})
    assert choose(annual, [{"id": "route", "groups": [1, 2]}, {"id": "balanced", "groups": list(range(5))}]) == "route"


def inputs():
    """互いに異なる競走キーを持つ3系列と固定設定を作る。"""
    cfg = json.loads((Path(__file__).resolve().parents[1] / "configs/research/graded_common_patterns_v1.json").read_text(encoding="utf-8"))
    cfg["bootstrap_repeats"] = 10
    datasets = {}
    for series, venue in (("elizabeth", "08"), ("musashino", "05"), ("daily2", "09")):
        dataset = data()
        for race in dataset["races"]:
            race["venue_code"] = venue
            race["race_key"] = race["race_key"][:8]+venue+"11"
        dataset.pop("input_sha256")
        dataset["input_sha256"] = digest(dataset)
        datasets[series] = dataset
    return cfg, datasets


def test_future_results_and_series_exclusion(config):
    """同年他系列の結果を候補選択へ使わず、当該結果は予想値を変えない。"""
    cfg, datasets = inputs()
    before = evaluate(datasets, config, cfg)
    changed = deepcopy(datasets)
    for dataset in changed.values():
        for row in dataset["races"][-1]["runners"]:
            row["rank"] = 7-row["rank"]
        dataset.pop("input_sha256")
        dataset["input_sha256"] = digest(dataset)
    after = evaluate(changed, config, cfg)
    assert before["predictions"] == after["predictions"]
    assert [(r["selected_pattern"], r["selection_latest_year"]) for r in before["selection"]] == [(r["selected_pattern"], r["selection_latest_year"]) for r in after["selection"]]
    for row in before["selection"]:
        assert row["selection_latest_year"] < row["race_date"][:4]
        if row["policy"] == "other_series":
            assert row["series_id"] not in row["selection_series"]
    outcome = selection_comparison(before, cfg)
    assert outcome["other_series"]["years"] == ["2013", "2014"]


def test_input_sha_rejected(config):
    """内容SHAが不一致なら比較しない。"""
    cfg, datasets = inputs()
    datasets["daily2"]["races"][0]["runners"][0]["age"] = 4
    with pytest.raises(ResearchError, match="dataset_sha"):
        evaluate(datasets, config, cfg)
