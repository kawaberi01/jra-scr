"""概要：保存済み買い目の会計と確率精度を確認し、検証結果をまとめる。
作成日：2026-10-02
入力：report.json、tickets.jsonl、predictions.jsonl、元データの読み取り専用再読込。
出力：quality.json、feature_coverage.json、RESULTS.md、NEXT.md、検証記録。
実行例：uv run python .workstate/jra-srb/tipster-chimera-pair-v2/finalize.py
注意事項：学習や条件の変更は行わない。外部通信なし。元データは変更しない。
"""
from collections import defaultdict
import json
from pathlib import Path
import numpy as np
from threadpoolctl import threadpool_limits
import evaluate_pairs as research

OUT = Path(__file__).resolve().parent


def load_lines(name):
    """保存済みUTF-8 JSON Linesを読み込む。"""
    with (OUT/name).open(encoding='utf-8') as stream:
        return [json.loads(line) for line in stream if line.strip()]


def percentage(value):
    """割合を表表示用の百分率に変換する。"""
    return f'{value*100:.2f}%' if value is not None else '購入なし'


def main():
    """結果を再学習せず、元払戻と保存買い目の照合および期間別精度を集計する。"""
    report = json.loads((OUT/'report.json').read_text(encoding='utf-8'))
    tickets = load_lines('tickets.jsonl')
    predictions = load_lines('predictions.jsonl')
    records,_,hashes,_ = research.prepare()
    by_id = {r['race_id']:r for r in records}
    accounting = defaultdict(lambda:[0,0])
    race_budgets = defaultdict(int)
    for ticket in tickets:
        record = by_id[ticket['race_id']]
        payout = record['w_payout'] if ticket['kind']=='wide' else record['q_payout']
        pair = tuple(ticket['pair'])
        expected = payout.get(pair,0)*ticket['stake_yen']//100
        assert ticket['return_yen']==expected
        accounting[(ticket['trial'],ticket['period'])][0] += ticket['stake_yen']
        accounting[(ticket['trial'],ticket['period'])][1] += expected
        race_budgets[(ticket['trial'],ticket['race_id'])] += ticket['stake_yen']
    assert all(budget==600 for budget in race_budgets.values())
    for (trial,period),(stake,returned) in accounting.items():
        value = report['results'][trial][period]
        assert value['stake_yen']==stake and value['return_yen']==returned
    assert hashes==report['input_sha256']
    losses = defaultdict(list)
    for prediction in predictions:
        record = by_id[prediction['race_id']]
        assert [tuple(k) for k in prediction['keys']]==record['keys']
        for model,probabilities in {'q_unmodified_market':record['market'],**prediction['scores']}.items():
            probabilities = np.clip(probabilities,1e-12,1-1e-12)
            target = record['target'] if model.startswith('q_') else record['wide_target']
            loss = float(-target@np.log(probabilities)) if model.startswith('q_') else float(np.mean((target-probabilities)**2))
            losses[(prediction['period'],model)].append(loss)
    quality = {period:{model:float(np.mean(values)) for (part,model),values in losses.items() if part==period} for period in ['development','check','reused_2026']}
    research.save('quality.json',quality)
    content_start = 7 + 2*len(research.previous.HISTORY_KEYS)
    coverage = {}
    for period in report['period_counts']:
        part = [r for r in records if r['period']==period]
        coverage[period] = dict(
            pair_both_latest_corner_observed=float(np.mean([np.mean(np.isfinite(r['full_x'][:,content_start+9])) for r in part])),
            pair_both_latest_pace_observed=float(np.mean([np.mean(np.isfinite(r['full_x'][:,content_start+10])) for r in part])))
    research.save('feature_coverage.json',coverage)
    verification = json.loads((OUT/'verification.json').read_text(encoding='utf-8'))
    verification.update(separately_reloaded_input_and_ticket_accounting=True,all_bought_race_budgets_600=True,probability_quality='馬連=レース平均対数損失、ワイド=レース平均ペアBrier。低いほどよい。')
    research.save('verification.json',verification)
    text = ['# 共同確率と買い目：固定10案の検証結果','',
            '作成日：2026-10-02。研究用途。夏（6～8月）は全案共通で除外。', '',
            '## 分割と入力','',
            '2024年で学習し、2025年1～2月で確率校正。2025年9～10月で券種別候補を選び、11～12月と2026年1～5月で確認した。後半の結果で候補を選び直していない。2026年と過去期間は以前の研究でも参照済みで、独立した未使用テストではない。','',
            '| 区間 | 採用レース数 |','|---|---:|']
    for period,count in report['period_counts'].items():
        text.append(f'| {period} | {count} |')
    text += ['', '元JSONLは4,400レース。ここでは8頭以上・障害除外・照合可能なワイドと馬連払戻がある共通集合を使用。月別欠測・払戻欠測で件数が減るため、全JRAへの一般化はできない。元データ生成条件は各年manifest.json、今回の件数差はreport.jsonのsource_auditを参照。','',
             'manifest_audit.jsonにも生成条件・月別件数・除外理由を保存した。2024年9～11月は採用0、12月は20件。2025年3～8月も採用0であり、年間を均等に比較できるデータではない。','',
             '既存の履歴処理・netkeiba_race_id経由の払戻照合・市場を基準とする馬連学習を再利用した。新規モデルはpair_models.joblibに保存。元DBは読み取り専用接続。入力JSONLのハッシュ一致を確認。ライブモデル・取得処理を変更していない。', '',
             '## 回収率','',
             '購入したレースの総予算は600円。1点案は600円、ワイド2点案は各300円。見送りは投資に数えない。P07/P08/P10は時点価格から期待倍率を判定し、校正期間で推定した払戻価格の下方補正も共通で使用。','',
             '| 案 | 券種 | 9～10月 件数/回収率 | 11～12月 件数/回収率 | 2026年1～5月 件数/回収率 |',
             '|---|---|---:|---:|---:|']
    for trial,values in report['results'].items():
        kind = 'ワイド' if trial in ['P05','P06','P09'] else '馬連'
        cells = [f"{values[p]['races']} / {percentage(values[p]['roi'])}" for p in ['development','check','reused_2026']]
        text.append(f'| {trial} | {kind} | '+' | '.join(cells)+' |')
    text += ['', '各案の定義はprotocol.json、全買い目はtickets.jsonl、全ペア確率はpredictions.jsonlに保存。実行後の閾値変更や競馬場別の絞り込みは行っていない。','',
             '## 開発期間だけで選んだ候補','']
    for kind,trial in report['development_selected'].items():
        text += [f'### {kind}: {trial}','']
        if trial is None:
            text += ['開発期間で30購入レースに達した候補なし。','']
            continue
        for period in ['development','check','reused_2026']:
            value = report['results'][trial][period]
            ci = value['day_bootstrap_roi_95']
            text.append(f"- {period}: {value['races']}レース、利益{value['profit_yen']:,}円、回収率{percentage(value['roi'])}、最大払戻レースを除くと{percentage(value['roi_without_max'])}。日単位bootstrapの95%区間：{percentage(ci[0])}～{percentage(ci[1])}。")
        text.append('')
    text += ['## 確率の精度','', '馬連はレース平均対数損失、ワイドはレース平均ペアBrier。低いほど良い。回収率が高い案と確率が正確な案が一致するとは限らない。','',
             '| モデル | 9～10月 | 11～12月 | 2026年1～5月 |','|---|---:|---:|---:|']
    for model in quality['development']:
        text.append('| '+model+' | '+' | '.join(f'{quality[p][model]:.6f}' for p in quality)+' |')
    text += ['', '馬連の校正係数（市場からの乖離に掛ける値。0なら市場そのもの）：','']
    for model,calibration in report['calibration'].items():
        if 'alpha' in calibration:
            text.append(f"- {model}: {calibration['alpha']:.6f}")
    selected_values = [report['results'][trial] for trial in report['development_selected'].values() if trial]
    robust = [values for values in selected_values if all(values[p]['roi'] is not None and values[p]['roi']>1 and values[p]['roi_without_max']>1 for p in ['check','reused_2026'])]
    text += ['', '## 過去内容の利用可能性','',
             '各レース内の全ペアについて、2頭とも直近過去走の指標がある割合のレース平均。今回の採用期間・非夏集合で再計算した。','',
             '| 区間 | 2頭とも通過順あり | 2頭ともラップ由来ペースあり |','|---|---:|---:|']
    for period,value in coverage.items():
        text.append(f"| {period} | {percentage(value['pair_both_latest_corner_observed'])} | {percentage(value['pair_both_latest_pace_observed'])} |")
    text += ['', '年によって欠測量が変わっている。学習期でほぼ観測されない内容変数を後の期間で増やしても、その関係を十分に学習できない。この差が損失の直接原因とまでは断定できない。','', '## 判断と次の課題','']
    text += ['後続2期間で最大払戻除外後も100%を超えた選択候補がある。ただし再利用データと多重探索のため、実運用収益を証明したものではない。'] if robust else ['今回も、開発期間で選んだ案が後続2期間で最大払戻除外後も100%を上回る結果は得られなかった。購入に値すると断定できるモデルは成立していない。']
    text += ['', 'ワイドはT-30価格がないため、配当との釣り合いによる購入・見送りを検証できていない。馬連は市場補正を強く縮める校正結果があり、過去内容の代理変数を増やすだけで収益改善するとは確認できない。本人の折り合い・進路損失・調教等の観察は再現できておらず、今回のモデルを予想家本人の完全トレースとは扱わない。','',
             '次の仮説では、現在あるデータのうち学習期と評価期で共通して観測できる指標を中心にし、欠測が増える場合の市場予測への戻し方を契約する。今回の結果を見て価格閾値や競馬場を後付けで変えない。','',
             '日別bootstrap区間は今回の固定条件のばらつきであり、全研究の多重探索を補正していない。過去出馬表・発走時刻の当時検証不足、後日再構成のオッズ、2025年の月別欠測も残る。最適という表現は今回の10案と開発期間に限定する。','',
             '## 確認','',
             f"- {verification['selection_checks']:,}回の選択と予測に対し、対象結果・払戻・偽T-10情報の追加による不変性を確認。",
             f'- 保存買い目{len(tickets):,}点の払戻を再読込した元データと照合し、期間別会計も再計算。',
             '- 新規Pythonの説明ヘッダーと全関数docstringをASTで確認。',
             '- 使用ライブラリ：既存のNumPy/SciPy/scikit-learn/joblib/threadpoolctl。依存追加なし。処理は2スレッドに制限。','']
    (OUT/'RESULTS.md').write_text('\n'.join(text),encoding='utf-8')
    (OUT/'NEXT.md').write_text('# 再開地点\n\n固定10案の学習・会計確認完了。RESULTS.md / report.json / quality.jsonを先に読む。選択候補を後続の結果で入れ替えない。ライブ採用はしていない。\n\n今後の仮説は別契約で作成し、この10案の結果を上書きしない。追加の価格情報がない間、ワイドの期待値判定を成立済みと扱わない。\n',encoding='utf-8')
    print(json.dumps(dict(selected=report['development_selected'],quality=quality,verified_tickets=len(tickets)),ensure_ascii=False,indent=2))


if __name__ == '__main__':
    with threadpool_limits(limits=2):
        main()
