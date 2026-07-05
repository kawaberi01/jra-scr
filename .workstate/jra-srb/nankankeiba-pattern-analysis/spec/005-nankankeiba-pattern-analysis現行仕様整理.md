# nankankeiba-pattern-analysis 現行仕様整理

## プロジェクト構成

対象プロジェクトは `jra-srb`。

現行構成:

- FastAPI入口: `src/jra_srb/app.py`
- CLI入口: `src/jra_srb/cli.py`
- モデル: `src/jra_srb/models.py`
- JRA service/provider: `src/jra_srb/service.py`, `src/jra_srb/provider.py`
- netkeiba service/provider/extractor: `src/jra_srb/netkeiba_service.py`, `src/jra_srb/netkeiba_provider.py`, `src/jra_srb/netkeiba_extractors.py`
- NAR netkeiba service/provider/extractor: `src/jra_srb/nar_netkeiba_service.py`, `src/jra_srb/nar_netkeiba_provider.py`, `src/jra_srb/nar_netkeiba_extractors.py`
- API tests: `tests/test_api.py`
- CLI tests: `tests/test_cli.py`

## 既存の実装流儀

既存実装は次の責務分離を採用している。

- provider: upstream HTML/API の取得、retry、decode、fixture読み込み
- extractor: HTMLからドメインデータへの解析
- service: cache、provider呼び出し、extractor呼び出し、モデル生成
- app: FastAPI endpoint と dependency injection
- cli: argparse command と service/collector呼び出し
- tests: fixture provider による外部通信なしの検証

勝ちパターン分析も同じ分離に合わせる。

## 既存APIの追加方針

現行APIは `/netkeiba/...`、`/nar-netkeiba/...` のようにデータ元別のprefixを持つ。

勝ちパターン分析は nankankeiba.com 固有機能なので、API公開時は次のようなprefixが妥当。

```text
/nankankeiba/pattern/...
```

ただし初期実装ではAPI公開より先に service/provider/extractor とCLIを作る。

## 現行テスト方針

既存の外部HTML取得機能は fixture provider を用意し、`tests/fixtures` のHTMLで検証している。

勝ちパターン分析でも以下を追加する。

- `NankankeibaPatternFixtureProvider`
- `tests/fixtures/nankankeiba_pattern_kis_202607062104010101.html`
- `tests/fixtures/nankankeiba_pattern_uma_202607062104010101.html`
- `tests/fixtures/nankankeiba_pattern_cho_202607062104010101.html`
- `tests/fixtures/nankankeiba_pattern_kis_cho_202607062104010101.html`

## 要件との差分

現行コードには nankankeiba.com の勝ちパターン分析取得機能はない。

追加が必要なもの:

- 南関東勝ちパターンURL生成
- nankankeiba.com HTML provider
- Shift_JISを含むdecode
- 勝率文字列 `14.5% (256/1770)` の数値化
- カテゴリ別テーブル解析
- 馬ごとの統合JSONモデル
- CLI入口
- 後続API入口
