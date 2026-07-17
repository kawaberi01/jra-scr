# 010-JRA発走前snapshot・オッズ時系列参照API実装仕様書

## 0. 最初に読む要約

- 対象機能: JRA発走前snapshot・オッズ時系列参照API
- 改修目的: 保存済みSQLiteを読み取り専用APIとして公開する。
- 現行仕様の要点: 発走前snapshotのStoreメソッドはあるがAPIはなく、時系列専用queryもない。
- 実装時の最重要注意点: 結果・払戻・評価の非混入、時間順、同一時点ラベル上書きというDB制約を守る。

## 1. 変更後仕様

### 1.1 API一覧

| Method | Path | 目的 |
| --- | --- | --- |
| GET | `/jra/races/{race_id}/pre-race-snapshot` | 保存済みの発走前レース・出走馬と、選択したオッズsnapshotを取得 |
| GET | `/jra/races/{race_id}/odds-timeline` | 券種ごとの保存済みオッズを時系列で取得 |

両APIは以下を共通契約とする。

- `race_id`は既存`RaceIdPath`を使い、12桁数字以外は422。
- `AnalysisSQLiteStore`のみを参照し、外部サイトへ通信しない。
- `refresh` queryは設けない。
- raceがDBに存在しない場合は`LookupError`経由で404。
- raceが存在し、該当オッズがない場合は200と空配列。
- tagは`jra-analysis`。
- MCP allowlistには追加しない。

### 1.2 発走前snapshot API

```http
GET /jra/races/202607180211/pre-race-snapshot
GET /jra/races/202607180211/pre-race-snapshot?include_odds=true&odds_timing=t_minus_10m
```

Query:

| 名称 | 型 | 既定 | 契約 |
| --- | --- | --- | --- |
| `include_odds` | bool | `true` | falseならオッズをqueryせず`odds=[]` |
| `odds_timing` | string nullable | null | 指定時は完全一致。省略時は券種ごとに`fetched_at`が最新の1 snapshot |

正常応答:

```json
{
  "race": {
    "race_id": "202607180211",
    "race_date": "2026-07-18",
    "course": "kokura",
    "meeting_no": 2,
    "meeting_day": 4,
    "race_no": 11,
    "race_name": "sample",
    "start_time": "15:35",
    "surface": "turf",
    "distance": "1800",
    "source": "jra",
    "fetched_at": "2026-07-18T14:55:00+09:00"
  },
  "runners": [],
  "odds": [],
  "meta": {
    "include_odds": true,
    "requested_odds_timing": null,
    "available_odds_timings": ["t_minus_30m", "t_minus_10m", "t_minus_2m"],
    "missing_components": ["runners"]
  }
}
```

応答規則:

- `runners`は馬番を数値優先で昇順。
- `odds_timing`省略時は各`bet_type`につき最新1件。
- `odds_timing`指定時は該当ラベルの全券種を`bet_type`昇順。
- `available_odds_timings`はraceに保存済みのdistinctラベルを`fetched_at`最小値順で返す。
- `missing_components`:
  - runnerが0件なら`runners`
  - `include_odds=true`かつ選択条件に該当するsnapshotが0件なら`odds`
- `include_odds=false`の場合、`missing_components`へ`odds`を入れない。
- response top-levelに`results`、`payouts`、`evaluations`を定義しない。

### 1.3 オッズ時系列 API

```http
GET /jra/races/202607180211/odds-timeline?bet_type=win
GET /jra/races/202607180211/odds-timeline?bet_type=wide&combination=4,10
```

Query:

| 名称 | 型 | 必須 | 契約 |
| --- | --- | --- | --- |
| `bet_type` | `BetType` | 必須 | `win/place/quinella/wide/exacta/trio/trifecta` |
| `combination` | string nullable | 任意 | カンマ区切り。券種ごとの点数を検証 |

正常応答:

```json
{
  "race_id": "202607180211",
  "bet_type": "win",
  "combination": ["1"],
  "snapshots": [
    {
      "snapshot_id": "202607180211:win:t_minus_30m",
      "race_id": "202607180211",
      "bet_type": "win",
      "odds_timing": "t_minus_30m",
      "fetched_at": "2026-07-18T15:05:02+09:00",
      "source": "jra",
      "entries": [
        {
          "bet_type": "win",
          "combination": ["1"],
          "odds": 3.2,
          "odds_min": null,
          "odds_max": null,
          "popularity": 2
        }
      ]
    }
  ],
  "total": 1
}
```

時系列規則:

- snapshotは`fetched_at ASC, snapshot_id ASC`で返す。
- `total`は返却したsnapshot数であり、entry数ではない。
- `combination`未指定時は各snapshotの全entriesを返す。
- `combination`指定時は各snapshot内の一致entryだけを返す。
- 一致entryがないsnapshotも時系列の欠測を示すため残し、`entries=[]`とする。
- queryの`combination`は`normalization.normalize_combination()`で分割後、既存の券種別選択正規化規則と同じ検証を行う。
- `quinella/wide/trio`は馬番を昇順に正規化し、逆順指定でも一致させる。
- `exacta/trifecta`は順序を保持する。
- `win/place`は1点、`quinella/wide/exacta`は2点、`trio/trifecta`は3点。点数不一致は400 `bad_request`。
- responseのオッズ値はSQLiteの型に合わせて`float | null`、人気は`int | null`とする。
- 公開項目は`combination`のみとし、DB列名`combination_json`は返さない。

## 2. 応答モデル

`src/jra_srb/models.py`へ既存命名に合わせて次のPydantic modelを追加する。

- `StoredPreRace`
- `StoredPreRaceRunner`
- `StoredOddsEntry`
- `StoredOddsSnapshot`
- `StoredPreRaceSnapshotMeta`
- `StoredPreRaceSnapshot`
- `StoredOddsTimeline`

最低限の型:

| Model | 主なフィールド |
| --- | --- |
| `StoredPreRace` | racesテーブルの公開全列。`race_date: date`、`fetched_at: datetime \| None` |
| `StoredPreRaceRunner` | runnersテーブルの公開全列。`card_odds: float \| None`、`card_popularity: int \| None` |
| `StoredOddsEntry` | `bet_type`, `combination: list[str]`, `odds/odds_min/odds_max`, `popularity` |
| `StoredOddsSnapshot` | snapshot metadata、`entries` |
| `StoredPreRaceSnapshotMeta` | query条件、利用可能時点、欠損component |
| `StoredPreRaceSnapshot` | `race`, `runners`, `odds`, `meta` |
| `StoredOddsTimeline` | `race_id`, `bet_type`, `combination`, `snapshots`, `total` |

既存の外部取得用`OddsEntry`はオッズ値がstringであり、保存済みSQLiteの数値型と契約が違うため流用しない。

## 3. Store仕様

### 3.1 `get_pre_race_snapshot`

既存メソッドを後方互換なdefaultで拡張する。

```python
def get_pre_race_snapshot(
    self,
    race_id: str,
    *,
    include_odds: bool = True,
    odds_timing: str | None = None,
) -> StoredPreRaceSnapshot:
```

- race存在確認を最初に行う。
- runner、利用可能時点、選択対象oddsを同一connection内で読む。
- 最新snapshot選択はwindow functionへ依存せず、`order by bet_type, fetched_at desc, snapshot_id desc`の結果からbet_typeごとに先頭を採用してもよい。
- `include_odds=false`では`odds_snapshots/odds_entries`の本体queryを省略する。ただし`available_odds_timings`も空配列とし、追加queryしない。
- 返却時にPydantic modelへ型変換する。

### 3.2 `get_odds_timeline`

新規メソッド:

```python
def get_odds_timeline(
    self,
    race_id: str,
    bet_type: str,
    combination: list[str] | None = None,
) -> StoredOddsTimeline:
```

- race存在確認後、指定券種の全snapshotを`fetched_at ASC, snapshot_id ASC`で取得する。
- combination指定時は既存の`_normalize_selection_items()`と同等の規則で正規化する。
- SQL値は必ずbindする。
- queryの文字列からSQL断片を生成しない。
- snapshotごとのentry順は`popularity IS NULL, popularity, combination`とし、人気なしを末尾にする。
- combination指定時もsnapshot自体は削除しない。

## 4. API配置

`src/jra_srb/app.py`の保存済みJRA予想・評価参照API付近へ2 routeを追加する。

- `response_model`を必ず指定する。
- `get_analysis_store()`を依存注入する。
- `race_id`は`RaceIdPath`。
- `bet_type`は既存`BetType`。
- combinationは`normalize_combination()`でlist化し、Storeへ渡す。
- 新しい例外handlerは追加しない。既存`LookupError`と`BadRequestError`を使う。

## 5. エラー・ログ・設定

- 404: raceが存在しない。
- 400: combinationの点数不一致または券種との不整合。
- 422: race_id形式、bet_type enum、bool queryのFastAPI validation失敗。
- 500: DB破損等の予期しない例外。握りつぶさない。
- 読み取り成功ごとの新規ログは追加しない。
- 設定は既存`JRA_SRB_ANALYSIS_DB_PATH`をそのまま使う。
- 新しい機密情報、環境変数、外部通信はない。

## 6. 根拠

| 判断 | 根拠ファイル | 行 | 備考 |
| --- | --- | ---: | --- |
| 発走前系と結果系を分離 | `src/jra_srb/analysis_store.py` | 61-144 | テーブルが分離 |
| 時点ラベル単位でupsert | `src/jra_srb/analysis_store.py` | 612-656 | 同一ラベルは明細置換 |
| 既存snapshot Storeを拡張 | `src/jra_srb/analysis_store.py` | 1943-1982 | 現行の直接参照口 |
| 404はLookupErrorを利用 | `src/jra_srb/app.py` | 420-422 | 共通error shape |
| 12桁race_id validation | `src/jra_srb/app.py` | 87 | `RaceIdPath` |
| 保存済みAPIはStore DI | `src/jra_srb/app.py` | 1501-1612 | 予想・評価参照API |
| 結果リーク禁止 | `tests/test_analysis_store.py` | 150-157 | 既存test |
| 離散収集時点 | `src/jra_srb/jra_odds_timeline.py` | 16-25, 135-156 | `t_minus_Nm`保存 |

## 7. テスト観点

### Store

- race/runnerと3時点のwin/wideを保存し、最新snapshotを券種ごとに1件返す。
- `odds_timing=t_minus_10m`で対象時点だけ返す。
- `include_odds=false`でオッズquery結果、available timings、odds欠損表示が空になる。
- timelineが`fetched_at`昇順。
- wideの`4,10`と`10,4`が同じentryへ一致する。
- exactaの順序違いは別組み合わせ。
- combination点数不一致は400相当の`BadRequestError`。
- raceあり・oddsなしは空配列。
- raceなしは`LookupError`。
- result/payoutを同じraceへ保存してもresponseに含まれない。

### API

- 2 endpointの200、404、400、422。
- `JRA_SRB_ANALYSIS_DB_PATH`で指定した一時SQLiteを読む。
- `response_model`により`combination_json`が露出しない。
- OpenAPIにsummary、query説明、response schemaが出る。
- MCP tool一覧に2 endpointが追加されない。

### 回帰

- 既存`get_pre_race_snapshot(race_id)`呼び出しが引数追加なしで動く。
- 既存予想・評価参照APIのrouteとmodelを変更しない。
- collectorと`write_odds()`を変更しない。

## 8. 対象外

- DB schema変更、migration、index追加。
- 任意時刻のas-of snapshot。
- races/runnersの履歴化。
- 同一`odds_timing`の複数世代保存。
- 外部JRAサイトからの再取得。
- SSE/WebSocketによるリアルタイム配信。
- MCP公開。
- Nankan、netkeiba保存オッズの共通化。
- pagination、CSV/Parquet export。

## 9. 要確認事項

- 仕様確定を妨げる保留はない。
- 将来、完全なas-of再現が必要になった場合は、`races/runners`の履歴化とodds snapshotのappend-only化を別仕様として作る。
