# 南関API DB優先・TTL更新・取得時保存 改修依頼プロンプト

南関競馬APIについて、外部サイトへ毎回取得しに行くのではなく、DBに保存済みのデータを優先し、未保存または古い場合のみ外部取得する方式へ改修してください。

## 背景

現在、南関の各種APIは外部取得できる状態ですが、予想や検証で同じデータを何度も使います。
毎回外部取得すると以下の問題があります。

- 外部サイトへのアクセスが増える
- 同じデータを再取得してしまう
- 予想時点のオッズや馬場など、あとで検証したい情報が残りにくい
- API取得時点のデータを履歴として活用しにくい

そのため、API取得時にDBを優先し、必要な場合だけ外部取得する構成にしてください。

## 目的

各APIの取得戦略を以下に統一します。

1. DBに保存済みデータがあるか確認する
2. 保存済みで、TTL内ならDBのデータを返す
3. 未保存なら外部取得する
4. 保存済みでもTTL切れなら外部再取得する
5. 外部取得に成功したらDBへ保存する
6. 取得したデータをAPIレスポンスとして返す

データを予想で使うかどうかは別レイヤーで判断します。
この改修では「取得・蓄積」の責務に集中してください。

## 対象データ

少なくとも以下を対象にしてください。

- `card`
- `odds`
- `result`
- `trend`
- `best-time`
- `closing-speed`
- `style-profile`
- `pattern`
- `leading-jockey`

既存DBに保存領域があるものは既存テーブルを使ってください。
保存領域がないものは、既存の `analysis.sqlite` の設計に合わせて追加してください。

## 基本方針

### DB優先

APIリクエスト時は、まずDBを確認してください。

例:

```http
GET /nankan/meetings/2026-07-07/kawasaki/races/11/odds?bet_type=win
```

この場合、まずDBの `odds_snapshots` / `odds_entries` を確認します。

- 保存済みかつTTL内: DBの内容を返す
- 未保存: 外部取得して保存
- 保存済みだがTTL切れ: 外部再取得して保存

### refresh=true

既存の `refresh=true` は強制外部取得として扱ってください。

```http
GET /nankan/meetings/2026-07-07/kawasaki/races/11/odds?bet_type=win&refresh=true
```

この場合はDBに保存済みであっても外部取得し、成功したらDBを更新またはスナップショット追加してください。

### source metadata

レスポンスには可能であれば以下を含めてください。

```json
{
  "cache_policy": "db_first_ttl",
  "data_source": "db",
  "db_hit": true,
  "ttl_expired": false,
  "saved": false,
  "fetched_at": "2026-07-07T12:00:00+09:00"
}
```

外部取得した場合:

```json
{
  "cache_policy": "db_first_ttl",
  "data_source": "external",
  "db_hit": false,
  "ttl_expired": true,
  "saved": true,
  "fetched_at": "2026-07-07T12:05:00+09:00"
}
```

既存レスポンス形式を大きく壊さないよう、必要なら `meta` フィールドにまとめてください。

## TTL方針

データ種別ごとにTTLを分けてください。
全部同じTTLにはしないでください。

推奨値:

| データ | TTL目安 | 理由 |
|---|---:|---|
| odds | 1〜5分 | 開催中に大きく変わる |
| trend | 3〜10分 | レース進行で変わる |
| card | 10〜30分 | 馬体重、取消、馬場が変わる可能性がある |
| leading-jockey | 6〜24時間 | 短時間では大きく変わりにくい |
| best-time | 24時間以上 | レース直前に頻繁には変わらない |
| closing-speed | 24時間以上 | レース直前に頻繁には変わらない |
| style-profile | 24時間以上 | 近走ベースで頻繁には変わらない |
| pattern | 24時間以上 | 勝ちパターン分析は頻繁には変わらない |
| result | 確定後は長期 | 結果は基本固定。ただし速報直後は再確認余地あり |

TTL値は設定化してください。
環境変数または設定オブジェクトで変更できる形が望ましいです。

例:

- `JRA_SRB_NANKAN_ODDS_TTL_SECONDS`
- `JRA_SRB_NANKAN_TREND_TTL_SECONDS`
- `JRA_SRB_NANKAN_CARD_TTL_SECONDS`
- `JRA_SRB_NANKAN_LEADING_JOCKEY_TTL_SECONDS`
- `JRA_SRB_NANKAN_STATIC_MATERIAL_TTL_SECONDS`

## オッズの扱い

オッズは履歴価値が高いため、単なる上書きではなくスナップショット保存を基本にしてください。

保存先の既存候補:

- `odds_snapshots`
- `odds_entries`

要件:

- `race_id`
- `bet_type`
- `odds_timing`
- `fetched_at`
- `entries`

を保持してください。

同一 `race_id + bet_type + odds_timing` で既に保存済みの場合の扱いは、以下のどちらかで統一してください。

- 同一タイミングは上書き
- 取得時刻ごとに別スナップショットとして追加

予想時点オッズを後で検証したいので、可能なら「取得時刻ごとに別スナップショット」を優先してください。
ただし既存スキーマと衝突する場合は、既存仕様を壊さない形で設計してください。

## resultの扱い

結果は基本的に確定後は固定ですが、取得直後は速報状態の可能性があります。

方針:

- 未保存なら外部取得して保存
- 保存済みなら原則DBを返す
- `refresh=true` の場合は再取得
- 必要なら `result_status` または `is_final` のような状態を持てる設計にする

## leading-jockeyの扱い

`GET /nankan/leading/jockeys` もDB優先対象にしてください。

キー:

- `course`
- `distance`
- `track_condition`
- `period`
- `sort`
- `requested_condition_code`
- `effective_condition_code`

`fallback: true` のレスポンスも保存対象にしてよいですが、保存時に `fallback` を保持してください。
予想側で信用度を下げる判断に使います。

## patternの扱い

勝ちパターン分析は予想根拠として重要なので、取得成功時に保存してください。

キー:

- `race_id`
- `date`
- `course`
- `race_no`
- `meeting_no`
- `meeting_day`
- `periods`
- `categories`

同じ条件で保存済みかつTTL内ならDBを返してください。

## APIレスポンスの互換性

既存クライアントを壊さないことを優先してください。

推奨:

- 既存のトップレベル項目は維持する
- DB/TTL情報は `meta` または既存の `cache_hit` 周辺に追加する

例:

```json
{
  "race_id": "2026070721040211",
  "bet_type": "win",
  "entries": [],
  "meta": {
    "cache_policy": "db_first_ttl",
    "data_source": "db",
    "db_hit": true,
    "ttl_expired": false,
    "saved": false,
    "fetched_at": "2026-07-07T12:00:00+09:00"
  }
}
```

## 実装上の注意

- `has_odds_snapshot` は保存済み確認専用なので、保存処理は `write_odds` 側で行う
- API取得系のサービスにDB依存を直接混ぜすぎない
- 可能なら `repository` または `cache service` 的な層を作り、DB優先ロジックを集約する
- 外部取得失敗時にDBの古いデータがある場合は、古いデータを返せるか検討する
- その場合は `stale: true` を明示する

## 外部取得失敗時の挙動

推奨:

1. TTL切れで外部取得を試す
2. 外部取得に失敗
3. DBに古いデータがあれば、それを返す
4. レスポンスに `stale: true` と `refresh_error` を含める

例:

```json
{
  "meta": {
    "data_source": "db",
    "db_hit": true,
    "ttl_expired": true,
    "stale": true,
    "refresh_error": "upstream timeout"
  }
}
```

DBにもデータがない場合は、従来どおりエラーにしてください。

## テスト観点

最低限、以下をテストしてください。

1. 未保存時に外部取得し、DBへ保存される
2. TTL内なら外部取得せずDBを返す
3. TTL切れなら外部再取得し、DBへ保存される
4. `refresh=true` ならTTL内でも外部取得する
5. 外部取得失敗時、古いDBデータがあれば `stale: true` で返す
6. 外部取得失敗時、DBデータもなければエラーにする
7. `odds` が `odds_snapshots` / `odds_entries` に保存される
8. `leading-jockey` の `fallback` 情報が保存・返却される
9. 既存APIレスポンスの主要項目が壊れていない

## 完了条件

- 南関APIの主要データ取得が `DB優先 -> TTL判定 -> 外部取得 -> 保存` の流れになっている
- `refresh=true` で強制更新できる
- オッズ取得時にDBへスナップショット保存される
- 古いデータと新しいデータの判定が `fetched_at` とTTLで行われる
- 予想ロジックは「取得・蓄積」と「使うかどうか」を分離したまま扱える
