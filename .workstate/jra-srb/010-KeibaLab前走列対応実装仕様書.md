# 010-KeibaLab前走列対応実装仕様書

## 0. 最初に読む要約
- 対象機能: KeibaLab 馬柱の `recent_races` 解析。
- 改修目的: 空欄の前走セルを含む行でも、HTML の列位置と馬番・馬名の対応を維持する。
- 現行仕様の要点: 前走テーブルを持つセルだけを抽出して `zip` している。
- 実装時の最重要注意点: 空欄セルを除外してはならない。空欄は初出走等の正常な「履歴なし」である。

## 1. 変更後仕様

### 入力
- KeibaLab 馬柱の `table.megamoriTable`。
- 出走馬の表示順と同じ列順で並ぶ `tr.zensou*` の直接子 `td`。

### 出力
- 各 `JraPublicRunnerAnalysis.recent_races` には、その馬と同一列の `table.zensouTable` から解析した前走だけを追加する。
- 前走セルが空欄の馬は `recent_races` を追加せず、空配列のままとする。

### 正常系
1. 全馬に前走テーブルがある場合、従来どおり各列を対応させる。
2. 初出走馬など一部の列が空欄の場合、空欄を含めた列位置で対応させる。空欄列の馬には前走を追加しない。
3. 複数の `tr.zensou*` 行がある場合、それぞれで同じ列位置を用い、最大5走の既存制限を維持する。
4. 馬柱が降順の馬番列であっても、HTML 内の馬番・馬名・前走列が同じ順で処理されることを保証する。

### 異常系
- 前走行の直接子 `td` 数が出走馬数と一致しない場合、列を詰めて再対応してはならない。
- 解析可能な共通列だけを安全に処理し、対応できない馬へ前走を推測・補完しない。
- HTML 構造不明により直接子 `td` の列対応が確定できない場合は、当該行の前走解析をスキップする。既存の公開材料全体を例外で失敗させない。

### 副作用
- 修正後は初出走馬の lite 指標が `unavailable` またはサンプル数0となる。
- 初出走馬へ誤付与されていた時計・上がり・脚質の順位根拠が消える。

## 2. 既存構成における担当
- 入口: `JraPredictionService` が既存のまま `parse_keibalab_umabashira` を呼ぶ。
- 処理配置: `src/jra_srb/jra_public_analysis_extractors.py` の KeibaLab 前走行解析。
- データモデル: 既存の `JraPublicRunnerAnalysis` と `JraRecentRace` を流用する。
- 派生処理: `src/jra_srb/jra_prediction_materials.py` は正しく紐付いた `recent_races` をそのまま利用する。
- 新規抽象化: 不要。列対応を局所的に修正する。

## 3. 実装配置
- 追加ファイル: `tests/fixtures/keibalab_umabashira_initial_runner.html`
- 修正ファイル:
  - `src/jra_srb/jra_public_analysis_extractors.py`
  - `tests/test_jra_prediction_materials.py`
- 既存流用: `_parse_keibalab_recent_race`、`JraPublicRunnerAnalysis`、`JraRecentRace`。

## 4. 根拠

| 判断 | 根拠ファイル | 行 | 備考 |
| --- | --- | --- | --- |
| 前走セルが詰められる | `src/jra_srb/jra_public_analysis_extractors.py` | 62-67 | `table.zensouTable` があるセルだけを抽出して `zip` している。 |
| 誤った前走は lite 指標へ波及する | `src/jra_srb/jra_prediction_materials.py` | 55-136 | `recent_races` を時計・上がり・脚質計算に使用する。 |
| 公開材料順位へ波及する | `src/jra_srb/jra_prediction_engine.py` | 14-44 | lite 指標順位をスコア根拠へ加算する。 |
| 初出走と前走ありの混在を実データで確認 | KeibaLab 2026-07-12 福島3R 馬柱 | - | 14番スティールシップは「初出走」。 |

## 5. エラー / ログ / 設定
- エラー処理: 既存どおり、個別前走の解析不能はその馬の履歴なしとして扱う。
- ログ: 今回の局所修正では新規ログを必須にしない。
- 設定: 追加不要。
- 機密情報: 追加なし。

## 6. Reference との差分

| Reference 仮説 | 実コードの事実 | 採用判断 |
| --- | --- | --- |
| 初出走なら前走情報を持たない | 空欄セルの除外により別馬の前走が付与される | 空欄を保持する列対応へ修正する。 |

## 7. テスト観点
- 自動テスト:
  - 前走あり・初出走・前走ありの3頭が同一行に混在しても、初出走馬の `recent_races` が空であること。
  - 初出走馬の後ろの馬へ、その馬自身の前走日・競馬場・着順が紐付くこと。
  - 複数前走行で、各馬の履歴件数と順序が保たれること。
  - 既存の最小HTMLテストが継続して通ること。
- 手動確認:
  - 実取得した2026-07-12福島3R相当HTMLで、14番が前走なしとして返ること。
  - prediction-bundle の14番の時計・上がり・脚質liteが誤った実績を表示しないこと。
- 回帰確認: `rtk uv run pytest -q tests/test_jra_prediction_materials.py tests/test_jra_prediction_engine.py`。

## 8. 対象外
- KeibaLab以外の解析器変更。
- 既存分析SQLiteの過去データ修復。
- 履歴モデルの再学習・係数変更。
- 自動買い目ロジックの変更。

## 9. 要確認事項
- 実装時に実HTMLで前走行の直接子 `td` に馬列以外の固定列が含まれる場合、その列数・位置をfixtureで明示し、馬番列とのオフセットを固定すること。
