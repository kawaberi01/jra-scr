## 対象機能名
地方競馬 netkeiba API 追加

## 改修目的
`nar.netkeiba.com` から地方競馬の開催日程、開催一覧、出馬表、結果払戻、オッズを取得する API を既存構成に沿って追加する。

## 変更してよい範囲
- `src/jra_srb/app.py`
- `src/jra_srb/models.py`
- `src/jra_srb/` 配下の NAR 向け新規モジュール追加
- `tests/` と `tests/fixtures/`
- `docs/jra/05_API仕様.md`

## 変更してはいけない範囲
- 既存 JRA API の route 契約
- 既存 `/netkeiba/races/...` API の挙動
- 既存 analysis.sqlite 保存機能
- 既存 CLI の主契約

## 実装順序
1. `models.py` に NAR 用 calendar / meeting モデルを追加する
2. `nar_netkeiba_provider.py` を追加する
3. `nar_netkeiba_extractors.py` を追加する
4. `nar_netkeiba_service.py` を追加する
5. `app.py` に `/nar/...` endpoint を追加する
6. fixture を追加する
7. extractor / API テストを追加する
8. `docs/jra/05_API仕様.md` を更新する

## 追加 / 修正対象ファイル候補
- `src/jra_srb/models.py`
- `src/jra_srb/app.py`
- `src/jra_srb/nar_netkeiba_provider.py`
- `src/jra_srb/nar_netkeiba_extractors.py`
- `src/jra_srb/nar_netkeiba_service.py`
- `tests/test_nar_netkeiba_extractors.py`
- `tests/test_api.py`
- `tests/fixtures/nar_*`
- `docs/jra/05_API仕様.md`

## 実装詳細指示

### route
- `/nar/calendar`
  - query: `year`, `month`, `course` optional
- `/nar/meetings/{date_}/{course}`
- `/nar/races/{race_id}/card`
- `/nar/races/{race_id}/result`
- `/nar/races/{race_id}/odds`

### provider
- `nar.netkeiba.com` 専用 provider と fixture provider を分ける
- User-Agent, timeout, retry, min interval を持つ
- HTML decode は `utf-8`, `euc_jp`, `shift_jis` を順に試す

### service
- calendar / race_list / card / result / odds を分けて呼ぶ
- odds は `bet_type` と `combination` のフィルタを持つ
- 順不同券種
  - `quinella`, `wide`, `trio`
- 順序付き券種
  - `exacta`, `trifecta`
- `wakuren`, `wakutan` は実装する場合だけ既存ロジックに局所追加し、中央 API 側の enum 契約を壊さない

### extractor
- race header から以下を拾う
  - `race_name`
  - `start_time`
  - `distance`
  - `surface`
  - `direction`
  - `weather`
  - `track_condition`
- runner 行から以下を優先取得
  - `frame_no`
  - `horse_no`
  - `horse_name`
  - `sex_age`
  - `weight_carried`
  - `jockey`
  - `trainer`
  - `horse_weight`
  - `horse_weight_diff`
  - `odds`
  - `popularity`
- result は
  - 着順
  - 馬番
  - 馬名
  - 騎手
  - タイム
  - 払戻
  - コーナー通過順位
  を優先する

### fixture
- 2026-06-15 川崎を起点 fixture にする
- fixture 名は `nar_` prefix に統一する

## テスト観点
- calendar month 取得
- course filter 取得
- race_list 取得
- card 取得
- result 取得
- odds 取得
- 順不同券種の逆順一致
- 順序券種の順序維持
- 文字化けなし

## 人手確認観点
- 実ページと fixture の整合
- odds `type` と券種の対応
- 地方競馬場コード文字列の公開契約

## 禁止事項
- JRA 側 service / provider に NAR 用分岐を大量に混ぜること
- 実装途中で analysis DB 保存まで広げること
- fixture なしで live HTML 前提実装にすること
- `race.sp.netkeiba.com` の既存 netkeiba 補完コードへ直接混在させること

## 停止条件
- `type=` と券種の対応が fixture 取得だけでは確定しない
- NAR 用 `course` 公開値の設計が固まらない
- `wakuren` / `wakutan` を初回公開範囲へ入れるか判断できない

## 実装時に最低限見るべき静的確認観点
- `app.py` の依存注入が JRA / 既存 netkeiba と独立していること
- `models.py` の既存 enum 契約を壊していないこと
- 新規 extractor / service / provider の責務が混ざっていないこと
- 既存 `tests/test_api.py` に波及破壊がないこと

## ビルド・テストを人間へ引き継ぐ場合の確認コマンド候補
- `rtk .venv-win\\Scripts\\pytest.exe tests\\test_nar_netkeiba_extractors.py tests\\test_api.py -q`
- `rtk .venv-win\\Scripts\\pytest.exe -q`
