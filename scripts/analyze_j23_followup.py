"""概要: 保存済みJ23予測の黒字要因と固定6案の購入抑制を探索的に再集計する。
作成日: 2026-10-22
入力: リポジトリ内の固定済み30仮説研究run。
出力: artifacts/jra_research/j23_followup_20261022の計画・集計・Markdown。
実行例: uv run --frozen python -X utf8 scripts/analyze_j23_followup.py
注意事項: 既使用期間の探索のみ。学習・再選択・元run変更・SQL・外部通信なし。
"""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'artifacts/jra_research/runs/20261022T080510Z_b6a4eb0716114496b680ea3378644159'
OUT = ROOT / 'artifacts/jra_research/j23_followup_20261022'
POLICIES = [
    ('P01', '低確率抑制', 'ticket_probability', 'min', .05),
    ('P02', '高配当依存抑制', 'ticket_odds', 'max', 30.),
    ('P03', '期待倍率の余裕', 'ev', 'min', 1.2),
    ('P04', '低確率抑制の強化', 'ticket_probability', 'min', .10),
    ('P05', '高配当依存抑制の強化', 'ticket_odds', 'max', 15.),
    ('P06', '期待倍率の余裕の強化', 'ev', 'min', 1.3),
]


def dump(path, value):
    """有限値のJSONをUTF-8で保存する。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def aggregate(rows):
    """既存購入行の損益・確率校正と集中度を集計する。"""
    stake = sum(r['stake'] for r in rows)
    payout = sum(r['payout'] for r in rows)
    balance = peak = drawdown = 0
    for r in sorted(rows, key=lambda r: (r['race_date'], r['race_key'])):
        balance += r['payout']-r['stake']
        peak = max(peak, balance)
        drawdown = max(drawdown, peak-balance)
    largest = max((r['payout'] for r in rows), default=0)
    return dict(bets=len(rows), buy_days=len({r['race_date'] for r in rows}),
                hits=sum(r['payout'] > 0 for r in rows), stake=stake, payout=payout,
                profit=payout-stake, roi=payout/stake if stake else None,
                expected_hits=sum(r['ticket_probability'] for r in rows),
                quoted_expected_payout=sum(r['stake']*r['ev'] for r in rows),
                roi_without_largest=(payout-largest)/stake if stake else None,
                max_drawdown_yen=drawdown)


def groups(rows, key, edges):
    """結果を使わず固定した境界で購入行を区分する。"""
    result = {}
    for low, high in zip(edges, edges[1:]):
        result[f'[{low}, {high})'] = aggregate([r for r in rows if low <= r[key] < high])
    assert sum(s['bets'] for s in result.values()) == len(rows)
    return result


def percent(value):
    """回収率を百分率で表示し、購入なしを明記する。"""
    return f'{100*value:.2f}%' if value is not None else '購入なし'


def main():
    """先に探索条件を保存し、会計・原本不変を検査して結果を出力する。"""
    OUT.mkdir(parents=True, exist_ok=True)
    protocol = dict(status='exploratory_only', policies=POLICIES,
                    rounds=[['P01', 'P02', 'P03'], ['P04', 'P05', 'P06']],
                    scope='filter_original_ticket_only_no_reselection',
                    candidate_cap=12, fresh_holdout_available_in_source=False,
                    stop='No independent new period in saved source; no adoption or additional fitting.',
                    probability_edges=[0, .02, .05, .1, .2, 1.000001],
                    odds_edges=[0, 5, 10, 15, 30, 60, 100, 1e300],
                    ev_edges=[0, 1.05, 1.1, 1.2, 1.3, 1.5, 2, 1e300])
    protocol_path = OUT/'protocol.json'
    if protocol_path.exists():
        assert json.loads(protocol_path.read_text(encoding='utf-8')) == json.loads(json.dumps(protocol))
    else:
        dump(protocol_path, protocol)
    paths = sorted((SOURCE/'cells').glob('*_J23.json'))+[SOURCE/'metrics.json']
    before = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    phases = defaultdict(list)
    monthly = {}
    for path in paths[:-1]:
        cell = json.loads(path.read_text(encoding='utf-8-sig'))
        rows = []
        for row in cell['rows']:
            if row['stake']:
                r = dict(row)
                r['ev'] = r['ticket_probability']*r['ticket_odds']
                assert r['stake'] == 600 and 0 < r['ticket_probability'] <= 1
                assert (r['chosen'] == r['winner']) == (r['payout'] > 0)
                assert r['payout'] == (6*r['hr_payout_yen'] if r['chosen'] == r['winner'] else 0)
                rows.append(r)
        phase = 'selection' if cell['month'] <= '2026-03' else 'confirmation'
        phases[phase].extend(rows)
        monthly[cell['month']] = aggregate(rows)
    assert len(monthly) == 30
    metrics = json.loads((SOURCE/'metrics.json').read_text(encoding='utf-8-sig'))
    result = dict(protocol=protocol, phases={}, monthly=monthly)
    for phase, rows in phases.items():
        base = aggregate(rows)
        for field in ('bets', 'stake', 'payout', 'hits'):
            assert base[field] == metrics['phases'][phase]['J23'][field]
        variants = {}
        for name, _, field, direction, threshold in POLICIES:
            kept = [r for r in rows if (r[field] >= threshold if direction == 'min' else r[field] <= threshold)]
            summary = aggregate(kept)
            assert summary['bets'] <= base['bets'] and summary['stake'] <= base['stake']
            variants[name] = summary
        days = defaultdict(list)
        for r in rows:
            days[r['race_date']].append(r)
        day_stats = {day: aggregate(values) for day, values in sorted(days.items())}
        positive_days = sum(s['profit'] > 0 for s in day_stats.values())
        result['phases'][phase] = dict(baseline=base, variants=variants,
            probability_bands=groups(rows, 'ticket_probability', protocol['probability_edges']),
            odds_bands=groups(rows, 'ticket_odds', protocol['odds_edges']),
            ev_bands=groups(rows, 'ev', protocol['ev_edges']),
            days=day_stats, positive_days=positive_days,
            realized_winner_to_quoted_payout_ratio=(sum(r['payout'] for r in rows)/sum(r['stake']*r['ticket_odds'] for r in rows if r['payout'] > 0)))
    assert before == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    result['verification'] = dict(status='passed', source_sha256=before, original_unchanged=True,
                                  training_runs=0, new_model_candidates=0, screening_policies=6,
                                  adoption=False, stop_reason='saved_source_has_no_new_independent_period')
    dump(OUT/'results.json', result)
    lines = ['# J23追加診断と固定6案の探索', '',
             '2026-10-22。既使用期間の探索であり、新モデルの学習・採用判定ではない。', '',
             '元の買い目を条件で見送る比較。別の組への買い替えはしない。6案は一括固定し、途中結果で変更しない。', '',
             '| 案 | 選抜24月 点数/回収率 | 確認6月 点数/回収率 | 確認 最大払戻除外 |',
             '|---|---:|---:|---:|']
    for name in ['baseline', *(p[0] for p in POLICIES)]:
        a = result['phases']['selection']['baseline' if name == 'baseline' else 'variants']
        b = result['phases']['confirmation']['baseline' if name == 'baseline' else 'variants']
        if name != 'baseline':
            a, b = a[name], b[name]
        lines.append(f"| {name} | {a['bets']} / {percent(a['roi'])} | {b['bets']} / {percent(b['roi'])} | {percent(b['roi_without_largest'])} |")
    lines.extend(['', '## 条件', ''])
    lines.extend(f'- {name}: {label}、{field} {direction} {threshold}。' for name, label, field, direction, threshold in POLICIES)
    for phase, values in result['phases'].items():
        lines.extend(['', f'## {phase} 確率帯', '', '| 確率帯 | 点数 | 期待的中 | 実的中 | 回収率 |', '|---|---:|---:|---:|---:|'])
        for band, s in values['probability_bands'].items():
            lines.append(f"| {band} | {s['bets']} | {s['expected_hits']:.2f} | {s['hits']} | {percent(s['roi'])} |")
    lines.extend(['', '## 終了判断と限界', '',
                  '固定6案・2巡分の購入抑制を探索集計した。最大12案は上限であり、使い切る目標ではない。',
                  '保存元には2026-09より後の独立した評価セルがない。新しいSQL入力の有無は今回確認していない。',
                  '見た成績を使って残り6案を作ると確認期間への適合が進むため、この一括処理は診断・探索の完了で終了する。',
                  '新モデル学習0、実用採用0。独立期間で評価するための前向き保存設計は未実装。',
                  '確率帯・期待倍率帯などの部分集団は探索。小標本の黒字群をそのまま採用しない。',
                  '最終単勝/馬連価格や場・距離属性、全部品の厳密な除外比較はこの保存行にないため、未検証。',
                  '的中時の実払戻/購入時オッズ比は的中分のみの価格変化診断で、全買い目の価格変動ではない。',
                  '原本SHA不変、会計・購入部分集合・30月の照合passed。SQL・再学習・外部送信なし。'])
    (OUT/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('\n'.join(lines[:18]))
    print('verification passed; saved:', OUT)


if __name__ == '__main__':
    main()
