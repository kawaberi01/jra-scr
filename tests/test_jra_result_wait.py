"""概要: 型付き結果公開待ちの範囲と期限・対象IDを検証する。
作成日: 2026-11-08
入力: 合成APIエラーとJST時刻。
出力: pytest結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_result_wait.py
注意事項: SQL/HTTP/実購入なし。
"""

from datetime import date, datetime
import pytest
from jra_srb.jra_research_result_wait import pending_result


def check(status, code, message, when='2026-11-08T11:00:00+09:00'):
    """東京1Rの公開待ち判定を合成応答で呼ぶ。"""
    return pending_result(status, {'error': {'code': code, 'message': message}}, date(2026, 11, 8),
                          'tokyo', 1, datetime.fromisoformat(when))


def test_result_race_missing_is_pending():
    """一致する結果専用not_foundは待機となる。"""
    assert check(404, 'not_found', 'result race not found for course=tokyo date=2026-11-08 race_no=1') == 'result_not_published'
    assert check(404, 'not_found', 'result selection page not found for date=2026-11-08') == 'result_not_published'


def test_not_finalized_is_pending():
    """従来の公式未確定も待機する。"""
    assert check(400, 'bad_request', 'result or payout is not finalized') == 'not_finalized'


@pytest.mark.parametrize('status,code,message', [
    (404, 'not_found', 'Not Found'), (500, 'internal_error', 'result or payout is not finalized'),
    (404, 'not_found', 'result race not found for course=kyoto date=2026-11-08 race_no=1'),
    (404, 'not_found', 'result race not found for course=tokyo date=2026-11-08 race_no=2'),
    (404, 'not_found', 'prediction not found'), (400, 'bad_request', 'different error')])
def test_other_errors_never_become_pending(status, code, message):
    """別対象や通常障害を公開待ちとして隠さない。"""
    assert check(status, code, message) is None


def test_deadline_is_finite():
    """最終期限を超えて取得を無限に繰り返さない。"""
    assert check(404, 'not_found', 'result selection page not found for date=2026-11-08', '2026-11-08T17:45:00+09:00') is None


def test_plain_route_404_body_is_refused():
    """FastAPIのルート不在JSONは公開待ちと異なる。"""
    assert pending_result(404, {'detail': 'Not Found'}, date(2026, 11, 8), 'tokyo', 1,
                          datetime.fromisoformat('2026-11-08T11:00:00+09:00')) is None
