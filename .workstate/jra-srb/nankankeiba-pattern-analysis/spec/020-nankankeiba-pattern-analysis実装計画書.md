# nankankeiba-pattern-analysis 実装計画書

## 方針

APIへ直接追加せず、まず provider/extractor/service を実装し、CLIで検証する。データ形状が安定してからAPI endpointを追加する。

## Phase 1: 取得基盤

対象:

- `src/jra_srb/nankankeiba_pattern_provider.py`
- provider単体テスト

作業:

1. `NankankeibaPatternPageContent` を定義する。
2. `BaseNankankeibaPatternProvider` を定義する。
3. `NankankeibaPatternHttpProvider` を実装する。
4. `NankankeibaPatternFixtureProvider` を実装する。
5. Shift_JIS/cp932/utf-8 decodeを実装する。
6. min_interval_seconds、retry、timeoutを既存providerに合わせて実装する。

完了条件:

- fixture providerでHTMLを読める。
- HTTP providerのURL生成が単体で検証できる。

## Phase 2: URL生成とHTML解析

対象:

- `src/jra_srb/nankankeiba_pattern_extractors.py`
- `tests/test_nankankeiba_pattern_extractors.py`

作業:

1. `build_pattern_race_id` を実装する。
2. `build_pattern_url_path` を実装する。
3. `parse_pattern_rate` を実装する。
4. `parse_pattern_category_page` を実装する。
5. `pattern_kis`, `pattern_uma`, `pattern_cho`, `pattern_kis_cho` のfixtureを追加する。
6. 1R 2026年7月6日 川崎 第4回 第1日 のfixtureで解析テストを書く。

完了条件:

- `14.5% (256/1770)` を rate/wins/starts へ変換できる。
- 4カテゴリの出走馬数が一致する。
- 馬番、馬名、騎手、調教師、主要勝率列が取得できる。

## Phase 3: Service

対象:

- `src/jra_srb/nankankeiba_pattern_service.py`
- `tests/test_nankankeiba_pattern_service.py`

作業:

1. `NankankeibaPatternService` を実装する。
2. category/period指定を正規化する。
3. providerからHTMLを取得してextractorへ渡す。
4. cache keyを設計する。
5. 馬番単位のmerged entryを作る。

完了条件:

- `get_pattern_category` で1カテゴリを取得できる。
- `get_pattern_bundle` で4カテゴリを統合できる。
- source URL、fetched_at、cache_hitを保持する。

## Phase 4: CLI

対象:

- `src/jra_srb/cli.py`
- `tests/test_cli.py`

作業:

1. `fetch-nankankeiba-pattern` subcommandを追加する。
2. `--date`, `--course`, `--meeting`, `--day`, `--race`, `--periods`, `--categories`, `--output` を追加する。
3. stdout JSON出力を実装する。
4. output指定時にJSONファイルへ保存する。

完了条件:

- fixture service差し替えまたは関数単体でCLI引数解析をテストできる。
- 実行結果JSONをAI評価の入力として使える。

## Phase 5: API

対象:

- `src/jra_srb/app.py`
- `tests/test_api.py`
- `README.md` または `docs/jra/05_API仕様.md`

作業:

1. `build_nankankeiba_pattern_service` を追加する。
2. `get_nankankeiba_pattern_service` dependencyを追加する。
3. API tag `nankankeiba` を追加する。
4. endpointを追加する。
5. OpenAPI summary/descriptionを追加する。
6. API testを追加する。

完了条件:

- `GET /nankankeiba/pattern/meetings/2026-07-06/kawasaki/races/1?meeting_no=4&meeting_day=1` がJSONを返す。

## Phase 6: AI評価連携

対象外だが後続候補:

- AIに渡すための軽量サマリ生成
- 条件一致列の自動選定
- 母数を考慮した評価用特徴量
- 結果確定後の予想評価

## リスク

- nankankeiba.comのHTML構造変更。
- オッズ・人気が取得タイミングで変わる。
- 期間コードと場コードの未確認範囲。
- 出走取消や少頭数レースのrowspan差分。

## テスト観点

- URL生成
- course/period/category validation
- rate parser
- Shift_JIS fixture decode
- 4カテゴリ解析
- merge処理
- CLI JSON出力
- API dependency override
