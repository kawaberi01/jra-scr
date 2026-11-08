"""概要: 停止済み前向きrunのID・原本・候補凍結日時を保つ移行を検証する。
作成日: 2026-11-08
入力: tmp_path配下の合成旧protocol・台帳・payload。
出力: pytest結果。
実行例: uv run --frozen --extra ml pytest -q tests/test_jra_shadow_recovery.py
注意事項: 実SQL/HTTP/プロセス起動なし。一時ファイルだけ作成する。
"""

import importlib
import json
from datetime import datetime, timedelta
from pathlib import Path
import pytest


def setup_run(tmp_path, monkeypatch):
    """停止状態だけを持つ合成runと実行モジュールを準備する。"""
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    module = importlib.import_module('run_jra_shadow_series')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    parent = tmp_path / 'artifacts/jra_research'; parent.mkdir(parents=True)
    old, new = parent / 'old', parent / 'new'
    old.mkdir(); new.mkdir()
    recovery = parent / 'shadow_recovery_20261108'; recovery.mkdir()
    module.save(recovery / 'preservation.json', {'old_processes_alive': {'123': False}})
    contract = {'models_sha256': {'S0': 'same'}, 'policies': ['fixed'], 'turf_overlay': {'surface': 'turf'},
                'first_date': '2026-11-08', 'last_date': '2026-11-21'}
    module.save(old / 'protocol.json', contract | {'frozen_at': '2026-11-07T12:00:00+00:00'})
    state = {'status': 'failed', 'errors': [{'reason': 'http'}], 'days': {'2026-11-08': {'status': 'running'}}}
    module.save(old / 'state.json', state)
    day = old / '2026-11-08'; day.mkdir()
    module.save(day / 'state.json', {'records': {'saved-id': {'status': 'saved'}}, 'seen': ['same-token']})
    module.save(day / 'saved-id-payload.json', {'prediction_id': 'saved-id', 'probability': .2})
    module.save(day / 'protocol.json', {'old_source_sha': 'original'})
    (day / 'worker.stdout.log').write_text('old log', encoding='utf-8')
    return module, contract, old, new


def test_migration_preserves_originals_ids_and_freeze(tmp_path, monkeypatch):
    """機械的復旧で候補凍結日時や既存予想IDを新しくしない。"""
    module, contract, old, new = setup_run(tmp_path, monkeypatch)
    before = {str(p): p.read_bytes() for p in old.rglob('*') if p.is_file()}
    state = module.migrate(new, old, contract)
    assert contract['frozen_at'] == '2026-11-07T12:00:00+00:00'
    assert state['days']['2026-11-08']['status'] == 'resume_pending'
    assert module.read(new / '2026-11-08/state.json')['records'] == {'saved-id': {'status': 'saved'}}
    assert (new / '2026-11-08/saved-id-payload.json').read_bytes() == (old / '2026-11-08/saved-id-payload.json').read_bytes()
    assert (new / '2026-11-08/pre-recovery-protocol.json').exists()
    assert (new / '2026-11-08/pre-recovery-worker.stdout.log').exists()
    assert all(Path(name).read_bytes() == value for name, value in before.items())


def test_migration_rejects_changed_model(tmp_path, monkeypatch):
    """モデル変更を単なる復旧として同じ試験へ混ぜない。"""
    module, contract, old, new = setup_run(tmp_path, monkeypatch)
    contract['models_sha256'] = {'S0': 'different'}
    with pytest.raises(Exception, match='series_migration_contract'):
        module.migrate(new, old, contract)


def test_migration_rejects_live_old_process(tmp_path, monkeypatch):
    """旧処理が稼働中なら二重監視を開始できない。"""
    module, contract, old, new = setup_run(tmp_path, monkeypatch)
    file = tmp_path / 'artifacts/jra_research/shadow_recovery_20261108/preservation.json'
    file.write_text(json.dumps({'old_processes_alive': {'123': True}}), encoding='utf-8')
    with pytest.raises(Exception, match='series_migration_old_process_still_running'):
        module.migrate(new, old, contract)


def test_resume_heartbeat_uses_new_child_start(tmp_path, monkeypatch):
    """旧workerの古いheartbeatを引継いでも起動猶予後に新しい更新を要求する。"""
    module, _, _, _ = setup_run(tmp_path, monkeypatch)
    started = '2026-11-08T02:42:17+00:00'
    began = datetime.fromisoformat(started)
    old = '2026-11-08T01:11:51+00:00'
    assert module.heartbeat_recent(old, started, began + timedelta(seconds=1))
    assert not module.heartbeat_recent(old, started, began + timedelta(seconds=601))
    assert module.heartbeat_recent('2026-11-08T02:52:16+00:00', started, began + timedelta(seconds=601))
