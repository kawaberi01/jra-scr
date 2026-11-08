"""概要: 第四段階研究の期間・過去履歴・精算境界を確認する。
作成日: 2026-10-17
入力: 合成履歴・払戻のみ。
出力: pytestの検証結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_research_tipster_experiment.py
注意事項: SQL・外部通信・旧データ読取なし。
"""

import pytest
import numpy as np
from types import SimpleNamespace

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_tipster_experiment import PriorStates, batch_records, settlement_reason, split, state_signature, summary
from jra_srb import jra_history_dataset as history
from jra_srb.jra_research_tipster_smoke import FIELDS, TipsterMarketReader, load_legacy


def test_new_period_keeps_previously_missing_quarter():
    """旧入口で除外された2025年3〜5月を学習へ含め、夏と分割逆転を防ぐ。"""
    for month in (3, 4, 5):
        assert split(f"2025-{month:02}-15") == "train"
    assert split("2025-06-01") is None
    assert split("2025-09-30") == "train"
    assert split("2025-10-01") == "calibration"
    assert split("2025-11-01") == "evaluation_2025"
    assert split("2026-02-28") == "evaluation_early"
    assert split("2026-03-01") == "evaluation_late"
    assert split("2026-06-01") is None


def test_incremental_history_matches_rebuild_and_excludes_same_day():
    """同日と未来の結果を含めず、日付更新が共有純計算と一致する。"""
    rows = [{"race_id": rid, "race_date": day, "horse_name": horse, "jockey": "騎手", "trainer": "厩舎",
             "rank": rank, "surface": "芝", "distance": 1600, "race_name": "条件戦"}
            for rid, day in (("202501010501", "2025-01-01"), ("202501020501", "2025-01-02"))
            for horse, rank in (("馬A", 1), ("馬B", 2))]
    states = PriorStates(rows)
    for day in ("2025-01-01", "2025-01-02", "2025-01-03"):
        expected = history._build_history_states(r for r in rows if r["race_date"] < day)
        assert state_signature(states.before(day)) == state_signature(expected)
    assert states.states["horse"]["馬A"].starts == 2
    with pytest.raises(ResearchError, match="history_date_regression"):
        states.before("2025-01-01")


def test_settlement_requires_all_wide_pairs_and_unique_ranks():
    """欠落・余分な払戻と同着を正常な外れ0円として扱わない。"""
    race = {"race_date": "2025-01-01", "race": {"course": "tokyo", "race_no": 1},
            "result": {"ranks_by_horse": {"01": 1, "02": 2, "03": 3, "04": 4}}}
    key = ("2025-01-01", "tokyo", 1)
    wide = {key: {("01", "02"): 200, ("01", "03"): 300, ("02", "03"): 400}}
    assert settlement_reason(race, wide) is None
    assert settlement_reason(race, {}) == "incomplete_wide_settlement"
    wide[key][("01", "04")] = 500
    assert settlement_reason(race, wide) == "incomplete_wide_settlement"
    race["result"]["ranks_by_horse"]["04"] = 3
    assert settlement_reason(race, wide) == "non_unique_or_incomplete_ranks"


def test_drawdown_includes_initial_losses():
    """初期資金からの損失も最大資金減少へ含め、会計単位を固定する。"""
    tickets = [{"stake_yen": 600, "payout_yen": payout, "race_date": "2025-11-01"}
               for payout in (0, 1800, 0, 0)]
    result = summary(tickets)
    assert result["profit_yen"] == -600
    assert result["return_rate"] == .75
    assert result["max_drawdown_yen"] == 1200


def test_market_reader_uses_explicit_experiment_days():
    """研究日付がsmoke固定6日で上書きされる退行を防ぐ。"""
    class QueryReached(Exception):
        """SQLを実行せず最初のレース問合せで診断を終了する。"""

    class FakeReader(TipsterMarketReader):
        """metadataだけを模擬し、日付パラメーターを検査する。"""

        def _small(self, query_id, sql, params=()):
            """必要な最小metadataを返し、対象日がSQLへ渡ることを確認する。"""
            if query_id.endswith(":source"):
                return [{"source_key": "prediction-full-20261008", "status": "verified"}]
            if query_id.endswith(":columns"):
                fields = FIELDS.get(params[0], ("race_key", "race_date", "venue_code", "race_no", "retrospective_metadata_json"))
                return [{"name": name} for name in (*fields, "__migration_source_snapshot_id", "__unified_race_sha256")]
            if query_id.endswith(":indexes"):
                return [{"name": "test", "column_name": name}
                        for name in ("__migration_source_snapshot_id", "__unified_race_sha256")]
            if query_id.endswith(":permission"):
                return [{"permitted": int(params[1] == "SELECT")}]
            assert query_id == "tipster_market:races"
            assert params == (31, "2025-03-01", "2025-03-02")
            raise QueryReached

    with pytest.raises(QueryReached):
        FakeReader(None).selected(["2025-03-01", "2025-03-02"])


def test_batch_memory_sharing_preserves_legacy_design_values():
    """メモリ節約後も旧純計算の履歴値と内容値・精度を維持する。"""
    from collections import Counter, defaultdict
    legacy = load_legacy()
    rows, metadata = [], {}
    h = len(legacy.v2.previous.HISTORY_KEYS)
    for key, day in (("old", "2024-01-01"), ("recent", "2025-01-01")):
        for number in range(1, 9):
            rows.append({"race_id": key, "race_date": day, "key": f"{number:02}",
                         "rank": number, "top3": number <= 3, "market_probability": 1/8,
                         "basic": [1., 1/8] + [number / 10] * h,
                         "content": [float(number)] * 13, "condition": [1.] * 27,
                         "has_history": True, "past_runs": 2})
        metadata[key] = {"race_date": day, "course": "tokyo", "quinella": {},
                         "quinella_payout": {("01", "02"): 500},
                         "wide_payout": {("01", "02"): 200, ("01", "03"): 300, ("02", "03"): 400}}

    def build_rows(**kwargs):
        """合成馬別行を返し、SQLと旧JSONLの読取を発生させない。"""
        return rows, metadata, {}, {}, None

    fake = SimpleNamespace(v2=SimpleNamespace(design=legacy.v2.design, previous=SimpleNamespace(build_rows=build_rows)))
    records = batch_records([], fake, None, defaultdict(Counter))
    for record in records:
        reference = legacy.v2.design([r for r in rows if r["race_id"] == record["race_id"]], {"quinella": {}})
        assert np.array_equal(record["history_x"], reference["history_x"])
        assert record["history_x"].dtype == np.float64
        if record["race_id"] == "old":
            assert "full_x" not in record
        else:
            assert np.array_equal(record["full_x"], reference["full_x"])
            assert np.shares_memory(record["history_x"], record["full_x"])
