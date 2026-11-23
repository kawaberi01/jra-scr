"""概要: 追加部品の時点制約・欠測と女王杯の当日入口を検証する。
作成日: 2026-11-15
入力: 合成履歴、保存済み女王杯datasetと固定予測。
出力: pytestの検証結果。
実行例: uv run pytest -q tests/test_jra_form_parts.py
注意事項: 通信・DB更新・当日結果取得なし。
"""

from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run_jra_form_parts import form_values, add_parts
from apply_eliza_form_reference import official_reference
from jra_srb.jra_graded_live import score_live, validate_live
from jra_srb.jra_race_conditions import load_config, public_runner
from jra_srb.jra_research_contracts import ResearchError


def test_form_excludes_target_future_and_non_starters():
    """未来・当該日・取消を除き、対象馬の実出走だけで比率を計算する。"""
    race = dict(race_date="2026-11-15", race_name="エリザベス女王杯")
    row = dict(horse_id="2021100000")
    history = [dict(**row, race_key=str(i), race_date=day, status=status, rank=rank,
                    race_name="別レース") for i, (day, status, rank) in enumerate([
        ("2026-08-01", "active", 1), ("2026-09-01", "active", 2),
        ("2026-10-01", "active", 10), ("2026-10-20", "excluded", 1),
        ("2026-11-15", "active", 10), ("2026-12-01", "active", 10)])]
    assert form_values(race, row, history) == dict(recent_three_top3="2/3以上", previous_edition_rank="前年出走確認なし")
    history[0]["rank"] = None
    assert form_values(race, row, history)["recent_three_top3"] is None


def test_previous_edition_is_previous_calendar_year_and_missing_is_unknown():
    """前年と過去年を区別し、着順不明を惨敗に置換しない。"""
    race = dict(race_date="2026-11-15", race_name="エリザベス女王杯")
    row = dict(horse_id="2021100000", values={"existing": "保持"})
    past = dict(horse_id=row["horse_id"], race_key="202511160811", race_date="2025-11-16",
                status="active", rank=6, race_name=race["race_name"])
    assert form_values(race, row, [past])["previous_edition_rank"] == "4〜6着"
    assert form_values(race, row, [{**past, "rank": None}])["previous_edition_rank"] is None
    assert form_values(race, row, [{**past, "race_date": "2024-11-10"}])["previous_edition_rank"] == "前年出走確認なし"
    source = [{**race, "rows": [row]}]
    result = add_parts(source, [past], 3)
    assert result[0]["rows"][0]["values"]["existing"] == "保持"
    assert source[0]["rows"][0]["values"] == {"existing": "保持"}


def test_elizabeth_live_matches_frozen_forecast_and_rejects_wrong_scope():
    """女王杯専用datasetで過去予測を再現し、牡馬・距離違いを拒否する。"""
    base = ROOT / "artifacts/jra_research"
    data_path = base / "elizabeth_conditions_v1_20261108_export_v4/dataset.json"
    saved_path = base / "graded_patterns_20261114_verified/predictions.json"
    if not data_path.exists() or not saved_path.exists():
        pytest.skip("検証済み研究成果物が未配置")
    data = json.loads(data_path.read_text(encoding="utf-8"))
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    card = deepcopy(max(data["races"], key=lambda r: r["race_date"]))
    history = [h for h in data["history"] if h["race_date"] < card["race_date"]]
    card["runners"] = [public_runner(r) for r in card["runners"] if r["status"] == "active"]
    for r in card["runners"]:
        r["latest_race_date"] = max(h["race_date"] for h in history if h["horse_id"] == r["horse_id"] and h["status"] == "active")
    actual = score_live(data, card, history, load_config(ROOT / "configs/research/race_conditions_elizabeth_v1.json"), "elizabeth")
    expected = next(p for p in saved if p["series_id"] == "elizabeth" and p["race_key"] == card["race_key"] and p["pattern"] == "frozen_v2")
    expected = {r["horse_no"]: r["probability_top3"] for r in expected["runners"]}
    assert {r["horse_no"]: r["probability_top3"] for r in actual["runners"]} == pytest.approx(expected, abs=1e-12)
    assert sum(expected.values()) == pytest.approx(3)
    for field, value in (("distance", 2000), ("sex", "1")):
        bad = deepcopy(card)
        if field == "sex":
            bad["runners"][0][field] = value
        else:
            bad[field] = value
        with pytest.raises(ResearchError):
            validate_live(bad, history, "elizabeth")


def test_official_reference_checks_identity_and_preserves_missing():
    """実資料33頭を照合し、属性不一致を停止して欠測評価を保持する。"""
    base = ROOT / "artifacts/jra_research"
    required = [base / "elizabeth_conditions_v1_20261108_export_v4/dataset.json",
                base / "elizabeth_live_20261115_v1/normalized-card.json",
                base / "eliza_official_20261115_export/2025-11-16.json"]
    if not all(p.exists() for p in required):
        pytest.skip("照合済み資料未配置")
    data, card, _ = [json.loads(p.read_text(encoding="utf-8")) for p in required]
    result = official_reference(card, data)
    assert len(result["verified_runner_links"]) == 33
    assert {r["current_horse_no"] for r in result["matched_current_runners"]} == {"03", "10", "17"}
    stellen = next(r for r in result["matched_current_runners"] if r["current_horse_no"] == "03")
    rating = next(json.loads(r["values_json"]) for r in stellen["records"]
                  if r["record_kind"] == "ratings" and json.loads(r["values_json"])["rating_kind"] == "pre_rating")
    assert rating["rating_value"] is None
    bad = deepcopy(data)
    bad["races"][-1]["runners"][0]["sex"] = "1"
    with pytest.raises(AssertionError):
        official_reference(card, bad)
