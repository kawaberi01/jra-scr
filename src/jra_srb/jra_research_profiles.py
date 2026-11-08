"""概要: 既存研究族とSQL置換profileの対応・実装状態を登録する。
作成日: 2026-10-15
入力: profile ID。
出力: 必要capability、旧入口、受入試験、対応状態。
実行例: uv run python scripts/run_jra_research.py profiles
注意事項: 未実装の研究を新しいmaskedモデルで代用したり完了扱いしたりしない。
"""

from __future__ import annotations

from .jra_research_contracts import PROFILE_ID, ResearchError


REGISTRY = (
    ("R01", "history_sql_v1", "train_jra_history_model.py", "T71", "history"),
    ("R01", "recent_form_sql_v2", "train_jra_history_model.py --recent-form", "T71", "recent_form"),
    ("R02", "asof_o1o2_sql_v1", "build_jra_o1o2_asof_dataset.py", "T72", "O1_O2_asof"),
    ("R03", "asof_odds_sql_v1", "build_jra_odds_asof_dataset.py", "T72", "odds_asof"),
    ("R04", "o1o2_movement_sql_v1", "evaluate_jra_o1o2_movement.py", "T73", "T30_T10_pair"),
    ("R05", PROFILE_ID, "evaluate_jra_o1o2_cross_pool.py", "T10", "masked46_win_payout"),
    ("R05", "cross_pool_compat_sql_v1", "validate_jra_o1o2_cross_pool.py", "T74", "legacy_history15"),
    ("R06", "v91_compat_sql_v1", "evaluate_jra_v91.py", "T75", "legacy_history43_context"),
    ("R07", "ten_trials_sql_v1", "evaluate_jra_ten_trials.py", "T75", "V92_V101_quinella"),
    ("R08", "second_ten_sql_v1", "evaluate_jra_second_ten.py", "T75", "V102_V111_quinella"),
    ("R09", "v91_score_sql_v1", "score_jra_v91.py", "T76", "model_contract"),
    ("R09", "ten_trials_score_sql_v1", "score_jra_ten_trials.py", "T76", "model_contract"),
    ("R09", "second_ten_score_sql_v1", "score_jra_second_ten.py", "T76", "model_contract"),
    ("R10", "analyze_predictions_v1", "analyze_jra_ten_trials.py", "T77", "prediction_artifact"),
    ("R11", "cross_market_disagreement_sql_v1", "evaluate_cross_market_disagreement.py", "T78", "cross_market"),
    ("R12", "hidden_rebound_sql_v1", "evaluate_hidden_run_rebound.py", "T78", "history_corner"),
    ("R12", "hidden_rebound_external_sql_v1", "evaluate_hidden_run_rebound_external.py", "T78", "history_external"),
    ("R13", "market_overlay_sql_v1", "evaluate_market_price_overlay.py", "T78", "market_history"),
    ("R13", "win_overlay_sql_v1", "evaluate_win_price_overlay.py", "T78", "win_history"),
    ("R14", "catboost_saved_day_sql_v1", "scout_jra_catboost_day.py", "T79", "saved_card_history"),
    ("R15", "cross_pool_saved_race_sql_v1", "score_jra_o1o2_cross_pool_live.py", "T76", "saved_card_asof"),
)

VARIANTS = {
    "v91_compat_sql_v1": ["V91A", "V91B", "V91_selected"],
    "v91_score_sql_v1": ["V91A", "V91B", "V91_selected"],
    "ten_trials_sql_v1": [f"V{i}" for i in range(92, 102)],
    "ten_trials_score_sql_v1": [f"V{i}" for i in range(92, 102)],
    "second_ten_sql_v1": [f"V{i}" for i in range(102, 112)],
    "second_ten_score_sql_v1": [f"V{i}" for i in range(102, 112)],
    PROFILE_ID: ["market", "basic", "cross"],
}


def profiles() -> list[dict]:
    """最低対象の全研究族を未実装も隠さず列挙する。"""
    return [{"family": family, "profile_id": profile, "legacy_entry": entry, "acceptance_test": test,
             "required_capability": capability, "status": "implemented_pending_acceptance" if profile in {PROFILE_ID, "history_sql_v1", "recent_form_sql_v2"} else "pending",
             "variants": VARIANTS.get(profile, []),
             "command": "history" if profile in {"history_sql_v1", "recent_form_sql_v2"} else "run" if profile == PROFILE_ID else None,
             "model_artifacts": ["model_basic.joblib", "model_cross.joblib"] if profile == PROFILE_ID else ["model_history.json"] if profile in {"history_sql_v1", "recent_form_sql_v2"} else []}
            for family, profile, entry, test, capability in REGISTRY]


def require_profile(profile_id: str) -> None:
    """未登録や未実装のprofileを別モデルで代用せず明示拒否する。"""
    item = next((p for p in profiles() if p["profile_id"] == profile_id), None)
    if item is None:
        raise ResearchError("unknown_profile", 2)
    if item["status"] == "pending":
        raise ResearchError("profile_not_implemented", 4, profile_id=profile_id, required_capability=item["required_capability"])
