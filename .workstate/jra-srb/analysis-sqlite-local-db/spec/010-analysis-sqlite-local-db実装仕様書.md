# 010-analysis-sqlite-local-db 実装仕様書

## 0. 最初に読む要約

- 分析用の一次保存先は SQLite。
- CSV は一次保存ではなく export として後続対応。
- 最重要要件は結果リーク防止。
- 発走前 snapshot と結果 / 払戻 / 評価をスキーマ上で分離する。
- オッズ中心分析のため、`odds_snapshots` と `odds_entries` を正規化保存する。

## 1. 変更後仕様

### 1.1 新規DB

既定パス:

```text
data/analysis.sqlite
```

環境変数:

```text
JRA_SRB_ANALYSIS_DB_PATH
```

### 1.2 テーブル

#### collection_runs

収集単位を保存する。

| column | type | 備考 |
| --- | --- | --- |
| run_id | text primary key | UUID |
| from_date | text | YYYY-MM-DD |
| to_date | text | YYYY-MM-DD |
| courses_json | text | JSON |
| include_card | integer | 0/1 |
| include_odds | integer | 0/1 |
| include_results | integer | 0/1 |
| odds_timing | text | `final_or_near_final` など |
| status | text | running/succeeded/failed |
| created_at | text | ISO datetime |
| finished_at | text nullable | ISO datetime |

#### races

レースの基本情報。

| column | type |
| --- | --- |
| race_id | text primary key |
| race_date | text |
| course | text |
| race_no | integer |
| race_name | text |
| start_time | text |
| surface | text |
| distance | text |
| source | text |
| fetched_at | text |

#### runners

発走前の出走馬情報。

| column | type |
| --- | --- |
| race_id | text |
| horse_no | text |
| frame_no | text |
| horse_name | text |
| sex_age | text |
| weight_carried | text |
| jockey | text |
| trainer | text |
| card_odds | real nullable |
| card_popularity | integer nullable |

primary key:

```text
(race_id, horse_no)
```

#### odds_snapshots

オッズ取得単位。

| column | type |
| --- | --- |
| snapshot_id | text primary key |
| race_id | text |
| bet_type | text |
| odds_timing | text |
| fetched_at | text |
| source | text |

unique:

```text
(race_id, bet_type, odds_timing)
```

#### odds_entries

オッズ明細。自己改良エージェントではここが中核。

| column | type |
| --- | --- |
| snapshot_id | text |
| race_id | text |
| bet_type | text |
| combination | text |
| combination_json | text |
| odds | real nullable |
| odds_min | real nullable |
| odds_max | real nullable |
| popularity | integer nullable |

index:

```text
(race_id, bet_type)
(bet_type, odds)
(bet_type, popularity)
```

#### race_results

結果ヘッダ。

| column | type |
| --- | --- |
| race_id | text primary key |
| race_name | text |
| fetched_at | text |
| source | text |

#### result_entries

着順。

| column | type |
| --- | --- |
| race_id | text |
| rank | integer nullable |
| horse_no | text |
| horse_name | text |
| jockey | text |
| finish_time | text |

primary key:

```text
(race_id, rank, horse_no)
```

#### payouts

払戻。

| column | type |
| --- | --- |
| race_id | text |
| bet_type | text |
| combination | text |
| payout | integer nullable |
| popularity | integer nullable |

index:

```text
(race_id, bet_type)
```

#### collection_errors

レース単位の収集失敗理由。

| column | type |
| --- | --- |
| error_id | text primary key |
| run_id | text |
| race_id | text nullable |
| race_date | text |
| course | text |
| race_no | integer nullable |
| stage | text | meeting/card/odds/result |
| error_type | text |
| error_message | text |
| created_at | text |

#### theory_versions

理論ファイルの履歴。

| column | type |
| --- | --- |
| theory_version | text primary key |
| parent_version | text nullable |
| status | text | active/candidate/promoted/rejected |
| theory_yaml | text |
| notes | text nullable |
| created_at | text |
| promoted_at | text nullable |

#### predictions

Prediction Agent の出力。

| column | type |
| --- | --- |
| prediction_id | text primary key |
| race_id | text |
| theory_version | text |
| mode | text |
| budget | integer |
| pre_race_snapshot_json | text |
| prediction_json | text |
| created_at | text |

#### prediction_tickets

評価を deterministic code で行うための買い目正規化。

| column | type |
| --- | --- |
| ticket_id | text primary key |
| prediction_id | text |
| race_id | text |
| bucket | text |
| bet_type | text |
| selection | text |
| selection_json | text |
| amount | integer |
| reason | text nullable |

#### evaluations

評価結果。

| column | type |
| --- | --- |
| evaluation_id | text primary key |
| prediction_id | text |
| race_id | text |
| theory_version | text |
| total_bet | integer |
| total_payout | integer |
| return_rate | real |
| hit | integer |
| gami | integer |
| axis_in_top3 | integer nullable |
| middle_hole_in_top3 | integer nullable |
| firework_hit | integer nullable |
| max_odds_selected | real nullable |
| evaluation_json | text |
| created_at | text |

#### evaluation_ticket_results

買い目単位の評価結果。

| column | type |
| --- | --- |
| ticket_result_id | text primary key |
| evaluation_id | text |
| ticket_id | text |
| bucket | text |
| bet_type | text |
| selection | text |
| amount | integer |
| hit | integer |
| payout | integer |

## 2. API / CLI

### 2.1 CLI

追加候補:

```bash
jra-srb collect-analysis --from-date 2026-03-22 --to-date 2026-03-22 --courses nakayama --db data/analysis.sqlite --include-odds --include-card --include-results
```

最初の実装では CLI 優先。API Job は後続でよい。

### 2.2 MCP / API 用の読み出し

将来 endpoint:

- `GET /analysis/races`
- `GET /analysis/races/{race_id}/pre-race-snapshot`
- `GET /analysis/races/{race_id}/result`
- `GET /analysis/races/{race_id}/payouts`
- `POST /analysis/predictions`
- `POST /analysis/evaluations`
- `GET /analysis/backtests/summary`

## 3. 結果リーク防止

`pre-race-snapshot` には以下を含める。

- race metadata
- runners
- odds snapshots / odds entries

`pre-race-snapshot` には以下を含めない。

- result_entries
- payouts
- evaluations
- prediction outcome

## 4. 対象外

- CSV / Parquet export
- 自己改良エージェント本体
- LLM prediction 実行
- deterministic evaluator 実装
- API Job 化
- SQLite 以外のDB
