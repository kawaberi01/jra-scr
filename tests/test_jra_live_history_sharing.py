"""概要: 当日共通履歴の1回取得・集計・近走同値性と実行間分離を検証する。
作成日: 2026-10-18
入力: pytest、一時DB、モックの当日カードとスカウトservice。
出力: テスト結果。
実行例: uv run pytest -q tests/test_jra_live_history_sharing.py
注意事項: 一時SQLiteは互換性検証専用。実SQL・外部API・保存モデルを変更しない。
"""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

import jra_srb.jra_history_dataset as history
import jra_srb.jra_day_race_scout as scout_module
from jra_srb.jra_history_model import build_artifact_live_records
from jra_srb.jra_recent_form_dataset import RECENT_FORM_SCHEMA, append_recent_form_live_features
from jra_srb.models import RaceCard, Runner
from jra_srb.sqlserver_db import SqlServerConnection, SqlServerStorageError, StorageResult
from jra_srb.sqlserver_schema import ANALYSIS_TABLES


DAY = date(2026, 10, 18)


@pytest.fixture
def history_db(tmp_path):
    """NULL着順・未結合着順・当日/未来・対象外sourceを含む小さい履歴を作る。"""
    path = tmp_path / 'history.sqlite'
    with sqlite3.connect(path) as connection:
        connection.executescript('''
            create table races (race_id text primary key, race_date text, race_name text,
                                surface text, distance text, source text);
            create table runners (race_id text, horse_no text, frame_no text, horse_name text,
                                  sex_age text, weight_carried text, jockey text, trainer text);
            create table result_entries (race_id text, horse_no text, rank integer);
            create table payouts (race_id text);
        ''')
        for race_id, day, source, paid in (
            ('202609270801', '2026-09-27', 'https://www.jra.go.jp/card', True),
            ('202610040801', '2026-10-04', 'https://www.jra.go.jp/card', True),
            ('202610180801', '2026-10-18', 'https://www.jra.go.jp/card', True),
            ('202610190801', '2026-10-19', 'https://www.jra.go.jp/card', True),
            ('202610110801', '2026-10-11', 'https://example.com/', True),
            ('202610120801', '2026-10-12', 'https://www.jra.go.jp/card', False),
        ):
            connection.execute('insert into races values (?,?,?,?,?,?)',
                               (race_id, day, '3歳以上1勝クラス', '芝', '1600', source))
            connection.executemany('insert into runners values (?,?,?,?,?,?,?,?)', [
                (race_id, '1', '1', '馬A', '牡3', '57.0', '騎手A', '厩舎A'),
                (race_id, '2', '1', '馬B', '牝3', '55.0', '騎手B', '厩舎B'),
            ])
            connection.executemany('insert into result_entries values (?,?,?)', [
                (race_id, '1', 1), (race_id, '2', 2),
                (race_id, '3', 3), (race_id, '4', None),
            ])
            if paid:
                connection.executemany('insert into payouts values (?)', [(race_id,), (race_id,)])
    return path


def card(race_no, names=('馬A', '馬B')):
    """最新のレース属性と馬番を持つテスト用カードを返す。"""
    return RaceCard(
        race_id=f'2026101808{race_no:02d}', course='kyoto', race_name='3歳以上1勝クラス',
        surface='芝', distance='1600', start_time='15時00分', source='test', fetched_at=datetime.now(UTC),
        runners=[Runner(horse_no=str(index), frame_no='1', horse_name=name, sex_age='牝3' if index == 2 else '牡3',
                        weight_carried='55.0' if index == 2 else '57.0', jockey='騎手B' if index == 2 else '騎手A',
                        trainer='厩舎B' if index == 2 else '厩舎A', status='active', odds='3.0')
                 for index, name in enumerate(names, 1)],
    )


def artifact():
    """再学習不要な49列モデルを返し、実際の特徴量生成と推論を通す。"""
    return {
        'trained_through': '2026-10-17', 'feature_names': RECENT_FORM_SCHEMA,
        'scaler': {'mean': [0.0]*49, 'scale': [1.0]*49},
        'models': {name: {'intercept': 0.0, 'coefficients': [0.0]*49} for name in ('win', 'top3')},
    }


def test_shared_features_match_legacy_recent_query_and_do_not_mutate_states(history_db, monkeypatch):
    """近走分母・履歴除外を維持し、複数カードとdatasetで取得/集計が各1回になる。"""
    loads, builds = [], []
    load, build = history._load_live_history_rows, history._build_history_states

    def counted_load(*args):
        """共通履歴SELECTの実行回数を記録する。"""
        loads.append(1)
        return load(*args)

    def counted_build(rows):
        """生涯集計の構築回数を記録する。"""
        builds.append(1)
        return build(rows)

    monkeypatch.setattr(history, '_load_live_history_rows', counted_load)
    monkeypatch.setattr(history, '_build_history_states', counted_build)
    context = history.LiveHistoryContext(history_db, target_date=DAY)
    assert loads == builds == []
    first = build_artifact_live_records(artifact(), history_db, target_date=DAY, course='kyoto', card=card(1), history_context=context)
    base = [{**row, 'features': row['features'][:43]} for row in first]
    legacy = append_recent_form_live_features(base, history_db, target_date=DAY)
    assert first == legacy
    assert first[1]['features'][44] == pytest.approx(2/3)  # 2着/結果4頭（結合後は2頭）
    assert all(row['history_starts'] == 2 for row in first)
    snapshot = context.get(history_db, DAY)
    assert {r['race_date'] for r in snapshot.rows} == {'2026-09-27', '2026-10-04'}
    assert all(r['history_field_size'] == 4 for r in snapshot.rows)
    sizes = {name: len(values) for name, values in snapshot.states.items()}
    for number in range(2, 13):
        current = card(number, ('未知馬', '馬B'))
        records = build_artifact_live_records(artifact(), history_db, target_date=DAY, course='kyoto', card=current, history_context=context)
        assert records[0]['history_starts'] == 0
        assert records[1]['features'] == first[1]['features']
    dataset, _ = history.build_history_dataset(history_db, through_date=DAY-timedelta(days=1), history_context=context)
    assert len(dataset) == 4
    assert {name: len(values) for name, values in snapshot.states.items()} == sizes
    assert len(loads) == len(builds) == 1


def test_context_serializes_concurrent_load_and_rejects_other_dates_or_databases(history_db, monkeypatch):
    """並行カードでも1回だけ取得し、別日/別DBへの誤共有を拒否する。"""
    calls = []
    load = history._load_live_history_rows

    def counted(*args):
        """並行利用時のSQL実行数を記録する。"""
        calls.append(1)
        return load(*args)

    monkeypatch.setattr(history, '_load_live_history_rows', counted)
    context = history.LiveHistoryContext(history_db, target_date=DAY)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(context.get, history_db, DAY) for _ in range(8)]
        snapshots = [future.result() for future in futures]
    assert all(s is snapshots[0] for s in snapshots)
    assert len(calls) == 1
    with pytest.raises(ValueError, match='mismatch'):
        context.get(history_db, DAY+timedelta(days=1))
    with pytest.raises(ValueError, match='mismatch'):
        context.get(history_db.with_name('other.sqlite'), DAY)
    with pytest.raises(ValueError, match='cutoff'):
        history.build_history_dataset(history_db, through_date=DAY, history_context=context)


def test_failed_load_is_not_retried_until_new_run(history_db, monkeypatch):
    """共通障害でレースごとにSQLを再実行せず、新runだけが再取得できる。"""
    calls = []

    def fail(*args):
        """読取障害を再現する。"""
        calls.append(1)
        raise OSError('test read failure')

    monkeypatch.setattr(history, '_load_live_history_rows', fail)
    context = history.LiveHistoryContext(history_db, target_date=DAY)
    with pytest.raises(OSError):
        context.get(history_db, DAY)
    with pytest.raises(RuntimeError, match='unavailable'):
        context.get(history_db, DAY)
    assert len(calls) == 1
    with pytest.raises(OSError):
        history.LiveHistoryContext(history_db, target_date=DAY).get(history_db, DAY)
    assert len(calls) == 2


def test_sql_history_hint_is_opt_in_and_derived_result_count_is_compiled(monkeypatch, tmp_path):
    """対象reader SELECTだけのhintと、結合前の頭数集計のSQL変換を検証する。"""
    statements = []
    connection = SqlServerConnection.__new__(SqlServerConnection)
    connection.tables = ANALYSIS_TABLES
    connection.read_only = True
    connection._raw = lambda sql, params=(): statements.append((sql, params)) or StorageResult()
    connection.close = lambda: None
    connection.execute('select race_id from races')
    assert 'OPTION (HASH JOIN)' not in statements[-1][0]
    monkeypatch.setattr(history, 'storage_backend', lambda: 'sqlserver')
    monkeypatch.setattr(history, 'open_analysis_read', lambda path: connection)
    context = history.LiveHistoryContext(tmp_path / 'unused', target_date=DAY)
    context.get(tmp_path / 'unused', DAY)
    sql, params = statements[-1]
    assert sql.endswith('OPTION (HASH JOIN)')
    assert 'COUNT_BIG(*) OVER (PARTITION BY [race_id])' in sql
    assert params == ['2026-10-18']
    connection.read_only = False
    with pytest.raises(SqlServerStorageError, match='reader SELECT'):
        connection.execute('select race_id from races', hash_join=True)
    connection.read_only = True
    with pytest.raises(SqlServerStorageError, match='reader SELECT'):
        connection.execute('delete from races', hash_join=True)


@pytest.mark.parametrize('local', [False, True])
def test_scout_shares_history_across_races_and_discards_it_between_runs(history_db, monkeypatch, local):
    """APIの外部/保存カード経路で履歴はrunごとに1回、カードは各レースで取得する。"""
    cards = [card(number) for number in range(1, 13)]
    races = [SimpleNamespace(race_id=c.race_id, race_no=index, race_name=c.race_name,
                             start_time=c.start_time, course='kyoto') for index, c in enumerate(cards, 1)]
    calls, fetched, saved = [], [], []
    load = history._load_live_history_rows

    def counted(*args):
        """実際の履歴取得を数える。"""
        calls.append(1)
        return load(*args)

    async def meetings(day):
        """外部経路の開催一覧を返す。"""
        return [SimpleNamespace(course='kyoto', meeting_no=4, meeting_day=7, races=races)]

    async def get_card(day, course, race_no, **kwargs):
        """カードは毎レースの既存取得経路を通したことを記録する。"""
        fetched.append(race_no)
        return cards[race_no-1]

    def snapshot(race_id):
        """保存済みカードを個別に返す。"""
        index = next(i for i, r in enumerate(races) if r.race_id == race_id)
        fetched.append(index+1)
        return SimpleNamespace(race=races[index], card=cards[index])

    monkeypatch.setattr(history, '_load_live_history_rows', counted)
    monkeypatch.setattr(scout_module, '_has_started', lambda *args: False)
    monkeypatch.setattr(scout_module, 'load_model_artifact', lambda path: artifact())
    monkeypatch.setattr(scout_module, 'build_win_betting_decision', lambda *args: {'status': 'not_recommended', 'reason': 'test'})
    monkeypatch.setattr(scout_module, '_race_card_from_snapshot', lambda s: s.card)
    monkeypatch.setattr(scout_module, '_race_odds_from_snapshot', lambda s: object())
    store = SimpleNamespace(
        list_pre_race_race_ids=lambda day: [r.race_id for r in races] if local else [],
        get_pre_race_snapshot=snapshot, save_jra_scout_result=lambda result, **kwargs: saved.append(result),
    )
    scout = scout_module.JraDayRaceScout(
        jra_service=SimpleNamespace(get_meetings_for_date=meetings, get_race_card_by_number=get_card),
        prediction_service=object(), store=store, analysis_db_path=history_db, history_model_path='unused',
    )
    for run in range(2):
        result = asyncio.run(scout.run(DAY))
        assert result.status == 'completed'
        assert result.analyzed_count == 12
        assert len(calls) == run+1
        assert len(fetched) == (run+1)*12
    assert len(saved) == 2


def test_catboost_cli_reuses_live_context_for_history_dataset(history_db, monkeypatch, tmp_path):
    """CatBoostの複数カードと後段dataset生成で履歴SELECTを再実行しない。"""
    import importlib.util
    import json
    import sys
    import httpx

    spec = importlib.util.spec_from_file_location('shared_catboost_scout', Path(__file__).parents[1] / 'scripts/scout_jra_catboost_day.py')
    scout = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scout)
    target = date.today()+timedelta(days=1)
    cards = [card(n).model_copy(update={'race_id': f'{target:%Y%m%d}08{n:02d}'}) for n in (1, 2)]
    by_id = {c.race_id: c for c in cards}
    schedule = [{'race_id': c.race_id, 'course': 'kyoto', 'race_no': n,
                 'race_name': c.race_name, 'start_time': c.start_time} for n, c in enumerate(cards, 1)]
    loads = []
    load = history._load_live_history_rows

    def counted(*args):
        """実際の履歴取得を数える。"""
        loads.append(1)
        return load(*args)

    def get(path, **kwargs):
        """開催一覧だけを返し、外部のカード取得は許可しない。"""
        assert path == '/search/races'
        return httpx.Response(200, json={'items': schedule}, request=httpx.Request('GET', 'http://test/search/races'))

    def append_style(records, db):
        """対象外のラップ読取を分離し、当日の65列への拡張を再現する。"""
        return [{**r, 'features': [*r['features'], *([0.0]*16)]} for r in records], {}

    monkeypatch.setattr(history, '_load_live_history_rows', counted)
    monkeypatch.setattr(scout.httpx, 'Client', lambda **kwargs: SimpleNamespace(get=get, close=lambda: None))
    monkeypatch.setattr(scout, 'build_analysis_store', lambda db: SimpleNamespace(list_pre_race_race_ids=lambda day: []))
    monkeypatch.setattr(scout, 'cached_card', lambda rid, *args: by_id[rid])
    monkeypatch.setattr(scout, 'load_model_artifact', lambda path: artifact())
    monkeypatch.setattr(scout, 'load_ranker', lambda path: SimpleNamespace(predict=lambda rows: list(range(len(rows)))))
    monkeypatch.setattr(scout, 'append_lap_style_features', append_style)
    monkeypatch.setattr(sys, 'argv', ['scout', '--date', target.isoformat(), '--db', str(history_db),
                                    '--ranker-model', 'unused', '--output-dir', str(tmp_path / 'output')])
    scout.main()
    result = json.loads(next((tmp_path / 'output').glob('day_scout_*.json')).read_text(encoding='utf-8'))
    assert result['analyzed_count'] == 2
    assert len(loads) == 1
