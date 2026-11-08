"""概要: cross-market純計算を固定旧スクリプトの式・選択・集計と照合する。
作成日: 2026-10-16
入力: 合成SQLite reader fixtureとメモリ内candidate/payout。
出力: pytestの単体試験結果。
実行例: uv run pytest -q tests/test_jra_research_cross_market.py
注意事項: SQL Server/HTTPへ接続せず、一時メモリSQLiteだけを使う。
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path
import sqlite3
import sys

import pytest

from jra_srb.jra_research_contracts import ResearchError
from jra_srb import jra_research_cross_market as cross


def _legacy_module():
    """固定旧scriptを副作用なしでロードし、純関数を比較可能にする。"""
    path = Path(__file__).resolve().parents[1] / "scripts/evaluate_cross_market_disagreement.py"
    name = "_jra_research_cross_market_legacy_test"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError("legacy script cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _fixture_rows():
    """各periodで異なる市場比率を作る、再現可能な全入力fixtureを返す。"""
    rows = []
    for index, race_date in enumerate(("2025-03-01", "2025-06-30", "2025-07-01", "2025-09-30", "2025-10-01", "2025-12-20")):
        race_id = f"R{index:02d}"
        wins = {"1": 2.0 + index, "2": 4.0, "3": 8.0 - index * 0.25}
        wides = {("1", "2"): 3.0 + index, ("1", "3"): 10.0, ("2", "3"): 20.0}
        payouts = {("1", "2"): 250 if index % 2 == 0 else 0,
                   ("1", "3"): 0,
                   ("2", "3"): 0}
        rows.append((race_id, race_date, wins, wides, payouts))
    return rows


def _legacy_db(rows):
    """旧loaderが要求する表をmemory SQLiteに作り、完成した接続を返す。"""
    connection = sqlite3.connect(":memory:")
    connection.executescript("""
        CREATE TABLE races (race_id TEXT, race_date TEXT);
        CREATE TABLE netkeiba_result_entries (jra_race_id TEXT, horse_no TEXT, win_odds REAL);
        CREATE TABLE netkeiba_odds_entries (jra_race_id TEXT, combination TEXT, odds REAL, odds_min REAL, odds_max REAL, bet_type TEXT);
        CREATE TABLE netkeiba_payouts (jra_race_id TEXT, combination TEXT, payout INTEGER, bet_type TEXT);
    """)
    for race_id, race_date, wins, wides, payouts in rows:
        connection.execute("INSERT INTO races VALUES (?,?)", (race_id, race_date))
        connection.executemany("INSERT INTO netkeiba_result_entries VALUES (?,?,?)",
                               [(race_id, horse, price) for horse, price in wins.items()])
        connection.executemany("INSERT INTO netkeiba_odds_entries VALUES (?,?,?,?,?,?)",
                               [(race_id, f"{pair[0]}-{pair[1]}", price, None, None, "wide")
                                for pair, price in wides.items()])
        connection.executemany("INSERT INTO netkeiba_payouts VALUES (?,?,?,?)",
                               [(race_id, f"{pair[0]}-{pair[1]}", amount, "wide")
                                for pair, amount in payouts.items()])
    connection.commit()
    return connection


def _as_candidate(row):
    """新候補を旧dataclassと同じ引数へ変換する。"""
    return _legacy.Candidate(row["race_id"], row["race_date"], row["pair"], row["price"],
                             row["cross_ratio"], _fixture_payouts[(row["race_id"], row["pair"])])


_legacy = _legacy_module()
_fixture_payouts = {}


def test_old_loader_and_twenty_policy_report_are_equivalent(monkeypatch):
    """同じSQLite rowsで候補式・全20threshold/period・集計出力が旧実装と一致する。"""
    fixture = _fixture_rows()
    connection = _legacy_db(fixture)
    monkeypatch.setattr(_legacy, "open_analysis_read", lambda _path: connection)
    old_rows = _legacy.load_candidates(Path("unused"))

    new_rows = []
    _fixture_payouts.clear()
    for race_id, race_date, wins, wides, payouts in fixture:
        new_rows.extend(cross.build_race_candidates(race_id, race_date, wins, wides))
        _fixture_payouts.update({(race_id, pair): amount for pair, amount in payouts.items()})
    assert len(new_rows) == len(old_rows)
    old_by_key = {(row.race_id, row.pair): row for row in old_rows}
    new_by_key = {(row["race_id"], row["pair"]): row for row in new_rows}
    assert set(new_by_key) == set(old_by_key)
    for key, row in new_by_key.items():
        assert row["race_date"] == old_by_key[key].race_date
        assert row["price"] == old_by_key[key].price
        assert row["cross_ratio"] == pytest.approx(old_by_key[key].cross_ratio, rel=0, abs=1e-15)

    legacy_periods = {
        "development_2025h1": [row for row in old_rows if row.race_date <= "2025-06-30"],
        "external_2025q3": [row for row in old_rows if "2025-07-01" <= row.race_date <= "2025-09-30"],
        "external_2025q4": [row for row in old_rows if row.race_date >= "2025-10-01"],
    }
    configs = [("value", value) for value in _legacy.VALUE_THRESHOLDS] + [
        ("information", value) for value in _legacy.INFORMATION_THRESHOLDS
    ]
    expected_candidates = []
    for direction, threshold in configs:
        metrics = {}
        for period, period_rows in legacy_periods.items():
            selected = _legacy.select(period_rows, direction, threshold)
            metrics[period] = _legacy.summarize(selected)
            new_selected = cross.select_candidates(
                [row for row in new_rows if row["race_date"] in {candidate.race_date for candidate in period_rows}],
                direction, threshold)
            selected_keys = [(row.race_id, row.pair) for row in selected]
            assert [(row["race_id"], row["pair"]) for row in new_selected] == selected_keys
            assert cross.summarize_candidates(new_selected, _fixture_payouts) == metrics[period]
        passed = all(item["tickets"] >= 100 and item["return_rate"] >= 1.0
                     and item["no_max_return_rate"] >= 1.0 and item["no_top3_return_rate"] >= 1.0
                     for item in metrics.values())
        expected_candidates.append({"name": f"cross_{direction}_{threshold:.2f}", "direction": direction,
                                    "threshold": threshold, "metrics": metrics, "pass": passed})
    expected = {
        "theory": "win-wide-cross-pool-disagreement-v1",
        "definition": "expected wide pool share from normalized win shares divided by observed wide pool share",
        "candidate_count": 20,
        "candidates": expected_candidates,
        "eligible": [item["name"] for item in expected_candidates if item["pass"]],
    }
    assert cross.VALUE_THRESHOLDS == _legacy.VALUE_THRESHOLDS
    assert cross.INFORMATION_THRESHOLDS == _legacy.INFORMATION_THRESHOLDS
    assert cross.evaluate_candidates(new_rows, _fixture_payouts) == expected


def test_boundaries_ties_and_outcome_fields_do_not_change_selection():
    """wide odds 3/20とthreshold同値は含み、同率では先行pairを選びOutcomeを参照しない。"""
    rows = [
        {"race_id": "r1", "race_date": "2025-01-01", "pair": ("1", "2"), "price": 3.0,
         "cross_ratio": 1.1, "outcome": object()},
        {"race_id": "r1", "race_date": "2025-01-01", "pair": ("1", "3"), "price": 20.0,
         "cross_ratio": 1.1, "outcome": object()},
        {"race_id": "r2", "race_date": "2025-01-01", "pair": ("1", "2"), "price": 2.99,
         "cross_ratio": 8.0},
        {"race_id": "r3", "race_date": "2025-01-01", "pair": ("1", "2"), "price": 20.01,
         "cross_ratio": 8.0},
    ]
    selected = cross.select_candidates(rows, "value", 1.1)
    assert [(row["race_id"], row["pair"]) for row in selected] == [("r1", ("1", "2"))]
    assert cross.select_candidates(rows[:2], "information", 1.1)[0]["pair"] == ("1", "2")


def test_unknown_payout_is_not_silently_counted_as_zero():
    """選択pairの払戻未収載を損失扱いせず停止する。"""
    row = {"race_id": "r1", "race_date": "2025-01-01", "pair": ("1", "2"), "price": 3.0,
           "cross_ratio": 1.0}
    with pytest.raises(ResearchError) as error:
        cross.summarize_candidates([row], {})
    assert error.value.reason == "settlement_unknown"


@pytest.mark.parametrize("operation", [
    lambda: cross.build_race_candidates("r", "2025-01-01", {"1": float("nan")}, {("1", "2"): 3}),
    lambda: cross.build_race_candidates("r", "2025-01-01", {"1": 2}, {("1", "1"): 3}),
    lambda: cross.build_race_candidates("r", "2025-01-01", {"1": 2}, {("1", "01"): 3}),
    lambda: cross.select_candidates([], "unknown", 1.0),
    lambda: cross.select_candidates([], "value", math.inf),
    lambda: cross.summarize_candidates([], {("r", ("1", "2")): True}),
])
def test_invalid_numeric_pair_direction_and_payout_inputs_are_rejected(operation):
    """不正数値、自己pair、未知policy、非有限threshold、bool払戻を拒否する。"""
    with pytest.raises(ResearchError):
        operation()


def test_duplicate_race_pair_candidate_is_rejected():
    """同じrace/pairの重複候補が選択・払戻へ混入することを拒否する。"""
    row = {"race_id": "r1", "race_date": "2025-01-01", "pair": ("1", "2"), "price": 3.0,
           "cross_ratio": 1.0}
    with pytest.raises(ResearchError) as error:
        cross.select_candidates([row, dict(row)], "value", 1.0)
    assert error.value.reason == "duplicate_key"
