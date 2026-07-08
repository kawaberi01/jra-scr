# 010-nankan-prediction-performance実装仕様書

## 0. 最初に読む要約
- 対象機能:
  - 南関予想向け軽量オッズ API
  - 南関予想向け bundle API
  - bundle 専用 CLI
- 改修目的:
  - 予想で毎回複数 API を順番に呼ぶ構成をやめ、1 回の CLI 呼び出しで必要材料を返せるようにする
  - 特に最重の `odds` を全券種既定取得から外し、必要券種だけ返す
- 現行仕様の要点:
  - `call-local-api` は単純な GET ラッパーであり、遅延主因ではない
  - `nankan` 系 API は個別取得前提
  - `get_race_odds()` は券種ごと順次取得し、未指定時は全券種対象
  - pattern は別 service / 別 endpoint として既に存在する
- 実装時の最重要注意点:
  - 既存 endpoint / CLI 契約は壊さない
  - まず体感速度改善を優先し、設計の横断整理は入れない
  - bundle は race_id 解決と card 取得の重複を抑える方向で組み立てる

## 1. 変更後仕様

### 1.1 軽量オッズ API

#### 入力

`GET /nankan/meetings/{date_}/{course}/races/{race_no}/odds-summary`

Path:

- `date_`: 開催日
- `course`: 南関場コード
- `race_no`: レース番号

Query:

- `bet_types`: 任意。カンマ区切り。許可値は `win`, `wide`, `quinella`, `trio`
- `refresh`: 任意。既存 odds endpoint と同じ

既定:

- `bet_types` 未指定時は `win,wide,quinella`

#### 出力

- response model: `RaceOdds`

返却内容:

- `race_id`
- `odds`
  - 指定または既定の summary 対象券種だけを含む
- `fetched_at`
- `source`
- `cache_hit`
- `meta`

#### 正常系

- race_no から 1 回だけ race_id を解決する
- `get_race_odds()` を既定 summary 券種で呼ぶ
- `trifecta`, `exacta`, `place` は summary 既定から除外する
- `bet_types` 指定時は許可された summary 券種のみ返す

#### 異常系

- summary 対象外券種が指定された場合は 400 `bad_request`
- race 未存在時は既存の 404 系挙動に従う
- upstream 失敗時は既存 odds endpoint と同じ error handler に従う

#### 副作用

- 既存 odds cache / snapshot 書き込みルールをそのまま使う
- 新規永続化は行わない

### 1.2 予想 bundle API

#### 入力

`GET /nankan/meetings/{date_}/{course}/races/{race_no}/prediction-bundle`

Path:

- `date_`
- `course`
- `race_no`

Query:

- `meeting_no`: 必須。pattern 用
- `meeting_day`: 必須。pattern 用
- `bet_types`: 任意。`odds-summary` と同じ。未指定時は `win,wide,quinella`
- `refresh`: 任意

#### 出力

- response model: 新規 `NankanPredictionBundle`

返却内容:

- `race_id`
- `date`
- `course`
- `race_no`
- `meeting_no`
- `meeting_day`
- `odds_bet_types`
- `card: RaceCard`
- `odds_summary: RaceOdds`
- `trend_context: NankanMeetingTrendContext`
- `best_time: NankanRaceBestTime`
- `closing_speed: NankanRaceClosingSpeed`
- `pattern: NankankeibaPatternBundle`
- `leading_jockeys: NankanLeadingJockeyPage`
- `fetched_at`
- `cache_hit`
- `meta`

`meta` には少なくとも以下を持たせる。

- `parallelized: bool`
- `used_existing_services: bool`

#### 正常系

- endpoint は専用オーケストレーション service を呼ぶ
- service は次の順で組み立てる
  1. meeting を 1 回取得して `race_id` を解決する
  2. `card` を先に取得する
  3. `trend_context` と `pattern` は card と独立に並列取得する
  4. `odds_summary`, `best_time`, `closing_speed`, `leading_jockeys` は card 解決後に並列取得する
- `leading_jockeys` の入力は card から導出する
  - `course`: path の `course`
  - `distance`: card.distance から数値化できた値
  - `track_condition`: card.track_condition
  - `period`: 既定 `recent_3months`
  - `sort`: 既定 `win_rate`
- `best_time` / `closing_speed` / `odds_summary` は既存 service を再利用する
- `pattern` は既存 `NankankeibaPatternService.get_pattern_bundle()` を再利用する

#### 異常系

- `meeting_no` / `meeting_day` 欠落は 422 validation error
- `bet_types` に summary 対象外が含まれる場合は 400 `bad_request`
- pattern 側だけ失敗した場合も API 全体は失敗させる
  - 理由: 予想 bundle は「必要材料を一括取得する」契約にするため
- race 解決不可、meeting 不存在、upstream 失敗は既存 handler に従う

#### 副作用

- 既存 cache 利用と必要な odds snapshot 書き込みは残る
- 新規 DB 保存は行わない

### 1.3 bundle 専用 CLI

#### 入力

新規 subcommand:

```bash
jra-srb fetch-nankan-prediction-bundle \
  --date 2026-07-08 \
  --course kawasaki \
  --race 11 \
  --meeting 4 \
  --day 2 \
  --bet-types win,wide,quinella \
  --output data/prediction_bundle_20260708_kawasaki_11r.json
```

引数:

- `--date`: 必須
- `--course`: 必須
- `--race`: 必須
- `--meeting`: 必須
- `--day`: 必須
- `--bet-types`: 任意。未指定時は `win,wide,quinella`
- `--base-url`: 任意。既存 `call-local-api` と同じ既定値
- `--refresh`: 任意
- `--output`: 任意

#### 出力

- local API の bundle JSON を pretty print して stdout または file 出力する

#### 正常系

- CLI は local API を 1 回だけ GET する
- 内部実装は `call_local_api()` を流用し、path と query を組み立てて渡す
- `call-local-api` 自体は残す

#### 異常系

- API が 4xx/5xx を返した場合は `call_local_api()` と同じ例外挙動

#### 副作用

- `--output` 指定時のみ file 出力

## 2. 既存構成における担当
- 入口:
  - `src/jra_srb/app.py`
  - `src/jra_srb/cli.py`
- 入力モデル / ViewModel / DTO:
  - `src/jra_srb/models.py`
- 処理配置:
  - `src/jra_srb/nankan_service.py`
  - 新規 `src/jra_srb/nankan_prediction_service.py`
- データアクセス方式:
  - 既存 `NankanService`
  - 既存 `NankankeibaPatternService`
- 表示 / 応答:
  - FastAPI response model と CLI pretty JSON
- 共通処理 / helper:
  - `call_local_api()`
  - 既存の query CSV 解析に近い小 helper

## 3. 実装配置
- 追加ファイル:
  - `src/jra_srb/nankan_prediction_service.py`
- 修正ファイル:
  - `src/jra_srb/models.py`
  - `src/jra_srb/app.py`
  - `src/jra_srb/cli.py`
  - `tests/test_api.py`
  - `tests/test_cli.py`
  - 必要なら `README.md` または `docs/jra/05_API仕様.md`
- 既存流用:
  - `NankanService.get_meeting_trend_context()`
  - `NankanService.get_race_card()`
  - `NankanService.get_race_best_time()`
  - `NankanService.get_race_closing_speed()`
  - `NankanService.get_race_odds()`
  - `NankanService.get_leading_jockeys()`
  - `NankankeibaPatternService.get_pattern_bundle()`
  - `call_local_api()`
- 新規抽象化の有無と理由:
  - `nankan_prediction_service.py` は必要
  - 理由は、`app.py` に cross-service orchestration と `asyncio.gather()` を直書きすると endpoint が肥大化し、bundle CLI/API の共通責務が散るため

## 4. 根拠
| 判断 | 根拠ファイル | 行 | 備考 |
| --- | --- | --- | --- |
| `call-local-api` は既に単純な GET ラッパー | `src/jra_srb/cli.py` | 193, 350 | path + query + pretty JSON |
| pattern bundle は既存 service を再利用できる | `src/jra_srb/nankankeiba_pattern_service.py` | 143 | 既に bundle 返却あり |
| `trend-context` は既存 endpoint / model を持つ | `src/jra_srb/app.py` | 713 | race_no ベースで公開済み |
| `best-time` は内部で card を使う | `src/jra_srb/nankan_service.py` | 313, 317 | card 依存あり |
| `closing-speed` は内部で card を使う | `src/jra_srb/nankan_service.py` | 340, 344 | card 依存あり |
| `odds` は券種ごと順次取得 | `src/jra_srb/nankan_service.py` | 490 | 既定全券種 |
| race_no ベース odds endpoint は既存にある | `src/jra_srb/app.py` | 886 | summary と同じ routing 文脈を使える |
| leading jockey は query ベース | `src/jra_srb/app.py` | 659 | course/distance/track_condition を取る |

## 5. エラー / ログ / 設定
- エラー処理:
  - FastAPI validation は既存通り
  - summary 対象外券種は `BadRequestError`
  - upstream 例外は既存 handler に従う
- ログ:
  - bundle 開始・完了・失敗時に `logger.info` / `logger.exception`
  - `date`, `course`, `race_no`, `meeting_no`, `meeting_day`, `bet_types` を `extra` に含める
- 設定:
  - 既存 `JRA_SRB_LOCAL_API_BASE_URL`
  - 既存 Nankan/provider 側設定を流用し、新規 env は原則追加しない
- 機密情報の扱い:
  - 追加 secret は扱わない

## 6. Reference との差分
| Reference 仮説 | 実コードの事実 | 採用判断 |
| --- | --- | --- |
| `call-local-api` が遅延主因 | 実コードは単純な GET ラッパー | 不採用 |
| `prediction-bundle` は新規 API で束ねるべき | 現状は個別 API 群しかない | 採用 |
| `odds` は必要券種だけ返せば十分 | 実コードは券種指定時にその券種だけ取得できる | 採用 |
| batch 汎用 CLI が必要 | 既存構成では bundle 専用 CLI の方が小さく入る | 今回は不採用 |

## 7. テスト観点
- 自動テスト:
  - `GET /nankan/meetings/.../odds-summary` が既定で `win,wide,quinella` のみ返す
  - `GET /nankan/meetings/.../odds-summary?bet_types=win,wide,trio` が指定券種のみ返す
  - summary 対象外券種指定で 400 を返す
  - `GET /nankan/meetings/.../prediction-bundle` が必要要素をすべて含む
  - bundle endpoint が `meeting_no` / `meeting_day` 必須である
  - CLI parser が `fetch-nankan-prediction-bundle` を受理する
  - CLI が local API URL を 1 本組み立てて pretty JSON を出力する
- 手動確認:
  - local API 起動下で bundle 実行結果が 1 ファイルへ保存できる
  - 実運用の予想フローを bundle 1 回に置き換え可能な JSON 形状である
- 回帰確認:
  - 既存 `call-local-api` テストが通る
  - 既存 pattern CLI / API テストが通る
  - 既存 odds endpoint 契約が変わらない

## 8. 対象外
- 既存予想テンプレートの置き換え
- generic `call-local-api-batch` CLI
- `trend-context` 自身の意味変更
- odds の永続フォーマット見直し
- bundle 失敗時の部分成功返却
- 更なる style-profile 同梱

## 9. 要確認事項
- bundle に `style-profile` も含めるか
  - 現時点では handoff note の優先候補に含まれていないため対象外前提
- `trio` を summary 既定に含めるか
  - 現時点では未指定時 `win,wide,quinella` を既定とし、必要時だけ query 指定する前提
