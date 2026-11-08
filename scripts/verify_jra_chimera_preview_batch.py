"""概要: 研究予想の保存payloadをローカルAPIから読み戻し、全文と発走前時刻を照合する。
作成日: 2026-10-25
入力: --payloadの予想JSON群、--outputの新規出力先。
出力: 各API読戻しJSONとverification/summary.json。
実行例: uv run python scripts/verify_jra_chimera_preview_batch.py --help
注意事項: GETのみ、結果取得/予想書込/購入なし。予想順位は2着内周辺順位。
"""

import argparse
from datetime import datetime
import json
from pathlib import Path
import re
import urllib.request


def read(path):
    """UTF-8の監査対象payloadを読み込む。"""
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    """新規の監査証跡を排他的に保存する。"""
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def verify(payload_paths, output):
    """予想/束/ID/買い目0と発走前時刻を照合し、比較用の順位を返す。"""
    output.mkdir(parents=True, exist_ok=False)
    summaries = []
    for path in payload_paths:
        payload = read(path)
        key = payload['prediction_id']
        assert re.fullmatch(r'[A-Za-z0-9_-]+', key)
        with urllib.request.urlopen('http://127.0.0.1:8000/jra/predictions/'+key, timeout=20) as response:
            actual = json.load(response)
        save(output/(key+'.json'), actual)
        assert actual['prediction_id'] == key and actual['race_id'] == payload['race_id']
        assert actual['prediction'] == payload['prediction_json']
        assert actual['pre_race_snapshot'] == payload['pre_race_snapshot']
        assert actual['prediction_tickets'] == payload['prediction_tickets'] == []
        assert actual['budget'] == payload['budget'] == 0
        assert datetime.fromisoformat(actual['created_at']) == datetime.fromisoformat(payload['created_at'])
        card = payload['pre_race_snapshot']['card']
        match = re.fullmatch(r'(\d{1,2})時(\d{2})分', card['start_time'])
        assert match is not None
        day = payload['race_id'][:8]
        post = datetime.fromisoformat(f'{day[:4]}-{day[4:6]}-{day[6:8]}T{int(match[1]):02d}:{int(match[2]):02d}:00+09:00')
        assert datetime.fromisoformat(payload['created_at']) < post
        p = actual['prediction']
        summaries.append({'prediction_id': key, 'race_id': payload['race_id'], 'case': p['forecast']['case'],
            'ranking_semantics': 'top2_marginal_not_finish_order', 'top5': p['predicted_ranking'][:5],
            'top_pair': p['forecast']['pair_ranking'][0], 'odds_observed_at': payload['pre_race_snapshot']['odds']['fetched_at'],
            'created_at': payload['created_at'], 'purchase_yen': 0})
    assert len({r['prediction_id'] for r in summaries}) == len(summaries)
    assert len({r['odds_observed_at'] for r in summaries}) == 1
    save(output/'summary.json', summaries)
    save(output/'verification.json', {'status': 'passed', 'predictions': len(summaries),
        'full_predictions_and_snapshots_equal': True, 'all_before_post': True, 'purchase_yen': 0, 'result_reads': 0})
    print(json.dumps(summaries, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', nargs='+', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    verify(args.payload, args.output)
