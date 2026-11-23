"""概要: 東スポ杯の固定34方式と28条件を時系列検証し当年参考順位を生成する。
作成日: 2026-11-22
入力: --dataset、--input、--output。
出力: 検証・全条件成績・全頭根拠・固定選択・当年参考順位・SHA。
実行例: uv run python scripts/run_tokyo_sports_patterns.py --dataset dataset.json --input inputs --output output
注意事項: オフラインのみ。SQL予想保存は別工程。当該結果を取得しない。
"""

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from jra_srb.jra_tokyo_sports_patterns import evaluate, records, examples, forecasts, features, rule_catalogue, rule_value, GROUPS
from jra_srb.jra_graded_patterns import feature_values
from jra_srb.jra_race_conditions import public_runner


def read(path: Path) -> object:
    """UTF-8 JSONを読む。"""
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: object) -> None:
    """JSONを新規出力する。"""
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def main() -> None:
    """固定入力をSHA照合し、研究結果を未使用先へ保存する。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try:
        for folder in (args.dataset.parent,args.input):
            manifest=read(folder/'manifest.json')
            for name,digest in manifest['files'].items():assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest,name
        data=read(args.dataset);card=read(args.input/'normalized-card.json');history=read(args.input/'normalized-history.json')
        cfg=read(ROOT/'configs/research/race_conditions_elizabeth_v1.json')
        result=evaluate(data,cfg)
        cond=records(result['sets'])
        targets={k:{k2:v for k2,v in card.items() if k2!='runners'} | {'evaluation_eligible':True,'rows':[]} for k in ('specific','general','joint')}
        rationales=[]
        for r in card['runners']:
            f=features(card,r,history);common=public_runner(r)
            targets['specific']['rows'].append({**common,**f})
            targets['general']['rows'].append({**common,'values':feature_values(card,r,history)})
            main=('prev_win','prev1800','career_le3','never_below3')
            joint=None if any(f['atoms'][k] is None for k in main) else ''.join(str(int(f['atoms'][k])) for k in main)
            targets['joint']['rows'].append({**common,'values':{'joint4':joint}})
            rationales.append({**common,**f,'rules':{rule['id']:rule_value(f['atoms'],rule) for rule in rule_catalogue()}})
        predictions,ev=forecasts(result['sets'],targets,cfg)
        selected=next(p for p in predictions if p['pattern']==result['selection']['used_pattern'])
        for name,value in [('summary', {k:v for k,v in result.items() if k not in ('sets','predictions','annual')}),('annual',result['annual']),('predictions',result['predictions']),('examples',result['sets']),('records',cond),('live-all-patterns',predictions),('live-selected',selected),('live-rationales',rationales),('live-evidence',ev)]:
            save(args.output/(name+'.json'),value)
        lines=['# 東京スポーツ杯2歳S 固定パターン検証','',f"23開催、対象{sum(len(r['runners']) for r in data['races'])}頭、事前履歴{len(data['history'])}走。32候補＋2基準、18年612予測。28条件。",'',f"開発選択：{result['selection']['candidate']}。採用判定：{result['selection']['validation_checks']}。当年使用：{result['selection']['used_pattern']}。",'',
            '2008〜2015開発、2016〜2020採否、2021〜2025監査。公式直近10年の傾向を参照済みのため独立未知の成績ではない。','',
            '|期間|方式|Brier|logloss|上位3捕捉/開催|上位6捕捉/開催|','|---|---|---:|---:|---:|---:|']
        for period in result['periods']:
            for pattern in dict.fromkeys([result['selection']['candidate'],result['selection']['used_pattern'],'general','uniform']):
                s=result['summaries'][period][pattern];lines.append(f"|{period}|{pattern}|{s['brier']:.6f}|{s['logloss']:.6f}|{s['top3_captured']:.3f}|{s['top6_captured']:.3f}|")
        lines += ['','## 条件根拠（1着－2着－3着－着外）','','|条件|全23年|直近10年|直近10年不明|','|---|---|---|---:|']
        for r in cond:
            lines.append('|'+r['label']+'|'+'-'.join(map(str,r['periods']['all']['matched']['record']))+'|'+'-'.join(map(str,r['periods']['recent10']['matched']['record']))+'|'+str(r['periods']['recent10']['unknown']['n'])+'|')
        lines += ['','## 欠測と採否の留保','','当年カード12頭・全掲載履歴20走を照合。歴年は固定DBの事後属性で海外/地方は不完全。初走が新馬と確認できない馬はキャリア条件を不明とし、未経験へ変換しない。確率未校正・利益未検証。GIIIと2021年以降GIIの制度差を年度別に残す。','',
            '本研究はマイルCSの係数・結果を選択に使用しない。全条件の非該当・不明・反例・該当馬はrecords.jsonに保存。']
        (args.output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        save(args.output/'manifest.json',{'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file()},'sources':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),ROOT/'src/jra_srb/jra_tokyo_sports_patterns.py',args.dataset,args.input/'normalized-card.json',args.input/'normalized-history.json']}})
        print(json.dumps({'selection':result['selection'],'top6':selected['runners'][:6],'career_unknown':sum(not r['career_complete'] for r in rationales)},ensure_ascii=False))
    except Exception as error:
        save(args.output/'failure.json',{'type':type(error).__name__,'reason':getattr(error,'reason',str(error))});raise


if __name__=='__main__':main()
