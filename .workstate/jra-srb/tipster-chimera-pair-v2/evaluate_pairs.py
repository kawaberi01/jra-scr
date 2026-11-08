"""概要：既存履歴処理を再利用し、共同的中確率と買い目の10仮説を時系列で比較する。
作成日：2026-10-02
入力：protocol.json、既存2024～2026年JSONL、読み取り専用analysis.sqlite。
出力：同じディレクトリ内のモデル、予測、買い目、report.json、verification.json。
実行例：uv run python .workstate/jra-srb/tipster-chimera-pair-v2/evaluate_pairs.py
注意事項：元データ・既存モデル・稼働中取得処理は変更しない。外部通信なし。
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from pathlib import Path
import ast
import importlib.util
import json
import sys
import joblib
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import expit, logit, softmax
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from jra_second_ten_model import fit_choice, choice
from evaluate_jra_o1o2_movement import sha256
spec = importlib.util.spec_from_file_location('previous_chimera', OUT.parent/'tipster-trace-v1/evaluate_chimera.py')
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)


def save(name, value):
    """研究ディレクトリにUTF-8のJSONを保存する。"""
    (OUT/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def period(day):
    """固定した日付区間を返し、夏と対象外期間を除外する。"""
    if int(day[5:7]) in [6, 7, 8]:
        return None
    for key, bounds in CONTRACT.items():
        if key in ['train', 'calibration', 'development', 'check', 'reused_2026'] and bounds[0] <= day <= bounds[1]:
            return key
    return None


def design(field, meta):
    """予測時点の入力だけから全2頭組合せの対称特徴量を生成する。

    Args:
        field: 結果ラベルを除いた馬ごとのT-30情報と過去履歴。
        meta: 券種価格など予測時点で許可された情報。
    Returns:
        ペア、特徴行列、馬連市場確率、T-30馬連価格を含む辞書。
    Notes:
        払戻と対象レース結果にはアクセスしない。欠損馬連価格は単勝由来の代替支持を使う。
    """
    pairs = list(combinations(range(len(field)), 2))
    keys = [tuple(sorted((field[i]['key'], field[j]['key']), key=int)) for i,j in pairs]
    p = np.asarray([r['market_probability'] for r in field])
    pl = np.asarray([p[i]*p[j]*(1/(1-p[i])+1/(1-p[j])) for i,j in pairs])
    prices = np.asarray([meta['quinella'].get(k, np.nan) for k in keys])
    market = np.where(np.isfinite(prices), 1/prices, pl*.775)
    market /= market.sum()
    base = []
    hist = []
    content = []
    for index,(i,j) in enumerate(pairs):
        a,b = field[i],field[j]
        base.append([np.log(pl[index]), np.log(market[index]/pl[index]), min(p[i],p[j]), max(p[i],p[j]),
                     abs(np.log(p[i]/p[j])), len(field)/18, int(np.isfinite(prices[index]))])
        ha,hb = np.asarray(a['basic'][2:]),np.asarray(b['basic'][2:])
        hist.append(np.r_[ha+hb, np.abs(ha-hb)])
        ca,cb = np.asarray(a['content']),np.asarray(b['content'])
        da,db = np.asarray(a['condition']),np.asarray(b['condition'])
        front_a = float(ca[9] <= .3) if np.isfinite(ca[9]) else np.nan
        front_b = float(cb[9] <= .3) if np.isfinite(cb[9]) else np.nan
        content.append(np.r_[ca+cb,np.abs(ca-cb),da+db,np.abs(da-db),
                             front_a*front_b,abs(front_a-front_b),front_a*front_b*da[23]])
    return dict(keys=keys, market=market, prices=prices, market_x=np.asarray(base),
                history_x=np.column_stack((base,hist)), full_x=np.column_stack((base,hist,content)))


def prepare():
    """既存の厳密な履歴抽出と払戻照合を再利用し、ラベルを入力とは別に作る。"""
    rows,meta,audit,hashes,maxpast = previous.build_rows()
    fields = defaultdict(list)
    for row in rows:
        if period(row['race_date']):
            fields[row['race_id']].append(row)
    records = []
    for rid,field in sorted(fields.items(), key=lambda item:(item[1][0]['race_date'],item[0])):
        m = meta[rid]
        allowed = [{k:v for k,v in row.items() if k not in ['rank','top3']} for row in field]
        r = design(allowed, {'quinella':m['quinella']})
        yq = np.asarray([float(k in m['quinella_payout']) for k in r['keys']])
        if yq.sum() == 0:
            continue
        yq /= yq.sum()
        yw = np.asarray([float(k in m['wide_payout']) for k in r['keys']])
        r.update(race_id=rid, race_date=m['race_date'], period=period(m['race_date']),
                 target=yq, wide_target=yw, q_payout=m['quinella_payout'], w_payout=m['wide_payout'], course=m['course'])
        # 対象レースの順位・払戻を追加しても入力行列が変わらないことを確認する。
        mutated = design(field, {**m,'T-10m':{'fake':9999}})
        for name in ['market_x','history_x','full_x','market','prices']:
            assert np.array_equal(r[name],mutated[name],equal_nan=True)
        records.append(r)
    return records,audit,hashes,maxpast


def fit_models(train, calibration):
    """2024年で共同確率を学習し、2025年初めの正解だけで校正する。"""
    models = {}
    imputer = SimpleImputer(strategy='mean', add_indicator=True, keep_empty_features=True)
    imputer.fit(np.concatenate([r['full_x'] for r in train]))
    for r in train+calibration:
        r['imputed'] = imputer.transform(r['full_x'])
    for key,feature in [('q_market','market_x'),('q_history','history_x'),('q_content','imputed')]:
        model = fit_choice(train,feature=feature,penalty=.1)
        deltas = [(r[feature]/model['scale'])@model['coef'] for r in calibration]
        def loss(alpha):
            """校正期間のレース単位対数損失を計算する。"""
            return float(np.mean([-r['target']@np.log(np.maximum(softmax(np.log(r['market'])+alpha*d),1e-15))
                                  for r,d in zip(calibration,deltas,strict=True)]))
        alpha = float(minimize_scalar(loss,bounds=(0,1),method='bounded').x)
        models[key] = dict(model=model,alpha=alpha)
        print('Fitted',key,'alpha',alpha,flush=True)
    x = np.concatenate([r['imputed'] for r in train])
    weights = np.concatenate([np.full(len(r['keys']),1/len(r['keys'])) for r in train])
    for key,label,nonlinear in [('q_boost','target',True),('w_linear','wide_target',False),('w_boost','wide_target',True)]:
        y = np.concatenate([r[label] for r in train])
        # 同着の分数ラベルはこの二値モデルに限り正解として扱う。
        model = HistGradientBoostingClassifier(max_iter=100,max_leaf_nodes=7,min_samples_leaf=150,
                     learning_rate=.04,l2_regularization=10,early_stopping=False,random_state=2026) if nonlinear else make_pipeline(StandardScaler(),LogisticRegression(C=.1,max_iter=1000))
        model.fit(x,(y>0).astype(int),sample_weight=weights/weights.mean()) if nonlinear else model.fit(x,(y>0).astype(int),logisticregression__sample_weight=weights/weights.mean())
        raw = [np.clip(model.predict_proba(r['imputed'])[:,1],1e-8,1-1e-8) for r in calibration]
        if key == 'q_boost':
            delta = [np.log(p/p.sum())-np.log(r['market']) for r,p in zip(calibration,raw,strict=True)]
            def boost_loss(alpha):
                """馬連非線形モデルの市場からの乖離を校正する。"""
                return float(np.mean([-r['target']@np.log(np.maximum(softmax(np.log(r['market'])+alpha*d),1e-15)) for r,d in zip(calibration,delta,strict=True)]))
            models[key] = dict(model=model,alpha=float(minimize_scalar(boost_loss,bounds=(0,1),method='bounded').x))
        else:
            calibrator = LogisticRegression(C=1)
            calibrator.fit(np.concatenate([logit(p) for p in raw])[:,None],np.concatenate([r['wide_target'] for r in calibration]))
            models[key] = dict(model=model,calibrator=calibrator)
        print('Fitted',key,flush=True)
    ratios = [r['q_payout'][k]/100/r['prices'][i] for r in calibration for i,k in enumerate(r['keys']) if k in r['q_payout'] and np.isfinite(r['prices'][i])]
    discount = min(1.,(sum(ratios)+30)/(len(ratios)+30))
    return models,imputer,discount


def predict(r, models, imputer):
    """学習済みモデルで結果ラベルを参照せずペア確率を返す。"""
    r = dict(r)
    r['imputed'] = imputer.transform(r['full_x'])
    scores = {}
    for key,value in models.items():
        model = value['model']
        if key in ['q_market','q_history','q_content']:
            delta = (r[model['feature']]/model['scale'])@model['coef']
            scores[key] = softmax(np.log(r['market'])+value['alpha']*delta)
        else:
            raw = np.clip(model.predict_proba(r['imputed'])[:,1],1e-8,1-1e-8)
            scores[key] = softmax(np.log(r['market'])+value['alpha']*(np.log(raw/raw.sum())-np.log(r['market']))) if key=='q_boost' else value['calibrator'].predict_proba(logit(raw)[:,None])[:,1]
    return scores


def choose(trial, scores, prices, discount):
    """固定10仮説の確率・価格だけから券種と購入ペア位置を決める。"""
    mapping = {'P01':'q_market','P02':'q_history','P03':'q_content','P04':'q_boost',
               'P05':'w_linear','P06':'w_boost','P07':'q_content','P08':'q_boost','P09':'w_linear','P10':'q_content'}
    key = mapping[trial]
    kind = 'wide' if key.startswith('w_') else 'quinella'
    valid = np.ones(len(prices),dtype=bool) if kind=='wide' else np.isfinite(prices)
    score = scores[key].copy()
    if trial in ['P07','P08','P10']:
        valid &= (prices>=3)&(prices<=100)
        score *= np.nan_to_num(prices)*discount
        valid &= score>=1.05
    positions = np.flatnonzero(valid)
    selected = sorted(positions,key=lambda i:(-score[i],int(i)))[:2 if trial=='P09' else 1]
    if trial=='P10' and selected:
        other = scores['q_boost']*np.nan_to_num(prices)*discount
        alternatives = np.flatnonzero(np.isfinite(prices)&(prices>=3)&(prices<=100)&(other>=1.05))
        best = max(alternatives,key=lambda i:(other[i],-int(i))) if len(alternatives) else None
        if best != selected[0]:
            selected = []
    return kind,[int(i) for i in selected]


def summary(tickets):
    """買い目をレース単位に集計し、回収率・最大払戻除外・日別損失を返す。"""
    races = defaultdict(lambda:[0,0])
    daily = defaultdict(int)
    for t in tickets:
        races[t['race_id']][0] += t['stake_yen']
        races[t['race_id']][1] += t['return_yen']
        daily[t['race_date']] += t['return_yen']-t['stake_yen']
    stake = sum(t['stake_yen'] for t in tickets)
    returned = sum(t['return_yen'] for t in tickets)
    biggest = max(races.values(),key=lambda x:x[1],default=[0,0])
    balance = peak = drawdown = 0
    for day in sorted(daily):
        balance += daily[day]
        peak = max(peak,balance)
        drawdown = max(drawdown,peak-balance)
    rng = np.random.default_rng(2026)
    day_values = [(sum(t['stake_yen'] for t in tickets if t['race_date']==day),sum(t['return_yen'] for t in tickets if t['race_date']==day)) for day in sorted(daily)]
    ci = None
    if day_values:
        a = np.asarray(day_values)
        sample = a[rng.integers(0,len(a),size=(2000,len(a)))].sum(axis=1)
        ci = np.quantile(sample[:,1]/sample[:,0],[.025,.975]).tolist()
    return dict(races=len(races),tickets=len(tickets),hits=sum(v[1]>0 for v in races.values()),
                stake_yen=stake,return_yen=returned,profit_yen=returned-stake,roi=returned/stake if stake else None,
                roi_without_max=(returned-biggest[1])/(stake-biggest[0]) if stake>biggest[0] else None,
                day_bootstrap_roi_95=ci,max_daily_drawdown_yen=drawdown)


def main():
    """固定契約に従い学習・予測・10比較・漏洩と会計の確認を実行する。"""
    sys.stdout.reconfigure(encoding='utf-8')
    records,audit,hashes,maxpast = prepare()
    print('Periods', {k:sum(r['period']==k for r in records) for k in ['train','calibration','development','check','reused_2026']},flush=True)
    train = [r for r in records if r['period']=='train']
    calibration = [r for r in records if r['period']=='calibration']
    models,imputer,discount = fit_models(train,calibration)
    joblib.dump(dict(models=models,imputer=imputer,discount=discount,contract=CONTRACT),OUT/'pair_models.joblib')
    tickets = []
    predictions = []
    checks = 0
    for r in records:
        if r['period'] in ['train','calibration']:
            continue
        allowed = {k:v for k,v in r.items() if k not in ['target','wide_target','q_payout','w_payout']}
        scores = predict(allowed,models,imputer)
        polluted = predict({**allowed,'target':np.ones(len(r['keys'])),'q_payout':{'fake':99999},'T-10m':{'fake':99999}},models,imputer)
        assert all(np.array_equal(scores[k],polluted[k]) for k in scores)
        predictions.append(dict(race_id=r['race_id'],race_date=r['race_date'],period=r['period'],keys=r['keys'],
                                prices=[float(p) if np.isfinite(p) else None for p in r['prices']],scores={k:v.tolist() for k,v in scores.items()}))
        for trial in CONTRACT['trials']:
            kind,indices = choose(trial,scores,r['prices'],discount)
            checks += 1
            stake = 600//len(indices) if indices else 0
            for i in indices:
                pair = r['keys'][i]
                payout = r['w_payout'] if kind=='wide' else r['q_payout']
                tickets.append(dict(trial=trial,kind=kind,race_id=r['race_id'],race_date=r['race_date'],period=r['period'],
                                    course=r['course'],pair=pair,stake_yen=stake,return_yen=payout.get(pair,0)*(stake//100)))
    results = {trial:{part:summary([t for t in tickets if t['trial']==trial and t['period']==part]) for part in ['development','check','reused_2026']} for trial in CONTRACT['trials']}
    chosen = {}
    for kind,prefix in [('quinella','q_'),('wide','w_')]:
        eligible = [trial for trial in results if any(t['trial']==trial and t['kind']==kind for t in tickets) and results[trial]['development']['races']>=30]
        chosen[kind] = max(eligible,key=lambda trial:results[trial]['development']['roi']) if eligible else None
    for path,digest in hashes.items():
        assert sha256(Path(path))==digest
    for t in tickets:
        r = next(r for r in records if r['race_id']==t['race_id'])
        assert t['return_yen']==(r['w_payout'] if t['kind']=='wide' else r['q_payout']).get(tuple(t['pair']),0)*t['stake_yen']//100
    tree = ast.parse(Path(__file__).read_text(encoding='utf-8'))
    assert ast.get_docstring(tree) and all(ast.get_docstring(node) for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.ClassDef,ast.AsyncFunctionDef)))
    report = dict(contract=CONTRACT,contract_sha256=sha256(OUT/'protocol.json'),input_sha256=hashes,
                  reused_code_sha256={str(Path(previous.__file__)):sha256(Path(previous.__file__)),str(ROOT/'scripts/jra_second_ten_model.py'):sha256(ROOT/'scripts/jra_second_ten_model.py')},
                  models_sha256=sha256(OUT/'pair_models.joblib'),source_audit=dict(audit),period_counts={k:sum(r['period']==k for r in records) for k in ['train','calibration','development','check','reused_2026']},
                  maximum_used_past_date=maxpast,settlement_discount=discount,calibration={k:{'alpha':v['alpha']} if 'alpha' in v else {'coef':v['calibrator'].coef_.tolist(),'intercept':v['calibrator'].intercept_.tolist()} for k,v in models.items()},
                  results=results,development_selected=chosen,trial_count=10)
    save('report.json',report)
    save('verification.json',dict(input_hashes_unchanged=True,feature_result_mutation_invariant=True,prediction_result_and_T10_mutation_invariant=True,selection_checks=checks,
                                  independently_recomputed_ticket_returns=len(tickets),docstring_audit=True))
    for filename,data in [('tickets.jsonl',tickets),('predictions.jsonl',predictions)]:
        with (OUT/filename).open('w',encoding='utf-8') as stream:
            for item in data:
                stream.write(json.dumps(item,ensure_ascii=False,allow_nan=False)+'\n')
    for trial,values in results.items():
        print(trial,[(p,v['races'],round(v['roi']*100,2) if v['roi'] is not None else None) for p,v in values.items()],flush=True)
    print('Selected',chosen,'discount',discount,flush=True)


CONTRACT = json.loads((OUT/'protocol.json').read_text(encoding='utf-8'))
if __name__ == '__main__':
    with threadpool_limits(limits=2):
        main()
