"""概要: 通常SQL readerで共有履歴の全行digest・取得回数・再利用時間を検証する。
作成日: 2026-10-18
入力: --output、既存runtime設定、10/18秋華賞の保存済み発走前カード。
出力: 秘密を含まない新規検証JSONと標準出力。
実行例: uv run --extra ml python .workstate/jra-srb/live-history-sharing/verify_live_sql.py --output artifacts/diagnostics/live-history-sharing-20261018.json
注意事項: 通常readerだけを使用し、SQL更新・外部取得・予想保存なし。
    SQLite/旧JSONL読取をguardで拒否する。診断プロセスは45秒で終了する。
"""

from datetime import date, datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import threading
import time

import jra_srb.jra_history_dataset as history
from jra_srb.jra_history_model import build_artifact_live_records, load_model_artifact
from jra_srb.jra_research_tipster_smoke import install_input_guard
from jra_srb.models import RaceCard
from jra_srb.storage_config import storage_backend


def main():
    """1回のSQL取得後にカード36回分の特徴を作り、元履歴のdigestと照合する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    install_input_guard()
    assert storage_backend() == 'sqlserver'
    day = date(2026, 10, 18)
    report = {'started_at': datetime.now(timezone.utc).isoformat(), 'sql_history_selects': 0,
              'history_aggregations': 0, 'connection_closed': False, 'sqlite_used': False}

    def persist():
        """この診断だけが所有する出力へ最新の検証結果を保存する。"""
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

    def expire():
        """時間上限を超えたらこの検証プロセスだけを終了する。"""
        report['status'] = 'wall_timeout'
        persist()
        os._exit(124)

    watchdog = threading.Timer(45, expire)
    watchdog.daemon = True
    watchdog.start()
    open_read = history.open_analysis_read
    aggregate = history._build_history_states

    def counted_open(path):
        """通常readerのidentityと履歴SELECT回数・接続終了を検査する。"""
        connection = open_read(path)
        identity = connection._raw("SELECT ORIGINAL_LOGIN() login_name,IS_SRVROLEMEMBER('sysadmin') sysadmin,IS_ROLEMEMBER('db_owner') db_owner").fetchone()
        assert identity[1] == identity[2] == 0
        report['reader_identity'] = dict(identity)
        execute, close = connection.execute, connection.close

        def counted_execute(*values, **options):
            """履歴SELECTを数え、明示HASH JOINが指定されていることを確認する。"""
            report['sql_history_selects'] += 1
            assert options == {'hash_join': True}
            return execute(*values, **options)

        def counted_close():
            """SQL接続を閉じたことを記録する。"""
            close()
            report['connection_closed'] = True

        connection.execute = counted_execute
        connection.close = counted_close
        return connection

    def counted_aggregate(rows):
        """生涯集計が1回だけ構築されることを記録する。"""
        report['history_aggregations'] += 1
        return aggregate(rows)

    history.open_analysis_read = counted_open
    history._build_history_states = counted_aggregate
    try:
        source = Path('artifacts/jra_research/runs/20261017T162905Z_331cf5bcd0db4e2f97e9e15d650fa24d/metrics.json')
        saved = json.loads(source.read_text(encoding='utf-8'))
        card = RaceCard.model_validate(saved['pre_race_snapshot']['card'])
        model = load_model_artifact('data/models/jra_history_recent_form_v2/model.json')
        assert model['trained_through'] < day.isoformat()
        db = Path('data/db/analysis.sqlite')
        context = history.LiveHistoryContext(db, target_date=day)
        begin = time.perf_counter()
        first = build_artifact_live_records(model, db, target_date=day, course='kyoto', card=card, history_context=context)
        report['first_features_seconds'] = time.perf_counter()-begin
        snapshot = context.get(db, day)
        report['history_rows'] = len(snapshot.rows)
        columns = ('race_id','race_date','race_name','surface','distance','horse_no','frame_no',
                   'horse_name','sex_age','weight_carried','jockey','trainer','rank')
        hashes = sorted(hashlib.sha256(json.dumps([row[k] for k in columns], ensure_ascii=False, default=str).encode('utf-8')).hexdigest()
                        for row in snapshot.rows)
        report['legacy_multiset_sha256'] = hashlib.sha256('\n'.join(hashes).encode()).hexdigest()
        report['matches_prechange_sql_rows'] = report['legacy_multiset_sha256'] == 'a01cec6fde06c1c8acbcf74d99793e74956d143e48f893d192bdb8fab2a297e2'
        assert report['matches_prechange_sql_rows']
        assert all(row['race_date'] < day.isoformat() for row in snapshot.rows)
        before = report['sql_history_selects']
        begin = time.perf_counter()
        for _ in range(35):
            current = build_artifact_live_records(model, db, target_date=day, course='kyoto', card=card, history_context=context)
            assert current == first
        report['reuse_35_cards_seconds'] = time.perf_counter()-begin
        assert before == report['sql_history_selects'] == 1
        assert report['history_aggregations'] == 1 and report['connection_closed']
        report.update(status='passed', feature_count=len(first[0]['features']), runner_count=len(first),
                      scope='saved_card_feature_equivalence_and_shared_history_only_not_full_day_scout')
    except Exception as error:
        report.update(status='failed', error_type=type(error).__name__)
    finally:
        watchdog.cancel()
        history.open_analysis_read = open_read
        history._build_history_states = aggregate
        persist()
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(0 if report['status'] == 'passed' else 1)


if __name__ == '__main__':
    main()
