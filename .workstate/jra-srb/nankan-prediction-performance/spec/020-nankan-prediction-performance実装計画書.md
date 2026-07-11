# 020-nankan-prediction-performance実装計画書

## 1. 実装方針
大きい新機能追加ではなく、既存 API 契約を維持した内部最適化として進める。

優先順位は次の通り。

1. card 再利用
2. odds source page 共有
3. pattern 並列化
4. trend-context 軽量化フック

## 2. タスク

| ID | 作業 | 対象 | 完了条件 |
| --- | --- | --- | --- |
| P01 | bundle 内部で共有する request-local 材料を定義 | `nankan_prediction_service.py` | `card` と派生値の共有方針が決まる |
| P02 | `best_time` / `closing_speed` / win odds 補完が card を受け取れるようにする | `nankan_service.py` | 同一 request で `get_race_card()` 再呼び出しを避けられる |
| P03 | odds source page 共有ロジックを追加 | `nankan_service.py` | `wide` と `quinella` が同一 page fetch から構成される |
| P04 | pattern bundle を category 並列取得へ変更 | `nankankeiba_pattern_service.py` | 4 category の逐次 await がなくなる |
| P05 | trend-context を optional 化できるフックを service に置く | `nankan_prediction_service.py` ほか | 将来の skip 制御点ができる |
| P06 | 既存 trace で比較できることを確認 | trace + tests | 修正前後比較が可能 |
| P07 | service / API テスト追加 | `tests` | 重複削減ロジックと既存契約を検証できる |

## 3. 実装順
1. P02 を先に行い、card 再利用の土台を作る
2. P03 で `odds_summary` の最重量部分を削る
3. P04 で pattern を短縮する
4. P05 は最小の制御点だけ入れる
5. P07 で回帰防止を付ける

## 4. 検証観点
- `prediction-bundle` 実行時:
  - `upstream_request` の `uma_shosai` 本数
  - `program` 本数
  - `odds/...04.do` 本数
  - `pattern_*` 4 本の並び
- 回帰:
  - API レスポンス形状が変わらない
  - 既存 test fixture で結果が保たれる

## 5. リスク
- card を外から渡す形にすると service API の変更範囲がやや広がる
- odds page 共有は parse の責務整理が甘いと分岐が増える
- pattern 並列化は provider のスロットル設定と干渉しうる

## 6. 停止条件
- 既存 endpoint 契約変更が必要になった場合
- cache の意味を崩さないと実装できない場合
- 重複削減のために大規模な責務再編が必要になった場合
