# 010-JRAオッズsnapshot追記保存実装仕様書

## 0. 最初に読む要約

- 対象機能: JRAオッズsnapshot追記保存
- 改修目的: 再取得したオッズを上書きせず世代として保持する。
- 現行仕様の要点: DB一意制約と固定snapshot IDにより同一ラベルはupsertされる。
- 最重要注意点: 既存DBを無損失で移行し、pre-race snapshot APIの応答件数を増やさない。

## 1. 変更後仕様

### 保存

- `odds_snapshots`から`unique(race_id, bet_type, odds_timing)`を除く。
- `write_odds()`呼出しごとにUUIDを含む新規snapshot IDを生成する。
- 既存snapshot/entryを削除しない。
- 1回の`write_odds()`内のsnapshotとentryは同一transactionで保存する。

### 既存DB migration

1. `pragma index_list/index_info`で旧3列unique indexを検出する。
2. 旧tableを一時名へrenameする。
3. 新schemaで`odds_snapshots`を作る。
4. 全行を同じsnapshot IDのままcopyする。
5. 旧tableをdropする。
6. `(race_id, bet_type, odds_timing, fetched_at)`の非unique indexを作る。

`odds_entries`はsnapshot IDが変わらないためcopy不要。

### 参照

- `get_odds_timeline()`: 全世代を古い順に返す。
- `get_pre_race_snapshot()`: 各券種の最新世代のみ返す。`odds_timing`指定時も同じ。
- `has_odds_snapshot()`: 1件以上で`True`。

### collector/CLI

- `JraOddsTimelineCollector.collect(refresh_existing=False)`を追加する。
- `False`: 従来どおり既存ラベルをskipする。
- `True`: 既存ラベルも再取得して新世代として保存する。
- CLIへ`--refresh-existing`を追加する。

## 2. 実装配置

- 修正: `src/jra_srb/analysis_store.py`
- 修正: `src/jra_srb/jra_odds_timeline.py`
- 修正: `src/jra_srb/cli.py`
- 修正: `tests/test_analysis_store.py`
- 修正: `tests/test_jra_odds_timeline.py`
- 必要に応じて`tests/test_cli.py`
- 新規層・依存追加: なし。

## 3. 根拠

| 判断 | 根拠 |
| --- | --- |
| 旧unique制約 | `analysis_store.py:101-109` |
| 現行upsert | `analysis_store.py:732-760` |
| timeline全行取得 | `analysis_store.py:2173`付近 |
| timeline collectorの既存skip | `jra_odds_timeline.py:135` |
| CLI入口 | `cli.py:147`付近、`cli.py:325`付近 |

## 4. エラー・設定

- migration失敗はDB初期化エラーとして伝播する。
- 新しい環境変数や外部依存は追加しない。
- CLI option未指定時の挙動は変更しない。

## 5. テスト観点

- 同一レース・券種・ラベルを2回保存するとsnapshot/entryが2世代残る。
- timelineが2世代を古い順に返す。
- pre-race snapshotは最新世代だけを返す。
- 旧schema fixtureから初期化しても既存行を保持し、追記可能になる。
- collectorは既定でskipし、`refresh_existing=True`で追記する。
- CLI optionがcollectorへ渡る。

## 6. 対象外

- 既存snapshotの重複排除。
- retention、削除API。
- races/runnersのas-of履歴化。

## 7. 要確認事項

- なし。現行構成内で実装可能。
