"""概要: 外部データを使わない研究テスト用の整合した小規模入力を作る。
作成日: 2026-10-15
入力: 年と合成馬数。
出力: SQL行と等しい形の合成辞書、設定、メモリ内研究入力。
実行例: uv run pytest -q tests/test_jra_research_features.py
注意事項: 実データ・秘密・DB接続を含まない。
"""

from __future__ import annotations

from copy import deepcopy
import json
import math

from jra_srb.jra_research_contracts import EXPECTED_FEATURE_NAMES, MASKED_NAMES, ResearchConfig, ResearchDataset
from jra_srb.jra_research_features import build_input
from jra_srb.jra_research_sources import outcome_bundle


def config_fixture() -> ResearchConfig:
    """3つの開催日を重複なしに分割する合成設定を返す。"""
    return ResearchConfig.parse({
        "schema_version": 1, "profile_id": "cross_pool_sql_masked_v2",
        "source_policy": {"policy_id": "frozen_prediction_v1", "source_key": "prediction-full-20261008", "snapshot_id": 31},
        "date_from": "2020-01-01", "date_through": "2022-01-01", "horizon": "T30",
        "splits": {"train": ["2020-01-01", "2020-01-01"], "dev": ["2021-01-01", "2021-01-01"], "evaluation": ["2022-01-01", "2022-01-01"]},
        "seed": 42, "model": {"C": 1.0, "solver": "lbfgs", "max_iter": 1000},
        "ticket": {"stake_yen": 100, "odds_min": 2.0, "odds_max": 30.0, "min_expected_return": 1.05, "max_tickets_per_race": 1},
        "quality": {"availability": "research_only", "require_atomic_snapshot": False},
        "limits": {"batch_races": 500, "fetch_rows": 10000, "query_timeout_seconds": 30,
                   "memory_bytes": 2147483648, "max_candidate_rows": 1500000, "max_label_scan_rows": 1500000},
    })


def race_rows(year: int = 2020) -> dict:
    """O1/O2、46特徴、結果、HR金額が整合する5頭の合成行を返す。"""
    key, day = f"{year}01010601", f"{year}-01-01"
    cutoff, announced = f"{day}T09:30:00+09:00", f"{day}T09:29+09:00"
    horses = [f"{i:02d}" for i in range(1, 6)]
    win = {h: i + 2.0 for i, h in enumerate(horses)}
    pair = {(a, b): 6.0 + i for i, (a, b) in enumerate((a, b) for a in horses for b in horses if a < b)}
    total, pair_total = sum(1 / p for p in win.values()), sum(1 / p for p in pair.values())
    feature_rows = []
    for i, horse in enumerate(horses):
        values = {name: None if name in MASKED_NAMES else float(i) / 10 for name in EXPECTED_FEATURE_NAMES}
        marginal = sum(1 / price for pair_key, price in pair.items() if horse in pair_key) / (2 * pair_total)
        values.update(log_win_odds=math.log(win[horse]), normalized_win_market_share=1 / win[horse] / total,
                      log_o2_marginal_over_o1_share=math.log(marginal / (1 / win[horse] / total)))
        feature_rows.append({"race_key": key, "horse_no": horse, "horizon": "T30", "market_cutoff_at": cutoff,
                             "o1_announced_at": announced, "o2_announced_at": announced, "features_json": json.dumps(values),
                             "masked_feature_names_json": json.dumps(sorted(MASKED_NAMES)),
                             "feature_status": "research_only_final_SE_identity_mapping_unverified",
                             "source_o1_sha256": "1" * 64, "source_o2_sha256": "2" * 64})
    markets = []
    for market, entries, sha in (("win", [{"market": "win", "selection_key": h, "odds_low_x10": int(p * 10), "odds_status_low": "numeric"} for h, p in win.items()], "1" * 64),
                                ("quinella", [{"market": "quinella", "selection_key": a + b, "odds_low_x10": int(p * 10), "odds_status_low": "numeric"} for (a, b), p in pair.items()], "2" * 64)):
        markets.append({"race_key": key, "horizon": "T30", "market": market, "cutoff_at": cutoff, "announced_at": announced,
                        "content_sha256": sha, "selection_status": "selected", "parser_version": "jv-o1o2-v2", "entries_json": json.dumps(entries)})
    return {"race": {"race_key": key, "race_date": day, "venue_code": "06", "status": "final", "feature_eligibility": "built"},
            "features": feature_rows, "entries": [{"race_key": key, "horse_no": h, "horse_id": "horse" + h} for h in horses], "markets": markets,
            "labels": [{"race_key": key, "horse_no": h, "rank": i + 1, "abnormal_code": "0", "settlement_status": "official_HR_payout",
                        "official_win_settlement": int(i == 0), "hr_sha256": "a" * 64, "se_sha256": "b" * 64} for i, h in enumerate(horses)],
            "payouts": [{"race_key": key, "market": "win", "slot": 1, "selection_raw": "01", "payout_raw": "000001230",
                         "payout_yen": 1230, "slot_status": "published", "hr_sha256": "a" * 64}]}


def input_fixture(rows: dict | None = None):
    """合成行から実装の検査を通したInputRaceを返す。"""
    rows = rows or race_rows()
    return build_input(rows["race"], rows["features"], rows["entries"], rows["markets"], snapshot=31, horizon="T30")


def dataset_fixture() -> ResearchDataset:
    """3期間の合成Input/Outcomeと来歴を返す。"""
    dataset = ResearchDataset(provenance={"build_identity_sha256": "test-build"}, candidate_count=3)
    for year in (2020, 2021, 2022):
        rows = race_rows(year)
        race = input_fixture(rows)
        dataset.races.append(race)
        dataset.outcomes[race.race_key] = outcome_bundle(race, rows["labels"], rows["payouts"])
    return dataset
