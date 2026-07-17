# 030-JRA出馬表as-of履歴実装指示書

## 1. 対象概要

- 対象機能: JRA-NEXT-003 出馬表のas-of履歴化
- 改修目的: 保存済み発走前情報を観測時点で再現する。
- 変更してよい範囲:
  - `src/jra_srb/models.py`
  - `src/jra_srb/extractors.py`
  - `src/jra_srb/service.py`
  - `src/jra_srb/analysis_store.py`
  - `src/jra_srb/jra_odds_timeline.py`
  - `src/jra_srb/app.py`
  - 関連pytest、API文書、当Featureと共通backlogのprogress
- 変更してはいけない範囲:
  - 結果・払戻・評価の意味
  - MCP allowlist、認証、CORS
  - JRA予想ロジック、購入判断
  - 無関係なログ、一時ファイル、横断リファクタ

## 2. 実装順序

1. modelへadditive fieldを追加する。
2. JRA extractorでrunner集合品質と明示取消を生成する。
3. serviceへcardのrefresh制御を追加する。
4. Store schema、migration、append保存、取消導出を実装する。
5. Store/APIへ`as_of`を追加し、cardとoddsへ同じ境界を適用する。
6. 定刻collectorでcard世代を取得する。
7. extractor、Store、API、collectorテストと文書を更新する。
8. pytest、ruff、compile、diff checkを実行しprogressを更新する。

## 3. 実装ルール

- 履歴IDは既存odds snapshotと同様にUUIDを使う。
- card snapshot保存と最新値同期は1transactionで行う。
- `complete`判定はrunner候補行、変換数、馬番必須、馬番一意性で決める。
- 不完全世代は保存してもas-of候補にせず、取消導出へ使わない。
- `result_page`は発走前履歴tableへ保存しない。
- 取消導出時は直前の完全pre-race世代payloadをコピーする。
- `as_of`比較は`julianday()`を使い、同一時刻はsnapshot IDで決定する。
- 新しい性能indexを追加しない。
- 履歴のない旧DBは`as_of`省略時だけ最新値へfallbackする。
- 公開responseから結果、払戻、評価を返さない。

## 4. テスト必須項目

| 順序 | 対象 | 完了条件 |
| --- | --- | --- |
| 1 | extractor | 通常、明示取消、不完全cardを判別 |
| 2 | Store schema | 旧DB行を失わずcolumn/table追加 |
| 3 | Store履歴 | 複数世代、騎手・馬体重更新、取消導出、再出現 |
| 4 | Store品質 | 不完全/result pageをas-of候補から除外 |
| 5 | Store as-of | cardとoddsが境界以前、timezone offsetも正しい |
| 6 | API | 200、404、timezoneなし422、OpenAPI field |
| 7 | collector | refresh card、skip、live request件数 |
| 8 | 回帰 | 既存pytestとruffが成功 |

## 5. 停止条件

- 既存modelとDB schemaが本指示と矛盾し、additive変更で解消できない場合。
- cardの完全性を候補行数と変換数から判定できない実装差異が見つかった場合。
- 既存の結果リーク防止を破らないと実装できない場合。

## 6. 確認コマンド

```powershell
rtk uv run pytest -q tests/test_extractors.py tests/test_analysis_store.py tests/test_api.py tests/test_jra_odds_timeline.py
rtk uv run pytest -q
rtk uv run ruff check .
rtk uv run python -m compileall -q src tests
rtk git diff --check
```

## 7. 禁止事項

- 過去の最新値から複数世代を捏造しない。
- 不完全cardの欠落を取消にしない。
- 結果pageを発走前cardとしてas-of APIへ返さない。
- 対象外index、API、リファクタを混ぜない。
- コミット、push、deployを行わない。
