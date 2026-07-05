# v2 Feature Availability And Initial Results

Date: 2026-07-04

## Objective

`v1` 系の履歴スコアと odds gate だけでは month-to-month の再現性が足りないため、
発走前に取得可能な追加特徴量を使う `v2` に進める前提を確認した。

この資料では次の 2 点を固定する。

1. 現在の `analysis.sqlite` で何が使えるか
2. 使える特徴量だけで作った初期 `v2` 候補がどうだったか

## Data availability

確認方法:

- `data/analysis.sqlite`
- `src/jra_srb/analysis_store.py`
- `docs/jra/13_netkeiba_analysis_sqlite_usage.md`

### netkeiba_result_entries coverage

| period | races | rows | win_odds | popularity | horse_weight | horse_weight_diff |
|---|---:|---:|---:|---:|---:|---:|
| train 2025-01-01..2025-09-30 | 2615 | 35780 | 35780 | 35780 | 35780 | 35749 |
| validation 2025-10-01..2025-12-31 | 840 | 11717 | 11717 | 11717 | 11717 | 11708 |
| holdout 2026-01-01..2026-06-28 | 1338 | 18773 | 18773 | 18773 | 18773 | 18761 |

読み取り:

- `win_odds`, `popularity`, `horse_weight`, `horse_weight_diff` はほぼ全件ある
- `horse_weight_diff` の欠損はごく少ない

### netkeiba_race_results coverage

| period | races | weather | track_condition | surface | distance |
|---|---:|---:|---:|---:|---:|
| train | 2615 | 2615 | 1364 | 2525 | 2615 |
| validation | 840 | 840 | 445 | 810 | 840 |
| holdout | 1338 | 1338 | 643 | 1290 | 1338 |

読み取り:

- `weather` は全件ある
- `track_condition` は約半分なので、初期 `v2` の主特徴量にはしづらい

### JRA runners coverage

| period | rows | card_odds | card_popularity | frame_no |
|---|---:|---:|---:|---:|
| train | 36087 | 0 | 0 | 0 |
| validation | 11797 | 0 | 0 | 0 |
| holdout | 18896 | 159 | 159 | 0 |

読み取り:

- `runners.card_odds`, `runners.card_popularity`, `frame_no` は過去評価では使えない
- 初期 `v2` は JRA 側 card 情報ではなく、netkeiba result page に保存された発走前項目を proxy として使う

## Feature analysis on v17

Script:

- `.workstate/jra-srb/prediction-v1-validation/analyze_v17_target_features.py`

### axis popularity

`v17` の target-race popularity で見ると:

- validation:
  - axis popularity `<=3`: ROI `1.0381`
  - axis popularity `4-6`: ROI `0.9634`
- 2025-08:
  - axis popularity `<=3`: ROI `0.8401`
  - axis popularity `4-6`: ROI `0.3288`
- 2025-09:
  - axis popularity `<=3`: ROI `0.6548`
  - axis popularity `4-6`: ROI `0.4100`

読み取り:

- `axis popularity 4-6` は一貫して弱い
- `<=3` も強いとは言えないが、相対的には明確にまし

### first middle weight diff

- validation:
  - `1-4`: ROI `1.1945`
  - `9+`: ROI `0.7954`
- 2025-08:
  - `1-4`: ROI `0.9264`
  - `5-8`: ROI `0.5487`
- 2025-09:
  - `1-4`: ROI `0.7211`
  - `5-8`: ROI `0.4554`
  - `9+`: ROI `0.4647`

読み取り:

- `first middle` の馬体重増減は `1-4` が最も安定
- `5-8`, `9+` は train の弱月で明確に悪い

## Initial v2 candidates

実装:

- `v23`: `v17` + `axis popularity <= 3`
- `v24`: `v23` + `selected middles abs weight diff <= 8`
- `v25`: `v23` + `selected middles abs weight diff <= 4`
- `v26`: `v23` + `axis abs weight diff <= 8` + `selected middles abs weight diff <= 8`

関連変更:

- `evaluate_v1_validation.py` に `popularity`, `horse_weight`, `horse_weight_diff` を読み込むよう追加

## Results

### Validation 2025Q4

| theory | ROI | no-max ROI | top3-cut ROI | bet_races | tickets |
|---|---:|---:|---:|---:|---:|
| v17 | 1.0402 | 1.0124 | 0.9667 | 432 | 848 |
| v23 | 1.0217 | 0.9939 | 0.9489 | 433 | 848 |
| v24 | 1.0874 | 1.0564 | 1.0064 | 394 | 762 |
| v25 | 1.0723 | 1.0313 | 0.9710 | 307 | 575 |
| v26 | 1.0209 | 0.9897 | 0.9392 | 390 | 755 |

### Train walk-forward

| theory | Jul ROI | Aug ROI | Sep ROI | Jul no-max | Aug no-max | Sep no-max |
|---|---:|---:|---:|---:|---:|---:|
| v17 | 0.9601 | 0.7812 | 0.6264 | 0.8812 | 0.7401 | 0.5787 |
| v23 | 1.0198 | 0.8031 | 0.5742 | 0.9426 | 0.7623 | 0.5296 |
| v24 | 0.8608 | 0.8506 | 0.5583 | 0.7753 | 0.8069 | 0.5078 |
| v25 | 0.9928 | 0.9155 | 0.6313 | 0.8815 | 0.8570 | 0.5614 |
| v26 | 0.7748 | 0.8508 | 0.5177 | 0.6877 | 0.8061 | 0.4675 |

## Interpretation

1. `axis popularity <= 3` だけでは `2025-07` は改善するが `2025-09` が悪化する
2. `middle weight diff` を加えると validation は大きく改善する
3. その中では `v25` が最もバランスが良い
4. それでも `wf3=0.6313` なので holdout 候補には届かない

## Decision

初期 `v2` 候補も現時点では不採用。

- `v23`: 不採用
- `v24`: 不採用
- `v25`: 不採用
- `v26`: 不採用

ただし、`v25` は次の意味で価値がある。

- validation は基準超え
- `2025-08` を `0.9155` まで改善
- target-race feature が本当に効くことを示した

## Next step

次に試すべきなのは、hard gate だけでなく target-race feature を score 化する方向。

優先候補:

1. `axis popularity` を hard cutoff ではなく score bonus / penalty にする
2. `middle horse_weight_diff` を hard cutoff ではなく score penalty にする
3. `weather` を coarse condition として score へ入れる

現時点の evidence は、「追加特徴量自体は有効だが、hard gate だけでは再現性を作り切れない」を支持している。
