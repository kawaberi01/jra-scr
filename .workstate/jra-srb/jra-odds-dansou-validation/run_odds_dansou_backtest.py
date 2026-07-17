from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the original GPTs odds-dansou win rule.")
    parser.add_argument("--db", type=Path, default=Path("data/db/analysis.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path(".workstate/jra-srb/jra-odds-dansou-validation"))
    args = parser.parse_args()
    with sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            select r.race_id,r.race_date,r.course,re.horse_no,re.rank,ne.win_odds,p.payout
            from races r join result_entries re on re.race_id=r.race_id
            join netkeiba_race_mappings m on m.jra_race_id=r.race_id
            join netkeiba_result_entries ne on ne.netkeiba_race_id=m.netkeiba_race_id and ne.horse_no=re.horse_no
            left join payouts p on p.race_id=r.race_id and p.bet_type in ('win','単勝') and p.combination=re.horse_no
            where length(r.race_id)=12 and substr(r.race_id,9,2) between '01' and '10'
              and r.source like 'https://www.jra.go.jp/%' and ne.win_odds>0
              and coalesce(r.race_name,'') not like '%新馬%' and coalesce(r.race_name,'') not like '%メイクデビュー%' and coalesce(r.race_name,'') not like '%障害%'
            order by r.race_date,r.race_id,cast(re.horse_no as integer)
        """).fetchall()
    by_race: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_race[str(row['race_id'])].append(dict(row))
    selections = []
    skipped = Counter()
    for race_id, runners in by_race.items():
        ranked = sorted(runners, key=lambda item: (item['win_odds'], int(item['horse_no'])))[:6]
        if len(ranked) < 6:
            skipped['fewer_than_six_odds'] += 1
            continue
        gaps = [ranked[index + 1]['win_odds'] / ranked[index]['win_odds'] for index in range(5)]
        max_index = max(range(5), key=lambda index: gaps[index])
        max_gap = gaps[max_index]
        if max_gap < 2:
            skipped['no_gap'] += 1
            continue
        candidate = ranked[max_index]
        if not 3.0 <= candidate['win_odds'] <= 10.9:
            skipped['candidate_outside_win_band'] += 1
            continue
        pattern = 'p1' if max_index == 0 and max_gap >= 2.5 else 'p2' if max_index == 1 else 'p3'
        if sum(gap >= 2 for gap in gaps) >= 2:
            pattern = 'p4'
        selections.append({**candidate, 'max_gap': max_gap, 'pattern': pattern})
    payouts = [item['payout'] if item['rank'] == 1 and item['payout'] else 0 for item in selections]
    ordered = sorted(payouts, reverse=True)
    def roi(values: list[int]) -> float:
        return sum(values) / (len(values) * 100) if values else 0.0
    result = {
        'status': 'historical_screen_only',
        'rule': 'top6 adjacent odds gap >=2.0; select directly above max gap; win odds 3.0..10.9',
        'races_with_odds': len(by_race), 'selections': len(selections), 'hits': sum(value > 0 for value in payouts),
        'roi': roi(payouts), 'no_max_roi': roi(ordered[1:]), 'no_top3_roi': roi(ordered[3:]),
        'patterns': dict(Counter(item['pattern'] for item in selections)), 'skipped': dict(skipped),
        'warning': 'final odds are used; this does not validate pre-race odds movement or promote a betting rule.',
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'odds-dansou-backtest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    (args.output_dir / 'odds-dansou-backtest.md').write_text('\n'.join((
        '# 元Gpts オッズ断層履歴スクリーニング', '', f"- 対象レース: {result['races_with_odds']}", f"- 選択: {result['selections']}", f"- ROI: {result['roi']:.3f}", f"- 最大払戻除外後ROI: {result['no_max_roi']:.3f}", f"- 上位3払戻除外後ROI: {result['no_top3_roi']:.3f}", f"- 注意: {result['warning']}", ''
    )), encoding='utf-8', newline='\n')
    print(f"DANSOU_STATUS=completed selections={len(selections)} roi={result['roi']:.3f}")


if __name__ == '__main__':
    main()
