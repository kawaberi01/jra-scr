"""概要: 発走前人気パーツの参考予想と比較用買い目を事前保存用JSONへまとめる。
作成日: 2026-11-23
入力: 固定T30比較、11/23途中の公式出馬表・オッズ、旧予想。
出力: 新IDの予想payload、固定表示、証拠と検証情報。
実行例: uv run python scripts/finalize_tokyo_sports_popularity.py
注意事項: 未明の人気は発走30分前ではない。結果は取得せず、実購入は行わない。
"""

from datetime import datetime, timezone
from itertools import combinations
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
from verify_tokyo_sports_popularity import create_sets
from jra_srb.jra_conditions_refinement import group_deltas,candidate_prediction
from run_jra_graded_live import observed_price,table,jst


def read(path: Path) -> dict:
    """保存されたUTF-8 JSONを読み出す。"""
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> None:
    """時点の異なる人気を仮入力と明記して、新しい予想本文とpayloadを作る。"""
    base=ROOT/'artifacts/jra_research';out=base/'tokyo_sports_popularity_forecast_20261123_v1';out.mkdir(exist_ok=False)
    examples=read(base/'tokyo_sports_patterns_20261122_v1/examples.json')['specific']
    markets=read(base/'tokyo_sports_market_coverage_20261123/coverage.json');sets,audits=create_sets(examples,markets,'T30')
    old=read(base/'tokyo_sports_forecast_20261122_v1/payload.json')
    card=read(base/'tokyo_sports_collect_20261122_v1_1/normalized-card.json')
    api=read(base/'tokyo_sports_popularity_current_20261123_v1/card.json')
    odds=read(base/'tokyo_sports_popularity_current_20261123_v1/odds.json')
    assert api['race_id']==card['race_key']==odds['race_id']=='202611230511'
    assert len(api['runners'])==12 and all(r['status']=='active' for r in api['runners'])
    before=old['pre_race_snapshot']['latest_api_card']
    for a,b in zip(before['runners'],api['runners'],strict=True):
        assert all(a[k]==b[k] for k in ('horse_no','horse_name','frame_no','weight_carried','official_recent_races'))
    wins=odds['odds']['win'];assert len(wins)==12
    ordered=sorted(wins,key=lambda r:(float(r['odds']),int(r['combination'][0])))
    pop={str(int(v['combination'][0])):i for i,v in enumerate(ordered,1)}
    win={str(int(v['combination'][0])):v for v in wins}
    target={k:v for k,v in card.items() if k!='runners'}
    target.update(evaluation_eligible=True,rows=[{**r,'values':{'pop':str(pop[str(int(r['horse_no']))])}} for r in card['runners']])
    cfg=read(ROOT/'configs/research/race_conditions_elizabeth_v1.json');cfg['groups']={'人気':['pop']}
    ev=group_deltas(sets['M'],target,cfg,{'half_life':None,'pooling':'hierarchical','shrinkage':20})
    forecast=candidate_prediction(ev,target,{'pattern':'M','family':'popularity','weights':[1],'scale':1})
    for i,r in enumerate(forecast['runners'],1):
        r.update(rank=i,mark=['◎','○','▲','△','△','△'][i-1] if i<=6 else '―',popularity=pop[r['horse_no']],win_odds=win[r['horse_no']]['odds'])
    assert abs(sum(r['probability_top3'] for r in forecast['runners'])-3)<1e-9
    now=datetime.now(timezone.utc);assert now<datetime.fromisoformat(card['start_at'])
    pid='jra-tospo-popularity-preliminary-20261123-'+uuid4().hex
    top=[r['horse_no'] for r in forecast['runners'][:3]]
    tickets=[]
    for bet,parts in [('wide',list(combinations(top,2))),('trio',[tuple(top)])]:
        for choice in parts:
            chosen=sorted(choice,key=int);price=observed_price(odds,bet,chosen)
            display='未取得' if price is None else str(price['odds_min'])+'〜'+str(price['odds_max']) if bet=='wide' else str(price['odds'])
            tickets.append({'bet_type':bet,'selection':chosen,'amount':100,'observed_odds':price,'observed_at':odds['fetched_at'] if price else None,'display_odds':display})
    assert all(t['observed_odds'] is not None for t in tickets)
    plan={'plan_id':pid+'-main','policy_id':'tospo-popularity-w3t1-equal100-v1','virtual_only':True,'budget':400,'tickets':tickets,
          'status':'priced','purpose':'途中人気を発走30分前の代用として用いた時点差ありの仮説'}
    result=read(base/'tokyo_sports_popularity_20261123_v1_1/summary.json')
    assert result['T30']['selection']['used']=='M'
    lines=['**人気パーツを東スポ杯の主軸候補に組み込みました。** 発走30分前の人気を使う過去検証では、従来の条件のみの方式より好走馬を多く捕捉しました。',
      '', '**今回は11/23未明の途中人気による暫定案です。発走30分前の人気で確認した予想ではありません。** 馬体重も未発表です。','',
      '## 1. レースと使用方式','',table(['項目','内容'],[['対象','2026/11/23 東京11R 東京スポーツ杯2歳S／15:30発走'],['使用方式','東スポ杯・人気パーツ参考方式'],
      ['選択理由','過去の発走30分前人気は条件のみより捕捉良好。今回の人気＋条件は人気単独への改善基準未達'],
      ['使用モデル','人気順位別の同名過去年3着内率を縮約／2003〜2025年23開催'],['予想作成時刻',jst(now.isoformat())],
      ['予想の状態','発走前・未明の途中人気を使う暫定案'],['確率の意味','未校正の3着内参考確率。単勝や組合せの確率ではない']]),'',
      '## 2. 入力データの状態','',table(['材料','観測時刻','確認結果・不足'],[['出馬表・取消',jst(api['fetched_at']),'12頭。取消なし。前日カードの馬名・枠・斤量・近走と照合'],
      ['過去走・競走条件','11/22収集','同名23開催288頭。当年12頭の20走を照合'],['馬場・馬体重',jst(api['fetched_at']),'カード上の芝は良。馬体重未発表。馬場補正は未実装'],
      ['単勝オッズ',jst(odds['fetched_at']),'未明の途中人気。発走30分前の人気ではない'],['ワイド・3連複オッズ',jst(odds['fetched_at']),'66組・220組を取得'],['補助券種オッズ','未取得','追加券種なし']]),'',
      '## 3. 全頭評価','',table(['評価順位','印','馬番・馬名','3着内参考確率','単勝オッズ・人気','市場人気との差'],[[r['rank'],r['mark'],r['horse_no']+' '+r['horse_name'],f"{r['probability_top3']:.1%}",r['win_odds']+'倍・'+str(r['popularity'])+'人気',r['popularity']-r['rank']] for r in forecast['runners']]),'',
      '参考確率は人気順位ごとの過去成績を縮約して算出。少数例のため人気順と予測順位は必ずしも一致しません。','',
      '## 4. 使用パーツと評価の根拠','',table(['条件群','今回使った条件','過去の根拠','今回の評価への影響'],[
      ['人気','発走前の単勝人気順位','同名23開催の人気ごとの3着内を集計','現在の途中人気を仮入力。主計算に使用'],
      ['基本属性','キャリア数・敗戦経験','2016〜2025年：1戦5-5-6-27','補助確認。主確率へ未加算'],
      ['前哨戦経路','前走格・距離','前走1着＋芝1800m 8-4-4-27','⑩と①が該当。⑤は前走芝2000m3着'],
      ['直近成績と間隔','前走着順・間隔','前走3着以内10-10-10-64','3頭とも前走3着以内。主確率へ未加算'],
      ['過去実績','同舞台・重賞実績','札幌2歳S公式資料を照合','⑩は札幌2歳S勝ち。①⑤は東京芝1800m勝利歴']]),'',
      '⑩は2戦2勝で前走札幌2歳S1着。①は前走東京芝1800m未勝利1着。⑤は東京芝1800m新馬1着後、芙蓉S3着。⑧は前走アイビーS2着で東京芝1800m好走歴があります。',
      '', '発走30分前を使った2016〜2020年の上位3捕捉は、人気方式2.0頭／開催、従来方式1.2頭。2021〜2025年は1.8頭対1.0頭。探索済み過去データで、利益や未来の改善を実証したものではありません。','',
      '## 5. 市場比較と採否','',table(['対象馬','モデル評価','市場評価','扱い','理由'],[[r['horse_no']+' '+r['horse_name'],str(r['rank'])+'位・'+f"{r['probability_top3']:.1%}",r['win_odds']+'倍・'+str(r['popularity'])+'人気','仮想主案に含める' if r['rank']<=3 else '主案外','人気パーツの計算順位。固有条件は補助確認'] for r in forecast['runners'] if r['rank']<=3 or r['horse_no']=='8']),'',
      '## 6. 主案の検証用仮想買い目','',f"主案ID：{plan['plan_id']}／規則：{plan['policy_id']}／評価対象：この主案1つ",'',
      table(['券種','組合せ','実オッズ','仮想金額','採用理由'],[['ワイド' if t['bet_type']=='wide' else '3連複','－'.join(t['selection']),t['display_odds']+'倍','100円','人気パーツ上位3頭の仮想検証'] for t in tickets]),'',
      f"仮想合計400円・実購入0円。観測：{jst(odds['fetched_at'])}。組合せ確率・期待値は未計算。",'',
      '## 7. 補助案・追加仮説','',table(['案ID','券種・組合せ','実オッズ','仮想金額','仮説・根拠','評価上の扱い'],[['旧前日案','ワイド1-8/2-8/1-2、3連複1-2-8','旧予想を参照','400円','条件のみの前日案','旧IDで独立評価。主案に非合算']]),'',
      '## 8. 保存状況','',table(['項目','状態'],[['予想ID',pid],['主案・入力・表示全文','新IDでSQL保存・全文読戻し照合済み。旧予想を保持'],['事前保存の確認','発走前・当日未明の途中人気。対象結果未取得'],['自動評価の対応','独自ワイド・3連複は未接続。結果後に別途精算']]),'',
      '## 9. 結果検証','',table(['評価項目','結果'],[['公式結果・払戻','未確定・未取得'],['モデル評価と実際の3着内馬','未確定'],['主案：仮想購入額・払戻・回収率','仮想400円、払戻・回収率未確定'],['券種別的中・トリガミ','未確定'],['補助仮説','旧前日案は別枠評価']]),'',
      '## 10. 断層競馬の独立参考','','未判定。本体へ混入していません。','']
    presentation='\n'.join(lines)
    prediction={'method_selection':{'method':'condition_parts','source':'explicit_request','reason':'人気パーツを同名重賞で検証し導入','model':'tospo-t30-popularity-provisional-v1'},
      'selected_model':{'model_id':'tospo-t30-popularity-provisional-v1','training_start':'2003-01-01','training_end':'2025-12-31','usage':'exploratory_provisional','purchase_allowed':False},
      'probability_kind':'uncalibrated_top3_marginals','condition_parts_forecast':forecast,'condition_parts_evidence':ev,'condition_parts_plan':plan,
      'condition_parts_alternatives':[],'popularity_backtest':result,'previous_forecast_id':old['prediction_id'],
      'input_state':{'card_observed_at':api['fetched_at'],'odds_observed_at':odds['fetched_at'],'odds_timing':'early_morning_not_t30','body_weight':'unpublished','going':api.get('track_condition_label'),'going_in_model':False},
      'predicted_top3':[],'finish_order_prediction_available':False,'axis_horse_numbers':[top[0]],'opponent_horse_numbers':top[1:],
      'generated_before_result':True,'reconstruction_after_result':False,'presentation':{'text':presentation,'template_version':'condition-parts-output-v1'}}
    payload={'prediction_id':pid,'race_id':card['race_key'],'theory_version':'tospo-t30-popularity-provisional-v1','mode':'condition_parts','budget':0,'created_at':now.isoformat(),
      'pre_race_snapshot':{'card':card,'latest_api_card':api,'odds':odds,'historical_popularity_audit':audits},'prediction_json':prediction,'prediction_tickets':[]}
    for name,value in [('payload',payload),('prediction',prediction)]:
        (out/(name+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    (out/'presentation.md').write_text(presentation,encoding='utf-8')
    (out/'manifest.json').write_text(json.dumps({'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}},indent=2),encoding='utf-8')
    print(json.dumps({'prediction_id':pid,'top3':top,'prices':[t['display_odds'] for t in tickets]},ensure_ascii=False))


if __name__=='__main__':main()
