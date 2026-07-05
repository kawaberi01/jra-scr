## 対象機能名
地方競馬 netkeiba API 追加

## 改修目的
`nar.netkeiba.com` から地方競馬の開催日程、開催一覧、出馬表、結果払戻、オッズを取得できる API を既存構成に沿って追加する。

## 現行仕様の要点
- JRA 本体 API と netkeiba 補完 API は責務分離済み
- netkeiba 補完 API は `provider / service / extractors / models / app` の分離で実装済み
- `RaceOdds` と `OddsEntry` は共通再利用されている

## 実装時に最も注意すべき点
- 地方競馬は URL 規則が中央と異なるため、JRA の `MeetingSnapshot` 導線へ無理に乗せない
- `nar.netkeiba.com` 用コードは既存 `netkeiba` モジュールと近い形で独立させる
- `wakuren` / `wakutan` の追加により odds 正規化ルールを中央 API に波及させない

## 実コード優先で採用した判断
- 既存 JRA `CourseCode` は再利用しない
- 既存 `NetkeibaHttpProvider` はホストと取得方法が異なるため流用ではなく別 provider にする
- 既存 `RaceOdds` / `OddsEntry` / `PayoutEntry` は再利用する
- route は JRA と混線しないよう `/nar/...` を新設する

## 追加仕様

### 1. 新規 route 群
- `GET /nar/calendar`
  - query: `year`, `month`, `course` optional
  - 返却: 月内の開催日一覧と会場一覧
- `GET /nar/meetings/{date_}/{course}`
  - `date_` は `YYYY-MM-DD`
  - `course` は地方競馬場コード文字列
  - 返却: 当日の該当場レース一覧
- `GET /nar/races/{race_id}/card`
  - 返却: 出馬表
- `GET /nar/races/{race_id}/result`
  - 返却: 結果払戻
- `GET /nar/races/{race_id}/odds`
  - query: `bet_type`, `combination` optional
  - 返却: オッズ

### 2. route 命名
- 初期実装では `/netkeiba/nar/...` ではなく `/nar/...` を採用する
- 理由:
  - 利用者にとって中央 API と地方 API の区別が明確
  - 既存 `/netkeiba/races/...` は中央 race_id ベース補完 API として残せる

### 3. 新規 provider
- `src/jra_srb/nar_netkeiba_provider.py`
- 役割:
  - `calendar`
  - `race_list`
  - `shutuba`
  - `result`
  - `odds`
  を HTML 取得
- 共通方針:
  - User-Agent 付与
  - timeout
  - 5xx retry
  - min interval
  - fixture provider 対応

### 4. 新規 extractor
- `src/jra_srb/nar_netkeiba_extractors.py`
- 役割:
  - カレンダー HTML から開催日一覧
  - 開催一覧 HTML からレース一覧
  - 出馬表 HTML から `RaceCard` 相当
  - 結果 HTML から `RaceResult` 相当
  - オッズ HTML から `RaceOdds`

### 5. 新規 service
- `src/jra_srb/nar_netkeiba_service.py`
- 役割:
  - provider 呼び出し
  - cache key 管理
  - `bet_type` / `combination` フィルタ
  - 券種ごとの順不同 / 順序付き正規化
  - `kaisai_id` / `race_id` 補助ロジック

### 6. モデル追加
- `src/jra_srb/models.py`
- 新規候補:
  - `NarCourseCode` または `NarVenueCode` 相当 enum / 文字列モデル
  - `NarMeetingRace`
  - `NarMeetingSnapshot`
  - `NarCalendarDay`
  - `NarCalendarPage`
- 既存再利用:
  - `RaceCard`
  - `Runner`
  - `RaceResult`
  - `ResultEntry`
  - `PayoutEntry`
  - `RaceOdds`
  - `OddsEntry`

### 7. 券種仕様
- 初期対応券種:
  - `win`
  - `place`
  - `quinella`
  - `wide`
  - `exacta`
  - `trio`
  - `trifecta`
- 追加対応候補:
  - `wakuren`
  - `wakutan`
- 正規化ルール:
  - 順不同: `quinella`, `wide`, `trio`
  - 順序付き: `exacta`, `trifecta`
  - 単項目: `win`, `place`
  - `wakuren` は順不同
  - `wakutan` は順序付き

### 8. URL / ID ヘルパー
- `kaisai_id = YYYY + jyo_cd + MMDD`
- `race_id = kaisai_id + race_no_2digit`
- helper は provider ではなく service か専用 util に置く

### 9. fixture 方針
- `tests/fixtures/`
  - `nar_calendar_202606.html`
  - `nar_calendar_202606_kawasaki.html`
  - `nar_race_list_2026450615.html`
  - `nar_race_card_202645061501.html`
  - `nar_race_result_202645061501.html`
  - `nar_odds_b0_202645061501.html`
  - 券種別 odds fixture

### 10. 非対応として明示する事項
- 大量取得 / 全月巡回
- DB 永続保存
- 変更情報や新聞など副次ページ
- オッズの全 `type` 完全網羅
- ログイン前提機能

## 返却仕様の方向性

### calendar
- `year`
- `month`
- `course` optional
- `days`
  - `date`
  - `venues`

### meeting
- `date`
- `course`
- `kaisai_id`
- `races`
  - `race_no`
  - `race_id`
  - `race_name`
  - `start_time`

### card / result / odds
- 既存 JRA / netkeiba 補完 API とできるだけ揃える

## 未確定事項
- オッズ `type=b0..` と券種の完全対応表
- NAR 用 enum を厳格型にするか、文字列で受けるか
- `/nar/meetings/{date}/{course}` で `kaisai_id` を内部推定だけで足りるか、calendar 経由解決を必須にするか
- `wakuren` / `wakutan` を初回から API モデル上も公開するか
