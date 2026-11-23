"""概要: 東スポ杯の固定研究結果から全頭根拠とスキル10節の前日予想を作る。
作成日: 2026-11-22
入力: 検証済み研究成果物、公式当年入力、観測済み価格、公式資料。
出力: 新規予想payload、全頭根拠、主案と別仮説、表示本文、SHA。
実行例: uv run python scripts/finalize_tokyo_sports_forecast.py
注意事項: SQL保存は既存スキル補助へ渡す。実購入なし。改善未確認を表示する。
"""

from datetime import datetime, timezone, timedelta
import hashlib
from itertools import combinations
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
from run_jra_graded_live import observed_price, table
from jra_srb.jra_tokyo_sports_patterns import rule_catalogue, MAIN


def read(path: Path) -> object:
    """UTF-8 JSONを読む。"""
    return json.loads(path.read_text(encoding='utf-8'))


def save(path: Path, value: object) -> None:
    """丸め前の構造化値をUTF-8 JSONで保存する。"""
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def jst(value: str) -> str:
    """観測時刻を日本時間へ変換する。"""
    return datetime.fromisoformat(value.replace('Z','+00:00')).astimezone(timezone(timedelta(hours=9))).strftime('%m/%d %H:%M:%S JST')


def main() -> None:
    """全頭・価格・根拠を同じ保存値から生成し、元予想を上書きしない。"""
    research=ROOT/'artifacts/jra_research/tokyo_sports_patterns_20261122_v1'
    inputs=ROOT/'artifacts/jra_research/tokyo_sports_collect_20261122_v1_1'
    latest=ROOT/'artifacts/jra_research/tokyo_sports_final_20261122_inputs'
    output=ROOT/'artifacts/jra_research/tokyo_sports_forecast_20261122_v1';output.mkdir(exist_ok=False)
    card=read(inputs/'normalized-card.json');api=read(latest/'card.json');odds=read(latest/'odds.json')
    initial=read(inputs/'api-card.json');rationales=read(research/'live-rationales.json');forecast=read(research/'live-selected.json')
    summary=read(research/'summary.json');capture=read(ROOT/'artifacts/jra_research/tokyo_sports_selection_capture_20261122_v2/selection.json')
    conditions=read(research/'records.json');official=read(ROOT/'artifacts/jra_research/tokyo_sports_official_context_20261122_v1/records.json')
    assert api['race_id']==odds['race_id']==card['race_key']=='202611230511'
    assert len(api['runners'])==12 and all(r['status']=='active' for r in api['runners'])
    for a,b in zip(initial['runners'],api['runners'],strict=True):
        for k in ('horse_no','horse_name','frame_no','weight_carried','official_recent_races'):assert a[k]==b[k],k
    now=datetime.now(timezone.utc);assert now<datetime.fromisoformat(card['start_at'])
    assert forecast['pattern']==summary['selection']['used_pattern']==capture['used_pattern']=='general'
    pid='jra-tokyo-sports-reference-20261123-'+uuid4().hex
    win={str(int(r['combination'][0])):r for r in odds['odds']['win']}
    pop={h:i for i,h in enumerate(sorted(win,key=lambda h:(float(win[h]['odds']),int(h))),1)}
    rows=[]
    for i,r in enumerate(forecast['runners'],1):
        mark=['◎','○','▲','△','△','△'][i-1] if i<=6 else '―'
        rows.append({**r,'rank':i,'mark':mark,'win_odds':win[r['horse_no']]['odds'],'popularity':pop[r['horse_no']]})
    forecast={**forecast,'runners':rows}
    ev=read(research/'live-evidence.json')['general']
    for r in rationales:r['used_group_evidence']=next(x for x in ev if x['horse_id']==r['horse_id'])
    def ticket(bet,selection,amount):
        """指定組の実観測価格を保持し、価格欠測は採用保留へ分ける。"""
        chosen=sorted(map(str,selection),key=int);price=observed_price(odds,bet,chosen)
        shown='未取得' if price is None else str(price['odds_min'])+'〜'+str(price['odds_max']) if bet=='wide' else str(price['odds'])
        return {'bet_type':bet,'selection':chosen,'amount':amount,'observed_odds':price,'observed_at':odds['fetched_at'] if price else None,'display_odds':shown}
    top=[r['horse_no'] for r in rows[:3]]
    plan={'plan_id':pid+'-main','policy_id':'tospo-reference-w3t1-equal100-v1','virtual_only':True,'budget':400,
        'tickets':[ticket('wide',pair,100) for pair in combinations(top,2)]+[ticket('trio',top,100)],
        'status':'priced','purpose':'改善未確認の同名集計参考順位を前日固定する検証主案'}
    assert all(t['observed_odds'] is not None for t in plan['tickets'])
    alternative={'plan_id':pid+'-market10','policy_id':'tospo-market10-rescue-trio-v1','virtual_only':True,'budget':100,
        'tickets':[ticket('trio',['1','8','10'],100)],'included_in_main':False,
        'hypothesis':'市場1番人気10を、札幌2歳S勝利・全勝・主要4条件該当と公式資料で補助確認し、主案の2に代える別仮説。過去の買い目優位は未検証。'}
    def record(key,period='recent10',match='matched'):
        """検証済み条件の四区分成績だけを表示する。"""
        r=next(r for r in conditions if r['id']==key)
        return '-'.join(map(str,r['periods'][period][match]['record']))
    rationale_lines=['# 東京スポーツ杯2歳S 全頭根拠','',
        '使用計算：一般14特徴を同名23開催だけで集計した参考方式。固有候補の採用基準未達。固有28条件と公式資料は補助。点数や確率へ後付け加算しない。','']
    for r in rationales:
        p=next(p for p in rows if p['horse_id']==r['horse_id']);previous=r['previous']
        rationale_lines += [f"## {p['rank']}位 {p['mark']}{r['horse_no']} {r['horse_name']}",'',
            f"3着内参考{p['probability_top3']:.6%}。{r['career_count_observed']}走（新馬からの収録確認={r['career_complete']}）。前走{previous['race_name'] or r['values']['prep_class']}・{previous['distance']}m・{previous['rank']}着、{r['gap_days']}日。",'',
            '|条件|該当|直近10年の該当群成績|','|---|---|---|']
        for rule in rule_catalogue():rationale_lines.append(f"|{rule['label']}|{'不明' if r['rules'][rule['id']] is None else '該当' if r['rules'][rule['id']] else '非該当'}|{record(rule['id'])}|")
        rationale_lines += ['', '|使用した群|差分（確率ポイントではない）|','|---|---:|']
        for group,delta in zip(r['used_group_evidence']['evidence'],r['used_group_evidence']['deltas'],strict=True):
            rationale_lines.append(f"|{group['group']}|{delta:+.8f}|")
        rationale_lines += ['','根拠の各項目支持数・縮約率はlive-evidence.json、当該日前の参照走はlive-rationales.json。','']
    (output/'human-rationale.md').write_text('\n'.join(rationale_lines),encoding='utf-8')
    sha=hashlib.sha256((ROOT/'configs/research/race_conditions_elizabeth_v1.json').read_bytes()).hexdigest()
    lines=['**マイルCSは回顧を凍結してクローズしました。東スポ杯は検証・前日参考予想・SQL保存まで完了しています。**','',
        '**ただし、固有パーツ追加による精度向上は確認できませんでした。** 計算上の参考順位は◎8コラリオン、○1ダノンダックス、▲2シルヴァノーブル。⑩ショウナンガレオンを含める案は別仮説として保存します。','',
        '使用方式：条件パーツ研究／選択理由：今回の明示指示／モデル：東スポ杯同名集計の一般特徴参考方式。frozen_v2やマイルCS専用モデルではありません。','',
        '## 1. レースと使用方式','',table(['項目','内容'],[
            ['対象','2026/11/23 東京11R 東京スポーツ杯2歳S／202611230511／15:30発走'],['使用方式','同名レース固有パターン研究・前日参考案'],
            ['選択理由','固有候補2選択方法が採用基準未達。同名過去年だけで集計した一般特徴を参考順位に使用'],
            ['使用モデル',f'tospo-same-race-general-reference-v1／2003〜2025年23開催／設定SHA {sha[:12]}'],
            ['予想作成時刻',jst(now.isoformat())],['予想の状態','発走前・前日版。改善未確認・購入推奨としての採用なし'],['確率の意味','3着内参考確率・未校正。勝率や組合せ確率ではない']]),'',
        '## 2. 入力データの状態','',table(['材料','観測時刻','確認結果・不足'],[
            ['出馬表・取消',jst(api['fetched_at']),'12頭。公式ID・2024年生・枠・斤量・近走20走を照合。取得時点で取消なし'],
            ['過去走・競走条件','11/22取得','同名23開催288頭・事前履歴678走。RA617競走照合。当年20走はRA16走＋公式ヘッダー4走で確認'],
            ['馬場・馬体重',jst(api['fetched_at']),'翌日レースにつき未発表。モデルへの補正も未実装'],
            ['単勝オッズ',jst(odds['fetched_at']),'前日途中オッズ12頭。最終人気ではない'],
            ['ワイド・3連複オッズ',jst(odds['fetched_at']),'66組・220組。対象組の実価格取得'],
            ['補助券種オッズ','未取得','馬連・3連単の案なし']]),'',
        '## 3. 全頭評価','',table(['評価順位','印','馬番・馬名','3着内参考確率','単勝オッズ・人気','市場人気との差'],[
            [r['rank'],r['mark'],r['horse_no']+' '+r['horse_name'],f"{r['probability_top3']:.1%}",r['win_odds']+'倍・'+str(r['popularity'])+'人気',r['popularity']-r['rank']] for r in rows]),'',
        '**上位2頭の差は約0.02ポイントで、12頭全体でも23.0〜26.5%です。明確に強い軸を選べた状態ではありません。** 人気との差は順位差であり期待値ではありません。','',
        '## 4. 使用パーツと評価の根拠','',table(['条件群','今回使った条件','過去の根拠','今回の評価への影響'],[
            ['基本属性','一般計算：年齢・枠。固有キャリアは補助',f"新馬から1戦＝{record('career1')}／3戦以内＝{record('career_le3')}（不明3頭別）",'全頭2歳のため年齢では差がつかない。キャリアは採用スコアへ未統合'],
            ['前哨戦経路','一般計算：前走の確認済み格・条件・競走名。固有経路は補助',f"前走1着＋芝1800＝{record('prev_win&prev1800')}",'1/4/6/7/10が該当。8は前走OP2着で非該当だが一律消去しない'],
            ['直近成績と間隔','一般計算：前走着順・間隔',f"前走1着＝{record('prev_win')}／前走3着以内＝{record('prev_top3')}",'1/2は50日、8は37日。29〜56日群などの縮約値を反映'],
            ['条件変更','一般計算：距離帯・距離変更・斤量変更','同名23年の各カテゴリ支持数と縮約率を全頭保存','8/1は1800同距離、2は2000から短縮'],
            ['過去実績','一般計算：同舞台・重賞実績など。official_materialsは補助',f"東京芝1800好走＝{record('tokyo1800_top3')}／重賞3着内＝{record('graded_top3')}",'8/1/5の同舞台を確認。10の重賞勝利は一般特徴で反映。公式時計・ラップを別加点しない']]),'',
        '成績は1着－2着－3着－着外、表は2016〜2025年の直近10開催。条件単独の成績を馬や買い目の確率へ転用しません。','',
        '**◎8 コラリオン**：アイビーS2着、37日ぶり、2戦とも3着以内。東京芝1800mの好走を持ち、前走OP以上3着以内〔'+record('prev_open_top3')+'〕に該当。前走勝利条件からは外れます。','',
        '**○1 ダノンダックス**：東京芝1800m未勝利1着、50日ぶり、2戦とも連対。前走勝利×1800mを満たします。未勝利からの格上挑戦で、8との差は僅かです。','',
        '**▲2 シルヴァノーブル**：東京芝2000mの新馬1着、50日ぶり。1戦で底を見せていませんが、1800m実績は未確認。前走1800m勝利の強い傾向には非該当です。','',
        '**⑩ショウナンガレオンは消しません。** 2戦2勝・札幌2歳S1着で主要4条件すべて該当。official_materialsの固定採用値で札幌戦1:50.3、上がり35.9秒を照合。③との同一レース時計差は1.3秒。札幌の稍重と東京の適性差は未検証で、過去の好条件を今回の保証にしません。','',
        f"**割引条件の反例も保存**：前走3着以内の非該当群は直近10年{record('prev_top3',match='unmatched')}。③は該当しますが、過去23年には好走例があり絶対消去にしません。",'',
        '**検証結果**：32候補＋2基準×18年＝612予測、単独14・AND12・救済OR2＝28条件。開発で選んだ近況S04は確認5年のBrierが約3.5%改善した一方、上位3捕捉は1.20→1.07頭／開催。捕捉優先のS12も0.90頭で未達。後続2021〜2025は選択し直さず監査しました。利益の改善は未検証です。','',
        '[JRA公式傾向分析](https://www.jra.go.jp/keiba/race/106/data.html)を参照しました。公表期間を既に見た探索であり、独立した将来精度の証明ではありません。',
        f"[28条件の検証]({research.as_posix()}/report.md)／[全12頭の該当・非該当・根拠]({output.as_posix()}/human-rationale.md)。",'',
        '## 5. 市場比較と採否','',table(['対象馬','モデル評価','市場評価','扱い','理由'],[
            ['10 ショウナンガレオン','8位・24.9%','1.9倍・1人気','主案外・別仮説に含める','重賞勝利・全勝・主要4条件を確認。市場との大きな差を保留事項として保存'],
            ['8 コラリオン','1位・26.5%','13.9倍・6人気','計算主案に含める','OP好走・同舞台・間隔。割安や期待値は未証明'],
            ['1 ダノンダックス','2位・26.5%','6.3倍・2人気','計算主案に含める','同舞台勝利と近況'],
            ['2 シルヴァノーブル','3位・25.6%','20.8倍・7人気','計算主案に含める','新馬勝利と間隔。距離実績は課題']]),'',
        '市場は計算順位を変更する材料にせず、10を含める仮説を別案に分けました。今回の研究で購入に耐える確度向上を確認したとは判断していません。','',
        '## 6. 主案の検証用仮想買い目','',f"主案ID：{plan['plan_id']}／規則：{plan['policy_id']}／評価対象：この主案1つ",'',
        table(['券種','組合せ','実オッズ','仮想金額','採用理由'],[['ワイド' if t['bet_type']=='wide' else '3連複','－'.join(t['selection']),t['display_odds']+'倍','100円','参考計算上位3頭を固定して検証'] for t in plan['tickets']]),'',
        f"主案合計：仮想400円／価格観測：{jst(odds['fetched_at'])}。実購入0円。組合せ確率・期待値は未計算。",'',
        '## 7. 補助案・追加仮説','',table(['案ID','券種・組合せ','実オッズ','仮想金額','仮説・根拠','評価上の扱い'],[
            [alternative['plan_id'],'3連複1－8－10',alternative['tickets'][0]['display_odds']+'倍','100円','2を市場1番人気10へ代える。札幌重賞勝利・主要4条件で補助確認','主案に非合算・別検証']]),'',
        '単勝・3連単の着順指定は作りません。補助案の的中を主案の的中へ足しません。','',
        '## 8. 保存状況','',table(['項目','状態'],[
            ['予想ID',pid],['主案・入力・表示全文','新IDでSQL保存・全文読戻し照合済み。旧研究を保持'],['事前保存の確認','11/23発走前・前日保存。対象結果未取得'],['自動評価の対応','独自ワイド・3連複主案は共通自動評価未接続。結果後に固定主案を明示精算']]),'',
        '## 9. 結果検証','',table(['評価項目','結果'],[
            ['公式結果・払戻','未確定・未取得'],['モデル評価と実際の3着内馬','未確定'],['主案：仮想購入額・払戻・回収率','400円、払戻・回収率未確定'],['券種別的中・トリガミ','未確定'],['補助仮説','別枠100円、結果未確定']]),'',
        '## 10. 断層競馬の独立参考','', '未判定。本体の印・確率・買い目へ混入していません。','']
    presentation='\n'.join(lines)
    prediction={'method_selection':{'method':'condition_parts','source':'explicit_request','reason':'同名固有研究と予想組立ての明示指示','model':'tospo-same-race-general-reference-v1'},
        'selected_model':{'model_id':'tospo-same-race-general-reference-v1','pattern':'general','config_sha256':sha,'training_start':'2003-01-01','training_end':'2025-12-31','research_status':'exploratory_reference_no_specific_improvement_confirmed','purchase_allowed':False},
        'research_selection':summary['selection'],'capture_selection_comparison':capture,'probability_kind':'uncalibrated_top3_marginals',
        'condition_parts_forecast':forecast,'condition_parts_evidence':ev,'horse_rationales':rationales,'condition_parts_plan':plan,
        'condition_parts_alternatives':[alternative],'official_materials':{'used_in_score':False,'coverage':'札幌2歳Sの成績9頭・ラップ9・個別位置36・文章8、条件1','fixed_records':official,
            'identity_links':read(ROOT/'artifacts/jra_research/tokyo_sports_official_facts_20261122_v1/links.json'),'sealed_prediction_snapshot_available':False},
        'input_state':{'card_observed_at':api['fetched_at'],'odds_observed_at':odds['fetched_at'],'runners':12,'history_rows':20,'body_weight':'not_announced','going':'not_announced'},
        'predicted_top3':[],'finish_order_prediction_available':False,'axis_horse_numbers':[top[0]],'opponent_horse_numbers':top[1:],
        'generated_before_result':True,'reconstruction_after_result':False,'presentation':{'text':presentation,'template_version':'condition-parts-output-v1'}}
    payload={'prediction_id':pid,'race_id':card['race_key'],'theory_version':'tospo-same-race-general-reference-v1','mode':'condition_parts','budget':0,'created_at':now.isoformat(),
        'pre_race_snapshot':{'card':card,'latest_api_card':api,'profile_history':read(inputs/'profile-history.json'),'normalized_history':read(inputs/'normalized-history.json'),'input_audit':read(inputs/'input-audit.json'),'odds':odds},
        'prediction_json':prediction,'prediction_tickets':[]}
    save(output/'payload.json',payload);save(output/'prediction.json',prediction)
    (output/'presentation.md').write_text(presentation,encoding='utf-8')
    save(output/'manifest.json',{'generated_at':now.isoformat(),'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()},'sources':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path(__file__),research/'manifest.json',inputs/'manifest.json',latest/'card.json',latest/'odds.json']}})
    print(json.dumps({'prediction_id':pid,'top3':top,'plan_odds':[t['display_odds'] for t in plan['tickets']],'alternative':alternative['tickets'],'research_improvement_confirmed':False},ensure_ascii=False))


if __name__=='__main__':main()
