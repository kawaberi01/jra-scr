# netkeiba odds combination 指定ガイド

## 対象 API

netkeiba のオッズ取得 API では、`bet_type` と `combination` を指定して特定の買い目だけを取得できます。

```text
GET /netkeiba/races/{race_id}/odds?bet_type={bet_type}&combination={combination}
```

例:

```text
GET http://127.0.0.1:8000/netkeiba/races/202605021211/odds?bet_type=wide&combination=13,17
```

## combination の書き方

`combination` は馬番をカンマ区切りで指定します。

```text
combination=13,17
combination=17,13
combination=17,13,5
```

数字文字列は正規化されます。

```text
combination=05,13
```

これは次と同じ扱いです。

```text
combination=5,13
```

## 順不同として扱う券種

以下の券種は、指定順が違っても同じ買い目として扱います。

```text
bracket_quinella
quinella
wide
trio
```

例: `wide`

```text
GET /netkeiba/races/202605021211/odds?bet_type=wide&combination=13,17
GET /netkeiba/races/202605021211/odds?bet_type=wide&combination=17,13
```

どちらも同じ entry に一致します。

例: `quinella`

```text
GET /netkeiba/races/202605021211/odds?bet_type=quinella&combination=11,17
GET /netkeiba/races/202605021211/odds?bet_type=quinella&combination=17,11
```

どちらも同じ entry に一致します。

例: `trio`

```text
GET /netkeiba/races/202605021211/odds?bet_type=trio&combination=1,11,17
GET /netkeiba/races/202605021211/odds?bet_type=trio&combination=17,11,1
```

どちらも同じ entry に一致します。

## 順序ありとして扱う券種

以下の券種は、指定順を維持して別の買い目として扱います。

```text
exacta
trifecta
```

例: `exacta`

```text
GET /netkeiba/races/202605021211/odds?bet_type=exacta&combination=17,11
GET /netkeiba/races/202605021211/odds?bet_type=exacta&combination=11,17
```

この2つは別の entry として扱います。

例: `trifecta`

```text
GET /netkeiba/races/202605021211/odds?bet_type=trifecta&combination=17,13,5
GET /netkeiba/races/202605021211/odds?bet_type=trifecta&combination=17,5,13
```

この2つは別の entry として扱います。`17,5,13` を `17,13,5` に丸めることはありません。

## 単一馬の券種

以下は単一馬指定なので、順序の問題はありません。

```text
win
place
```

例:

```text
GET /netkeiba/races/202605021211/odds?bet_type=win&combination=17
GET /netkeiba/races/202605021211/odds?bet_type=place&combination=17
```

## 全件取得

`bet_type` を指定しない場合は、従来通り全券種をまとめて返します。

```text
GET /netkeiba/races/202605021211/odds
```

この場合、`combination` による絞り込みは使いません。特定の買い目だけを取得したい場合は、必ず `bet_type` も指定してください。

## 起動例

```powershell
cd D:\develop\jra-scr
.venv-win\Scripts\uvicorn.exe jra_srb.app:app --reload
```

Swagger UI:

```text
http://127.0.0.1:8000/docs
```

## 注意

- netkeiba API は JRA 公式サイトではなく `https://race.sp.netkeiba.com/` にアクセスします。
- テストは fixture を使っており、ライブ netkeiba へのアクセスには依存しません。
- 大量取得や無制限クロール前提では使わないでください。
