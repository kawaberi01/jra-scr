## 対象機能名
地方競馬 netkeiba API 追加

## 改修目的
- `nar.netkeiba.com` の地方競馬開催日程、開催一覧、出馬表、結果払戻、オッズを既存 API に追加できるようにする。
- 既存の JRA API と既存の netkeiba API の責務分離を維持したまま、NAR 向けの別導線を用意する。

## 対象 root
- `D:\develop\jra-scr`

## 想定成果物
- `.workstate/jra-srb/nar-netkeiba-api-addition/spec/`
- `.workstate/jra-srb/nar-netkeiba-api-addition/progress/`

## 現時点で確認した対象 URL
- カレンダー
  - `https://nar.netkeiba.com/top/calendar.html?rf=race_list`
  - `https://nar.netkeiba.com/top/calendar.html?year=2026&month=6`
  - `https://nar.netkeiba.com/top/calendar.html?year=2026&month=6&jyo_cd=45`
- 開催一覧
  - `https://nar.netkeiba.com/top/race_list.html?kaisai_date=20260615&kaisai_id=2026450615`
- 出馬表
  - `https://nar.netkeiba.com/race/shutuba.html?race_id=202645061501`
- 結果払戻
  - `https://nar.netkeiba.com/race/result.html?race_id=202645061501&rf=race_list`
- オッズ
  - `https://nar.netkeiba.com/odds/?race_id=202645061501&type=b0`

## URL / ID ルール仮説
- `jyo_cd` は地方競馬場コード
  - 例: 川崎は `45`
- `kaisai_id` は `YYYY + jyo_cd + MMDD`
  - 例: `2026450615`
- `race_id` は `kaisai_id + race_no(2桁)`
  - 例: `202645061501`

## 実コード優先で採用した前提
- 既存の中央競馬向け API は `provider / service / extractors / models / app` 分離で実装されている。
- 既存の netkeiba 補完 API は `netkeiba_provider.py`, `netkeiba_service.py`, `netkeiba_extractors.py` を持つ。
- NAR も同じ流儀で、JRA 本体と混ぜず別モジュールとして足す方針が自然。

## 今回の仕様化で扱う範囲
- API 追加可否の検討
- URL / ID 規則の整理
- 既存構成への追加設計
- 初期実装スコープの決定

## 今回の仕様化で扱わない範囲
- 実装そのもの
- ライブアクセスの大量巡回
- analysis.sqlite 保存設計の詳細
- 地方競馬の全券種完全対応の確定
