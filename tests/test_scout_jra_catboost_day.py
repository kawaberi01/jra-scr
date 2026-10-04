"""概要：日次スカウトの取得上限・失敗継続・キャッシュ再開を検証する。
作成日：2026-10-04
入力：pytest、一時ディレクトリ、モックAPI。
出力：テスト結果。
実行例：rtk uv run python -X utf8 -m pytest -q tests/test_scout_jra_catboost_day.py
注意事項：外部通信や実SQLiteへの書き込みは行わない。
"""

from datetime import date, datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import httpx


def load_scout():
    """CLIスクリプトを実行せずに読み込む。"""
    spec = importlib.util.spec_from_file_location(
        "catboost_scout", Path(__file__).parents[1] / "scripts/scout_jra_catboost_day.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_timeout_counts_toward_batch_limit_and_empty_input(tmp_path, monkeypatch):
    """タイムアウトも取得上限に数え、推論対象ゼロでも結果を保存する。"""
    scout = load_scout()
    target = date.today() + timedelta(days=1)
    schedule = [dict(race_id=f"race{i}", start_time="15:00", race_name="通常戦",
                     course="tokyo", race_no=i) for i in range(1, 4)]
    fetched = []

    def get(path, **kwargs):
        """開催一覧を返し、個別出馬表ではタイムアウトを再現する。"""
        if path == "/search/races":
            return httpx.Response(200, json={"items": schedule},
                                  request=httpx.Request("GET", "http://test/search/races"))
        fetched.append(path)
        raise httpx.ReadTimeout("test timeout")

    client = SimpleNamespace(get=get, close=lambda: None)
    monkeypatch.setattr(scout.httpx, "Client", lambda **kwargs: client)
    monkeypatch.setattr(scout, "AnalysisSQLiteStore", lambda db: SimpleNamespace(
        list_pre_race_race_ids=lambda day: []))
    monkeypatch.setattr(scout, "load_model_artifact", lambda path: {})
    monkeypatch.setattr(scout, "load_ranker", lambda path: SimpleNamespace())
    monkeypatch.setattr(sys, "argv", ["scout", "--date", target.isoformat(),
        "--ranker-model", "unused.cbm", "--output-dir", str(tmp_path),
        "--fill-missing", "--max-fetches", "2"])
    scout.main()
    output = json.loads(next(tmp_path.glob("day_scout_*.json")).read_text(encoding="utf-8"))
    assert len(fetched) == output["fetches"] == 2
    assert output["remaining"] == 3
    assert output["analyzed_count"] == 0
    assert output["status"] == "partial"
    assert [r["reason"] for r in output["excluded"]] == [
        "取得失敗：ReadTimeout", "取得失敗：ReadTimeout", "今回の取得範囲外：次バッチで補完"]


def test_checkpoint_reuse_rejects_stale_and_future_cards(tmp_path, monkeypatch):
    """保存したカードを再利用し、期限切れと未来時刻のカードを拒否する。"""
    scout = load_scout()
    now = datetime.now(timezone.utc)
    card = SimpleNamespace(race_id="race1", fetched_at=now,
                           model_dump_json=lambda indent: "{}")
    monkeypatch.setattr(scout, "RaceCard", SimpleNamespace(model_validate_json=lambda value: card))
    scout.checkpoint_card(card, tmp_path)
    assert scout.cached_card("race1", now + timedelta(seconds=299), tmp_path, 300) is card
    assert scout.cached_card("race1", now + timedelta(seconds=300), tmp_path, 300) is None
    assert scout.cached_card("race1", now - timedelta(seconds=1), tmp_path, 300) is None
    assert scout.cached_card("race2", now, tmp_path, 300) is None
