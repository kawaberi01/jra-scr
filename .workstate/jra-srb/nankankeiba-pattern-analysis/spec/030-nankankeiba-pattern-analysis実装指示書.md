# nankankeiba-pattern-analysis 実装指示書

## 改修目的

南関東4競馬場サイトの勝ちパターン分析を、AI勝ち馬分析の元データとして取得・構造化できるようにする。

## 変更してよい範囲

- `src/jra_srb/models.py`
- `src/jra_srb/nankankeiba_pattern_provider.py`
- `src/jra_srb/nankankeiba_pattern_extractors.py`
- `src/jra_srb/nankankeiba_pattern_service.py`
- `src/jra_srb/cli.py`
- `src/jra_srb/app.py`
- `tests/test_nankankeiba_pattern_provider.py`
- `tests/test_nankankeiba_pattern_extractors.py`
- `tests/test_nankankeiba_pattern_service.py`
- `tests/test_cli.py`
- `tests/test_api.py`
- `tests/fixtures/nankankeiba_*.html`
- 必要なREADME/docsの最小追記

## 変更してはいけない範囲

- 既存JRA/netkeiba/NAR netkeiba endpointのレスポンス互換性
- 既存CLI commandの引数互換性
- 既存SQLite schemaの破壊的変更
- AI評価・予想ロジック本体

## 実装順序

1. `nankankeiba_pattern_provider.py` を追加する。
2. `nankankeiba_pattern_extractors.py` を追加し、URL生成とrate parserを先にテストする。
3. 公式ページからfixtureを保存し、4カテゴリ解析テストを追加する。
4. `models.py` に必要なPydanticモデルを追加する。
5. `nankankeiba_pattern_service.py` を追加する。
6. CLI `fetch-nankankeiba-pattern` を追加する。
7. CLIでJSON形状を確認する。
8. 必要ならAPI endpointを追加する。

## 最小実装の固定条件

- 最初は川崎 `kawasaki` / `川崎` のみ対応でよい。
- 最初はperiod `01` のみ必須対応でよい。
- URL生成はAIや文字列推測に依存させない。
- HTML取得結果をAIへ直接渡さない。
- 勝率、勝利数、母数は数値として保持する。
- source URLとfetched_atを必ず保持する。

## 推奨ファイル名

```text
src/jra_srb/nankankeiba_pattern_provider.py
src/jra_srb/nankankeiba_pattern_extractors.py
src/jra_srb/nankankeiba_pattern_service.py
tests/test_nankankeiba_pattern_provider.py
tests/test_nankankeiba_pattern_extractors.py
tests/test_nankankeiba_pattern_service.py
```

## CLI仕様

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

`--output` がない場合はstdoutへJSONを出す。

## API仕様

APIはCLI検証後に追加する。

```http
GET /nankankeiba/pattern/meetings/{date}/{course}/races/{race_no}
```

必須query:

- `meeting_no`
- `meeting_day`

任意query:

- `periods`
- `categories`

## テスト観点

- `build_pattern_race_id(date(2026, 7, 6), "kawasaki", 4, 1, 1, "01") == "202607062104010101"`
- `pattern_kis`, `pattern_uma`, `pattern_cho`, `pattern_kis_cho` のURL pathを生成できる。
- `parse_pattern_rate("14.5% (256/1770)")` が `rate=14.5`, `wins=256`, `starts=1770` を返す。
- `parse_pattern_rate("")` や欠損値で例外にしない。
- fixtureから出走馬7頭を取得できる。
- 4カテゴリを馬番で統合できる。
- CLI引数解析で `fetch-nankankeiba-pattern` が選択される。
- API追加時はdependency overrideでfixture serviceを使う。

## 人手確認観点

- 実ページのURLが期待通り開けること。
- 出走馬名、騎手名、調教師名が文字化けしないこと。
- オッズ・人気は取得時刻依存であることがレスポンス上わかること。
- AI評価用JSONにHTML断片が混入しないこと。

## 停止条件

- 川崎以外の場コードが未確認のまま全場対応として実装しようとする場合は停止する。
- HTML構造がfixtureと実ページで大きく違い、出走馬行を安定抽出できない場合は停止する。
- APIレスポンス形状が未確定のまま永続DB保存を始めようとする場合は停止する。

## 実行禁止

- `git reset --hard`
- 既存データベースの破壊的migration
- upstreamへの高頻度アクセス
- 既存endpointのレスポンス変更を伴うリファクタリング

## 実装後の推奨検証

```bash
rtk uv run pytest tests/test_nankankeiba_pattern_provider.py tests/test_nankankeiba_pattern_extractors.py tests/test_nankankeiba_pattern_service.py
rtk uv run pytest tests/test_cli.py tests/test_api.py
```
