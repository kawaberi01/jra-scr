# Shape Guard And Hybrid Iteration

Date: 2026-07-04

## Objective

`v17` 系の標準 2 点買いについて、`axis_odds × odds_ratio` の shape guard を追加すれば、

- validation の no-max ROI を維持しつつ
- 2025-08 / 2025-09 の train split を改善できるか

を確認した。

## Sweep 1: shape guard matrix

Script:

- `.workstate/jra-srb/prediction-v1-validation/sweep_v17_shape_guard_matrix.py`

主な候補:

- `sg_a4_6_rle2`: axis `4.0..6.0`, ratio `<= 2.0`
- `sg_a4_6_r3_5`: axis `4.0..6.0`, ratio `3.0..5.0`
- `sg_a4_8_rle2`: axis `4.0..8.0`, ratio `<= 2.0`
- `sg_a2_10_rle2`: axis `2.0..10.0`, ratio `<= 2.0`

主要結果:

| theory | validation ROI | validation no-max | wf1 | wf2 | wf3 |
|---|---:|---:|---:|---:|---:|
| v17 | 1.0402 | 1.0124 | 0.9601 | 0.7812 | 0.6264 |
| sg_a4_6_rle2 | 1.0476 | 1.0176 | 0.9644 | 0.7978 | 0.5952 |
| sg_a4_6_r3_5 | 1.0315 | 1.0014 | 0.9505 | 0.8184 | 0.6733 |
| sg_a4_8_rle2 | 1.0478 | 1.0178 | 0.9371 | 0.8064 | 0.6410 |
| sg_a2_10_rle2 | 1.0429 | 1.0104 | 0.8705 | 0.8275 | 0.6818 |

読み取り:

1. `axis 4-6 / ratio 3-5` は `2025-08` と `2025-09` を改善するが、validation no-max がぎりぎりで、`2025-07` も少し悪化する。
2. `ratio <= 2.0` 系は validation が強くなる。
3. ただし `ratio <= 2.0` を広く切るほど `2025-07` が崩れる。

この時点で最もバランスが良い shape guard 単独候補は `sg_a4_6_r3_5` だが、まだ holdout 候補水準ではない。

## Sweep 2: hybrid guard

Script:

- `.workstate/jra-srb/prediction-v1-validation/sweep_v17_hybrid_guards.py`

主な候補:

- `hy_fg7_5_a4_6_r3_5`
- `hy_fg7_5_a2_10_rle2`

主要結果:

| theory | validation ROI | validation no-max | wf1 | wf2 | wf3 |
|---|---:|---:|---:|---:|---:|
| hy_fg7_5_a4_6_r3_5 | 1.0126 | 0.9795 | 0.9450 | 0.7929 | 0.7036 |
| hy_fg7_5_a2_10_rle2 | 1.0997 | 1.0596 | 0.8271 | 0.8033 | 0.8140 |

読み取り:

- `hy_fg7_5_a4_6_r3_5` は 2025-09 をさらに上げるが validation no-max が 1.0 を割る。
- `hy_fg7_5_a2_10_rle2` は validation, 2025-08, 2025-09 を大きく改善するが、`2025-07=0.8271` まで崩れる。

つまり、hybrid 化で train の弱月を押し上げても、別の月を壊している。

## Sweep 3: ratio<=2 branch gap curve

Script:

- `.workstate/jra-srb/prediction-v1-validation/sweep_v17_ratio_le2_gap_curve.py`

主要結果:

| theory | validation ROI | validation no-max | wf1 | wf2 | wf3 |
|---|---:|---:|---:|---:|---:|
| le2_g0 | 1.0429 | 1.0104 | 0.8705 | 0.8275 | 0.6818 |
| le2_g2_5 | 1.0846 | 1.0450 | 0.8575 | 0.7920 | 0.7275 |
| le2_g5 | 1.0970 | 1.0572 | 0.8642 | 0.7872 | 0.7566 |
| le2_g7_5 | 1.0997 | 1.0596 | 0.8271 | 0.8033 | 0.8140 |

読み取り:

1. `first gap` を強めるほど validation と `2025-09` は上がる。
2. 同時に `2025-07` は一貫して悪化する。
3. これは単純な閾値最適化ではなく、月ごとの race shape 差分を v1 スコアが吸収できていないことを示す。

## Decision

このイテレーションで確認できたこと:

- `v17` 系で `shape guard` を足すだけでは holdout 候補に届かない
- とくに `ratio <= 2.0` は validation で効くが、train の別月を壊しやすい
- 現行 v1 スコアと odds gate だけで、train 3 分割を同時に安定化させるのは難しい

現時点の不採用候補:

- `sg_a4_6_rle2`
- `sg_a4_6_r3_5`
- `sg_a4_8_rle2`
- `sg_a2_10_rle2`
- `hy_fg7_5_a4_6_r3_5`
- `hy_fg7_5_a2_10_rle2`
- `le2_g0`
- `le2_g2_5`
- `le2_g5`
- `le2_g7_5`

## Implication

この v1 系の探索だけで続けると、validation を上げる代わりに train のどこかを壊す形が続く。

したがって次の合理的な分岐は以下のどちらか。

1. `v1` はここで打ち切り、`holdout 候補なし` と明示して v2 系へ進む
2. 発走前に取得可能な追加特徴量を導入した `v2` を作る

優先は `2`。

追加候補の中心は次:

- 発走前の人気・単勝オッズ帯
- 馬体重と増減
- 当日馬場・天候
- 枠順や頭数由来の race shape

結論として、この turn の evidence は「現在の v1 feature set では再現性が足りない」方向を強く支持する。
