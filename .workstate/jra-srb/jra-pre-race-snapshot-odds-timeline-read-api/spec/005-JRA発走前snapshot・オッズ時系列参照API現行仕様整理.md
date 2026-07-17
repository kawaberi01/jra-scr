# 005-JRA発走前snapshot・オッズ時系列参照API現行仕様整理

## 0. 要約

- `AnalysisSQLiteStore.get_pre_race_snapshot(race_id)` は発走前のレース、出走馬、全オッズsnapshotをdictで返す。
- 発走前snapshotを公開するHTTP APIはない。
- `JraOddsTimelineCollector` は既定運用で発走30分前、10分前、2分前の単勝・ワイドを保存する。
- 結果系テーブルは発走前系と分離され、既存テストもsnapshotに結果・払戻がないことを確認している。
- オッズの並びは現在`bet_type, odds_timing`の文字列順であり、時間順を保証しない。

## 1. 実コードで確認した事実

### 1.1 入口と呼び出し経路

| 種別 | パス | 行 | 役割 |
| --- | --- | ---: | --- |
| Store | `src/jra_srb/analysis_store.py` | 1943 | `get_pre_race_snapshot(race_id)`でrace/runners/oddsを取得 |
| Store | `src/jra_srb/analysis_store.py` | 612 | `write_odds()`で時点別オッズを保存 |
| Store | `src/jra_srb/analysis_store.py` | 745 | 時点別snapshotの存在確認 |
| Collector | `src/jra_srb/jra_odds_timeline.py` | 83 | 開催と発走時刻から収集タスクを実行 |
| API | `src/jra_srb/app.py` | 369 | `JRA_SRB_ANALYSIS_DB_PATH`を使うStore依存 |
| Test | `tests/test_analysis_store.py` | 150 | 発走前snapshotと結果リーク防止を検証 |

現行の収集経路:

1. `JraOddsTimelineCollector.collect()`が当日の開催一覧を取得する。
2. 発走時刻から`OddsTimelineTask`を作る。
3. `t_minus_<N>m`を`odds_timing`としてJRAオッズを取得する。
4. `AnalysisSQLiteStore.write_race()`と`write_odds()`でSQLiteへ保存する。
5. 参照時はPythonコードから`get_pre_race_snapshot()`を直接呼ぶ。

### 1.2 DB契約

- `races`: `race_id`主キー。日付、開催場、レース番号、名称、発走時刻、馬場種別、距離等を保持。
- `runners`: `(race_id, horse_no)`主キー。発走前出走馬情報を保持。
- `odds_snapshots`: `(race_id, bet_type, odds_timing)`がunique。
- `odds_entries`: snapshot配下の組み合わせ、オッズ、人気を保持。
- `race_results`、`result_entries`、`payouts`は別テーブル。

`write_odds()`は同じ`race_id / bet_type / odds_timing`をupsertした後、既存`odds_entries`を削除して入れ直す。このため同一時点ラベルの再取得履歴は残らない。

### 1.3 現行の入力・出力

`get_pre_race_snapshot(race_id)`:

- 入力: 12桁JRA `race_id`相当の文字列。ただしStore自身には形式検証なし。
- 出力:
  - `race`: DB rowのdict
  - `runners`: 馬番数値順のdict配列
  - `odds`: snapshotメタデータとentriesの配列
- raceが存在しない場合: `LookupError`
- oddsがなくてもraceが存在すれば空配列。
- 結果、払戻、評価は取得しない。

### 1.4 収集時点

- `OddsTimelineTask.timing_label`: `t_minus_<offset_minutes>m`
- 既定PowerShell運用:
  - courses: `all`
  - bet types: `win,wide`
  - offsets: `30,10,2`
  - DB: `data/db/analysis.sqlite`
- 90秒を超える遅延はskipする。
- 既存snapshotがあれば再取得しない。
- 外部取得失敗は件数化し、標準出力へ記録する。

## 2. 現行APIの流儀

- FastAPIのrouteを`src/jra_srb/app.py`へ定義する。
- Pydantic response modelを`src/jra_srb/models.py`へ置く。
- 分析DBは`get_analysis_store()`から注入する。
- 12桁JRA race_idは`RaceIdPath`で422検証する。
- Storeの`LookupError`は共通handlerで404 `not_found`へ変換する。
- 保存済み予想・評価GET APIは`jra-analysis` tagを使用する。
- MCPは`MCP_OPERATION_IDS`のallowlist方式であり、追加しなければ公開されない。

## 3. 現行仕様の問題

1. HTTP利用者は発走前snapshotを参照できず、SQLite直接参照が必要。
2. オッズ時系列だけを券種・組み合わせ指定で取得するStore/APIがない。
3. 現行snapshotのオッズは全時点を一括返却し、単一時点のsnapshotという意味が曖昧。
4. `order by odds_timing`は`t_minus_10m / 2m / 30m`を時間順に並べない。
5. 公開レスポンスにDB列名`combination_json`がそのまま現れる。
6. `races/runners`は履歴化されていないため、過去時点の完全な出馬表を再現できない。

## 4. Reference・既存資料との差分

| 既存資料の仮説 | 実コードの事実 | 採用判断 |
| --- | --- | --- |
| `get_pre_race_snapshot`は結果を含めない | 結果系テーブルをqueryせず、既存テストも非混入を確認 | 一致 |
| `odds_timing`を指定してsnapshotを取得する | 現行Storeは引数を持たず全時点を返す | API/Store拡張対象 |
| 時系列オッズを保存する | 時点ラベル単位では保存するが同一ラベルは上書き | 実コード優先で離散系列と定義 |
| 発走前snapshotは予想時点を完全再現できる | race/runnerは版管理されない | 未対応。対象外として明記 |

## 5. 影響範囲

- 修正候補:
  - `src/jra_srb/models.py`
  - `src/jra_srb/analysis_store.py`
  - `src/jra_srb/app.py`
  - `tests/test_analysis_store.py`
  - `tests/test_api.py`
  - `docs/jra/05_API仕様.md`
- DB schema、collector、外部provider、予想・評価ロジックは変更不要。

## 6. 読み取り範囲

- 初期バッチ: `pyproject.toml`、`README.md`、`app.py`、`analysis_store.py`、`jra_odds_timeline.py`
- 追加バッチ: `models.py`、関連テスト、既存API仕様、既存`.workstate`
- 追加理由: 応答型、404、結果リーク防止、前機能からの優先順位を確定するため。
- 読まなかった範囲: provider/extractor全体、生成ログ、予想モデル群。保存済み参照APIの仕様化には不要。
