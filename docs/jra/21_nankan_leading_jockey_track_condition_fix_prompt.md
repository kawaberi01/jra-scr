# 南関リーディングジョッキーAPI 馬場条件対応 修正依頼プロンプト

南関競馬のリーディングジョッキーAPIについて、馬場条件コードが未確定のため、URLパターン解析を含めて実装してください。

## 背景

南関公式のリーディングジョッキーは、条件違いで以下のURLになります。

- 川崎競馬場 / 2026
  - https://www.nankankeiba.com/leading_kis/210000002026011.do
- 川崎競馬場 / 距離900 / 2026
  - https://www.nankankeiba.com/leading_kis/210900002026011.do
- 川崎競馬場 / 距離900 / 馬場 良 / 2026
  - https://www.nankankeiba.com/leading_kis/210900012026011.do

ここから、

- 場
- 距離
- 馬場
- 期間
- 表示順

に相当するコードが埋め込まれている前提です。

ただし、現時点では「馬場パラメータのコード対応」が確定していません。
そのため、推測で固定せず、URL構造または画面遷移から安全に特定できるようにしてください。

## 目的

以下のAPIを安定利用できるようにしたいです。

`GET /nankan/leading/jockeys`

想定クエリ:

- `course`
- `distance`
- `track_condition`
- `period`
- `sort`
- `refresh`

例:

`GET /nankan/leading/jockeys?course=kawasaki&distance=900&track_condition=good&period=2026&sort=wins`

## やってほしいこと

### 1. URLコード構造の解析

`leading_kis/{code}.do` の `code` 部分について、少なくとも以下を切り分けてください。

- 場コード
- 距離コード
- 馬場コード
- 期間コード
- 表示順コード

特に馬場コードは未確定なので、以下のどちらかで実装してください。

- ページ上の条件リンクやフォームから逆引きする
- 既知URL差分から安全にテーブル化する

「良=01 らしい」のような曖昧な固定は避けてください。
確証がない場合は、取得過程で実際に検証してください。

### 2. `track_condition` パラメータ対応

APIの `track_condition` は既存 card API と同じ正規値を使ってください。

- `good`
- `slightly_heavy`
- `heavy`
- `bad`

この正規値から、`leading_kis` 側の実URLコードへ変換する処理を追加してください。

### 3. 条件省略時の扱い

以下のように、省略時も扱えるようにしてください。

- `course` のみ
- `course + distance`
- `course + distance + track_condition`

つまり、馬場条件なしの総合ランキングも取れるようにしてください。

### 4. レスポンス形式

最低限以下を返してください。

```json
{
  "source": "nankankeiba",
  "source_url": "https://www.nankankeiba.com/leading_kis/210900012026011.do",
  "course": "kawasaki",
  "distance": 900,
  "track_condition": "good",
  "period": "2026",
  "sort": "wins",
  "generated_at": "2026-07-07T10:00:00Z",
  "items": [
    {
      "rank": 1,
      "jockey_code": "12345",
      "jockey_name": "騎手名",
      "rides": 120,
      "wins": 24,
      "seconds": 18,
      "thirds": 11,
      "win_rate": 20.0,
      "quinella_rate": 35.0,
      "trio_rate": 44.2
    }
  ],
  "cache_hit": false
}
```

### 5. フォールバック

条件付きURLが存在しない、または公式側が未集計の場合は、ベースページへフォールバックしてください。

ただし、

- フォールバックしたことが分かるようにする
- データが見つからない場合はエラーではなく `items: []` を返す

ようにしてください。

## 実装上の注意

- URLコードを呼び出し側で組み立てさせない
- API側で `course / distance / track_condition / period / sort` を受けて変換する
- 画面列順に依存しすぎず、ヘッダ文言で列判定する
- 数値や `%` を正規化する
- 推測実装ではなく、実ページの条件差分で確認する

## テスト観点

最低限、以下を通してください。

1.
`course=kawasaki&period=2026&sort=wins`
で総合ランキングが返る

2.
`course=kawasaki&distance=900&period=2026&sort=wins`
で距離別ランキングが返る

3.
`course=kawasaki&distance=900&track_condition=good&period=2026&sort=wins`
で馬場条件付きランキングが返る

4.
`track_condition=slightly_heavy/heavy/bad`
でも正規値からURLへ変換できる

5.
条件付きURLが存在しない場合、適切にフォールバックまたは `items: []` になる

## 完了条件

- 馬場コード対応がAPI内部で解決されている
- 呼び出し側は `track_condition=good` のような正規値だけ指定すればよい
- 川崎総合、川崎900、川崎900良 の3パターンがAPIで再現できる
- 将来、浦和・船橋・大井にも同じ構造で拡張しやすい実装になっている
