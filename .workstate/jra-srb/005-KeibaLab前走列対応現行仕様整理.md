# 005-KeibaLab前走列対応現行仕様整理

## 1. 解析の入口
- `JraPredictionService` は KeibaLab の馬柱 HTML を取得し、`parse_keibalab_umabashira` へ渡す。
- 解析結果の `JraPublicRunnerAnalysis.recent_races` は、予想束の `best_time_lite`、`closing_speed_lite`、`style_profile_lite` の入力になる。
- 公開材料モデルも同じ lite 指標を順位根拠として利用する。

## 2. 現行の馬番と前走の対応方法
- `parse_keibalab_umabashira` は `tr.umaban i` から馬番、`a.bamei` から馬名を取得し、順序で `JraPublicRunnerAnalysis` を作る。
- 各 `tr.zensou*` 行について、現行実装は `table.zensouTable` を持つ `td` だけを `cells` に残す。
- 残った `cells` と全出走馬を `zip(runners, cells)` して前走を追加する。

## 3. 確認済みの不具合
- KeibaLab の前走行では、初出走馬の列は `table.zensouTable` を持たない空欄セルとして存在する。
- 現行実装はその空欄セルをフィルタで除外するため、列数が出走馬数より少なくなる。
- その後の `zip` は詰められたセルを先頭の馬から再割当てするため、空欄より後の前走情報が別馬へずれる。
- 2026-07-12 福島3Rでは14番スティールシップが「初出走」なのに、現行 API は過去5走を返した。

## 4. 影響範囲
- 直接影響: `JraPublicRunnerAnalysis.recent_races`。
- 派生影響: 持ち時計、上がり、脚質の lite 指標と、公開材料モデルの順位根拠。
- 非直接影響: 履歴モデルの学習済み成果物そのものは変更しない。ただし API が返す比較・買い目に公開材料由来の誤情報が混ざるため、修正後に当該 API の表示を確認する必要がある。

## 5. 既存テスト
- `tests/test_jra_prediction_materials.py` には最小 HTML の可視項目テストのみがある。
- 初出走の空欄列、複数の前走行、列順（16番から1番のような降順）を検証する fixture はない。
