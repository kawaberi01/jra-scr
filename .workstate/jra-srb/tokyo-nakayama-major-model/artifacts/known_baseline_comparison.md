# v89・ベースライン既知期間比較

判定用途: **診断のみ**。発走前odds snapshotがないため、昇格根拠には再利用しない。

| period | venue | tickets | ROI | no-max | no-top3 | axis top3 | partner top3 | hit rate | target rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| known_validation | combined | 7 | 2.8429 | 1.7429 | 0.4571 | 0.5871 | 0.5714 | 0.5714 | 0.0348 |
| known_validation | tokyo | 5 | 2.6 | 1.06 | 0.0 | 0.5915 | 0.4 | 0.4 | 0.0352 |
| known_validation | nakayama | 2 | 3.45 | 1.6 | 0.0 | 0.5763 | 1.0 | 1.0 | 0.0339 |
| known_holdout | combined | 16 | 1.4688 | 0.9563 | 0.2938 | 0.5829 | 0.25 | 0.25 | 0.0402 |
| known_holdout | tokyo | 5 | 0.94 | 0.0 | 0.0 | 0.6232 | 0.2 | 0.2 | 0.0362 |
| known_holdout | nakayama | 11 | 1.7091 | 0.9636 | 0.0 | 0.5615 | 0.2727 | 0.2727 | 0.0423 |

## 単純人気baseline（1番人気の3着内率）

- known_validation: `{'tokyo': {'races': 227, 'top3_rate': 0.7048}, 'nakayama': {'races': 96, 'top3_rate': 0.6042}, 'combined': {'races': 323, 'top3_rate': 0.6749}}`
- known_holdout: `{'tokyo': {'races': 163, 'top3_rate': 0.6871}, 'nakayama': {'races': 300, 'top3_rate': 0.7067}, 'combined': {'races': 463, 'top3_rate': 0.6998}}`

## 既存履歴モデルbaseline

- status: `not_comparable_on_known_periods`
- artifact: `jra-history-logistic-recent-form-v2`, trained_through `2026-07-11`
- reason: The only current artifact was trained through 2026-07-11, later than both known periods.

## 解釈

- v89は既知期間で高いROIを示しても、市場値が結果ページ由来でas-ofを証明できない。
- 現行履歴artifactは既知期間より後まで学習済みのため、同期間baselineへ使うと未来情報混入になる。
- よって新規候補探索は行わず、v89順位ルールを凍結したshadow比較へ進む。
