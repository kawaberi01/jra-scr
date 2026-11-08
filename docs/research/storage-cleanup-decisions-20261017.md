# PC容量整理：削除対象と実施順

2026-10-25更新：A～Cの削除を実施。[最新の実施結果・保持対象・残件](storage-cleanup-result-20261025.md)を参照。以下は当時の判断記録。

作成日: 2026-10-17 JST。既存98ファイルの台帳・移行証跡・現在のファイル情報を照合した。**削除・移動・圧縮は未実施。**

## 結論

**最初は2つのDBと付随ファイル、計6ファイル・70,796,189,696 bytes（約70.80GB）をPCから除去する対象とする。** 保持側を残すことで、この段階では巨大なNAS追加コピーは必要ない。

現用の旧SQLite非依存は[受入済み](sqlite-independence-acceptance-20261017.md)。今回も研究の再実行・再移行・SQLite内容照会は行っていない。旧データの内容を研究入力として使うための確認ではなく、削除対象の版と保管先の確認である。

## 第1対象：具体的な6ファイル

| PCから除去する絶対パス | bytes | 保持するもの・根拠 |
|---|---:|---|
| `C:\jra-sqlserver-migration-stage\20261009\jra-prediction.sqlite` | 14,843,629,568 | NASの同一SHA保管物。Cのcopy-manifestに転送時SHAと転送後の全SHA一致あり。現在も長さ・mtime・file IDが移行固定版と一致 |
| `C:\jra-sqlserver-migration-stage\20261009\jra-prediction.sqlite-wal` | 0 | 上記本体と同じ単位。未反映データを含まない長さ0 |
| `C:\jra-sqlserver-migration-stage\20261009\jra-prediction.sqlite-shm` | 32,768 | 上記本体のsidecar。本体と一組で扱う |
| `D:\develop\jra-scr\data\jvlink\odds-parsed.sqlite` | 55,952,494,592 | SQL移行済み。取得元の長さ・mtime・file ID・deviceが固定記録と一致。C側の一貫した移行固定版を保持し、同時に削除しない |
| `D:\develop\jra-scr\data\jvlink\odds-parsed.sqlite-wal` | 0 | 固定時と同じ長さ・mtimeの0 byte WAL |
| `D:\develop\jra-scr\data\jvlink\odds-parsed.sqlite-shm` | 32,768 | 上記本体と一組で扱う |

この一覧は削除実行用コマンドではない。[対象manifest](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261017/first-batch-targets.json)に期待する長さ・mtime・file ID・deviceを保存した。実行直前の状態が変わっていれば、その単位の削除を止める。

### 必ず保持する側

- Cの全期間DBに対応するNAS版：`\\192.168.1.101\jra\jra-van-data\prediction\full-20261005-verified-20261008\jra-prediction.sqlite`
- Dの解析済みオッズに対応するC固定版：`C:\jra-sqlserver-migration-stage\20261010-unified\snapshots\20261009T164315Z\odds-parsed-current.sqlite`
- NASのSQLバックアップ：`\\192.168.1.101\jra\sqlserver2022-poc\jra_unified_20261016_053626.bak`
- 現在のSQL Server本体・ログ・設定、利用中モデルとコード。

Dのオッズを除去した後に、Cの統合移行フォルダー全体を続けて削除してはいけない。C固定版を残すことが第1対象の保全条件である。Cの20261009フォルダーも丸ごとではなく、上表3ファイルだけが対象。4.37MBのサンプルDBと小さなmanifest/コードは残す。

### 実行直前と実行後

具体的な6ファイルに対する削除指示を受けたら、対象と保持側の所在・長さ・mtime等、WAL状態、親パスのreparse属性、使用中でないことを再確認する。対象が期待する絶対パス内にあることを確かめ、PowerShellのLiteralPathで指定ファイルだけを除去する。ファイルを使用中なら無断でプロセスを止めない。

完了後にC/D空きを再測定する。約70.80GBは論理ファイル長で、空き容量の増加保証値ではない。対象親フォルダー・NAS・原本マスターの再帰削除を行わない。

## 98ファイル全体の判断

| 区分 | 本体/backup数 | 本体の論理容量 | 決定 |
|---|---:|---:|---|
| A：第1対象 | 2 | 70.796GB | 上記6ファイルとして具体化。保持側を残して除去する対象 |
| B：その他の移行済み元DB・固定版 | 62 | 84.394GB | 移行対応あり。C/Dの同じ原版を双方から失わないよう、一度だけ保管した後にPCから除去する対象 |
| C：修復前の旧版backup | 6 | 0.531GB | 移行manifestでは明示除外。現用と同じデータとは仮定せず、小容量なのでNASへ一度保管後にPCから除去する対象 |
| D：少量の試行・派生DB | 28 | 0.011GB | 第1対象から外して保持。除外理由・固有記録の保管を確定してから除去。大容量整理を待たせる条件にはしない |

本表はSQLite本体/backup98件の合計約155.732GB。受信bin31.727GBやJV-Link管理キャッシュ等を含む全体195.584GBとは母集団が異なる。sidecarは本体数に含めない。[98件の個別判断CSV](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261017/deletion-decisions.csv)に絶対パス・容量・移行元キー・区分を記録した。

Bの62件を無条件にすべてNASへ追加コピーする意味ではない。Cの固定コピーとDの元ファイルは同一保管単位へ対応付け、同じ版を重ねて保管しない。解析済みオッズ固定版の最終保管/廃棄判断はBの段階で行い、第1対象実行と同時に処分しない。

## 後続の実施順

1. **Aの約70.80GBを先に整理。** 新たな大容量コピーなし。Cに約14.84GB、Dに約55.95GBの論理容量を確保する候補。
2. **Bの原版保管を単位別に確定。** C統合移行コピー約70.386GB、Dの旧JV-Link管理DB約11.862GB、年別DB約1.681GB、旧業務DB等を対応付ける。同じ版は一度だけ保管。保管と照合が済んだ単位だけ除去する。
3. **Cの旧backup約0.531GBを小さな保管単位として退避。** 予想・購入・評価の過去版を失わない。旧研究を再計算しない。
4. **受信bin約31.727GBは別単位。** 約2,113万ファイルの再棚卸しは開始しない。原本マスターへの包含・来歴の既存証跡で取得単位を対応付け、包含不明分だけを一度保管する。今回はbin単位ごとの削除許可まで確定していない。
5. **少量の試行物・JV-Link管理キャッシュ、SQL内の不要データ整理は後続。** SQLデータ削除はNAS側容量の別作業。今回のPC整理へ混ぜない。

現用モデル・接続設定・直近記録・研究結果資料はPCに保持する。今回の容量整理で過去不採用研究の再現や全21プロファイルを条件に戻さない。

## 今回確認した事実

- 98ファイルすべてが存在し、10/16棚卸しのサイズ・更新日時と一致。DB内容は開いていない。
- 64ファイルを基準manifestの33入力またはanalysis差分の移行元/固定版に対応付けた。64はモデル数・テーブル数ではない。
- 基準33入力の現在の長さ・mtime・file ID・deviceが固定元の記録と一致。analysis-currentは採用済み差分を使い、旧基準の425MBと誤比較していない。
- 旧analysis/jobsは10/15最終同期のmain/WAL記録と一致。SQL移行完了192/192表・470,517,746行、pending/mismatch=0の証跡を再利用した。
- C全期間DBはcopy-manifestのSHA `c7fbddf171fe96996a04622fc85ac9c6d002221b5cb403c0e5552b730e9dda62` がNAS既存保管証跡と一致。NAS側も同じ長さ・mtimeで存在する。今回14.84GBを再ハッシュしていない。
- NASの原本マスター149,929,996,288 bytesを確認。既存の全SHA読戻し証跡を再利用し、現在も長さ・mtimeが一致。149.93GBの再ハッシュはしていない。
- NAS原本DB13本がすべて存在し、保管証跡の長さと一致。過去の元/先SHA一致証跡あり。ただし、これだけでPCのbin群すべての包含確認済みとは扱わない。
- 利用者が完了を報告したSQLバックアップの所在を特定。116,499,734,528 bytes。今回確認したのは所在・長さ等で、実復元試験を追加実行したわけではない。
- 観測時の空きはC:16,734,302,208 bytes、D:47,372,722,176 bytes。今回整理による空き増加は0。

## 証跡・再開点

- [ファイル情報と根拠JSON](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261017/candidate-evidence.json)
- [移行対応CSV](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261017/candidate-files.csv)
- [98件の削除判断CSV](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261017/deletion-decisions.csv)
- [第1対象6件manifest](../../.workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261017/first-batch-targets.json)
- [元の保管計画](storage-retention-plan-20261016.md)

次の実行単位はAの6ファイル。まだ削除指示は受けていない。B〜DとbinはAの削除対象に含めない。原本マスターやSQLバックアップを削除対象にしない。
