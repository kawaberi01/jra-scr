# 000-JRA出馬表as-of履歴前提メモ

## 1. 対象

- 対象root: `D:\develop\jra-scr`
- 対象機能: JRA出馬表as-of履歴
- 改修目的: 指定観測時点のレース情報と出走馬集合を、結果情報なしで再現する。
- reference_status: `not_found`

## 2. 今回の調査範囲

- `races/runners` schema。
- `write_race()`、`write_card()`。
- `Runner/RaceCard/StoredPreRaceRunner`。
- analysis collector、timeline collector。
- pre-race snapshot Store/APIと関連test。

## 3. フェーズ1で確定したこと

- 現行`races/runners`は最新値upsert tableで、履歴を保持しない。
- `Runner`の馬体重・増減は`runners`と公開snapshot DTOへ保存されない。
- 取消・除外を表す明示fieldは現行`Runner`と抽出処理にない。
- `write_card()`はカードから消えたrunnerを最新tableから削除しない。

## 4. 次工程で固定する契約

- 1カード取得を完全なrunner集合snapshotとして扱うか。
- 前世代に存在し後世代から消えた馬を取消として導出する条件。
- 不完全取得と取消を区別するdata quality条件。
- `as_of`境界時刻と同一時刻の順序。
- 最新値tableを互換用途で維持する方法。

## 5. フェーズ2で確認した入力

- ユーザー要件: 仕様作成から実装、ビルド相当確認まで完了する。
- reference_status: `not_found`
- 読み込んだproject reference: なし。router同梱資料はOZ系プロジェクト向けで本機能に該当しない。
- 参照した主要コード:
  - `src/jra_srb/models.py`
  - `src/jra_srb/extractors.py`
  - `src/jra_srb/service.py`
  - `src/jra_srb/analysis_store.py`
  - `src/jra_srb/app.py`
  - `src/jra_srb/jra_odds_timeline.py`
- 参照した主要テスト:
  - `tests/test_extractors.py`
  - `tests/test_analysis_store.py`
  - `tests/test_api.py`
  - `tests/test_jra_odds_timeline.py`

## 6. フェーズ2で固定した方針

- card取得単位のappend-only集合snapshotを採用する。
- parserが候補行をすべて馬番付きrunnerへ変換できた時だけ完全cardとする。
- 不完全cardは監査用に保存してもas-of合成には使わず、runner欠落を取消へ変換しない。
- 完全card間で消えたrunnerは直前payloadを引き継ぎ、`withdrawn/derived`として保存する。
- HTML行に取消・除外が明示される場合は`withdrawn/explicit`として保存する。
- 結果ページ由来cardは`result_page`として区別し、発走前as-of履歴には使わない。
- 既存最新値tableは互換用途で維持し、履歴がない旧DBでは`as_of`省略時のみ従来参照へfallbackする。
