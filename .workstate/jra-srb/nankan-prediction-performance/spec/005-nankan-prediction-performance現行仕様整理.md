# 005-nankan-prediction-performance現行仕様整理

## プロジェクト構成

対象プロジェクトは `jra-srb`。

現行構成:

- FastAPI 入口: `src/jra_srb/app.py`
- CLI 入口: `src/jra_srb/cli.py`
- モデル: `src/jra_srb/models.py`
- 南関 service/provider/extractor: `src/jra_srb/nankan_service.py`, `src/jra_srb/nankan_provider.py`, `src/jra_srb/nankan_extractors.py`
- nankankeiba pattern service/provider/extractor: `src/jra_srb/nankankeiba_pattern_service.py`, `src/jra_srb/nankankeiba_pattern_provider.py`, `src/jra_srb/nankankeiba_pattern_extractors.py`
- API tests: `tests/test_api.py`, `tests/test_nankan_api.py`
- CLI tests: `tests/test_cli.py`

## 既存の責務分離

既存実装は次の責務分離を採用している。

- `app.py`:
  - FastAPI endpoint
  - dependency injection
  - query/path 受け取り
- `nankan_service.py`:
  - meeting 解決
  - cache 利用
  - provider 呼び出し
  - extractor 呼び出し
  - Pydantic model 組み立て
- `nankankeiba_pattern_service.py`:
  - pattern の category / bundle 組み立て
  - cache 利用
- `cli.py`:
  - argparse subcommand 定義
  - service または local API の薄い呼び出し

今回の高速化も、この既存分離に沿って追加するのが前提になる。

## 現行 API / CLI の事実

### 1. 個別取得 API 前提

`app.py` には南関向けに次の個別取得 endpoint がある。

- `GET /nankan/meetings/{date_}/{course}/races/{race_no}/trend-context`
- `GET /nankan/meetings/{date_}/{course}/races/{race_no}/card`
- `GET /nankan/meetings/{date_}/{course}/races/{race_no}/best-time`
- `GET /nankan/meetings/{date_}/{course}/races/{race_no}/closing-speed`
- `GET /nankan/meetings/{date_}/{course}/races/{race_no}/style-profile`
- `GET /nankan/meetings/{date_}/{course}/races/{race_no}/odds`
- `GET /nankan/meetings/{date_}/{course}/races/{race_no}/result`

また、pattern は別 prefix で公開済み。

- `GET /nankankeiba/pattern/meetings/{date_}/{course}/races/{race_no}`

このため、予想材料は現在も複数 endpoint を順番に叩く前提で構成されている。

### 2. CLI は汎用呼び出し中心

`cli.py` には次がある。

- `call-local-api`
  - 任意 path + query をそのまま local API に GET する
- `fetch-nankankeiba-pattern`
  - pattern service を直接呼ぶ専用 CLI

一方で、複数 path をまとめる CLI や、予想一式を 1 回で返す CLI はまだない。

### 3. `trend-context` は既存ロジックを持つ

`NankanService.get_meeting_trend_context()` は meeting trend を取得し、`required_max_completed = race_no - 1` を使って usable 判定を返す。

- post-race snapshot と判断した場合は `usable=false`
- その場合は空の summary を返す

したがって bundle でも `trend-context` の既存意味を変えず、そのまま内包するのが自然。

### 4. `best-time` / `closing-speed` は内部で card 依存

`NankanService.get_race_best_time()` と `get_race_closing_speed()` はどちらも内部で `get_race_card()` を呼び、距離やコース情報を補助入力として使っている。

つまり bundle 側で card を先に取得しても、既存 service をそのまま呼ぶと重複 card 参照が起こり得る。

### 5. `odds` は券種ごと逐次取得

`NankanService.get_race_odds()` は:

- 指定券種を `_requested_bet_types()` で決定する
- 未指定時は `SUPPORTED_NANKAN_BET_TYPES` 全券種を対象にする
- 券種ごとに `provider.fetch_odds(race_id, current)` を順次実行する
- `win` だけは `_complete_win_odds()` で card を見て欠番補完する

このため:

- 全券種既定取得は最も重い
- `win` / `wide` / `quinella` など必要券種だけに絞れば、それだけで upstream 呼び出し数と JSON 量を減らせる

### 6. race_no ベース API は meeting 解決を伴う

`get_race_*_by_number()` 系は内部で `get_meeting()` から race_id を解決する。

よって bundle 実装時に race_no ベース API を何度も呼ぶより、

- 1 回だけ meeting から race_id を引く
- 以降は race_id ベース service を使う

方が無駄が少ない。

### 7. pattern は既に bundle 単位 service を持つ

`NankankeibaPatternService.get_pattern_bundle()` は、

- `date`
- `course`
- `meeting_no`
- `meeting_day`
- `race_no`
- `periods`
- `categories`

を受け取り、4 category をまとめた `NankankeibaPatternBundle` を返す。

したがって今回の prediction bundle は pattern 自体を再実装せず、既存 service を呼ぶだけでよい。

### 8. leading jockey は race 直接 endpoint ではない

`GET /nankan/leading/jockeys` は query ベースで、

- `course`
- `distance`
- `track_condition`
- `period`
- `sort`

を取る。

予想 bundle に含める場合は、card から取れるコース・距離・馬場状態を使ってパラメータを導出する必要がある。

## 現行テスト方針

- API は `TestClient(app)` と dependency override で検証する
- CLI は parser 単体と `httpx.MockTransport` で検証する
- pattern は fixture provider で外部通信なしに検証する

今回も同じ方針に合わせるのが自然。

## 要件との差分

現行コードにないもの:

- `GET /nankan/meetings/{date_}/{course}/races/{race_no}/odds-summary`
- `GET /nankan/meetings/{date_}/{course}/races/{race_no}/prediction-bundle`
- `fetch-nankan-prediction-bundle` CLI
- 複数予想材料をサーバー側で並列に束ねるオーケストレーション
- 予想用軽量 odds の既定券種セット

既存コードで流用できるもの:

- `RaceOdds`
- `RaceCard`
- `NankanMeetingTrendContext`
- `NankanRaceBestTime`
- `NankanRaceClosingSpeed`
- `NankanLeadingJockeyPage`
- `NankankeibaPatternBundle`
- `call_local_api()`

## 今回の仕様化で採る前提

- まず `odds-summary` を追加し、全券種既定取得を避ける
- 次に `prediction-bundle` を追加し、1 回の local API 呼び出しで予想材料を返す
- bundle は既存 response model を内包する新 model とし、既存 endpoint の契約は変えない
- CLI は generic batch ではなく、まず bundle 専用の薄い入口を追加する
