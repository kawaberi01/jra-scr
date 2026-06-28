# API 品質追加改修 前提メモ

作成日: 2026-06-28

## 目的

これまでの改修で API の基本契約、入力正規化、保存済み結果 API、CLI、docs 同期は進んだ。次に、運用・公開・長時間処理・レスポンス契約の面でさらに改善すべき点をタスク化する。

## 現在完了済み

- 日本語入力正規化
- `CourseCode` / `BetType` Enum
- 標準エラーレスポンス
- `x-request-id`
- 保存済み結果 API
- 保存済み結果 API のページング
- JSONL / SQLite storage
- 結果収集 CLI
- README / API 仕様同期
- Windows / WSL の `uv` 運用整理
- 全体テスト: `57 passed, 1 skipped, 1 warning`

## まだ弱いところ

- API 側では storage backend を JSONL / SQLite から選べない。
- 収集処理は CLI でしか実行できず、API job として扱えない。
- 外部 JRA への同時実行数や最小アクセス間隔を制御していない。
- ローカル利用前提はあるが、外部公開時の API key / CORS 境界がない。
- API response が内部 model に強く依存している。
- logging はあるが JSON log 出力や request_id の全ログ注入はまだ弱い。

## 優先判断

次は「運用で事故を減らす」順に進める。特に JRA upstream へのアクセス制御と storage 設定統一は、機能追加より先に整える価値が高い。
