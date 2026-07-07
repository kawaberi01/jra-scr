from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
import re
import sqlite3
from statistics import mean
from types import SimpleNamespace
from typing import Any

from jra_srb.netkeiba_provider import BaseNetkeibaProvider, NetkeibaHttpProvider, NetkeibaPageContent
from jra_srb.netkeiba_service import NetkeibaService


TRAIN_END = "2025-09-30"
VALIDATION_FROM = "2025-10-01"
VALIDATION_TO = "2025-12-31"
MIN_HISTORY = 2
MIN_CANDIDATES = 6
BUDGET_PER_TICKET = 100
MAX_MIDDLES = 2


@dataclass(frozen=True)
class TheoryConfig:
    version: str
    score_note: str
    recent_top3_weight: float
    top3_weight: float
    same_surface_weight: float
    same_dist_weight: float
    starts_bonus_cap: float
    starts_bonus_weight: float
    recent_avg_rank_penalty: float
    same_course_weight: float = 0.0
    jockey_recent_top3_weight: float = 0.0
    trainer_recent_top3_weight: float = 0.0
    large_field_bonus_weight: float = 0.0
    field_size_reference: int = 12
    late_race_bonus: float = 0.0
    late_race_min_no: int = 7
    min_history: int = MIN_HISTORY
    min_candidates: int = MIN_CANDIDATES
    middle_odds_min: float = 8.0
    middle_odds_max: float = 30.0
    max_middles: int = MAX_MIDDLES
    min_middles_to_bet: int = 1
    min_race_no_to_bet: int = 1
    max_race_no_to_bet: int | None = None
    min_field_size_to_bet: int | None = None
    max_field_size_to_bet: int | None = None
    surface_to_bet: str | None = None
    excluded_course_codes: tuple[str, ...] | None = None
    allowed_course_codes: tuple[str, ...] | None = None
    axis_odds_max: float | None = None
    max_axis_odds_to_bet: float | None = None
    first_middle_min_axis_score_gap: float | None = None
    second_middle_min_axis_score_gap: float | None = None
    single_middle_min_axis_score_gap: float | None = None
    single_middle_min_odds_ratio: float | None = None
    standard_max_middles: int | None = None
    standard_axis_odds_max_for_ratio_guard: float | None = None
    standard_min_first_middle_odds_ratio: float | None = None
    standard_axis_odds_min_for_ratio_guard: float | None = None
    standard_max_first_middle_odds_ratio_exclusive: float | None = None
    axis_popularity_max: int | None = None
    axis_max_abs_weight_diff: int | None = None
    middle_max_abs_weight_diff: int | None = None
    middle_min_jockey_recent_top3_rate: float | None = None
    middle_min_trainer_recent_top3_rate: float | None = None
    middle_min_same_course_top3_rate: float | None = None
    middle_min_same_dist_top3_rate: float | None = None
    middle_allowed_trainer_recent_top3_rate_buckets: tuple[str, ...] | None = None
    middle_allowed_same_dist_rate_buckets: tuple[str, ...] | None = None
    middle_allowed_jockey_same_surface_rate_buckets: tuple[str, ...] | None = None
    middle_allowed_trainer_same_distance_rate_buckets: tuple[str, ...] | None = None
    ticket_allowed_axis_popularity_buckets: tuple[str, ...] | None = None
    ticket_allowed_middle_popularity_buckets: tuple[str, ...] | None = None
    ticket_allowed_axis_middle_popularity_pairs: tuple[str, ...] | None = None
    ticket_allowed_axis_odds_buckets: tuple[str, ...] | None = None
    ticket_allowed_odds_ratio_buckets: tuple[str, ...] | None = None
    ticket_allowed_middle_same_course_top3_rate_buckets: tuple[str, ...] | None = None
    ticket_allowed_middle_trainer_recent_top3_rate_buckets: tuple[str, ...] | None = None
    ticket_allowed_middle_jockey_recent_top3_rate_buckets: tuple[str, ...] | None = None
    middle_allowed_field_size_buckets: tuple[str, ...] | None = None
    large_field_middle_odds_max: float | None = None
    middle_same_dist_lt_0_15_bonus: float = 0.0
    middle_same_dist_0_25_0_35_bonus: float = 0.0
    middle_same_dist_0_25_0_35_bonus_axis_odds_max: float | None = None
    middle_same_dist_ge_0_35_penalty: float = 0.0
    middle_same_dist_missing_bonus: float = 0.0
    middle_jockey_same_surface_lt_0_15_bonus: float = 0.0
    middle_jockey_same_surface_0_25_0_35_bonus: float = 0.0
    middle_jockey_same_surface_ge_0_35_penalty: float = 0.0
    middle_trainer_same_distance_0_25_0_35_bonus: float = 0.0
    middle_trainer_same_distance_ge_0_35_bonus: float = 0.0
    middle_field_size_ge_14_bonus: float = 0.0
    middle_field_size_le_10_penalty: float = 0.0
    middle_large_field_odds_over_10_penalty: float = 0.0
    axis_same_dist_ge_0_35_bonus: float = 0.0
    axis_same_dist_0_25_0_35_bonus: float = 0.0
    axis_same_dist_lt_0_15_penalty: float = 0.0
    axis_jockey_recent_ge_0_35_bonus: float = 0.0
    axis_jockey_recent_lt_0_15_penalty: float = 0.0
    axis_trainer_recent_ge_0_35_bonus: float = 0.0
    axis_trainer_recent_lt_0_15_penalty: float = 0.0
    axis_same_surface_ge_0_35_bonus: float = 0.0
    axis_same_surface_lt_0_15_penalty: float = 0.0
    axis_field_size_ge_14_bonus: float = 0.0
    axis_field_size_le_10_penalty: float = 0.0
    popularity_top3_bonus: float = 0.0
    popularity_4to6_penalty: float = 0.0
    popularity_7plus_penalty: float = 0.0
    abs_weight_diff_1to4_bonus: float = 0.0
    abs_weight_diff_5to8_penalty: float = 0.0
    abs_weight_diff_9plus_penalty: float = 0.0


THEORIES: dict[str, TheoryConfig] = {
    "v1": TheoryConfig(
        version="v1",
        score_note="baseline: recent_top3 heavy score",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
    ),
    "v2": TheoryConfig(
        version="v2",
        score_note=(
            "axis-quality test: reduce recent top3 volatility and penalize poor recent average rank more strongly"
        ),
        recent_top3_weight=35.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=10.0,
        starts_bonus_weight=1.0,
        recent_avg_rank_penalty=2.4,
    ),
    "v3": TheoryConfig(
        version="v3",
        score_note="axis-market-guard test: use v1 score, but prefer scored axis with win odds <= 15.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        axis_odds_max=15.0,
    ),
    "v4": TheoryConfig(
        version="v4",
        score_note="middle-ticket-quality test: keep v3 axis guard, but narrow middle win odds to 8.0..20.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        axis_odds_max=15.0,
    ),
    "v5": TheoryConfig(
        version="v5",
        score_note="middle-ticket-quality follow-up: keep v3 axis guard, but narrow middle win odds to 8.0..18.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=18.0,
        axis_odds_max=15.0,
    ),
    "v6": TheoryConfig(
        version="v6",
        score_note="ticket-count robustness test: keep v4 rules, but buy only the top middle candidate",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        max_middles=1,
        axis_odds_max=15.0,
    ),
    "v7": TheoryConfig(
        version="v7",
        score_note="second-ticket guard test: keep v4 rules, but require second middle axis-score gap > 10.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        axis_odds_max=15.0,
        second_middle_min_axis_score_gap=10.0,
    ),
    "v8": TheoryConfig(
        version="v8",
        score_note="second-ticket guard follow-up: keep v4 rules, but require second middle axis-score gap > 5.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        axis_odds_max=15.0,
        second_middle_min_axis_score_gap=5.0,
    ),
    "v9": TheoryConfig(
        version="v9",
        score_note="race-confidence guard test: keep v8 rules, but bet only when two middle candidates are available",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=15.0,
        second_middle_min_axis_score_gap=5.0,
    ),
    "v10": TheoryConfig(
        version="v10",
        score_note="race-confidence follow-up: keep v9 rules, but bet only race 7 or later",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        min_race_no_to_bet=7,
        axis_odds_max=15.0,
        second_middle_min_axis_score_gap=5.0,
    ),
    "v11": TheoryConfig(
        version="v11",
        score_note="train-robustness test: keep v9 rules, but tighten axis win odds to <= 10.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
    ),
    "v12": TheoryConfig(
        version="v12",
        score_note="train-robustness test: keep v9 rules, but narrow middle win odds to 8.0..18.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=18.0,
        min_middles_to_bet=2,
        axis_odds_max=15.0,
        second_middle_min_axis_score_gap=5.0,
    ),
    "v13": TheoryConfig(
        version="v13",
        score_note="train-robustness combo: keep v9 rules, tighten axis to <= 10.0 and middles to 8.0..18.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=18.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
    ),
    "v14": TheoryConfig(
        version="v14",
        score_note="score-gap test: keep v11 rules, but require first middle axis-score gap > 5.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        first_middle_min_axis_score_gap=5.0,
        second_middle_min_axis_score_gap=5.0,
    ),
    "v15": TheoryConfig(
        version="v15",
        score_note="score-gap follow-up: keep v11 rules, but require first middle axis-score gap > 10.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        first_middle_min_axis_score_gap=10.0,
        second_middle_min_axis_score_gap=5.0,
    ),
    "v16": TheoryConfig(
        version="v16",
        score_note="score-gap comparison: keep v9 rules, but require first middle axis-score gap > 5.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=15.0,
        first_middle_min_axis_score_gap=5.0,
        second_middle_min_axis_score_gap=5.0,
    ),
    "v17": TheoryConfig(
        version="v17",
        score_note="single-middle test: keep v11 rules, but allow one middle when axis gap > 10 and odds ratio > 5",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
    ),
    "v18": TheoryConfig(
        version="v18",
        score_note="single-middle follow-up: keep v11 rules, but allow one middle when axis gap > 10 and odds ratio > 3",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=3.0,
    ),
    "v19": TheoryConfig(
        version="v19",
        score_note="two-middle shape guard: keep v17 rules, but skip standard bets when axis odds <= 4 and odds ratio <= 3",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_axis_odds_max_for_ratio_guard=4.0,
        standard_min_first_middle_odds_ratio=3.0,
    ),
    "v20": TheoryConfig(
        version="v20",
        score_note="two-middle shape follow-up: keep v17 rules, but skip standard bets when axis odds <= 6 and odds ratio <= 2",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_axis_odds_max_for_ratio_guard=6.0,
        standard_min_first_middle_odds_ratio=2.0,
    ),
    "v21": TheoryConfig(
        version="v21",
        score_note="targeted shape guard: keep v17 rules, but skip standard bets only when axis odds are 2.0..4.0 and odds ratio is 2.0..3.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_axis_odds_min_for_ratio_guard=2.0,
        standard_axis_odds_max_for_ratio_guard=4.0,
        standard_min_first_middle_odds_ratio=2.0,
        standard_max_first_middle_odds_ratio_exclusive=3.0,
    ),
    "v22": TheoryConfig(
        version="v22",
        score_note="ticket-shape test: keep v17 rules, but buy only the top middle on standard races",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
    ),
    "v23": TheoryConfig(
        version="v23",
        score_note="target-feature test: keep v17 rules, but require axis popularity <= 3",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
    ),
    "v24": TheoryConfig(
        version="v24",
        score_note="target-feature test: keep v23 rules, and require selected middles to have abs weight diff <= 8",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=8,
    ),
    "v25": TheoryConfig(
        version="v25",
        score_note="target-feature test: keep v23 rules, and require selected middles to have abs weight diff <= 4",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
    ),
    "v26": TheoryConfig(
        version="v26",
        score_note="target-feature test: keep v23 rules, and require axis abs weight diff <= 8 plus selected middles abs weight diff <= 8",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        axis_max_abs_weight_diff=8,
        middle_max_abs_weight_diff=8,
    ),
    "v27": TheoryConfig(
        version="v27",
        score_note="target-score test: keep v17 rules, add popularity and weight-diff score adjustments",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        popularity_top3_bonus=8.0,
        popularity_4to6_penalty=8.0,
        popularity_7plus_penalty=3.0,
        abs_weight_diff_1to4_bonus=4.0,
        abs_weight_diff_5to8_penalty=4.0,
        abs_weight_diff_9plus_penalty=8.0,
    ),
    "v28": TheoryConfig(
        version="v28",
        score_note="target-score test: stronger popularity penalty, lighter weight penalty",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        popularity_top3_bonus=10.0,
        popularity_4to6_penalty=10.0,
        popularity_7plus_penalty=4.0,
        abs_weight_diff_1to4_bonus=3.0,
        abs_weight_diff_5to8_penalty=3.0,
        abs_weight_diff_9plus_penalty=6.0,
    ),
    "v29": TheoryConfig(
        version="v29",
        score_note="target-score test: moderate popularity bonus plus stronger weight-diff preference",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        popularity_top3_bonus=6.0,
        popularity_4to6_penalty=7.0,
        popularity_7plus_penalty=2.0,
        abs_weight_diff_1to4_bonus=6.0,
        abs_weight_diff_5to8_penalty=6.0,
        abs_weight_diff_9plus_penalty=10.0,
    ),
    "v30": TheoryConfig(
        version="v30",
        score_note="target-score test: popularity score only, no weight-diff adjustments",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        popularity_top3_bonus=8.0,
        popularity_4to6_penalty=8.0,
        popularity_7plus_penalty=3.0,
    ),
    "v31": TheoryConfig(
        version="v31",
        score_note="derived-feature test: v25 plus same-course, jockey recent form, trainer recent form",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_course_weight=10.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        jockey_recent_top3_weight=8.0,
        trainer_recent_top3_weight=6.0,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
    ),
    "v32": TheoryConfig(
        version="v32",
        score_note="derived-feature test: v25 plus same-course, stronger jockey/trainer form, and large-field bonus",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_course_weight=12.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        jockey_recent_top3_weight=10.0,
        trainer_recent_top3_weight=8.0,
        large_field_bonus_weight=2.0,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
    ),
    "v33": TheoryConfig(
        version="v33",
        score_note="derived-feature test: v25 plus same-course and late-card score bonus",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_course_weight=10.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        jockey_recent_top3_weight=8.0,
        trainer_recent_top3_weight=6.0,
        late_race_bonus=2.5,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
    ),
    "v34": TheoryConfig(
        version="v34",
        score_note="derived-feature test: v25 plus stronger same-course and stronger jockey form",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=18.0,
        same_course_weight=16.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        jockey_recent_top3_weight=12.0,
        trainer_recent_top3_weight=4.0,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
    ),
    "v35": TheoryConfig(
        version="v35",
        score_note="target-filter test: v25 plus require middle jockey recent top3 >= 0.25",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_min_jockey_recent_top3_rate=0.25,
    ),
    "v36": TheoryConfig(
        version="v36",
        score_note="target-filter test: v25 plus require middle trainer recent top3 >= 0.20",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_min_trainer_recent_top3_rate=0.20,
    ),
    "v37": TheoryConfig(
        version="v37",
        score_note="target-filter test: v25 plus require middle jockey >= 0.20 and trainer >= 0.15",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_min_jockey_recent_top3_rate=0.20,
        middle_min_trainer_recent_top3_rate=0.15,
    ),
    "v38": TheoryConfig(
        version="v38",
        score_note="target-filter test: v25 plus require middle same-course top3 >= 0.25",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_min_same_course_top3_rate=0.25,
    ),
    "v39": TheoryConfig(
        version="v39",
        score_note="race-shape test: v25 but bet only field size >= 14",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
    ),
    "v40": TheoryConfig(
        version="v40",
        score_note="race-shape test: v25 but skip field size <= 10",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        min_field_size_to_bet=11,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
    ),
    "v41": TheoryConfig(
        version="v41",
        score_note="hybrid test: v25 plus field size >= 14 and first gap > 2.5",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        first_middle_min_axis_score_gap=2.5,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
    ),
    "v42": TheoryConfig(
        version="v42",
        score_note="shape-filter test: v25 plus dirt races only and axis odds <= 2.5",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        surface_to_bet="ダート",
        axis_odds_max=2.5,
        max_axis_odds_to_bet=2.5,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
    ),
    "v43": TheoryConfig(
        version="v43",
        score_note=(
            "context-profile test: v25 plus non-small fields, same-dist bucket filter, "
            "jockey same-surface context, and tighter middle odds in large fields"
        ),
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_allowed_same_dist_rate_buckets=("lt_0_15", "0_25_0_35"),
        middle_allowed_jockey_same_surface_rate_buckets=("lt_0_15", "0_15_0_25", "0_25_0_35"),
        middle_allowed_field_size_buckets=("11_13", "ge_14"),
        large_field_middle_odds_max=10.0,
    ),
    "v44": TheoryConfig(
        version="v44",
        score_note=(
            "context-profile follow-up: v25 plus same-dist bucket filter, trainer same-distance context, "
            "and skip high-rate same-surface jockey buckets"
        ),
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_allowed_same_dist_rate_buckets=("lt_0_15", "0_25_0_35", "missing"),
        middle_allowed_jockey_same_surface_rate_buckets=("lt_0_15", "0_15_0_25", "0_25_0_35"),
        middle_allowed_trainer_same_distance_rate_buckets=("0_15_0_25", "0_25_0_35", "ge_0_35"),
        middle_allowed_field_size_buckets=("11_13", "ge_14"),
        large_field_middle_odds_max=12.0,
    ),
    "v45": TheoryConfig(
        version="v45",
        score_note=(
            "context-profile balance: v25 plus same-dist bucket filter and field-size x middle-odds guard, "
            "without trainer-side hard pruning"
        ),
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_allowed_same_dist_rate_buckets=("lt_0_15", "0_25_0_35", "missing"),
        middle_allowed_field_size_buckets=("11_13", "ge_14"),
        large_field_middle_odds_max=10.0,
    ),
    "v46": TheoryConfig(
        version="v46",
        score_note=(
            "middle-score test: v45 base plus same-dist and jockey same-surface bucket bonuses, "
            "with small-field and large-field-longshot penalties"
        ),
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
    ),
    "v47": TheoryConfig(
        version="v47",
        score_note=(
            "middle-score follow-up: lighter same-dist/jockey bonuses and softer large-field-longshot penalty"
        ),
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=6.0,
        middle_same_dist_0_25_0_35_bonus=3.0,
        middle_same_dist_ge_0_35_penalty=4.0,
        middle_same_dist_missing_bonus=1.0,
        middle_jockey_same_surface_lt_0_15_bonus=3.0,
        middle_jockey_same_surface_0_25_0_35_bonus=1.5,
        middle_jockey_same_surface_ge_0_35_penalty=3.0,
        middle_field_size_ge_14_bonus=1.0,
        middle_field_size_le_10_penalty=4.0,
        middle_large_field_odds_over_10_penalty=2.0,
    ),
    "v48": TheoryConfig(
        version="v48",
        score_note=(
            "middle-score trainer mix: v47 plus mild trainer same-distance bonuses"
        ),
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=6.0,
        middle_same_dist_0_25_0_35_bonus=3.0,
        middle_same_dist_ge_0_35_penalty=4.0,
        middle_same_dist_missing_bonus=1.0,
        middle_jockey_same_surface_lt_0_15_bonus=3.0,
        middle_jockey_same_surface_0_25_0_35_bonus=1.5,
        middle_jockey_same_surface_ge_0_35_penalty=3.0,
        middle_trainer_same_distance_0_25_0_35_bonus=2.0,
        middle_trainer_same_distance_ge_0_35_bonus=1.0,
        middle_field_size_ge_14_bonus=1.0,
        middle_field_size_le_10_penalty=4.0,
        middle_large_field_odds_over_10_penalty=2.0,
    ),
    "v49": TheoryConfig(
        version="v49",
        score_note=(
            "axis-context test: v46 plus axis bonuses for stronger same-surface/same-dist and recent rider/trainer form"
        ),
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v50": TheoryConfig(
        version="v50",
        score_note=(
            "axis-context follow-up: lighter axis context adjustments on top of v46"
        ),
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=3.0,
        axis_same_dist_0_25_0_35_bonus=1.0,
        axis_same_dist_lt_0_15_penalty=2.0,
        axis_jockey_recent_ge_0_35_bonus=2.0,
        axis_jockey_recent_lt_0_15_penalty=1.0,
        axis_trainer_recent_ge_0_35_bonus=1.0,
        axis_trainer_recent_lt_0_15_penalty=1.0,
        axis_same_surface_ge_0_35_bonus=2.0,
        axis_same_surface_lt_0_15_penalty=1.0,
        axis_field_size_ge_14_bonus=0.5,
        axis_field_size_le_10_penalty=1.0,
    ),
    "v51": TheoryConfig(
        version="v51",
        score_note=(
            "axis-context conservative: v46 plus only same-dist and same-surface axis adjustments"
        ),
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=4.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=3.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=1.0,
    ),
    "v52": TheoryConfig(
        version="v52",
        score_note="targeted-guard test: v49 plus axis popularity <= 2 only",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=2,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v53": TheoryConfig(
        version="v53",
        score_note="targeted-guard test: v49 plus skip race 9-12",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v54": TheoryConfig(
        version="v54",
        score_note="targeted-guard test: v49 plus field size >= 14 only",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v55": TheoryConfig(
        version="v55",
        score_note="targeted-guard test: v53 plus field size >= 14 only",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v56": TheoryConfig(
        version="v56",
        score_note="targeted-guard test: v53 plus axis popularity <= 2",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=2,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v57": TheoryConfig(
        version="v57",
        score_note="targeted-guard test: v55 plus reject middle same-distance 0.15-0.25 bucket",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_allowed_same_dist_rate_buckets=("lt_0_15", "0_25_0_35", "ge_0_35", "missing"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v58": TheoryConfig(
        version="v58",
        score_note="targeted-guard test: v55 plus reject middle same-distance 0.15-0.25 and missing buckets",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_allowed_same_dist_rate_buckets=("lt_0_15", "0_25_0_35", "ge_0_35"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v59": TheoryConfig(
        version="v59",
        score_note="targeted-guard test: v55 plus middle same-distance only 0.25-0.35 or ge_0.35",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_allowed_same_dist_rate_buckets=("0_25_0_35", "ge_0_35"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v60": TheoryConfig(
        version="v60",
        score_note="targeted-guard test: v55 plus buy only the top middle on standard races",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v61": TheoryConfig(
        version="v61",
        score_note="targeted-guard test: v60 plus axis popularity <= 2",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=2,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v62": TheoryConfig(
        version="v62",
        score_note="targeted-guard test: v60 plus skip compressed 1-ticket shapes when axis<=4 and ratio<=3",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        standard_axis_odds_max_for_ratio_guard=4.0,
        standard_min_first_middle_odds_ratio=3.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v63": TheoryConfig(
        version="v63",
        score_note="targeted-guard test: v60 plus skip compressed 1-ticket shapes when axis<=6 and ratio<=2",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        standard_axis_odds_max_for_ratio_guard=6.0,
        standard_min_first_middle_odds_ratio=2.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v64": TheoryConfig(
        version="v64",
        score_note="targeted-guard test: v60 plus skip compressed 1-ticket shapes when axis<=4 and ratio<=2",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        standard_axis_odds_max_for_ratio_guard=4.0,
        standard_min_first_middle_odds_ratio=2.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v65": TheoryConfig(
        version="v65",
        score_note="targeted-guard test: v60 plus skip compressed 1-ticket shapes when axis<=4 and ratio<=2.5",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        standard_axis_odds_max_for_ratio_guard=4.0,
        standard_min_first_middle_odds_ratio=2.5,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v66": TheoryConfig(
        version="v66",
        score_note="targeted-guard test: v60 plus skip compressed 1-ticket shapes when axis<=5 and ratio<=2",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        standard_axis_odds_max_for_ratio_guard=5.0,
        standard_min_first_middle_odds_ratio=2.0,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v67": TheoryConfig(
        version="v67",
        score_note="targeted-guard test: v60 plus skip compressed 1-ticket shapes when axis<=5 and ratio<=2.5",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        standard_axis_odds_max_for_ratio_guard=5.0,
        standard_min_first_middle_odds_ratio=2.5,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v68": TheoryConfig(
        version="v68",
        score_note="v60 rerank test: weaken large-field middle odds > 10 penalty from 4 to 2",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v69": TheoryConfig(
        version="v69",
        score_note="v60 rerank test: remove large-field middle odds > 10 penalty",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=0.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v70": TheoryConfig(
        version="v70",
        score_note="v60 rerank test: weaken large-field >10 penalty and remove 0.25-0.35 same-dist bonus",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=0.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v71": TheoryConfig(
        version="v71",
        score_note="v60 rerank test: weaken large-field >10 penalty and reduce ge_0.35 same-dist penalty",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_ge_0_35_penalty=2.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v72": TheoryConfig(
        version="v72",
        score_note="v60 conditional rerank: disable middle same-dist 0.25-0.35 bonus when axis odds <= 2.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v73": TheoryConfig(
        version="v73",
        score_note="v60 conditional rerank: disable middle same-dist 0.25-0.35 bonus when axis odds <= 2.5",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.5,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v74": TheoryConfig(
        version="v74",
        score_note="v60 conditional rerank: disable middle same-dist 0.25-0.35 bonus when axis odds <= 3.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=3.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=4.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v75": TheoryConfig(
        version="v75",
        score_note="v60 conditional rerank: weaken large-field >10 penalty and disable middle same-dist 0.25-0.35 bonus when axis odds <= 2.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v76": TheoryConfig(
        version="v76",
        score_note="v60 conditional rerank: weaken large-field >10 penalty and disable middle same-dist 0.25-0.35 bonus when axis odds <= 2.5",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.5,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v77": TheoryConfig(
        version="v77",
        score_note="v60 conditional rerank: weaken large-field >10 penalty and disable middle same-dist 0.25-0.35 bonus when axis odds <= 3.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=3.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v78": TheoryConfig(
        version="v78",
        score_note="v75 plus skip middle trainer recent top3 bucket 0.15-0.25",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        middle_allowed_trainer_recent_top3_rate_buckets=("lt_0_15", "0_25_0_35", "ge_0_35", "missing"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v79": TheoryConfig(
        version="v79",
        score_note="v75 plus ticket-shape filter: skip selected middle trainer recent top3 bucket 0.15-0.25",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        ticket_allowed_middle_trainer_recent_top3_rate_buckets=("lt_0_15", "0_25_0_35", "ge_0_35", "missing"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v80": TheoryConfig(
        version="v80",
        score_note="v75 plus ticket-shape filter: axis popularity 1-2 and middle popularity 4-5 only",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        ticket_allowed_axis_popularity_buckets=("1", "2"),
        ticket_allowed_middle_popularity_buckets=("4", "5"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v81": TheoryConfig(
        version="v81",
        score_note="v80 plus ticket-shape filter: exclude odds_ratio < 2",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        ticket_allowed_axis_popularity_buckets=("1", "2"),
        ticket_allowed_middle_popularity_buckets=("4", "5"),
        ticket_allowed_odds_ratio_buckets=("2_3_5", "3_5_5", "ge_5"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v82": TheoryConfig(
        version="v82",
        score_note="v80 plus ticket-shape filter: exclude middle same-course top3 < 0.15",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        ticket_allowed_axis_popularity_buckets=("1", "2"),
        ticket_allowed_middle_popularity_buckets=("4", "5"),
        ticket_allowed_middle_same_course_top3_rate_buckets=("0_15_0_25", "0_25_0_35", "ge_0_35", "missing"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v83": TheoryConfig(
        version="v83",
        score_note="v75 standalone shape: axis popularity 1 and middle popularity 5 only",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        ticket_allowed_axis_popularity_buckets=("1",),
        ticket_allowed_middle_popularity_buckets=("5",),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v84": TheoryConfig(
        version="v84",
        score_note="v75 standalone shape: axis popularity 2 and middle popularity 4 only",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        ticket_allowed_axis_popularity_buckets=("2",),
        ticket_allowed_middle_popularity_buckets=("4",),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v85": TheoryConfig(
        version="v85",
        score_note="v75 standalone shapes: (axis 1, middle 5) or (axis 2, middle 4)",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        ticket_allowed_axis_middle_popularity_pairs=("1:5", "2:4"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v86": TheoryConfig(
        version="v86",
        score_note="v80 plus ticket filters: exclude middle jockey recent 0.15-0.25 and axis odds 4.0-6.0",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        ticket_allowed_axis_popularity_buckets=("1", "2"),
        ticket_allowed_middle_popularity_buckets=("4", "5"),
        ticket_allowed_axis_odds_buckets=("le_2_5", "2_5_4", "gt_6"),
        ticket_allowed_middle_jockey_recent_top3_rate_buckets=("lt_0_15", "0_25_0_35", "ge_0_35", "missing"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v87": TheoryConfig( 
        version="v87", 
        score_note="v80 plus ticket filters: exclude middle jockey recent 0.15-0.25 and odds_ratio < 2", 
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        ticket_allowed_axis_popularity_buckets=("1", "2"),
        ticket_allowed_middle_popularity_buckets=("4", "5"),
        ticket_allowed_odds_ratio_buckets=("2_3_5", "3_5_5", "ge_5"),
        ticket_allowed_middle_jockey_recent_top3_rate_buckets=("lt_0_15", "0_25_0_35", "ge_0_35", "missing"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0, 
        axis_same_surface_lt_0_15_penalty=2.0, 
        axis_field_size_ge_14_bonus=1.0, 
        axis_field_size_le_10_penalty=2.0, 
    ), 
    "v88": TheoryConfig(
        version="v88",
        score_note="v86 plus venue cut: exclude course_code 07 (Chukyo)",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        excluded_course_codes=("07",),
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        ticket_allowed_axis_popularity_buckets=("1", "2"),
        ticket_allowed_middle_popularity_buckets=("4", "5"),
        ticket_allowed_axis_odds_buckets=("le_2_5", "2_5_4", "gt_6"),
        ticket_allowed_middle_jockey_recent_top3_rate_buckets=("lt_0_15", "0_25_0_35", "ge_0_35", "missing"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
    "v89": TheoryConfig(
        version="v89",
        score_note="v86 main-venue branch: only course_code 05/06/08/09 (Tokyo/Nakayama/Kyoto/Hanshin)",
        recent_top3_weight=45.0,
        top3_weight=25.0,
        same_surface_weight=20.0,
        same_dist_weight=20.0,
        starts_bonus_cap=8.0,
        starts_bonus_weight=0.8,
        recent_avg_rank_penalty=1.8,
        middle_odds_min=8.0,
        middle_odds_max=20.0,
        min_middles_to_bet=2,
        max_race_no_to_bet=8,
        min_field_size_to_bet=14,
        allowed_course_codes=("05", "06", "08", "09"),
        axis_odds_max=10.0,
        second_middle_min_axis_score_gap=5.0,
        single_middle_min_axis_score_gap=10.0,
        single_middle_min_odds_ratio=5.0,
        standard_max_middles=1,
        axis_popularity_max=3,
        middle_max_abs_weight_diff=4,
        ticket_allowed_axis_popularity_buckets=("1", "2"),
        ticket_allowed_middle_popularity_buckets=("4", "5"),
        ticket_allowed_axis_odds_buckets=("le_2_5", "2_5_4", "gt_6"),
        ticket_allowed_middle_jockey_recent_top3_rate_buckets=("lt_0_15", "0_25_0_35", "ge_0_35", "missing"),
        middle_same_dist_lt_0_15_bonus=8.0,
        middle_same_dist_0_25_0_35_bonus=4.0,
        middle_same_dist_0_25_0_35_bonus_axis_odds_max=2.0,
        middle_same_dist_ge_0_35_penalty=6.0,
        middle_same_dist_missing_bonus=2.0,
        middle_jockey_same_surface_lt_0_15_bonus=4.0,
        middle_jockey_same_surface_0_25_0_35_bonus=2.0,
        middle_jockey_same_surface_ge_0_35_penalty=4.0,
        middle_field_size_ge_14_bonus=2.0,
        middle_field_size_le_10_penalty=6.0,
        middle_large_field_odds_over_10_penalty=2.0,
        axis_same_dist_ge_0_35_bonus=5.0,
        axis_same_dist_0_25_0_35_bonus=2.0,
        axis_same_dist_lt_0_15_penalty=4.0,
        axis_jockey_recent_ge_0_35_bonus=3.0,
        axis_jockey_recent_lt_0_15_penalty=2.0,
        axis_trainer_recent_ge_0_35_bonus=2.0,
        axis_trainer_recent_lt_0_15_penalty=2.0,
        axis_same_surface_ge_0_35_bonus=3.0,
        axis_same_surface_lt_0_15_penalty=2.0,
        axis_field_size_ge_14_bonus=1.0,
        axis_field_size_le_10_penalty=2.0,
    ),
} 

# netkeiba uses YYYY + course_code + meeting_no + day_no + race_no.
# This table covers central JRA validation days in 2025-10-01..2025-12-31.
NETKEIBA_PREFIX_BY_DATE_COURSE: dict[tuple[str, str], str] = {
    # 4th Tokyo / 4th Kyoto
    ("2025-10-04", "05"): "2025050401",
    ("2025-10-05", "05"): "2025050402",
    ("2025-10-11", "05"): "2025050403",
    ("2025-10-12", "05"): "2025050404",
    ("2025-10-13", "05"): "2025050405",
    ("2025-10-18", "05"): "2025050406",
    ("2025-10-19", "05"): "2025050407",
    ("2025-10-25", "05"): "2025050408",
    ("2025-10-26", "05"): "2025050409",
    ("2025-10-04", "08"): "2025080401",
    ("2025-10-05", "08"): "2025080402",
    ("2025-10-11", "08"): "2025080403",
    ("2025-10-12", "08"): "2025080404",
    ("2025-10-13", "08"): "2025080405",
    ("2025-10-18", "08"): "2025080406",
    ("2025-10-19", "08"): "2025080407",
    ("2025-10-25", "08"): "2025080408",
    ("2025-10-26", "08"): "2025080409",
    # 4th Niigata
    ("2025-10-04", "04"): "2025040401",
    ("2025-10-05", "04"): "2025040402",
    ("2025-10-11", "04"): "2025040403",
    ("2025-10-12", "04"): "2025040404",
    ("2025-10-13", "04"): "2025040405",
    ("2025-10-18", "04"): "2025040406",
    ("2025-10-19", "04"): "2025040407",
    ("2025-10-25", "04"): "2025040408",
    ("2025-10-26", "04"): "2025040409",
    # 3rd Fukushima, 5th Tokyo / Kyoto
    ("2025-11-01", "03"): "2025030301",
    ("2025-11-02", "03"): "2025030302",
    ("2025-11-08", "03"): "2025030303",
    ("2025-11-09", "03"): "2025030304",
    ("2025-11-15", "03"): "2025030305",
    ("2025-11-16", "03"): "2025030306",
    ("2025-11-22", "03"): "2025030307",
    ("2025-11-24", "03"): "2025030308",
    ("2025-11-01", "05"): "2025050501",
    ("2025-11-02", "05"): "2025050502",
    ("2025-11-08", "05"): "2025050503",
    ("2025-11-09", "05"): "2025050504",
    ("2025-11-15", "05"): "2025050505",
    ("2025-11-16", "05"): "2025050506",
    ("2025-11-22", "05"): "2025050507",
    ("2025-11-23", "05"): "2025050508",
    ("2025-11-24", "05"): "2025050509",
    ("2025-11-29", "05"): "2025050510",
    ("2025-11-30", "05"): "2025050511",
    ("2025-11-01", "08"): "2025080501",
    ("2025-11-02", "08"): "2025080502",
    ("2025-11-08", "08"): "2025080503",
    ("2025-11-09", "08"): "2025080504",
    ("2025-11-15", "08"): "2025080505",
    ("2025-11-16", "08"): "2025080506",
    ("2025-11-22", "08"): "2025080507",
    ("2025-11-23", "08"): "2025080508",
    ("2025-11-24", "08"): "2025080509",
    ("2025-11-29", "08"): "2025080510",
    ("2025-11-30", "08"): "2025080511",
    # 4th Chukyo, 5th Nakayama, 5th Hanshin
    ("2025-12-06", "07"): "2025070401",
    ("2025-12-07", "07"): "2025070402",
    ("2025-12-13", "07"): "2025070403",
    ("2025-12-14", "07"): "2025070404",
    ("2025-12-20", "07"): "2025070405",
    ("2025-12-21", "07"): "2025070406",
    ("2025-12-06", "06"): "2025060501",
    ("2025-12-07", "06"): "2025060502",
    ("2025-12-13", "06"): "2025060503",
    ("2025-12-14", "06"): "2025060504",
    ("2025-12-20", "06"): "2025060505",
    ("2025-12-21", "06"): "2025060506",
    ("2025-12-27", "06"): "2025060507",
    ("2025-12-28", "06"): "2025060508",
    ("2025-12-06", "09"): "2025090501",
    ("2025-12-07", "09"): "2025090502",
    ("2025-12-13", "09"): "2025090503",
    ("2025-12-14", "09"): "2025090504",
    ("2025-12-20", "09"): "2025090505",
    ("2025-12-21", "09"): "2025090506",
    ("2025-12-27", "09"): "2025090507",
    ("2025-12-28", "09"): "2025090508",
}


class DiskCachedNetkeibaProvider(BaseNetkeibaProvider):
    def __init__(
        self,
        inner: NetkeibaHttpProvider,
        cache_dir: Path,
        offline: bool = False,
        max_live_requests: int | None = None,
    ) -> None:
        self.inner = inner
        self.cache_dir = cache_dir
        self.offline = offline
        self.max_live_requests = max_live_requests
        self.live_requests = 0

    async def fetch_race_result(self, race_id: str) -> NetkeibaPageContent:
        return await self._cached(
            f"race_result_{race_id}.html",
            lambda: self.inner.fetch_race_result(race_id),
        )

    async def fetch_odds_view(self, race_id: str) -> NetkeibaPageContent:
        return await self._cached(
            f"odds_view_{race_id}.html",
            lambda: self.inner.fetch_odds_view(race_id),
        )

    async def fetch_odds_api(self, race_id: str) -> NetkeibaPageContent:
        return await self._cached(
            f"odds_api_{race_id}.json",
            lambda: self.inner.fetch_odds_api(race_id),
        )

    async def _cached(self, name: str, fetcher) -> NetkeibaPageContent:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self.cache_dir / name
        source_path = self.cache_dir / f"{name}.source"
        if path.exists():
            source = source_path.read_text(encoding="utf-8") if source_path.exists() else str(path)
            return NetkeibaPageContent(source=source, content=path.read_text(encoding="utf-8"))
        if self.offline:
            raise FileNotFoundError(f"netkeiba cache missing: {path}")
        if self.max_live_requests is not None and self.live_requests >= self.max_live_requests:
            raise RuntimeError("max_live_requests_reached")
        page = await fetcher()
        self.live_requests += 1
        path.write_text(page.content, encoding="utf-8")
        source_path.write_text(page.source, encoding="utf-8")
        return page


@dataclass
class HistoryBundle:
    horses: dict[str, list[dict[str, Any]]]
    jockeys: dict[str, list[dict[str, Any]]]
    trainers: dict[str, list[dict[str, Any]]]


@dataclass
class RaceEvaluation:
    jra_race_id: str
    netkeiba_race_id: str | None
    race_date: str
    course_code: str
    race_no: int
    race_name: str | None
    status: str
    reason: str | None = None
    axis_name: str | None = None
    axis_no: str | None = None
    axis_rank: int | None = None
    axis_odds: float | None = None
    axis_top3: bool = False
    middle_top3_count: int = 0
    tickets: list[str] | None = None
    hit_tickets: list[str] | None = None
    payouts: list[int] | None = None
    bet: int = 0
    payout: int = 0


def load_rows(db_path: Path) -> dict[str, list[dict[str, Any]]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            select r.race_id, r.race_date, r.race_no, r.race_name, r.course, r.surface, r.distance,
                   ru.horse_no, ru.horse_name, ru.jockey, ru.trainer, ru.weight_carried,
                   re.rank
            from races r
            join runners ru on ru.race_id = r.race_id
            left join result_entries re on re.race_id = ru.race_id and re.horse_no = ru.horse_no
            where re.rank is not null
            order by r.race_date, r.race_id, cast(ru.horse_no as integer), ru.horse_no
            """
        ).fetchall()
    finally:
        conn.close()
    races: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        races[row["race_id"]].append(dict(row))
    for race_rows in races.values():
        field_size = len(race_rows)
        for row in race_rows:
            row["field_size"] = field_size
    return races


def load_netkeiba_db_results(db_path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        mappings = conn.execute(
            """
            select jra_race_id, netkeiba_race_id
            from netkeiba_race_mappings
            where netkeiba_race_id is not null and netkeiba_race_id != ''
            """
        ).fetchall()
        results = conn.execute(
            """
            select netkeiba_race_id
            from netkeiba_race_results
            """
        ).fetchall()
        entries = conn.execute(
            """
            select netkeiba_race_id, rank, horse_no, horse_name, win_odds, popularity,
                   frame_no, horse_weight, horse_weight_diff
            from netkeiba_result_entries
            order by netkeiba_race_id, rank, horse_no
            """
        ).fetchall()
        payouts = conn.execute(
            """
            select netkeiba_race_id, bet_type, combination, payout
            from netkeiba_payouts
            order by netkeiba_race_id
            """
        ).fetchall()
    finally:
        conn.close()

    result_map: dict[str, Any] = {}
    by_jra: dict[str, Any] = {}
    nk_by_jra: dict[str, str] = {}

    for row in mappings:
        jra_race_id = row["jra_race_id"]
        netkeiba_race_id = row["netkeiba_race_id"]
        if jra_race_id and netkeiba_race_id:
            nk_by_jra[str(jra_race_id)] = str(netkeiba_race_id)

    for row in results:
        netkeiba_race_id = str(row["netkeiba_race_id"])
        payload = SimpleNamespace(results=[], payouts=[])
        result_map[netkeiba_race_id] = payload

    for row in entries:
        payload = result_map.get(str(row["netkeiba_race_id"]))
        if payload is None:
            continue
        payload.results.append(
            SimpleNamespace(
                rank=str(row["rank"]) if row["rank"] is not None else None,
                horse_no=str(row["horse_no"]) if row["horse_no"] is not None else None,
                horse_name=row["horse_name"],
                win_odds=row["win_odds"],
                popularity=row["popularity"],
                frame_no=str(row["frame_no"]) if row["frame_no"] is not None else None,
                horse_weight=row["horse_weight"],
                horse_weight_diff=row["horse_weight_diff"],
            )
        )

    for row in payouts:
        payload = result_map.get(str(row["netkeiba_race_id"]))
        if payload is None:
            continue
        payload.payouts.append(
            SimpleNamespace(
                bet_type=row["bet_type"],
                combination=row["combination"],
                payout=row["payout"],
            )
        )

    for jra_race_id, netkeiba_race_id in nk_by_jra.items():
        payload = result_map.get(netkeiba_race_id)
        if payload is not None:
            by_jra[jra_race_id] = payload

    return by_jra, nk_by_jra


def build_history(races: dict[str, list[dict[str, Any]]], until_date: str) -> HistoryBundle:
    horse_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    jockey_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trainer_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for race_id in sorted(races, key=lambda rid: (races[rid][0]["race_date"], rid)):
        if races[race_id][0]["race_date"] >= until_date:
            break
        for row in races[race_id]:
            horse_history[row["horse_name"]].append(row)
            if row.get("jockey"):
                jockey_history[str(row["jockey"])].append(row)
            if row.get("trainer"):
                trainer_history[str(row["trainer"])].append(row)
    return HistoryBundle(horses=horse_history, jockeys=jockey_history, trainers=trainer_history)


def race_ids_in_period(races: dict[str, list[dict[str, Any]]], from_date: str, to_date: str) -> list[str]:
    return [
        race_id
        for race_id in sorted(races, key=lambda rid: (races[rid][0]["race_date"], rid))
        if from_date <= races[race_id][0]["race_date"] <= to_date
    ]


def course_code(jra_race_id: str) -> str:
    return jra_race_id[8:10]


def netkeiba_race_id(jra_race_id: str, race_date: str, race_no: int) -> str | None:
    prefix = NETKEIBA_PREFIX_BY_DATE_COURSE.get((race_date, course_code(jra_race_id)))
    if prefix is None:
        return None
    return f"{prefix}{race_no:02d}"


def norm_dist(value: Any) -> int | None:
    if not value:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else None


def distance_bucket(dist: int | None) -> str:
    if dist is None:
        return "missing"
    if dist <= 1400:
        return "sprint"
    if dist <= 1800:
        return "mile"
    if dist <= 2200:
        return "intermediate"
    return "long"


def rate_bucket(value: Any) -> str:
    if value is None:
        return "missing"
    rate = float(value)
    if rate < 0.15:
        return "lt_0_15"
    if rate < 0.25:
        return "0_15_0_25"
    if rate < 0.35:
        return "0_25_0_35"
    return "ge_0_35"


def axis_odds_bucket(value: float | None) -> str:
    if value is None:
        return "missing"
    if value <= 2.5:
        return "le_2_5"
    if value <= 4.0:
        return "2_5_4"
    if value <= 6.0:
        return "4_6"
    return "gt_6"


def field_size_bucket(value: Any) -> str:
    size = int(value or 0)
    if size <= 10:
        return "le_10"
    if size <= 13:
        return "11_13"
    return "ge_14"


def hist_features(
    hist: list[dict[str, Any]],
    race: dict[str, Any],
    history: HistoryBundle,
) -> dict[str, Any]:
    starts = len(hist)
    ranks = [int(item["rank"]) for item in hist if item["rank"]]
    top3 = sum(1 for rank in ranks if rank <= 3)
    recent = hist[-5:]
    recent_ranks = [int(item["rank"]) for item in recent if item["rank"]]
    recent_top3 = sum(1 for rank in recent_ranks if rank <= 3)
    surface = race.get("surface")
    course = race.get("course")
    same_surface = [item for item in hist if surface and item.get("surface") == surface]
    same_course = [item for item in hist if course and item.get("course") == course]
    same_surface_top3 = sum(1 for item in same_surface if int(item["rank"]) <= 3)
    same_course_top3 = sum(1 for item in same_course if int(item["rank"]) <= 3)
    dist = norm_dist(race.get("distance"))
    same_dist = []
    if dist:
        for item in hist:
            past_dist = norm_dist(item.get("distance"))
            if past_dist and abs(past_dist - dist) <= 200:
                same_dist.append(item)
    same_dist_top3 = sum(1 for item in same_dist if int(item["rank"]) <= 3)
    jockey_recent: list[dict[str, Any]] = []
    trainer_recent: list[dict[str, Any]] = []
    jockey_recent_same_surface: list[dict[str, Any]] = []
    trainer_recent_same_distance_bucket: list[dict[str, Any]] = []
    jockey = race.get("jockey")
    trainer = race.get("trainer")
    if jockey:
        jockey_recent = history.jockeys.get(str(jockey), [])[-20:]
        jockey_recent_same_surface = [item for item in jockey_recent if surface and item.get("surface") == surface]
    if trainer:
        trainer_recent = history.trainers.get(str(trainer), [])[-20:]
        target_distance_bucket = distance_bucket(dist)
        trainer_recent_same_distance_bucket = [
            item
            for item in trainer_recent
            if distance_bucket(norm_dist(item.get("distance"))) == target_distance_bucket
        ]
    jockey_recent_top3 = sum(1 for item in jockey_recent if int(item["rank"]) <= 3)
    trainer_recent_top3 = sum(1 for item in trainer_recent if int(item["rank"]) <= 3)
    jockey_recent_same_surface_top3 = sum(1 for item in jockey_recent_same_surface if int(item["rank"]) <= 3)
    trainer_recent_same_distance_bucket_top3 = sum(
        1 for item in trainer_recent_same_distance_bucket if int(item["rank"]) <= 3
    )
    return {
        "starts": starts,
        "avg_rank": mean(ranks) if ranks else 99.0,
        "top3_rate": top3 / starts if starts else 0.0,
        "recent_top3_rate": recent_top3 / len(recent) if recent else 0.0,
        "recent_avg_rank": mean(recent_ranks) if recent_ranks else 99.0,
        "same_surface_top3_rate": same_surface_top3 / len(same_surface) if same_surface else None,
        "same_course_top3_rate": same_course_top3 / len(same_course) if same_course else None,
        "same_dist_top3_rate": same_dist_top3 / len(same_dist) if same_dist else None,
        "jockey_recent_top3_rate": jockey_recent_top3 / len(jockey_recent) if jockey_recent else None,
        "trainer_recent_top3_rate": trainer_recent_top3 / len(trainer_recent) if trainer_recent else None,
        "jockey_recent_same_surface_top3_rate": (
            jockey_recent_same_surface_top3 / len(jockey_recent_same_surface) if jockey_recent_same_surface else None
        ),
        "trainer_recent_same_distance_bucket_top3_rate": (
            trainer_recent_same_distance_bucket_top3 / len(trainer_recent_same_distance_bucket)
            if trainer_recent_same_distance_bucket
            else None
        ),
        "field_size": float(race.get("field_size") or 0),
        "race_no": float(race.get("race_no") or 0),
        "surface": surface,
        "distance_bucket": distance_bucket(dist),
    }


def score(features: dict[str, Any], theory: TheoryConfig, nk: Any | None = None) -> float:
    starts_bonus = min(float(features["starts"] or 0), theory.starts_bonus_cap) * theory.starts_bonus_weight
    top3_rate = float(features["top3_rate"] or 0)
    same_surface = features["same_surface_top3_rate"]
    same_course = features["same_course_top3_rate"]
    same_dist = features["same_dist_top3_rate"]
    jockey_recent = features["jockey_recent_top3_rate"]
    trainer_recent = features["trainer_recent_top3_rate"]
    field_size = float(features["field_size"] or 0)
    race_no = int(features["race_no"] or 0)
    out = (
        float(features["recent_top3_rate"] or 0) * theory.recent_top3_weight
        + top3_rate * theory.top3_weight
        + float(same_surface if same_surface is not None else top3_rate) * theory.same_surface_weight
        + float(same_course if same_course is not None else top3_rate) * theory.same_course_weight
        + float(same_dist if same_dist is not None else top3_rate) * theory.same_dist_weight
        + float(jockey_recent if jockey_recent is not None else top3_rate) * theory.jockey_recent_top3_weight
        + float(trainer_recent if trainer_recent is not None else top3_rate) * theory.trainer_recent_top3_weight
        + starts_bonus
        + max(field_size - theory.field_size_reference, 0.0) * theory.large_field_bonus_weight
        + (theory.late_race_bonus if race_no >= theory.late_race_min_no else 0.0)
        - float(features["recent_avg_rank"] or 99) * theory.recent_avg_rank_penalty
    )
    if nk is not None:
        out += target_score_adjustment(nk, theory)
    return out


def norm_name(value: str | None) -> str:
    return re.sub(r"\s+", "", value or "")


def odds_to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def target_score_adjustment(nk: Any, theory: TheoryConfig) -> float:
    out = 0.0
    popularity = int_or_none(getattr(nk, "popularity", None))
    if popularity is not None:
        if popularity <= 3:
            out += theory.popularity_top3_bonus
        elif popularity <= 6:
            out -= theory.popularity_4to6_penalty
        else:
            out -= theory.popularity_7plus_penalty

    weight_diff = int_or_none(getattr(nk, "horse_weight_diff", None))
    if weight_diff is not None:
        abs_weight_diff = abs(weight_diff)
        if 1 <= abs_weight_diff <= 4:
            out += theory.abs_weight_diff_1to4_bonus
        elif 5 <= abs_weight_diff <= 8:
            out -= theory.abs_weight_diff_5to8_penalty
        elif abs_weight_diff >= 9:
            out -= theory.abs_weight_diff_9plus_penalty
    return out


def middle_context_score_adjustment(
    features: dict[str, Any],
    theory: TheoryConfig,
    middle_odds: float | None,
    axis_odds: float | None = None,
) -> float:
    out = 0.0
    same_dist_bucket = rate_bucket(features.get("same_dist_top3_rate"))
    if same_dist_bucket == "lt_0_15":
        out += theory.middle_same_dist_lt_0_15_bonus
    elif same_dist_bucket == "0_25_0_35":
        if (
            theory.middle_same_dist_0_25_0_35_bonus_axis_odds_max is None
            or axis_odds is None
            or axis_odds > theory.middle_same_dist_0_25_0_35_bonus_axis_odds_max
        ):
            out += theory.middle_same_dist_0_25_0_35_bonus
    elif same_dist_bucket == "ge_0_35":
        out -= theory.middle_same_dist_ge_0_35_penalty
    elif same_dist_bucket == "missing":
        out += theory.middle_same_dist_missing_bonus

    jockey_same_surface_bucket = rate_bucket(features.get("jockey_recent_same_surface_top3_rate"))
    if jockey_same_surface_bucket == "lt_0_15":
        out += theory.middle_jockey_same_surface_lt_0_15_bonus
    elif jockey_same_surface_bucket == "0_25_0_35":
        out += theory.middle_jockey_same_surface_0_25_0_35_bonus
    elif jockey_same_surface_bucket == "ge_0_35":
        out -= theory.middle_jockey_same_surface_ge_0_35_penalty

    trainer_same_distance_bucket = rate_bucket(features.get("trainer_recent_same_distance_bucket_top3_rate"))
    if trainer_same_distance_bucket == "0_25_0_35":
        out += theory.middle_trainer_same_distance_0_25_0_35_bonus
    elif trainer_same_distance_bucket == "ge_0_35":
        out += theory.middle_trainer_same_distance_ge_0_35_bonus

    size_bucket = field_size_bucket(features.get("field_size"))
    if size_bucket == "ge_14":
        out += theory.middle_field_size_ge_14_bonus
        if middle_odds is not None and middle_odds > 10.0:
            out -= theory.middle_large_field_odds_over_10_penalty
    elif size_bucket == "le_10":
        out -= theory.middle_field_size_le_10_penalty
    return out


def axis_context_score_adjustment(features: dict[str, Any], theory: TheoryConfig) -> float:
    out = 0.0
    same_dist_bucket = rate_bucket(features.get("same_dist_top3_rate"))
    if same_dist_bucket == "ge_0_35":
        out += theory.axis_same_dist_ge_0_35_bonus
    elif same_dist_bucket == "0_25_0_35":
        out += theory.axis_same_dist_0_25_0_35_bonus
    elif same_dist_bucket == "lt_0_15":
        out -= theory.axis_same_dist_lt_0_15_penalty

    jockey_recent_bucket = rate_bucket(features.get("jockey_recent_top3_rate"))
    if jockey_recent_bucket == "ge_0_35":
        out += theory.axis_jockey_recent_ge_0_35_bonus
    elif jockey_recent_bucket == "lt_0_15":
        out -= theory.axis_jockey_recent_lt_0_15_penalty

    trainer_recent_bucket = rate_bucket(features.get("trainer_recent_top3_rate"))
    if trainer_recent_bucket == "ge_0_35":
        out += theory.axis_trainer_recent_ge_0_35_bonus
    elif trainer_recent_bucket == "lt_0_15":
        out -= theory.axis_trainer_recent_lt_0_15_penalty

    same_surface_bucket = rate_bucket(features.get("same_surface_top3_rate"))
    if same_surface_bucket == "ge_0_35":
        out += theory.axis_same_surface_ge_0_35_bonus
    elif same_surface_bucket == "lt_0_15":
        out -= theory.axis_same_surface_lt_0_15_penalty

    size_bucket = field_size_bucket(features.get("field_size"))
    if size_bucket == "ge_14":
        out += theory.axis_field_size_ge_14_bonus
    elif size_bucket == "le_10":
        out -= theory.axis_field_size_le_10_penalty
    return out


def feature_at_least(features: dict[str, Any], key: str, threshold: float | None) -> bool:
    if threshold is None:
        return True
    value = features.get(key)
    return value is not None and float(value) >= threshold


def middle_context_allowed(features: dict[str, Any], theory: TheoryConfig, middle_odds: float | None) -> bool:
    if not (
        feature_at_least(features, "jockey_recent_top3_rate", theory.middle_min_jockey_recent_top3_rate)
        and feature_at_least(features, "trainer_recent_top3_rate", theory.middle_min_trainer_recent_top3_rate)
        and feature_at_least(features, "same_course_top3_rate", theory.middle_min_same_course_top3_rate)
        and feature_at_least(features, "same_dist_top3_rate", theory.middle_min_same_dist_top3_rate)
    ):
        return False
    if theory.middle_allowed_trainer_recent_top3_rate_buckets is not None:
        if rate_bucket(features.get("trainer_recent_top3_rate")) not in theory.middle_allowed_trainer_recent_top3_rate_buckets:
            return False
    if theory.middle_allowed_same_dist_rate_buckets is not None:
        if rate_bucket(features.get("same_dist_top3_rate")) not in theory.middle_allowed_same_dist_rate_buckets:
            return False
    if theory.middle_allowed_jockey_same_surface_rate_buckets is not None:
        if (
            rate_bucket(features.get("jockey_recent_same_surface_top3_rate"))
            not in theory.middle_allowed_jockey_same_surface_rate_buckets
        ):
            return False
    if theory.middle_allowed_trainer_same_distance_rate_buckets is not None:
        if (
            rate_bucket(features.get("trainer_recent_same_distance_bucket_top3_rate"))
            not in theory.middle_allowed_trainer_same_distance_rate_buckets
        ):
            return False
    size_bucket = field_size_bucket(features.get("field_size"))
    if theory.middle_allowed_field_size_buckets is not None and size_bucket not in theory.middle_allowed_field_size_buckets:
        return False
    if (
        theory.large_field_middle_odds_max is not None
        and size_bucket == "ge_14"
        and middle_odds is not None
        and middle_odds > theory.large_field_middle_odds_max
    ):
        return False
    return True


def yen_to_int(value: Any) -> int:
    if value is None:
        return 0
    match = re.search(r"\d[\d,]*", str(value))
    return int(match.group(0).replace(",", "")) if match else 0


def wide_payout_map(payouts: list[Any]) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for payout in payouts:
        if payout.bet_type != "wide":
            continue
        values = re.findall(r"\d+", payout.combination)
        key = tuple(sorted((str(value) for value in values), key=lambda value: int(value)))
        if len(key) == 2:
            out[key] = yen_to_int(payout.payout)
    return out


def ticket_middle_allowed(
    middle: dict[str, Any],
    theory: TheoryConfig,
    axis_popularity: str,
    axis_odds_bucket_value: str,
    odds_ratio_bucket: str,
) -> bool:
    middle_popularity = str(int_or_none(middle["nk"].popularity) or "missing")
    axis_middle_pair = f"{axis_popularity}:{middle_popularity}"
    if theory.ticket_allowed_axis_popularity_buckets is not None:
        if axis_popularity not in theory.ticket_allowed_axis_popularity_buckets:
            return False
    if theory.ticket_allowed_middle_popularity_buckets is not None:
        if middle_popularity not in theory.ticket_allowed_middle_popularity_buckets:
            return False
    if theory.ticket_allowed_axis_middle_popularity_pairs is not None:
        if axis_middle_pair not in theory.ticket_allowed_axis_middle_popularity_pairs:
            return False
    if theory.ticket_allowed_axis_odds_buckets is not None:
        if axis_odds_bucket_value not in theory.ticket_allowed_axis_odds_buckets:
            return False
    if theory.ticket_allowed_odds_ratio_buckets is not None:
        if odds_ratio_bucket not in theory.ticket_allowed_odds_ratio_buckets:
            return False
    if theory.ticket_allowed_middle_same_course_top3_rate_buckets is not None:
        if (
            rate_bucket(middle["features"].get("same_course_top3_rate"))
            not in theory.ticket_allowed_middle_same_course_top3_rate_buckets
        ):
            return False
    if theory.ticket_allowed_middle_trainer_recent_top3_rate_buckets is not None:
        if (
            rate_bucket(middle["features"].get("trainer_recent_top3_rate"))
            not in theory.ticket_allowed_middle_trainer_recent_top3_rate_buckets
        ):
            return False
    if theory.ticket_allowed_middle_jockey_recent_top3_rate_buckets is not None:
        if (
            rate_bucket(middle["features"].get("jockey_recent_top3_rate"))
            not in theory.ticket_allowed_middle_jockey_recent_top3_rate_buckets
        ):
            return False
    return True


async def evaluate_race(
    service: NetkeibaService,
    races: dict[str, list[dict[str, Any]]],
    history: HistoryBundle,
    db_results_by_jra: dict[str, Any],
    nk_by_jra: dict[str, str],
    jra_race_id: str,
    theory: TheoryConfig,
) -> RaceEvaluation:
    race_rows = races[jra_race_id]
    meta = race_rows[0]
    nk_race_id = nk_by_jra.get(jra_race_id) or netkeiba_race_id(jra_race_id, meta["race_date"], int(meta["race_no"]))
    base = {
        "jra_race_id": jra_race_id,
        "netkeiba_race_id": nk_race_id,
        "race_date": meta["race_date"],
        "course_code": course_code(jra_race_id),
        "race_no": int(meta["race_no"]),
        "race_name": meta.get("race_name"),
    }
    if nk_race_id is None:
        return RaceEvaluation(**base, status="excluded", reason="missing_netkeiba_mapping")
    result = db_results_by_jra.get(jra_race_id)
    if result is None:
        try:
            result = await service.get_race_result(nk_race_id)
        except Exception as exc:  # noqa: BLE001 - record upstream failures as exclusions.
            return RaceEvaluation(**base, status="excluded", reason=f"netkeiba_result_error:{type(exc).__name__}")
    if not result.results or not result.payouts:
        return RaceEvaluation(**base, status="excluded", reason="missing_result_or_payout")
    nk_by_name = {norm_name(item.horse_name): item for item in result.results}
    candidates = []
    matched = 0
    for row in race_rows:
        nk = nk_by_name.get(norm_name(row["horse_name"]))
        if nk is None:
            continue
        matched += 1
        hist = history.horses[row["horse_name"]]
        if len(hist) < theory.min_history:
            continue
        features = hist_features(hist, row, history)
        candidates.append({"row": row, "nk": nk, "features": features, "score": score(features, theory, nk=nk)})
    if result.results and matched / len(result.results) < 0.7:
        return RaceEvaluation(**base, status="excluded", reason=f"low_name_match:{matched}/{len(result.results)}")
    if len(candidates) < theory.min_candidates:
        return RaceEvaluation(**base, status="excluded", reason=f"few_candidates:{len(candidates)}")
    ranked = sorted(candidates, key=lambda item: item["score"], reverse=True)
    for candidate in ranked:
        candidate["axis_score"] = candidate["score"] + axis_context_score_adjustment(candidate["features"], theory)
    axis_ranked = sorted(ranked, key=lambda item: item.get("axis_score", item["score"]), reverse=True)
    if theory.axis_odds_max is None:
        axis = axis_ranked[0]
    else:
        axis = next(
            (
                candidate
                for candidate in axis_ranked
                if (odds := odds_to_float(candidate["nk"].win_odds)) is not None
                and odds <= theory.axis_odds_max
                and (
                    theory.axis_popularity_max is None
                    or (
                        (popularity := int_or_none(candidate["nk"].popularity)) is not None
                        and popularity <= theory.axis_popularity_max
                    )
                )
                and (
                    theory.axis_max_abs_weight_diff is None
                    or (
                        (weight_diff := int_or_none(candidate["nk"].horse_weight_diff)) is not None
                        and abs(weight_diff) <= theory.axis_max_abs_weight_diff
                    )
                )
            ),
            axis_ranked[0],
        )
    middles = []
    axis_odds = odds_to_float(axis["nk"].win_odds)
    for candidate in ranked:
        if candidate is axis:
            continue
        odds = odds_to_float(candidate["nk"].win_odds)
        candidate["middle_score"] = candidate["score"] + middle_context_score_adjustment(
            candidate["features"], theory, odds, axis_odds
        )
    middle_ranked = sorted(
        (candidate for candidate in ranked if candidate is not axis),
        key=lambda item: item.get("middle_score", item["score"]),
        reverse=True,
    )
    for candidate in middle_ranked:
        odds = odds_to_float(candidate["nk"].win_odds)
        if odds is not None and theory.middle_odds_min <= odds <= theory.middle_odds_max:
            if not middle_context_allowed(candidate["features"], theory, odds):
                continue
            if theory.middle_max_abs_weight_diff is not None:
                weight_diff = int_or_none(candidate["nk"].horse_weight_diff)
                if weight_diff is None or abs(weight_diff) > theory.middle_max_abs_weight_diff:
                    continue
            if (
                not middles
                and theory.first_middle_min_axis_score_gap is not None
                and axis["score"] - candidate["score"] <= theory.first_middle_min_axis_score_gap
            ):
                continue
            if (
                middles
                and theory.second_middle_min_axis_score_gap is not None
                and axis["score"] - candidate["score"] <= theory.second_middle_min_axis_score_gap
            ):
                continue
            middles.append(candidate)
        if len(middles) >= theory.max_middles:
            break
    single_middle_override = False
    if len(middles) < theory.min_middles_to_bet:
        if (
            len(middles) == 1
            and theory.single_middle_min_axis_score_gap is not None
            and theory.single_middle_min_odds_ratio is not None
        ):
            middle_odds = odds_to_float(middles[0]["nk"].win_odds)
            axis_odds = odds_to_float(axis["nk"].win_odds)
            odds_ratio = (middle_odds / axis_odds) if middle_odds is not None and axis_odds not in (None, 0) else None
            score_gap = axis["score"] - middles[0]["score"]
            if (
                odds_ratio is not None
                and odds_ratio > theory.single_middle_min_odds_ratio
                and score_gap > theory.single_middle_min_axis_score_gap
            ):
                single_middle_override = True
        if not single_middle_override:
            return RaceEvaluation(
                **base,
                status="evaluated",
                reason=f"insufficient_middle_candidates:{len(middles)}",
                axis_name=axis["nk"].horse_name,
                axis_no=axis["nk"].horse_no,
                axis_rank=int(axis["nk"].rank),
                axis_odds=odds_to_float(axis["nk"].win_odds),
                axis_top3=int(axis["nk"].rank) <= 3,
                tickets=[],
                hit_tickets=[],
                payouts=[],
            )
    if (
        not single_middle_override
        and middles
        and theory.standard_max_middles is not None
        and len(middles) > theory.standard_max_middles
    ):
        middles = middles[: theory.standard_max_middles]
    if (
        not single_middle_override
        and middles
        and theory.standard_axis_odds_max_for_ratio_guard is not None
        and theory.standard_min_first_middle_odds_ratio is not None
    ):
        middle_odds = odds_to_float(middles[0]["nk"].win_odds)
        axis_odds = odds_to_float(axis["nk"].win_odds)
        odds_ratio = (middle_odds / axis_odds) if middle_odds is not None and axis_odds not in (None, 0) else None
        if (
            axis_odds is not None
            and odds_ratio is not None
            and (
                theory.standard_axis_odds_min_for_ratio_guard is None
                or axis_odds > theory.standard_axis_odds_min_for_ratio_guard
            )
            and axis_odds <= theory.standard_axis_odds_max_for_ratio_guard
            and (
                (
                    theory.standard_max_first_middle_odds_ratio_exclusive is None
                    and odds_ratio <= theory.standard_min_first_middle_odds_ratio
                )
                or (
                    theory.standard_max_first_middle_odds_ratio_exclusive is not None
                    and odds_ratio >= theory.standard_min_first_middle_odds_ratio
                    and odds_ratio < theory.standard_max_first_middle_odds_ratio_exclusive
                )
            )
        ):
            return RaceEvaluation(
                **base,
                status="evaluated",
                reason=f"compressed_standard_shape:{axis_odds:.1f}:{odds_ratio:.2f}",
                axis_name=axis["nk"].horse_name,
                axis_no=axis["nk"].horse_no,
                axis_rank=int(axis["nk"].rank),
                axis_odds=axis_odds,
                axis_top3=int(axis["nk"].rank) <= 3,
                middle_top3_count=sum(1 for middle in middles if int(middle["nk"].rank) <= 3),
                tickets=[],
                hit_tickets=[],
                payouts=[],
            )
    field_size = int(race_rows[0].get("field_size") or len(race_rows)) 
    surface = str(meta.get("surface") or "") 
    if theory.excluded_course_codes is not None and base["course_code"] in theory.excluded_course_codes:
        return RaceEvaluation(
            **base,
            status="evaluated",
            reason=f"course_code_excluded:{base['course_code']}",
            axis_name=axis["nk"].horse_name,
            axis_no=axis["nk"].horse_no,
            axis_rank=int(axis["nk"].rank),
            axis_odds=odds_to_float(axis["nk"].win_odds),
            axis_top3=int(axis["nk"].rank) <= 3,
            middle_top3_count=sum(1 for middle in middles if int(middle["nk"].rank) <= 3),
            tickets=[],
            hit_tickets=[],
            payouts=[],
        )
    if theory.allowed_course_codes is not None and base["course_code"] not in theory.allowed_course_codes:
        return RaceEvaluation(
            **base,
            status="evaluated",
            reason=f"course_code_not_allowed:{base['course_code']}",
            axis_name=axis["nk"].horse_name,
            axis_no=axis["nk"].horse_no,
            axis_rank=int(axis["nk"].rank),
            axis_odds=odds_to_float(axis["nk"].win_odds),
            axis_top3=int(axis["nk"].rank) <= 3,
            middle_top3_count=sum(1 for middle in middles if int(middle["nk"].rank) <= 3),
            tickets=[],
            hit_tickets=[],
            payouts=[],
        )
    if theory.surface_to_bet is not None and surface != theory.surface_to_bet: 
        return RaceEvaluation( 
            **base, 
            status="evaluated",
            reason="surface_not_allowed",
            axis_name=axis["nk"].horse_name,
            axis_no=axis["nk"].horse_no,
            axis_rank=int(axis["nk"].rank),
            axis_odds=odds_to_float(axis["nk"].win_odds),
            axis_top3=int(axis["nk"].rank) <= 3,
            middle_top3_count=sum(1 for middle in middles if int(middle["nk"].rank) <= 3),
            tickets=[],
            hit_tickets=[],
            payouts=[],
        )
    axis_odds = odds_to_float(axis["nk"].win_odds)
    if theory.max_axis_odds_to_bet is not None and (
        axis_odds is None or axis_odds > theory.max_axis_odds_to_bet
    ):
        return RaceEvaluation(
            **base,
            status="evaluated",
            reason="axis_odds_above_bet_max",
            axis_name=axis["nk"].horse_name,
            axis_no=axis["nk"].horse_no,
            axis_rank=int(axis["nk"].rank),
            axis_odds=axis_odds,
            axis_top3=int(axis["nk"].rank) <= 3,
            middle_top3_count=sum(1 for middle in middles if int(middle["nk"].rank) <= 3),
            tickets=[],
            hit_tickets=[],
            payouts=[],
        )
    if theory.min_field_size_to_bet is not None and field_size < theory.min_field_size_to_bet:
        return RaceEvaluation(
            **base,
            status="evaluated",
            reason=f"field_size_below_min:{field_size}",
            axis_name=axis["nk"].horse_name,
            axis_no=axis["nk"].horse_no,
            axis_rank=int(axis["nk"].rank),
            axis_odds=odds_to_float(axis["nk"].win_odds),
            axis_top3=int(axis["nk"].rank) <= 3,
            middle_top3_count=sum(1 for middle in middles if int(middle["nk"].rank) <= 3),
            tickets=[],
            hit_tickets=[],
            payouts=[],
        )
    if theory.max_field_size_to_bet is not None and field_size > theory.max_field_size_to_bet:
        return RaceEvaluation(
            **base,
            status="evaluated",
            reason=f"field_size_above_max:{field_size}",
            axis_name=axis["nk"].horse_name,
            axis_no=axis["nk"].horse_no,
            axis_rank=int(axis["nk"].rank),
            axis_odds=odds_to_float(axis["nk"].win_odds),
            axis_top3=int(axis["nk"].rank) <= 3,
            middle_top3_count=sum(1 for middle in middles if int(middle["nk"].rank) <= 3),
            tickets=[],
            hit_tickets=[],
            payouts=[],
        )
    if int(meta["race_no"]) < theory.min_race_no_to_bet:
        return RaceEvaluation(
            **base,
            status="evaluated",
            reason=f"race_no_below_min:{int(meta['race_no'])}",
            axis_name=axis["nk"].horse_name,
            axis_no=axis["nk"].horse_no,
            axis_rank=int(axis["nk"].rank),
            axis_odds=odds_to_float(axis["nk"].win_odds),
            axis_top3=int(axis["nk"].rank) <= 3,
            middle_top3_count=sum(1 for middle in middles if int(middle["nk"].rank) <= 3),
            tickets=[],
            hit_tickets=[],
            payouts=[],
        )
    if theory.max_race_no_to_bet is not None and int(meta["race_no"]) > theory.max_race_no_to_bet:
        return RaceEvaluation(
            **base,
            status="evaluated",
            reason=f"race_no_above_max:{int(meta['race_no'])}",
            axis_name=axis["nk"].horse_name,
            axis_no=axis["nk"].horse_no,
            axis_rank=int(axis["nk"].rank),
            axis_odds=odds_to_float(axis["nk"].win_odds),
            axis_top3=int(axis["nk"].rank) <= 3,
            middle_top3_count=sum(1 for middle in middles if int(middle["nk"].rank) <= 3),
            tickets=[],
            hit_tickets=[],
            payouts=[],
        )
    tickets = []
    filtered_middles = []
    axis_popularity_bucket = str(int_or_none(axis["nk"].popularity) or "missing")
    axis_odds_bucket_value = axis_odds_bucket(axis_odds)
    for middle in middles:
        middle_odds = odds_to_float(middle["nk"].win_odds)
        odds_ratio_bucket = "missing"
        if axis_odds not in (None, 0) and middle_odds is not None:
            ratio = middle_odds / axis_odds
            if ratio < 2.0:
                odds_ratio_bucket = "lt_2"
            elif ratio < 3.5:
                odds_ratio_bucket = "2_3_5"
            elif ratio < 5.0:
                odds_ratio_bucket = "3_5_5"
            else:
                odds_ratio_bucket = "ge_5"
        if ticket_middle_allowed(middle, theory, axis_popularity_bucket, axis_odds_bucket_value, odds_ratio_bucket):
            filtered_middles.append(middle)
    for middle in filtered_middles:
        tickets.append(tuple(sorted([str(axis["nk"].horse_no), str(middle["nk"].horse_no)], key=lambda value: int(value))))
    payout_by_combo = wide_payout_map(result.payouts)
    hit_tickets = ["-".join(ticket) for ticket in tickets if ticket in payout_by_combo]
    ticket_payouts = [payout_by_combo.get(ticket, 0) for ticket in tickets]
    return RaceEvaluation(
        **base,
        status="evaluated",
        axis_name=axis["nk"].horse_name,
        axis_no=axis["nk"].horse_no,
        axis_rank=int(axis["nk"].rank),
        axis_odds=odds_to_float(axis["nk"].win_odds),
        axis_top3=int(axis["nk"].rank) <= 3,
        middle_top3_count=sum(1 for middle in filtered_middles if int(middle["nk"].rank) <= 3),
        tickets=["-".join(ticket) for ticket in tickets],
        hit_tickets=hit_tickets,
        payouts=ticket_payouts,
        bet=len(tickets) * BUDGET_PER_TICKET,
        payout=sum(ticket_payouts),
    )


def summarize(evaluations: list[RaceEvaluation], theory: TheoryConfig, from_date: str, to_date: str) -> dict[str, Any]:
    evaluated = [item for item in evaluations if item.status == "evaluated"]
    excluded = [item for item in evaluations if item.status == "excluded"]
    bet_races = [item for item in evaluated if item.bet > 0]
    tickets = [ticket for item in evaluated for ticket in (item.tickets or [])]
    hits = [ticket for item in evaluated for ticket in (item.hit_tickets or [])]
    payouts = [payout for item in evaluated for payout in (item.payouts or []) if payout > 0]
    total_bet = sum(item.bet for item in evaluated)
    total_payout = sum(item.payout for item in evaluated)
    payout_without_max = total_payout - max(payouts, default=0)
    payout_without_top3 = total_payout - sum(sorted(payouts, reverse=True)[:3])
    return {
        "theory_version": theory.version,
        "theory_note": theory.score_note,
        "evaluation_period": f"{from_date}..{to_date}",
        "candidate_races": len(evaluations),
        "evaluated_races": len(evaluated),
        "excluded_races": len(excluded),
        "bet_races": len(bet_races),
        "tickets": len(tickets),
        "hits": len(hits),
        "total_bet": total_bet,
        "total_payout": total_payout,
        "return_rate": round(total_payout / total_bet, 4) if total_bet else None,
        "return_rate_without_max_payout": round(payout_without_max / total_bet, 4) if total_bet else None,
        "return_rate_without_top3_payouts": round(payout_without_top3 / total_bet, 4) if total_bet else None,
        "axis_top3_rate": round(sum(1 for item in evaluated if item.axis_top3) / len(evaluated), 4) if evaluated else None,
        "middle_hole_top3_rate": round(
            sum(item.middle_top3_count for item in evaluated if item.tickets) / len(tickets), 4
        )
        if tickets
        else None,
        "wide_hit_rate": round(len(hits) / len(tickets), 4) if tickets else None,
        "average_tickets_per_evaluated_race": round(len(tickets) / len(evaluated), 4) if evaluated else None,
        "skip_rate": round(sum(1 for item in evaluated if item.bet == 0) / len(evaluated), 4) if evaluated else None,
        "exclusion_rate": round(len(excluded) / len(evaluations), 4) if evaluations else None,
        "max_payout": max(payouts, default=0),
    }


def write_outputs(
    output_dir: Path,
    evaluations: list[RaceEvaluation],
    summary: dict[str, Any],
    theory: TheoryConfig,
    period_label: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    version = theory.version
    rows = []
    for item in evaluations:
        rows.append(
            {
                "jra_race_id": item.jra_race_id,
                "netkeiba_race_id": item.netkeiba_race_id,
                "race_date": item.race_date,
                "course_code": item.course_code,
                "race_no": item.race_no,
                "race_name": item.race_name,
                "status": item.status,
                "reason": item.reason,
                "axis_name": item.axis_name,
                "axis_no": item.axis_no,
                "axis_rank": item.axis_rank,
                "axis_odds": item.axis_odds,
                "axis_top3": item.axis_top3,
                "middle_top3_count": item.middle_top3_count,
                "tickets": item.tickets or [],
                "hit_tickets": item.hit_tickets or [],
                "payouts": item.payouts or [],
                "bet": item.bet,
                "payout": item.payout,
            }
        )
    (output_dir / f"{version}_{period_label}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / f"{version}_{period_label}_races.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    reasons: dict[str, int] = defaultdict(int)
    for item in evaluations:
        if item.status == "excluded":
            reasons[item.reason or "unknown"] += 1
    report = [
        "# Prediction Evaluation Report",
        "",
        "## 対象",
        f"- theory_version: {version}",
        f"- theory_note: {theory.score_note}",
        f"- evaluation_period: {summary['evaluation_period']}",
        "- data_sources: JRA analysis.sqlite, netkeiba race_result, netkeiba odds_view when needed",
        "- excluded_contaminated_periods: 2026-06-28 Fukushima is outside this validation period",
        "",
        "## ルール",
        "- axis_rule: target race dateより前の過去走スコア最大馬",
        "- middle_hole_rule: 軸以外、単勝8.0から30.0倍、過去走スコア上位から最大2頭",
        "- ticket_rule: wide, axis-middle, 100円, max 2 tickets per race",
        "- exclusion_rule: docs/jra/12_予想エージェント評価プロトコル.md v1 conditions",
        "",
        "## 集計",
    ]
    for key, value in summary.items():
        report.append(f"- {key}: {value}")
    report.extend(["", "## 除外理由"])
    for reason, count in sorted(reasons.items(), key=lambda item: (-item[1], item[0])):
        report.append(f"- {reason}: {count}")
    top_hits = sorted([item for item in evaluations if item.payout > 0], key=lambda item: item.payout, reverse=True)[:10]
    report.extend(["", "## 的中上位"])
    for item in top_hits:
        report.append(
            f"- {item.race_date} {item.course_code}R{item.race_no} {item.race_name}: "
            f"{item.hit_tickets} payout={item.payout} axis={item.axis_name} rank={item.axis_rank}"
        )
    decision = "needs_more_test"
    decision_reason = "Validation metrics were checked, but holdout has not been run yet."
    if period_label == "holdout":
        failed_checks: list[str] = []
        if summary["return_rate"] < 1.0:
            failed_checks.append(f"ROI {summary['return_rate']:.4f} < 1.0000")
        if summary["axis_top3_rate"] < 0.45:
            failed_checks.append(f"axis_top3_rate {summary['axis_top3_rate']:.4f} < 0.4500")
        if summary["return_rate_without_max_payout"] < 1.0:
            failed_checks.append(
                "return_rate_without_max_payout "
                f"{summary['return_rate_without_max_payout']:.4f} < 1.0000"
            )
        if failed_checks:
            decision = "reject_release_candidate"
            decision_reason = "; ".join(failed_checks)
        else:
            decision = "promote_release_candidate"
            decision_reason = "Holdout pass criteria are satisfied."
    report.extend(
        [
            "",
            "## 採用判断",
            f"- decision: {decision}",
            f"- reason: {decision_reason}",
        ]
    )
    (output_dir / f"{version}_{period_label}_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/analysis.sqlite")
    parser.add_argument("--output-dir", default=".workstate/jra-srb/prediction-v1-validation")
    parser.add_argument("--cache-dir", default=".workstate/jra-srb/prediction-v1-validation/netkeiba-cache")
    parser.add_argument("--min-interval", type=float, default=5.0)
    parser.add_argument("--max-live-requests", type=int, default=30)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--theory-version", choices=sorted(THEORIES), default="v1")
    parser.add_argument("--from-date", default=VALIDATION_FROM)
    parser.add_argument("--to-date", default=VALIDATION_TO)
    parser.add_argument("--period-label", default="validation")
    args = parser.parse_args()

    theory = THEORIES[args.theory_version]
    races = load_rows(Path(args.db))
    db_results_by_jra, nk_by_jra = load_netkeiba_db_results(Path(args.db))
    history = build_history(races, args.from_date)
    race_ids = race_ids_in_period(races, args.from_date, args.to_date)
    if args.limit is not None:
        race_ids = race_ids[: args.limit]
    provider = DiskCachedNetkeibaProvider(
        inner=NetkeibaHttpProvider(
            min_interval_seconds=args.min_interval,
            timeout=15.0,
            retries=1,
        ),
        cache_dir=Path(args.cache_dir),
        offline=args.offline,
        max_live_requests=args.max_live_requests,
    )
    service = NetkeibaService(
        provider=provider
    )
    evaluations = []
    for index, race_id in enumerate(race_ids, 1):
        evaluation = await evaluate_race(service, races, history, db_results_by_jra, nk_by_jra, race_id, theory)
        evaluations.append(evaluation)
        print(
            f"{index}/{len(race_ids)} {race_id} {evaluation.netkeiba_race_id} "
            f"{evaluation.status} {evaluation.reason or ''} bet={evaluation.bet} payout={evaluation.payout}",
            flush=True,
        )
        if (
            not args.offline
            and args.max_live_requests is not None
            and provider.live_requests >= args.max_live_requests
        ):
            print(f"stopped: max_live_requests reached ({provider.live_requests})", flush=True)
            break
    summary = summarize(evaluations, theory, args.from_date, args.to_date)
    summary["live_requests"] = provider.live_requests
    summary["cache_dir"] = str(Path(args.cache_dir))
    write_outputs(Path(args.output_dir), evaluations, summary, theory, args.period_label)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
