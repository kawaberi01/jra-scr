## 対象機能名
地方競馬 netkeiba API 追加

## 改修目的
既存の JRA API と既存 netkeiba 補完 API の構成に合わせて、`nar.netkeiba.com` の地方競馬情報を取得する API を追加するための現行整理を行う。

## reference_status
not_found

## 現行実装の要点

### 1. API 入口
- [src/jra_srb/app.py](D:/develop/jra-scr/src/jra_srb/app.py)
- 現在の公開 API は大きく以下に分かれる。
  - JRA 本体: `/races/...`, `/meetings/...`
  - netkeiba 補完: `/netkeiba/races/{race_id}/result`, `/netkeiba/races/{race_id}/odds`
- `build_service()` と `build_netkeiba_service()` を分けて依存注入している。

### 2. 既存 netkeiba 補完の責務分離
- [src/jra_srb/netkeiba_provider.py](D:/develop/jra-scr/src/jra_srb/netkeiba_provider.py)
  - HTTP 取得、User-Agent、timeout、retry、min interval を担当
- [src/jra_srb/netkeiba_service.py](D:/develop/jra-scr/src/jra_srb/netkeiba_service.py)
  - cache、bet_type 絞り込み、combination 正規化を担当
- [src/jra_srb/netkeiba_extractors.py](D:/develop/jra-scr/src/jra_srb/netkeiba_extractors.py)
  - race_result HTML、odds payload(JSON/JSONP) をパース
- [src/jra_srb/models.py](D:/develop/jra-scr/src/jra_srb/models.py)
  - 返却モデルは `NetkeibaRaceResult`, `RaceOdds`, `OddsEntry`, `PayoutEntry` を使う

### 3. 既存 netkeiba の券種モデル
- `RaceOdds` / `OddsEntry` は JRA と netkeiba で共通再利用している。
- `BetType` enum は中央競馬向けで `win`, `place`, `quinella`, `wide`, `exacta`, `trio`, `trifecta` のみ。
- 既存 netkeiba 補完では `SUPPORTED_NETKEIBA_BET_TYPES` に `bracket_quinella` が追加されている。
- 地方競馬ページには `枠連`, `枠単` も存在するため、既存 enum/モデルのままでは不足する。

### 4. 既存 netkeiba 利用ガイド
- [docs/jra/10_netkeiba利用ガイド.md](D:/develop/jra-scr/docs/jra/10_netkeiba利用ガイド.md)
- モバイル向け `race.sp.netkeiba.com` を前提にしており、地方競馬の `nar.netkeiba.com` は未対象。

## 外部ページから確認した地方競馬パターン

### 1. 開催カレンダー
- `calendar.html?year={YYYY}&month={M}`
- `calendar.html?...&jyo_cd={venue_code}`
- カレンダーページは日付ごとに競馬場名リンクを持つ。

### 2. 開催一覧
- `race_list.html?kaisai_date={YYYYMMDD}&kaisai_id={YYYY}{jyo_cd}{MMDD}`
- 例: `20260615` と `2026450615`
- 地方開催 1 日ぶんのレース一覧ページになる。

### 3. レース ID
- `race_id = {kaisai_id}{race_no_2digit}`
- 例: `202645061501`

### 4. 出馬表ページ
- `race/shutuba.html?race_id=...`
- レース見出し、発走時刻、距離、向き、天候、馬場、頭数、賞金、馬体重、オッズ、人気がある。

### 5. 結果払戻ページ
- `race/result.html?race_id=...`
- 着順表、払戻、コーナー通過順位がある。

### 6. オッズページ
- `odds/?race_id=...&type=...`
- `type=b0` は上位人気一覧系
- タブとして以下が確認できる
  - 単勝・複勝
  - 枠連
  - 枠単
  - 馬連
  - ワイド
  - 馬単
  - 3連複
  - 3連単

## 現行仕様との差分

### 1. JRA meeting 軸ではなく NAR calendar / kaisai_id 軸
- 既存 JRA は `date + course` から meeting を組み立てる。
- NAR は `year/month` カレンダーと `kaisai_id` を経由する構造が自然。

### 2. 競馬場コード体系が別
- 既存 `CourseCode` は中央 10 場前提。
- 地方競馬は別 enum または別名称マップが必要。

### 3. 券種差分
- `wakuren`, `wakutan` が新規追加候補。
- 既存 odds モデルのままでも文字列 bet_type で受けることはできるが、enum と normalize の扱いを設計し直す必要がある。

### 4. オッズ取得方式差分
- 既存 JRA は HTML / action 遷移
- 既存 netkeiba 補完は odds API(JSON) を使う
- 地方競馬は `type=` 切り替え HTML を最初の対象にするのが無難

## 実装時の注意点
- `nar.netkeiba.com` は `race.sp.netkeiba.com` と別ホストなので、専用 provider を分けるべき。
- 既存 JRA API と route / model / cache key を混ぜすぎない。
- fixture first を維持し、HTML 構造差分を先に固定する。
- 地方競馬は中央より会場と券種が増えるため、初期対応範囲を絞る必要がある。
