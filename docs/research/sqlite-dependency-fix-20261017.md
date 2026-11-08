# 現用SQLite依存の修正結果

更新日: 2026-10-17。対象: 依存監査のJ1〜J5/N1〜N3。

## 状態

**後続の実動作確認も完了した。** 2026-10-17 17:54 JST、現用8入口を旧SQLite禁止条件で検証し52項目成功。保存・評価・読戻し、設定不備、SQL障害、旧パス不存在を確認。実SQL変更はrollbackし残存0。[非依存の受入結果](sqlite-independence-acceptance-20261017.md)を最新の判定とする。以下は先行した静的修正時点の記録。

**8コードファイルの修正と静的確認を完了した。実SQLの保存・評価・読戻し、テスト実行は今回行っていない。** 修正内容を実動作確認済み・SQLite全削除可能とは扱わない。

利用者指定の[修正計画110](../../.workstate/jra-srb/sqlserver-model-data-audit/spec/110-現用SQLite依存修正計画.md)を先に保存し、その範囲で実装した。関連スキル5資料も更新。現用コード8本＋手順書5本の計13ファイルを変更した。

## 変更内容

| 対象 | 修正 |
|---|---|
| JRA/南関の予想保存・評価補助4本 | AnalysisSQLiteStore直接生成を廃止。共通build_analysis_storeへ接続。SQL以外のbackendを接続前に拒否 |
| 確度スキルの--from-db読取 | SQLite存在確認と直接接続を廃止。SQL専用ガードと共通open_analysis_readで保存済みスカウトを読む。通常のAPI取得・Markdownの計算は保持 |
| 南関結果保存 | sqlite3接続と独立upsertを撤去。APIのRaceResultを検証して既存Store.write_resultを呼び、共通SQL readerで対象レースの3表件数を読む |
| 日次予想/V89 shadow CLI | SQL設定時は旧DBファイル存在を判定せず、保存済み予想をSQLで確認。明示旧backendの従来不存在処理は維持 |
| スキルの説明とコマンド | SQL保存を指示するよう更新。案件環境のuv run --projectを使用。旧スクリプト名・--db/--from-dbは呼出し互換名として維持 |

スキル補助6本は、読み込んだ案件moduleの所在からroot/data/storage/runtime.envを絶対パスで解決する。明示したJRA_SRB_STORAGE_ENV_FILE・環境変数は従来の共通設定の優先順に従う。設定不足でSQLiteへ接続/作成しない。予想保存・評価の出力backendはsqlserver、dbは実SQL DB名になる。

南関結果保存は既存SQL Storeのtransaction・受領重複制御を再利用する。新しいSQL更新文・schema・索引を追加しない。引数の旧DBファイルや親フォルダを作成しない。

## 静的確認

- 変更Python8本すべてAST構文解析成功。
- 8本のsqlite3.connect/AnalysisSQLiteStore直接生成は0。
- 補助6本のSQL専用ガード・絶対設定ファイル解決を確認。
- CLI2本は`storage_backend() == "sqlite" and not db_path.exists()`とし、SQL分岐では旧ファイルを参照しない。
- 8本の6項目ヘッダー、変更/追加関数の説明不足0。
- 変更前後の改行形式を保持。変更前からある未コミット差分を上書きしない。
- 既存Storeのwrite_result/RaceResult、共通readerの名前付き行・count読取契約、既存予想/評価の呼出し署名に照合。

新規依存ライブラリなし。ファイル操作とAST確認にはuv経由のPython標準ライブラリ、編集にはapply_patchを使用した。

## 実動作で残る確認

| 項目 | 状態・確認方法 |
|---|---|
| 旧パスが存在しない場合のStore選択 | 未実施。ファイルは削除せず存在しない引数パスで、SQL設定が選ばれることを確認する |
| SQL以外・設定不足の拒否 | 静的確認済み、実行未確認。SQL/SQLiteへ接続する前に止まることを確認する |
| 任意の別作業ディレクトリからの設定解決 | 絶対パス化を静的確認、実行未確認。案件のuv環境で実施する |
| 保存済み予想の重複判定 | 未実施。SQL既存行あり/なしと旧ファイル不存在を組み合わせて確認する |
| 予想保存・評価・南関結果保存/件数読戻し | 実SQL書込未実施。保存データと確認範囲を定めて実施する。実レースを架空データで上書きしない |
| 最新スカウトの読戻し | 実SQL読取未実施。同日複数runと保存なしの両方を確認する |

今回は修正開始の依頼に対して実装と静的確認を行った。ユーザーからテスト実行の依頼はないため、テストの追加/実行はしていない。業務書込やAPI取得による確認を自動実行していない。

## 保全・引継ぎ

- [変更前manifest](../../.workstate/jra-srb/sqlserver-model-data-audit/dependency-fix-20261017/manifest-before.json)
- [今回だけの差分](../../.workstate/jra-srb/sqlserver-model-data-audit/dependency-fix-20261017/changes.diff)
- [静的確認と変更後SHA](../../.workstate/jra-srb/sqlserver-model-data-audit/dependency-fix-20261017/static-review.json)
- [次回着手メモ](../../.workstate/jra-srb/sqlserver-model-data-audit/progress/006-次回着手メモ.md)

スキルの実ファイルはC:/Users/main/skills配下であり、jra-scrのGit差分だけでは確認できないため、上記manifest/diffで合わせて追跡する。秘密値・元DB・設定ファイルは保全コピーの対象にしていない。

API/共通Store本体/runtime.env/タスク/SQL/旧モデル/SQLiteを変更せず、取得・研究の再実行・削除は行っていない。旧取得/移行/終了研究の単発ツールを全て再移植する必要はない。
