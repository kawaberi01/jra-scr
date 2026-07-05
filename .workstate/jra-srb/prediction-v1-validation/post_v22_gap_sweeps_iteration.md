# Post v22 Gap Sweeps Iteration

## Goal

`v22` の「標準形は 1 点買い」によって 2025-09 を少し改善できたが、validation の no-max ROI が 1.0 を割った。
そのため、次は `v17` 系のまま「弱い 2 点目だけを削る」または「弱い標準形だけを外す」方向が成立するかを確認した。

## Confirmed Baseline

- `v17`
  - validation 2025Q4: ROI `1.0402`, no-max `1.0124`, top3-cut `0.9667`
  - wf1 2025-07: ROI `0.9601`
  - wf2 2025-08: ROI `0.7812`
  - wf3 2025-09: ROI `0.6264`
- `v22`
  - validation 2025Q4: ROI `1.0303`, no-max `0.9819`, top3-cut `0.9042`
  - wf1 2025-07: ROI `0.8978`
  - wf2 2025-08: ROI `1.0081`
  - wf3 2025-09: ROI `0.6560`

判断:

- `v22` は 2025-09 の悪化を少し抑えたが、validation の再現性を落とした。
- よって「標準形を全面 1 点化する」方針は採用候補にできない。

## Ticket Mode Check

`analyze_ticket_modes.py` で `v17` を分解すると、2025-09 は以下だった。

- `bet_single_ticket`: ROI `1.28` (`10` races)
- `bet_two_tickets`: ROI `0.6000` (`124` races)

これは「9月の失速は single-middle override ではなく、標準 2 点買い側に集中している」ことを示す。

## Sweep 1: second middle gap tightening

Script:

- `.workstate/jra-srb/prediction-v1-validation/sweep_v17_second_ticket_gap.py`

候補:

- `g6`: second gap `> 6.0`
- `g7_5`: second gap `> 7.5`
- `g10`: second gap `> 10.0`
- `g12_5`: second gap `> 12.5`
- `g15`: second gap `> 15.0`

主要結果:

| theory | validation ROI | validation no-max | wf1 | wf2 | wf3 |
|---|---:|---:|---:|---:|---:|
| g6 | 1.0361 | 1.0082 | 0.9769 | 0.7812 | 0.6264 |
| g7_5 | 1.0413 | 1.0134 | 0.9825 | 0.7812 | 0.6264 |
| g10 | 1.0486 | 1.0203 | 0.9882 | 0.7394 | 0.6312 |
| g12_5 | 1.0549 | 1.0266 | 0.9882 | 0.7537 | 0.6362 |
| g15 | 1.0489 | 1.0203 | 0.9791 | 0.7758 | 0.6362 |

判断:

- validation は改善する。
- ただし 2025-08 と 2025-09 の train split は依然として弱い。
- 特に `g12_5` が sweep の中では最良だが、`wf2=0.7537`, `wf3=0.6362` で holdout 候補にはならない。

結論:

- 「2 点目だけを score gap で厳しくする」だけでは不足。

## Sweep 2: first middle gap tightening

Script:

- `.workstate/jra-srb/prediction-v1-validation/sweep_v17_first_middle_gap.py`

候補:

- `fg2_5`: first gap `> 2.5`
- `fg5`: first gap `> 5.0`
- `fg7_5`: first gap `> 7.5`
- `fg10`: first gap `> 10.0`

主要結果:

| theory | validation ROI | validation no-max | wf1 | wf2 | wf3 |
|---|---:|---:|---:|---:|---:|
| fg2_5 | 0.9861 | 0.9561 | 0.9632 | 0.7349 | 0.6097 |
| fg5 | 1.0003 | 0.9700 | 0.9756 | 0.7273 | 0.6383 |
| fg7_5 | 1.0208 | 0.9901 | 0.9459 | 0.7726 | 0.6934 |
| fg10 | 0.9996 | 0.9685 | 0.9636 | 0.7045 | 0.6934 |

判断:

- `fg7_5` は 2025-09 を `0.6934` まで改善した。
- しかし validation no-max は `0.9901` で基準未達。
- 他候補も validation か train のどちらかが崩れる。

結論:

- race 全体を first gap で絞るだけでも不足。

## Shape Observation

`analyze_v11_race_shape.py --theory-version v17` から、shape bucket の差は次の通り。

validation 2025Q4:

- axis odds `<=2.0`: ROI `1.2143`
- axis odds `4.1-6.0`: ROI `1.1559`
- first gap `>10.0`: ROI `1.0976`
- odds ratio `>5.0`: ROI `1.1427`

2025-09:

- axis odds `4.1-6.0`: ROI `0.4636`
- axis odds `6.1-8.0`: ROI `0.0000`
- first gap `<=2.5`: ROI `0.4621`
- odds ratio `<=2.0`: ROI `0.3053`
- odds ratio `3.0-5.0`: ROI `0.4681`

読み取り:

- 2025-09 の失速は「標準形の 2 点目」だけでなく、標準形そのものの race shape による不安定さを含む。
- 特に `axis odds` と `odds ratio` の組み合わせで、validation と train の挙動差が大きい。

## Decision

現時点で holdout に出せる候補はまだない。

- `v22`: 不採用
- `g6/g7_5/g10/g12_5/g15`: 不採用
- `fg2_5/fg5/fg7_5/fg10`: 不採用

## Next iteration

次に進めるべき仮説は次のどちらか。

1. `standard` レースだけに対して、`axis_odds` と `first_middle odds ratio` の明示的な shape guard を追加する
2. 既存スコアだけでは標準形の再現性が足りないと認め、発走前に取得可能な追加特徴量を使う v2 系へ進む

優先は `1`。
まずは `standard` レース限定で `axis_odds × odds_ratio` の組み合わせ guard を導入し、train 3 分割と validation を再評価する。
