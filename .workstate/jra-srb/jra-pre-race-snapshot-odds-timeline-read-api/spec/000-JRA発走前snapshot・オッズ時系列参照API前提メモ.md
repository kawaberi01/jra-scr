# 000-JRA発走前snapshot・オッズ時系列参照API前提メモ

## 0. 最初に読む要約

- 対象機能名: JRA発走前snapshot・オッズ時系列参照API
- 改修目的: `analysis.sqlite` を直接開かず、保存済みの発走前情報と離散時点のオッズ推移をHTTP APIで参照できるようにする。
- 現行仕様の要点: `AnalysisSQLiteStore.get_pre_race_snapshot()` は存在するがHTTP APIはなく、オッズは `(race_id, bet_type, odds_timing)` ごとに上書き保存される。
- 実装時に最も注意すべき点: 結果・払戻・評価をレスポンスへ混入させない。現行DBから任意時刻の出馬表過去版は再現できない。
- reference_status: `unavailable`
- 実コード優先で採用した判断: Windows環境で指定reference rootを参照できなかったため、現行コード、既存docs、既存`.workstate`を正とした。
- spec_root: `.workstate/jra-srb/jra-pre-race-snapshot-odds-timeline-read-api/spec/`
- progress_root: `.workstate/jra-srb/jra-pre-race-snapshot-odds-timeline-read-api/progress/`
- 実装skillへの主入力: `030-JRA発走前snapshot・オッズ時系列参照API実装指示書.md`、`020-JRA発走前snapshot・オッズ時系列参照API実装計画書.md`
- ビルド・テスト実行: 分析スキルの制約により今回は実行せず、人間または実装工程へ引き継ぐ。

## 1. 対象

- 対象root: `D:\develop\jra-scr`
- 対象プロジェクト: `jra-srb`
- 関連API: 新規の保存済みJRAデータ参照GET API 2本
- 関連Store: `AnalysisSQLiteStore`
- 関連DB: 既定 `data/db/analysis.sqlite`

## 2. ユーザー要件

- 「JRA発走前snapshot・オッズ時系列参照API」を仕様化する。
- 今回はコード実装、DB migration、テスト実行、アプリ起動を行わない。

## 3. 入力情報

- reference routing:
  - project候補はワークスペース名、`pyproject.toml`、`src/jra_srb`から`jra-srb`に確定。
  - skill指定のreference root `/home/masaruishikawa/.../references/` はWindows環境に存在しない。
  - よって `reference_status: unavailable` とし、実コードへフォールバックした。
- 参照した主要コード:
  - `src/jra_srb/analysis_store.py`
  - `src/jra_srb/app.py`
  - `src/jra_srb/models.py`
  - `src/jra_srb/jra_odds_timeline.py`
  - `tests/test_analysis_store.py`
  - `tests/test_jra_odds_timeline.py`
- 参照した既存資料:
  - `docs/14_自己学習エージェント仕様メモ.md`
  - `docs/jra/05_API仕様.md`
  - `.workstate/jra-srb/analysis-sqlite-local-db/spec/`
  - `.workstate/jra-srb/jra-prediction-evaluation-read-api/spec/`

## 4. 成果物

- `005-JRA発走前snapshot・オッズ時系列参照API現行仕様整理.md`
- `010-JRA発走前snapshot・オッズ時系列参照API実装仕様書.md`
- `020-JRA発走前snapshot・オッズ時系列参照API実装計画書.md`
- `030-JRA発走前snapshot・オッズ時系列参照API実装指示書.md`
- `progress/` 配下の継続用記録

## 5. 前提上の注意

- 現行の`races`と`runners`は履歴テーブルではなく最新値のupsertである。
- 現行の`odds_snapshots`は時点ラベル単位の履歴であり、同じ時点ラベルを再保存すると明細を置換する。
- 「時系列」は保存済み`odds_timing`の離散系列を意味し、任意時刻の連続履歴を意味しない。
- 対象ソースには既存の未コミット差分があるため、実装時は限定diffで競合を確認する。
