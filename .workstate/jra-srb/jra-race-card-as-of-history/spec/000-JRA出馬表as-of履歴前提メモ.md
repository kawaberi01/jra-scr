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
