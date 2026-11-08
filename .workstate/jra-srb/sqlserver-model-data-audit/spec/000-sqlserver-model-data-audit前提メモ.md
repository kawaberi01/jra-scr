# SQL Server研究基盤の前提

作成日: 2026-10-15。状態: 実装前の仕様。対象root: `D:/develop/jra-scr`。

## 最初に読む要約

- 対象機能: SQL Serverだけを使う共通研究基盤。
- 改修目的: 既存`jra_unified`を起点に研究し、研究ごとの元データ・特徴量データの複製をなくす。
- 現行仕様: APIはSQLで稼働を確認済みだが、研究は旧SQLite・年別JSONL・個別評価に依存する経路が残る。
- 最重要注意点: API切替との並行変更を避ける。SQLに存在すること、研究に必要な情報が揃うこと、当時利用可能だったことを分ける。
- reference_status: `not_found`。routerの既定Linux rootは本Windows環境に適合せず、同梱referencesの一覧にも本案件のreferenceなし。実コード・案件証跡を採用。
- 実コード優先の判断: API用SQL接続の流用では履歴schemaを読めない。旧モデルは23項目マスクと非互換。研究専用の読取りとprofile契約を追加する。
- spec_root: `.workstate/jra-srb/sqlserver-model-data-audit/spec/`
- progress_root: `.workstate/jra-srb/sqlserver-model-data-audit/progress/`
- 実装skillの主入力: `030-sqlserver-model-data-audit実装指示書.md` → `020-sqlserver-model-data-audit実装計画書.md`。
- 今回はコード実装・ビルド・テスト・新規DB照会なし。実装時の自動試験・読取り結合試験は060に定義し、今回の成功実績とは扱わない。

## 確定要件

1. 通常研究の業務入力は既存SQL Server `jra_unified`だけ。SQLite、別DB、外部原本ファイル、HTTP取得へのfallbackなし。
2. 新DB・テーブル・ビュー・索引を作らず、既存移送版と来歴を上書きしない。研究はSELECT専用。
3. 元データや学習用特徴量の全量コピーを実験ごとに保存しない。計算はメモリ上、期間と列を限定する。
4. 保存を許すのは設定・来歴・キー・digest・モデル・予測・評価・診断。特徴量行やraw payloadの永続cacheは今回作らない。
5. 同じSQL入力・契約・分割で比較し、研究条件を利用者が年度ごとに手動で組み替えなくてよい構成にする。
6. 初期モデル1本の成功で全体完了にしない。既存研究族の代替経路・必要データ・未達を050で追跡する。
7. API・worker・scheduler・接続設定・migration・他セッションの作業物を変更しない。旧DB・原本・旧成果物は保持する。

## 入力と根拠

- 本会話の利用者指示、既存progress/002・006、`../2026-10-15-data-review.md`。
- 監査JSON: inventory/coverage/latest_scope/normalized_times/integrity。いずれも記録時点の観測。
- API契約: `docs/jra/30_SQLServer_API切替と復旧.md`、既存SQL inventory、storage/sqlserver接続・Store実装。
- 研究実装: 005の根拠表と050の入口一覧。実コード未確認の年度・モデル互換を推測で保証しない。
- Notionは[原本マスターの自足性・全期間統一要件](https://app.notion.com/p/3ee7e56d67ed8160a11acdc59960d001)を読取り参照。適用元は別案件の原本統合であり、現指示に反する旧analysis.sqlite利用は採用しない。全期間の構造統一・不足の区別は整合する。書込みなし。

## 完了を分ける

- **今回の完了**: 仕様・計画・指示・レビューを揃え、初期実装を開始できること。
- **M1基盤受入**: 固定SQL版を使った単勝baseline/basic/crossの縦断実行。全研究移行完了ではない。
- **最終目的達成**: 050の全研究族とその必要profileでSQL限定実行・入力契約・評価・保存検査を通過。未分類・未移行・必要データblockerが0。
- 最新データ不足・当時の時刻未証明・未取得券種を新コードだけで解消できるとはしない。データ補充はAPI側等への契約付き引継ぎとし、未達を隠さない。

## 同時作業の境界

新規研究ファイルと本案件資料を所有範囲とする。APIがimportする共有ファイルの変更は今回の実装契約に含めない。既存scriptsの接続差替えは別作業の更新有無を読取り確認し、競合する場合は新しい研究CLIのadapterに実装する。Git reset/clean/stash、他人の差分の整形・コミットを行わない。
