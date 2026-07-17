# v90 2024 外部検証データ収集バッチ

## 目的

v90_summerを変更せず、2024年7〜8月を補助的な外部検証に使うためのJRA公式データを段階収集する。

## 実行順

1. history batch 1〜12 を順番に実行する。
2. 各バッチの結合監査が成功した場合だけ次へ進む。
3. target batch 13〜16 を実行する。
4. 2024年7〜8月だけの正しいnetkeiba開催カレンダーを作成する。
5. mapping生成、netkeiba結果収集、監査後にv90を1回だけ評価する。

## JRA公式データのバッチ

| batch | 期間 | 競馬場 | 用途 |
|---:|---|---|---|
| 1 | 01-01..01-15 | 中山・京都・小倉 | history |
| 2 | 01-16..01-31 | 中山・京都・小倉 | history |
| 3 | 02-01..02-15 | 東京・京都・阪神・小倉 | history |
| 4 | 02-16..02-29 | 東京・京都・阪神・小倉 | history |
| 5 | 03-01..03-15 | 中山・中京・阪神 | history |
| 6 | 03-16..03-31 | 中山・中京・阪神 | history |
| 7 | 04-01..04-15 | 福島・中山・阪神 | history |
| 8 | 04-16..04-30 | 福島・東京・京都 | history |
| 9 | 05-01..05-15 | 新潟・東京・京都 | history |
| 10 | 05-16..05-31 | 新潟・東京・京都 | history |
| 11 | 06-01..06-15 | 東京・阪神 | history |
| 12 | 06-16..06-30 | 東京・阪神・函館 | history |
| 13 | 07-01..07-15 | 函館・福島・小倉 | target |
| 14 | 07-16..07-31 | 函館・福島・小倉・札幌 | target |
| 15 | 08-01..08-15 | 札幌・新潟 | target |
| 16 | 08-16..08-31 | 札幌・新潟 | target |

## 実行例

```powershell
rtk uv run jra-srb collect-analysis --from-date 2024-01-01 --to-date 2024-01-15 --courses nakayama,kyoto,kokura --db "data/db/analysis.sqlite" --include-card --include-results --retries 1 --min-interval-seconds 3 --max-live-requests 50 --skip-existing

rtk uv run jra-srb verify-analysis-joins --from-date 2024-01-01 --to-date 2024-01-15 --db "data/db/analysis.sqlite" --sample-size 5
```

以後のバッチも同じ既存CLIに、対象期間・競馬場だけを表のとおり指定する。バッチは最大50リクエスト・3秒間隔・`--skip-existing` 固定である。途中失敗時は同じ期間を再実行する。収集済みカード・結果は再取得しない。

## 中断条件

- `verify-analysis-joins` が失敗した場合
- collection runがpartialのまま再実行しても改善しない場合
- upstreamエラー、429、403が続く場合
- 1バッチが15分を超える場合

中断時は次バッチに進まず、保存件数・エラー内容・実行番号を記録して原因を確認する。
