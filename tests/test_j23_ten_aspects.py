"""概要: J23追加10案の予測時制約・縮約・変額精算を検証する。
作成日: 2026-10-23
入力: 合成した購入行。SQL・研究runへのアクセスなし。
出力: unittestの検証結果。
実行例: uv run --frozen python -m unittest discover -s tests -p test_j23_ten_aspects.py
注意事項: 外部通信・学習・研究成果物の変更なし。
"""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from analyze_j23_ten_aspects import applied, band, estimate, policy_stake


class PurchaseContracts(unittest.TestCase):
    """購入判断と結果精算の境界を検証する。"""

    def test_current_outcome_cannot_change_decision(self):
        """現在レースの的中や払戻を変更しても賭金が変わらない。"""
        neutral = estimate([])
        params = {'global': neutral, 'recent': neutral,
                  'price_bands': {b: neutral for b in ('under10', '10to30', '30plus')}}
        row = dict(ticket_probability=.1, ticket_odds=12., pair_count=105,
                   r1_agrees=True, chosen=1, winner=1, payout=7200)
        future_changed = dict(row, winner=2, payout=0)
        for name in (f'Q{i:02}' for i in range(1, 11)):
            self.assertEqual(policy_stake(name, row, params), policy_stake(name, future_changed, params))

    def test_stake_scaled_by_official_payout(self):
        """当たり外れと100円単位の賭金から精算し、原本は書き換えない。"""
        row = dict(chosen=3, winner=3, hr_payout_yen=1230, stake=600, payout=7380)
        self.assertEqual(applied(row, 200)['payout'], 2460)
        self.assertEqual(applied(dict(row, winner=4), 200)['payout'], 0)
        self.assertEqual(row['stake'], 600)
        with self.assertRaises(AssertionError):
            applied(row, 150)

    def test_neutral_prior_and_quote_only_winners(self):
        """空履歴は中立、負け券の公表払戻を価格係数へ混入させない。"""
        self.assertEqual(estimate([])['price'], 1.)
        loss = dict(ticket_probability=.05, payout=0, stake=600, ticket_odds=30.)
        self.assertEqual(estimate([loss])['price'], 1.)
        winner = dict(ticket_probability=.05, payout=12000, stake=600, ticket_odds=30.)
        self.assertLess(estimate([winner])['price'], 1.)

    def test_exposure_and_odds_boundaries(self):
        """境界の帰属と100円未満を買わない払戻集中制約を確認する。"""
        self.assertEqual(band(10), '10to30')
        self.assertEqual(band(30), '30plus')
        row = dict(ticket_probability=.02, ticket_odds=50.)
        self.assertEqual(policy_stake('Q08', row, {'global': {}}), 100)
        self.assertEqual(policy_stake('Q08', dict(row, ticket_odds=100.), {'global': {}}), 0)


if __name__ == '__main__':
    unittest.main()
