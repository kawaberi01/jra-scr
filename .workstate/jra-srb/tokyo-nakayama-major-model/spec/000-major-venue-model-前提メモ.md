# 000-major-venue-model 前提メモ

## 0. 要約

- 対象機能名: 2026年秋 東京・中山主要場モデル
- 改修目的: V90と分離した正式順位、頭・軸・相手候補、実オッズ時だけの買い目判断を、時系列検証可能な形で提供する。
- 現行仕様の要点: 東京・中山は `v89` にルーティングされるが `not_final` / `shadow_only` である。
- 実装時に最も注意すべき点: 既知期間を最終holdoutに再利用せず、対象レース日以後の情報を特徴量へ入れない。
- reference_status: `unavailable`（同梱skillのLinux reference rootはWindows環境に存在しない）
- 実コード優先で採用した判断: `src/jra_srb/jra_v_theory.py` とSQLite・実行結果を正本にする。
- spec_root: `.workstate/jra-srb/tokyo-nakayama-major-model/spec/`
- progress_root: `.workstate/jra-srb/tokyo-nakayama-major-model/progress/`
- 実装 skill への主入力: `030-major-venue-model-実装指示書.md`, `020-major-venue-model-実装計画書.md`
- ビルド・テスト実行: 分析フェーズ後、ユーザー指定どおり実装skillで実行する。

## 1. 対象

- 対象 root: `D:\develop\jra-scr`
- 対象開催: 東京 (`05`)・中山 (`06`)。秋開催を主対象とする。
- 分離対象: 芝/ダート、距離、頭数、レース番号、クラス。新馬・障害は一般戦と混ぜない。
- 非対象: 夏開催V90の仕様変更、中京・京都・阪神の正式採否、実投票。

## 2. 入力情報

- 指定資料: `v89_main_venue_decision.md`, `v89_revalidation_protocol.md`, `v89_revalidation_status.md`, `goal_progress_snapshot.md`
- 指定コード: `src/jra_srb/jra_v_theory.py`, `evaluate_v1_validation.py`
- データ正本: `data/db/analysis.sqlite`
- Git開始点: `bdb79af`、既存ログ差分・未追跡ログは対象外。

## 3. 既知汚染境界（初期値）

- 2025-01-05..2025-09-30: train / walk-forwardで参照済み。
- 2025-10-01..2025-12-31: validationで参照済み。
- 2026-01-01..2026-06-28: v89 holdoutとして参照済み。
- 2024-12-28: 補完パイロットで参照済み。
- 2024年のその他期間および2026-06-29以後: 成果物横断監査が完了するまでholdout候補にしない。

## 4. 注意点

- 最終holdoutを見る前に候補、閾値、採否基準、必要標本数を固定する。
- 最終holdoutが30買い目未満なら正式採用せず、2026年秋シャドーモデルとする。
- ROI単独で採用しない。最大払戻除外、上位3払戻除外、軸/相手3着内率、的中率、買い目数、対象率、場別を必須とする。

