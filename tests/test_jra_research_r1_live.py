"""概要: R1当日参考推論の取消・時点・同定順序・確率の契約を検証する。
作成日: 2026-10-18
入力: 合成の発走前カード・市場・R1係数。
出力: pytestの検証結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_r1_live.py
注意事項: SQL・API・実モデル学習・実購入への接続は行わない。
"""

from datetime import datetime, timezone
from itertools import combinations

import numpy as np
import pytest

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_r1_live import market_record, score, validate_card


NOW = datetime(2026, 10, 18, 3, tzinfo=timezone.utc)


def inputs():
    """8頭と取消1頭のカード・全有効価格・非一様な48特徴を用意する。"""
    runners = [{"horse_no": str(i), "horse_name": f"馬{i}", "frame_no": str(i),
                "sex_age": "牝3", "weight_carried": "55.0 kg", "status": "active"} for i in range(1, 9)]
    card = {"race_id": "202610180811", "source": "https://www.jra.go.jp/card", "start_time": "15時40分",
            "fetched_at": NOW.isoformat(), "runners": runners + [{"horse_no": "9", "status": "withdrawn"}],
            "data_status": {"runner_set": "complete", "source_kind": "pre_race_card"}}
    odds = {"race_id": card["race_id"], "fetched_at": NOW.isoformat(), "odds": {"quinella": [
        {"combination": list(pair), "odds": str(5 + i)} for i, pair in enumerate(combinations(range(1, 9), 2))]}}
    x = np.random.default_rng(170).uniform(.1, .9, (8, 48))
    normalized, _ = validate_card(card, "2026-10-18", "kyoto", 11, NOW)
    return card, normalized, odds, x


def test_withdrawn_market_is_ignored_and_complete_active_field_required():
    """取消価格の除外と有効馬の欠落時停止を確認する。"""
    card, runners, odds, x = inputs()
    odds["odds"]["quinella"].append({"combination": [1, 9], "odds": None})
    record = market_record(card, runners, odds, x, NOW)
    assert len(record["keys"]) == 28
    assert np.isclose(record["market"].sum(), 1)
    odds["odds"]["quinella"].pop(0)
    with pytest.raises(ResearchError, match="missing_active_pair"):
        market_record(card, runners, odds, x, NOW)


@pytest.mark.parametrize("change,reason", [("late", "already_started"), ("partial", "incomplete_card"), ("wrong_id", "identity_mismatch"), ("stale", "stale_card")])
def test_invalid_card_never_scores(change, reason):
    """発走後・欠落・別レース・古いカードでは推論を拒否する。"""
    card, _, _, _ = inputs()
    now = NOW
    if change == "late":
        now = NOW.replace(hour=7)
    elif change == "partial":
        card["data_status"]["runner_set"] = "partial"
    elif change == "wrong_id":
        card["race_id"] = "202610180511"
    else:
        card["fetched_at"] = NOW.replace(hour=2).isoformat()
    with pytest.raises(ResearchError, match=reason):
        validate_card(card, "2026-10-18", "kyoto", 11, now)


def test_reordered_odds_and_reversed_pairs_preserve_scores():
    """価格の順序やペアの左右によって推論結果が変わらないことを確認する。"""
    card, runners, odds, x = inputs()
    model = {"variant": "R1", "scale": np.ones(17), "coef": np.linspace(-.1, .1, 17)}
    original = score(model, market_record(card, runners, odds, x, NOW), runners)
    odds["odds"]["quinella"].reverse()
    for row in odds["odds"]["quinella"]:
        row["combination"].reverse()
    changed = score(model, market_record(card, runners, odds, x, NOW), runners)
    assert changed == original
    assert original["verification"]["independent_softmax"]
    assert original["verification"]["outcome_independent"]
    assert np.isclose(sum(r["top2_probability"] for r in original["runner_top2_marginals"]), 2)


def test_duplicate_or_stale_market_rejected():
    """重複価格と古い価格を採用しないことを確認する。"""
    card, runners, odds, x = inputs()
    odds["odds"]["quinella"].append(odds["odds"]["quinella"][0])
    with pytest.raises(ResearchError, match="duplicate_odds_pair"):
        market_record(card, runners, odds, x, NOW)
    odds["odds"]["quinella"].pop()
    odds["fetched_at"] = NOW.replace(hour=2).isoformat()
    with pytest.raises(ResearchError, match="stale_odds"):
        market_record(card, runners, odds, x, NOW)


def test_unselected_content_and_actor_features_do_not_affect_r1():
    """騎手・厩舎等の非使用特徴が変わってもR1確率が変わらないことを確認する。"""
    from jra_srb.jra_research_tipster_residual import BASIC

    card, runners, odds, x = inputs()
    model = {"variant": "R1", "scale": np.ones(17), "coef": np.linspace(-.2, .2, 17)}
    before = score(model, market_record(card, runners, odds, x, NOW), runners)
    changed = x.copy()
    changed[:, [i for i in range(48) if i not in BASIC]] = -2.5
    after = score(model, market_record(card, runners, odds, changed, NOW), runners)
    assert before == after


def test_market_only_prediction_does_not_force_a_ticket():
    """固定期待倍率を満たさなければ確率順位があっても見送りになることを確認する。"""
    card, runners, odds, x = inputs()
    model = {"variant": "R1", "scale": np.ones(17), "coef": np.zeros(17)}
    prediction = score(model, market_record(card, runners, odds, x, NOW), runners)
    assert prediction["pairs"]
    assert prediction["research_policy_status"] == "no_bet"
    assert prediction["research_policy_candidate"] == []
