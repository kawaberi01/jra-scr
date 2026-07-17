# 010-JRA予想評価参照API実装仕様書

## 0. 最初に読む要約

- 対象機能: JRA予想・評価参照API
- 改修目的: 保存済み予想と評価をHTTP経由で監査・検索・集計できるようにする。
- 現行仕様の要点: 作成・評価・SQLite保存は実装済みだが、参照APIがない。
- 実装時の最重要注意点: 既存JSON、真偽値、券明細を型付きレスポンスへ復元し、既存の作成・評価ロジックとDBスキーマを変更しない。
- reference_status: `not_found`
- 実コード優先で採用した判断: 既存`BetRecordPage`、`LookupError`、`get_analysis_store()`のパターンを流用する。
- spec_root: `.workstate/jra-srb/jra-prediction-evaluation-read-api/spec/`
- progress_root: `.workstate/jra-srb/jra-prediction-evaluation-read-api/progress/`
- 実装skillへの主入力: `030-JRA予想評価参照API実装指示書.md`、`020-JRA予想評価参照API実装計画書.md`
- ビルド・テスト実行: 実装skill規約により原則として人間へ引き継ぐ。

## 1. 変更後仕様

### 1.1 予想詳細

```http
GET /jra/predictions/{prediction_id}
```

- `PredictionRecord`を返す。
- 予想本体に`prediction_tickets`を含める。
- `pre_race_snapshot_json`は`pre_race_snapshot`、`prediction_json`は`prediction`としてJSON objectを返す。
- 未検出は404 `not_found`。

### 1.2 予想一覧

```http
GET /jra/predictions
```

任意query:

- `race_id`: 完全一致。JRAの12桁形式。
- `from_date`、`to_date`: `races.race_date`による範囲絞り込み。
- `theory_version`: 完全一致。
- `mode`: 完全一致。
- `limit`: 既定100、1以上500以下。
- `offset`: 既定0、0以上。

レスポンスは`PredictionRecordPage(items,total,limit,offset)`。並び順は`created_at desc, prediction_id desc`。

### 1.3 評価詳細

```http
GET /jra/evaluations/{evaluation_id}
```

- `EvaluationRecord`を返す。
- 評価本体に`ticket_results`を含める。
- `evaluation_json`は`evaluation`としてJSON objectを返す。
- integerで保存された判定値はboolへ変換する。nullable列は`bool | null`。
- 未検出は404 `not_found`。

### 1.4 評価一覧

```http
GET /jra/evaluations
```

任意query:

- `evaluation_id`: 追加しない。詳細APIを使う。
- `prediction_id`: 完全一致。
- `race_id`: 完全一致。JRAの12桁形式。
- `from_date`、`to_date`: `races.race_date`による範囲絞り込み。
- `theory_version`: 完全一致。
- `limit`: 既定100、1以上500以下。
- `offset`: 既定0、0以上。

レスポンスは`EvaluationRecordPage(items,total,limit,offset)`。並び順は`created_at desc, evaluation_id desc`。

### 1.5 評価集計

```http
GET /jra/evaluations/summary
```

任意query:

- `from_date`、`to_date`
- `theory_version`

レスポンス`EvaluationSummary`:

- `evaluation_count`
- `total_bet`
- `total_payout`
- `return_rate`: `total_payout / total_bet`。購入額0なら0.0。
- `hit_count`、`hit_rate`
- `gami_count`、`gami_rate`
- `axis_in_top3_count`、`axis_in_top3_rate`: nullableを分母から除外する。
- `middle_hole_in_top3_count`、`middle_hole_in_top3_rate`: nullableを分母から除外する。
- `firework_hit_count`、`firework_hit_rate`: nullableを分母から除外する。
- `max_single_payout`
- `return_rate_without_max_payout`: `(total_payout - max_single_payout) / total_bet`。購入額0なら0.0。

評価0件の場合、件数・金額・率は0または0.0、`max_single_payout`は0とする。

### 1.6 共通異常系

- `from_date > to_date`は400 `bad_request`。
- race_id形式、limit、offsetの入力不正はFastAPI既存handlerにより422 `validation_error`。
- JSON列が壊れている場合は隠蔽せずサーバーエラーとし、今回の範囲で修復処理は追加しない。

## 2. 既存構成における担当

- 入口: `src/jra_srb/app.py`のFastAPI route。
- 入出力モデル: `src/jra_srb/models.py`のPydantic model。
- データアクセス: `AnalysisSQLiteStore`へ詳細・一覧・集計メソッドを追加。
- エラー変換: 既存`LookupError` handler、`BadRequestError` handlerを流用。
- ページング: 既存`BetRecordPage`、`list_bet_records()`の構造を流用。

## 3. 実装配置

- 追加ファイル: なし。
- 修正ファイル: `models.py`、`analysis_store.py`、`app.py`、対象テスト2ファイル、API仕様書。
- 既存流用: `_row_to_dict()`、`_connect()`、`get_analysis_store()`、ページ上限定数、共通例外handler。
- 新規抽象化: なし。RepositoryやServiceを新設せず、既存Store責務へ追加する。

## 4. 根拠

| 判断 | 根拠ファイル | 行 | 備考 |
| --- | --- | --- | --- |
| 作成・評価済みで参照がない | `src/jra_srb/app.py` | 1480, 1496 | POSTのみ存在する。 |
| 予想・評価・券結果を同じSQLiteに保存 | `src/jra_srb/analysis_store.py` | 253-304 | 現行schemaをそのまま読む。 |
| 未検出を404へ変換 | `src/jra_srb/app.py` | 415-417 | `LookupError`を使う。 |
| 一覧ページ形式 | `src/jra_srb/models.py` | 987-991 | `items/total/limit/offset`。 |
| Store一覧実装パターン | `src/jra_srb/analysis_store.py` | 1443-1501 | countとID取得後に詳細を組み立てる。 |

## 5. エラー・ログ・設定

- エラー処理: 既存共通handlerを流用する。
- ログ: 既存HTTP middlewareへ任せ、Store内に新規ログ基盤を追加しない。
- 設定: `JRA_SRB_ANALYSIS_DB_PATH`を既存どおり使用する。新規設定なし。
- 機密情報: レスポンスにDBパスやSQLを含めない。

## 6. Referenceとの差分

| Reference仮説 | 実コードの事実 | 採用判断 |
| --- | --- | --- |
| 適用可能なproject referenceなし | Python/FastAPI/SQLiteの既存構成が正本 | 実コード優先 |

## 7. テスト観点

- Store詳細取得でJSON、bool、券明細が復元される。
- Store一覧で各filter、並び順、total、limit、offsetが正しい。
- 日付filter時に`races`とのjoinが機能する。
- 詳細未検出が`LookupError`となる。
- 評価集計で率、nullable分母、最大払戻除外後回収率、0件が正しい。
- API詳細・一覧・集計の200、詳細404、日付逆転400、query不正422。
- 既存POST予想・評価、実買い記録APIを回帰確認する。

## 8. 対象外

- DB schema/index追加。
- 予想生成・評価計算の変更。
- 作成・評価POST APIのrequest/response model整理。
- Nankan専用route追加。
- MCP公開、認証、CSV/Parquet export、キャッシュ追加。
- 既存のSQLite直接参照スクリプトの置換。

## 9. 要確認事項

- 実装前に対象ファイルの既存未コミット差分と衝突しないことを確認する。競合する場合は変更を上書きせず停止する。

