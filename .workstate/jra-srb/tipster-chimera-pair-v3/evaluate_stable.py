"""概要：特徴量の観測期間を揃え、欠測時の市場回帰と買い方の10案を比較する。
作成日：2026-10-02
入力：protocol.json、既存JSONLと読み取り専用DB、v2のコードと保存買い目。
出力：このディレクトリのモデル・予測・買い目・会計・比較・検証記録。
実行例：uv run python .workstate/jra-srb/tipster-chimera-pair-v3/evaluate_stable.py
注意事項：外部通信・依存追加なし。元入力・既存成果物・取得処理は変更しない。
"""
from __future__ import annotations

from collections import defaultdict
from itertools import permutations
from pathlib import Path
import ast
import importlib.util
import json
import sys
import joblib
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import logit, softmax
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT = Path(__file__).resolve().parent
OLD = OUT.parent/'tipster-chimera-pair-v2'
spec = importlib.util.spec_from_file_location('pair_v2',OLD/'evaluate_pairs.py')
v2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v2)
CONTRACT = json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
H = len(v2.previous.HISTORY_KEYS)
CONTENT_START = 7+2*H


def save(name, value):
    """研究用JSONを新しい出力ディレクトリへUTF-8で保存する。"""
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def period(day):
    """実行前に固定した日付区間を返す。"""
    if int(day[5:7]) in [6,7,8]:
        return None
    if '2024-01-01' <= day <= '2025-09-30':
        return 'train'
    if '2025-10-01' <= day <= '2025-10-31':
        return 'calibration'
    if '2025-11-01' <= day <= '2025-12-31':
        return 'development'
    if '2026-01-01' <= day <= '2026-02-28':
        return 'confirmation_early'
    if '2026-03-01' <= day <= '2026-05-31':
        return 'confirmation_late'
    return None


def fit_q(train,calibration,feature):
    """市場を基準に馬連モデルを学習し、後の日付の校正損失で補正を縮小する。"""
    model = v2.fit_choice(train,feature=feature,penalty=.1)
    deltas = [(r[feature]/model['scale'])@model['coef'] for r in calibration]
    def loss(alpha):
        """校正期間のレース平均対数損失を返す。"""
        return float(np.mean([-r['target']@np.log(np.maximum(softmax(np.log(r['market'])+alpha*d),1e-15)) for r,d in zip(calibration,deltas,strict=True)]))
    alpha = float(minimize_scalar(loss,bounds=(0,1),method='bounded').x)
    return dict(model=model,alpha=alpha)


def stable_content(train,calibration,name,all_records):
    """正解を見ず、両時期で30%以上観測される内容列を選択して補完する。

    Args:
        train: そのモデルの学習レース。
        calibration: 学習より後の校正レース。
        name: 保存する特徴行列の識別名。
        all_records: 同じ変換を適用するレース。
    Returns:
        学習期だけで適合した補完器と列番号・利用可能性の記録。
    Notes:
        評価期間の欠測率や結果を列選択に使用しない。
    """
    x = np.concatenate([r['full_x'] for r in train])
    c = np.concatenate([r['full_x'] for r in calibration])
    train_observed = np.isfinite(x).mean(axis=0)
    calibration_observed = np.isfinite(c).mean(axis=0)
    keep = np.flatnonzero((train_observed>=.3)&(calibration_observed>=.3))
    assert set(range(CONTENT_START)).issubset(set(keep))
    imputer = SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True)
    imputer.fit(x[:,keep])
    for r in all_records:
        r[name] = imputer.transform(r['full_x'][:,keep])
    return dict(imputer=imputer,keep=keep,train_observed=train_observed,calibration_observed=calibration_observed)


def fit_w(train,calibration,feature):
    """ペアのワイド的中をレース均等重みで学習し、同じ重みで確率校正する。"""
    x = np.concatenate([r[feature] for r in train])
    y = np.concatenate([r['wide_target'] for r in train])
    weights = np.concatenate([np.full(len(r['keys']),1/len(r['keys'])) for r in train])
    model = make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=1000))
    model.fit(x,y,logisticregression__sample_weight=weights/weights.mean())
    p = np.concatenate([model.predict_proba(r[feature])[:,1] for r in calibration])
    labels = np.concatenate([r['wide_target'] for r in calibration])
    weights = np.concatenate([np.full(len(r['keys']),1/len(r['keys'])) for r in calibration])
    calibrator = LogisticRegression(C=1)
    calibrator.fit(logit(np.clip(p,1e-8,1-1e-8))[:,None],labels,sample_weight=weights/weights.mean())
    return dict(model=model,calibrator=calibrator,feature=feature)


def scores(r,models,transforms):
    """対象結果を使わず、各モデルと欠測時の混合モデルのペア確率を返す。"""
    r = dict(r)
    for name,transform in transforms.items():
        r[name] = transform['imputer'].transform(r['full_x'][:,transform['keep']])
    out = {}
    for name,value in models.items():
        model = value['model']
        if name.startswith('q_'):
            delta = (r[model['feature']]/model['scale'])@model['coef']
            out[name] = softmax(np.log(r['market'])+value['alpha']*delta)
        else:
            raw = model.predict_proba(r[value['feature']])[:,1]
            out[name] = value['calibrator'].predict_proba(logit(np.clip(raw,1e-8,1-1e-8))[:,None])[:,1]
    # 過去3走のうち両馬に共通して観測できる走数と、共通内容列の有無で混合する。
    c = r['full_x']
    past_min = np.clip((c[:,CONTENT_START]-c[:,CONTENT_START+13])/2,0,1)
    content_cols = transforms['recent_x']['keep']
    content_cols = content_cols[content_cols>=CONTENT_START]
    availability = np.isfinite(c[:,content_cols]).mean(axis=1) if len(content_cols) else np.zeros(len(c))
    gate = past_min*availability
    hist_min = (r['history_x'][:,7]-r['history_x'][:,7+H])/2
    has_history = (hist_min>0).astype(float)
    delta_stable = np.log(out['q_history']/r['market'])
    delta_recent = np.log(out['q_recent']/r['market'])
    out['q_gated'] = softmax(np.log(r['market'])+has_history*((1-gate)*delta_stable+gate*delta_recent))
    return out


def market_wide(r):
    """T-30単勝支持だけからPlackett–Luceの上位3頭ペア確率を計算する。"""
    runner_p = r['runner_market']
    total = sum(runner_p.values())
    p = {k:v/total for k,v in runner_p.items()}
    out = []
    for left,right in r['keys']:
        value = 0.
        for third in p:
            if third in [left,right]:
                continue
            for a,b,c in permutations((left,right,third)):
                value += p[a]*p[b]*p[c]/((1-p[a])*(1-p[a]-p[b]))
        out.append(value)
    return np.asarray(out)


def choose(trial,prediction,r):
    """固定した10案の入力確率とT-30価格から券種・ペア・点数を決める。"""
    mapping = {'S01':'q_market','S02':'q_history','S03':'q_stable','S04':'q_recent','S05':'q_gated',
               'S06':'w_history','S07':'w_recent','S08':'q_gated','S09':'w_recent','S10':'w_recent'}
    name = mapping[trial]
    kind = 'quinella' if name.startswith('q_') else 'wide'
    score = prediction[name].copy()
    prices = r['prices']
    valid = np.isfinite(prices) if kind=='quinella' else np.ones(len(score),dtype=bool)
    if trial=='S08':
        valid &= (prices>=4)&(prices<=80)&(score>=.015)
        score *= np.nan_to_num(prices)
    if trial=='S09':
        valid &= score>=.08
        valid &= np.asarray([all(r['runner_prices'][k]<=30 for k in pair) for pair in r['keys']])
        score -= r['market_wide']
    positions = np.flatnonzero(valid)
    best = sorted(positions,key=lambda i:(-score[i],int(i)))[:1]
    if trial=='S10' and best:
        first = set(r['keys'][best[0]])
        others = [i for i in positions if len(first.intersection(r['keys'][i]))==1]
        best += sorted(others,key=lambda i:(-score[i],int(i)))[:1]
    return kind,[int(i) for i in best]


def baseline_tickets():
    """前回選択候補の保存買い目だけを比較用に読み込む。"""
    with (OLD/'tickets.jsonl').open(encoding='utf-8') as stream:
        return [t for line in stream if (t:=json.loads(line))['trial'] in ['P03','P09']]


def prepare_records():
    """既存の履歴・払戻照合を1回再利用し、予測入力と教師ラベルを分離する。"""
    rows,metadata,audit,hashes,maxpast = v2.previous.build_rows()
    grouped = defaultdict(list)
    for row in rows:
        if period(row['race_date']):
            grouped[row['race_id']].append(row)
    records = []
    for rid,field in sorted(grouped.items(),key=lambda item:(item[1][0]['race_date'],item[0])):
        meta = metadata[rid]
        if not meta['quinella_payout']:
            continue
        allowed = [{k:v for k,v in row.items() if k not in ['rank','top3']} for row in field]
        record = v2.design(allowed,{'quinella':meta['quinella']})
        target = np.asarray([float(k in meta['quinella_payout']) for k in record['keys']])
        if target.sum()==0:
            continue
        ranks = {row['key']:row['rank'] for row in field}
        assert all(all(0<ranks[k]<=2 for k in pair) for pair in meta['quinella_payout'])
        target /= target.sum()
        record.update(race_id=rid,race_date=meta['race_date'],period=period(meta['race_date']),course=meta['course'],
                      target=target,wide_target=np.asarray([float(k in meta['wide_payout']) for k in record['keys']]),
                      q_payout=meta['quinella_payout'],w_payout=meta['wide_payout'],
                      runner_market={row['key']:row['market_probability'] for row in field},
                      runner_prices={row['key']:row['price'] for row in field})
        polluted = v2.design(field,{**meta,'T-10m':{'fake':99999}})
        assert all(np.array_equal(record[k],polluted[k],equal_nan=True) for k in ['market_x','history_x','full_x','market','prices'])
        records.append(record)
    return records,audit,hashes,maxpast


def main():
    """固定10案の学習、時系列評価、同じ購入レースでの比較と会計確認を行う。"""
    sys.stdout.reconfigure(encoding='utf-8')
    records,audit,hashes,maxpast = prepare_records()
    train = [r for r in records if r['period']=='train']
    recent = [r for r in train if r['race_date']>='2025-01-01']
    calibration = [r for r in records if r['period']=='calibration']
    print('Counts',len(train),len(recent),len(calibration),flush=True)
    transforms = dict(stable_x=stable_content(train,calibration,'stable_x',records),
                      recent_x=stable_content(recent,calibration,'recent_x',records))
    models = {}
    for name,data,feature in [('q_market',train,'market_x'),('q_history',train,'history_x'),
                              ('q_stable',train,'stable_x'),('q_recent',recent,'recent_x')]:
        models[name] = fit_q(data,calibration,feature)
        print('Fitted',name,'alpha',models[name]['alpha'],flush=True)
    models['w_history'] = fit_w(train,calibration,'history_x')
    models['w_recent'] = fit_w(recent,calibration,'recent_x')
    joblib.dump(dict(models=models,transforms=transforms,contract=CONTRACT),OUT/'models.joblib')
    evaluated = [r for r in records if r['period'] not in ['train','calibration']]
    by_id = {r['race_id']:r for r in evaluated}
    tickets = []
    predictions = []
    losses = defaultdict(list)
    mutation_checks = 0
    for r in evaluated:
        allowed = {k:v for k,v in r.items() if k not in ['target','wide_target','q_payout','w_payout']}
        allowed['market_wide'] = market_wide(allowed)
        prediction = scores(allowed,models,transforms)
        mutated = scores({**allowed,'target':np.zeros(len(r['keys'])),'wide_target':np.ones(len(r['keys'])),'T-10m':{'fake':99999},'q_payout':{'fake':99999}},models,transforms)
        assert all(np.array_equal(prediction[k],mutated[k]) for k in prediction)
        predictions.append(dict(race_id=r['race_id'],race_date=r['race_date'],period=r['period'],keys=r['keys'],scores={k:v.tolist() for k,v in prediction.items()}))
        for name,p in {'q_raw_market':r['market'],**prediction}.items():
            loss = float(-r['target']@np.log(np.maximum(p,1e-15))) if name.startswith('q_') else float(np.mean((p-r['wide_target'])**2))
            losses[(r['period'],name)].append(loss)
        for trial in CONTRACT['trials']:
            kind,indices = choose(trial,prediction,allowed)
            assert (kind,indices)==choose(trial,mutated,{**allowed,'rank':9999,'T-10m':{'fake':99999}})
            mutation_checks += 1
            stake = 600//len(indices) if indices else 0
            for i in indices:
                pair = r['keys'][i]
                payout = r['q_payout'] if kind=='quinella' else r['w_payout']
                tickets.append(dict(trial=trial,kind=kind,race_id=r['race_id'],race_date=r['race_date'],period=r['period'],course=r['course'],
                                    pair=pair,stake_yen=stake,return_yen=payout.get(pair,0)*(stake//100)))
    baseline = baseline_tickets()
    results = {}
    periods = ['development','confirmation_early','confirmation_late']
    for trial in CONTRACT['trials']:
        actual = [t for t in tickets if t['trial']==trial]
        kind = 'wide' if trial in ['S06','S07','S09','S10'] else 'quinella'
        bought = {t['race_id'] for t in actual}
        matched = [{**t,'period':by_id[t['race_id']]['period']} for t in baseline if t['race_id'] in bought and t['kind']==kind]
        assert {t['race_id'] for t in matched}==bought
        values = {}
        for part in periods+['confirmation_combined']:
            current = [t for t in actual if t['period']==part or (part=='confirmation_combined' and t['period'].startswith('confirmation'))]
            comparison = [t for t in matched if t['period']==part or (part=='confirmation_combined' and t['period'].startswith('confirmation'))]
            a,b = v2.summary(current),v2.summary(comparison)
            assert a['stake_yen']==b['stake_yen']
            values[part] = dict(actual=a,matched_baseline=b,roi_difference=a['roi']-b['roi'] if a['roi'] is not None else None)
        results[trial] = values
        print(trial,[(part,value['actual']['races'],round(value['actual']['roi']*100,2) if value['actual']['roi'] is not None else None,
                      round(value['roi_difference']*100,2) if value['roi_difference'] is not None else None) for part,value in values.items()],flush=True)
    selected = {}
    for kind,options in [('quinella',['S01','S02','S03','S04','S05','S08']),('wide',['S06','S07','S09','S10'])]:
        eligible = [t for t in options if results[t]['development']['actual']['races']>=30]
        selected[kind] = max(eligible,key=lambda t:results[t]['development']['actual']['roi']) if eligible else None
    for t in tickets:
        r = by_id[t['race_id']]
        payout = r['q_payout'] if t['kind']=='quinella' else r['w_payout']
        assert t['return_yen']==payout.get(tuple(t['pair']),0)*t['stake_yen']//100
    budgets = defaultdict(int)
    for t in tickets:
        budgets[(t['trial'],t['race_id'])] += t['stake_yen']
    assert all(value==600 for value in budgets.values())
    for path,digest in hashes.items():
        assert v2.sha256(Path(path))==digest
    tree = ast.parse(Path(__file__).read_text(encoding='utf-8'))
    assert ast.get_docstring(tree) and all(ast.get_docstring(n) for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.ClassDef)))
    coverage = {name:{'kept_columns':v['keep'].tolist(),'train_observed':v['train_observed'].tolist(),'calibration_observed':v['calibration_observed'].tolist()} for name,v in transforms.items()}
    quality = {part:{name:float(np.mean(values)) for (p,name),values in losses.items() if p==part} for part in periods}
    report = dict(contract=CONTRACT,contract_sha256=v2.sha256(OUT/'protocol.json'),input_sha256=hashes,
                  reused_code_sha256={str(Path(v2.__file__)):v2.sha256(Path(v2.__file__)),str(Path(v2.previous.__file__)):v2.sha256(Path(v2.previous.__file__))},
                  baseline_sha256=v2.sha256(OLD/'tickets.jsonl'),model_sha256=v2.sha256(OUT/'models.joblib'),script_sha256=v2.sha256(Path(__file__)),
                  source_audit=dict(audit),period_counts={p:sum(r['period']==p for r in records) for p in ['train','calibration',*periods]},recent_training_races=len(recent),
                  training_max_date=max(r['race_date'] for r in train),calibration_max_date=max(r['race_date'] for r in calibration),
                  max_used_past_date=maxpast,feature_selection=coverage,calibration={k:v['alpha'] for k,v in models.items() if 'alpha' in v},
                  quality=quality,results=results,development_selected=selected,trial_count=10)
    save('report.json',report)
    save('verification.json',dict(input_hashes_unchanged=True,strict_past_dates=True,mutation_checks=mutation_checks,
                                  ticket_accounting_checks=len(tickets),budgets_600=True,matched_baseline_stakes_equal=True,docstrings=True))
    for name,data in [('tickets.jsonl',tickets),('predictions.jsonl',predictions)]:
        with (OUT/name).open('w',encoding='utf-8') as stream:
            for item in data:
                stream.write(json.dumps(item,ensure_ascii=False,allow_nan=False)+'\n')
    print('Selected',selected,flush=True)


if __name__ == '__main__':
    with threadpool_limits(limits=2):
        main()
