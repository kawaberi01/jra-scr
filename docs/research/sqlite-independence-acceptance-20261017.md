# 現用処理の旧SQLite非依存：受入結果

確認日時: 2026-10-17 17:54〜17:55 JST。

## 判定

**現在選択しているSQL Server設定で、監査対象の現用処理は旧SQLiteを参照せず動作する。旧SQLiteを現用処理のためにPCへ置いておく必要はない。容量を空ける計画へ進める。**

前回残っていたJ1〜J5/N1〜N3の実動作確認を完了した。存在しない旧パスを渡し、SQLite接続・旧データファイルのopen・SQLiteパスのexists判定を禁止して実行した。52項目すべて成功、禁止アクセス試行0件。旧SQLiteの内容は読んでいない。

これは以下の現用入口とSQL研究入口についての判定である。過去の終了研究・移行・復旧ツールを含めた全コードの再実行保証や、全98ファイルの無条件削除許可ではない。

## 新たに実行した確認

| 対象 | 結果 |
|---|---|
| JRA/南関の保存・評価4補助、南関結果保存 | 旧ファイルなし・別cwdでSQL Storeを選択。実SQLで予想と買い目、結果と払戻、評価を保存・読戻し。100円の単勝に250円の払戻が正しく評価された |
| SQL reader | 本来のreader接続でDB名、baseline/権限、既存予想の読取成功 |
| 手動日次/V89 shadowの既存予想確認 | 両方とも不存在/保存済みを正しく判定。旧ファイルexistsは呼ばれなかった |
| 最新スカウトの読取 | 別cwd・旧パス不存在で同日2runから新しい方とその明細を選択。未保存日は所定のエラー |
| 設定不備 | 補助6本でsqlite選択とreader設定不足を接続前に拒否 |
| SQL障害 | SQL接続失敗を永続化エラーとして返し、SQLiteへfallbackしない |
| 後始末 | SQL rollback後、別実接続で10業務表とwrite_receiptsの検証ID残存0。旧パス未作成 |
| 現在稼働中のAPI | /health、保存済み予想一覧がHTTP200。予想一覧1件を同じ条件の直接SQL Store応答と比較して完全一致 |

52項目は新規スクリプトのcheck数であり、全業務シナリオ数ではない。現用8ファイルのSHAを実行結果へ記録した。

## SQLへの影響と試験条件

実DBはjra_unified。本番レースとは異なるUUID付き検証IDを使用し、業務SQL、型検証、Store factory、SQL変換、受領重複制御を実際に実行した。

業務データを残さないため、ドライバーの検証用leaseで接続を1つの実transactionに参加させ、操作終了ごとのcommit/rollback/closeを保留した。10回のcommit要求を保留し、最後に実connectionをrollback/closeした。通常の操作別commitと独立readerによる確定後の読取は今回の試験では変更された条件であり、それ自体の再検証とは扱わない。通常のtransaction・原子性・最小権限は既存API切替試験の証跡を再利用する。

本来のreader接続はlease適用前にも実行した。rollback後の残存確認もleaseを外した別実接続で行った。SQLのschema/index、接続設定、既存レース、モデル、タスク、元SQLiteの変更、HTTPによる外部データ取得は行っていない。API再起動も不要だった。

## 既存の確認結果と合わせた範囲

| 範囲 | 採用した根拠 |
|---|---|
| 通常API/MCP、cache/jobs、履歴、CLI、日次タスク | [API切替完了監査](../../.workstate/jra-srb/sqlserver-api-cutover/completion-audit.md)。通常HTTP69/MCP10の経路、SQL実接続39件等の既存結果。今回の[依存監査](sqlite-dependency-audit-20261017.md)で関連タスクと現在設定を確認済み |
| 現用手動入口・スキル | [修正結果](sqlite-dependency-fix-20261017.md)＋今回の52項目。監査で検出した8ファイルの未確認を解消 |
| S06/S08の研究 | [第四段階結果](tipster-sql-step4-results-20261017.md)。SQL31/34入力で固定6案を学習・評価済み。旧SQLite/JSONL禁止条件の既存成功結果を採用し、再学習しない |
| 移行済み原データ | [移行完了証跡](../../.workstate/jra-srb/sqlserver-model-data-audit/progress/034-移行完了証跡の再利用と研究への復帰.md)。192/192表・470,517,746行、pending/mismatch=0。再投入・全量再照合を行わない |

CatBoostの通常スカウトは共通SQL factory/readerを使う経路として静的監査済み。今回、CatBoostの65列・実scoreやML V91〜V111各方式の研究実行を追加確認したわけではない。今後の新方式の実装はSQLの既存データを入力にする。旧JSONL/SQLiteを読む終了研究コードの直接再実行を、現用の研究手順へ戻さない。

確認境界は依存監査に記載した2案件・関連スキル・登録タスク。PC内の任意の別ソフトや将来追加されるコードまで保証する表現は用いない。SQL設定を明示的にsqliteへ変更すれば、共通ライブラリの旧backend機能は選べるため、現在のSQL設定を維持する。

## 容量整理への引継ぎ

**現用処理の旧SQLite依存という停止条件は解消した。** 次は[既存の保管計画](storage-retention-plan-20261016.md)を使い、各削除候補について移行証明の対象版・固定後更新・NASでの原本保管/重複保管の有無を既存証跡と照合して実施順を確定する。依存調査や全21研究の再現からやり直す必要はない。

PCから除去することと、再取得できない原本を唯一の保管先から消すことは別に判断する。契約終了により歴史データを再取得できないという前提を保持する。今回ファイル削除・移動・圧縮・SQLデータ整理は実行していない。

## 証跡

- [今回の検証計画115](../../.workstate/jra-srb/sqlserver-model-data-audit/spec/115-旧SQLite非依存実動作確認.md)
- [実行結果：52項目](../../.workstate/jra-srb/sqlserver-model-data-audit/dependency-fix-20261017/runtime-verification.json)
- [実行用スクリプト](../../.workstate/jra-srb/sqlserver-model-data-audit/dependency-fix-20261017/verify_no_legacy.py)
- [現在APIの読取照合](../../.workstate/jra-srb/sqlserver-model-data-audit/dependency-fix-20261017/current-api-read-verification.json)

新規依存追加なし。uv経由のPython標準ライブラリと既存mssql-python/案件コードを使用した。
