# 010-jra-prediction-materials-api 実装仕様書

## 0. 最初に読む要約

- 対象機能: JRA当日予想材料API
- 改修目的: 有料データや事前一括バックフィルなしで、対象レース当日の公開情報を予想エージェントへ一括提供する。
- 現行仕様の要点: JRA公式card/odds/resultはあるが、分析値とbundleはない。
- 実装時の最重要注意点: `lite`の母集団、取得元、取得時刻、欠損理由を必ず返し、南関公式の全履歴分析と同じ精度を装わない。

## 1. 変更後仕様

### 1.1 API一覧

```http
GET /jra/meetings/{date_}/{course}/races/{race_no}/odds-summary
GET /jra/meetings/{date_}/{course}/races/{race_no}/trend-context
GET /jra/meetings/{date_}/{course}/races/{race_no}/public-analysis
GET /jra/meetings/{date_}/{course}/races/{race_no}/best-time-lite
GET /jra/meetings/{date_}/{course}/races/{race_no}/closing-speed-lite
GET /jra/meetings/{date_}/{course}/races/{race_no}/style-profile-lite
GET /jra/meetings/{date_}/{course}/races/{race_no}/prediction-bundle
```

`public-analysis`、3つのlite API、`prediction-bundle` は次を必須queryとする。

- `meeting_no`: JRA開催回。1以上。
- `meeting_day`: 開催日次。1以上。

共通任意query:

- `refresh=false`
- `sources=netkeiba,keibalab,umanity`
- `bet_types=win,wide,quinella`

`sources` は許可リスト内だけを受け付け、重複を除去する。空指定は外部ソースを取得しない。

### 1.2 ソース別レースキー

既存のcourseコード表を正として、専用resolverで次を生成する。

```text
jra_internal_race_id = YYYYMMDD + course_code(2) + race_no(2)
netkeiba_race_id     = YYYY + course_code(2) + meeting_no(2) + meeting_day(2) + race_no(2)
keibalab_race_code   = YYYYMMDD + course_code(2) + race_no(2)
umanity_race_code    = YYYYMMDD + course_code(2) + meeting_no(2) + meeting_day(2) + race_no(2)
```

範囲外のmeeting/race値は422とする。生成したキーはresponse `meta.source_keys` に返して照合可能にする。

### 1.3 公開ソース取得制約

- 1回のbundle生成につき、各第三者ソースは最大1 HTTP GETとする。
- 馬ごとのプロフィールページ巡回は行わない。
- 匿名GETで表示されるHTMLまたは同一ページが匿名で利用する公開レスポンスだけを対象にする。
- ログイン、会員Cookie、課金、CAPTCHA回避、非公開API推測は行わない。
- Providerごとに最小アクセス間隔とTTLキャッシュを持つ。
- 既定値はtimeout 10秒、retry 1回、min interval 10秒/ドメイン、public analysis TTL 6時間とする。
- `refresh=true` でも最小アクセス間隔は無効化しない。
- User-Agent、timeout、source URL、取得時刻を記録し、レスポンス本文全体はログへ出さない。

設定候補:

```text
JRA_SRB_PUBLIC_ANALYSIS_TIMEOUT_SECONDS=10
JRA_SRB_PUBLIC_ANALYSIS_RETRIES=1
JRA_SRB_PUBLIC_ANALYSIS_MIN_INTERVAL_SECONDS=10
JRA_SRB_PUBLIC_ANALYSIS_TTL_SECONDS=21600
JRA_SRB_PUBLIC_ANALYSIS_SOURCES=netkeiba,keibalab,umanity
```

### 1.4 public-analysis契約

レスポンスはソースごとの成功・欠損を保持する。

```json
{
  "race_id": "202607110305",
  "date": "2026-07-11",
  "course": "fukushima",
  "race_no": 5,
  "meeting_no": 2,
  "meeting_day": 5,
  "sources": {
    "netkeiba": {"status": "available", "course_analysis": {}},
    "keibalab": {"status": "partial", "recent_form": []},
    "umanity": {"status": "unavailable", "reason": "field_not_public"}
  },
  "fetched_at": "...",
  "cache_hit": false,
  "meta": {"source_keys": {}}
}
```

component status:

- `available`: 必須フィールドを取得できた。
- `partial`: ページ取得には成功したが、一部フィールドがない。
- `unavailable`: 匿名公開範囲に対象値がない。
- `upstream_error`: timeout、HTTPエラー、HTML構造不一致。
- `disabled`: sources指定または設定で無効。

第三者値はJRA公式のcard/odds/weather/track_conditionを上書きしない。

### 1.5 recent form共通モデル

公開馬柱から取得できた範囲を次に正規化する。

```text
horse_no, horse_name
source_date, source_course, source_race_no
surface, distance, track_condition
finish_rank, field_size, finish_time, final_3f
corner_positions
weight_carried, jockey, popularity, win_odds
source, source_url
```

- 欠損は`null`または空配列にする。
- 対象レースの結果行は含めない。
- 1頭最大5走とし、ページに見える範囲を超えて追加取得しない。
- 同一馬の照合は第一に馬番、第二に正規化馬名を使う。曖昧な行は採用せずwarningへ入れる。

### 1.6 best-time-lite

- `recent_form` のうち対象と同じsurfaceの走破時計を候補にする。
- 優先順位は「同場かつ同距離」「同距離」「距離差が最小」の順。
- 時計文字列を秒へ変換できない行は除外する。
- 馬場差・クラス差・ペース差の補正はv1では行わない。
- 各馬について採用時計、取得元レース条件、対象との一致フラグ、候補走数を返す。
- 出走馬間rankは同一比較区分の有効時計だけで付ける。
- `scope="visible_recent_races"` と `max_recent_races=5` を必ず返す。

### 1.7 closing-speed-lite

- `recent_form.final_3f` の最小値を基本値とする。
- 同surface・同距離を優先し、なければ同surfaceの公開近走へフォールバックする。
- 採用元条件、候補走数、フォールバック有無を返す。
- 上がり順位がページにある場合は別フィールドに保持し、時計と混同しない。
- `final_3f` が公開されていない馬は`unavailable`とする。

### 1.8 style-profile-lite

- 最大5走の`corner_positions`を使う。
- 各走の最終コーナー位置をfield_sizeで割って位置率を求める。
- field_sizeがない場合は、その走をスコア計算から除外する。
- 南関既存ルールに合わせ、位置率25%以内=`front`、45%以内=`stalker`、70%以内=`midpack`、それ以外=`closer`とする。
- 各カテゴリ件数/有効走数をscoreとし、最大カテゴリを`expected_style`にする。
- 最大scoreが同率なら`expected_style=null`、`ambiguous=true`とする。
- 公開レースページに通過順がない場合、追加の馬ページ取得はせずcomponentを`unavailable`にする。

### 1.9 trend-context

- 対象レースより前の同日・同場レースだけを利用する。
- `1..race_no-1` の結果をJRA公式APIから取得し、未確定・404はskipする。
- 既存TTLを利用し、同一レースを繰り返し取得しない。
- v1で集計する候補は、完了レース数、3着内の枠・騎手・調教師、払戻傾向とする。結果ページで取得できない項目はstatus付き欠損にする。
- 通過順がない場合、当日脚質傾向は`unavailable`にする。
- `required_max_completed = race_no - 1` とし、対象以後の結果が混入したsnapshotを採用しない。
- 1Rは空summary、`usable=true`で返す。

### 1.10 odds-summary

- 既存JRA oddsサービスを再利用する。
- 既定券種は`win,wide,quinella`。
- `trio`等は`bet_types`で明示された場合だけ取得する。
- 同じbundle内でcard・oddsページを重複取得しない。

### 1.11 prediction-bundle

cardを先に取得し、その後に独立componentを並列実行する。

```text
card (必須)
  -> odds_summary
  -> trend_context
  -> public_analysis
       -> recent_form
       -> best_time_lite
       -> closing_speed_lite
       -> style_profile_lite
```

`public_analysis`は1回だけ取得し、3つのlite計算で共有する。bundle内で同一URLを再取得しない。

主要レスポンス:

```text
race_id, date, course, race_no, meeting_no, meeting_day
card
odds_summary
trend_context
public_analysis
best_time_lite
closing_speed_lite
style_profile_lite
data_quality
fetched_at, cache_hit, meta
```

`data_quality.components`にはstatus、source、sample_size、reason、warningsを持たせる。

### 1.12 正常系・異常系

- card取得成功: optional componentに失敗があっても200で返す。
- cardのレースが存在しない: 404。
- meeting_no/day、sources、bet_types不正: 422または既存BadRequest契約に合わせた400。
- 全外部ソース失敗: card/odds/trendを含むpartial bundleを200で返す。
- parser構造不一致: source componentを`upstream_error`とし、request ID付きwarning logを残す。
- 未公表オッズ: componentを`unavailable`とし、bundle全体を失敗させない。

## 2. 既存構成における担当

- 入口: `src/jra_srb/app.py`
- オーケストレーション: 新規`src/jra_srb/jra_prediction_service.py`
- 公開ソース取得: 新規`src/jra_srb/jra_public_analysis_provider.py`
- HTML抽出: 新規`src/jra_srb/jra_public_analysis_extractors.py`
- lite計算: 新規`src/jra_srb/jra_prediction_materials.py`
- source key解決: `jra_prediction_materials.py`内の小さな純粋関数。独立抽象化は不要。
- モデル: `src/jra_srb/models.py`
- JRA公式データ: 既存`JraService`を注入して再利用する。

## 3. 実装配置

### 追加ファイル

- `src/jra_srb/jra_public_analysis_provider.py`
- `src/jra_srb/jra_public_analysis_extractors.py`
- `src/jra_srb/jra_prediction_materials.py`
- `src/jra_srb/jra_prediction_service.py`
- `tests/test_jra_public_analysis_extractors.py`
- `tests/test_jra_prediction_materials.py`
- `tests/test_jra_prediction_service.py`
- 対象3ページの最小HTML fixture

### 修正ファイル

- `src/jra_srb/models.py`
- `src/jra_srb/app.py`
- `tests/test_api.py`
- `docs/jra/05_API仕様.md`
- `docs/jra/04_利用ガイド.md`

### v1では修正しない

- `analysis_store.py`のDBスキーマ
- 既存JRA card/odds/resultのレスポンス契約
- 南関APIと南関モデル
- 既存netkeiba result/oddsの挙動

## 4. 根拠

| 判断 | 根拠ファイル | 行 | 備考 |
| --- | --- | --- | --- |
| JRA card/odds/resultを再利用 | `src/jra_srb/service.py` | 87, 107, 174 | 既存TTLと例外処理を維持する。 |
| API追加先はapp.py | `src/jra_srb/app.py` | 473以降 | 開催座標版の既存パターン。 |
| bundle専用serviceを置く | `src/jra_srb/nankan_prediction_service.py` | 43-222 | card先行、共有context、並列componentの類似実装。 |
| JRA公式結果だけでは上がり・通過順不足 | `src/jra_srb/models.py` | 105-110 | ResultEntryが最小項目のみ。 |
| SQLite公式結果にも詳細不足 | `src/jra_srb/analysis_store.py` | 119-126 | v1でDB依存の精密指標は作れない。 |
| fixture-first | `tests/test_api.py` | 74以降 | live取得なしでAPI契約を確認している。 |

## 5. エラー・ログ・設定

- 既存エラーmiddlewareとrequest IDを使用する。
- URLには認証情報を含めない。
- source URL、status、elapsed_ms、cache_hit、抽出件数だけを構造化ログへ出す。
- HTML本文、Cookie、第三者記事本文はログへ出さない。
- source単位でfeature flagを設定可能にする。

## 6. Referenceとの差分

対象に一致するproject referenceはなかったため、reference由来の設計判断は採用していない。

## 7. テスト観点

### 自動テスト

- 3サイト各fixtureから匿名公開値だけを抽出できる。
- 有料・会員専用表示は抽出しない。
- source keyがサンプルURLと一致する。
- 1頭最大5走、対象レース結果除外、馬番/馬名照合。
- best/closing/styleの計算、欠損、同率、フォールバック。
- trendが対象レースより後の結果を参照しない。
- bundleがpublic analysisを1回だけ取得して共有する。
- optional source timeoutでも200 partial response。
- card 404、query validation、OpenAPI掲載。

### 手動確認

- Swaggerで対象当日レースを1件だけ確認する。
- sourceごとの実リクエスト数が1以下であることをログで確認する。
- ブラウザ表示と抽出値を少数項目で照合する。

### 回帰確認

- 既存JRA card/odds/result。
- netkeiba result/odds。
- 南関 prediction bundle。

## 8. 対象外

- 全履歴を使った精密best time、統計的タイム指数、馬場差補正。
- 騎手・調教師の長期条件別成績の自前再集計。
- 機械学習、買い目生成、予想本文生成。
- 外部公開値のSQLite永続化と過去バックテスト。

## 9. 停止条件・要確認事項

- 対象ページが匿名HTMLに値を含まず、ログインまたは保護回避が必要なら、そのsource実装を停止する。
- 安定したrace keyを生成できないsourceは、推測変換を追加せず`disabled`とする。
- fixtureで通過順を確認できなければstyle-profile-liteを空実装で誤魔化さず`unavailable`契約にする。
- 公開利用条件に抵触する疑いが新たに確認されたsourceは、既定無効にしてユーザー判断へ戻す。

