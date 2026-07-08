---
name: nankan-race-session-starter
description: Start a live or same-day Nankan race prediction with a short instruction and fixed defaults. Use when the user wants to say only the date, course, and race number such as "今日の川崎1Rを予想", "7/9 川崎 3R", or "次のレースを予想" and still get the full Japanese prediction format, rationale, odds, budgeted betting plan, and separate dansou reference without repeating the long prompt each time.
---

# Nankan Race Session Starter

短い開始指示を、`nankan-race-predictor` へ渡すための前処理スキルです。

## 実行方針

1. 対象を 1 レースだけに固定する。
2. 日付、場、レース番号を読み取る。
3. ユーザーがモードを明示していなければ、既定を `integrated_betting` とする。
4. 予想本体は必ず [../nankan-race-predictor/SKILL.md](../nankan-race-predictor/SKILL.md) を読んでから実行する。
5. 出力は日本語固定とし、見出し順も崩さない。

## 入力の解釈

- `今日` は当日のローカル日付として扱う。
- `明日` や `7/9` のような相対・月日指定は絶対日付へ補う。
- `川崎1R`、`川崎 1R`、`1レース` のような省略表現を受け付ける。
- `次のレース` と言われた場合は、その時点で未発走または直近対象の 1 レースだけを扱う。
- 情報が足りない場合は、欠けているのが `日付 / 場 / レース番号` のどれかを短く確認する。

## 既定値

- 予想モード: `integrated_betting`
- 対象件数: 1 レースのみ
- 予想スタイル: 本番用
- 断層競馬: 常に別枠で参考表示する
- データ取得: `prediction-bundle` 優先
- live 中の取得: `refresh=true` 前提
- `prediction-bundle` が `404` でも異常扱いせず、必要なら個別 API へフォールバックしてよい

## 必須出力

`nankan-race-predictor` の固定出力順をそのまま使い、少なくとも次を必ず含めること。

1. `レース情報`
2. `予想モード`
3. `使用データ`
4. `当日傾向`
5. `熱さ判定`
6. `予想順位`
7. `予想の根拠`
8. `買い方`
9. `予算別の買い方`
10. `マークシート向け`
11. `注意点`
12. `断層競馬参考`

## このラッパーで固定する条件

- 1 日分をまとめて出さず、今回指定した 1 レースだけを予想する。
- 必ず根拠を添える。
- 予想順位の各馬に、取れている範囲でオッズを併記する。
- `熱さ判定`、`本命信頼度`、`買う価値`、`低配当判定` を必ず出す。
- `相手昇格` があれば理由を書く。
- `見送り` 寄りでも、買うならどう買うかを軽く出す。
- 買い方は `1000円 / 2000円 / 3000円` の予算別に出す。
- `熱い！` のときは厚め配分案も出してよい。
- `流し / フォーメーション / BOX` のような、マーク数の少ない書き方も出す。
- 断層競馬は予想本体に混ぜず、最後に参考として出す。

## データ欠損時の扱い

- 馬体重が未発表なら `未発表のため未取得` と明記する。
- 馬体重が取得不可なら `取得不可` と明記する。
- 当日傾向は `usable=true` の場合だけ採用する。
- `usable=false` なら、無理に傾向を使わず理由を短く添える。
- オッズがまだ取れない場合は、その旨を `使用データ` または `注意点` に残す。
- `pattern` 比較は全量表示ではなく、馬ごとの主要指標だけを抜いて扱う。
- 文字化けした日本語ラベルは、まずエンコード問題を疑い、データ欠損と即断しない。

## 開始時のまとめ

最後に短く次の 2 点を付ける。

- `今回の主軸`
- `買うなら何を中心に買うか`
