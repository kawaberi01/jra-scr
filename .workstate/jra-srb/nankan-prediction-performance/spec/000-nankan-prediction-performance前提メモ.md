# 000-nankan-prediction-performance前提メモ

## 1. 対象
- 対象 root: `D:\develop\jra-scr`
- 対象機能: 南関予想向け取得高速化
- 改修目的: 予想1ターンあたりの体感待ち時間を下げるため、`odds-summary` API、`prediction-bundle` API、bundle 専用 CLI を追加する
- 関連画面 / API / バッチ:
  - `GET /nankan/meetings/{date_}/{course}/races/{race_no}/odds`
  - `GET /nankan/meetings/{date_}/{course}/races/{race_no}/trend-context`
  - `GET /nankan/meetings/{date_}/{course}/races/{race_no}/card`
  - `GET /nankan/meetings/{date_}/{course}/races/{race_no}/best-time`
  - `GET /nankan/meetings/{date_}/{course}/races/{race_no}/closing-speed`
  - `GET /nankankeiba/pattern/meetings/{date_}/{course}/races/{race_no}`
  - `GET /nankan/leading/jockeys`
  - `jra-srb call-local-api`
  - `jra-srb fetch-nankankeiba-pattern`

## 2. 入力情報
- ユーザー要件:
  - `notes/2026-07-08_prediction_performance_handoff.md` を優先づけて仕様化する
- reference_status:
  - handoff note と実コードを突合済み
  - reference 由来の改善案は採用するが、既存構成・責務は実コードを正とする
- 読み込んだ reference:
  - `notes/2026-07-08_prediction_performance_handoff.md`
- 参照した既存資料:
  - `docs/jra/05_API仕様.md`
  - `docs/jra/25_nankan_trend_asof_race_fix_plan.md`
- 参照した主要コード:
  - `src/jra_srb/app.py`
  - `src/jra_srb/cli.py`
  - `src/jra_srb/models.py`
  - `src/jra_srb/nankan_service.py`
  - `src/jra_srb/nankankeiba_pattern_service.py`
  - `tests/test_cli.py`

## 3. 作成する成果物
- `005-nankan-prediction-performance現行仕様整理.md`
- `010-nankan-prediction-performance実装仕様書.md`
- `020-nankan-prediction-performance実装計画書.md`
- `030-nankan-prediction-performance実装指示書.md`

## 4. 注意点
- 既存 `call-local-api` は残す
- 既存 `/nankan/...` と `/nankankeiba/pattern/...` の契約は壊さず、追加 API と追加 CLI で入れる
- 待ち時間削減を最優先とし、横断リファクタや理想設計への置き換えは対象外にする
- pattern 取得は既存 `NankankeibaPatternService` 契約に合わせ、`meeting_no` / `meeting_day` を bundle 側でも明示入力に残す前提で扱う
