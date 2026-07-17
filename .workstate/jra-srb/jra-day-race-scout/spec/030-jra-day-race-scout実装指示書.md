# 030-jra-day-race-scout実装指示書

## 1. 対象概要

- 対象機能: JRA当日1R前の全レース横断スカウト。
- 改修目的: 一日の候補レースを最大5件に絞り、既存 `jra-race-predictor` の詳細予想に引き継ぐ。
- この機能が行う処理: 開催座標自動解決、全レース材料取得、S/V信号判定、A/B/C/X格付け、日次スナップショット保存、候補一覧返却。
- 変更してよい範囲: 010仕様書の「実装配置」に列挙したファイル、新規スキル配下。
- 変更してはいけない範囲: 履歴モデル学習ロジック、既存単レース格付けの仕様、南関/NAR取得ロジック、買い目ポリシー。

## 2. 実装順序

1. 実JRA開催HTMLを確認し、開催回・開催日extractorの契約とfixtureを固定する。
2. `MeetingSnapshot` とJRA serviceにoptional開催座標を追加し、既存レスポンス回帰を確認する。
3. scoutモデルと純粋なS/V・A/B/C/X判定をテスト駆動で実装する。
4. `JraDayRaceScout` でbundle再利用、履歴成果物1回読込み、並列制限、部分失敗継続を実装する。
5. analysis SQLiteのscout run / entry schemaとtransaction保存を実装する。
6. POST APIを追加し、依存差し替えテストを追加する。
7. `skill-creator` で `jra-day-race-scout` を作成し、ローカルAPI呼び出しと固定出力を記載する。
8. 局所テスト、全体テスト、skill validation、実開催日手動確認を行う。

## 3. 追加 / 修正対象

| 種別 | パス | 内容 |
| --- | --- | --- |
| 追加 | `src/jra_srb/jra_day_race_scout.py` | 日次サービスと格付け関数 |
| 追加 | `tests/test_jra_day_race_scout.py` | 日次処理の局所テスト |
| 修正 | `src/jra_srb/models.py` | 開催座標とscout応答モデル |
| 修正 | `src/jra_srb/extractors.py` | JRA開催回・開催日extractor |
| 修正 | `src/jra_srb/service.py` | JRA meetingへ開催座標を設定 |
| 修正 | `src/jra_srb/analysis_store.py` | scout run / entryテーブルと保存 |
| 修正 | `src/jra_srb/app.py` | POST APIと依存構築 |
| 修正 | `tests/test_api.py` | HTTP契約テスト |
| 修正 | `tests/test_analysis_store.py` | SQLiteスキーマ・transactionテスト |
| 修正 | JRA meeting fixture/test | 開催座標の抽出と欠損回帰 |
| 追加 | `C:\Users\main\skills\jra-day-race-scout\SKILL.md` | 日次スカウトの手順と固定出力 |
| 追加 | `C:\Users\main\skills\jra-day-race-scout\agents\openai.yaml` | スキルUIメタデータ |

## 4. 実装ルール

- 既存構成にない DTO / Repository / Service / DI 分離を標準作成しない。
- 新規抽象化は、既存類似パターンがある場合、または変更局所化に明確な理由がある場合のみ行う。
- 実コードで裏取りできないreference由来の仮説を実装前提にしない。
- 既存 `JraPredictionService`、履歴モデル関数、`build_win_ev_decision()` を流用し、ロジックをコピーしない。
- 日次サービスのルール判定はI/Oから分離した純粋関数とする。
- 早朝のEV推奨を `provisional_value` 以外の表現で返さない。
- 予想ticketは応答、scout DB、既存prediction DBのいずれにも保存しない。
- 個別レース取得失敗をrun全体の例外にしない。
- 開催座標を日付・場の固定辞書で補完しない。
- 履歴モデルの `trained_through < target_date` をrun開始時に検証する。
- upstream並列数は既定3、最大5とし、既存キャッシュを優先する。

## 5. タスク詳細

| 順序 | タスク名 | 内容 | 入力 | 出力 | 完了条件 |
| --- | --- | --- | --- | --- | --- |
| 1 | 開催HTML調査 | 開催回・日の抽出元と欠損時動作を確定 | 実HTML | fixtureとselectorメモ | 2場以上で一致 |
| 2 | meeting拡張 | optional開催座標をモデル・extractor・serviceに追加 | fixture | enriched meeting | JRA正常、他種別回帰通過 |
| 3 | 格付け | 010のS/VとA/B/C/Xを実装 | 公開/履歴順位、EV | scout entry | 境界値とソートテスト通過 |
| 4 | 日次実行 | 全レースを有界並列処理 | date / meetings | run result | 1race 1bundle、partial継続 |
| 5 | DB保存 | run / entryを同一transactionで保存 | run result | SQLite rows | upsert、rollback、JSON復元テスト通過 |
| 6 | API | POST endpointと依存差し替えを追加 | date / query | HTTP response | 422、completed、partial、unavailable通過 |
| 7 | スキル | skill-creatorで初期化後、API実行と既存予想への引継ぎを記載 | API契約 | skill directory | quick_validate成功 |
| 8 | 検証 | 局所、全体、diff、手動確認 | 全差分 | 検証記録 | 020の完了判定を満たす |

## 6. レビュー観点

- 日付のみで全開催座標を解決でき、固定値に依存していないか。
- 各レースのbundle取得が1回で、モデル成果物もrunごと1回読みか。
- S/VとA/B/C/Xが010の閾値と完全に一致するか。
- 早朝オッズを最終推奨と扱っていないか。
- ticketと購入推奨がscout経路から漏れていないか。
- 対象日以降の学習データ、結果、後方スナップショットを参照していないか。
- 部分失敗で他レースの処理とDB保存が継続するか。
- `MeetingSnapshot` 拡張が南関・NARレスポンスとfixtureを壊していないか。
- スキルの出力が候補レースと再確認予定に集中し、単レース詳細を重複表示しないか。

## 7. 禁止事項

- `scripts/jra_live_prediction_day.py` の `MEETING_META` を新機能にコピーすること。
- 全レースに対してprediction bundle、model comparison、betting decision APIを別々に呼ぶこと。
- scout runから `upsert_prediction_record()` を呼ぶこと。
- 早朝の `recommended` を「買い」「勝負確定」と表示すること。
- 取得失敗値を0や推測値で補完すること。
- 履歴モデルの学習期間ガードを無効化すること。
- 既存の単レース予想スキルを日次スキルへ複製すること。
- 実HTML未確認のselectorを仕様どおりとみなして実装を終了すること。
