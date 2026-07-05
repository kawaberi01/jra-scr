## 対象機能名
地方競馬 netkeiba API 追加

## 改修目的
`nar.netkeiba.com` の地方競馬情報取得 API を、既存構成を崩さずに追加する。

## 実装方針
- JRA 本体 API と混ぜない
- 既存 netkeiba 補完 API に近い責務分離で追加する
- fixture first
- 初回スコープは単一開催日・単一レース取得に絞る

## 実装ステップ

1. モデル追加
- NAR 用 calendar / meeting モデル追加
- 必要なら地方券種文字列の扱いを拡張

2. provider 追加
- NAR HTML 取得用 provider / fixture provider 追加
- timeout / retry / min interval / decode を実装

3. extractor 追加
- calendar
- race_list
- race_card
- race_result
- odds

4. service 追加
- calendar 取得
- meeting 取得
- race card/result/odds 取得
- `combination` 正規化

5. app 追加
- `/nar/calendar`
- `/nar/meetings/{date_}/{course}`
- `/nar/races/{race_id}/card`
- `/nar/races/{race_id}/result`
- `/nar/races/{race_id}/odds`

6. fixture / tests 追加
- extractor テスト
- API テスト
- odds 正規化テスト

7. docs 反映
- `docs/jra/05_API仕様.md`
- 必要なら `docs/jra/04_利用ガイド.md` か新規ガイド

## 対象ファイル候補
- `src/jra_srb/models.py`
- `src/jra_srb/app.py`
- `src/jra_srb/nar_netkeiba_provider.py` 新規
- `src/jra_srb/nar_netkeiba_service.py` 新規
- `src/jra_srb/nar_netkeiba_extractors.py` 新規
- `tests/test_nar_netkeiba_extractors.py` 新規
- `tests/test_api.py`
- `tests/fixtures/*` 新規
- `docs/jra/05_API仕様.md`

## テスト観点
- calendar 月指定で開催日が取れる
- course 指定で会場絞り込みが効く
- `kaisai_id` からレース一覧が取れる
- `race_id` から出馬表が取れる
- `race_id` から結果払戻が取れる
- `race_id` から券種別オッズが取れる
- 順不同券種の逆順指定が一致する
- 順序券種の順序性が保持される
- 文字化けしない

## 人手確認観点
- 実際の `2026-06-15 川崎 1R` と fixture の一致
- 出馬表の馬体重・人気・オッズの有無
- 結果払戻の券種名と返却 bet_type の対応
- オッズ `type` ごとの券種対応

## リスク
- HTML 構造が中央 netkeiba と別
- `type=` の券種対応が一部未確定
- 地方競馬場コードの固定 enum 化で漏れが出る可能性

## 停止条件
- odds `type` と券種対応が fixture だけでは確定できない場合
- calendar から meeting 解決の導線が会場ごとに不安定な場合
- `wakuren` / `wakutan` を初回スコープへ含めるかの判断が未確定な場合
