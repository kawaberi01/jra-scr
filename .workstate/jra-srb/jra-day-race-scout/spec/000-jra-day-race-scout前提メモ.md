# 000-jra-day-race-scout前提メモ

## 1. 対象

- 対象 root: `D:\develop\jra-scr`
- 対象機能: JRA当日1R前の全レース横断スカウト
- 改修目的: 当日の全レースを同一時点で簡易評価し、発走前に既存 `jra-race-predictor` で詳細予想すべき候補レースを最大5件に絞る。
- 関連 API / バッチ: 開催一覧、JRA prediction bundle、model comparison、betting decision、analysis SQLite、新規日次スカウト API
- 連携スキル: 新規 `jra-day-race-scout`、既存 `jra-race-predictor`

## 2. 入力情報

- ユーザー要件: 1R前に当日全レースをざっくり予想し、勝負レースの目星をつける別スキルを用意する。
- reference_status: project reference は使用せず、現行コードと既存 `.workstate` 仕様を根拠とした。
- 読み込んだ reference: なし
- 参照した既存資料:
  - `.workstate/jra-srb/jra-prediction-materials-api/spec/005-jra-prediction-materials-api現行仕様整理.md`
  - `.workstate/jra-srb/jra-win-ev-decision/spec/010-jra-win-ev-decision実装仕様書.md`
  - `C:\Users\main\skills\jra-race-predictor\SKILL.md`
- 参照した主要コード:
  - `src/jra_srb/app.py`
  - `src/jra_srb/service.py`
  - `src/jra_srb/models.py`
  - `src/jra_srb/jra_prediction_service.py`
  - `src/jra_srb/jra_prediction_engine.py`
  - `src/jra_srb/jra_betting_decision.py`
  - `src/jra_srb/analysis_store.py`
  - `scripts/jra_live_prediction_day.py`

## 3. 作成する成果物

- `005-jra-day-race-scout現行仕様整理.md`
- `010-jra-day-race-scout実装仕様書.md`
- `020-jra-day-race-scout実装計画書.md`
- `030-jra-day-race-scout実装指示書.md`

## 4. 注意点

- 早朝オッズは投票量が少ないため、朝時点の妙味は暂定値とし、購入推奨にしない。
- 日次スカウトはレース候補の選定だけを行い、馬の買い目を生成しない。
- 現行 `MeetingSnapshot` にはJRAの `meeting_no` / `meeting_day` がない。日付だけで実行するために自動解決を先行実装する。
- `scripts/jra_live_prediction_day.py` の `MEETING_META` 固定値は流用しない。
- 結果が判明した後の情報を朝のスナップショットに混入させない。

