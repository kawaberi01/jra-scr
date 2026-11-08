# JRAデータ容量整理 実施結果

実施日：2026-10-25 JST。実施指示：「では削除を進めてください。」
状態：A～Cの計画対象80ファイルを削除済み。削除後に新しいjobs.sqliteが再作成されているため、その12KBは保持。

## 対象と結果

- A：Cの全期間移行コピーとDの解析済みオッズ、本体と付随の6ファイルを削除済み。論理70,796,189,696 bytes。
- B/C：移行済み本体62件、修復前backup6件、付随6件の計74ファイルをNAS保管・展開読戻し照合後に削除済み。論理84,925,039,224 bytes。
- Dの28件、受信bin群、未特定の旧ビルド・cache、SQL内部の表・行は削除しない。Dは固有記録・参照判定が保留、binは原本マスター包含・来歴の単位別確認が未完。未確認の範囲を無条件削除へ広げない。
- 現用コード・モデル・最新研究成果・接続設定・NAS原本マスター・既存原本13本・SQL本体/ログ・SQLバックアップを保持。

## 検証と保管方法

既存の移行受入証跡を再利用。対象の長さ・mtime_ns・file ID・deviceを直前照合し、対象および祖先にreparse pointがないことを確認。B/CはWindowsの読取専用共有ロックで元の更新・削除を防止しながら、元SHA-256、zstd圧縮保管、展開読戻しSHA-256を照合。同一SHAの保管物は共用し、元パス・本体/sidecarの単位・版・保管先をmanifestへ記録する。

NAS追加保管先：`\\192.168.1.101\jra\jra-van-data\retired\pc-cleanup-20261025\`

A削除前後でSQLのDB名jra_unified、状態ONLINE、baseline readyを確認。API `/health` は200/status=ok。後続保管中の `/races?date=2026-10-25` は200/36件。業務保存の書込み試験、全量移行再照合、研究の再学習は行わない。

## 復元方法

1. 原因と必要な復元単位を決め、対象を使用する処理を把握する。稼働SQLへの自動切戻しは行わない。
2. AのC全期間DBは計画K1のNAS既存版から戻せる。AのDオッズは、B/C保管完了後はNAS manifestの元パスK2に対応するSHA保管物から復元する。
3. B/CはNASの`manifest.json`で元の絶対パス・unit・SHA・保管物を選ぶ。WALがあるDBはmain/WAL/SHMを同一unitとして揃えて戻す。
4. 既存ファイルを上書きせず、十分な空きを持つ確認用フォルダーへ`zstd -d -o "復元先の新規ファイル" -- "保管物.zst"`で展開する。展開後SHA-256と長さをmanifestと照合する。
5. 照合成功後、元の配置が必要な時だけ対象パスへ戻す。DBを開く前にmain/WALの組合せを確認する。SQLiteを通常の研究入力へ戻すことを既定にしない。
6. SQL運用の障害は既存のSQL復旧手順で扱う。10/16 BAKのVERIFYONLY・実復元は今回実施していない。BAKの存在・長さだけで復元可能と認定しない。

## 証跡

- [削除計画・個別一覧](storage-cleanup-plan-20261025.md)
- [A直前確認](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/a-preflight.json)
- [A削除ログ](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/a-deletion.jsonl)
- [A削除後確認](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/a-postcheck.json)
- [B/C保管ログ](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/bc-archive.jsonl)

## 次の着手点

A～Cは完了。再生成されたjobs.sqliteの作成元確認は未完で、その新規ファイルは削除しない。D/bin/SQL内部整理は対象別の追加確認が必要。全NAS・bin群の再棚卸しを最初から繰り返さない。
## 最終確認・実測容量

計80ファイル（本体・backup70件、付随10件）を個別削除。論理容量合計155,721,228,920 bytes（約155.72GB）。削除ログは全80件で成功。最終確認では79パスが不存在で、jobs.sqliteの1パスだけ別のfile IDの新規ファイルが存在する。

| 項目 | Cドライブ | Dドライブ |
|---|---:|---:|
| 初回削除前の空きbytes | 39,826,554,880 | 44,178,513,920 |
| 最終確認時の空きbytes | 125,025,951,744 | 114,667,646,976 |
| 実空き増加bytes | 85,199,396,864 | 70,489,133,056 |
| 最終空き（10進GB） | 約125.03 | 約114.67 |

実空き増加の合計は155,688,529,920 bytes（約155.69GB）。他の処理・OSの同時書込みを含むため、削除ファイルの論理容量と区別する。NASの新規zstd保管物は71本・13,000,750,496 bytes（約13.00GB）。このほか小さなmanifest・実施結果JSONを保存。新規圧縮物は全て展開読戻しSHA-256と元SHA-256が一致し、partialファイルは残っていない。

D区分28件は版・サイズ・file IDが元証跡と一致して保持。NAS原本DB13本、原本マスター、既存全期間DB、SQL BAKの現存を確認し、既存保持4ファイルはサイズ・mtime一致。第1段階で保持したC側オッズ固定版K2は、B/CでNAS圧縮版を照合した後に削除した。K2復元時はNAS manifestの同パス対応SHAを使う。

最終確認：SQL jra_unified/ONLINE、baseline ready、api_runtime.racesから1行の読取成功。API `/health` は200/status=ok、当日レース一覧は200/36件。SQL表の削除・縮小・再投入、API停止・再起動、モデル変更は実施していない。

### jobs.sqlite再作成の扱い

削除した旧jobs.sqliteのfile IDは1688849860555835。削除後の2026-10-25 08:23:04 JSTに更新された新規12,288 bytesのfile IDは1970324837266491で、旧版とは異なる。旧版はNASへ照合済み保管され、削除ログも成功している。新規ファイルは再削除していない。

作成元プロセスは未特定。現コードにはSQLite指定時にJobRegistryがDB初期化する経路があるが、これだけで作成元とは断定しない。API待受プロセスも作業中に以前のものから別PIDへ変わっていた。こちらからプロセス停止・再起動は行っていない。現時点の設定解決はSQL Serverで、SQL読取・API読取は成功。再作成の原因確認やコード修正は別途扱う。

### 追加証跡

- [B/C保管manifest](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/bc-archive.json)
- [B/C削除直前確認](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/bc-preflight.json)
- [B/C削除ログ](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/bc-deletion.jsonl)
- [B/C削除結果](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/bc-deletion-summary.json)
- [最終確認JSON](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/final-postcheck.json)
- [再生成jobs.sqliteの識別情報](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/jobs-recreated.json)

使用ツール：PowerShell、uv経由のPython標準ライブラリ、既存zstd.exe、既存mssql-python。限定的なプロセス環境確認にpsutilをuvの一時依存として使用し、プロジェクト依存へは追加していない。