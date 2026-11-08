"""概要: 2026年10月以降の実開催検証に向け、現在のSQL受領と固定J23初期化を限定確認する。
作成日: 2026-10-23
入力: 既存研究reader、固定J23モデル/月別履歴、対象日のnative race ID。
出力: j23_october_trial_20261023/readiness.json。
実行例: uv run --frozen --extra ml python -X utf8 .workstate/jra-srb/sqlserver-model-data-audit/diagnostics/audit_october_trial_readiness_20261023.py
注意事項: SELECTのみ、本文を保存せず、学習・予測・SQL保存・API取得はしない。
"""

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

from jra_srb.jra_research_contracts import ResearchError
from jra_srb.jra_research_j23_live import load_frozen
from jra_srb.jra_research_reader import ResearchReader
from jra_srb.jra_research_runtime_sql import _preflight


ROOT = Path(__file__).resolve().parents[4]
OUT = ROOT/'artifacts/jra_research/j23_october_trial_20261023'


def main():
    """読取権限/受領metadataと10月・11月初期化を照合し、未完条件を保存する。"""
    OUT.mkdir(exist_ok=True)
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'evaluation_start': '2026-10-01',
              'target_priority': 'tokyo', 'forecast_written': False, 'new_model_fits': 0}
    with ResearchReader(SimpleNamespace(raw={'limits': {'query_timeout_seconds': 30}})) as reader:
        report['preflight'] = _preflight(reader, {'source_policy': {'source_key': 'analysis-current', 'snapshot_id': 34}})
        rows = reader._small('october_trial:receipt_metadata',
                             "SELECT TOP (2001) operation,race_id,CONVERT(varchar(33),received_at_utc,126) received_at_utc "
                             "FROM api_runtime.write_receipts WHERE race_id LIKE N'202610%' "
                             "AND operation IN(N'race_card',N'odds',N'race_result',N'prediction_record') "
                             "ORDER BY received_at_utc,request_sha256")
        assert len(rows) <= 2000, 'bounded_october_receipt_limit'
        operations = defaultdict(set)
        for row in rows:
            if len(row['race_id']) == 12 and row['race_id'].isdigit() and '01' <= row['race_id'][8:10] <= '10':
                operations[row['operation']].add(row['race_id'])
        report['october_receipts'] = {'rows': len(rows), 'race_counts': {k: len(v) for k, v in operations.items()},
            'card_odds_result_intersection': len(operations['race_card'] & operations['odds'] & operations['race_result']),
            'latest_received_at_utc': max((r['received_at_utc'] for r in rows), default=None),
            'tokyo_counts': {k: sum(i[8:10] == '05' for i in v) for k, v in operations.items()},
            'tomorrow_tokyo_receipt_race_ids': sorted({r['race_id'] for r in rows if r['race_id'].startswith('2026102405')})}
        report['query_metrics'] = reader.query_metrics
    for day in ('2026-10-24', '2026-11-01'):
        try:
            _, parameters, provenance = load_frozen(day)
            report[day] = {'status': 'initialization_passed', 'model': provenance, 'parameters_initialized': True}
        except ResearchError as error:
            report[day] = {'status': 'initialization_rejected', 'reason': error.reason, 'details': error.details}
    path = OUT/'readiness.json'
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('preflight', 'query_metrics')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
