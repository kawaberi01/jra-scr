# netkeiba 補完データ analysis.sqlite 保存 利用ガイド

## 実装状況

実装は完了しています。

- netkeiba `race_result` を `analysis.sqlite` に保存できます。
- netkeiba `odds_view` は、全件ではなく指定済みの買い目だけ保存できます。
- 保存済みの `race_result` は、通常は再取得しません。
- `--refresh` を付けた場合だけ再取得します。
- 大量アクセスを避けるため、バッチにはライブ取得上限とアクセス間隔があります。

確認済みテスト:

```powershell
rtk .venv-win\Scripts\pytest.exe -q
```

結果:

```text
100 passed, 1 skipped, 1 warning
```

## 保存先テーブル

`analysis.sqlite` に以下の netkeiba 専用テーブルを作成します。

- `netkeiba_race_results`
- `netkeiba_result_entries`
- `netkeiba_payouts`
- `netkeiba_odds_entries`

既存の JRA 公式向けテーブルは変更しません。

## 重要: race_id の対応表が必要

JRA の race_id と netkeiba の race_id は直接一致しません。

例:

```text
JRA      : 202606280301
netkeiba : 202603020201
```

そのため、バッチ収集には対応表 CSV を渡します。

## 対応表 CSV の形式

例: `data/netkeiba_race_mapping.csv`

```csv
jra_race_id,netkeiba_race_id,race_date,course,race_no,mapping_status,mapping_note
202606280301,202603020201,2025-10-01,fukushima,1,mapped,calendar course=fukushima meeting=3 day=1
202606280302,,2025-10-01,unknown,2,unmapped,unsupported course=unknown
```

必須列:

- `netkeiba_race_id`

推奨列:

- `jra_race_id`
- `race_date`
- `course`
- `race_no`
- `mapping_status`
- `mapping_note`

`race_date` がある場合、`--from-date` / `--to-date` の範囲で絞り込みます。

`generate-netkeiba-mapping` で生成する場合、CSV の `course` は `races.course` ではなく `jra_race_id` の 9〜10 桁目の JRA 場コードから復元します。`races.course` に「コース： 1,600 メートル （ダート・左）」のような条件文字列が入っていても、`202510040501` なら `05 -> tokyo` として出力します。

`mapping_status` は以下を想定します。

- `mapped`: 確定した対応
- `mapped_estimated`: 開催カレンダーなしで推定した対応
- `unmapped`: 対応不能。`mapping_note` に理由を出力

## 対応表 CSV を生成する

既存 `analysis.sqlite` の `races` から対応表 CSV を生成できます。

```powershell
jra-srb generate-netkeiba-mapping `
  --from-date 2025-10-01 `
  --to-date 2025-12-31 `
  --db data/analysis.sqlite `
  --output data/netkeiba_race_mapping.validation_2025q4.csv
```

このコマンドは netkeiba へアクセスしません。

正確な netkeiba race_id には開催回次と開催日次が必要です。開催カレンダーを持っている場合は `--meeting-calendar-csv` を渡してください。

```powershell
jra-srb generate-netkeiba-mapping `
  --from-date 2025-10-01 `
  --to-date 2025-12-31 `
  --db data/analysis.sqlite `
  --output data/netkeiba_race_mapping.validation_2025q4.csv `
  --meeting-calendar-csv data/netkeiba_meeting_calendar.2025q4.csv
```

開催カレンダー CSV 例:

```csv
course,meeting_no,start_date,start_day_no
tokyo,4,2025-10-04,1
tokyo,5,2025-11-01,1
nakayama,5,2025-12-06,1
```

開催カレンダーを渡さない場合、`meeting_no=1` の推定値として `mapping_status=mapped_estimated` を出力します。validation 本番用途では開催カレンダー CSV を使ってください。

## race_result を保存する

```powershell
jra-srb collect-netkeiba-results `
  --from-date 2025-10-01 `
  --to-date 2025-10-31 `
  --db data/analysis.sqlite `
  --mapping-csv data/netkeiba_race_mapping.csv `
  --max-live-requests 30 `
  --min-interval-seconds 10
```

動作:

- CSV から対象 netkeiba race_id を読む
- `netkeiba_race_results` に保存済みならスキップする
- 未保存のレースだけ netkeiba にアクセスする
- 取得成功後、結果詳細と払戻を SQLite に保存する
- 取得失敗は `collection_errors` に `stage = netkeiba-result` で記録する

## dry-run で確認する

netkeiba にアクセスせず、対象件数と取得予定件数だけ確認できます。

```powershell
jra-srb collect-netkeiba-results `
  --from-date 2025-10-01 `
  --to-date 2025-12-31 `
  --db data/analysis.sqlite `
  --mapping-csv data/netkeiba_race_mapping.validation_2025q4.csv `
  --max-live-requests 30 `
  --dry-run
```

出力例:

```text
run_id=- dry_run=True targets=720 saved=100 unsaved=610 planned=30 unmappable=10 collected=0 skipped=100 failed=0 limit_reached=True
```

## limit で対象を絞る

テストや評価前の小規模確認では `--limit` を使います。`--limit` は mapping CSV の対象レースを先頭 N 件に絞ります。

```powershell
jra-srb collect-netkeiba-results `
  --from-date 2025-10-01 `
  --to-date 2025-12-31 `
  --db data/analysis.sqlite `
  --mapping-csv data/netkeiba_race_mapping.validation_2025q4.csv `
  --limit 20 `
  --max-live-requests 5 `
  --min-interval-seconds 10
```

`--limit` は対象抽出の上限です。`--max-live-requests` は実際に netkeiba へアクセスする回数の上限です。

## 再取得する

保存済みデータを上書きしたい場合だけ `--refresh` を付けます。

```powershell
jra-srb collect-netkeiba-results `
  --from-date 2025-10-01 `
  --to-date 2025-10-31 `
  --db data/analysis.sqlite `
  --mapping-csv data/netkeiba_race_mapping.csv `
  --max-live-requests 10 `
  --min-interval-seconds 10 `
  --refresh
```

## odds_view の保存方針

`odds_view` は初期段階では全件保存しません。

予想エージェントが参照した買い目だけ、service で絞ってから `AnalysisSQLiteStore.write_netkeiba_odds()` で保存します。

例:

```python
from pathlib import Path

from jra_srb.analysis_store import AnalysisSQLiteStore
from jra_srb.netkeiba_service import NetkeibaService


async def save_referenced_odds():
    service = NetkeibaService()
    store = AnalysisSQLiteStore(Path("data/analysis.sqlite"))

    odds = await service.get_race_odds(
        "202603020201",
        bet_type="wide",
        combination=["5", "13"],
    )

    store.write_netkeiba_odds(
        odds,
        jra_race_id="202606280301",
        bet_type="wide",
    )
```

保存先:

- `netkeiba_odds_entries`

## 再開可能性

途中で止まった場合は、同じコマンドを再実行してください。

`--refresh` なしであれば保存済みレースはスキップされるため、未取得分から進められます。

## 注意点

- netkeiba へのライブ取得は JRA 公式サイトとは別のアクセスです。
- 無制限クロール前提ではありません。
- `--max-live-requests` と `--min-interval-seconds` を必ず現実的な値にしてください。
- JRA race_id と netkeiba race_id の自動対応付けは未対応です。
