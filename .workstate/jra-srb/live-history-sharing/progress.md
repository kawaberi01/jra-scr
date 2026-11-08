# 当日共通履歴の実行内共有 実装結果

更新日: 2026-10-18 JST。利用者の明示した修正依頼に基づく。

## 完了した変更

- LiveHistoryContext/LiveHistorySnapshotをjra_history_dataset.pyへ追加。最初のカードで履歴を1回だけ取得し、生涯成績と近走5走の当日用集計を各1回構築。SQL接続は取得直後に閉じ、メモリ上の行・集計だけを共有する。
- 初回SELECTに結果表側のCOUNT OVERを追加。runnerとの結合で落ちる着順やNULL着順も、従来の近走特徴の頭数分母に残す。対象日前・公式source・払戻あり等の既存母集団を維持。
- SQL Serverの通常reader SELECTに限り、呼出元が明示したhash_join=TrueでOPTION(HASH JOIN)を追加。全SQLへの適用ではない。DBの索引・統計・権限・timeout設定変更なし。saは使わない。
- build_live_feature_records/build_artifact_live_records/append_recent_form_live_featuresに任意のhistory_contextを追加。43/49列の当日特徴と算出式は維持。
- APIスカウトの外部カード経路・保存カード経路、CatBoost日次CLIでrun/mainごとに新しいcontextを所有。2レース目以降の共通履歴再取得・当日用再集計をなくす。
- APIの同期履歴処理をto_threadへ移し、共有初回ロードはLockで1回に制限。同じrun中の読込障害を記憶し、各レースで同じSQL障害を再試行しない。
- 別日/別DBへのcontext流用を拒否。未知馬の参照で共通集計を変更しない。グローバルcache・DB別テーブル・永続cacheは追加しない。
- CatBoostのラップ生成前に作る過去datasetにも取得済み行を渡す。この過去datasetは過去各レース時点の特徴を作る別計算なので、従来どおり1回生成するがSQLで共通履歴を取り直さない。
- 最新カード・取消・オッズのレース別経路、順位政策・モデル重み・R1専用履歴は変更しない。過去日固定の保存比較scriptは対象外。

## 検証

- 関連10ファイル: 99 passed、2 skipped、既存Pydantic deprecation warning 1件。skipは明示フラグが必要な既存の実SQL purity検証。今回の通常reader実SQL検証は別途実施済み。
- 新規テスト7件: 従来の近走SQLとの49列一致、未結合結果の頭数分母、対象日/未来・非公式source・払戻なし除外、並行初回ロード1回、失敗時再取得なし、日付/DB分離、API両経路の複数カード共有とrun間再取得、CatBoost live→過去datasetの取得1回、hint限定等。
- 初回テストでは新規fixtureの列数とCOUNT_BIGへの変換に対する期待文字列に誤りがあり、テストを修正。アプリの計算値変更で合わせていない。
- 研究履歴同値テストのMemoryConnectionを、追加したhistory_field_size列を返す契約へ追随させた。研究モデル・研究入力の変更なし。
- 通常reader実データ: sql_history_selects=1、history_aggregations=1、取得後connection_closed=true、sysadmin=0/db_owner=0、SQLite/旧JSONLをaudit guardで拒否。
- 全101,408行の既存13列multiset SHA256が変更前のa01cec6fde06c1c8acbcf74d99793e74956d143e48f893d192bdb8fab2a297e2と完全一致。
- 初回取得・集計・保存カード49特徴生成: 11.098949秒。以後同じ保存カードで35回特徴生成: 合計0.051536秒、SQL再取得なし、特徴recordの完全一致。
- この実測は保存カードの特徴生成を36回行ったもの。全36レースの外部カード/オッズ取得・モデル比較の所要時間ではない。スカウト全体が何秒で完走するかは未測定。
- git diff --check成功。既存CRLFを主とする変更ファイルはCRLFへ揃え、巨大な文字コード差分なし。

## 成果物と反映範囲

- 契約: implementation-contract.md。
- 新規テスト: tests/test_jra_live_history_sharing.py。
- 実SQL検証: verify_live_sql.py、artifacts/diagnostics/live-history-sharing-20261018.json。
- 既存依存と標準ライブラリのみ。恒久依存追加・コミット・API再起動・DB更新なし。
- 稼働中APIはこの作業では再起動していない。コードを読み直す次回起動から修正が適用される。CLIは新しいプロセスで起動すれば適用される。
- 他セッションで研究002/006が更新されているため、本フォルダーに実装記録を分離して保存した。

## 次に確認する場合

稼働APIへ反映したうえで全日スカウトを1回実行し、開催一覧との36R照合・最新カードと取消/除外・欠測・各段階の所要時間を確認する。今回の修正・検証だけで全日候補や3モデル比較の完了とは扱わない。
