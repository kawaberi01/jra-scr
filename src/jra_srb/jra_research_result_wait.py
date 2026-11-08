"""概要: 保存済み予想の結果公開待ちと通常HTTP障害を区別する。
作成日: 2026-11-08
入力: 結果保存APIの応答コード/JSON、対象日・場・番号、現在時刻。
出力: 公開待ちであれば理由、通常障害/期限超過ならNone。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_result_wait.py
注意事項: 予想GETや通常ルート404には使用しない。外部通信・実購入なし。
"""

from datetime import datetime, time, timedelta, timezone


def pending_result(status, body, target, course, race_no, now):
    """対象結果APIの型付き公開待ちだけを当日17:45JSTまで許可する。"""
    jst = timezone(timedelta(hours=9))
    deadline = datetime.combine(target, time(17, 45), jst)
    if now >= deadline or not isinstance(body, dict) or not isinstance(body.get('error'), dict):
        return None
    error = body['error']
    code, message = error.get('code'), str(error.get('message', ''))
    if status == 400 and code == 'bad_request' and message == 'result or payout is not finalized':
        return 'not_finalized'
    expected = (f'result race not found for course={course} date={target.isoformat()} race_no={race_no}',
                f'result selection page not found for date={target.isoformat()}')
    if status == 404 and code == 'not_found' and message in expected:
        return 'result_not_published'
    return None
