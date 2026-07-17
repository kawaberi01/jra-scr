# 005-JRAオッズsnapshot追記保存現行仕様整理

## 1. 実コードで確認した事実

- `odds_snapshots`は`unique(race_id, bet_type, odds_timing)`を持つ。
- `write_odds()`は固定的なsnapshot IDでupsertし、既存entryを削除して再挿入する。
- `get_odds_timeline()`は`fetched_at, snapshot_id`順に全snapshotを返す。
- `get_pre_race_snapshot()`は時点指定なしでは券種ごとの最新を返すが、時点指定ありでは該当行をすべて返す。
- analysis collectorは`skip_existing=False`なら再取得する。
- timeline collectorは既存snapshotがあれば常にskipする。

## 2. 現行の問題

| 要件 | 現行 | 差分 |
| --- | --- | --- |
| 過去世代保持 | upsertで上書き | 一意制約と固定IDを廃止 |
| 再取得経路 | analysis collectorのみ条件付き | timeline collectorへ明示optionが必要 |
| timeline参照 | 並び順は対応済み | 複数世代を保存すれば流用可能 |
| snapshot参照互換 | 現状1世代前提 | 指定時点でも最新1世代/券種へ限定 |
| 既存DB | unique制約あり | データ保持migrationが必要 |

## 3. 入出力・副作用

- 入力: `RaceOdds`、券種、`odds_timing`。
- DB副作用: `odds_snapshots`と`odds_entries`。
- 参照出力: `StoredPreRaceSnapshot`、`StoredOddsTimeline`。
- CLI: `collect-jra-odds-timeline`。

## 4. 実コード優先で採用する判断

- snapshot IDは書込ごとに新規生成する。
- timeline APIは全世代を`fetched_at, snapshot_id`順で返す。
- pre-race snapshot APIは指定時点の有無にかかわらず、各券種の最新世代だけを返す。
- `has_odds_snapshot()`は「1世代以上存在する」の意味を維持する。
- timeline collectorは`refresh_existing=False`を既定とし、明示時だけ既存ラベルへ追記する。

## 5. 対象外

- races/runnersの履歴化。
- snapshotの削除・保持期間管理。
- indexの性能最適化。
