# netkeiba analysis.sqlite persistence 前提メモ

## 目的
- netkeiba の `race_result` 由来の補完データを `analysis.sqlite` に保存し、予想エージェント評価で再利用できるようにする。
- netkeiba の `odds_view` は全件保存せず、予想エージェントが参照した買い目だけを保存する。
- 一時キャッシュとは別に、再取得を避ける永続保存層を追加する。

## 前提
- 既存の JRA 公式取得 API/DB スキーマは壊さない。
- JRA race_id と netkeiba race_id は直接一致しないため、保存レコードには両方を保持する。
- ただし現行コードには JRA race_id と netkeiba race_id の自動対応付け情報がない。初期実装では対応表 CSV を入力にしてバッチ保存する。
- スクレイピング対象のため、ライブ取得は上限件数、アクセス間隔、保存済みスキップ、`--refresh` を持つ。

## 対象外
- 予想エージェント本体の実装。
- netkeiba odds 全券種の全件バルク保存。
- JRA race_id と netkeiba race_id の自動照合ロジック。
- 既存 JRA API の永続化仕様変更。
