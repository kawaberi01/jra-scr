"""概要: 保存D0早朝予想を利用者指定テンプレートで提示し、印と全文を別IDで保存する。
作成日: 2026-10-25
入力: 既存D0予想payload、確認済みMarkdown、共通SQL設定。
出力: 新IDのpayload/表示本文/SQLとAPI読戻し証跡。
実行例: uv run python scripts/save_jra_d0_template.py
注意事項: 早朝入力を再利用し再予測しない。SQL予想書込のみ、結果取得/購入なし。
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.request

from jra_srb.storage import build_analysis_store
from jra_srb.storage_config import storage_backend

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    """新規の監査JSONを排他的に保存する。"""
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


def run():
    """D0の全確率を保持し、表示印・参考断層・予算0と全文を保存/照合する。"""
    out = ROOT/'artifacts/predictions/20261025-D0-template'
    source = json.loads((ROOT/'artifacts/predictions/20261025-early-D0/prediction_payload.json').read_text(encoding='utf-8'))
    payload = deepcopy(source)
    now = datetime.now(timezone.utc)
    assert now < datetime.fromisoformat('2026-10-25T15:40:00+09:00')
    assert storage_backend() == 'sqlserver' and payload['prediction_json']['forecast']['case'] == 'D0'
    key = f"jra-{payload['race_id']}-D0-template-{now.strftime('%Y%m%dT%H%M%SZ')}"
    text = (out/'presentation.md').read_text(encoding='utf-8').replace('{{prediction_id}}', key)
    payload.update(prediction_id=key, created_at=now.isoformat(), theory_version='market-attribute-chimera:D0:skill-template:v1')
    p = payload['prediction_json']
    assert p['predicted_ranking'][:6] == ['08', '10', '09', '05', '02', '03']
    p.update(marks={'08': '◎', '10': '○', '09': '▲', '05': '△', '02': '△', '03': '☆'},
        opponent_horse_numbers=['10', '09', '05', '02', '03'], presentation_markdown=text,
        based_on_prediction_id=source['prediction_id'], same_day_recheck_required=True,
        dansou_reference={'as_of': source['pre_race_snapshot']['odds']['fetched_at'], 'pattern': 4,
            'ratios': [4.1/1.8, 11.4/4.1, 12.9/11.4, 19.4/12.9, 20.7/19.4],
            'reference_single_candidate': '10', 'reference_single_odds': 4.1, 'main_tickets_changed': False})
    assert p['prediction_tickets'] == payload['prediction_tickets'] == [] and payload['budget'] == 0
    save(out/'prediction_payload.json', payload)
    store = build_analysis_store(ROOT/'data/db/analysis.sqlite')
    try:
        store.upsert_prediction_record(payload)
        saved = store.get_prediction_record(key)
        assert saved.prediction == p and saved.race_id == payload['race_id'] and not saved.prediction_tickets
    finally:
        if hasattr(store, 'close'):
            store.close()
    with urllib.request.urlopen('http://127.0.0.1:8000/jra/predictions/'+key, timeout=20) as response:
        actual = json.load(response)
    save(out/'api-readback.json', actual)
    assert actual['prediction'] == p and actual['pre_race_snapshot'] == payload['pre_race_snapshot']
    assert actual['prediction_id'] == key and actual['race_id'] == payload['race_id']
    assert actual['prediction_tickets'] == [] and actual['budget'] == 0
    (out/'rendered.md').open('x', encoding='utf-8').write(text)
    save(out/'verification.json', {'status': 'passed', 'prediction_id': key, 'full_prediction_and_snapshot_equal': True,
        'D0_forecast_unchanged': p['forecast'] == source['prediction_json']['forecast'], 'purchase_yen': 0, 'result_reads': 0})
    print(key)


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        save(ROOT/'artifacts/predictions/20261025-D0-template/failure.json', {'type': type(error).__name__, 'stage': 'template_save'})
        raise
