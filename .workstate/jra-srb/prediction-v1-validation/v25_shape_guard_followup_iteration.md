# v25 Shape Guard Follow-up Iteration

Date: 2026-07-04

## Objective

`v25` は現時点の `v2` 候補で最もましだった。

- validation: ROI `1.0723`, no-max `1.0313`
- train:
  - Jul `0.9928`
  - Aug `0.9155`
  - Sep `0.6313`

次に、`v25` の target-race gate を保ったまま shape guard を重ねて、
特に `2025-09` を押し上げられるか確認した。

## Sweep 1: v25 + shape guard

Script:

- `.workstate/jra-srb/prediction-v1-validation/sweep_v25_shape_guards.py`

候補:

- `v25_sg_a4_6_r3_5`
- `v25_sg_a4_6_rle2`
- `v25_sg_a4_8_rle2`
- `v25_sg_a2_10_rle2`

主要結果:

| theory | validation ROI | validation no-max | wf1 | wf2 | wf3 |
|---|---:|---:|---:|---:|---:|
| v25 | 1.0723 | 1.0313 | 0.9928 | 0.9155 | 0.6313 |
| v25_sg_a4_6_r3_5 | 1.0409 | 0.9968 | 1.0117 | 0.9640 | 0.6297 |
| v25_sg_a4_6_rle2 | 1.0974 | 1.0527 | 0.9218 | 1.0158 | 0.6469 |
| v25_sg_a4_8_rle2 | 1.0979 | 1.0548 | 0.8680 | 1.0135 | 0.6895 |
| v25_sg_a2_10_rle2 | 1.1211 | 1.0771 | 0.7186 | 0.9646 | 0.6987 |

読み取り:

1. `axis 4-6 / ratio 3-5` は Jul を少し改善したが、validation no-max が 1.0 を割る。
2. `ratio <= 2` 系は validation が非常に強くなる。
3. ただし範囲を広げるほど Jul が崩れる。
4. `v25_sg_a4_6_rle2` は最も現実的だが、Sep `0.6469` にとどまる。

## Sweep 2: v25 + ratio<=2 guard + first gap

Script:

- `.workstate/jra-srb/prediction-v1-validation/sweep_v25_ratio_guard_with_first_gap.py`

候補:

- `v25_a4_6_rle2_fg2_5`
- `v25_a4_6_rle2_fg5`
- `v25_a4_8_rle2_fg2_5`
- `v25_a4_8_rle2_fg5`

主要結果:

| theory | validation ROI | validation no-max | wf1 | wf2 | wf3 |
|---|---:|---:|---:|---:|---:|
| v25_a4_6_rle2_fg2_5 | 1.0662 | 1.0171 | 0.9930 | 0.9384 | 0.6805 |
| v25_a4_6_rle2_fg5 | 1.0983 | 1.0476 | 0.9879 | 0.9089 | 0.6589 |
| v25_a4_8_rle2_fg2_5 | 1.0977 | 1.0446 | 0.9408 | 0.9242 | 0.7278 |
| v25_a4_8_rle2_fg5 | 1.1335 | 1.0786 | 0.9344 | 0.8932 | 0.7057 |

読み取り:

1. `first gap` を足すと Sep は押し上がる。
2. ただし Aug が 다시落ちるか、Jul が下がる。
3. 最もバランスが良いのは `v25_a4_6_rle2_fg2_5` だが、
   - validation no-max `1.0171`
   - Jul `0.9930`
   - Aug `0.9384`
   - Sep `0.6805`
   で、まだ reproducibility 水準には届かない。
4. `v25_a4_8_rle2_fg2_5` は Sep `0.7278` まで上がるが、Jul/Aug が弱い。

## Decision

この follow-up でも holdout 候補は出ていない。

不採用:

- `v25_sg_a4_6_r3_5`
- `v25_sg_a4_6_rle2`
- `v25_sg_a4_8_rle2`
- `v25_sg_a2_10_rle2`
- `v25_a4_6_rle2_fg2_5`
- `v25_a4_6_rle2_fg5`
- `v25_a4_8_rle2_fg2_5`
- `v25_a4_8_rle2_fg5`

## Updated conclusion

`v25` に shape guard を重ねる方向でも、validation と train 3分割を同時に揃えることはできなかった。

ただし、今回の結果から次はっきり言えることは次の 2 点。

1. `ratio <= 2.0` は依然として重要な弱形シグナル
2. `first gap` は Sep 改善には効くが、月跨ぎ安定化には不十分

このため、現行データとルール空間の中では、
「閾値と gate の足し引きだけで holdout 候補を作る」期待値はかなり低い。

## Next step

次の合理的な分岐は以下のどちらか。

1. ここで `v1/v2 current rule space では holdout 候補なし` と判定し、理論探索を一旦閉じる
2. 追加の発走前特徴量を入れる新しい設計に進む

現時点の evidence では `1` の判断がかなり強い。

つまり、少なくとも今の feature set と gate space の範囲では、
再現性のある採用候補理論はまだ確立できていない。
