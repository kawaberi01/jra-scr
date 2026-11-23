"""概要: 条件集計予想の時点境界、確率、母集団、原文と保存契約を検証する。
作成日: 2026-11-08。
入力: 合成競走・履歴・カード、pytest一時フォルダー。
出力: pytestの検証結果。実DB・外部通信は使わない。
実行例: uv run pytest -q tests/test_jra_race_conditions.py
注意事項: 合成例の成績は実際の競馬での性能を意味しない。
"""

from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from jra_srb.jra_race_conditions import (
    analyze, examples, load_config, make_features, predict, predict_card, probabilities, validate_card, validate_race,
)
from jra_srb.jra_race_conditions_report import Outputs, condition_rows, save_analysis
from jra_srb.jra_race_conditions_sql import ConditionsReader, normalize_row, parse_ra
from jra_srb.jra_research_contracts import ResearchError, digest


@pytest.fixture
def config():
    """実装と共通の固定設定を読み、閾値のテスト専用緩和をしない。"""
    return load_config(Path(__file__).resolve().parents[1] / "configs/research/race_conditions_elizabeth_v1.json")


def race(year=2010, venue="08"):
    """6頭で3着内が3頭の合成対象競走を作る。"""
    day = f"{year}-11-15"
    return {"race_key": f"{year}1115{venue}11", "race_date": day, "race_name": "エリザベス女王杯",
            "venue_code": venue, "distance": 2200, "track_code": "18", "conditions": {},
            "runners": [{"horse_id": f"200000000{i}", "horse_name": f"合成馬{i}", "horse_no": f"{i:02}",
                         "age": 3 if i <= 3 else 5, "sex": "2", "frame_no": i, "weight_carried": 56.,
                         "jockey": "試験騎手", "trainer": "試験厩舎", "status": "active", "rank": i}
                        for i in range(1, 7)]}


def dataset():
    """過去5開催と評価2開催を含む解析済み入力を作る。"""
    races = [race(y) for y in range(2010, 2017)]
    return {"schema_version": 1, "race_name": "エリザベス女王杯", "races": races, "history": [],
            "coverage": {"race_count": 7, "target_rows": 42, "history_rows": 0, "ra_missing": 7}}


def prior_run(day="2010-10-10", horse_id="2000000001"):
    """前哨戦として使う、当該結果と独立した保存過去走を作る。"""
    return {"horse_id": horse_id, "race_key": day.replace("-", "") + "0511", "race_date": day,
            "race_name": "試験前哨戦", "venue_code": "05", "distance": 1800, "track_code": "11",
            "rank": 2, "status": "active", "weight_carried": 55., "grade": "B", "weight_rule": "2",
            "symbol": "000", "ra_verified": True}


def test_features_exclude_same_day_future_and_current_outcome():
    """同日・未来履歴と当該着順を変えても、事前特徴が変わらないことを確かめる。"""
    r = race()
    horse = r["runners"][0]
    h = [prior_run(), prior_run("2010-11-15"), prior_run("2011-01-01")]
    before = make_features(r, horse, h)
    after = make_features({**r, "rank": 99}, {**horse, "rank": 99, "closing": 9}, h[:1])
    assert before == after
    assert before["latest_stored_race"] == "2010-10-10"
    assert before["values"]["interval"] == "29〜56日"
    assert before["values"]["weight_change"] == "増"


def test_missing_history_is_unknown_not_negative():
    """履歴なしを不適性や未好走へ置き換えないことを確かめる。"""
    r = race()
    f = make_features(r, r["runners"][0], [])
    assert f["values"]["repeat_top3"] is None
    assert f["values"]["graded_top3"] is None
    assert f["history_count"] == 0


def test_missing_raw_does_not_prove_no_graded_experience():
    """原文がない過去走を非重賞と断定しないことを確かめる。"""
    r = race()
    h = prior_run()
    h.update(ra_verified=False, grade=None)
    assert make_features(r, r["runners"][0], [h])["values"]["graded_top3"] is None


@pytest.mark.parametrize("scores", [[0.] * 6, [-1000., 1000., 0., 5.], list(range(18))])
def test_probability_bounds_and_sum(scores):
    """極端なスコアでも有限な周辺確率と合計3を維持する。"""
    p = probabilities(scores)
    assert all(0 <= v <= 1 for v in p)
    assert sum(p) == pytest.approx(3, abs=1e-10)


def test_walk_forward_warmup_and_all_ablations(config):
    """過去5開催を待ち、全条件除去と一律基準を同じ2年で比較する。"""
    result = analyze(dataset(), config)
    assert len(result["excluded"]) == 5
    assert len(result["predictions"]) == 2
    assert len(result["summary"]) == 7
    assert all(v["all"]["races"] == 2 for v in result["summary"].values())
    assert result["summary"]["uniform"]["all"]["brier"] == .25
    for p in result["predictions"]:
        assert p["prior_latest_date"] < p["race_date"]


def test_target_result_does_not_change_own_prediction(config):
    """評価年の正解を反転しても、その年の予測に漏れないことを確かめる。"""
    data = dataset()
    before = analyze(data, config)["predictions"][0]
    for row in data["races"][5]["runners"]:
        row["rank"] = 7 - row["rank"]
    after = analyze(data, config)["predictions"][0]
    assert before == after


def test_future_year_result_does_not_change_earlier_prediction(config):
    """後年の結果を変更しても、以前の年の予測が不変であることを確かめる。"""
    data = dataset()
    before = analyze(data, config)["predictions"][0]
    data["races"][-1]["runners"].reverse()
    for row in data["races"][-1]["runners"]:
        row["rank"] = 7 - row["rank"]
    assert analyze(data, config)["predictions"][0] == before


def test_unseen_venue_and_categories_are_finite(config):
    """同場履歴がなく新カテゴリがあっても、全場集計へ戻り計算できる。"""
    rows = examples(dataset())
    target = deepcopy(rows[-1])
    target["venue_code"] = "09"
    target["rows"][0]["values"]["previous_race"] = "未出現"
    output = predict(rows[:-1], target, config)
    assert sum(r["probability_top3"] for r in output["runners"]) == pytest.approx(3)
    assert all(e["same_venue_n"] == 0 for r in output["runners"] for g in r["groups"] for e in g["evidence"])


def test_explanation_matches_group_removal(config):
    """説明の差分が、そのグループを外す再計算と一致する。"""
    rows = examples(dataset())
    full = predict(rows[:5], rows[5], config)
    horse = full["runners"][0]
    for explanation in horse["explanations"]:
        without = predict(rows[:5], rows[5], config, explanation["group"])
        row = next(r for r in without["runners"] if r["horse_no"] == horse["horse_no"])
        assert explanation["probability_difference_pp"] == pytest.approx(100 * (horse["probability_top3"] - row["probability_top3"]))


def test_condition_counts_include_nonmatches_and_unknown(config):
    """各条件のカテゴリ合計が全活動馬数と好走数に一致する。"""
    result = analyze(dataset(), config)
    rows = condition_rows(result)
    for key in {r["race_key"] for r in rows}:
        for name in {r["feature"] for r in rows}:
            group = [r for r in rows if r["race_key"] == key and r["feature"] == name]
            assert sum(r["n"] for r in group) == 6
            assert sum(r["top3"] for r in group) == 3
            assert all(r["n"] + r["nonmatched_n"] == 6 for r in group)


def test_cancelled_runner_retained_but_not_predicted(config):
    """取消行は比較表に残るが、確率の出走集合へ混入しない。"""
    data = dataset()
    cancelled = {**data["races"][-1]["runners"][-1], "horse_no": "07", "horse_id": "2000000007",
                 "status": "excluded", "abnormal_code": "1", "rank": None}
    data["races"][-1]["runners"].append(cancelled)
    result = analyze(data, config)
    assert len(result["comparison_rows"][-1]["excluded"]) == 1
    assert len(result["predictions"][-1]["runners"]) == 6


def test_four_top3_from_tie_not_used_for_probability_evaluation(config):
    """3着同着で好走馬が4頭の年は記述表に残し、合計3の確率評価から外す。"""
    data = dataset()
    data["races"][-1]["runners"][3]["rank"] = 3
    result = analyze(data, config)
    assert result["excluded"][-1]["reason"] == "top3_count_not_three"
    assert len(result["comparison_rows"][-1]["rows"]) == 6


def test_duplicate_runner_rejected():
    """同じ馬IDの二重登録を拒否する。"""
    r = race()
    r["runners"][1]["horse_id"] = r["runners"][0]["horse_id"]
    with pytest.raises(ResearchError, match="duplicate_or_missing_horse"):
        validate_race(r)


def test_ra_identity_sha_and_offsets():
    """SDKの固定位置、SHA不一致、競走キー不一致を検出する。"""
    raw = bytearray(b" " * 1272)
    raw[:2] = b"RA"
    raw[11:27] = b"2020111508050411"
    raw[614:615] = b"A"
    raw[616:622] = b"180004"
    raw[697:701] = b"2200"
    raw[705:707] = b"18"
    raw[887:890] = b"111"
    raw[-2:] = b"\r\n"
    payload = bytes(raw)
    sha = hashlib.sha256(payload).hexdigest()
    values = parse_ra(payload, sha, "202011150811")
    assert values["grade"] == "A" and values["weight_rule"] == "4" and values["weather"] == "1"
    with pytest.raises(ResearchError, match="RA_sha"):
        parse_ra(payload, "0" * 64, "202011150811")
    with pytest.raises(ResearchError, match="RA_identity"):
        parse_ra(payload, sha, "202011150911")


def test_normalize_cancelled_zero_rank():
    """原文側の取消・順位0を正しく欠損と除外に変換する。"""
    row = {"race_key": "202011150811", "race_date": "2020-11-15", "venue_code": "08", "horse_no": "01",
        "horse_id": "2000000001", "rank": 0, "abnormal_code": "1",
        "metadata": json.dumps({"race_name": "エリザベス女王杯", "distance_raw": "2200", "track_code": "18"}),
        "attrs": json.dumps({"age": "03", "sex": "2", "frame_no": "1", "weight_carried_raw": "540", "horse_name": "試験"})}
    value = normalize_row(row)
    assert value["status"] == "excluded" and value["rank"] is None and value["weight_carried"] == 54.


def card():
    """発走前の許可列だけを持つ合成カードを作る。"""
    r = race(2026)
    r.pop("conditions")
    for runner in r["runners"]:
        runner.pop("rank")
    return {**r, "observed_at": "2026-11-14T12:00:00+09:00", "start_at": "2026-11-15T15:40:00+09:00"}


def test_card_result_and_posttime_rejected(config):
    """結果列の混入と発走後の観測を事前カードとして受け入れない。"""
    c = card()
    c["runners"][0]["rank"] = 1
    with pytest.raises(ResearchError, match="card_result_rejected"):
        validate_card(c, config)
    c = card()
    c["observed_at"] = c["start_at"]
    with pytest.raises(ResearchError, match="card_time"):
        validate_card(c, config)


def test_future_prediction_is_reference_only(config):
    """最新性の独立検証がないカードを運用可へ昇格しない。"""
    value = predict_card(dataset(), card(), config)
    assert value["availability"] == "reference_only"
    assert all(r["status"] == "unverified_or_mismatch" for r in value["freshness"])


def test_card_observation_cuts_off_later_history(config):
    """発走前でもカード観測後の走りを予想へ混入しない。"""
    data = dataset()
    c = card()
    c["observed_at"] = "2026-10-01T12:00:00+09:00"
    before = predict_card(data, c, config)
    data["history"].append(prior_run("2026-10-10"))
    assert predict_card(data, c, config) == before


def test_outputs_hashes_csv_and_overwrite_rejection(tmp_path, config):
    """成果物の保存・再読込・SHAと、既存フォルダー拒否を確認する。"""
    data = dataset()
    data["input_sha256"] = digest(data)
    output = Outputs(tmp_path / "analysis", "analyze", config)
    save_analysis(output, analyze(data, config), data)
    manifest = json.loads((output.path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "complete" and manifest["evaluated_races"] == 2
    for name, sha in manifest["files_sha256"].items():
        assert hashlib.sha256((output.path / name).read_bytes()).hexdigest() == sha
    assert (output.path / "comparisons.csv").read_bytes().startswith(b"\xef\xbb\xbf")
    with pytest.raises(ResearchError, match="output_exists"):
        Outputs(output.path, "analyze", config)


def test_failure_does_not_expose_exception_message(tmp_path, config):
    """予期しない例外の秘密らしい本文を成果物へ保存しない。"""
    output = Outputs(tmp_path / "failed", "export", config)
    output.fail(ValueError("SECRET_CONNECTION_VALUE"))
    assert "SECRET_CONNECTION_VALUE" not in (output.path / "failure.json").read_text(encoding="utf-8")
    assert json.loads((output.path / "manifest.json").read_text(encoding="utf-8"))["status"] == "failed"


def ra_payload(grade="A", version="20201116"):
    """版の選択と競合検証に使う正常な合成RAを作る。"""
    raw = bytearray(b" " * 1272)
    raw[:3] = b"RA7"
    raw[3:11] = version.encode("ascii")
    raw[11:27] = b"2020111508050411"
    raw[614:615] = grade.encode("ascii")
    raw[616:622] = b"180004"
    raw[697:701] = b"2200"
    raw[705:707] = b"18"
    raw[-2:] = b"\r\n"
    return bytes(raw)


class FakeRAReader(ConditionsReader):
    """DBなしで、RA台帳と索引原文読取の契約を検証する。"""

    def __init__(self, config, payloads):
        """固定設定と合成原文だけを保持する。"""
        super().__init__(config)
        self.payloads = payloads

    def _small(self, query_id, sql, params=()):
        """必要な一意索引とverified年版を返す。"""
        if query_id == "conditions:RA_indexes":
            return [{"name": "source_row", "column_name": name, "key_ordinal": i}
                    for i, name in enumerate(("__migration_source_snapshot_id", "__migration_source_rowid"), 1)]
        return [{"source_key": "jv-results-2020", "status": "verified"}]

    def rows(self, query_id, sql, params=(), limit=20000):
        """台帳後の本文取得がrowidのbigint集合であることを検査して返す。"""
        if query_id == "conditions:RA_catalog":
            return [{"rowid": i, "race_key": "202011150811", "key_length": 12}
                    for i in range(1, len(self.payloads)+1)]
        assert "CONVERT(bigint,?)" in sql and "y.__migration_source_rowid=k.rowid" in sql
        return [{"rowid": i, "race_key": "202011150811", "is_valid": True,
                 "sha256": hashlib.sha256(raw).hexdigest(), "payload": raw, "payload_length": len(raw)}
                for i, raw in enumerate(self.payloads, 1)]


def test_ra_rowid_route_selects_latest_revision(config):
    """LOBのIN比較を使わず、検証済み最新RA版を選ぶ。"""
    reader = FakeRAReader(config, [ra_payload(version="20201115"), ra_payload("B")])
    selected, audit = reader.race_conditions({"202011150811"})
    assert selected["202011150811"]["grade"] == "B"
    assert audit["catalog_rows"] == 2 and audit["queried_records"] == 2


def test_ra_same_revision_conflict_stops(config):
    """同順位の異なる本文を都合よく選ばず停止する。"""
    reader = FakeRAReader(config, [ra_payload(), ra_payload("B")])
    with pytest.raises(ResearchError, match="RA_version_conflict"):
        reader.race_conditions({"202011150811"})


def test_ra_original_length_not_silently_truncated(config):
    """SQL投影前の長さを照合し、長い原文を正常1272byteと誤認しない。"""
    reader = FakeRAReader(config, [ra_payload() + b"x"])
    with pytest.raises(ResearchError, match="RA_full_key_mismatch"):
        reader.race_conditions({"202011150811"})


def test_cli_offline_analyze_and_tampered_input(tmp_path):
    """DB接続なしのCLI実行と、改ざん入力の非0終了・失敗保存を確認する。"""
    root = Path(__file__).resolve().parents[1]
    value = dataset()
    value["input_sha256"] = digest(value)
    source = tmp_path / "dataset.json"
    source.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    command = [sys.executable, str(root / "scripts/run_jra_race_conditions.py"), "analyze", "--dataset", str(source)]
    good = subprocess.run([*command, "--output", str(tmp_path / "good")], cwd=root, capture_output=True,
                          text=True, encoding="utf-8", env=env)
    assert good.returncode == 0, good.stderr
    assert json.loads((tmp_path / "good/manifest.json").read_text(encoding="utf-8"))["status"] == "complete"
    value["history"].append(prior_run())
    source.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    bad = subprocess.run([*command, "--output", str(tmp_path / "bad")], cwd=root, capture_output=True,
                         text=True, encoding="utf-8", env=env)
    assert bad.returncode != 0
    failure = json.loads((tmp_path / "bad/failure.json").read_text(encoding="utf-8"))
    assert failure["reason"] == "conditions_dataset_sha"
