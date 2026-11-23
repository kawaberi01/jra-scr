"""概要: 東スポ杯の発走前人気を単独パーツ・条件複合パーツとして固定比較する。
作成日: 2026-11-23
入力: T30/T10固定市場46行、旧特徴・予測、対象結果、固定仕様050。
出力: 5方式＋旧基準の時系列評価、選択、人気帯成績、入力監査とSHA。
実行例: uv run python scripts/verify_tokyo_sports_popularity.py
注意事項: オフライン。過去結果は学習・評価へ分離。当該2026結果は取得しない。
"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from jra_srb.jra_conditions_refinement import group_deltas, candidate_prediction
from jra_srb.jra_specific_patterns import metrics, mean_metrics


def read(path: Path) -> object:
    """固定JSONを読む。"""
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: object) -> None:
    """丸め前の値を保存する。"""
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def band(pop: int) -> str:
    """事前固定した人気帯へ分類する。"""
    return str(pop) if pop<=3 else '4-5' if pop<=5 else '6-8' if pop<=8 else '9+'


def create_sets(examples: list[dict], markets: list[dict], horizon: str) -> tuple[dict,list[dict]]:
    """全頭集合と公表締切を検査し人気条件の特徴を作る。"""
    output={k:[] for k in ('M','MC','joint')};audits=[]
    for race in examples:
        found=[m for m in markets if m['race_key']==race['race_key'] and m['horizon']==horizon];assert len(found)==1
        m=found[0]
        if m['selection_status']!='selected':
            audits.append({'race_key':race['race_key'],'horizon':horizon,'status':m['selection_status'],'excluded':True})
            continue
        assert datetime.fromisoformat(m['announced_at'])<=datetime.fromisoformat(m['cutoff_at'])
        entries=[r for r in json.loads(m['entries_json']) if r['market']=='win'];by_no={int(r['selection_key']):r for r in entries}
        assert len(by_no)==len(entries)
        assert {int(r['horse_no']) for r in race['rows']}.issubset(set(by_no))
        target_rows={k:[] for k in output}
        for r in race['rows']:
            observed=by_no[int(r['horse_no'])];pop=observed['popularity']
            assert isinstance(pop,int) and pop>=1 and observed['odds_status_low']=='numeric'
            atoms=r['atoms'];main=('prev_win','prev1800','career_le3','never_below3')
            known=all(atoms[k] is not None for k in main)
            count=str(sum(atoms[k] for k in main)) if known else None
            joint=band(pop)+'|'+''.join(str(int(atoms[k])) for k in main) if known else None
            common={k:v for k,v in r.items() if k not in ('values','history','atoms')}
            target_rows['M'].append({**common,'values':{'pop':str(pop)}})
            target_rows['MC'].append({**common,'values':{'band':band(pop),'count':count}})
            target_rows['joint'].append({**common,'values':{'joint':joint}})
        for key in output:output[key].append({k:v for k,v in race.items() if k!='rows'} | {'rows':target_rows[key]})
        audits.append({'race_key':race['race_key'],'horizon':horizon,'cutoff_at':m['cutoff_at'],'announced_at':m['announced_at'],
            'content_sha256':m['content_sha256'],'market_rows':len(entries),'active_rows':len(race['rows']),'roster_matched':True})
    return output,audits


def calculate(sets: dict, prior: dict, index: int, cfg: dict, original: list[dict]) -> list[dict]:
    """人気だけ・一般補助・固有補助・条件群・同時型の5方式を計算する。"""
    settings={'M':{'人気':['pop']},'MC':{'人気帯':['band'],'4条件数':['count']},'joint':{'人気と条件同時型':['joint']}}
    calculated={}
    for key,groups in settings.items():
        ev=group_deltas(prior[key],sets[key][index],{**cfg,'groups':groups},{'half_life':None,'pooling':'hierarchical','shrinkage':20})
        calculated[key]=candidate_prediction(ev,sets[key][index],{'pattern':key,'family':'popularity','weights':[2,1] if key=='MC' else [1],'scale':1})
    out=[calculated['M'],calculated['MC'],calculated['joint']]
    key=sets['M'][index]['race_key']
    for source,name in [('general','M+G'),('S15','M+S')]:
        base=next(r for r in original if r['race_key']==key and r['pattern']==source)
        bp={r['horse_no']:r['probability_top3'] for r in base['runners']}
        rows=[{**r,'probability_top3':(2*r['probability_top3']+bp[r['horse_no']])/3} for r in calculated['M']['runners']]
        rows.sort(key=lambda r:(-r['probability_top3'],int(r['horse_no'])))
        out.append({**calculated['M'],'pattern':name,'runners':rows})
    out.append(next(r for r in original if r['race_key']==key and r['pattern']=='general'))
    assert len(out)==6 and all(abs(sum(r['probability_top3'] for r in p['runners'])-3)<1e-9 for p in out)
    return out


def main() -> None:
    """旧版を保持して市場との追加比較だけを新規出力する。"""
    source=ROOT/'artifacts/jra_research/tokyo_sports_patterns_20261122_v1'
    market_path=ROOT/'artifacts/jra_research/tokyo_sports_market_coverage_20261123/coverage.json'
    output=ROOT/'artifacts/jra_research/tokyo_sports_popularity_20261123_v1_1';output.mkdir(exist_ok=False)
    examples=read(source/'examples.json')['specific'];markets=read(market_path);original=read(source/'predictions.json')
    cfg=read(ROOT/'configs/research/race_conditions_elizabeth_v1.json');all_out={}
    for horizon in ('T30','T10'):
        sets,audit=create_sets(examples,markets,horizon);predictions=[];annual=[]
        for i,race in enumerate(sets['M']):
            if i<5:continue
            local=calculate(sets,{k:v[:i] for k,v in sets.items()},i,cfg,original)
            target=next(r for r in examples if r['race_key']==race['race_key'])
            for p in local:
                predictions.append(p);annual.append({'race_date':race['race_date'],'race_key':race['race_key'],'pattern':p['pattern'],**metrics(p,target)})
        assert len(predictions)==(108 if horizon=='T30' else 96)
        summaries={period:{pattern:mean_metrics([r for r in annual if lo<=int(r['race_date'][:4])<=hi and r['pattern']==pattern]) for pattern in ('M','M+G','M+S','MC','joint','general')}
            for period,(lo,hi) in {'development':(2008,2015),'validation':(2016,2020),'audit':(2021,2025)}.items()}
        dev=summaries['development'];eligible=[k for k in ('M+G','M+S','MC','joint') if dev[k]['top3_captured']>=dev['M']['top3_captured']-1e-12]
        selected=min(eligible,key=lambda k:(dev[k]['brier'],k)) if eligible else 'M'
        a,b=summaries['validation'][selected],summaries['validation']['M']
        improved=sum(next(x['brier'] for x in annual if x['pattern']==selected and x['race_date'][:4]==str(y))<next(x['brier'] for x in annual if x['pattern']=='M' and x['race_date'][:4]==str(y)) for y in range(2016,2021))
        checks={'brier_1pct':a['brier']<=.99*b['brier'],'capture_not_worse':a['top3_captured']>=b['top3_captured']-1e-12,'logloss_not_worse':a['logloss']<=b['logloss'],'majority_improved':improved>=3}
        primary=selected if all(checks.values()) else 'M'
        pop_records={}
        for lo,hi in [(2003,2025),(2016,2025)]:
            record={}
            for group in ('1','2','3','4-5','6-8','9+'):
                rows=[r for race in sets['MC'] if lo<=int(race['race_date'][:4])<=hi for r in race['rows'] if r['values']['band']==group]
                counts=[sum(r['finish_rank']==k for r in rows) for k in (1,2,3)];counts.append(len(rows)-sum(counts));record[group]=counts
            pop_records[f'{lo}-{hi}']=record
        all_out[horizon]={'selection':{'candidate':selected,'used':primary,'checks':checks,'selected_through':2015,'adoption_through':2020,'audit_used_for_selection':False},'summaries':summaries,'pop_records':pop_records,'input_audit':audit}
        save(output/(horizon+'-predictions.json'),predictions);save(output/(horizon+'-annual.json'),annual)
    save(output/'summary.json',all_out)
    lines=['# 東スポ杯：人気パーツの固定比較','','発走前T30を本比較108予測、T10は2012・2025の同時刻内容競合を除外した感度分析96予測。最終人気の公式記事とは別の観測時点。公開傾向参照後の探索で独立未知性能ではない。','',
        '|時点|期間|方式|Brier|上位3捕捉/開催|上位6捕捉/開催|','|---|---|---|---:|---:|---:|']
    for horizon,result in all_out.items():
        for period,vals in result['summaries'].items():
            for name in dict.fromkeys(('M',result['selection']['candidate'],result['selection']['used'],'general')):
                s=vals[name];lines.append(f"|{horizon}|{period}|{name}|{s['brier']:.6f}|{s['top3_captured']:.3f}|{s['top6_captured']:.3f}|")
    lines+=['','## 採否と利用境界','',json.dumps({h:r['selection'] for h,r in all_out.items()},ensure_ascii=False),
        '', '人気はオッズの逆数を3着内確率へ転用せず、過去年の同人気の実際の3着内事実から推定した。現在未明の途中人気はT30ではなく、当日直前人気への可用性は未充足。旧予想は上書きしない。']
    (output/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    save(output/'manifest.json',{'inputs':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),market_path,source/'examples.json',source/'predictions.json']},'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}})
    print(json.dumps({h:{'selection':r['selection'],'audit':{k:r['summaries']['audit'][k] for k in ('M','general')},'validation':{k:r['summaries']['validation'][k] for k in ('M','general')}} for h,r in all_out.items()},ensure_ascii=False))


if __name__=='__main__':main()
