"""概要：固定10案の保存買い目を独立再計算し、採用判断と比較結果をまとめる。
作成日：2026-10-02
入力：report.json、tickets.jsonl、前回基準買い目、読み取り専用の既存払戻。
出力：RESULTS.md、comparison.json、verification.jsonの追加確認、NEXT.md。
実行例：uv run python .workstate/jra-srb/tipster-chimera-pair-v3/finalize_stable.py
注意事項：再学習・新規データ取得・購入・ライブ採用は行わない。外部通信なし。
"""
from collections import defaultdict
from pathlib import Path
import ast
import json
import sys
import numpy as np
from threadpoolctl import threadpool_limits
import evaluate_stable as study

OUT = Path(__file__).resolve().parent


def read_lines(path):
    """UTF-8の保存済みJSON Linesを読み込む。"""
    with path.open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def percentage(value):
    """割合を結果表の百分率表示に変換する。"""
    return f'{100*value:.2f}%' if value is not None else '購入なし'


def paired_difference(actual,baseline):
    """同じレース・投資額での日別回収率差と集中度を再計算する。

    Args:
        actual: 新案の保存買い目。
        baseline: 同一購入レースの前回基準買い目。
    Returns:
        回収率差の日単位bootstrap区間、最大払戻占有率と差額寄与。
    Notes:
        区間は多重探索を補正していない。最大払戻除外は採用必須条件ではない。
    """
    daily = defaultdict(lambda:np.zeros(3))
    race_return = defaultdict(int)
    baseline_return = defaultdict(int)
    for t in actual:
        daily[t['race_date']][0] += t['stake_yen']
        daily[t['race_date']][1] += t['return_yen']
        race_return[t['race_id']] += t['return_yen']
    for t in baseline:
        daily[t['race_date']][2] += t['return_yen']
        baseline_return[t['race_id']] += t['return_yen']
    if not daily:
        return dict(difference_ci_95=None,max_race_return_share=None,positive_return_difference_top1_share=None)
    a = np.asarray(list(daily.values()))
    rng = np.random.default_rng(2026)
    sample = a[rng.integers(0,len(a),size=(3000,len(a)))].sum(axis=1)
    difference = (sample[:,1]-sample[:,2])/sample[:,0]
    returned = sum(race_return.values())
    largest = max(race_return.values())
    positive_changes = [max(0,value-baseline_return.get(rid,0)) for rid,value in race_return.items()]
    positive_total = sum(positive_changes)
    return dict(difference_ci_95=np.quantile(difference,[.025,.975]).tolist(),
                max_race_return_share=largest/returned if returned else None,
                positive_return_difference_top1_share=max(positive_changes)/positive_total if positive_total else None)


def main():
    """元払戻と買い目を再照合し、後続期間で候補を入れ替えず採用判断を記録する。"""
    sys.stdout.reconfigure(encoding='utf-8')
    report = json.loads((OUT/'report.json').read_text(encoding='utf-8'))
    tickets = read_lines(OUT/'tickets.jsonl')
    rows,meta,_,input_hashes,_ = study.v2.previous.build_rows()
    assert input_hashes==report['input_sha256']
    assert study.v2.sha256(study.OLD/'tickets.jsonl')==report['baseline_sha256']
    assert study.v2.sha256(OUT/'models.joblib')==report['model_sha256']
    # 生成プログラムの選択や集計関数を使用せず、日付・ペア・払戻を別に照合する。
    totals = defaultdict(lambda:[0,0,set()])
    budgets = defaultdict(int)
    for t in tickets:
        r = meta[t['race_id']]
        assert t['race_date']==r['race_date'] and t['period']==study.period(t['race_date'])
        payout = r['wide_payout'] if t['kind']=='wide' else r['quinella_payout']
        expected = payout.get(tuple(t['pair']),0)*t['stake_yen']//100
        assert t['return_yen']==expected
        value = totals[(t['trial'],t['period'])]
        value[0] += t['stake_yen']
        value[1] += expected
        value[2].add(t['race_id'])
        budgets[(t['trial'],t['race_id'])] += t['stake_yen']
    assert all(value==600 for value in budgets.values())
    for (trial,period),(stake,returned,races) in totals.items():
        value = report['results'][trial][period]['actual']
        assert value['stake_yen']==stake and value['return_yen']==returned and value['races']==len(races)
    previous = study.baseline_tickets()
    comparison = {}
    for trial,result in report['results'].items():
        part = [t for t in tickets if t['trial']==trial and t['period'].startswith('confirmation')]
        kind = 'wide' if trial in ['S06','S07','S09','S10'] else 'quinella'
        ids = {t['race_id'] for t in part}
        baseline = [t for t in previous if t['race_id'] in ids and t['kind']==kind]
        comparison[trial] = paired_difference(part,baseline)
    study.save('comparison.json',comparison)
    verification = json.loads((OUT/'verification.json').read_text(encoding='utf-8'))
    verification.update(independent_reloaded_payout_checks=len(tickets),period_accounts_recomputed=True,
                        baseline_and_model_hashes_unchanged=True)
    docs = {}
    for path in OUT.glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        docs[path.name] = bool(ast.get_docstring(tree)) and all(ast.get_docstring(n) for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.ClassDef,ast.AsyncFunctionDef)))
    assert all(docs.values())
    verification['new_python_docstring_audit'] = docs
    study.save('verification.json',verification)
    text = ['# 欠測差を抑えた共同確率：固定10案の結果','',
            '作成日：2026-10-02。現在あるデータのみ使用。予測時点T-30、夏6～8月は除外。', '',
            '## 今回変えたこと','',
            '- 学習を2025年9月まで延ばし、10月で校正。2025年11～12月で候補選択。2026年1～2月・3～5月で確認。',
            '- 内容列は学習・校正の双方で観測率30%以上のものに限定。評価期の結果や欠測率では列を選ばない。',
            '- 内容の観測が少ないペアは既存履歴の市場補正へ戻す。両馬に既存履歴がないペアは市場へ戻す混合を比較。',
            '- 新案が実際に買ったレースに、前回選択候補の買い目を揃えて比較。各レースの予算600円。',
            '- 各期間100%以上、最大払戻除外後の黒字、将来追加100レースの黒字は採用の必須条件にしない。','',
            '予想家の「能力」「内容の不利」「条件」「軸と相手」「価格」の観点を数値代理変数へ落とした継続研究。本人の完全再現ではない。稼働中取得・ライブモデルには反映していない。2026年を含む今回の期間は既存研究で参照済みで、独立した未使用テストではない。','',
            '## 分割','', '| 区間 | レース数 |','|---|---:|']
    for period,count in report['period_counts'].items():
        text.append(f'| {period} | {count} |')
    text += ['',f"2025年のみの最近学習は{report['recent_training_races']}レース。2025年3～8月等の元データ欠測は補っていない。母集団は、8頭以上・障害除外・整合したワイドと馬連払戻があるレース。",'',
             '## 回収率と同一対象の既存案との差','',
             '基準は前回開発期間で選択したP03（馬連）・P09（ワイド）。確認合算の差は、各案と同じ購入レース・予算での比較。1点案は600円、2点案は各300円。','',
             '| 案 | 券種 | 開発11～12月 | 確認1～2月 | 確認3～5月 | 確認合算 | 同一対象の既存案 | 差（pt） | 件数 |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for trial,values in report['results'].items():
        kind = 'ワイド' if trial in ['S06','S07','S09','S10'] else '馬連'
        combined = values['confirmation_combined']
        cells = [percentage(values[p]['actual']['roi']) for p in ['development','confirmation_early','confirmation_late','confirmation_combined']]
        difference = combined['roi_difference']
        text.append(f'| {trial} | {kind} | '+' | '.join(cells)+f" | {percentage(combined['matched_baseline']['roi'])} | {difference*100:+.2f} | {combined['actual']['races']} |" if difference is not None else f'| {trial} | {kind} | '+' | '.join(cells)+' | 購入なし | — | 0 |')
    text += ['', '## 開発期間で選んだ候補と判断','']
    decisions = {}
    for kind,trial in report['development_selected'].items():
        text += [f'### {kind}: {trial}','']
        if trial is None:
            decisions[kind] = '候補なし'
            continue
        result = report['results'][trial]['confirmation_combined']
        actual = result['actual']
        if actual['roi'] is not None and actual['roi']>1:
            decision = '少額試験採用の検討候補。実運用収益が保証されたという意味ではない。'
        elif result['roi_difference'] is not None and result['roi_difference']>0:
            decision = '予想モデルの改善候補として保持。確認合算は赤字で、購入手法の黒字は未確認。'
        else:
            decision = '前回案に対する改善は確認できず、採用は保留。'
        decisions[kind] = decision
        ci = comparison[trial]['difference_ci_95']
        concentration = comparison[trial]['max_race_return_share']
        text += [decision,'',
                 f"- 確認合算：{actual['races']}レース、投資{actual['stake_yen']:,}円、払戻{actual['return_yen']:,}円、損益{actual['profit_yen']:+,}円。",
                 f"- 同じ対象での前回案との差：{result['roi_difference']*100:+.2f}pt。日単位bootstrap 95%区間：{ci[0]*100:+.2f}～{ci[1]*100:+.2f}pt。" if ci else '- 比較対象なし。',
                 f'- 最大払戻レースの占有率：{percentage(concentration)}。極端な的中依存の診断であり、除外後黒字を必須にはしていない。','']
    study.save('adoption_decision.json',dict(development_selected=report['development_selected'],decisions=decisions,live_adopted=False))
    same_probability = report['results']['S05']['confirmation_combined']['actual']
    price_policy = report['results']['S08']['confirmation_combined']['actual']
    same_ids = {t['race_id'] for t in tickets if t['trial']=='S05' and t['period'].startswith('confirmation')}
    price_ids = {t['race_id'] for t in tickets if t['trial']=='S08' and t['period'].startswith('confirmation')}
    assert same_ids==price_ids
    text += ['## 同じ確率モデルで買い方だけを比較','',
             f"S05とS08は同じ欠測対応モデルの確率を使用。確認期間の購入レース集合と総予算も同じ。確率上位を買うS05は{percentage(same_probability['roi'])}、価格も掛け合わせるS08は{percentage(price_policy['roi'])}で、差は{(price_policy['roi']-same_probability['roi'])*100:+.2f}pt。今回の範囲では、モデルを変えず買い目の選び方だけを変える改善が見られた。",'',
             f"ただし的中率はS05の{percentage(same_probability['hits']/same_probability['races'])}からS08の{percentage(price_policy['hits']/price_policy['races'])}へ下がる。S08は当たりやすさより払戻を重視する買い方であり、改善の統計的不確実性も残る。",'',
             '## 特徴量と確率精度','',
             '市場7列＋履歴の和・差30列が基礎。内容は学習・校正の観測率で選択。列番号はreport.json、列名の対応はfeature_names.jsonに記録。','']
    for name,value in report['feature_selection'].items():
        text.append(f"- {name}: 元{len(value['train_observed'])}列から{len(value['kept_columns'])}列を採用（補完後の欠測指標追加前）。")
    text += ['', '馬連はレース平均対数損失、ワイドはレース平均ペアBrier。小さいほどよい。','',
             '| モデル | 開発 | 確認1～2月 | 確認3～5月 |','|---|---:|---:|---:|']
    for name in report['quality']['development']:
        text.append('| '+name+' | '+' | '.join(f'{report["quality"][p][name]:.6f}' for p in ['development','confirmation_early','confirmation_late'])+' |')
    text += ['', '馬連の市場補正に掛ける校正係数：','']
    for name,alpha in report['calibration'].items():
        text.append(f'- {name}: {alpha:.6f}')
    text += ['', '## 解釈上の制約','',
             '今回も新たな10案を比較しているため多重探索の影響がある。候補は開発期間で固定し、確認結果で入れ替えていない。今回の区間は以前にも研究済みで、前向き運用の実績ではない。過去出馬表・発走時刻の当時検証不足と後日再構成オッズの問題は残る。','',
             'S08の期待払戻上位選択は100%以上の期待値を保証しない。S09の市場との差は的中確率の差であり、T-30ワイド価格がないため割安な買い目を特定した証拠にはならない。','',
             '次回は今回選択した候補と確認結果を起点にする。確認期間で偶然良かった別案を、今回の正式選択候補として扱わない。条件の後付けによる結果改善は行わない。','',
             '## 検証','',
             f"- {verification['mutation_checks']:,}回の購入選択で、対象結果・払戻・偽T-10を加えても予測・買い目が不変。",
             f'- 保存買い目{len(tickets):,}点を再読込した元払戻と独立照合。',
             '- 全購入レース600円、期間会計、比較対象の投資一致、入力・基準買い目・モデルのハッシュを確認。',
             '- 新規スクリプトの日本語説明ヘッダー・全関数docstringを確認。',
             '- uv run、既存NumPy/SciPy/scikit-learn/joblib/threadpoolctlを使用。依存追加なし。2スレッド制限。','']
    base_names = ['log_o1_PL_pair','log_o2_over_o1_PL_pair','min_o1_share','max_o1_share','log_o1_share_difference','field_size_over18','o2_pair_available']
    names = [*base_names,*['sum_'+k for k in study.v2.previous.HISTORY_KEYS],*['abs_difference_'+k for k in study.v2.previous.HISTORY_KEYS],
             *['sum_'+k for k in study.v2.previous.CONTENT_NAMES],*['abs_difference_'+k for k in study.v2.previous.CONTENT_NAMES],
             *['sum_'+k for k in study.v2.previous.CONDITION_NAMES],*['abs_difference_'+k for k in study.v2.previous.CONDITION_NAMES],
             'both_front','different_front','both_front_x_front_density']
    assert all(len(names)==len(value['train_observed']) for value in report['feature_selection'].values())
    study.save('feature_names.json',dict(all_columns=names,selected={key:[names[i] for i in value['kept_columns']] for key,value in report['feature_selection'].items()}))
    (OUT/'RESULTS.md').write_text('\n'.join(text),encoding='utf-8')
    (OUT/'NEXT.md').write_text('# 再開地点\n\n固定10案の学習・同一対象比較・独立会計確認が完了。RESULTS.md、adoption_decision.json、report.jsonを読む。候補は開発期間だけで選択済み。確認結果で候補を交換しない。ライブ採用なし。\n\n次の研究は別契約に保存し、今回の結果は上書きしない。各期間100%以上や最大払戻除外後の黒字を再び必須条件にしない。\n',encoding='utf-8')
    print(json.dumps(dict(selected=report['development_selected'],decisions=decisions,verified_tickets=len(tickets)),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    with threadpool_limits(limits=2):
        main()
