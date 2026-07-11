# 010-nankan-prediction-performance実装仕様書

## 1. 目的
`prediction-bundle` request 内の重複 upstream 取得を減らし、体感待ち時間を短縮する。

今回の仕様は API 側に限定し、スキル側呼び出し順の整理は別タスクとする。

## 2. 対象
- [nankan_prediction_service.py](D:/develop/jra-scr/src/jra_srb/nankan_prediction_service.py)
- [nankan_service.py](D:/develop/jra-scr/src/jra_srb/nankan_service.py)
- [nankankeiba_pattern_service.py](D:/develop/jra-scr/src/jra_srb/nankankeiba_pattern_service.py)
- 必要に応じて [models.py](D:/develop/jra-scr/src/jra_srb/models.py)
- テスト:
  - [tests/test_nankan_service.py](D:/develop/jra-scr/tests/test_nankan_service.py)
  - [tests/test_api.py](D:/develop/jra-scr/tests/test_api.py)

## 3. 変更後仕様

### 3.1 bundle 内で card を共有する
- `prediction-bundle` が先行取得した `RaceCard` を、後続処理で再利用できるようにする
- 少なくとも次は card を外から受け取れる形にする
  - `get_race_best_time()`
  - `get_race_closing_speed()`
  - win odds 補完処理
  - leading jockey パラメータ生成

期待効果:
- `uma_shosai` の再取得削減
- `program` 補完再取得の連鎖削減

### 3.2 best-time と closing-speed の補助情報解決を共有する
- `best_time` と `closing_speed` はどちらも `card.distance`, `card.course`, `card.surface` を前提にする
- 同一 request では card 由来の距離・コース・馬場を再計算せず共有する
- `fetch_best()` 自体は 2 種必要なので残るが、その前段の card / program 再取得は避ける

### 3.3 odds_summary で同一 odds ページを 1 回だけ取得する
- `/odds/...04.do` を `wide` と `quinella` で別 fetch しない
- source page 単位で共有し、1 回の取得結果から両券種を parse する
- `win` は `/odds/...01.do` を別 fetch のままでよい
- `trio` を含める場合は現行の個別 fetch を維持してよい

期待効果:
- summary 既定の `win,wide,quinella` で 3 fetch 相当から 2 fetch 相当に削減
- `odds_summary` の最重量部分を圧縮

### 3.4 pattern bundle は category 取得を並列化する
- `pattern_kis`
- `pattern_uma`
- `pattern_cho`
- `pattern_kis_cho`

を直列ではなく `asyncio.gather()` で取得する。

注意:
- provider 側の `min_interval_seconds` は維持
- それでも現在の直列実行よりは短縮が見込める

### 3.5 trend-context の軽量化フックを入れる
今回の実装で必ず無効化するとは限らないが、少なくとも次を可能にする。

- bundle 呼び出し側から `include_trend_context: bool` を制御可能にする、または
- `usable=false` 前提ケースで取得自体をスキップできる拡張点を作る

今回の最低ライン:
- 既存契約を壊さず、将来スキップ判断を入れやすい分岐点を service 層に残す

### 3.6 trace で改善効果を比較できる状態を維持する
- 追加済みの prediction trace は維持
- 修正後も同じログから
  - upstream 本数
  - step 秒数
  - card/program/odds 重複
を比較できること

## 4. 非対象
- `prediction-bundle` を 2 回呼んでいるスキル側フローの修正
- 予想後の個別 quinella 照会 4 本の削減
- `refresh=true` の運用見直し
- 会話トークン削減用のプロンプト修正

## 5. 成功条件
- 同一 bundle request 内で `uma_shosai` / `program` の重複本数が減る
- `odds/...04.do` の取得回数が減る
- pattern の step 時間が短縮する
- `prediction-bundle` 全体の elapsed が観測ログで改善する

## 6. 根拠
- 観測ログで `best_time`, `closing_speed`, `odds_summary` が支配的
- 実コードで card 再取得・odds ページ再取得・pattern 逐次取得が確認済み
