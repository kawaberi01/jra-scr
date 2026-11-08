# 実装開始指示

作成日: 2026-10-15。対象: `D:/develop/jra-scr`のSQL Server共通研究基盤。

## 2026-10-15 実装時の追加許可と境界

利用者の継続目標は実装・不具合改修・データ再検証・不足投入・研究可能状態まで。したがって下記の「DB更新/取得は別担当」は、研究reader自体のSELECT専用契約として維持し、管理用の不足補充作業まで禁止するものとはしない。研究用7表にjra_readerのVIEW DEFINITIONだけを付与し、DML/DDL権限は付与しない。新規の研究専用秘密ファイル`data/storage/research.env`（Git管理外）を用意し、API runtime.envは保持する。

不足結果は`scripts/repair_jra_research_results.py`から既存result/save APIへ投入し、公式開催から欠落レース行を発見した時だけ既存SQL factoryのwrite_raceを使う。管理用の明示--applyに限り、研究CLI/モデルからこのwriterを呼ばない。APIコード・設定・scheduler・既存schema・移送snapshot・旧DB・NAS原本は変更しない。取得時刻を当時の受領時刻に偽装しない。

## 1. 最初に読むものと目的

030 → 020 → 010 → 040 → 050 → 060 → progress/002・004。目的は`jra_unified`だけで研究でき、実験ごとの元データ/特徴量コピーを増やさないこと。今回の実装開始単位はM0〜M1。後続M2〜M5も全体残作業として維持する。

現物確認の根拠は005、品質とscopeの前提は000。API切替は別セッションの作業物を読取り確認するだけ。本仕様はAPI変更を承認するものではない。

## 2. 変更してよい範囲

- 010の新規`jra_research_*.py`、新CLI、`configs/research/`の非秘密設定、060の新規tests、本案件spec/progress。
- 後続profile接続で、APIからimportされず別作業の変更と競合しないと確認できた研究scripts/研究専用modelの局所変更。対象と意味をregistryへ記録。
- 純関数再利用は引数/戻り値/副作用を調べたものだけ。既存scriptを無条件importして旧readerを呼ばない。

## 3. 変更禁止

`app.py/cli.py/storage.py/storage_config.py/sqlserver_*.py/analysis_store.py/jobs.py/models.py`、APIが使うhistory/recent/lap/V理論等の共有モジュール、runtime.env、scheduler、migration、SQLオブジェクト、他の.workstate案件。pyproject/uv.lockの無関係な変更も行わない。必要な依存は既存extrasを使い、追加が不可避なら理由と差分を別契約にする。

旧SQLite・NAS原本・年別JSONL・既存artifactを削除/移動/上書きしない。全4.7億行の再投入・無制限JOIN・APIのprovider呼出・起動/停止・ready更新は禁止。研究入力を外部ファイルで補完しない。

## 4. 着手順序

1. `rtk git status --short`と本案件ファイルを確認し、他作業差分を保持。050の対象入口を限定走査し、対象/除外/variantをregistryへ固定する。
2. contracts、readerの接続/権限/schema preflight、設定validationの小さい縦断実装を作る。まだモデル全族を変更しない。
3. M0bを少数キーで実施。driverのreader接続、固定版、JSON/精算単位/ロスター/マスクを検査。失敗時は依存処理停止。秘密や業務本文をログへ出さない。
4. 040のfrozen reader/coverage、InputRaceとOutcomeBundleの分離、digestを実装。学習前にSQL接続を閉じる。
5. basic8/cross9とmarket baseline、単勝共通精算、manifest/artifact、CLIをつなぐ。モデルは新規学習、旧joblibを流用しない。
6. 060のT01〜12を実施し、M1受入を記録。品質や除外条件を弱めて通さない。
7. M2〜M5を050に沿って順次実装。旧研究の意味を同じと証明できない場合は差分とblockerを残す。モデル1本で全体completeにしない。

## 5. 追加判断をしないための契約

- データ・版・時点・精算: 040。学習/購入/保存設定: 010・020。各研究族: 050。テスト: 060。
- 出力先: `artifacts/jra_research/runs/<run_id>/`のみ。run毎のraw/odds/features/dataframe/SQL結果ファイルを作らない。
- 研究reader資格情報は`JRA_SRB_RESEARCH_READER_CONNECTION_STRING`。無ければ3で停止し、API writerや旧DBへ切り替えない。
- SQL timeout後は自動再試行せず、query_id/期間/SQLSTATE等を秘密除去して記録。別のデータを使って成功に見せない。
- generated featuresの意図NULLは欠損補完しない。旧モデル互換性はprofileごとの契約検査を必須とする。
- 確定していないraw SHA結合や未登録ID変換を実装者の推測で埋めない。

## 6. 停止条件と報告内容

M1は接続/権限/schema/source/label単位/特徴量定義の不一致時に停止。権限管理やデータ補充が必要なら、必要表/列/期間/券種/時点/版/期待状態を004とfailureへ記録する。API側の実装を並行修正しない。

M2以降のprofile blockerは当該profileだけ止め、独立した他profileの作業は続けられる。外部取得不能などで要求全体を満たせない場合は、実現した範囲・未達要件・根拠・再開条件を明示する。仕様変更やscope縮小を黙って行わない。

## 7. 静的レビューと検証引継ぎ

R01の独立実装契約: analysis-currentの明示snapshotから既存history builderと同じ公式source・結果/runner結合・払戻存在条件を固定SELECTで読む。最古保存結果からの履歴を維持し、既存build_history_dataset_from_rows/append_recent_form_features/train_history_modelsの純計算を再利用する。元データ/特徴量file生成・SQLite接続・HTTP取得・API共有module改修は行わない。二巡digest照合、権限/版検査、学習前close、契約付きmodelと評価だけを共通run配下へ保存する。M2原本metadata lookup不足とは独立して進められる。履歴モデルの最終全量refitと時系列holdoutを既存通り区別し、当時カード利用可能性はretrospective研究品質とする。

R01の読取route: live.races/runners/result_entries/payoutsは固定34版の少数表（約8千/11万/10万/9万行）をそれぞれ一意(snapshot,rowid)索引で有界一巡し、必要列だけをメモリ結合する。上限は各表max_candidate_rows・一chunk最大1万行・最大二巡、実走査件数をprovenanceへ記録する。これは明示した4表だけの契約で、21M原本表や264M parsed表へ拡張しない。JOIN後TOPの重複行欠落を避け、レース/結果/出走の業務キー重複は停止する。

R11の独立route（2026-10-16実metadataに基づく追加）: live.races / netkeiba_race_results / netkeiba_result_entries / netkeiba_odds_entries / netkeiba_payoutsだけを明示analysis-current版で読む。全snapshot合計の概数は約1.6万/1.5万/19.8万/89.8万/17.2万、各表に有効な非filtered unique(snapshot,rowid)があることをmetadata auditで確認した。各表各巡100万行以下、chunk1万行以下、全体2巡まで。二巡目は内容digestだけを照合し、全データを二重保持しない。元データ出力なし。原本/parsedや他表へこのrouteを拡張しない。

R11はnetkeiba結果parentとwide各行の明示source・fetched_atを照合し、同じcaptureと証明できない入力を同時点扱いしない。親/子のnetkeiba ID・保存済みjra_race_id・開催属性を照合し、文字列位置で変換しない。重複price/payoutをlast-write-winsしない。正常順位と完全なwide的中組合せ/正の実払戻を検査してから、外れだけを0円とする。同着/取消/不完全データは今回推測せず除外理由を保持する。旧コードにない検査で変わる母集団をcoverageへ残し、旧全体互換・研究族受入を自動宣言しない。scoreは対象rank/payoutをSQLから読まず、結果を使う適格条件を入力選択へ流用しない。

R11の競馬場属性は、走路説明が保存されていたlive.races.courseとnetkeibaの場名を直接比較しない。登録済みhistory.race_identity_mapの明示source_snapshot/source_relationのindex prefixを、別上限9000行で完全読取してvenue/date/race_noを照合する。未解決は採用せず、対象年のverifiedが0なら市場5表の読取前に停止。computed hashを算出・選択・述語・結合・並び順・一致証拠に使わず、元IDのbinary表現とmap_idで順序を固定する。M4のhashed point lookupに必要な定義可視性ゲートを緩めるものではない。名称対応は既存COURSE_CODES/COURSE_ALIASESの定義と内容SHAを記録する。

新規Python先頭に日本語docstring（概要/作成日/入力/出力/実行例/注意事項）、関数/クラスに役割・Args/Returns/Raises/Notesを必要に応じ記載。既存規約を優先し無関係ファイルへ説明を追加しない。

全SQLのsnapshot/キー/horizon/market条件、モデル入力に結果がないこと、mask/型/単位、sourceのwhole-bundle選択、dirty code hash、許可成果物、例外停止・closeを確認する。T01〜12/必要なT71〜79のコマンド候補は060にある。今回の仕様作成ではビルド/テストは行っていないため、実装者が変更に応じて実行し結果をprogress/005へ記録する。

区切りで001/002/004/006を最新化、重要判断は003、試験は005へ追記。Notionへは保存しない。


## 2026-10-16 R13独立純計算の実装範囲

- R13 market_overlay_sql_v1 / win_overlay_sql_v1 の旧2scriptとevaluatorの必要pure helperだけを、新規研究専用moduleへ移す。shared/API/旧scriptを変更しない。SQL/CLI/保存との接続は別工程。
- 20特徴量、wideの40 min/max特徴量（欠損時は旧左右順）、2025年のみcold start、日付全体の特徴量を先に構築して日末履歴追加を維持。R01のrace毎履歴を流用しない。
- C=(.01,.03,.1,.3,1)、threshold=1.00..1.45を各10、train<=06/30/dev<=09/30/holdout以降、median imputer→standard scaler→logistic max_iter500/random_state0を維持。
- 候補入力とラベル/払戻を分離する。予測/採否には結果を参照しない。明示払戻がない候補を0円と推定しない。旧pureとの合成同値、同日/未来結果の非混入、50候補・形状を検証する。
- R11で判明した2025登録ID対応不足はSQL受入への依存。純計算の成功だけでR13をverifiedへ変更しない。取得時点/精算/全母集団同値・実SQLscore/replayは別途必要。
