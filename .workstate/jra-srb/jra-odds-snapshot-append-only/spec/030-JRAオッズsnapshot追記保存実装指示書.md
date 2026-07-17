# 030-JRAオッズsnapshot追記保存実装指示書

## 1. 対象概要

- 対象機能: JRAオッズsnapshot追記保存
- 改修目的: 同一時点ラベルの再取得を別世代として保持する。
- 変更してよい範囲: Store、timeline collector、CLI、関連test、対象progress。
- 変更してはいけない範囲: races/runners、予想・購入、外部provider、無関係なログ。

## 2. 実装順序

1. 旧unique制約検出とtable再構築migrationを追加する。
2. `write_odds()`を常時insertへ変更する。
3. pre-race snapshotの最新1世代選択を時点指定時にも適用する。
4. collector/CLIへ`refresh_existing`を追加する。
5. migration・保存・参照・collector/CLI testを追加する。
6. pytest・ruff・diff check後に進捗を更新する。

## 3. 対象ファイル

| 種別 | パス | 内容 |
| --- | --- | --- |
| Store | `src/jra_srb/analysis_store.py` | schema、migration、write、read |
| Collector | `src/jra_srb/jra_odds_timeline.py` | refresh option |
| CLI | `src/jra_srb/cli.py` | option定義と引渡し |
| Test | `tests/test_analysis_store.py` | append/migration/参照 |
| Test | `tests/test_jra_odds_timeline.py` | skip/refresh |
| Test | `tests/test_cli.py` | parser/引渡し |

## 4. 実装ルール

- 旧snapshot IDをmigration時に変更しない。
- `odds_entries`とのsnapshot ID対応を壊さない。
- migrationは旧3列unique indexが存在する場合だけ実行する。
- 新snapshot IDは書込ごとに衝突しない値とする。
- pre-race snapshotは同一券種を複数返さない。
- timeline APIは世代を省略しない。
- `refresh_existing`既定値は`False`とする。
- 新規Repository/Service/外部依存を追加しない。

## 5. レビュー観点

- 既存DBのデータ損失がないか。
- entryが別snapshotへ誤結合しないか。
- migrationが新DB起動ごとに再実行されないか。
- API互換と全世代参照が両立しているか。
- 明示optionなしに外部requestが増えないか。

## 6. 禁止事項・停止条件

- migrationで既存snapshot/entryを削除したままにしない。
- 仕様外のindex最適化やcleanupを混ぜない。
- 旧schemaを安全に識別できない場合は実装を止める。
