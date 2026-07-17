# 010-jra-day-race-scout実装仕様書

## 0. 最初に読む要約

- 対象機能: JRA当日全レースの早朝スカウト
- 改修目的: 1R発走前の同一時点材料で全レースを比較し、発走前に詳細予想する候補を最大5レース返す。
- 現行仕様の要点: 単レースの材料・二モデル比較・単勝期待値は実装済みだが、日次横断処理と開催座標自動解決はない。
- 実装時の最重要注意点: 早朝オッズの期待値は暂定信号とし、この機能から買い目を生成・保存しない。

## 1. 変更後仕様

### 1.1 入力

- HTTP: `POST /jra/days/{date_}/race-scout`
- path:
  - `date_`: ISO日付。
- query:
  - `max_candidates`: 1〜10、既定5。
  - `refresh`: bool、既定false。通常はキャッシュを使う。
  - `max_concurrency`: 1〜5、既定3。
- 日次スカウトはサーバー当日と異なる日付でも実行可能だが、発走済みレースは `skipped_started` として候補対象外にする。

### 1.2 出力

```json
{
  "run_id": "jra-scout-20260712-...",
  "date": "2026-07-12",
  "observed_at": "...",
  "phase": "morning_scout",
  "status": "completed|partial|unavailable",
  "race_count": 36,
  "analyzed_count": 32,
  "candidates": [
    {
      "rank": 1,
      "race_id": "...",
      "course": "...",
      "race_no": 9,
      "race_name": "...",
      "start_time": "...",
      "grade": "A",
      "signals": ["S", "V"],
      "confidence_signal": {
        "top_pick_agrees": true,
        "top3_agreement_count": 2,
        "history_probability_gap": 0.084
      },
      "value_signal": {
        "status": "provisional_value",
        "horse_no": "5",
        "expected_return": 1.18,
        "market_edge": 0.062
      },
      "recheck_required": true,
      "reasons": [],
      "component_status": {}
    }
  ],
  "entries": [],
  "errors": []
}
```

- `candidates` は上位 `max_candidates` 件のみ。
- `entries` は当日全レースの簡易判定。クライアントが見送り理由を確認できるように返す。
- 馬の予想順位全件と買い目は返さない。候補馬番は暂定妙味の説明用に限定する。

### 1.3 信号と格付け

#### S: 信頼信号

次のすべてを満たす場合に付与する。

- 履歴モデルが `available`。
- 公開材料モデルと履歴モデルの1位が一致。
- Top3一致が2頭以上。
- 履歴モデル1位と2位の `win_probability_race_normalized` 差が0.05以上。

#### V: 暂定妙味信号

- `build_win_ev_decision()` の結果が `recommended` の場合に付与する。
- API応答上は `recommended` を `provisional_value` に変換する。
- `recheck_required` は常にtrueとする。
- `build_win_ev_decision()` が返すticketは破棄し、scout応答・DBのどちらにも保存しない。

#### 格付け

| grade | 条件 | 意味 |
| --- | --- | --- |
| A | SかつV | 信頼と暂定妙味が両立し、最優先で再確認する。 |
| B | SまたはVのどちらか一方 | 信頼型または妙味型として再確認する。 |
| C | 必須材料はあるがS/Vなし | 優先度の低い参考候補。 |
| X | card不備、公開材料順位不能、履歴モデル不能、発走済みのいずれか | 候補対象外。 |

- `candidates` にはA、Bの順で格納し、件数不足時のみCを含める。Xは含めない。
- 同一grade内は、期待回収倍率降順、履歴勝率差降順、発走時刻昇順、race_id昇順で安定ソートする。該当値なしは0とする。

### 1.4 開催回・開催日の解決

- JRA開催一覧の実HTMLから、開催場ごとの `meeting_no` と `meeting_day` を抽出する。
- `MeetingSnapshot` にJRAでは値あり、他種別ではnullを許容するoptionalフィールドとして追加する。
- 解決できない開催場は固定値で補完せず、その開催場の各レースをXにし、`errors` に `meeting_coordinates_unavailable` を記録する。
- 抽出元と抽出値をfixtureテストで固定する。

### 1.5 処理フロー

1. `get_meetings_for_date(date_)` で当日開催を取得する。
2. 開催ごとに `meeting_no` / `meeting_day` を検証する。
3. 発走済みレースをスキップする。発走時刻不明は処理対象にするが、注意理由を付ける。
4. semaphoreでレース間並列数を制限し、1レースにつき `get_prediction_bundle()` を1回呼ぶ。
5. bundleから `build_prediction_record()` で公開材料順位を作るが、recordとticketは保存しない。
6. 履歴モデル成果物を日次runの先頭で1回読み、対象日より前の `trained_through` であることを確認する。
7. 各cardから履歴特徴量と順位を作る。
8. 公開材料順位、履歴順位、単勝オッズからS/V信号とgradeを決める。
9. 全entryを並べ、上位候補を取得する。
10. scout runとentryを同一SQLite transactionで保存する。
11. 保存した内容と同一の応答を返す。

### 1.6 正常系

- 一部レースの外部材料取得が失敗しても、他レースの処理と保存を継続し、run statusを `partial` にする。
- 候補が0件でもrunは正常保存し、`candidates=[]` を返す。
- 当日にJRA開催がない場合は `status=unavailable`、`race_count=0` を保存・返却する。

### 1.7 異常系

- 日付不正、query範囲外: FastAPI標準の422。
- 履歴モデル成果物なし、または学習終了日が対象日以降: 全レースX、run status `unavailable`。後方情報を使って継続しない。
- SQLite保存失敗: HTTP 500。runとentryはtransactionでrollbackする。
- 想定外の個別レース例外: entryをXにし、例外型と非機密メッセージを `errors` に記録する。

### 1.8 副作用

- JRA公式と設定有効な公開外部ソースへの取得。
- 既存cacheへの書き込み。
- analysis SQLiteへのscout run / entry保存。
- `predictions` / `prediction_tickets` には書き込まない。

## 2. 既存構成における担当

- 入口: `src/jra_srb/app.py`
- 入力・応答モデル: `src/jra_srb/models.py`
- 開催座標抽出: `src/jra_srb/extractors.py`、`src/jra_srb/service.py`
- 日次処理: 新規 `src/jra_srb/jra_day_race_scout.py`
- 既存材料取得: `JraPredictionService`
- 既存公開材料順位: `build_prediction_record()`
- 既存履歴モデル: `load_model_artifact()` / `build_live_feature_records()` / `score_live_records()`
- 既存単勝期待値: `build_win_ev_decision()`
- データアクセス: `AnalysisSQLiteStore`
- Codexスキル: `C:\Users\main\skills\jra-day-race-scout`

## 3. 実装配置

### 追加ファイル

- `src/jra_srb/jra_day_race_scout.py`: 日次オーケストレーションと格付け純粋関数。
- `tests/test_jra_day_race_scout.py`: 格付け、ソート、部分失敗、買い目非生成のテスト。
- `C:\Users\main\skills\jra-day-race-scout\SKILL.md`: 日次スカウト実行手順と固定出力。
- `C:\Users\main\skills\jra-day-race-scout\agents\openai.yaml`: スキルUI情報。

### 修正ファイル

- `src/jra_srb/models.py`: 開催座標、scout run / entryモデル。
- `src/jra_srb/extractors.py`: JRA開催回・開催日抽出。
- `src/jra_srb/service.py`: `MeetingSnapshot` へ開催座標を設定。
- `src/jra_srb/analysis_store.py`: scoutテーブル初期化、transaction保存、参照。
- `src/jra_srb/app.py`: 日次スカウト依存構築とPOST endpoint。
- `tests/test_api.py`: API契約テスト。
- `tests/test_analysis_store.py`: DB初期化と保存テスト。
- `tests/test_service_historical_meeting_fallback.py` または新規extractorテスト: 開催座標の回帰確認。

### 既存流用

- 既存のbundle、公開材料順位、履歴モデル、単勝EV関数を再利用する。
- 既存 `jra-race-predictor` は候補の発走前詳細予想にそのまま使い、日次スキルにコピーしない。

### 新規抽象化

- `JraDayRaceScout` は、多数レースの並列制御、モデル成果物の1回読込み、部分失敗継続をendpointから分離するため追加する。
- Repositoryは追加せず、既存 `AnalysisSQLiteStore` を拡張する。

## 4. 根拠

| 判断 | 根拠ファイル | 行 | 備考 |
| --- | --- | --- | --- |
| 開催一覧を日付で取れる | `src/jra_srb/service.py` | 230 | `get_meetings_for_date()` |
| `MeetingSnapshot` に開催回・日がない | `src/jra_srb/models.py` | 214 | 現行フィールドを確認 |
| bundleはレースごとに取得する | `src/jra_srb/jra_prediction_service.py` | 98 | `get_prediction_bundle()` |
| model comparisonがbundleを再取得する | `src/jra_srb/app.py` | 1234 | endpoint内でbundle取得 |
| betting decisionがbundleを再取得する | `src/jra_srb/app.py` | 1295 | endpoint内でbundle取得 |
| 公開材料順位をbundleから作れる | `src/jra_srb/jra_prediction_engine.py` | 11 | `build_prediction_record()` |
| 単勝EV閾値は実装済み | `src/jra_srb/jra_betting_decision.py` | 6 | 1.05 / 0.03 / 2.0 |
| 既存日次スクリプトは開催座標を固定している | `scripts/jra_live_prediction_day.py` | 16 | `MEETING_META` |
| analysis SQLiteに予想保存がある | `src/jra_srb/analysis_store.py` | 251 | 日次scoutは別テーブルとする |

## 5. エラー / ログ / 設定

- エラー処理: 個別レース例外はrun全体を止めずX entryに変換する。DB transaction失敗だけはendpoint失敗にする。
- ログ: run_id、date、race_id、component、elapsed time、cache hit、例外型を構造化ログに入れる。オッズ全件やレスポンスHTMLはログに出さない。
- 設定: 新規環境変数は追加せず、endpoint queryと既存のupstream制限を使う。閾値は初版ではモジュール定数とし、応答に記録する。
- 機密情報: 扱わない。公開・匿名取得の現行方針を維持する。

## 6. Reference との差分

| Reference 仮説 | 実コードの事実 | 採用判断 |
| --- | --- | --- |
| 日次処理は既存単レースAPIを36×3回呼べばよい | 比較とEV endpointはbundleを再取得する | 不採用。サービス内でbundleを1回再利用する。 |
| 早朝の `recommended` は購入推奨である | 現行EVは時間帯を考慮しない | 不採用。`provisional_value` に読み替える。 |
| 既存日次スクリプトを流用できる | 開催座標が3場固定で、横断格付けもない | 不採用。サービスを新設する。 |

## 7. テスト観点

### 自動テスト

- 開催回・開催日をJRA fixtureから抽出できる。
- 開催座標不明を固定値で補完しない。
- S/V、A/B/C/Xの境界値。
- 同grade内の安定ソート。
- `max_candidates`、候補0件、開催0件。
- 個別レース失敗時のpartial継続。
- 履歴モデル不在・学習期間不正の全X判定。
- bundle取得が各レース1回である。
- scout応答とDBにbet ticketが含まれない。
- run / entryが同一transactionで保存される。
- APIの422、completed、partial、unavailable。

### 手動確認

- 実開催日の1R前に `refresh=false` で実行し、全開催場・全レースが列挙される。
- オッズ未公開レースがあってもrunがpartialで完了する。
- 候補出力が最大5件で、「買い目」を表示しない。
- 発走20分前に既存 `jra-race-predictor` で再予想できるrace_id、場、R番号が表示される。

### 回帰確認

- 既存開催一覧、card、odds、result API。
- 既存JRA prediction bundle、model comparison、betting decision、prediction save。
- 既存南関とNARの `MeetingSnapshot` シリアライズ。
- analysis SQLiteの既存テーブルと評価。

## 8. 対象外

- 日次スカウトからの買い目生成、購入、通知。
- 発走前自動再実行スケジューラ。
- S/V閾値の機械学習、自動調整。
- 日次スカウト専用の結果評価API。初版は保存データと既存結果をSQLで検証可能にするところまで。
- 複勝、ワイド、馬連、三連系の期待値。
- 履歴モデルの学習ロジック変更。
- ダッシュボードと通知システム。

## 9. 要確認事項

- 開催回・開催日の抽出selectorは実HTMLの事前調査で確定する。selectorを確定できない場合は、日付のみのAPI契約を満たせないため実装を進めない。

