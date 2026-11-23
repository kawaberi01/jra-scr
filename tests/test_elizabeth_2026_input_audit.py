"""概要: 公式馬別履歴の未来遮断・同定・異常着順の扱いを検証する。
作成日: 2026-11-13。
入力: 合成HTMLとpytest。
出力: 合否。
実行例: uv run pytest -q tests/test_elizabeth_2026_input_audit.py
注意事項: DB・外部通信なし。
"""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def audit_module():
    """監査CLIの純粋関数だけをロードする。"""
    path = Path(__file__).resolve().parents[1] / "scripts/audit_elizabeth_2026_inputs.py"
    spec = importlib.util.spec_from_file_location("elizabeth_audit_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def profile(rank="3", day="2026年10月11日", compact="20261011"):
    """公式表と同じ列順の最小成績表を作る。"""
    cells = [day, "東京", f'<a href="/JRADB/accessS.html?CNAME=pw01sde10052026040411{compact}/69">試験</a><span class="grade_icon"><img alt="GⅡ"></span>',
             "芝1800", "良", "16", "2", rank, "騎手", "56.0", "490", "1:44.9", "109", "勝馬"]
    return '<table><tr><th>年月日</th><th>場</th><th>レース名</th></tr><tr>' + ''.join(f'<td>{c}</td>' for c in cells) + '</tr></table>'


def test_identity_and_non_numeric_rank(audit_module):
    """URL同定と原表現を保持し、取消を架空の着順にしない。"""
    row = audit_module.parse_history(profile(rank="取消"), "2021107098", "2026-11-15")[0]
    assert row["race_key"] == "202610110511"
    assert row["rank"] is None and row["rank_raw"] == "取消"
    assert row["grade_raw"] == ["GⅡ"] and row["distance"] == 1800


def test_target_day_result_rejected(audit_module):
    """対象日以後の成績を予測前履歴へ入れない。"""
    with pytest.raises(ValueError, match="future_or_target"):
        audit_module.parse_history(profile(day="2026年11月15日", compact="20261115"), "2021107098", "2026-11-15")


def test_link_date_mismatch_rejected(audit_module):
    """表示日付とリンク日付の矛盾を停止する。"""
    with pytest.raises(ValueError, match="link_date_mismatch"):
        audit_module.parse_history(profile(compact="20261012"), "2021107098", "2026-11-15")


def test_recent_disagreement_visible(audit_module):
    """近走の食い違いを一致扱いにしない。"""
    history = audit_module.parse_history(profile(), "2021107098", "2026-11-15")
    runner = {"official_recent_races": [{"source_date": "2026-10-11", "source_course": "東京", "distance": 1800,
                                        "finish_rank": 1, "weight_carried": 56.0}]}
    result = audit_module.compare_recent(runner, history)[0]
    assert result["status"] == "unresolved" and result["differences"][0]["field"] == "finish_rank"
