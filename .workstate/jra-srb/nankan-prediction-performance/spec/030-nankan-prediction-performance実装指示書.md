# 030-nankan-prediction-performance実装指示書

## 1. 目的
`prediction-bundle` の API 側遅延を、既存契約を壊さずに短縮する。

今回の実装は「API 側の重複取得削減」に限定する。スキル側の 2 回実行や追加 odds 照会の整理は別タスク。

## 2. 変更してよい範囲
- [nankan_prediction_service.py](D:/develop/jra-scr/src/jra_srb/nankan_prediction_service.py)
- [nankan_service.py](D:/develop/jra-scr/src/jra_srb/nankan_service.py)
- [nankankeiba_pattern_service.py](D:/develop/jra-scr/src/jra_srb/nankankeiba_pattern_service.py)
- 必要なら [models.py](D:/develop/jra-scr/src/jra_srb/models.py)
- テスト:
  - [tests/test_nankan_service.py](D:/develop/jra-scr/tests/test_nankan_service.py)
  - [tests/test_api.py](D:/develop/jra-scr/tests/test_api.py)

## 3. 変更してはいけない範囲
- 既存 `/nankan/...` endpoint の URL 契約変更
- 既存 CLI 契約変更
- スキル / 会話テンプレート変更
- prediction trace 機能の削除

## 4. 実装順序
1. bundle 内共有用の `RaceCard` 再利用経路を入れる
2. `best_time` / `closing_speed` / win odds 補完から card 再取得を外す
3. `get_race_odds()` に source page 共有を入れる
4. pattern bundle を `asyncio.gather()` 化する
5. trend-context の optional 化フックを最小で入れる
6. service / API テストを追加する

## 5. 実装詳細

### 5.1 card 再利用
- `get_race_best_time()` と `get_race_closing_speed()` に、必要なら `card: RaceCard | None = None` のような補助引数を追加してよい
- `card` が渡された場合は `get_race_card()` を呼ばない
- 既存 public 呼び出し元との後方互換は壊さない

### 5.2 win odds 補完
- `_complete_win_odds()` が card を受け取れるようにして、bundle 経路では再取得しない

### 5.3 odds page 共有
- `/odds/...04.do` を `wide` と `quinella` で共有する
- source page を 1 回 fetch し、両 bet type を parse する helper を追加してよい
- `win` は従来通り別 page でよい

### 5.4 pattern 並列化
- `get_pattern_bundle()` 内の category 取得を list comprehension + `asyncio.gather()` に変える
- merge 仕様と返却順は維持する

### 5.5 trend-context フック
- 直ちに API 契約を変えなくてよい
- ただし bundle orchestration の中で将来 skip 判断を差し込める構造にしておく

## 6. テスト観点
- bundle 実行時に card 再取得が減ることを unit test または trace ベースで確認できる
- `wide` と `quinella` が同一 odds page 共有で処理されること
- pattern bundle が従来と同じ categories / runners を返すこと
- 既存 API 形状が維持されること

## 7. 人手確認観点
- 観測ログで `uma_shosai` 本数が減っている
- 観測ログで `program` 本数が減っている
- 観測ログで `/odds/...04.do` が減っている
- `prediction-bundle` elapsed が改善している

## 8. 禁止事項
- ここでスキル側の `prediction-bundle` 2 回実行まで直し始めない
- ここで `refresh=true` 運用の見直しまで広げない
- ここで新しい generic optimization layer を作らない
