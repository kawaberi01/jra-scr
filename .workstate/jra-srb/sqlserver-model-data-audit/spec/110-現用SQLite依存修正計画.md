# 現用SQLite依存修正計画・実装契約

作成日: 2026-10-17。利用者の「修正計画を立てて修正を開始」に基づく。対象一覧はdocs/research/sqlite-dependency-audit-20261017.md。

## 目的・対象・影響

現用入口8ファイルのSQLite直接接続・旧Store生成・旧ファイル存在条件を解消し、選択中のSQL Serverを正本として使う。JRA5/共用南関3の範囲に限定し、関連スキルの保存先説明も更新する。

対象はjra-scrの既存scripts2本とC:/Users/main/skills内の補助6本。最新の利用者指示はこの範囲の修正を承認している。API/共通Store本体/SQL schema・索引/runtime.env/タスク/旧モデル/原本/SQLiteは変更しない。研究・取得・移行・削除は行わない。

## 順番

| 順 | 対象 | 修正内容 | 静的完了条件 |
|---|---|---|---|
| 1 | J1/J2/N1/N2の保存・評価補助 | AnalysisSQLiteStore直接生成をbuild_analysis_storeへ変更。案件module位置から絶対runtime.envを解決し、明示環境設定を優先。SQL以外は接続前に拒否。出力backend/dbを実SQLに合わせる | 4本とも直接旧Store生成なし。予想・評価のpayload/読戻し処理を保持 |
| 2 | N3南関結果保存 | RaceResult検証→共通Store.write_result→SQL reader件数確認へ。既存CLI引数は保持 | sqlite3.connect/独自upsertなし。既存SQLのtransaction/受領処理を再利用 |
| 3 | J3確度調査読取 | 任意--from-dbのSQL reader化。絶対設定解決、SQL以外拒否。API通常取得は保持 | 旧ファイル存在条件/直接SQLite読取なし。出力構造を維持 |
| 4 | J4/J5手動CLI重複確認 | sqlserver時は旧ファイル存在を判定せずSQL読取。明示旧backend時だけ従来不存在処理を維持 | SQLの既存予想確認が旧ファイルに依存しない |
| 5 | 関連SKILLと記録 | 保存先をSQL運用の実態へ。旧ファイル名/--dbは互換名と明記。変更範囲・未確認を保存 | SQLiteへ保存する指示との矛盾を解消 |

## 接続設定の取り扱い

- 補助でimportするjra_srb.storage_configの実ファイルから案件rootを解決する。既存のsrc探索はjra_srb/storage.pyの存在を条件とし、旧DBファイル自体の存在は要求しない。
- JRA_SRB_STORAGE_ENV_FILEが明示されていればそれを優先し、未指定時は案件root/data/storage/runtime.envの絶対パスを専用CLIプロセス環境へ設定する。秘密ファイルそのものや値は変更しない。
- SQL専用スキル補助はstorage_backend()!=sqlserverを拒否する。設定不足で自動SQLite生成/読取へ進ませない。共通ライブラリの明示旧backend/export機能は変更しない。
- --db/from-dbは既存呼出し互換の識別引数として残すが、SQL接続先は共通設定から読む。スキル補助で別SQLiteへの出力は行わない。

## 確認と停止条件

- 変更前の対象コード・SKILL本文を小さな作業記録へ保全しSHAを記録。既存の未コミット変更を保持する。
- AST構文・新規/変更関数の日本語説明・直接接続/生成の残存・呼出し先署名・ファイル差分を静的確認する。
- 今回テストの追加/実行、実API/HTTP取得、SQL/SQLiteデータ読取・書込は行わない。存在しない旧パスでの動作、実SQLの保存/評価/読戻しは確認観点として引継ぐ。未実施を成功としない。
- 予想前後・結果精算・順位/買い目方針・表示内容の計算式を変更しない。既存Storeで満たせない契約や対象外変更が必要ならその依存変更を止めて記録する。
- 完了は「8ファイルのコード対応・静的確認」と「実SQL動作確認」を分ける。削除安全の認定は本計画に含めない。
- 上限接近通知/利用者連絡時はrun/PID・変更ファイル・未完・次の1手を保存して停止。正確な５時間枠残率の自動取得手段はない。
