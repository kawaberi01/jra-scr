# 005-JRA予想評価参照API現行仕様整理

## 1. 現行の入口

| 種別 | 入口 | 現行動作 |
| --- | --- | --- |
| HTTP | `POST /jra/meetings/{date_}/{course}/races/{race_no}/predictions` | 予想材料を取得し、予想と予想券をSQLiteへupsertする。 |
| HTTP | `POST /jra/predictions/{prediction_id}/evaluate` | 保存済み予想と確定結果を照合し、評価と券別結果をSQLiteへupsertする。 |
| Store | `AnalysisSQLiteStore.upsert_prediction_record()` | `predictions`と`prediction_tickets`へ保存する。 |
| Store | `AnalysisSQLiteStore.evaluate_prediction_record()` | `evaluations`と`evaluation_ticket_results`へ保存する。 |

## 2. 現行データ

- `predictions`: ID、race_id、理論版、mode、budget、発走前snapshot JSON、予想JSON、作成日時。
- `prediction_tickets`: 予想券ID、予想ID、race_id、bucket、券種、組み合わせ、金額、理由。
- `evaluations`: 評価ID、予想ID、race_id、理論版、購入額、払戻、回収率、的中・ガミ・軸/中穴/花火指標、評価JSON、作成日時。
- `evaluation_ticket_results`: 評価に属する券単位の的中と払戻。
- `races`: race_idに対応する開催日、開催場、レース番号など。予想保存時にsnapshotから補完される場合がある。

## 3. 現行の不足

- 予想ID指定の詳細取得がない。
- race_id、開催日、理論版、modeによる予想一覧検索がない。
- 評価ID指定の詳細取得がない。
- prediction_id、race_id、開催日、理論版による評価一覧検索がない。
- 評価件数、購入額、払戻、回収率、的中率などの集計APIがない。
- 日次振り返りやライブ監査はSQLiteを直接SQL検索しており、API利用者が同じ情報を取得できない。

## 4. 現行の共通パターン

- ページ形式は`items`、`total`、`limit`、`offset`を使う。
- ページ上限は`MAX_PAGE_LIMIT=500`、既定値は100。
- Storeの未検出は`LookupError`を投げ、FastAPI共通handlerが404 `not_found`へ変換する。
- SQLite rowは辞書化し、JSON文字列を`json.loads()`してレスポンスへ戻す。
- 真偽値はSQLite上のintegerからPydanticのboolへ変換する。
- APIの依存注入は`get_analysis_store()`を使う。

## 5. 影響範囲

- 修正対象: `models.py`、`analysis_store.py`、`app.py`、`test_analysis_store.py`、`test_api.py`、`docs/jra/05_API仕様.md`。
- DBスキーマ変更: なし。
- 外部サイト通信: なし。
- 既存POST APIへの影響: なし。
- MCP公開対象: 今回は追加しない。

## 6. 未確認事項

- 大量データ時の検索性能は未計測。初回は既存ローカルSQLite運用を前提とし、索引追加は別タスクとする。
- `races`に対応行がない予想は、日付絞り込み時には対象外となる。ID・race_id・理論版のみの検索では取得可能とする。

