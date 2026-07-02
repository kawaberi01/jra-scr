# netkeiba 利用ガイド

## 位置づけ

このリポジトリには、JRA 公式サイト向け API とは別に、netkeiba の過去レースページから補完データを取得する API があります。

- 既存 JRA 公式 API: `/races/...`、`/meetings/...`
- netkeiba 補完 API: `/netkeiba/races/...`

`race_id` は既存 API と同じ 12 桁を使いますが、取得元は別です。netkeiba API は `https://race.sp.netkeiba.com/` にアクセスします。

## 起動

Windows のローカル環境では、リポジトリ直下で次を実行します。

```powershell
cd D:\develop\jra-scr
.venv-win\Scripts\uvicorn.exe jra_srb.app:app --reload
```

起動後、Swagger UI で確認できます。

```text
http://127.0.0.1:8000/docs
```

## レース結果を取得する

```text
GET http://127.0.0.1:8000/netkeiba/races/202605021211/result
```

主な返却項目です。

- `race_id`
- `race_name`
- `date`
- `course`
- `race_no`
- `surface`
- `distance`
- `direction`
- `weather`
- `track_condition`
- `results`
- `payouts`
- `corner_passages`
- `fetched_at`
- `source`

`results` には、着順、枠番、馬番、馬名、性齢、斤量、騎手、調教師、馬体重、増減、走破時計、着差、上がり、単勝オッズ、人気などが入ります。

## オッズを取得する

全券種をまとめて取得します。

```text
GET http://127.0.0.1:8000/netkeiba/races/202605021211/odds
```

券種を絞る場合:

```text
GET http://127.0.0.1:8000/netkeiba/races/202605021211/odds?bet_type=wide
```

券種と組み合わせを絞る場合:

```text
GET http://127.0.0.1:8000/netkeiba/races/202605021211/odds?bet_type=wide&combination=13,17
```

## 対応 bet_type

```text
win
place
bracket_quinella
quinella
wide
exacta
trio
trifecta
```

優先対応は `wide`、`quinella`、`trio`、`trifecta` です。現状は `win`、`place`、`exacta`、`bracket_quinella` も取得できます。

## JRA 公式 API との違い

JRA 公式 API は JRA 公式サイトから取得します。

```text
GET /races/{race_id}/result
GET /races/{race_id}/odds
```

netkeiba API は netkeiba から取得します。

```text
GET /netkeiba/races/{race_id}/result
GET /netkeiba/races/{race_id}/odds
```

同じ `race_id` を使っても、アクセス先は別です。netkeiba API は JRA 公式サイトにはアクセスしません。

## キャッシュとアクセス頻度

netkeiba はスクレイピング対象なので、無制限クロール前提では使わないでください。

実装上は以下を考慮しています。

- User-Agent を指定
- タイムアウトを指定
- 5xx や通信失敗時のリトライ
- 最小アクセス間隔
- TTL キャッシュ

netkeiba への最小アクセス間隔は環境変数で変更できます。

```powershell
$env:JRA_SRB_NETKEIBA_MIN_INTERVAL_SECONDS="2.0"
```

既定値は 1 秒です。

## テスト

netkeiba 取得は fixture first で実装しています。ライブ取得に依存せず、保存済み HTML/JSON fixture でテストします。

```powershell
cd D:\develop\jra-scr
.venv-win\Scripts\pytest.exe tests/test_netkeiba_extractors.py tests/test_api.py -q
```

全体テスト:

```powershell
cd D:\develop\jra-scr
.venv-win\Scripts\pytest.exe -q
```

## 現時点の未対応点

- 大量取得・巡回処理は未実装
- DB 保存は未実装
- `corner_order` は各馬の行単位では未設定
- ページ構造変更時は extractor の調整が必要
