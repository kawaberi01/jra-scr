# API仕様

## ヘルスチェック

### `GET /health`

API プロセスの生存確認です。外部通信は行いません。

### `GET /health/upstream`

JRA upstream への軽量な到達性を確認します。

## 入力正規化

### `GET /normalize`

日本語の開催場名、レース表記、券種名を API 用コードへ変換します。

クエリ:

- `course`: 例 `中山`, `nakayama`
- `race`: 例 `11R`, `第11レース`
- `bet_type`: 例 `3連単`, `trifecta`
- `combination`: 例 `1,2,3`

## 開催・出馬表・オッズ・結果

### `GET /races?date=YYYY-MM-DD&course=optional`

race summary 一覧を取得します。

### `GET /meetings/{date}/{course}`

開催日と開催場から 1R から 12R の一覧を取得します。

### `GET /meetings/{date}/{course}/races/{race_no}/card`

開催日、開催場、レース番号から出馬表を取得します。

### `GET /meetings/{date}/{course}/races/{race_no}/odds`

開催日、開催場、レース番号からオッズを取得します。

クエリ:

- `bet_type`: `win`, `quinella`, `wide`, `exacta`, `trio`, `trifecta`
- `combination`: 任意。例 `1,2,3`
- `refresh`: 任意。`true` の場合は cache を避けます。

### `GET /meetings/{date}/{course}/races/{race_no}/result`

開催日、開催場、レース番号から結果と払戻を取得します。

### `GET /races/{race_id}/card`

`race_id` で出馬表を取得します。

### `GET /races/{race_id}/odds`

`race_id` でオッズを取得します。

クエリ:

- `bet_type`: 単一券種
- `bet_types`: 複数券種。例 `win,trifecta`
- `combination`: 任意
- `refresh`: 任意

### `GET /races/{race_id}/result`

`race_id` で結果と払戻を取得します。

## 南関東公式 API

南関東4競馬場公式サイトから開催一覧、出走表、オッズ、結果を取得します。JRA公式の12桁 `race_id` とは分け、南関東では16桁 `race_id` を使います。

対象場:

- `urawa`
- `funabashi`
- `ohi`
- `kawasaki`

### `GET /nankan/meetings/{date}/{course}`

開催日と開催場からレース一覧を取得します。

クエリ:

- `refresh`: 任意。`true` の場合は cache を避けます。

### `GET /nankan/meetings/{date}/{course}/trend`

開催日と開催場から、南関東公式の当日開催傾向を取得します。予想本体ではなく、枠傾向、脚質傾向、騎手傾向、厩舎傾向などの当日補正用データです。

内部では開催一覧から南関東公式の開催IDを解決し、`race_trend/{meeting_id}.do?open_date={YYYYMMDD}` を取得します。trend ページが未作成または集計前の場合は 404 にせず、`race_count_completed: 0` と空の `summary` を返します。

クエリ:

- `refresh`: 任意。`true` の場合は cache を避けます。

主なレスポンス:

```json
{
  "date": "2026-07-06",
  "course": "kawasaki",
  "meeting_id": "2026210401",
  "open_date": "20260706",
  "updated_at": "2026-07-06T21:24:00+09:00",
  "race_count_completed": 12,
  "summary": {
    "frame": [{ "frame_no": "6", "top3_count": 8 }],
    "running_style": {
      "front_group_top3_count": 27,
      "back_group_top3_count": 9
    },
    "jockey": [{ "name": "笹川翼", "affiliation": "大井", "top3_count": 5 }],
    "trainer": [{ "name": "高月賢一", "affiliation": "川崎", "top3_count": 5 }],
    "sire": [{ "name": "パイロ", "top3_count": 2 }],
    "broodmare_sire": [{ "name": "クロフネ", "top3_count": 4 }],
    "payout": {
      "trifecta_max_payout": 109080,
      "trifecta_max_payout_race_no": 7
    }
  },
  "source": "https://www.nankankeiba.com/race_trend/2026210401.do?open_date=20260706"
}
```

### `GET /nankan/leading/jockeys`

南関東公式のリーディングジョッキー情報を取得します。予想では主材料ではなく、`pattern_kis` / `pattern_kis_cho` の裏取り、短距離戦の騎手補正、接戦時の順位補正に使います。

クエリ:

- `course`: 任意。`urawa`, `funabashi`, `ohi`, `kawasaki`
- `distance`: 任意。例: `1400`
- `track_condition`: 任意。`good`, `slightly_heavy`, `heavy`, `bad`
- `period`: 任意。既定値は `recent_3months`。`recent_1year` または年も指定可能です。
- `sort`: 任意。既定値は `win_rate`。`wins`, `earnings`, `win_rate`, `quinella_rate`
- `refresh`: 任意。`true` の場合は cache を避けます。

ランキング表が見つからない場合は、取得失敗ではなく `items: []` を返します。
条件付きURLが 404/400 などで取得できない場合はベースページへフォールバックし、`fallback: true`、`requested_condition_code`、`effective_condition_code` で要求条件と実取得条件を示します。

### `GET /nankan/meetings/{date}/{course}/races/{race_no}/card`

開催日、開催場、レース番号から出走表を取得します。

### `GET /nankan/meetings/{date}/{course}/races/{race_no}/best-time`

開催日、開催場、レース番号から南関東公式の持ち時計を取得します。

同条件のベース能力比較用です。公式の `best/{race_id}000000.do` を取得し、タイム、順位、場、馬場、距離、同場/同距離フラグを構造化して返します。公式ページ上で source race_id / source date が表示されない場合、`best_time_source_race_id` と `best_time_source_date` は `null` です。

クエリ:

- `refresh`: 任意。`true` の場合は cache を避けます。

### `GET /nankan/meetings/{date}/{course}/races/{race_no}/closing-speed`

開催日、開催場、レース番号から南関東公式の上がり時計を取得します。

終い性能比較用です。公式の `best/{race_id}22{distance}.do` を取得し、3F、順位、馬場、同場/同距離フラグを構造化して返します。`closing_section_distance` は 3F として `600` を返します。公式ページ上で source race_id / source date が表示されない場合、`closing_time_source_race_id` と `closing_time_source_date` は `null` です。

クエリ:

- `refresh`: 任意。`true` の場合は cache を避けます。

### `GET /nankan/meetings/{date}/{course}/races/{race_no}/style-profile`

開催日、開催場、レース番号から南関東公式の近走通過順を使って脚質傾向を推定します。

`best-time` ページから各馬の `uma_info` ID を解決し、各馬ページの近走成績にある `コーナー 通過順` を最大5走取得します。通過順平均を頭数比に正規化し、`front`, `stalker`, `midpack`, `closer` のスコアと `expected_style` を返します。

クエリ:

- `refresh`: 任意。`true` の場合は cache を避けます。

### `GET /nankan/meetings/{date}/{course}/races/{race_no}/odds`

開催日、開催場、レース番号から南関東公式オッズを取得します。

クエリ:

- `bet_type`: 単一券種。`win`, `place`, `quinella`, `wide`, `exacta`, `trio`, `trifecta`
- `bet_types`: 複数券種。例 `win,trifecta`
- `combination`: 任意。例 `5,7,6`
- `refresh`: 任意。`true` の場合は cache を避けます。

### `GET /nankan/meetings/{date}/{course}/races/{race_no}/result`

開催日、開催場、レース番号から南関東公式結果を取得します。開催一覧で16桁 `race_id` を解決してから、単レース結果ページを取得します。

クエリ:

- `refresh`: 任意。`true` の場合は cache を避けます。

### `GET /nankan/races/{race_id}/card`

16桁 `race_id` で出走表を取得します。

### `GET /nankan/races/{race_id}/best-time`

16桁 `race_id` で南関東公式の持ち時計を取得します。

### `GET /nankan/races/{race_id}/closing-speed`

16桁 `race_id` で南関東公式の上がり時計を取得します。

### `GET /nankan/races/{race_id}/style-profile`

16桁 `race_id` で南関東公式の近走通過順を使った脚質傾向推定を取得します。

### `GET /nankan/races/{race_id}/odds`

16桁 `race_id` で南関東公式オッズを取得します。発売前などで公式オッズページが404の場合は `not_found` として返します。

### `GET /nankan/races/{race_id}/result`

16桁 `race_id` で南関東公式結果を取得します。公式結果ページが404の場合は `not_found`、結果表が見つからない場合も `not_found` として返します。払戻表が見つからない場合は `payouts: []` を返します。

## 保存済み結果

### `GET /stored/results/{race_id}`

保存済み結果を `race_id` で取得します。

### `GET /stored/results`

保存済み結果を検索します。

クエリ:

- `from_date`: 任意。検索開始日
- `to_date`: 任意。検索終了日
- `course`: 任意。開催場
- `limit`: 返却件数。1 から 500
- `offset`: スキップ件数。0 以上

レスポンス:

```json
{
  "items": [],
  "total": 0,
  "limit": 100,
  "offset": 0
}
```

## レース検索

### `GET /search/races`

開催日、開催場、キーワードから race_id を探します。保存済み結果は読まず、既存のレース一覧取得 API を検索・ページングします。

クエリ:

- `date`: 必須。開催日。例 `2026-03-22`
- `course`: 任意。開催場コード。例 `nakayama`
- `keyword`: 任意。`race_id`、レース名、開催場、レース番号の部分一致
- `limit`: 返却件数。1 から 100
- `offset`: スキップ件数。0 以上

レスポンス:

```json
{
  "items": [
    {
      "race_id": "202603220611",
      "date": "2026-03-22",
      "course": "nakayama",
      "race_no": 11,
      "race_name": "Chiba Stakes",
      "start_time": "15:45"
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

## 結果収集 Job API

### `POST /jobs/result-collections`

過去結果の収集を非同期 job として開始します。収集には既存の `PastResultCollector` を使い、保存先は JSONL または SQLite です。

Request body:

```json
{
  "from_date": "2026-03-22",
  "to_date": "2026-03-22",
  "courses": ["nakayama"],
  "storage": "jsonl",
  "output": "data/results.jsonl",
  "retries": 1
}
```

- `from_date`: 必須。収集開始日
- `to_date`: 必須。収集終了日
- `courses`: 必須。1 件以上の開催場コード
- `storage`: 任意。`jsonl` または `sqlite`
- `output`: 任意。保存先パス
- `retries`: 任意。0 以上

レスポンスは `202 Accepted` です。

```json
{
  "job_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "queued"
}
```

### `GET /jobs/result-collections`

現在の API プロセスが保持している job 一覧を返します。

```json
{
  "items": [],
  "total": 0
}
```

### `GET /jobs/result-collections/{job_id}`

job の状態を返します。

```json
{
  "job_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "status": "succeeded",
  "from_date": "2026-03-22",
  "to_date": "2026-03-22",
  "courses": ["nakayama"],
  "storage": "jsonl",
  "output": "data/results.jsonl",
  "retries": 1,
  "created_at": "2026-03-22T00:00:00Z",
  "started_at": "2026-03-22T00:00:01Z",
  "finished_at": "2026-03-22T00:00:05Z",
  "message": "collection succeeded",
  "error": null
}
```

job status:

- `queued`
- `running`
- `succeeded`
- `failed`

job の記録は in-memory です。API サーバーを再起動すると job 一覧と状態は消えます。

## 実買い記録 API

### `POST /bet-records`

実際に購入した券を `analysis.sqlite` に保存します。`mode=box` の券は保存時に必ず展開されます。`race_id` は JRA の12桁、または南関東公式の16桁を指定できます。

Request body:

```json
{
  "race_id": "202607051011",
  "prediction_id": "pred_xxx",
  "theory_version": "v86",
  "decision_source": "agent_plus_manual",
  "purchased_at": "2026-07-05T15:40:00+09:00",
  "total_amount": 400,
  "note": "参考判定を見て購入",
  "tickets": [
    {
      "bet_type": "wide",
      "mode": "box",
      "selection": ["2", "4", "10"],
      "amount_per_ticket": 100
    },
    {
      "bet_type": "trio",
      "mode": "normal",
      "selection": ["2", "4", "10"],
      "amount": 100
    }
  ]
}
```

Response:

```json
{
  "bet_record_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "race_id": "202607051011",
  "prediction_id": "pred_xxx",
  "theory_version": "v86",
  "decision_source": "agent_plus_manual",
  "purchased_at": "2026-07-05T15:40:00+09:00",
  "total_amount": 400,
  "note": "参考判定を見て購入",
  "tickets": [
    {
      "bet_type": "wide",
      "selection": "2-4",
      "selection_json": ["2", "4"],
      "amount": 100,
      "is_box_expanded": true
    },
    {
      "bet_type": "wide",
      "selection": "2-10",
      "selection_json": ["2", "10"],
      "amount": 100,
      "is_box_expanded": true
    },
    {
      "bet_type": "wide",
      "selection": "4-10",
      "selection_json": ["4", "10"],
      "amount": 100,
      "is_box_expanded": true
    },
    {
      "bet_type": "trio",
      "selection": "2-4-10",
      "selection_json": ["2", "4", "10"],
      "amount": 100,
      "is_box_expanded": false
    }
  ]
}
```

### `GET /bet-records/{bet_record_id}`

保存済みの実買い記録を返します。`prediction_id` がある場合は、関連する `prediction` と `prediction_tickets` も含みます。

Response:

```json
{
  "bet_record_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "race_id": "202607051011",
  "prediction_id": "pred_xxx",
  "theory_version": "v86",
  "decision_source": "agent_plus_manual",
  "total_amount": 400,
  "tickets": [],
  "prediction": {
    "prediction_id": "pred_xxx",
    "race_id": "202607051011",
    "theory_version": "v86",
    "prediction_json": {}
  },
  "prediction_tickets": [],
  "result": null
}
```

### `GET /bet-records`

保存済みの実買い記録を検索します。

クエリ:

- `from_date`: 対象レースの開催開始日
- `to_date`: 対象レースの開催終了日
- `race_id`: race_id で絞り込み。JRA の12桁、または南関東公式の16桁
- `course`: 開催場コード
- `theory_version`: theory_version で絞り込み
- `decision_source`: `agent`, `manual`, `agent_plus_manual`
- `limit`: 返却件数。1 から 500
- `offset`: スキップ件数。0 以上

### `POST /bet-records/{bet_record_id}/settle`

保存済みの実買い記録を、既存の `payouts` または `netkeiba_payouts` を使って精算します。

Response:

```json
{
  "bet_record_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "race_id": "202607051011",
  "total_bet": 400,
  "total_payout": 0,
  "return_rate": 0.0,
  "hit": false,
  "settled_at": "2026-07-05T16:30:00+09:00",
  "ticket_results": [
    {"bet_type": "wide", "selection": "2-4", "selection_json": ["2", "4"], "amount": 100, "hit": false, "payout": 0},
    {"bet_type": "wide", "selection": "2-10", "selection_json": ["2", "10"], "amount": 100, "hit": false, "payout": 0},
    {"bet_type": "wide", "selection": "4-10", "selection_json": ["4", "10"], "amount": 100, "hit": false, "payout": 0},
    {"bet_type": "trio", "selection": "2-4-10", "selection_json": ["2", "4", "10"], "amount": 100, "hit": false, "payout": 0}
  ]
}
```

## 分析用 SQLite DB

分析用の一次保存は CLI の `collect-analysis` で行います。実買い記録だけは API からも保存できます。

```bash
jra-srb collect-analysis \
  --from-date 2026-03-22 \
  --to-date 2026-03-22 \
  --courses nakayama \
  --db data/analysis.sqlite \
  --include-card \
  --include-odds \
  --include-results \
  --bet-types wide,trio,trifecta
```

主な保存先:

- `races`
- `runners`
- `odds_snapshots`
- `odds_entries`
- `race_results`
- `result_entries`
- `payouts`
- `collection_errors`
- `predictions`
- `prediction_tickets`
- `evaluations`
- `evaluation_ticket_results`
- `theory_versions`
- `bet_records`
- `bet_record_tickets`
- `bet_record_results`

発走前 snapshot は `races`, `runners`, `odds_snapshots`, `odds_entries` から構成し、結果・払戻・評価結果を含めません。Prediction Agent へ渡す入力はこの発走前 snapshot に限定します。

## エラーレスポンス

API エラーは次の形式で返します。

```json
{
  "error": {
    "code": "bad_request",
    "message": "unsupported bet_type=foobar",
    "request_id": "..."
  }
}
```

`request_id` はレスポンスヘッダー `x-request-id` にも入ります。

## 環境変数

| 変数 | 内容 |
| --- | --- |
| `JRA_SRB_RESULTS_STORAGE` | 保存済み結果 API の backend。`jsonl` または `sqlite`。既定値は `jsonl` |
| `JRA_SRB_RESULTS_PATH` | 保存済み結果 API が読む JSONL パス。既定値は `data/results.jsonl` |
| `JRA_SRB_ANALYSIS_DB_PATH` | 分析用 SQLite DB の既定パス。既定値は `data/analysis.sqlite` |
| `JRA_SRB_CACHE_PATH` | 指定時に SQLite 永続 cache を使う |
| `JRA_SRB_UPSTREAM_MAX_CONCURRENCY` | JRA upstream への最大同時 request 数。既定値は `5` |
| `JRA_SRB_UPSTREAM_MIN_INTERVAL_SECONDS` | JRA upstream への request 開始間隔の最小秒数。既定値は `0` |
