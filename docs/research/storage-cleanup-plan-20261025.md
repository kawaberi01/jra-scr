# JRAデータ容量整理：削除対象一覧・実施計画

作成日：2026-10-25 JST。対象：jra-scrおよび関連するJRA-VAN取得・SQL移行ファイル。
状態：2026-10-25にA～Cの計80ファイルを削除済み。実空き約155.69GB増。新規再生成jobs.sqliteは保持。詳細は[実施結果](storage-cleanup-result-20261025.md)を参照。

## 1. 目的・前提・対象範囲

SQL Serverへの集約・通常API切替は完了済みとして、PC上の旧DB・重複コピーを段階的に整理する。既存の移行完了証跡（192/192表、470,517,746行、pending/mismatch=0）を再利用し、過去研究の全再実行・同じ全量移行検証は条件に戻さない。

本書の容量は10/16～10/17の棚卸し・対象manifestに基づく論理ファイル長。10/23には登録済みDB98件の存在・サイズ・更新日時一致が確認されている。10/25に対象データ全件・NAS保管物・使用中プロセスを再確認したものではない。現時点で全件を削除可能と認定する一覧ではなく、削除前の確認条件を伴う計画である。

JRAの過去データは再取得できない前提を維持する。通常の参照先はSQL Server。取得原本・来歴・必要な研究成果を残し、同じ版をNASへ何重にもコピーしない。具体的な対象への削除指示を受けた実施回に、対象単位で直前確認を行う。

## 2. 実施順と容量

| 順 | 区分 | 本体・backup数 | 論理容量GB | 扱いと着手条件 |
|---|---|---:|---:|---|
| 1 | A：第1対象 | 2本体＋4付随ファイル | 70.796190 | 保持側を残したままPCの6ファイルを除去する計画。直前照合・未使用確認後に実施 |
| 2 | B：その他の移行済みDB・固定版 | 62 | 84.393615 | 同じ原版を一度だけ保管し、版・WAL・来歴・現用参照を確認した単位から除去 |
| 3 | C：修復前backup | 6 | 0.531223 | SQL移行対象外。各版をNASに保管・照合後に除去 |
| 4 | 受信bin群 | 約2,113万ファイル | 約31.727 | 後続。原本マスターへの包含と来歴を取得単位で確認。不明分は一度保管後に除去 |
| 5 | D：少量の試行・派生DB | 28 | 0.010912 | 現状保持。固有記録と参照の確認後に個別判定 |
| 6 | 旧ビルド・旧学習入力・管理cache等 | 未確定 | 個別確定 | 非現用・再生成可能性を確認し、絶対パスの実施一覧を別途固定 |
| 別作業 | SQL内部の重複・派生データ | 未確定 | 削減量未確定 | 今回のファイル削除に含めない。表・版・条件と依存確認が必要 |

A本体の合計は70,796,124,160 bytes、付随4ファイルを含めると70,796,189,696 bytes。B/C/Dは本体・backupのみ。A～Dの本体98件合計は155,731,873,792 bytes（約155.732GB）。A～Cの本体だけでは155,720,962,048 bytes（約155.721GB）だが、一括削除の確定量ではない。

第1段階ではC約14.84GB、D約55.95GBが整理候補。ハードリンク・圧縮・割当単位等の影響があるため、実際の空き増加は削除前後の実測で記録する。SQL内の削減量をPCの空きへ加算しない。

## 3. 第1段階：削除対象6ファイル

保持先の条件は次節。下表以外の兄弟ファイルや親フォルダーは含めない。

| ID | 削除対象の絶対パス | bytes | 保持先 |
|---|---|---:|---|
| A1 | `C:\jra-sqlserver-migration-stage\20261009\jra-prediction.sqlite` | 14843629568 | K1：NAS全期間DB |
| A2 | `C:\jra-sqlserver-migration-stage\20261009\jra-prediction.sqlite-wal` | 0 | K1：NAS全期間DB |
| A3 | `C:\jra-sqlserver-migration-stage\20261009\jra-prediction.sqlite-shm` | 32768 | K1：NAS全期間DB |
| A4 | `D:\develop\jra-scr\data\jvlink\odds-parsed.sqlite` | 55952494592 | K2：C側オッズ固定版 |
| A5 | `D:\develop\jra-scr\data\jvlink\odds-parsed.sqlite-wal` | 0 | K2：C側オッズ固定版 |
| A6 | `D:\develop\jra-scr\data\jvlink\odds-parsed.sqlite-shm` | 32768 | K2：C側オッズ固定版 |

## 4. 必ず保持するもの・保管先

| ID | 保持する絶対パス・対象 | 条件・位置付け |
|---|---|---|
| K1 | `\\192.168.1.101\jra\jra-van-data\prediction\full-20261005-verified-20261008\jra-prediction.sqlite` | A1～A3の保持側。過去の元/先SHA一致証跡を再利用し、現物の版・長さ・更新有無を直前確認 |
| K2 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\odds-parsed-current.sqlite` | A4～A6の保持側。第1段階では削除禁止。Bに含まれるが、NAS保管・照合が済むまで保持 |
| K3 | `\\192.168.1.101\jra\sqlserver2022-poc\jra_unified_20261016_053626.bak` | 116,499,734,528 bytesの存在・サイズ等の確認記録あり。VERIFYONLY・実復元は未確認。10/16以後のSQL更新とDB外成果物は別保全 |
| K4 | `\\192.168.1.101\jra\jra-van-data\originals\c-originals-offload-20261008\master-20261005\jv-original-master.sqlite` | 原本マスター。削除対象外。bin群全件の包含を、この存在だけで証明したとは扱わない |
| K5 | `\\192.168.1.101\jra\jra-van-data\originals\snapshot-20261007\` と原本検証証跡 | 原本DB13本・取得来歴・manifestを保持 |
| K6 | `\\192.168.1.101\jra\sqlserver2022-poc\data\jra_unified.mdf`、同`log\jra_unified_log.ldf` | 稼働中SQL本体とログ。直接削除・移動・圧縮しない |
| K7 | `D:\develop\jra-scr\data\storage\`、現用コード・モデル・最新研究成果・仕様・検証証跡 | 保持。接続秘密は一般アーカイブへ混ぜない。`data`、`artifacts`、`.workstate`の一括削除はしない |

B/Cの追加保管先は、NASの既存アーカイブと版を照合したうえで実施時に確定する。現時点で個別の保管完了は認定しない。`\\192.168.1.101\jra\jra-van-data\retired\pc-cleanup-20261025\`を新規保管先の候補とし、作成・コピーは未実施。同じsourceでも基準版・差分版・最終版を別版として識別し、単純に1本へまとめない。

旧analysis/jobsは、SQLから復旧する運用ではSQL復旧の必須資産ではない。旧SQLiteへの切戻しを採用する場合に限り、既存復元ツール用の一式を保持する。全コピー保持を無条件に要求せず、原本保管と切戻し要否を区別する。

## 5. 実施手順

### 手順1：今回の実施単位を固定する

1. 第1回はAの6ファイルだけとする。対象manifestの絶対パス・bytes・mtime_ns・file ID・deviceを照合資料にする。
2. B/C以降は末尾の個別一覧から選び、対象パス、版、sidecar、保持先、照合証跡、復元方法を明記した実施一覧を作る。source名が同じだけで内容同一としない。Dやbin群を追加しない。
3. 対象単位の具体的な削除指示を確認する。本書の作成依頼をデータ削除の指示として扱わない。

### 手順2：対象・保持先・稼働状況を直前確認する

1. C/Dの空きbytes、対象と保持先の存在・長さ・更新日時を記録する。対象はfile ID・deviceまで既存manifestと比較する。差があれば、その単位は保留し差分理由を確認する。
2. 対象ファイルと祖先ディレクトリの実体パス・reparse属性を確認する。junction/symlink等により想定外の領域を指す場合は実施を止める。
3. 現在のプロセス、取得処理、定期タスク、API/worker/CLI、旧研究入口の対象参照を限定確認する。閉じられたDBであることを確認し、使用中ならその単位を保留する。更新日時の一致だけで未使用と断定しない。稼働プロセスを無断停止しない。
4. WAL/SHMの存在・長さ・更新状態を本体と一組で確認する。第1対象のWALは0 bytesが期待値。非0・新規作成・更新があれば未反映データの可能性を確認し、本体やsidecarの単独削除はしない。
5. 現在のSQL設定が想定どおりであることと、既存SQL接続による短い読取の成功を確認する。秘密値を出力しない。APIが稼働中なら既存の確認方法で通常読取を確認し、確認目的で未知のAPIプロセスを起動・停止しない。

### 手順3：保持側の照合・必要分だけ保管する

1. AはK1/K2の対応版と保管証跡を確認する。保持先を今回の削除一覧へ混ぜない。第1段階では巨大なNAS追加コピーは不要という既存計画を維持する。
2. Bは既存NAS版の有無を先に確認し、同一版なら重複コピーを省く。D元DBとC固定版にはサイズ差や差分版があるため、同一版の証拠がないものは個別に扱う。
3. 新規保管が必要な場合は、NASの現在空き・quota・SQL成長余地を確認する。閉じた整合版を、既存の圧縮ツール等でNAS上の新規保管物へ出力し、既存原本を上書きしない。PCに巨大な一時コピーを作らない。
4. 新規保管は元/先SHA一致、または圧縮テストと展開読戻しSHA一致を確認する。main/WAL/SHMの整合する保管単位を確定する。既存証跡は再利用できるが、変化した元へ過去SHAを適用しない。
5. Cの6backupはSQL未移行の旧版として別々に保管する。保管先・原パス・SHA・復元手順を小さなmanifestに残す。検証失敗なら依存する削除を止める。
6. 10/16のBAKより後の固有データを消す対象では、その保全先を確認する。BAKの存在・サイズだけで復元可能とは認定しない。新しい巨大BAKの作成・復元試験は、この計画作成では実施していない。

### 手順4：限定したファイルだけ削除する

1. 今回対象、照合結果、保持先、期待容量、残る未確認事項を確認できる形にする。条件が満たせない単位は保留し、満たした単位だけを進める。
2. 実行はPowerShellの`Remove-Item -LiteralPath`で、確認済みの個々の絶対パスを指定する。ワイルドカード・`-Recurse`・親フォルダー単位の削除は使用しない。未確認のCSV全件を直接削除へ流し込まない。
3. 本体・sidecarは同じ実施単位で扱い、各処理結果を記録する。途中失敗なら後続削除を止め、残存状況と復旧手順を記録する。使用中ファイルを強制削除しない。

### 手順5：削除後確認と区切り

1. 対象だけがなくなり、保持先と非対象ファイルが残ることを確認する。
2. C/Dの空きbytesを再計測し、削除論理bytesと実空き増加を別々に記録する。NASの追加bytes・既存保管再利用bytesも記録する。
3. 削除前に成功していたSQL/API読取を対象に応じて再確認する。業務保存の確認が必要なら既存の検証経路を選び、確認方法と副作用を明示する。研究全方式の再学習は不要。
4. 問題があれば次の単位を止める。K1/K2または照合済みNAS保管物から元の絶対パスへ戻す。戻し先への既存ファイル上書きは避け、main/WALの組合せを崩さない。SQL運用の障害と判明した場合は旧SQLiteへ自動切戻しせず、既存のSQL復旧手順へつなぐ。
5. 必要なPC空きが得られた時点で研究作業へ戻れる。B～D・bin群・SQL内整理の全完了を待たせない。

## 6. 後続・今回削除しない対象

| 対象 | 判定・必要な追加確認 |
|---|---|
| `D:\develop\jra-scr\data\jvlink\raw\jvlink\` | 約31.727GB。取得単位ごとのマスター包含・本文と出現来歴・未包含分の保管確認後。約2,113万ファイルの無条件再棚卸しや一括削除を開始しない |
| `data/training/jra_o1o2_asof_v1`等の旧学習入力 | 終了用途か、今後使う研究からの参照がないかを確認。結果・結論・条件を残す。現用入力は保持 |
| JV-Linkのdata/cache/download管理領域 | 正規の管理方法と稼働用途を確認。手動の一括削除は未認定 |
| 旧ログ・一時出力・旧ビルド | 個別パスと容量は未確定。固有証跡・現用参照・再生成可能性を確認後に別一覧へ追加 |
| 最新研究・前向き監査・採用モデル | 保持。10/23以後も研究が進んでいるため、旧run名だけを見て削除しない。10/25時点の現用・参照状況を実施時に確認 |
| `raw.legacy_jv_raw_records` | 既存記録で約20.85GiB。原本マスターとの重複・固有列・来歴・reader依存が未確定。SQL削除は別計画 |
| `prediction.features_asof` | 既存記録で約8.72GiB。view/reader依存・必要版・再生成条件を確認。現時点で削除確定していない |
| SQLのraw/history/market/ops/api_runtime等 | 現行共用入力・原本・来歴・通常保存を保持。SQLite整理に便乗してDELETE/TRUNCATE/DROP/SHRINKしない |

SQLの表使用量は削減可能量ではない。SQL内整理とデータファイル縮小は別操作として扱い、PC空きの回復量に混ぜない。

## 7. 実行記録テンプレート

| 実施日時 | 対象ID・絶対パス | 版照合・未使用確認 | 保持先・SHA証跡 | 削除結果・bytes | C/D実空き増加 | NAS追加/再利用bytes | SQL/API確認 | 保留・復旧事項 |
|---|---|---|---|---|---|---|---|---|
| 2026-10-25 | A～Cの80ファイル | 全対象の版・未使用確認済み | NAS保管・読戻し一致 | 80件 / 155,721,228,920 bytes | C約85.20GB / D約70.49GB | 圧縮物約13.00GB追加 | SQL/API読取成功 | 新規jobs.sqliteは保持。D/bin/SQL内は未削除 |

- [x] 今回対象の削除指示と具体的一覧を確認
- [x] パス実体・版・本体/sidecar・未使用を確認
- [x] 保持先・照合証跡・戻し方を確認
- [x] 直前の空きとSQL/API動作を記録
- [x] 確認済み対象のみ除去
- [x] 非対象保持・空き実測・SQL/API動作を確認
- [x] 結果・停止理由・次の実施単位を案件内に記録

## 8. 本体・backup98件の個別一覧

以下は既存CSVの全98件を転記した一覧。Aの付随4ファイルは第3節を参照。B/C/Dのsidecarは、この98件には含まれないため実施前に追加確認する。

区分A＝第1対象、B＝保管・参照確認後、C＝旧backup保管後、D＝保持・判定保留。Bのsourceキーは対応付けの手掛かりであり、全版同一の証明ではない。
### 区分A

| ID | 絶対パス | bytes | 対応sourceキー |
|---|---|---:|---|
| A-01 | `C:\jra-sqlserver-migration-stage\20261009\jra-prediction.sqlite` | 14843629568 | prediction-full-20261008;prediction-full-20261008 |
| A-02 | `D:\develop\jra-scr\data\jvlink\odds-parsed.sqlite` | 55952494592 | odds-parsed-current |

### 区分B

| ID | 絶対パス | bytes | 対応sourceキー |
|---|---|---:|---|
| B-01 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\analysis-current.sqlite` | 425394176 | analysis-current |
| B-02 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\analysis-legacy.sqlite` | 1073152 | analysis-legacy |
| B-03 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jobs-current.sqlite` | 12288 | jobs-current |
| B-04 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2003.sqlite` | 115130368 | jv-results-2003 |
| B-05 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2004.sqlite` | 67149824 | jv-results-2004 |
| B-06 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2005.sqlite` | 67231744 | jv-results-2005 |
| B-07 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2006.sqlite` | 68517888 | jv-results-2006 |
| B-08 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2007.sqlite` | 68349952 | jv-results-2007 |
| B-09 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2008.sqlite` | 70098944 | jv-results-2008 |
| B-10 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2009.sqlite` | 67575808 | jv-results-2009 |
| B-11 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2010.sqlite` | 59592704 | jv-results-2010 |
| B-12 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2011.sqlite` | 58466304 | jv-results-2011 |
| B-13 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2012.sqlite` | 59240448 | jv-results-2012 |
| B-14 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2013.sqlite` | 59949056 | jv-results-2013 |
| B-15 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2014.sqlite` | 60489728 | jv-results-2014 |
| B-16 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2015.sqlite` | 59179008 | jv-results-2015 |
| B-17 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2016.sqlite` | 59269120 | jv-results-2016 |
| B-18 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2017.sqlite` | 59150336 | jv-results-2017 |
| B-19 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2018.sqlite` | 58687488 | jv-results-2018 |
| B-20 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2019.sqlite` | 57384960 | jv-results-2019 |
| B-21 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2020.sqlite` | 58064896 | jv-results-2020 |
| B-22 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2021.sqlite` | 57032704 | jv-results-2021 |
| B-23 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2022.sqlite` | 122580992 | jv-results-2022 |
| B-24 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2023.sqlite` | 161595392 | jv-results-2023 |
| B-25 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2024.sqlite` | 56438784 | jv-results-2024 |
| B-26 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2025.sqlite` | 57245696 | jv-results-2025 |
| B-27 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2026.sqlite` | 52793344 | jv-results-2026 |
| B-28 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jvlink-current.sqlite` | 11862106112 | jvlink-current |
| B-29 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\odds-parsed-current.sqlite` | 55952494592 | odds-parsed-current |
| B-30 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\validation-live-capture.sqlite` | 1622016 | validation-live-capture |
| B-31 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\validation-market-capture.sqlite` | 20836352 | validation-market-capture |
| B-32 | `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\delta-20261013T133139Z\analysis-current.sqlite` | 440999936 | analysis-current |
| B-33 | `D:\develop\jra-scr\data\analysis.sqlite` | 1073152 | analysis-legacy |
| B-34 | `D:\develop\jra-scr\data\db\analysis.sqlite` | 440999936 | analysis-current |
| B-35 | `D:\develop\jra-scr\data\jobs.sqlite` | 12288 | jobs-current |
| B-36 | `D:\develop\jra-scr\data\jvlink\jvlink.sqlite` | 11862102016 | jvlink-current |
| B-37 | `D:\develop\jra-scr\data\jvlink\results\2003\results.sqlite` | 115130368 | jv-results-2003 |
| B-38 | `D:\develop\jra-scr\data\jvlink\results\2004\results.sqlite` | 67149824 | jv-results-2004 |
| B-39 | `D:\develop\jra-scr\data\jvlink\results\2005\results.sqlite` | 67231744 | jv-results-2005 |
| B-40 | `D:\develop\jra-scr\data\jvlink\results\2006\results.sqlite` | 68517888 | jv-results-2006 |
| B-41 | `D:\develop\jra-scr\data\jvlink\results\2007\results.sqlite` | 68349952 | jv-results-2007 |
| B-42 | `D:\develop\jra-scr\data\jvlink\results\2008\results.sqlite` | 70098944 | jv-results-2008 |
| B-43 | `D:\develop\jra-scr\data\jvlink\results\2009\results.sqlite` | 67575808 | jv-results-2009 |
| B-44 | `D:\develop\jra-scr\data\jvlink\results\2010\results.sqlite` | 59592704 | jv-results-2010 |
| B-45 | `D:\develop\jra-scr\data\jvlink\results\2011\results.sqlite` | 58466304 | jv-results-2011 |
| B-46 | `D:\develop\jra-scr\data\jvlink\results\2012\results.sqlite` | 59240448 | jv-results-2012 |
| B-47 | `D:\develop\jra-scr\data\jvlink\results\2013\results.sqlite` | 59949056 | jv-results-2013 |
| B-48 | `D:\develop\jra-scr\data\jvlink\results\2014\results.sqlite` | 60489728 | jv-results-2014 |
| B-49 | `D:\develop\jra-scr\data\jvlink\results\2015\results.sqlite` | 59179008 | jv-results-2015 |
| B-50 | `D:\develop\jra-scr\data\jvlink\results\2016\results.sqlite` | 59269120 | jv-results-2016 |
| B-51 | `D:\develop\jra-scr\data\jvlink\results\2017\results.sqlite` | 59150336 | jv-results-2017 |
| B-52 | `D:\develop\jra-scr\data\jvlink\results\2018\results.sqlite` | 58687488 | jv-results-2018 |
| B-53 | `D:\develop\jra-scr\data\jvlink\results\2019\results.sqlite` | 57384960 | jv-results-2019 |
| B-54 | `D:\develop\jra-scr\data\jvlink\results\2020\results.sqlite` | 58064896 | jv-results-2020 |
| B-55 | `D:\develop\jra-scr\data\jvlink\results\2021\results.sqlite` | 57032704 | jv-results-2021 |
| B-56 | `D:\develop\jra-scr\data\jvlink\results\2022\results.sqlite` | 122580992 | jv-results-2022 |
| B-57 | `D:\develop\jra-scr\data\jvlink\results\2023\results.sqlite` | 161595392 | jv-results-2023 |
| B-58 | `D:\develop\jra-scr\data\jvlink\results\2024\results.sqlite` | 56438784 | jv-results-2024 |
| B-59 | `D:\develop\jra-scr\data\jvlink\results\2025\results.sqlite` | 57245696 | jv-results-2025 |
| B-60 | `D:\develop\jra-scr\data\jvlink\results\2026\results.sqlite` | 52793344 | jv-results-2026 |
| B-61 | `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-market-validation\capture\jv-originals.sqlite` | 20836352 | validation-market-capture |
| B-62 | `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\live-race-week\jv-originals.sqlite` | 1622016 | validation-live-capture |

### 区分C

| ID | 絶対パス | bytes | 対応sourceキー |
|---|---|---:|---|
| C-01 | `D:\develop\jra-scr\data\db\analysis.sqlite.bak_20260709_2055` | 83873792 | 未対応・個別確認 |
| C-02 | `D:\develop\jra-scr\data\db\analysis.sqlite.bak_before_2024_course_repair_20260711` | 91340800 | 未対応・個別確認 |
| C-03 | `D:\develop\jra-scr\data\db\analysis.sqlite.bak_before_v89_20260711` | 85815296 | 未対応・個別確認 |
| C-04 | `D:\develop\jra-scr\data\db\analysis.sqlite.bak_before_v90_2024_batch01` | 90996736 | 未対応・個別確認 |
| C-05 | `D:\develop\jra-scr\data\db\analysis.sqlite.bak_before_v90_2024_external` | 92893184 | 未対応・個別確認 |
| C-06 | `D:\develop\jra-scr\data\db\analysis.sqlite.bak_before_v90_20260711_live` | 86302720 | 未対応・個別確認 |

### 区分D

| ID | 絶対パス | bytes | 対応sourceキー |
|---|---|---:|---|
| D-01 | `C:\jra-sqlserver-migration-stage\20261009\jra-prediction-2026-09-27.sqlite` | 4366336 | 未対応・個別確認 |
| D-02 | `D:\develop\jra-scr\.workstate\manual_checks\ttl_manual_check\analysis.sqlite` | 270336 | 未対応・個別確認 |
| D-03 | `D:\develop\jra-scr\.workstate\manual_checks\ttl_manual_check\cache.sqlite` | 12288 | 未対応・個別確認 |
| D-04 | `D:\develop\jra-scr\data\db\analysis-verify.sqlite` | 5140480 | 未対応・個別確認 |
| D-05 | `D:\develop\jra-scr\data\db\test_bet_records_nankan.sqlite` | 270336 | 未対応・個別確認 |
| D-06 | `D:\develop\jra-van-data\builds\custom-recent-probe-fixed-20260929\results\2026\results.sqlite` | 393216 | 未対応・個別確認 |
| D-07 | `D:\develop\jra-van-data\builds\fetch-year-retry-mock-smoke\batch-check\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-08 | `D:\develop\jra-van-data\builds\fetch-year-retry-mock-smoke\failure-check\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-09 | `D:\develop\jra-van-data\builds\fetch-year-retry-mock-smoke\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-10 | `D:\develop\jra-van-data\builds\fetch-year-retry-mock-smoke\wal-reader-check\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-11 | `D:\develop\jra-van-data\builds\sqlite-bulk-smoke-data-20260927\batch-check\jvlink.sqlite` | 69632 | 未対応・個別確認 |
| D-12 | `D:\develop\jra-van-data\builds\sqlite-bulk-smoke-data-20260927\jvlink.sqlite` | 69632 | 未対応・個別確認 |
| D-13 | `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data-20260927\batch-check\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-14 | `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data-20260927\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-15 | `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data-20260927\wal-reader-check\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-16 | `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data2-20260927\batch-check\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-17 | `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data2-20260927\failure-check\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-18 | `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data2-20260927\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-19 | `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data2-20260927\wal-reader-check\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-20 | `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\mock-v2\batch-check\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-21 | `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\mock-v2\failure-check\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-22 | `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\mock-v2\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-23 | `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\mock-v2\originals-check\jv-originals.sqlite` | 45056 | 未対応・個別確認 |
| D-24 | `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\mock-v2\originals-rollback-check\jv-originals.sqlite` | 45056 | 未対応・個別確認 |
| D-25 | `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\mock-v2\wal-reader-check\jvlink.sqlite` | 4096 | 未対応・個別確認 |
| D-26 | `D:\develop\jra-van-data\data\mock-check-x86\jvlink.sqlite` | 49152 | 未対応・個別確認 |
| D-27 | `D:\develop\jra-van-data\data\mock-check\jvlink.sqlite` | 49152 | 未対応・個別確認 |
| D-28 | `D:\develop\jra-van-data\data\mock-speed-smoke-20260927\jvlink.sqlite` | 69632 | 未対応・個別確認 |

## 9. 根拠・再開点

- [10/17の対象判断](storage-cleanup-decisions-20261017.md)
- [元の用途別保管計画](storage-retention-plan-20261016.md)（古い段階の保留条件は最新判断で更新済み）
- [個別判断CSV](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261017/deletion-decisions.csv)
- [第1対象の期待値manifest](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261017/first-batch-targets.json)
- [10/23のSQL集約・整理再確認](../../.workstate/jra-srb/sqlserver-model-data-audit/progress/058-SQL集約完了を前提とした削除整理の再確認.md)
- [SQL内部の容量・候補](../../.workstate/jra-srb/sqlserver-model-data-audit/progress/033-研究資産の保管とSQL容量整理.md)

2026-10-25実施：Aの6ファイルを削除し、保持側・SQL接続・APIヘルス正常を確認。B/CもNAS保管・読戻し照合後に削除済み。最終結果と残件は実施結果を参照。
## 10. 2026-10-25 実施記録

利用者の「では削除を進めてください。」により本計画の実施指示を受領。

第1段階Aは6/6ファイル削除済み。対象のサイズ・mtime_ns・file ID・device一致、祖先を含むreparse pointなし、6ファイル同時の排他読取オープン成功を確認。保持先5ファイルは読取共有ロックで更新・削除を防止した状態で、PowerShellのLiteralPathによる個別削除を実施。原本・NAS全期間DB・C側オッズ固定版・BAKは保持。

| 項目 | Cドライブ | Dドライブ |
|---|---:|---:|
| 削除前の空きbytes | 39,826,554,880 | 44,178,513,920 |
| 削除後の空きbytes | 54,669,287,424 | 100,131,045,376 |
| 実空き増加bytes | 14,842,732,544 | 55,952,531,456 |

対象の論理bytesは70,796,189,696。実空き増加との差は同時のOS・他処理の書込み等を含み得る。SQLはjra_unified/ONLINE、API `/health` は200/status=ok。業務データの書込み試験・全研究の再学習は実施していない。

- [A直前確認JSON](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/a-preflight.json)
- [A削除ログ](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/a-deletion.jsonl)
- [A削除後確認JSON](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/a-postcheck.json)

B/Cは本体68件すべてが10/17の版と一致。D側旧JV-Link管理DBには103,032 bytesのWALがあるため、本体だけを削除せず、sidecarを含む整合した保管単位として扱う。使用中・版変化・保管検証失敗はその単位の停止条件。既存のzstd.exeを使い、読取専用共有ロック中にSHA-256・圧縮保管・展開読戻しSHA-256を照合する。重複SHAは同じ保管物を再利用する。B/Cも保管完了後に74ファイルを削除済み。[実施結果](storage-cleanup-result-20261025.md)に容量・復元方法・jobs.sqlite再作成の注意点を記録した。