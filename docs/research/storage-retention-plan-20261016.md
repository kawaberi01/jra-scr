# JRAデータの用途別保管とPC容量削減案

2026-10-25更新：A～Cの削除を実施。[最新の実施結果・保持対象・残件](storage-cleanup-result-20261025.md)を参照。以下は当時の判断記録。

作成日 2026-10-16。対象はjra-scrと関連するJRA-VAN取得・SQL移行データ。

**2026-10-17の最新判断:** 現用SQLite非依存の実動作受入を完了し、98ファイルの現在情報と移行/保管証跡を照合した。[削除対象と実施順](storage-cleanup-decisions-20261017.md)を実施判断の最新資料とする。最初はCの全期間コピー＋Dの解析済みオッズの計6ファイル・約70.80GB。保持側は残す。削除未実施。下記の依存確認未完や全研究実行を条件とする記載は先行段階の記録であり、最新資料で更新される。

通常利用するデータを既存のSQL Serverへ一本化し、取得原文はNASの復元用アーカイブとして保管する。PCに置くのは現行コード・接続設定・利用中モデル・直近の実行記録を基本とする。元データや移行コピーを実験ごとに持たない。

JRA-VANへ引き続きアクセスできる前提でも、再取得は当時受信した内容・発表版・取得時刻の再現を保証しない。JRA-VAN受信原文、JRA公式サイト取得物、netkeiba等の外部取得物、購入・予想記録を区別し、復元に必要なものは保管する。移動・圧縮・削除はこの一覧作成では行っていない。

## 最優先条件の更新：再取得不能のため削除保留（2026-10-17）

利用者から、JRAデータの契約がなく取得済みデータを再取得できないことが明示された。**以下の容量優先の削除順は保留。現時点で「SQLだけで優先2系統の研究を継続できる確証がある」「PCのSQLiteを消しても問題ない」とは断言できない。削除実績は0。**

現在の順番は次のとおり。

1. SQL内の必要期間・列・原本/解析状態・時点市場・ID・結果/払戻を、優先2系統の入力要件へ対応付ける。必要情報が欠ける場合、既にSQL/NASにある取得済みデータから生成・復旧できるかを確認する。再取得を解消策にしない。
2. キメラ/S06/S08と機械学習系の代表経路について、SQLだけの学習・評価・将来scoreを実行し、未達/制約を明示する。対象外の過去研究全再現・全21件完走は求めない。
3. PCから除去する候補ごとに、固有情報がSQLまたはNASに保全され、同じ取得済みデータを再取得なしで戻せることを確認する。NASに何かが存在するだけで、同じ版/本文/来歴/WALを保全済みとは判定しない。
4. 上記の証拠・残件・具体的対象を示して、除去対象を改めて決める。NASから元コピーを戻せることと、SQLだけで研究できることは別の証明として報告する。

研究入力として旧SQLiteへ戻らない方針は維持する。ただし保全・移送確認のファイル読取まで禁止した意味ではない。最後の取得済みデータを再生成可能という推測で捨てない。必要な研究実行が未確認の現段階で、容量確保を理由に削除を先行しない。

## 2026-10-17 容量優先の実施案（上記確認まで削除保留）

### 目的と削除条件の変更

**先にPC容量を空け、その後に優先2系統の研究入力を整備する。** 対象外の過去研究の全再現・全候補再実行・全データ再整形を、SQLite除去の条件にしない。

通常の研究・学習・予測入力はSQL Serverだけを使う。SQLiteは研究のために開かず、退避時のファイルSHA・圧縮/読戻し等の保全確認だけを行う。既存のSQL移送証跡とNASの保管証跡を再利用し、98ファイルの全内容照会や約2,113万ファイルの再棚卸しを最初から繰り返さない。

「PCから除去できる」と「復元用の最後の1部まで廃棄できる」は別。初期段階は、既存NAS正本の活用またはNASへの一度だけの保管で、PC上のコピーを減らす。既存NAS保管物は上書きしない。

### 今回の読取確認

- C空き: 17,353,445,376 bytes（約17.35GB）。D空き: 47,590,985,728 bytes（約47.59GB）。今回確認時点の値。
- `C:\jra-sqlserver-migration-stage\20261009` と `20261010-unified` は存在。サイズ85.234GBは10/16既存集計を使用し、今回は再帰集計していない。
- Dの`odds-parsed.sqlite`は55,952,494,592 bytes、`jvlink.sqlite`は11,862,102,016 bytes、旧`data/db/analysis.sqlite`は440,999,936 bytesを再確認。更新日時だけでwriter停止とは判定しない。
- SQLのMDFは`/mnt/nas-poc/data/jra_unified.mdf`、LDFは`/mnt/nas-poc/log/jra_unified_log.ldf`。実際にNAS `//192.168.1.101/jra` 上。Dockerのsystem用volume `/var/opt/mssql`とは別。
- NAS mountの表示空きは300,684,230,656 bytes（約300.68GB、使用率93%）。共有容量/利用者quota、SQL成長分は別確認。PCデータ195.6GBを無条件に全量追加コピーする計画にはしない。
- 今回はパス・ファイル長・mount・DBファイル実パスのみ確認。SQLite内容・NAS原本の全量読取・新規保管・削除は未実行。

### 実施順と完了条件

容量は既存棚卸しの10進GB・論理サイズ。累計は計画上のPC除去候補で、実際の空き回復保証ではない。

| 順 | 作業単位 | PC除去候補 | 累計 | 必要な確認と終わり方 |
|---|---|---:|---:|---|
| 0 | 軽い事前確認・対象を固定 | — | — | 現在のwriter/取得処理/移行再開処理、必要なファイル参照を確認。既存SQL移送証跡、NAS正本/manifest、直近SQLバックアップの所在を照合。削除対象を絶対パスで固定し、junction等による範囲外参照を確認 |
| 1 | **C: 20261009** | 約14.848GB | 約14.8GB | 既存NASの全期間研究DBと同一版かSHA/manifestで確認。同一本文を再コピーせず、小さなstage証跡/固有の小DBだけ必要に応じ保管。対象の使用停止と保管確認後、この単位だけPCから除去しC空きを実測 |
| 2 | **C: 20261010-unified** | 約70.386GB | 約85.2GB | 取込元33系統/差分の固定版と移送証跡を単位別確認。NAS既存版との一致は重複保管せず、足りない閉じた版だけNASへ一度保管。先に全C退避を二重作成せず、検証できた単位からPCを除去 |
| 3 | **D: odds-parsed.sqlite** | 約55.952GB | 約141.2GB | SQL source30の移送済み版・解析版/行数/元SHAの既存証跡と、稼働writer/reader停止を確認。C stage由来のNAS保管版と同一ならそれを共用し、D由来の2部目を作らない。全21研究受入は不要 |
| 4 | **D: 旧JV-Link管理DB** | 約11.862GB | 約153.0GB | 取得ソフトの現用DBでないことを確認。checkpoint/取得履歴/原文参照等の固有情報をC由来保管版または専用保管で残す。取得中なら、そのDBだけ保留し他の単位を進める |
| 5 | **年別受信DB・旧analysis/jobs・修復前backup** | 約2.659GB | 約155.7GB | 年別固有原文と、予想・実購入・評価を含む旧業務記録を一度保管。main/WAL/SHMを整合する単位で扱う。旧analysis最終同期/SQL切替の既存証跡を使用。新たな全過去研究評価はしない |
| 6 | **受信原文bin群** | 約31.727GB | 約187.4GB | 既存の原本マスター包含・元SHA/出現来歴証拠を優先利用。包含確認済み本文は重複保管せず、未包含/包含不明の取得単位だけNASへ圧縮保管。確認できない単位は元を削除しない |
| 7 | **JV-Linkキャッシュ・旧ビルド・終了研究の中間物** | 個別確定 | 加算は実施後 | JV-Linkの正規管理方法と現用参照を確認。終了研究は報告・条件・結果中心で保管し、全特徴量コピーを新たに作らない。現用モデル・スキル参照コードを残す |
| 8 | **SQL内の派生/重複容量整理** | PC空きとは別 | 加算しない | 優先研究が必要なSQL入力を特定後、features_asof/旧JV移送等の参照・重複・固有情報を限定確認。SQL容量削減はNAS側の空きへ影響する別作業。033参照 |
| 9 | **優先研究用SQL入力→研究継続** | — | — | 予想家由来研究を最優先、V91〜V111を次優先。新専用adapterでSQLite直接参照を置換。SQL入力が不足なら不足を報告し、PCへSQLiteを戻して通常研究する運用にしない。090参照 |

**順3までの約141.2GBの候補を整理し、必要なPC空きが確保できた時点で優先研究P0へ戻れる。順4〜7の全整理やSQL内削減の完了を研究再開の前提にしない。** 旧SQLiteの残りは単位別に整理し、約2,113万ファイルのbin群は後続作業へ分離する。SQL側の削減候補確認は研究P0の必要入力調査と共用し、二重調査しない。

bin群はファイル数が非常に多いため、PC空きの初手にしない。既存の「最初の3対象で172.913GB」は対象組合せの合計であり、この実施順の最初の3単位はC2単位＋Dオッズで約141.186GBとなる。どちらも二重計上ではない。

### 研究の未改修とPC除去の関係

終了研究の直接SQLite参照コードは再実行しない。優先研究の一部コードに直接参照が残る場合も、それを使い続けるために全PC SQLiteを無期限保管する条件にはしない。NAS保全と移送確認ができ、稼働中参照を止めた対象からPCを除去できる。専用SQL adapterが整うまで、その旧入口で研究を実行しない。

一方、JV-Link等の取得処理が現に使う管理DBは、研究入力と別の稼働依存がある。使用中と判明したDBだけを保留し、API/取得タスクを無断で停止・変更して削除を通さない。

### 1保管単位の実施方法

1. 元パス/版/長さ/既存SHA・writer/reader・対応するSQL移送証跡とNAS保管先を確認する。以前確認済みの内容を理由なく全量再計算しないが、更新されたファイルに古いSHAを適用しない。
2. NASに同一内容があれば、小さな対応manifestのみ更新。固有分だけ、既存の7-Zip/tar/zstdでNAS上の新規`.partial`へ直接出力する。PCに巨大な圧縮一時ファイルを作らない。
3. 新規保管は圧縮テスト/読戻し照合、既存保管は版とSHA等で確認。元のパス・保管先・復元方法を小さな台帳に残す。検証失敗なら、その保管単位の削除を止める。
4. **元を消す段階だけ**、対象パス・サイズ・保管先・照合結果を提示し、利用者が具体的に確認できる状態にする。計画への同意を未特定ファイルの一括削除承認へ広げない。
5. 許可された対象だけPowerShellの`-LiteralPath`で除去し、解放量を実測。未検証・使用中の隣接ファイルをまとめて消さない。通常APIの対象単位に関係する読取り/保存確認を行う場合は、必要な確認だけを提示して実施する。

稼働中SQLiteを整合性なしにコピーする、WALだけ削除する、旧原文を再取得可能という理由だけで捨てる、秘密の接続設定を一般アーカイブへ混ぜる、といった扱いはしない。

### 進捗と見積り

各単位で「PC除去済みbytes・C/D実空き・NAS追加bytes・既存NAS再利用bytes・保留理由」を報告する。大容量コピー/ハッシュ/圧縮の所要時間は実際のNAS速度に依存するため、最初の保管単位で実測して以降を見積もる。古い研究全再現の完了待ちにはしない。

現在の次の作業単位は**順0〜1の具体化（C:20261009の保全・照合・除去対象提示）**。本改訂は計画作成のみで、コピー・圧縮・移動・削除はまだ行っていない。

## 容量削減の優先順位

対象範囲のPC上の論理サイズは195.584 GB、21,139,812 files。Cドライブ90.596 GB、Dドライブ104.988 GB。すべてが削除可能という意味ではない。重複したデータでもPC上の異なる保存パスは別々に数え、親フォルダーと子フォルダーの二重計上はしていない。

| 優先 | 対象 | PC上の論理サイズ | 実施条件 |
|---|---|---:|---|
| 1 | CドライブのSQL移行stage | 85.234 GB | 移行完了・使用停止を確認し、固定版とmanifestをNASへ。既存NAS保管と全SHA一致するコピーは追加保管を省略 |
| 2 | Dドライブの解析済みオッズ | 55.952 GB | 対象版のSQL移送・保全・稼働参照停止の確認後。全21件再現は不要。Cの固定版と同一ならNASへ二重保管しない |
| 3 | Dドライブの受信原文bin群 | 31.727 GB 約2,113万files | 原本マスターへの包含と来歴復元を確認。未包含分をNASへ圧縮保管してからPC側を除去 |
| 4 | Dドライブの旧JV-Link管理DB | 11.862 GB 本体のみ | checkpoint・来歴・原文参照の保存と参照経路の廃止確認後 |
| 5 | 年別受信DBと旧analysis等 | 年別DB本体1.681 GB、`data/db`全体0.978 GB | 固有原文・利用者記録をNASへ退避し、移行と復旧を確認 |
| 6 | JV-Link管理領域 | 5.362 GB | キャッシュ0.166 GBとダウンロード領域5.196 GBを分け、ソフト側の管理方法を確認 |
| 7 | 旧ビルドと再生成可能な学習入力 | ビルド約1.008 GB、学習入力0.244 GB | 非現用・再生成可能であることを確認 |

最初の3対象だけで172.913 GBが整理候補となる。これはPCの論理ファイル長の合計で、実際の回復容量や必要なNAS追加容量ではない。小ファイル群はNTFSの割当単位の影響が大きく、NASへはまとめて保管する。NAS追加量は重複照合と圧縮実測後に確定する。

ハードリンクやファイルシステムの圧縮による物理容量の共有は未集計。原本マスターとbin群は収録範囲・索引・重複排除が異なるため、容量の大小で包含を判断しない。

## 判定の意味

| 判定 | SQL一元化後の必要性 | PC上の扱い |
|---|---|---|
| 通常利用 | APIや研究を動かすため必要 | 稼働先に保持。SQL本体は既にNAS上 |
| 復元用保管 | 通常参照しないが、原文や当時の状態を復元するため必要 | NASへ集約し、照合後にPC側を除去可能 |
| 移行中保管 | SQL移行の同値確認・切戻しに必要 | 移行完了までは参照経路を維持。その後NASへ |
| 再生成可能 | SQLやソースから再生成できる | 移行受入後に削除候補。必要な過去版だけNASへ |
| 確認後削除 | キャッシュ・試行物・旧ビルド等 | 稼働・固有データ・参照がないことを確認して除去 |

旧研究台帳の`overall_complete=false`や全21件の受入は、現在のPC除去の一律前提にしない。対象単位の移送・保全・稼働参照を確認する。以下は既存棚卸しであり、現時点の一括削除リストではない。

## SQL ServerとNASの既存保管物

NASの共通ルートは `\\192.168.1.101\jra`。

| 用途 | 所在 | 容量 | 判定と保管方法 |
|---|---|---:|---|
| 統合DBの稼働データ | `sqlserver2022-poc/data/jra_unified.mdf` | 454.730 GB | 通常利用。圧縮アーカイブ化・移動・削除対象外 |
| 統合DBのトランザクションログ | `sqlserver2022-poc/log/jra_unified_log.ldf` | 1.879 GB | 通常利用。ファイルを直接削除・圧縮しない |
| 原本マスター | `jra-van-data/originals/c-originals-offload-20261008/master-20261005/jv-original-master.sqlite` | 149.930 GB | 復元用保管の中心。受信本文をBrotliまたはzlibで格納。既存保管を利用し、同じDBを重ねてコピーしない |
| 統合前の受信DB群 | `jra-van-data/originals/snapshot-20261007/` | DB13本 記録上24.787 GB | 復元用保管。元取得DBと取得証跡。マスターとの完全な包含・復元性確認前に捨てない |
| 旧全期間研究DB | `jra-van-data/prediction/full-20261005-verified-20261008/jra-prediction.sqlite` | 14.844 GB | 移行中保管。派生データだが旧研究の固定入力として価値がある。通常研究の参照をSQLへ移した後は過去版保管へ |
| 原本と研究DBの検証証跡 | `jra-van-data/proofs/master-verified-20261008/`、`proofs/prediction-full-verified-20261008/` | 総量未集計 | 復元用保管。SHA、取得条件、生成コード、検証記録を原本と組にする |
| 退役済み成果物の既存保管 | `jra-van-data/retired/d-closed-artifacts-20261008/` | 過去記録約1.803 GB | 既存アーカイブ。今回の移動先と重複しないかmanifestで確認 |
| SQLの本番全体バックアップ | SQL BACKUP履歴に記録されたNAS上の`.bak`（研究progress/027参照） | 利用者の完了報告・msdb履歴確認済み | 旧10/16棚卸し後に作成済み。実行前に対象と現存を再確認。新しい全体BAKを機械的に重ねて作らない。SQLiteの全原状保管を代替するとは推定しない |

SQL内の通常業務正本は `jra_unified.api_runtime`。移送済みの `raw/history/market/live/prediction/ops` は取得版・出典・研究入力の来歴として保持する。原文本文は `raw.master_contents`、出現履歴は `raw.master_occurrences`。SQLiteファイルの整理を理由にこれらのSQL表を削除しない。

`snapshot-20261007` のmanifestには停止・未完了の取得runも原状で含むと記録されている。原本を保管済みであることと、JRA全期間・全種類を欠落なく取得済みであることは別である。

稼働中のMDF/LDFをコピーしても正規のSQLバックアップにはならない。SQL本体と原本アーカイブは同一NAS上なので、NAS障害への保険が必要なら別媒体・別保存先も必要になる。

## PCデータの用途別判定

以下の相対パスは、特記がなければ `D:\develop\jra-scr` 配下。個別の実測容量と件数は末尾の全グループ一覧に対応する。

| 用途とデータ | 所在 | 一元化後の必要性 | PCとNASの扱い |
|---|---|---|---|
| JV-Linkの受信原文bin | `data/jvlink/raw/jvlink/` | 復元用保管 | 通常利用では不要。原本マスターへの全件包含を確認し、未包含分はrun・年単位でNASへ圧縮保管。元パス・SHA・取得履歴を残す |
| 旧JV-Link管理DB | `data/jvlink/jvlink.sqlite` とsidecar | 移行中保管から復元用保管 | 原文の参照・checkpoint・取得履歴を含む。binと別の役割があるため、SQL移行と原本マスターだけで復元できるか確認後に退避 |
| 年別RA SE HR等の受信DB | `data/jvlink/results/2003`〜`2026/results.sqlite` | 復元用保管 | 年別原文。受信原文を単なる再生成可能DBとして扱わない。採用原本・SQLとの差分を確認してNASへ |
| 解析済み全オッズ | `data/jvlink/odds-parsed.sqlite` とsidecar | 再生成可能 ただし移行受入までは必要 | 通常研究のSQL置換と解析版・元SHAの照合が済めばPC不要。復元保険として一版だけNAS保管も可 |
| 取得対象キー | `data/jvlink/catalog/` | 復元用の小さな台帳 | 原本アーカイブと組で保管。再収集や対象母集団を同じにする根拠。少量ならPCにも残す |
| 年次収集の結果と失敗記録 | `data/jvlink/years/`、`run-failures/` | 復元用保管 | 成否・対象範囲の証跡としてNAS。未解決エラーの要約はPC保持 |
| サンプル取得DBと試行物 | `data/jvlink/results-sample-probe-20260927/` | 固有原文があれば復元用 それ以外は確認後削除 | 名称だけでテスト不要と判定しない。未包含の取得物は保管 |
| 収集lock | `data/jvlink/*.lock`等 | 稼働中のみ | 実行中の制御情報。writer確認なしに削除せず、原本アーカイブへ恒久保管する必要はない |
| 旧通常業務と予想 購入 評価 | `data/db/analysis.sqlite` | 移行中保管から復元用保管 | 取得し直せない利用者の記録を含む。全表照合・SQL運用後のバックアップ・切戻し方法確認後にNASへ |
| 旧世代の分析DB | `data/analysis.sqlite` | 移行中保管から復元用保管 | 現用analysisとは別の登録元。固有行と移行先を照合しNASへ |
| 旧job記録 | `data/jobs.sqlite` | 移行中保管 | SQLのjob管理へ置換。過去実行履歴が必要なら旧analysisと同じ切戻し保管単位へ |
| 修復前の旧backup | `data/db/analysis.sqlite.bak_*` | 復元用保管 | 訂正前の状態を含む可能性がある。NASへ一括圧縮。移行済み最新版だけで置き換わるとは断定しない |
| 検証用analysisと南関テストDB | `data/db/analysis-verify.sqlite`、`test_bet_records_nankan.sqlite` | 確認後削除 | 名称上は検証用。固有の実予想・購入データがないことを確認し、必要なfixtureと検証結果だけ保管 |
| 旧学習入力と全特徴量 | `data/training/` のhistory、recent_form、O1O2、v89等 | 終了研究の全再現は不要 必要系統だけ個別確認 | 終了研究は条件・結果・結論を保管し、全入力再整形/再保存は不要。必要系統で現に使う入力と、固有で保管するものだけを判定。全特徴量コピーを実験ごとに残さない |
| 学習済みモデル | `data/models/` | 現用は通常利用 旧版は研究成果 | 現用モデルはPC。旧モデルは設定・特徴量順・コード版・評価と一緒にNASへ |
| 発走前の観測と予想 結果 振返り | `data/live/`、`data/exports/` | 復元用保管 | その時点の予想入力と出力の証跡。結果が同じでも再予測では代替できない。SQLへの保存範囲を照合してNASへ |
| 手動取得した南関セッション | `data/manual_snapshots/` | 復元用保管 | オッズ・見解・結果等を取得時の組で保管。SQLに全内容があるとは仮定しない |
| JRA公式サイトの取得HTML等 | `data/raw/jra/` | 復元用保管 | 利用者方針に従いNASへ。取得URL・日時・ファイルSHAを一緒に残す |
| 南関の取得原文 | `data/raw/nankan/` | 復元用保管 | JRA-VANの再取得可能性とは別。南関の当時の取得物として保管 |
| netkeibaの補助資料 | `data/reference/netkeiba/` | 復元用保管 | JRA-VANとは別ソース。詳細成績・通過順等の固有項目の有無を確認して保管 |
| SQL接続設定 | `data/storage/` | 通常利用 | PCに保持。原文・研究成果アーカイブには秘密値を含めない |
| 研究runと旧モデル比較成果 | `artifacts/` | 現用分は通常利用 完了分は研究成果 | 現用artifact・実行中runはPC。完了分は入力契約、モデル、設定、予測、評価、再現情報をNASへ |
| 案件の仕様 進捗 過去補助コード | `.workstate/jra-srb/` | 通常利用と復元根拠 | 現行資料と直接参照される補助コードはPC。無差別なフォルダー移動をしない。巨大な過去明細だけNASへ |
| APIと収集のログ | `.workstate/logs/`等 | 直近は通常利用 過去分は証跡 | 稼働中のログはPC。完了した古いログは日・run別に圧縮保管 |
| 単発作業と手動検証出力 | `tmp/`、`.workstate/manual_checks/` | 確認後削除 または固有取得物のみ保管 | 一時フォルダーという理由だけで全削除せず、未保存の原文・実記録を分ける |
| 配布ビルド | `dist/` | 再生成可能 | 稼働参照がなければ削除。使用中の配布版または再現に必要な版だけ保管 |
| SQL移行の固定コピー | `C:\jra-sqlserver-migration-stage\20261010-unified/` | 移行中保管から復元用保管 | 約70.386 GB。取込基準と差分固定版をNASへ保管し、移行ツールの参照と再開条件を確認後にPCから除去 |
| 旧予想DBの移行stage | `C:\jra-sqlserver-migration-stage\20261009/` | 確認後PCコピー不要 | 約14.848 GB。主DB約14.844 GBはNASにも存在。両者の全体SHAが一致すれば本文の追加保管を省略できる。小さなstage証跡は別途保管 |
| Cドライブの旧原本置場 | `C:\Users\main\jra-van-originals/` | 現時点は空 | 今回の集計は0 files。旧記録の約150 GBを現在の解放候補として加算しない |
| JV-Linkダウンロード済みデータ | `C:\ProgramData\JRA-VAN\Data Lab\data/` | 継続取得時の管理データ 再取得候補 | 5.196 GB。`.jvd`等。ソフトの保存先・キャッシュ運用を確認して整理。取得原文マスターと同一ではない |
| JV-Linkキャッシュ | `C:\ProgramData\JRA-VAN\Data Lab\cache/` | 確認後削除候補 | 0.166 GB。取得停止と正規の整理方法確認後。丸ごとNAS常用に置き換えない |
| JV-Link eventとpictures | `C:\ProgramData\JRA-VAN\Data Lab\event/`、`pictures/` | 今回0 files | 現在の解放対象なし。今後データが入れば用途を再確認 |
| 取得と品質検証の証跡 | `D:\develop\jra-van-data\data/` | 復元用保管と現行運用状態 | 全体0.916 GB。巨大な検証明細はNAS、現行設定・再開情報・manifestはPC。完了検証のerrors.jsonlも名称だけで不要とは判断しない |
| 旧Exporterビルド群 | `D:\develop\jra-van-data\builds/`、`D:\develop\jra-van-data-builds/` | 再生成可能 | 合計約1.008 GB。現用実行パスを確認し、非現用版は削除または代表版だけ保管 |
| Exporterの一時作業 | `D:\develop\jra-van-data\tmp/` | 確認後削除 固有の復旧記録は保管 | 0.039 GB。現在参照されるものを除いて整理 |

## PCに残すもの

| 用途 | 対象 | 残す理由 |
|---|---|---|
| 接続設定 | `data/storage/runtime.env`、`research.env` | SQL接続に必要。小容量。認証情報を一般アーカイブやGitへ混ぜない |
| 現行の実行環境 | `src`、`scripts`、`tools`、依存定義、現用Exporter、JV-Link | SQL参照・収集・学習を継続するため必要 |
| 現用モデル | `data/models`、`artifacts`内で現用設定が指すモデル | SQLにデータがあってもモデルの重みや学習版は別。旧モデルを全部消す根拠にはならない |
| 直近の運用記録 | 稼働中run、直近API/収集ログ、現在のprogressとspec | 実行中の監視・再開・障害調査に必要。完了後の古い大容量明細だけ保管先を変える |
| 小さな検索台帳 | アーカイブ索引、manifest、元パスとNASパスの対応、復元手順 | データをPCから除いても所在と戻し方を確認できるようにする |

## NASへ集約する方法

新規保管が必要なものは `\\192.168.1.101\jra\jra-van-data\archives\pc-offload-20261016\` を候補とする。これは提案先であり、まだ作成していない。既存原本マスター・snapshot・proofsへの追記や上書きはしない。

| 保管区分 | 内容 | 容量を抑える方法 |
|---|---|---|
| `originals` | 元の受信bin、公式HTML、外部取得物、原本に未包含の受信DB | 取得runや年で分けたtar.zst。小ファイルをまとめる。原本マスターの包含が全件証明できた分は、重複した本文コピーを増やさず元パス・SHA・出現情報を保持する方式を検討 |
| `migration` | Cドライブの固定SQLite、差分snapshot、移行manifest | 版単位の閉じたSQLiteを圧縮しNASへ直接出力。差分固定版を一つの最新版で代用しない |
| `legacy-runtime` | 旧analysis、jobs、修復前backup | 切戻し用の整合したDBとschema/index、設定・切替時刻を保存。WAL付きmainを単独コピーしない |
| `research` | 旧学習入力、旧モデル、実験結果、入力契約 | 再生成可能な全特徴量は原則増やさず、採用版・コード・設定・モデル・必要結果を保存。再生成不能な旧入力だけ例外保管 |
| `proofs` | 取得条件、SHA、品質区分、検証結果、取得/生成コード版 | JSON/テキストを圧縮。原文やデータの存在を証明する要約はPCにも残す |

Windowsには `C:\Program Files\7-Zip\7z.exe` と `zstd.exe`、`tar.exe` が存在する。新しいライブラリの恒久追加は不要。実行時は長い日本語パスと復元互換性を小さな保管単位で確認してから広げる。原本マスターや `.gz` は既に圧縮されているため、再圧縮後の削減率は実測するまで確定しない。

PCの空きを作る目的では、PC側へ巨大な圧縮一時ファイルを作らずNASの新規 `.partial` へ直接出力する。ファイル数の多い原文は年・run単位に分割し、障害時の再実行範囲と復元単位を小さくする。稼働中の入力や実行途中の出力は封鎖・圧縮しない。

## PC側を除去できる条件

1. 対象のwriterと参照元を確認し、旧SQLite・旧ファイルへの通常参照をSQLへ置換する。実行中runは完了または計画停止まで保持する。
2. 原文・旧運用記録・再生成可能物を分け、原本マスターへの包含を証明できない固有データはNASへ残す。
3. 新規NAS出力を作り、圧縮テスト、読戻しSHA、件数、総bytes、SQLiteの整合性を対象に応じて確認する。チェック済みのmanifestに元パス、版、移動先、復元方法を記録する。
4. 原本マスターから本文を戻せることと、SQL全体を戻せることを別々に確認する。新SQL運用後の予想・購入・結果等は古いSQLiteだけでは復元できない。
5. 検証済みの保管単位だけPC側を除去し、ドライブの実空き容量と通常API・研究の参照成功を確認する。NASコピーが未検証のまま元ファイルを削除しない。

再取得可能なJV-Linkキャッシュはソフト側の管理対象。利用停止と設定上の安全な整理方法を確認して扱い、JRA-VANのインストール・登録情報・認証設定までまとめて移さない。

## 調査範囲と測定方法

容量は原則10進GB（1 GB = 1,000,000,000 bytes）の論理ファイル長。小ファイルのNTFS割当量、圧縮率、実際の空き回復量とは異なる。取得時刻が異なる資料を現在値と混同しない。NASの大規模原本・SQL領域を再帰全走査せず、既知ファイルの実在と既存manifestで所在を確認した。

PC対象は `D:\develop\jra-scr` 内のdata/artifacts/tmp/.workstate/dist、`D:\develop\jra-van-data` 内のdata/builds/tmp、`D:\develop\jra-van-data-builds`、`C:\jra-sqlserver-migration-stage`、`C:\Users\main\jra-van-originals`、`C:\ProgramData\JRA-VAN`。別の旧案件 `D:\develop\jra-srb\jra-axis-accuracy-validation` は0 files。PC全体の個人ファイル・仮想環境・Docker仮想ディスク全体の削除可否は対象外。

最初の全ファイルパス保持方式は大量小ファイルにより長時間化し、2026-10-16に当該棚卸しプロセスだけ停止した。集計方式を主要ファイル・フォルダー容量へ変更し、元データ・取得処理への変更はない。測定はファイル名とstatだけを使い、設定の秘密値やDBレコード本文は読み取っていない。

詳細データと根拠は末尾の容量一覧およびJSONを参照。

## 実測した全対象の容量一覧

対象範囲のPC容量を合計する。NAS原本とSQL本体は加算しない。空フォルダーも対象ルートとして記載する。

| 対象ルート | GB | files |
|---|---:|---:|
| `C:\ProgramData\JRA-VAN\Data Lab\cache` | 0.165657 | 1,600 |
| `C:\ProgramData\JRA-VAN\Data Lab\data` | 5.196117 | 6,028 |
| `C:\ProgramData\JRA-VAN\Data Lab\event` | 0.000000 | 0 |
| `C:\ProgramData\JRA-VAN\Data Lab\pictures` | 0.000000 | 0 |
| `C:\Users\main\jra-van-originals` | 0.000000 | 0 |
| `C:\jra-sqlserver-migration-stage` | 85.233899 | 43 |
| `D:\develop\jra-scr\.workstate` | 0.391608 | 2,036 |
| `D:\develop\jra-scr\artifacts` | 0.037732 | 492 |
| `D:\develop\jra-scr\data` | 102.594652 | 21,127,771 |
| `D:\develop\jra-scr\dist` | 0.000382 | 3 |
| `D:\develop\jra-scr\tmp` | 0.000990 | 11 |
| `D:\develop\jra-van-data-builds` | 0.172909 | 160 |
| `D:\develop\jra-van-data\builds` | 0.835231 | 938 |
| `D:\develop\jra-van-data\data` | 0.916129 | 677 |
| `D:\develop\jra-van-data\tmp` | 0.038677 | 53 |
| 合計 | 195.583984 | 21,139,812 |

## 実測した全グループの用途と要否

各行はその集計グループに割り当てたファイルの合計。上位パス行が、別行の下位グループを含むわけではない。各行は重複せず合計できる。PC不要の判定には本文の移行受入とNAS照合条件が適用される。

| 集計グループ | GB | files | 用途 | 一元化後のPCとNASの扱い |
|---|---:|---:|---|---|
| `C:\ProgramData\JRA-VAN\Data Lab\cache` | 0.165657 | 1,600 | JV-Link管理データ | 正規の整理方法を確認後 |
| `C:\ProgramData\JRA-VAN\Data Lab\data` | 5.196117 | 6,028 | JV-Link管理データ | 正規の整理方法を確認後 |
| `C:\jra-sqlserver-migration-stage\20261009` | 14.848080 | 7 | 移行固定版と証跡 | NAS保管後PC不要 |
| `C:\jra-sqlserver-migration-stage\20261010-unified` | 70.385820 | 36 | 移行固定版と証跡 | NAS保管後PC不要 |
| `D:\develop\jra-scr\.workstate\jra-srb` | 0.389762 | 1,912 | 仕様 進捗 呼出補助コード | 現行PC 古い大容量明細NAS |
| `D:\develop\jra-scr\.workstate\logs` | 0.001272 | 116 | APIと収集のログ | 直近PC 過去分NAS |
| `D:\develop\jra-scr\.workstate\manual_checks` | 0.000546 | 4 | 手動検証の出力 | 固有記録確認後削除候補 |
| `D:\develop\jra-scr\.workstate\scripts` | 0.000028 | 4 | 仕様 進捗 呼出補助コード | 現行PC 古い大容量明細NAS |
| `D:\develop\jra-scr\artifacts\jra_research` | 0.001516 | 133 | 研究と予想の成果物 | 現用と実行中はPC 完了版NAS |
| `D:\develop\jra-scr\artifacts\predictions` | 0.036216 | 359 | 研究と予想の成果物 | 現用と実行中はPC 完了版NAS |
| `D:\develop\jra-scr\data` | 0.001085 | 2 | 旧analysisとjob | NASへ切戻し用保管 |
| `D:\develop\jra-scr\data\db` | 0.977633 | 9 | 旧業務DBと修復前backup | 固有記録を照合しNASへ |
| `D:\develop\jra-scr\data\exports\live` | 0.000097 | 3 | 当時の観測 予想 結果 | NASへ復元用保管 |
| `D:\develop\jra-scr\data\jvlink` | 67.814765 | 8 | 旧管理DBと解析オッズ | 原本と派生を分けNASへ 受入後整理 |
| `D:\develop\jra-scr\data\jvlink\catalog` | 0.001073 | 25 | 取得対象キー | 小台帳を保持 原本とNASへ |
| `D:\develop\jra-scr\data\jvlink\raw` | 31.726883 | 21,127,386 | 受信原文bin | 包含確認後NAS保管を集約 |
| `D:\develop\jra-scr\data\jvlink\results` | 1.827894 | 161 | 年別受信DBと試行出力 | 固有原文を確認しNASへ |
| `D:\develop\jra-scr\data\jvlink\results-sample-probe-20260927` | 0.000005 | 8 | 年別受信DBと試行出力 | 固有原文を確認しNASへ |
| `D:\develop\jra-scr\data\jvlink\run-failures` | 0.000001 | 2 | 取得失敗の証跡 | 未解決要約PC 完了証跡NAS |
| `D:\develop\jra-scr\data\jvlink\years` | 0.000189 | 28 | 年次取得の証跡 | 小台帳を保持 原本とNASへ |
| `D:\develop\jra-scr\data\live` | 0.000058 | 4 | 当時の観測 予想 結果 | NASへ復元用保管 |
| `D:\develop\jra-scr\data\live\snapshots` | 0.000097 | 11 | 当時の観測 予想 結果 | NASへ復元用保管 |
| `D:\develop\jra-scr\data\manual_snapshots\2026-07-07_kawasaki_session` | 0.000168 | 9 | 手動取得とセッション記録 | NASへ復元用保管 |
| `D:\develop\jra-scr\data\models\jra_history_recent_form_v2` | 0.000011 | 2 | 学習済みモデル | 現用PC 旧版NAS |
| `D:\develop\jra-scr\data\models\jra_history_v1` | 0.000011 | 3 | 学習済みモデル | 現用PC 旧版NAS |
| `D:\develop\jra-scr\data\raw\jra` | 0.000742 | 10 | 取得原文 | NASへ復元用保管 |
| `D:\develop\jra-scr\data\raw\nankan` | 0.000071 | 1 | 取得原文 | NASへ復元用保管 |
| `D:\develop\jra-scr\data\reference\netkeiba` | 0.000286 | 3 | 外部の補助資料 | NASへ復元用保管 |
| `D:\develop\jra-scr\data\storage` | 0.000001 | 2 | 秘密の接続設定 | PC保持 一般アーカイブ対象外 |
| `D:\develop\jra-scr\data\training\jra_history_recent_form_v2` | 0.008428 | 2 | 旧学習入力と全特徴量 | SQL受入後 再生成可能分削除 |
| `D:\develop\jra-scr\data\training\jra_history_v1` | 0.004669 | 2 | 旧学習入力と全特徴量 | SQL受入後 再生成可能分削除 |
| `D:\develop\jra-scr\data\training\jra_o1o2_asof_v1` | 0.018719 | 21 | 旧学習入力と全特徴量 | SQL受入後 再生成可能分削除 |
| `D:\develop\jra-scr\data\training\jra_o1o2_asof_v1_previous_20260927` | 0.018667 | 12 | 旧学習入力と全特徴量 | SQL受入後 再生成可能分削除 |
| `D:\develop\jra-scr\data\training\jra_o1o2_asof_v2` | 0.188357 | 43 | 旧学習入力と全特徴量 | SQL受入後 再生成可能分削除 |
| `D:\develop\jra-scr\data\training\jv_odds_asof` | 0.000719 | 4 | 旧学習入力と全特徴量 | SQL受入後 再生成可能分削除 |
| `D:\develop\jra-scr\data\training\jv_odds_asof_v1` | 0.001137 | 8 | 旧学習入力と全特徴量 | SQL受入後 再生成可能分削除 |
| `D:\develop\jra-scr\data\training\v89_recovery_v1` | 0.002887 | 2 | 旧学習入力と全特徴量 | SQL受入後 再生成可能分削除 |
| `D:\develop\jra-scr\dist` | 0.000382 | 3 | 配布ビルド | 現用確認後 再生成可能分削除 |
| `D:\develop\jra-scr\tmp` | 0.000990 | 11 | 一時作業出力 | 固有データ確認後削除候補 |
| `D:\develop\jra-van-data-builds\bounded-setup-20260928` | 0.034580 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data-builds\non-jra-filter-20260928` | 0.034580 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data-builds\normal-from-20260928` | 0.034581 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data-builds\rt-date-20260928` | 0.034585 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data-builds\this-week-20260928` | 0.034583 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\adaptive-wait-20260927` | 0.034471 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\custom-recent-probe-fixed-20260929` | 0.000395 | 3 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\fetch-year-retry-mock-smoke` | 0.000705 | 19 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\fetch-year-retry-validation` | 0.034578 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\final-refresh-20261003` | 0.034640 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\final-refresh-tests-20261003` | 0.000417 | 24 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\mock-review-interval-20260927` | 0.034431 | 31 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\mock-smoke-20260927` | 0.034418 | 31 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\odds-retention-probe-validation` | 0.035095 | 55 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\original-repair-20261003` | 0.034638 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\original-repair-tests-20261003` | 0.000188 | 5 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\originals-capture-20261003-final` | 0.034879 | 37 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\originals-capture-20261003-mock-v2` | 0.034491 | 31 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\originals-capture-20261003-validation` | 0.000003 | 6 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\preflight-x86-20260930-0825` | 0.034616 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\recent-odds-date-cli-validation` | 0.034610 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\request-timing-review-final-20260927` | 0.034487 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\request-timing-review-final-20260927-original` | 0.034484 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\request-timing-review-final-20260927-skipfailed-candidate` | 0.034487 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\results-legacy-validation` | 0.034610 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\results-preset-validation` | 0.034579 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\results-range-20261001` | 0.034635 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\results-sample-probe-20260927` | 0.000367 | 29 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\rt-date-no-catalog-fix` | 0.034622 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\sample1-validation-20260929` | 0.000000 | 1 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\sample1-validation-net481-20260929` | 0.002313 | 21 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\sqlite-bulk-mock-20260927` | 0.034422 | 31 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\sqlite-bulk-mock-x64-20260927` | 0.034422 | 31 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\sqlite-bulk-smoke-data-20260927` | 0.000140 | 7 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\sqlite-bulk-vs-20260927` | 0.034477 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\sqlite-lock-fix-20260927` | 0.034483 | 32 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-20260927` | 0.034433 | 31 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data-20260927` | 0.000556 | 15 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data2-20260927` | 0.000705 | 19 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke2-20260927` | 0.034435 | 31 | 旧Exporterビルド | 非現用確認後に削除候補 |
| `D:\develop\jra-van-data\data\acquisition` | 0.000725 | 41 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\catalog-latest-20261003` | 0.001184 | 62 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\master-build-20261005` | 0.000258 | 3 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\original-repair-20261003` | 0.000031 | 14 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-market-validation` | 0.021502 | 44 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation` | 0.002523 | 40 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\pipeline-recovery-doc-update-20261007` | 0.000042 | 3 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\prediction-pipeline-20261005` | 0.000008 | 4 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\prediction-pipeline-cache-recovery-20261007` | 0.000005 | 4 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\prediction-pipeline-capacity-recovery-20261007` | 0.000051 | 7 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\prediction-pipeline-recovery-20261006` | 0.000009 | 6 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\prediction-pipeline-recovery-20261007` | 0.000057 | 5 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\prediction-pipeline-validation-consolidation-20261008` | 0.000054 | 10 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\prediction-pipeline-verified-master-20261008` | 0.000012 | 7 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\prediction-pipeline-verified-master-20261008-attempt-02` | 0.000000 | 2 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\prediction-pipeline-verified-master-20261008-attempt-03` | 0.000061 | 12 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\prediction-pipeline-verified-master-20261008-attempt-04` | 0.000075 | 11 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\acquisition\supplements-20261005` | 0.000719 | 41 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\audits` | 0.002637 | 78 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\audits\original-inventory-20261003` | 0.005224 | 3 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\audits\original-inventory-20261003-after-catalog-update` | 0.005208 | 3 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\audits\original-inventory-20261003-after-repair` | 0.005236 | 3 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\audits\original-inventory-20261003-after-repair-v2` | 0.005218 | 3 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\audits\originals-full-verification-20261005-v2` | 0.819876 | 3 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\audits\originals-verifier-20261003-limited` | 0.002193 | 5 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\audits\progress-display-20261004` | 0.000040 | 2 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\audits\training-settlements-20261002-final` | 0.000359 | 1 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\audits\training-source-20261002-2026` | 0.004037 | 2 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\audits\training-source-20261002-final` | 0.032619 | 7 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\mock-check` | 0.000049 | 2 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\mock-check-x86` | 0.000049 | 2 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\mock-check-x86\raw` | 0.000000 | 2 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\mock-check\raw` | 0.000000 | 2 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\mock-speed-smoke-20260927` | 0.000070 | 2 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\mock-speed-smoke-20260927\raw` | 0.000000 | 2 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\prediction\prediction-20261005` | 0.000000 | 1 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\prediction\prediction-verified-master-20261008-attempt-03` | 0.000000 | 2 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups` | 0.001750 | 123 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\__pycache__` | 0.000137 | 4 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\api-design-records-20261015` | 0.000088 | 2 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\capacity-fixed-candidate-live-integration-20261008` | 0.000073 | 4 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\capacity-fixed-candidate-live-integration-20261008-final` | 0.000128 | 6 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\capacity-fixed-candidate-staging-20261008` | 0.000118 | 2 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\final-reclaim-doc-backup-20261008` | 0.000065 | 3 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\readonly-verify-cache-20261007` | 0.000083 | 1 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\sqlserver2022-finalize-resume-20261014T115631Z` | 0.000148 | 5 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\sqlserver2022-scope-correction-20261014T121200Z` | 0.000136 | 5 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\sqlserver2022-scope-finish-20261014` | 0.000147 | 5 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\verified-master-certificate-staging-20261008` | 0.002600 | 64 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\verified-master-live-integration-20261008` | 0.000153 | 3 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\data\workbackups\verified-master-producer-code-20261008` | 0.000370 | 9 | 取得 検証 復旧の証跡 | 現行状態PC 完了証跡NAS |
| `D:\develop\jra-van-data\tmp` | 0.002850 | 11 | 試行物と復旧記録 | 固有証跡はNAS その他確認後削除 |
| `D:\develop\jra-van-data\tmp\pdfs` | 0.001047 | 2 | 試行物と復旧記録 | 固有証跡はNAS その他確認後削除 |
| `D:\develop\jra-van-data\tmp\prediction-pipeline-launch-prechange-20261005` | 0.000041 | 3 | 試行物と復旧記録 | 固有証跡はNAS その他確認後削除 |
| `D:\develop\jra-van-data\tmp\probe-open-build` | 0.034612 | 32 | 試行物と復旧記録 | 固有証跡はNAS その他確認後削除 |
| `D:\develop\jra-van-data\tmp\run-jv-original-supplements-prechange-20261005` | 0.000034 | 2 | 試行物と復旧記録 | 固有証跡はNAS その他確認後削除 |
| `D:\develop\jra-van-data\tmp\status-backup-20261005-pilot` | 0.000035 | 1 | 試行物と復旧記録 | 固有証跡はNAS その他確認後削除 |
| `D:\develop\jra-van-data\tmp\verify-jv-originals-prechange-20261005` | 0.000058 | 2 | 試行物と復旧記録 | 固有証跡はNAS その他確認後削除 |

## SQLite本体と修復前backupの個別一覧

SQLiteの16 byteヘッダを確認した98ファイルを物理パス別に列挙する。NASの大容量SQLiteは前掲の既存保管物表を参照。WALとSHMは本体と一組で確認し、単独で削除しない。名称にSqliteを含むDLL30本と3 byteの検証ダミー1本はDB本体に数えず、ソフトと試行物に分類する。

| ファイル | MB | 保管用途 |
|---|---:|---|
| `C:\jra-sqlserver-migration-stage\20261009\jra-prediction-2026-09-27.sqlite` | 4.366 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261009\jra-prediction.sqlite` | 14843.630 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\analysis-current.sqlite` | 425.394 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\analysis-legacy.sqlite` | 1.073 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jobs-current.sqlite` | 0.012 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2003.sqlite` | 115.130 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2004.sqlite` | 67.150 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2005.sqlite` | 67.232 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2006.sqlite` | 68.518 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2007.sqlite` | 68.350 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2008.sqlite` | 70.099 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2009.sqlite` | 67.576 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2010.sqlite` | 59.593 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2011.sqlite` | 58.466 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2012.sqlite` | 59.240 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2013.sqlite` | 59.949 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2014.sqlite` | 60.490 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2015.sqlite` | 59.179 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2016.sqlite` | 59.269 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2017.sqlite` | 59.150 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2018.sqlite` | 58.687 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2019.sqlite` | 57.385 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2020.sqlite` | 58.065 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2021.sqlite` | 57.033 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2022.sqlite` | 122.581 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2023.sqlite` | 161.595 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2024.sqlite` | 56.439 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2025.sqlite` | 57.246 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jv-results-2026.sqlite` | 52.793 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\jvlink-current.sqlite` | 11862.106 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\odds-parsed-current.sqlite` | 55952.495 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\validation-live-capture.sqlite` | 1.622 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\validation-market-capture.sqlite` | 20.836 | 移行固定版と証跡 |
| `C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\delta-20261013T133139Z\analysis-current.sqlite` | 441.000 | 移行固定版と証跡 |
| `D:\develop\jra-scr\.workstate\manual_checks\ttl_manual_check\analysis.sqlite` | 0.270 | 手動検証の出力 |
| `D:\develop\jra-scr\.workstate\manual_checks\ttl_manual_check\cache.sqlite` | 0.012 | 手動検証の出力 |
| `D:\develop\jra-scr\data\analysis.sqlite` | 1.073 | 旧analysisとjob |
| `D:\develop\jra-scr\data\db\analysis-verify.sqlite` | 5.140 | 旧業務DBと修復前backup |
| `D:\develop\jra-scr\data\db\analysis.sqlite` | 441.000 | 旧業務DBと修復前backup |
| `D:\develop\jra-scr\data\db\analysis.sqlite.bak_20260709_2055` | 83.874 | 旧業務DBと修復前backup |
| `D:\develop\jra-scr\data\db\analysis.sqlite.bak_before_2024_course_repair_20260711` | 91.341 | 旧業務DBと修復前backup |
| `D:\develop\jra-scr\data\db\analysis.sqlite.bak_before_v89_20260711` | 85.815 | 旧業務DBと修復前backup |
| `D:\develop\jra-scr\data\db\analysis.sqlite.bak_before_v90_2024_batch01` | 90.997 | 旧業務DBと修復前backup |
| `D:\develop\jra-scr\data\db\analysis.sqlite.bak_before_v90_2024_external` | 92.893 | 旧業務DBと修復前backup |
| `D:\develop\jra-scr\data\db\analysis.sqlite.bak_before_v90_20260711_live` | 86.303 | 旧業務DBと修復前backup |
| `D:\develop\jra-scr\data\db\test_bet_records_nankan.sqlite` | 0.270 | 旧業務DBと修復前backup |
| `D:\develop\jra-scr\data\jobs.sqlite` | 0.012 | 旧analysisとjob |
| `D:\develop\jra-scr\data\jvlink\jvlink.sqlite` | 11862.102 | 旧管理DBと解析オッズ |
| `D:\develop\jra-scr\data\jvlink\odds-parsed.sqlite` | 55952.495 | 旧管理DBと解析オッズ |
| `D:\develop\jra-scr\data\jvlink\results\2003\results.sqlite` | 115.130 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2004\results.sqlite` | 67.150 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2005\results.sqlite` | 67.232 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2006\results.sqlite` | 68.518 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2007\results.sqlite` | 68.350 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2008\results.sqlite` | 70.099 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2009\results.sqlite` | 67.576 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2010\results.sqlite` | 59.593 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2011\results.sqlite` | 58.466 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2012\results.sqlite` | 59.240 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2013\results.sqlite` | 59.949 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2014\results.sqlite` | 60.490 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2015\results.sqlite` | 59.179 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2016\results.sqlite` | 59.269 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2017\results.sqlite` | 59.150 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2018\results.sqlite` | 58.687 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2019\results.sqlite` | 57.385 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2020\results.sqlite` | 58.065 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2021\results.sqlite` | 57.033 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2022\results.sqlite` | 122.581 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2023\results.sqlite` | 161.595 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2024\results.sqlite` | 56.439 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2025\results.sqlite` | 57.246 | 年別受信DBと試行出力 |
| `D:\develop\jra-scr\data\jvlink\results\2026\results.sqlite` | 52.793 | 年別受信DBと試行出力 |
| `D:\develop\jra-van-data\builds\custom-recent-probe-fixed-20260929\results\2026\results.sqlite` | 0.393 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\fetch-year-retry-mock-smoke\batch-check\jvlink.sqlite` | 0.004 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\fetch-year-retry-mock-smoke\failure-check\jvlink.sqlite` | 0.004 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\fetch-year-retry-mock-smoke\jvlink.sqlite` | 0.004 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\fetch-year-retry-mock-smoke\wal-reader-check\jvlink.sqlite` | 0.004 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\sqlite-bulk-smoke-data-20260927\batch-check\jvlink.sqlite` | 0.070 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\sqlite-bulk-smoke-data-20260927\jvlink.sqlite` | 0.070 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data-20260927\batch-check\jvlink.sqlite` | 0.004 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data-20260927\jvlink.sqlite` | 0.004 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data-20260927\wal-reader-check\jvlink.sqlite` | 0.004 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data2-20260927\batch-check\jvlink.sqlite` | 0.004 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data2-20260927\failure-check\jvlink.sqlite` | 0.004 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data2-20260927\jvlink.sqlite` | 0.004 | 旧Exporterビルド |
| `D:\develop\jra-van-data\builds\sqlite-lock-fix-smoke-data2-20260927\wal-reader-check\jvlink.sqlite` | 0.004 | 旧Exporterビルド |
| `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-market-validation\capture\jv-originals.sqlite` | 20.836 | 取得 検証 復旧の証跡 |
| `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\live-race-week\jv-originals.sqlite` | 1.622 | 取得 検証 復旧の証跡 |
| `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\mock-v2\batch-check\jvlink.sqlite` | 0.004 | 取得 検証 復旧の証跡 |
| `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\mock-v2\failure-check\jvlink.sqlite` | 0.004 | 取得 検証 復旧の証跡 |
| `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\mock-v2\jvlink.sqlite` | 0.004 | 取得 検証 復旧の証跡 |
| `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\mock-v2\originals-check\jv-originals.sqlite` | 0.045 | 取得 検証 復旧の証跡 |
| `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\mock-v2\originals-rollback-check\jv-originals.sqlite` | 0.045 | 取得 検証 復旧の証跡 |
| `D:\develop\jra-van-data\data\acquisition\originals-capture-20261003-validation\mock-v2\wal-reader-check\jvlink.sqlite` | 0.004 | 取得 検証 復旧の証跡 |
| `D:\develop\jra-van-data\data\mock-check-x86\jvlink.sqlite` | 0.049 | 取得 検証 復旧の証跡 |
| `D:\develop\jra-van-data\data\mock-check\jvlink.sqlite` | 0.049 | 取得 検証 復旧の証跡 |
| `D:\develop\jra-van-data\data\mock-speed-smoke-20260927\jvlink.sqlite` | 0.070 | 取得 検証 復旧の証跡 |

## 棚卸しデータと根拠

- [用途分類付き統合JSON](../../notes/storage-classified-inventory-20261016.json)
- [jra-scrの容量と主要DB](../../notes/storage-inventory-20261016.json) 受信bin群は別集計として明示除外
- [受信bin群のWindows標準集計](../../notes/storage-raw-native-inventory-20261016.json) 一覧モード 21,127,386 files 31,726,882,932 bytes 失敗0
- [C移行stageと関連取得案件](../../notes/storage-related-inventory-20261015.json)
- [JV-Link管理領域の内訳](../../notes/storage-jvlink-cache-detail-20261016.json)
- [SQL Server API切替と復旧](../jra/30_SQLServer_API切替と復旧.md)
- [研究移行の進捗](../../.workstate/jra-srb/sqlserver-model-data-audit/progress/002-進捗サマリ.md)
- [研究移行の受入台帳](../../configs/research/acceptance_registry.json)
- 別案件の移行台帳 D:/develop/jra-van-data/infra/sqlserver2022-poc/unified-source-manifest.json
- NAS originals/snapshot-20261007/manifest.json と既存archive/proofs記録

2026-10-15夜の関連案件集計と、2026-10-16朝のjra-scrとJV-Link集計を組み合わせた。全体の更新を止めるsnapshotは取得していない。元データ全件SHA、原本マスターへの全件包含、圧縮率、復元試験、NASの利用可能容量と割当上限は今回の測定範囲外。

## 2026-10-17最新訂正：移行完了証跡の再利用

利用者指定のD:/develop/jra-van-data/data/audits/sqlserver2022-scope-completion-20261014.jsonを確認。192/192表・470,517,746行照合済み、pending/mismatch=0、analysis-current差分29表採用済み。移行は完了済みとして扱い、同じ全量検証・再取得・全量再投入を削除判断や研究開始の前提にしない。対象ファイルが証明対象版と一致するか、固定後更新・稼働参照がないかを限定確認する。全優先研究の完成を全ファイル削除の一律条件とする前節の扱いを訂正する。削除未実行。詳細は研究監査progress/034。
