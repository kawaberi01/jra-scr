"""概要: spec241の30仮説を、前日までの履歴と同時点市場から構築する。
作成日: 2026-10-22
入力: 固定版SQLのRA/SE、T30馬連/単勝、公表HR、既存入力監査。
出力: メモリ内の7894競走の特徴と集計来歴。原文・全特徴は保存しない。
実行例: uv run --frozen --extra ml python scripts/run_jra_chimera_thirty.py
注意事項: SQL読取のみ。同日結果は全予測生成後に反映する。
"""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import date
from itertools import combinations
import gc
import hashlib
import json

import numpy as np

from . import jra_research_chimera_twenty_fit as previous
from . import jra_research_chimera_twenty as inputs
from .jra_research_artifacts import ROOT
from .jra_research_history import HistoryConfig
from .jra_research_r1_live import LiveAnnualReader, read_json, require
from .jra_research_resources import check_memory

old = previous.old
LIMIT = 2**31
RECORD_ROOT = ROOT / '.workstate/jra-srb/sqlserver-model-data-audit'
AUDIT = RECORD_ROOT / 'diagnostics/20261021-thirty-market-contract-v3.json'
# 追加列の開始位置・幅。J01の12馬特徴に、指定ケースの列だけを足す。
WIDTHS = {2: 1, 3: 1, 4: 1, 5: 3, 6: 3, 7: 2, 8: 2, 9: 3,
          10: 3, 11: 2, 12: 2, 13: 2, 14: 2, 15: 2, 16: 2,
          17: 2, 18: 3, 19: 2, 20: 2, 21: 2, 22: 2}
SLICES = {}
_column = 0
for _case, _width in WIDTHS.items():
    SLICES[_case] = slice(_column, _column + _width)
    _column += _width


def mean(values):
    """空集合を0とする有限値の平均を返す。"""
    return float(np.mean(values)) if len(values) else 0.0


def pl_pairs(win):
    """単勝確率から順序を周辺化したPL馬連確率を返す。"""
    win = np.asarray(win, dtype=float)
    win = win / win.sum()
    require(np.all(win > 0) and np.all(win < 1), 'thirty_invalid_win')
    left, right = old.pairs(len(win)).T
    result = win[left] * win[right] * (1 / (1 - win[left]) + 1 / (1 - win[right]))
    return result / result.sum()


def marginal(market, n):
    """馬連確率の周辺化で、合計2となる各馬の2着内確率を返す。"""
    pair = old.pairs(n)
    return np.bincount(pair.ravel(), weights=np.repeat(market, 2), minlength=n)


def historical_small(key, source):
    """正常な2〜7頭競走だけを、評価集合へ加えず履歴用に解析する。"""
    if source['RA'] is None or source['conflict'] or not 2 <= len(source['SE']) < 8:
        return None
    ra = source['RA'][2]
    track = old.native.number(ra[705:707])
    if not 10 <= track <= 29 or not '01' <= key[8:10] <= '10':
        return None
    runners = []
    for _, _, se in source['SE'].values():
        identity = se[30:40].decode('ascii')
        if se[331:332] != b'0' or not identity.isdigit() or int(identity) == 0:
            return None
        corner = next((old.native.number(se[o:o+2]) for o in (357, 355, 353, 351)
                       if old.native.number(se[o:o+2]) > 0), None)
        runners.append({'horse_no': f'{old.native.number(se[28:30]):02d}',
                        'horse_id': identity, 'rank': old.native.number(se[334:336]),
                        'corner': corner, 'closing': None, 'age': old.native.number(se[82:84]),
                        'frame': old.native.number(se[27:28]), 'weight': old.native.number(se[288:291])/10,
                        'jockey': se[296:301].decode('ascii'), 'trainer': ''})
    if sorted(r['rank'] for r in runners) != list(range(1, len(runners)+1)):
        return None
    if len({r['horse_id'] for r in runners}) != len(runners):
        return None
    day = f'{key[:4]}-{key[4:6]}-{key[6:8]}'
    return {'key': key, 'day': day, 'ordinal': date.fromisoformat(day).toordinal(),
            'surface': int(track >= 23), 'distance': old.native.number(ra[697:701]),
            'course': int(key[8:10]), 'condition': ra[634:637].decode('ascii'),
            'pace': None, 'late': None, 'runners': sorted(runners, key=lambda r: r['horse_no'])}


class PastRun:
    """過去5走の固定項目をslotsへ保存し、辞書の重複メモリを避ける。"""

    __slots__ = ('day', 'clock', 'class_clock', 'opponent', 'surprise', 'expectation',
                 'age', 'corner', 'weight', 'distance', 'surface', 'condition',
                 'jockey', 'trainer_code', 'speed_ratio')

    def __init__(self, values):
        """事前定義した過去走項目だけを格納する。"""
        for key in self.__slots__:
            setattr(self, key, values[key])

    def __getitem__(self, key):
        """固定項目を名前で参照し、未定義項目は拒否する。"""
        return getattr(self, key)


class MechanismStates:
    """追加の条件別集計と、馬ごとの直近5走だけを保持する。"""

    def __init__(self):
        """正常・異常・小頭数を区別した空の履歴を用意する。"""
        self.last = {}
        self.abnormal = {}
        self.small = {}
        self.class_clocks = {}
        self.bias = {}
        self.actors = {}
        self.growth = {}

    def public(self, race, states, public):
        """現在の結果を読まず、J02〜J22の追加馬特徴を作る。"""
        ratings = public['x'][:, 3]
        top = mean(sorted(ratings)[-3:])
        styles = []
        for runner in race['runners']:
            past = self.last.get(runner['horse_id'], ())
            styles.append(past[-1]['corner'] if past else .5)
        density = mean([s <= .3 for s in styles])
        result = []
        for i, runner in enumerate(race['runners']):
            h = self.last.get(runner['horse_id'], ())
            require(all(p['day'] < race['ordinal'] for p in h), 'thirty_same_day_history')
            last = h[-1] if h else None
            before = h[-2] if len(h) > 1 else None
            clock = public['x'][i, 0]
            speeds = [p['clock'] for p in h]
            surprises = [p['surprise'] for p in h if p['surprise'] is not None]
            out = np.zeros(_column)
            out[SLICES[2]] = mean([p['class_clock'] for p in h])
            out[SLICES[3]] = self.bias.get((race['course'], race['surface']), 0) * clock
            out[SLICES[4]] = mean([p['opponent'] for p in h])
            variance = float(np.var(speeds, ddof=1)) if len(speeds) > 1 else 0
            stderr = np.sqrt((variance + 1) / (len(speeds) + 1))
            out[SLICES[5]] = [variance, stderr, clock / (1 + stderr)]
            change = (last['clock'] - before['clock']) / max(1, last['age'] - before['age']) if before else 0
            gn, gs = self.growth.get((runner['age'], race['surface']), (0, 0))
            out[SLICES[6]] = [change, change * runner['age']/10, (gs + 10*change)/(gn+10)]
            surprise = mean(surprises)
            out[SLICES[7]] = [surprise, np.log1p(len(surprises))/5]
            out[SLICES[8]] = [mean([p['surprise']*p['clock'] for p in h if p['surprise'] is not None]), surprise*clock]
            an, ad = self.abnormal.get(runner['horse_id'], (0, 0))
            out[SLICES[9]] = [np.log1p(an)/5, min((race['ordinal']-ad)/365, 2) if an else 2,
                              int(bool(an and (not last or ad > last['day'])))]
            sn, ss = self.small.get(runner['horse_id'], (0, 0))
            out[SLICES[10]] = [ss/(sn+10), np.log1p(sn)/5, ss/sn-clock if sn else 0]
            dm = last['expectation']-before['expectation'] if before and last['expectation'] is not None and before['expectation'] is not None else 0
            dc = last['clock']-before['clock'] if before else 0
            out[SLICES[11]] = [dm-dc, dm*dc]
            for case, kind in ((12, 'jockey'), (13, 'trainer_code')):
                changed = int(bool(before and last[kind] != before[kind]))
                count, total = self.actors.get((runner['horse_id'], kind, last[kind]), (0, 0)) if last else (0, 0)
                out[SLICES[case]] = [changed, total/(count+10)*clock]
            out[SLICES[14]] = [mean([p['weight']/60*p['distance']/2000*p['clock'] for p in h]),
                                   runner['weight']/60*race['distance']/2000*clock]
            second = int(bool(before and last['day']-before['day'] >= 90 and race['ordinal']-last['day'] <= 60))
            out[SLICES[15]] = [second, second*clock]
            returned = int(bool(before and last['surface'] != before['surface'] and race['surface'] == before['surface']))
            out[SLICES[16]] = [returned, returned*before['clock'] if before else 0]
            returned_d = int(bool(before and abs(last['distance']-before['distance']) >= 400
                                  and abs(race['distance']-before['distance']) <= 200))
            out[SLICES[17]] = [returned_d, returned_d*before['clock'] if before else 0]
            moved = int(bool(before and last['condition'] != before['condition']))
            out[SLICES[18]] = [moved, moved*clock, moved*surprise]
            out[SLICES[19]] = [float(np.std(ratings))*ratings[i], top-ratings[i]]
            style_var = float(np.var([p['corner'] for p in h])) if h else 0
            out[SLICES[20]] = [style_var, style_var*density]
            ratio = mean([p['speed_ratio'] for p in h if p['speed_ratio'] is not None])
            out[SLICES[21]] = [ratio, ratio*clock]
            position = runner['frame']/8*styles[i]*len(ratings)/18*race['distance']/2000
            out[SLICES[22]] = [position, position*clock]
            result.append(np.clip(out, -5, 5))
        return np.asarray(result, dtype=np.float32), np.asarray(styles, dtype=np.float32), density

    def update_day(self, updates, states):
        """同日全競走の更新値を事前計算してから、追加履歴へ反映する。

        Args:
            updates: (競走, 秒, 馬場, normal/small/abnormal, 市場情報)の同日リスト。
            states: 当日結果をまだ反映していない既存時計状態。
        Notes:
            異常走は時計や敗北を代入せず、存在情報のみを保存する。
        """
        events, class_events, bias_events, growth_events, actor_events, small_events, abnormal_events = [], [], [], [], [], [], []
        for race, seconds, going, kind, market in updates:
            if kind == 'abnormal':
                abnormal_events.extend((r['horse_id'], race['ordinal']) for r in race['runners'])
                continue
            generic = (race['surface'], race['distance'])
            detailed = (*generic, race['course'], going)
            gn, gs = states.clocks.get(generic, (0, 0))
            dn, ds = states.clocks.get(detailed, (0, 0))
            baseline = (ds + 30*(gs/gn if gn else 16.5))/(dn+30)
            group = (*generic, race['grade'], race['condition'])
            cn, cs = self.class_clocks.get(group, (0, 0))
            classbase = (cs + 10*baseline)/(cn+10)
            ratings = [states.horses[r['horse_id']].rating if r['horse_id'] in states.horses else 0 for r in race['runners']]
            expected = marginal(market['market'], len(ratings)) if market is not None else None
            residuals = []
            for i, runner in enumerate(race['runners']):
                speed = race['distance']/seconds[runner['horse_no']]
                clock = (speed-baseline)/2
                if kind == 'small':
                    small_events.append((runner['horse_id'], clock*(len(ratings)-1)/len(ratings)))
                    continue
                prior_horse = states.horses.get(runner['horse_id'])
                expected_clock = mean([p[1] for p in prior_horse.last]) if prior_horse else 0
                residuals.append(clock-expected_clock)
                if runner['rank'] == 1:
                    class_events.append((group, speed))
                rank = (len(ratings)-runner['rank']+.5)/len(ratings)
                opponent = mean(sorted(ratings[:i]+ratings[i+1:])[-3:]) + .5*np.log(rank/(1-rank))
                surprise = float(int(runner['rank'] <= 2)-expected[i]) if expected is not None else None
                prior = self.last.get(runner['horse_id'], ())
                ratio = (600/runner['closing'])/speed-1 if runner['closing'] else None
                event = {'day': race['ordinal'], 'clock': clock, 'class_clock': (speed-classbase)/2,
                         'opponent': opponent, 'surprise': surprise,
                         'expectation': float(expected[i]) if expected is not None else None,
                         'age': runner['age'], 'corner': runner['corner']/len(ratings) if runner['corner'] else .5,
                         'weight': runner['weight'], 'distance': race['distance'], 'surface': race['surface'],
                         'condition': race['condition'], 'jockey': runner['jockey'],
                         'trainer_code': runner['trainer_code'], 'speed_ratio': ratio}
                events.append((runner['horse_id'], PastRun(event)))
                if prior:
                    growth_events.append(((runner['age'], race['surface']), (clock-prior[-1]['clock'])/max(1, runner['age']-prior[-1]['age'])))
                if surprise is not None:
                    for actor in ('jockey', 'trainer_code'):
                        actor_events.append(((runner['horse_id'], actor, runner[actor]), surprise))
            if residuals:
                bias_events.append(((race['course'], race['surface']), mean(residuals)))
        for identity, event in events:
            self.last.setdefault(identity, deque(maxlen=5)).append(event)
        for target, values in ((self.class_clocks, class_events), (self.growth, growth_events),
                               (self.actors, actor_events), (self.small, small_events)):
            for key, value in values:
                count, total = target.get(key, (0, 0))
                target[key] = count+1, total+float(value)
        # 同日競走の順序を変えても同一になるよう、日内平均を一度だけ反映する。
        grouped = defaultdict(list)
        for key, value in bias_events:
            grouped[key].append(value)
        for key, values in grouped.items():
            self.bias[key] = .95*self.bias.get(key, 0)+.05*mean(values)
        for identity, day in abnormal_events:
            count, _ = self.abnormal.get(identity, (0, 0))
            self.abnormal[identity] = count+1, day


def load_markets(races, config):
    """監査済み対象の価格・払戻だけを一度読み、時点と馬集合を再検査する。"""
    output = {}
    keys = sorted(races)
    with inputs.prior.ExperimentMarketReader(config) as reader:
        reader.selected(['2025-11-01'])
        for begin in range(0, len(keys), 100):
            batch = keys[begin:begin+100]
            rows = inputs.indexed_rows(reader, batch, 'market.odds_asof_index', old.base.FIELDS['market.odds_asof_index'],
                                       "AND t.market IN(N'quinella',N'win') AND t.horizon=N'T30'")
            hr = inputs.indexed_rows(reader, batch, 'history.payouts', old.base.FIELDS['history.payouts'],
                                     "AND t.market=N'quinella' AND t.slot_status=N'published'")
            grouped, payouts = defaultdict(list), defaultdict(list)
            for row in rows:
                grouped[row['race_key']].append(row)
            for row in hr:
                payouts[row['race_key']].append(row)
            for key in batch:
                q = [r for r in grouped[key] if r['market'] == 'quinella']
                w = [r for r in grouped[key] if r['market'] == 'win']
                prices = inputs.validate_inputs(races[key], q, payouts[key])
                require(len(w) == 1 and w[0]['selection_status'] == 'selected'
                        and w[0]['parser_version'] == 'jv-o1o2-v2' and bool(w[0]['content_sha256'])
                        and inputs.timestamp(w[0]['announced_at']) <= inputs.timestamp(w[0]['cutoff_at'])
                        and inputs.timestamp(w[0]['cutoff_at']) == inputs.timestamp(q[0]['cutoff_at']), 'thirty_win_identity')
                win = inputs.numeric_market(w[0], 'win')
                horse_numbers = [r['horse_no'] for r in races[key]['runners']]
                require(set(win) == set(horse_numbers), 'thirty_win_roster')
                expected_keys = list(combinations(horse_numbers, 2))
                quoted = np.asarray([prices[pair] for pair in expected_keys], dtype=float)
                market = 1/quoted
                market /= market.sum()
                wp = np.asarray([1/win[no] for no in horse_numbers])
                output[key] = {'market': market, 'prices': quoted, 'pl': pl_pairs(wp),
                               'payout_yen': int(payouts[key][0]['payout_yen']),
                               'market_sha256': q[0]['content_sha256'], 'win_sha256': w[0]['content_sha256'],
                               'hr_sha256': payouts[key][0]['hr_sha256']}
            print(json.dumps({'stage': 'market', 'races': len(output), 'expected': len(keys)}), flush=True)
    return output


def prepare(folder):
    """監査対象と照合しつつ全履歴を一巡し、新規研究の前日特徴を生成する。

    Args:
        folder: 集計coverageだけを保存する研究runディレクトリ。
    Returns:
        list: 価格と前日特徴を含む7894競走。原文を返さない。
    Raises:
        ResearchError: 年別digest、入力集合、時計、メモリ上限の不整合。
    """
    audit = read_json(AUDIT)
    expected = {r['race_key'] for r in audit['race_inputs'] if r['quinella_hr_valid'] and r['win_same_time_valid']}
    require(len(expected) == 7894, 'thirty_audit_cohort')
    config = HistoryConfig.load(ROOT/'configs/research/history_sql_v1.json')
    # 市場読取用の正常対象だけを先に3年抽出する。特徴原文の永続キャッシュは作らない。
    races = {}
    with LiveAnnualReader(config) as reader:
        reader.preflight()
        for year in (2024, 2025, 2026):
            raw, _ = reader.year_before(year, '2026-10-18')
            for key in sorted(expected.intersection(raw)):
                race, reason = old.native.parse_race(key, raw[key])
                require(reason is None, 'thirty_cohort_parse')
                races[key] = race
            del raw
            gc.collect()
    require(set(races) == expected, 'thirty_cohort_changed')
    prices = load_markets(races, config)
    del races
    states, mechanisms, records = previous.TwentyStates(), MechanismStates(), []
    historical_audit = read_json(old.AUDIT/'audit.json')
    years = {}
    with LiveAnnualReader(config) as reader:
        reader.preflight()
        for year in range(2003, 2027):
            raw, report = reader.year_before(year, '2026-10-18')
            require(report['input_digest'] == historical_audit['annual'][str(year)]['source_audit']['input_digest'], 'thirty_annual_changed')
            daily = defaultdict(list)
            counts = defaultdict(int)
            for key, source in sorted(raw.items()):
                if key[:8] > '20260930':
                    continue
                race, reason = old.native.parse_race(key, source)
                kind = 'normal'
                if reason is not None:
                    race = historical_small(key, source)
                    kind = 'small'
                if race is None:
                    # 異常走は該当馬だけをマーカー化し、正常走と混ぜない。
                    if source['RA'] is None or source['conflict'] or not '01' <= key[8:10] <= '10':
                        continue
                    ra = source['RA'][2]
                    track = old.native.number(ra[705:707])
                    if not 10 <= track <= 29:
                        continue
                    abnormal = []
                    for _, _, se in source['SE'].values():
                        hid = se[30:40].decode('ascii')
                        if se[331:332] in b'123456789' and hid.isdigit() and int(hid):
                            abnormal.append({'horse_id': hid})
                    if abnormal:
                        day = f'{key[:4]}-{key[4:6]}-{key[6:8]}'
                        daily[day].append(({'ordinal': date.fromisoformat(day).toordinal(), 'runners': abnormal}, {}, 0, 'abnormal', None))
                    continue
                ra = source['RA'][2]
                race['grade'] = ra[614:615].decode('ascii')
                for runner in race['runners']:
                    runner['trainer_code'] = source['SE'][runner['horse_no']][2][85:90].decode('ascii')
                    require(runner['trainer_code'].isdigit(), 'thirty_trainer_code')
                seconds = {r['horse_no']: old.clock_seconds(source['SE'][r['horse_no']][2][338:342]) for r in race['runners']}
                going = old.native.number(ra[888:889] if race['surface'] == 0 else ra[889:890])
                require(going in (1, 2, 3, 4), 'thirty_going')
                laps = [old.native.number(ra[890+i*3:893+i*3])/10 for i in range(25)]
                laps = [v for v in laps if v > 0]
                race['closing_total'] = sum(laps[-3:]) if race['pace'] is not None else None
                daily[race['day']].append((race, seconds, going, kind, prices.get(key)))
                counts[kind] += 1
            for day, updates in sorted(daily.items()):
                for race, _, _, kind, market in updates:
                    if kind != 'normal' or race['key'] not in expected:
                        continue
                    public = states.public(race)
                    addition, style, density = mechanisms.public(race, states, public)
                    x = np.column_stack((public['x'], public['extra'][:, 20:23])).astype(np.float32)
                    runners = race['runners']
                    winners = {i for i, r in enumerate(runners) if r['rank'] <= 2}
                    winner = next(i for i, pair in enumerate(old.pairs(len(runners))) if set(pair) == winners)
                    records.append({'race_key': race['key'], 'race_date': day, 'x': x, 'addition': addition,
                                    'basic': states.legacy_features(race)[:, old.residual.BASIC].astype(np.float32),
                                    'styles': style, 'density': density, 'winner': winner,
                                    'group': race['surface']*2+int(race['distance'] >= 2000), **market})
                mechanisms.update_day(updates, states)
                states.update_day([(r, s, g) for r, s, g, kind, _ in updates if kind == 'normal'])
            years[str(year)] = {'input_digest': report['input_digest'], 'counts': dict(counts)}
            (folder/'coverage.json').write_text(json.dumps({'years': years, 'records': len(records)}, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'stage': 'features', 'year': year, 'records': len(records), 'memory': check_memory(LIMIT)}), flush=True)
            del raw, daily
            gc.collect()
    require({r['race_key'] for r in records} == expected, 'thirty_feature_cohort')
    records.sort(key=lambda r: (r['race_date'], r['race_key']))
    return records
