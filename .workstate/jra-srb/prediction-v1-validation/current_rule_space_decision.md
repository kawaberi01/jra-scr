# Current Rule Space Decision

Date: 2026-07-04

## Goal

この資料は、現在までに評価した `v1/v2 current rule space` について、

- holdout 前に残すべき候補があるか
- それとも現行探索範囲は一旦 reject とみなすべきか

を明示するための判定メモ。

## Scope

ここでいう `current rule space` は次を含む。

- 履歴スコア主体の `v1` 系
- single-middle override
- standard ticket count / score gap / race-shape guard
- target-race hard gate (`popularity`, `horse_weight_diff`)
- target-race score bonus / penalty
- `v25` を土台にした shape guard / first gap 併用

## Fixed evidence

### Holdout済み候補

- `v10`
  - holdout `2026-01-01..2026-06-28`
  - ROI `85.95%`
  - no-max ROI `82.00%`
  - reject

これは「validation が良く見えても holdout で崩れる」実例として扱う。

### 代表候補の最終位置

| theory | summary | validation no-max | Jul | Aug | Sep | status |
|---|---|---:|---:|---:|---:|---|
| v17 | v1系の主基準 | 1.0124 | 0.9601 | 0.7812 | 0.6264 | reject |
| v22 | 標準1点化 | 0.9819 | 0.8978 | 1.0081 | 0.6560 | reject |
| g12_5 | second gap強化 | 1.0266 | 0.9882 | 0.7537 | 0.6362 | reject |
| sg_a4_6_r3_5 | shape guard | 1.0014 | 0.9505 | 0.8184 | 0.6733 | reject |
| v24 | popularity + middle weight<=8 | 1.0564 | 0.8608 | 0.8506 | 0.5583 | reject |
| v25 | popularity<=3 + middle weight<=4 | 1.0313 | 0.9928 | 0.9155 | 0.6313 | reject |
| v25_sg_a4_6_rle2 | v25 + ratio<=2 guard | 1.0527 | 0.9218 | 1.0158 | 0.6469 | reject |
| v25_a4_6_rle2_fg2_5 | v25 + ratio<=2 + first gap | 1.0171 | 0.9930 | 0.9384 | 0.6805 | reject |
| v25_a4_8_rle2_fg2_5 | v25 + wider ratio<=2 + first gap | 1.0446 | 0.9408 | 0.9242 | 0.7278 | reject |

## What the evidence says

1. `validation` の headline ROI を上げる理論は複数作れる
2. しかしそれらは train walk-forward のどこかを壊す
3. 逆に train の一部を押し上げる理論は validation no-max や top3-cut を壊す
4. `ratio <= 2.0` は強い弱形シグナルだが、切り方を広げると別月が崩れる
5. `first gap` は 2025-09 改善に効くが、month-to-month 再現性の解決にはならない
6. target-race feature は有効だが、hard gate を超えて「採用候補理論」にするには不足

## Decision

現時点では、`current rule space` に holdout へ進める採用候補はない。

結論:

- `current rule space = reject for promotion`
- ただし `evaluation framework = usable`
- したがって失敗しているのは評価手順ではなく、理論空間のほう

## What is complete already

以下はすでに整っている。

- train / validation / holdout の期間固定
- netkeiba 補完込みの再現可能データ基盤
- walk-forward 評価スクリプト
- validation / holdout 評価スクリプト
- candidate version ごとの成果物
- reject の根拠ログ

つまり「再実行可能な評価手順・判定基準・成果物一式」はかなり整っている。

未達なのは次の一点。

- holdout に出せる再現性ある理論

## Next phase

次フェーズは、現在の rule space をそのまま掘るより、
新しい発走前特徴量を入れた新設計へ進むべき。

優先候補:

- 枠順
- 頭数
- 当日馬場 / 天候のより使いやすい正規化
- 発走前人気・オッズのスナップショット運用
- 騎手 / 厩舎の近走条件別成績
- course / class / age 条件のターゲット側特徴

## Operational recommendation

このスレッドの現時点の実務判断は次。

1. `v1/v2 current rule space` はここで一旦打ち切る
2. 現行評価基盤は維持する
3. 次は新特徴量を加えた別バージョン空間として再開する

これにより、結果に合わせて同じ空間の閾値調整を続ける状態を止められる。
