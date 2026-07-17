# 020-jra-day-race-scout実装計画書

## 1. 対象と目的

- 対象機能: JRA当日全レースの早朝スカウトとCodexスキル連携。
- 改修目的: 1R前に最大5つの詳細予想候補を選び、既存単レース予想に引き継ぐ。
- 今回の対象範囲: 開催座標自動解決、日次サービス、ルールベース格付け、SQLite保存、POST API、新規スキル、自動テスト。
- 今回やらないこと: 買い目生成、自動購入、通知、スケジューラ、閾値自動学習、複合馬券EV。

## 2. 実装フェーズ

### Phase 1: 事前確認

- 当日JRA開催HTMLで開催回・開催日の表示位置を特定する。
- 対応fixtureを追加し、文字コードと公開範囲を確認する。

### Phase 2: 開催座標とモデル

- extractor、`MeetingSnapshot`、serviceを変更する。
- scout応答モデルとルールの純粋関数を追加する。

### Phase 3: 日次サービス

- bundleの1回取得、モデル成果物の1回読込み、並列数制限、部分失敗継続を実装する。

### Phase 4: 保存とAPI

- analysis SQLiteにrun / entryをtransaction保存する。
- POST endpointと依存構築を追加する。

### Phase 5: Codexスキル

- `skill-creator` の `init_skill.py` で `jra-day-race-scout` を作成する。
- ローカルAPI呼び出し、固定出力、買い目非生成、既存単レーススキルへの引継ぎを記載する。

### Phase 6: テストとレビュー

- 局所テスト、API/DBテスト、全体回帰、スキルvalidation、実開催日手動確認の順で実施する。

## 3. タスク一覧

| ID | フェーズ | 作業内容 | 入力 | 出力 | 依存 | DoD |
| --- | --- | --- | --- | --- | --- | --- |
| T01 | 1 | JRA開催回・日の実HTML調査 | 当日開催ページ | selectorとfixture | なし | 2開催場以上で値を確認 |
| T02 | 2 | 開催座標extractorテストと実装 | fixture | optional meeting fields | T01 | 正常・欠損テスト通過 |
| T03 | 2 | scoutモデルと格付け純粋関数 | 010仕様 | models / rules | T02 | 境界値テスト通過 |
| T04 | 3 | `JraDayRaceScout` 実装 | meetings / bundle / model artifact | run result | T03 | 1race 1bundle、部分失敗継続 |
| T05 | 4 | SQLiteスキーマとtransaction保存 | run result | scout tables | T03 | rollback含むDBテスト通過 |
| T06 | 4 | POST API追加 | service / store | HTTP response | T04,T05 | API契約テスト通過 |
| T07 | 5 | `jra-day-race-scout` スキル作成 | API契約 | SKILL.md / openai.yaml | T06 | quick_validate成功 |
| T08 | 6 | 局所・回帰テスト | 実装差分 | 検証結果 | T02-T07 | 関連・全体テスト成功 |
| T09 | 6 | 実開催日の1R前手動確認 | local API | 手動確認メモ | T08 | 全レース列挙、最大5候補、買い目なし |

## 4. 完了判定

- 実装完了条件:
  - 日付だけで当日開催と開催座標を解決し、日次scout runを作成・保存できる。
  - A/B/C/XとS/V信号が仕様どおりである。
  - scoutが買い目を保存しない。
  - 新規Codexスキルが発見・実行可能である。
- テスト完了条件:
  - `rtk uv run pytest -q tests/test_jra_day_race_scout.py tests/test_jra_prediction_materials.py tests/test_jra_betting_decision.py tests/test_analysis_store.py tests/test_api.py`
  - `rtk uv run pytest -q`
  - skill creatorの `quick_validate.py` 成功。
- レビュー完了条件:
  - `rtk git diff --check` に問題がない。
  - 関連外差分、意図しないBOM・改行変更がない。
  - 買い目禁止、早朝オッズの暂定扱い、データリーク防止を静的レビューで確認する。

## 5. 別タスク候補

- 発走20分前の候補自動再スカウト。
- scout runと確定結果の自動評価API。
- 蓄積後のS/V閾値キャリブレーション。
- Slack、Discord等への通知。
- 単勝以外の共同確率モデル。

