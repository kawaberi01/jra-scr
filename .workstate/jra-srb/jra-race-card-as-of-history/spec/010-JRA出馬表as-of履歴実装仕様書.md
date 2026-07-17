# 010-JRA出馬表as-of履歴実装仕様書

## 0. 最初に読む要約

- 対象機能: JRA-NEXT-003 出馬表のas-of履歴化
- 改修目的: 指定観測時点以前のレース情報、出走馬集合、取消・除外、騎手、馬体重、オッズを結果情報なしで再現する。
- 現行仕様の要点: `races/runners`は最新値upsertで、保存済みsnapshot APIも最新値だけを読む。
- 実装時の最重要注意点: 不完全取得による欠落を取消と誤判定せず、結果ページ由来cardを発走前履歴へ採用しない。
- reference_status: `not_found`
- 実コード優先の判断: 既存のmodel、Store、FastAPI route、collector、pytest構成へ直接追加する。
- spec_root: `.workstate/jra-srb/jra-race-card-as-of-history/spec/`
- progress_root: `.workstate/jra-srb/jra-race-card-as-of-history/progress/`

## 1. 変更後仕様

### 1.1 card品質

- `RaceCardDataStatus`へrunner集合状態、理由、source種別を追加する。
- runner集合状態は`complete`または`incomplete`。
- source種別は`pre_race_card`、`result_page`、`unknown`。
- runner候補行が1行以上あり、全候補行が馬番付きrunnerへ変換され、馬番が重複しない場合だけ`complete`。
- 行がない、変換漏れがある、馬番がない、馬番が重複する場合は`incomplete`。
- 馬体重状態は既存の`available/unpublished/unavailable`を維持する。

### 1.2 runner状態

- `Runner`と保存用runner DTOへ`status`と`status_source`を追加する。
- `status`: `active`または`withdrawn`。既定は`active`。
- `status_source`: `explicit`、`derived`、またはnull。
- HTML行に`出走取消`、`競走除外`、`取消`、`除外`が含まれる場合は`withdrawn/explicit`。
- 直前の完全世代に存在し、次の完全世代から消えたrunnerは、直前payloadを引き継いで`withdrawn/derived`。
- 不完全世代との差分では状態を導出しない。
- 後続完全世代に再出現したrunnerは`active`へ戻す。

### 1.3 履歴schema

- `race_card_snapshots`
  - card取得1回につきUUIDの`card_snapshot_id`を1行appendする。
  - race/card項目、`runner_set_status`、理由、source種別、`fetched_at`を保持する。
- `race_card_snapshot_runners`
  - `(card_snapshot_id, horse_no)`を主キーとする。
  - runner payload、馬体重、card odds、人気、状態、状態根拠を保持する。
- 不完全なpre-race cardも監査用にappendするが、as-of参照候補にしない。
- `result_page`は発走前履歴tableへ保存しない。
- 新規の性能indexは追加しない。必要性は`JRA-NEXT-016`で実測する。

### 1.4 最新値table互換

- `races/runners`は既存API・収集処理との互換用に維持する。
- `runners`へ馬体重、状態、状態根拠をadditive migrationする。
- `races`へcardに存在する天候、馬場、表示labelをadditive migrationする。
- 完全なpre-race card保存時は、その履歴世代で最新runner集合を置き換える。
- 不完全cardまたはresult pageでは既存と同様に取得できたrunnerだけをupsertし、欠落runnerを削除しない。

### 1.5 API

- 対象: `GET /jra/races/{race_id}/pre-race-snapshot`
- 新規query: `as_of`
  - 任意、timezone offset必須のISO 8601日時。
  - 指定時は`fetched_at <= as_of`の最新完全pre-race card世代を選ぶ。
  - 同一時刻は`card_snapshot_id`降順で決定する。
- `as_of`指定時のオッズも`fetched_at <= as_of`だけを対象にし、券種ごとの最新世代を返す。
- `odds_timing`指定時もas-of境界を適用する。
- `as_of`以前に完全card世代がない場合は404。
- `as_of`省略時は最新完全世代を優先し、履歴がない旧DBだけ従来の`races/runners`へfallbackする。
- response `meta`へ`requested_as_of`、`card_snapshot_id`、`card_fetched_at`、`runner_set_status`を追加する。
- 結果、払戻、評価tableは参照しない。

### 1.6 collector

- `JraService.get_race_card_by_number()`へ既定falseの`refresh`を追加する。
- 定刻オッズcollectorは、実際に取得する券種がある観測taskごとにcardを1回強制再取得して保存する。
- card取得はlive request上限と最小intervalの対象とする。
- card取得失敗時も可能な範囲でオッズ取得を続け、失敗件数へ記録する。

## 2. 既存構成における担当

- 抽出・品質判定: `extractors.py`
- 公開/保存model: `models.py`
- cache制御: `service.py`
- 永続化・as-of合成: `analysis_store.py`
- 定刻観測: `jra_odds_timeline.py`
- HTTP入力とresponse model: `app.py`
- API説明: `docs/jra/05_API仕様.md`

## 3. エラー・時刻・互換性

- timezoneなし`as_of`はFastAPI/Pydantic validationで422。
- Storeを直接呼ぶ場合もtimezoneなし`as_of`は`ValueError`。
- SQLite日時境界は`julianday()`で比較する。
- 既存queryを省略したレスポンスはadditive field以外の意味を維持する。
- migrationで既存`races/runners`行、ID、結果、オッズを削除しない。

## 4. テスト観点

- 通常card、明示取消card、不完全cardの抽出。
- card世代appendと馬体重保存。
- 完全世代間の取消導出と再出現。
- 不完全世代で取消を導出しない。
- result pageを発走前履歴へ採用しない。
- `as_of`境界前後、同一時刻、timezone offset。
- `as_of`以下のオッズだけを返す。
- 旧DBの最新値fallbackとadditive migration。
- API 200/404/422、OpenAPI、結果リーク防止。
- 定刻collectorのcard強制再取得、skip、live request件数。

## 5. 対象外

- 過去card履歴の推測backfill。
- 結果tableからのrunner補完。
- index最適化。
- MCP公開、認証、CORS。
- JRA以外の新しい公開as-of API。

## 6. 要確認事項

- 実サイトの未知の取消classは、取得fixtureが追加された時に明示判定を拡張する。今回の契約は日本語の取消・除外表示を正とする。
