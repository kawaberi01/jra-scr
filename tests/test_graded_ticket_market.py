"""概要: 人気馬採否の境界と時点付き市場・券精算を検査する。
作成日: 2026-11-14
入力: 架空の確率・市場・払戻。
出力: pytestの検証結果。
実行例: uv run pytest -q tests/test_graded_ticket_market.py
注意事項: 外部通信・実DB変更なし。
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
try:
    SPEC = importlib.util.spec_from_file_location("graded_ticket_market_tested", SCRIPTS / "evaluate_graded_ticket_market.py")
    MODULE = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(MODULE)
finally:
    sys.path.pop(0)


def runners():
    """4頭の順位が明確な仮想予想を返す。"""
    return [dict(horse_no=str(i), probability_top3=1-i/10) for i in (1, 2, 3, 4)]


def test_favorite_outside_top_three():
    """人気馬が圏外なら強制採用は3位を差し替え、合意条件は見送る。"""
    data = runners()
    assert MODULE.choose(data, 4, "original") == [1, 2, 3]
    assert MODULE.choose(data, 4, "include") == [1, 2, 4]
    assert MODULE.choose(data, 4, "exclude") == [1, 2, 3]
    assert MODULE.choose(data, 4, "consensus") == []


def test_favorite_inside_top_three():
    """人気馬が圏内なら除外時だけ次点馬を繰り上げる。"""
    assert MODULE.choose(runners(), 1, "include") == [1, 2, 3]
    assert MODULE.choose(runners(), 1, "exclude") == [2, 3, 4]
    assert MODULE.choose(runners(), 1, "consensus") == [1, 2, 3]


def test_ties_and_result_independence():
    """確率同点は馬番で決め、事後情報や配列順に依存しない。"""
    data = [dict(horse_no=str(i), probability_top3=.3, rank=1) for i in (4, 3, 2, 1)]
    before = MODULE.choose(data, 4, "include")
    for r in data:
        r.update(rank=99, payout_yen=1000000)
    assert before == MODULE.choose(list(reversed(data)), 4, "include") == [1, 2, 4]


def quote():
    """単勝と同梱の複勝、取消記号を含む仮想観測を返す。"""
    entries = [dict(market="win", selection_key="01", odds_status_low="numeric", odds_low_x10=25, odds_raw_low="0025"),
               dict(market="place"), dict(market="bracket_quinella"),
               dict(market="win", selection_key="02", odds_status_low="asterisk_marker", odds_low_x10=None, odds_raw_low="****")]
    return dict(horizon="T30", selection_status="selected", parser_version="jv-o1o2-v2", content_sha256="a"*64,
                announced_at="2025-11-16T14:50:00+09:00", cutoff_at="2025-11-16T15:00:00+09:00",
                market="win", entries_json=json.dumps(entries))


def test_mixed_market_and_cancel_marker():
    """同梱券種を無視し、取消記号を数値0へ変換しない。"""
    assert MODULE.numeric(quote(), 1) == {(1,): 2.5}


def test_late_market_rejected():
    """購入判断時点より後の観測は使用しない。"""
    row = quote()
    row["announced_at"] = "2025-11-16T15:10:00+09:00"
    with pytest.raises(AssertionError, match="late_market"):
        MODULE.numeric(row, 1)


def test_missing_price_not_zero():
    """取消以外の未知価格は失敗させる。"""
    row = quote()
    entries = json.loads(row["entries_json"])
    entries[0]["odds_status_low"] = "blank"
    row["entries_json"] = json.dumps(entries)
    with pytest.raises(AssertionError, match="nonnumeric_market"):
        MODULE.numeric(row, 1)


def test_ticket_generation_and_settlement():
    """3点各100円と払戻を分け、精算しても元の券を変更しない。"""
    bets = MODULE.tickets([1, 2, 3], "quinella", {(1, 2): 3., (1, 3): 4., (2, 3): 10.})
    paid = MODULE.settle(bets, {("r", "quinella"): {(2, 3): 1000}}, "r")
    assert len(bets) == 3 and sum(t["stake_yen"] for t in bets) == 300
    assert sum(t["payout_yen"] for t in paid) == 1000
    assert all("payout_yen" not in t for t in bets)
    assert MODULE.tickets([], "trio", {}) == []
