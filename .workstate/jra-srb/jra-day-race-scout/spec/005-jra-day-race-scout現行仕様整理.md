# 005-jra-day-race-scout現行仕様整理

## 1. 現在できていること

| 項目 | 現行入口 | 実コード上の状態 |
| --- | --- | --- |
| 当日開催列挙 | `JraService.get_meetings_for_date()` | 開催場と各1R〜12Rの `MeetingSnapshot` を返す。 |
| 単レース材料 | `GET /jra/meetings/{date}/{course}/races/{race_no}/prediction-bundle` | card、odds、public analysis、trend、3種lite指標を返す。 |
| 二モデル比較 | `GET .../model-comparison` | 公開材料順位、履歴モデル順位、本命一致、Top3一致馬を返す。 |
| 単勝期待値 | `GET .../betting-decision` | 履歴勝率×単勝オッズで `recommended` / `no_bet` / `unavailable` を返す。 |
| 予想保存 | `AnalysisSQLiteStore.upsert_prediction_record()` | 単レース予想と買い目を `predictions` 系テーブルへ保存する。 |
| 全レース予想スクリプト | `scripts/jra_live_prediction_day.py` | 全レースのbundle取得と単レース予想保存を行う。横断格付けはない。 |

## 2. 現在不足していること

- 当日全レースの同一時点比較がない。
- レース内の1位と2位の分離度、二モデル一致、暂定妙味を日次の候補順に変換する処理がない。
- 日次スカウト専用の実行履歴・候補保存がない。
- 日付だけから外部ソース用JRA開催回・開催日を自動解決する契約がない。
- 日次スカウトを実行するCodexスキルがない。

## 3. 重要な現行制約

### 3.1 開催座標

- JRA内部race_idは日付、場コード、レース番号の12桁であり、開催回・開催日を含まない。
- `build_source_keys()` は `meeting_no` と `meeting_day` を必須入力とする。
- `MeetingSnapshot` と `MeetingRace` には `meeting_no` / `meeting_day` がない。
- analysis SQLiteのJRAレースは12桁race_idから開催回・開催日を復元できない。

### 3.2 重複取得

- `model-comparison` と `betting-decision` はそれぞれ内部で `get_prediction_bundle()` を呼ぶ。
- 日次処理から3 APIをレースごとに個別呼び出しすると、同じデータの再計算と外部取得が増える。
- 日次処理はbundleを1レース1回だけ取得し、後続判定で再利用する必要がある。

### 3.3 期待値判定

- 現行閾値は期待回収倍率1.05以上、市場確率差0.03以上、単勝2.0倍以上である。
- 朝時点のオッズは最終オッズではない。日次スカウトでは `recommended` を `provisional_value` 信号に読み替える必要がある。

## 4. 現行テストと流用可能なパターン

- `tests/test_jra_prediction_materials.py`: 外部ソースキー生成。
- `tests/test_jra_prediction_engine.py`: bundleからの公開材料順位生成。
- `tests/test_jra_betting_decision.py`: 単勝期待値の純粋関数テスト。
- `tests/test_api.py`: FastAPIの依存差し替えとfixture-firstテスト。
- `tests/test_analysis_store.py`: SQLiteスキーマ初期化、upsert、参照テスト。
- `tests/test_service_historical_meeting_fallback.py`: 開催一覧のフォールバック。

## 5. 変更に対する現行差分

| 要件 | 現状 | 必要な変更 |
| --- | --- | --- |
| 日付だけで実行 | 開催回・日が別途必要 | JRA開催座標リゾルバを追加 |
| 全レース横断 | 単レースAPIのみ | 日次サービスとAPIを追加 |
| 候補格付け | なし | 純粋関数で信頼・妙味信号とA/B/C/Xを決定 |
| スナップショット保存 | 単レース予想のみ | scout run / entryをSQLite保存 |
| Codexから利用 | 単レーススキルのみ | `jra-day-race-scout` スキルを追加 |

## 6. 未確認事項

- JRAの当日開催ページのどの要素から開催回・開催日を安定して取れるかは、実HTML fixtureを追加して確定する必要がある。
- 朝時点で公開外部ソースと単勝オッズが全レース分公開済みかは日による。未公開は失敗ではなく個別レースの欠損として扱う。

