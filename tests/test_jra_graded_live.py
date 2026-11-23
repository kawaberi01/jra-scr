"""概要: 当日二重賞の入力境界と、固定研究v2の過去予測との同等性を確認する。
作成日: 2026-11-14。
入力: 保存済み研究dataset・過去予測・合成近走行。
出力: pytestの検証結果。
実行例: uv run pytest -q tests/test_jra_graded_live.py
注意事項: ネットワーク・SQL・当日結果・既存保存値の変更なし。
"""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_jra_graded_live import header_conditions, recent_comparisons, observed_price, history_statuses
from jra_srb.jra_graded_live import score_live, validate_live
from jra_srb.jra_race_conditions import load_config, public_runner
from jra_srb.jra_research_contracts import ResearchError


@pytest.fixture(scope="module")
def artifacts():
    """固定過去の検証済みdatasetと全予測を読み、未配置なら明示skipする。"""
    data = ROOT / "artifacts/jra_research/graded_patterns_20261114_export_v2/dataset.json"
    predictions = ROOT / "artifacts/jra_research/graded_patterns_20261114_verified/predictions.json"
    if not data.is_file() or not predictions.is_file():
        pytest.skip("固定研究成果物が未配置")
    return json.loads(data.read_text(encoding="utf-8")), json.loads(predictions.read_text(encoding="utf-8"))


def historical_input(dataset, series):
    """2025年の保存カードから当該結果を除去し、対象日前履歴を作る。"""
    race = deepcopy(max((r for r in dataset["races"] if r["series_id"] == series), key=lambda r: r["race_date"]))
    history = [h for h in dataset["history"] if h["race_date"] < race["race_date"]]
    race.pop("series_id")
    race["runners"] = [public_runner(r) for r in race["runners"] if r["status"] == "active"]
    for r in race["runners"]:
        r["latest_race_date"] = max(h["race_date"] for h in history if h["horse_id"] == r["horse_id"] and h["status"] == "active")
    return race, history


@pytest.mark.parametrize("series", ["musashino", "daily2"])
def test_matches_frozen_historical_forecast(artifacts, series):
    """当日入口を通しても固定過去の全頭確率が変わらないことを確認する。"""
    data, saved = artifacts
    card, history = historical_input(data, series)
    config = load_config(ROOT / "configs/research/race_conditions_elizabeth_v1.json")
    result = score_live(data, card, history, config, series)
    reference = next(p for p in saved if p["series_id"] == series and p["race_key"] == card["race_key"] and p["pattern"] == "frozen_v2")
    expected = {r["horse_no"]: r["probability_top3"] for r in reference["runners"]}
    assert len(result["runners"]) == len(expected)
    assert sum(r["probability_top3"] for r in result["runners"]) == pytest.approx(3, abs=1e-10)
    for row in result["runners"]:
        assert row["probability_top3"] == pytest.approx(expected[row["horse_no"]], abs=1e-12)
        assert abs(row["probability_top3"]-row["baseline_probability_top3"]) <= .050000001


@pytest.mark.parametrize("violation", ["future", "duplicate", "result", "sex", "surface", "stale"])
def test_rejects_invalid_live_input(artifacts, violation):
    """未来履歴・重複・結果混入・属性・対象・最新性違反を拒否する。"""
    data, _ = artifacts
    card, history = historical_input(data, "musashino")
    if violation == "future":
        history.append({**history[0], "race_date": card["race_date"]})
    elif violation == "duplicate":
        card["runners"][1]["horse_id"] = card["runners"][0]["horse_id"]
    elif violation == "result":
        card["runners"][0]["rank"] = 1
    elif violation == "sex":
        card["runners"][0]["sex"] = "unknown"
    elif violation == "surface":
        card["track_code"] = "11"
    else:
        card["runners"][0]["latest_race_date"] = card["race_date"]
    with pytest.raises(ResearchError):
        validate_live(card, history, "musashino")


def test_empty_unraced_slots_are_not_missing_races():
    """近走の未出走空欄を不足走と誤認せず、不完全な実走日付は拒否する。"""
    blank = {"source_date": None, "source_course": None, "distance": None, "finish_rank": None, "field_size": None}
    actual = {"source_date": "2026-10-24", "source_course": "京都", "distance": 1600, "finish_rank": 1, "weight_carried": 55.0}
    prior = [{"race_date": "2026-10-24", "venue_name": "京都", "distance": 1600, "rank": 1, "weight_carried": 55.0}]
    assert recent_comparisons({"official_recent_races": [actual, blank, blank, blank]}, prior)[0]["status"] == "matched"
    with pytest.raises(ResearchError):
        recent_comparisons({"official_recent_races": [{**blank, "distance": 1600}]}, prior)


def test_header_retains_grade_and_rule():
    """公式ヘッダーの格・交流記号・重量方式を独立した最小HTMLで確認する。"""
    html = '<div class="race_header"><h2><span class="race_name">武蔵野ステークス</span><span class="grade_icon"><img alt="GⅢ"></span></h2><div class="type"><span class="rule">（国際）（指定）</span><span class="weight">別定</span><span class="course">1,600 メートル（ダート・左）</span></div></div>'
    fields = header_conditions(html)
    assert fields["race_name"] == "武蔵野ステークス"
    assert (fields["grade"], fields["symbol"], fields["weight_rule"]) == ("C", "N01", "2")


def test_missing_and_duplicate_odds_are_not_treated_as_prices():
    """欠測・重複・逆転レンジを実価格取得済みと誤認しない。"""
    row = {"combination": ["6", "10"], "odds_min": "3.0", "odds_max": "4.0"}
    assert observed_price({"odds": {}}, "wide", ["06", "10"]) is None
    assert observed_price({"odds": {"wide": [{**row, "odds_min": None}]}}, "wide", ["10", "6"]) is None
    assert observed_price({"odds": {"wide": [row]}}, "wide", ["10", "6"]) == row
    for entries in ([row, row], [{**row, "odds_min": "5.0"}]):
        with pytest.raises(ResearchError):
            observed_price({"odds": {"wide": entries}}, "wide", ["6", "10"])


def test_excluded_history_is_preserved_but_not_an_active_start():
    """除外は削除せず非出走にし、競走中止とは区別する。"""
    rows = [{"horse_id": "2019103879", "race_key": "202407060311", "status": "active"}]
    assert history_statuses(rows, [{**rows[0], "rank_raw": "除外"}])[0]["status"] == "excluded"
    assert history_statuses(rows, [{**rows[0], "rank_raw": "中止"}])[0]["status"] == "active"
    assert rows[0]["status"] == "active"
