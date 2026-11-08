# SQLite依存確認：現行入口・スキル・定期処理

確認日: 2026-10-17 JST。目的: SQLite削除前に、現行処理が実際に旧ファイルへ依存するかを確認する。

**最新判定：現用8ファイルの修正・実SQL確認を完了。旧SQLite非依存を受入済み。** [最終受入結果](sqlite-independence-acceptance-20261017.md)を参照。52項目成功・禁止アクセス0・rollback後検証行0。以下は先行監査時点の記録であり、未対応/未実施という記載は当時の状態。

**修正段階の最新情報:** 利用者の追加指示に基づき、下記8ファイルと関連スキル5資料のコード/説明修正・静的確認を完了した。[修正結果](sqlite-dependency-fix-20261017.md)。以下の未対応記述は修正前の監査結果であり、実動作確認は別途未実施。SQLite削除の承認ではない。

## 1. 結論

**通常API・日次タスクはSQL backendへ切替済み。一方、手動予想CLIとスキル補助に、修正が必要な依存が8ファイル残る。** データの再取得・再投入が必要という意味ではない。

監査時点では依存の解消は未実施だった。後続で下表のコード修正と静的確認を完了。次はSQL設定・旧ファイル不存在での実動作確認が残る。全SQLiteの削除可とは判断しない。

## 2. 確認方法と範囲

- jra-scrのsrc/scripts/tools、研究用.workstate/jra-srb、保存予想のコード、jra-van-dataのsrc/tools、関連JRA・共用南関スキルを対象に339コードファイルを静的確認。PythonはASTでimport aliasも追跡し、SQLite接続・旧Store生成を抽出。C#のSqliteConnection生成も確認。
- 接続・旧Store生成94箇所/69ファイルを分類。importや型注釈だけのsqlite3、引数名analysis.sqliteを実接続と混同しない。
- Windows登録タスク206件を列挙し、名称またはactionにJRA/JV-Linkを含む3件の実action・作業ディレクトリを確認。
- 関連プロセス、8000番のlisten PID15068、HTTP /healthのstatus=okを確認。新規API・収集処理は起動していない。
- 現在のシェルと案件rootで解決する設定はbackend=sqlserver、DB=jra_unified、results_storage=sqlserver。秘密値・コマンド全文を証跡へ保存していない。
- 通常API切替の既存[完了監査](../../.workstate/jra-srb/sqlserver-api-cutover/completion-audit.md)と[運用資料](../jra/30_SQLServer_API切替と復旧.md)を再利用。SQLiteとの再照合・回帰テストは再実行していない。

SQLite内容読取、SQLデータ照会、収集、学習、タスク変更、コード修正、削除は行っていない。今回のコード確認は、SQL実接続での業務全件動作試験の代わりではない。

## 3. 修正対象：JRA関連5ファイル

| ID | 対象 | 実際の依存・影響 | 必要な対応 |
|---|---|---|---|
| J1 | [予想保存スキル補助](C:/Users/main/skills/jra-race-session-complete/scripts/save_jra_prediction_to_analysis_sqlite.py:35) | AnalysisSQLiteStoreを直接生成。SQL選択時はStore側のガードで拒否され、保存できない。既にSQL設定の現在も到達時に問題となる | build_analysis_storeへ統一し、保存後の読戻しもSQLで行う。表示のdb名も実backendと整合させる |
| J2 | [予想評価スキル補助](C:/Users/main/skills/jra-race-session-complete/scripts/evaluate_saved_prediction_to_analysis_sqlite.py:35) | J1と同じ直接生成。SQLの予想を評価する入口として未対応 | 共通factoryへ統一する |
| J3 | [全レース確度スキルの調査用入口](C:/Users/main/skills/jra-day-confidence-ranking/scripts/rank_confidence.py:82) | --from-db指定時にSQLite存在確認と直接connect。通常のAPI取得では使わないが、明示調査経路が残る | 共通SQL reader/Storeで同日の保存結果を読む。SQLiteへ自動補完しない |
| J4 | [日次予想CLIの既存予想確認](../../scripts/jra_live_prediction_day.py:81) | _has_predictionはSQLiteファイルがないとSQLを照会せずFalse。削除後、SQL保存済み予想を未保存と誤認し再生成し得る | SQL backendではファイル存在条件を通らずSQLを確認する |
| J5 | [V89 shadow CLIの重複確認](../../scripts/jra_major_venue_shadow_day.py:34) | _already_savedにJ4と同じ存在条件。書込先自体はSQL factoryだが、削除後の重複抑止に影響 | 同上。SQL保存済み理論版をSQLで確認する |

J1/J2は単なるファイル名の古さではなく、呼び出すクラスが違う。J4/J5は直接SQLite接続ではないが、旧ファイルの存在に挙動が依存するため修正対象に含めた。

## 4. 同じ分析DBを使う南関スキル3ファイル

| ID | 対象 | 実際の依存・影響 | 必要な対応 |
|---|---|---|---|
| N1 | [南関予想保存](C:/Users/main/skills/nankan-race-session-complete/scripts/save_nankan_prediction_to_analysis_sqlite.py:39) | AnalysisSQLiteStore直接生成。SQL設定で拒否される | 共通factoryへ統一 |
| N2 | [南関予想評価](C:/Users/main/skills/nankan-race-session-complete/scripts/evaluate_saved_prediction_to_analysis_sqlite.py:35) | 同上 | 同上 |
| N3 | [南関結果保存](C:/Users/main/skills/nankan-result-save-to-analysis-sqlite/scripts/save_nankan_result_to_analysis_sqlite.py:49) | data/db/analysis.sqliteへsqlite3.connectで直接書込。SQL factoryの旧writer拒否を迂回する | 既存SQL Storeの結果保存経路へ統一し、独立したSQLite書込を止める |

JRA研究の方式追加は不要だが、同じSQLiteファイルを整理するため、共用する入口として確認対象に含めた。今回これらを実行しておらず、実際に最近書き込まれたと認定したわけではない。

## 5. 通常SQL経路で問題にならないもの

| 対象 | 確認結果 |
|---|---|
| API/MCP・予想/購入/結果/評価・cache/jobs | app/cliから共通storage factoryへ。sqlserver選択時はSqlServer系Storeへ分岐し、自動SQLite fallbackなし。既存完了監査あり |
| 日次JRA-SRB-Odds-Daily | Ready。WorkingDirectory=D:/develop/jra-scr、run_jra_odds_timeline_today.ps1→collect-jra-odds-timeline→共通factory。--dbの文字列がanalysis.sqliteでもSQL backend時はSQLiteを開かない |
| 週次Saturday/Sunday | 両方Disabled。同じPS1と作業ディレクトリ。無効状態を変更していない |
| 履歴・近走・ラップ、CatBoostスカウトの通常DB読取 | open_analysis_read/build_analysis_storeへ接続。型注釈や引数名のSQLite表記は、それだけでは旧DB依存ではない |
| S06/S08の新SQL研究 | 専用reader。④の成功runでSQLite/旧JSONL拒否ガード付きの学習・評価済み。旧traceの履歴もSQL化済み |
| 旧analysis/cache/jobs/batch実装 | 明示旧backendまたは明示--storage sqlite出力のために残る。SQL運用の通常factoryでは選択しない。明示exportで新しいSQLiteを作る能力と、既存の元SQLiteが必要なことは別 |

## 6. 再移行しない旧処理

| 分類 | 抽出箇所数 | 扱い |
|---|---:|---|
| 明示旧backend・export | 9 | 通常SQLから選択しない。明示旧backendを通常運用へ戻さない |
| 旧ファイル指定の学習export | 3 | build_jra_odds_asof_dataset / build_jra_o1o2_asof_dataset / build_v89_recovery_2025_audit。新研究の入力に使用しない |
| 移行・比較・復旧用管理操作 | 5 | 明示的な旧ファイル比較/復元用。通常業務や研究の自動依存ではない。保管計画と合わせて必要性を判断する |
| 過去の単発研究・予想コード | 37 | 今回の通常src/scripts・スキルに対象入口名の参照は見つからず、登録タスクからも呼ばれていない。旧score_day.py等を直接実行すると旧DBが必要なため、旧研究記録として保持し再実行しない |
| 契約終了した旧JV-Link取得本体 | 6 | jra-van-dataの取得コードは今もSQLite実装。対象exporterの稼働プロセス/関連登録タスクは今回見つからない。取得自体を終了した経路として扱い、SQL研究のために移植・再起動しない |
| 旧取得・監視・解析・移行ツール | 28 | 原本SQLiteを明示入力にする手動ツール。今回関連タスクから自動呼出しなし。研究へ戻すための再取得/全量再投入はしない |
| 現用スキルの修正対象 | 6 | J1〜J3、N1〜N3。上記表のとおり修正が必要 |

94は接続/生成箇所の数であり、現用の未対応モデル数や未移行データ件数ではない。ファイル存在条件J4/J5は94箇所とは別に検出した。

## 7. 修正の順番と完了条件

1. J1/J2とN1/N2の4補助を共通factoryへ変更。各スキルの「SQLiteへ保存」という説明も実backendに合わせる。
2. N3の直接書込を既存のSQL結果保存へ統一、J3の任意読取を共通SQL経路へ変更。
3. J4/J5のファイル存在条件をSQL設定に依存しない形へ修正。
4. SQL設定・存在しない旧パスで各入口の選択先/既存保存判定を確認する。実ファイルを削除・改名して試す必要はない。テストや書込試験を行う場合は別途範囲を定める。
5. この8ファイルの解消結果を本資料へ反映し、研究へ戻る。過去研究や取得ツールすべてを動かせるようにすることは条件にしない。

依存確認と削除承認は分ける。削除時には対象版が移行証明対象か、固定後更新がないか、必要な保管があるかを既存証跡で確認する。

## 8. 証跡と確認の限界

- [コード抽出JSON](../../.workstate/jra-srb/sqlserver-model-data-audit/dependency-audit-20261017-code.json)：339ファイル、Python構文エラー0。
- [接続箇所分類CSV](../../.workstate/jra-srb/sqlserver-model-data-audit/dependency-audit-20261017-classification.csv)：94箇所、所在分類の未分類0。分類は実動作成功を意味しない。
- [登録タスクJSON](../../.workstate/jra-srb/sqlserver-model-data-audit/dependency-audit-20261017-tasks.json)：206タスクから関連3件。
- [プロセス/シェル設定観測](../../.workstate/jra-srb/sqlserver-model-data-audit/dependency-audit-20261017-runtime.json)：最初のタスクaction投影が不完全だったため、タスクは上記専用JSONを正とする。プロセス抽出には監査自身やエディタも含まれ、全行を稼働writerと解釈しない。

確認範囲は上記2案件・関連スキル・名称/actionで関連付けられた登録タスク。任意の別案件・PC全体のファイルハンドルを監査したものではない。APIプロセス内部の環境変数を取得していないため、現在シェルの設定と、既存API切替/稼働記録を区別する。/health正常だけで全SQL操作成功とは判断しない。

今回の作業ではデータと現用コードは変更していない。必要な修正対象を具体化して保存した。
