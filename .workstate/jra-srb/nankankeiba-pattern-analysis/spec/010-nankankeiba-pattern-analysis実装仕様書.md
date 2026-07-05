# nankankeiba-pattern-analysis 実装仕様書

## 対象範囲

南関東4競馬場サイトの勝ちパターン分析を取得し、AI評価用の構造化データへ変換する。

初期実装の対象:

- URL生成
- HTML取得
- 4カテゴリのテーブル解析
- 期間 `01` の取得
- CLIでJSON出力
- fixtureベースの単体テスト

後続実装の対象:

- 期間 `02`, `03` の同時取得
- FastAPI endpoint
- AI評価用スコアリング前処理
- SQLite保存

## 追加モジュール

```text
src/jra_srb/nankankeiba_pattern_provider.py
src/jra_srb/nankankeiba_pattern_extractors.py
src/jra_srb/nankankeiba_pattern_service.py
```

必要に応じて `models.py` にPydanticモデルを追加する。

## モデル案

```python
class NankankeibaPatternRate(BaseModel):
    label: str
    rate: float | None = None
    wins: int | None = None
    starts: int | None = None
    raw: str | None = None

class NankankeibaPatternEntry(BaseModel):
    frame_no: str | None = None
    horse_no: str
    horse_name: str
    jockey: str | None = None
    trainer: str | None = None
    odds: str | None = None
    popularity: str | None = None
    rates: dict[str, NankankeibaPatternRate] = Field(default_factory=dict)

class NankankeibaPatternCategoryPage(BaseModel):
    category: str
    period: str
    race_pattern_id: str
    race_date: date | None = None
    course: str | None = None
    race_no: int | None = None
    race_name: str | None = None
    distance: int | None = None
    entries: list[NankankeibaPatternEntry] = Field(default_factory=list)
    fetched_at: datetime
    source: str
    cache_hit: bool = False

class NankankeibaPatternBundle(BaseModel):
    race_pattern_base_id: str
    periods: list[str]
    categories: dict[str, NankankeibaPatternCategoryPage]
    entries: list[NankankeibaPatternMergedEntry] = Field(default_factory=list)
    fetched_at: datetime
```

## URL生成仕様

関数案:

```python
build_pattern_race_id(
    race_date: date,
    course: str,
    meeting_no: int,
    meeting_day: int,
    race_no: int,
    period: str = "01",
) -> str
```

`course` は当面以下を受ける。

- `kawasaki`
- `川崎`

初期実装では川崎コード `21` のみ必須。ほかの場コードは実ページ確認後に追加する。未対応courseは `BadRequestError`。

カテゴリ:

```python
PATTERN_CATEGORIES = {
    "jockey": "pattern_kis",
    "horse": "pattern_uma",
    "trainer": "pattern_cho",
    "jockey_trainer": "pattern_kis_cho",
}
```

期間:

```python
PATTERN_PERIODS = {
    "lifetime": "01",
    "last_year": "02",
    "last_3_months": "03",
}
```

## Provider仕様

`BaseNankankeibaPatternProvider`:

- `fetch_pattern(category_path: str, race_pattern_id: str) -> NankankeibaPatternPageContent`

`NankankeibaPatternHttpProvider`:

- base URL: `https://www.nankankeiba.com`
- User-Agentを設定
- `shift_jis`, `cp932`, `utf-8` の順でdecode
- retry、timeout、min_interval_secondsを持つ

`NankankeibaPatternFixtureProvider`:

- `tests/fixtures/nankankeiba_{category_path}_{race_pattern_id}.html` を読む

## Extractor仕様

抽出対象:

- レース概要
- 出走馬基本情報
- 騎手、調教師、オッズ、人気
- 勝率列
- 勝率、勝利数、母数

勝率解析:

```text
14.5% (256/1770)
0.0% (0/47)
```

を次へ変換する。

```json
{"rate": 14.5, "wins": 256, "starts": 1770, "raw": "14.5% (256/1770)"}
```

列キーはAI評価で使いやすい英語キーへ正規化する。

共通:

- `lifetime_rate`
- `urawa`
- `funabashi`
- `oi`
- `kawasaki`
- `short_distance`
- `middle_distance`
- `long_distance`
- `popularity_1`
- `popularity_2`
- `popularity_3`
- `popularity_4_or_less`

出走馬のみ:

- `jockey_current`
- `track_good`
- `track_slightly_heavy`
- `track_heavy`
- `track_bad`
- `season_jan_mar`
- `season_apr_jun`
- `season_jul_sep`
- `season_oct_dec`
- `frame_1_2`
- `frame_3_4`
- `frame_5_6`
- `frame_7_8`

## Service仕様

`NankankeibaPatternService`:

- `get_pattern_category(...)`
- `get_pattern_bundle(...)`

`get_pattern_bundle` はカテゴリ×期間を取得し、馬番をキーに統合する。

初期デフォルト:

- categories: all
- periods: `["01"]`

後続デフォルト候補:

- AI評価用途では `["01", "02", "03"]`

## CLI仕様

コマンド案:

```bash
jra-srb fetch-nankankeiba-pattern \
  --date 2026-07-06 \
  --course kawasaki \
  --meeting 4 \
  --day 1 \
  --race 1 \
  --periods lifetime \
  --output data/nankankeiba_pattern_20260706_kawasaki_1r.json
```

`--output` 未指定時はstdoutへJSON出力。

## API仕様案

CLIでデータ形状が固まった後に追加する。

```http
GET /nankankeiba/pattern/meetings/{date}/{course}/races/{race_no}
```

query:

- `meeting_no`
- `meeting_day`
- `periods=lifetime,last_year,last_3_months`
- `categories=jockey,horse,trainer,jockey_trainer`

## エラー仕様

- 未対応course: 400
- period不正: 400
- category不正: 400
- upstream 404: 502 または既存の upstream error handling に合わせる
- テーブルが見つからない: 404相当の `LookupError`
- 一部カテゴリ失敗: 初期実装では失敗扱い。後続でpartial responseを検討する。
