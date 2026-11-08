---
name: jra-day-confidence-ranking
description: 指定日のJRA全レースを、購入推奨ではなく履歴モデルの相対確度差で順位付けし、重賞、未分析、除外理由まで固定テンプレートで返す。ユーザーが「全レースの確度」「比較的確度が高いレース」「確度順」「重賞も含めて比較」「今日のレースを信頼度順に」と依頼した時に使う。買い目や購入判断の作成には使わない。
---

# JRA 全レース相対確度ランキング

全レースの状態を確認し、既定では分析済みレースを `history_probability_gap` の降順で比較する。これは的中確率や購入推奨ではなく、履歴モデル1位と2位の推定勝率差を使った相対指標である。利用者がモデルを指定した場合はそのモデルを優先し、比較指標を明記する。

ローカル API を使う前に [local-race-api-ready](../local-race-api-ready/SKILL.md) を実行する。準備に失敗したらランキング API に進まず、理由を実行状況へ記す。

## 手順

1. 対象日を `YYYY-MM-DD` で確定する。「今日」はサーバー日付を使う。
2. 上記の `local-race-api-ready` が成功したことを確認する。同じ作業で準備済みなら再実行しない。
3. JRA公式の開催日程または重賞一覧を確認し、その日の全重賞を `競馬場コード,レース番号,格,レース名` にする。検索する場合は `jra.go.jp` の一次情報だけを使う。見つからない重賞をレース名から推測しない。
4. `scripts/rank_confidence.py` を1回実行する。スクリプトが次のAPIを1回だけ呼び、全 `entries` を整形する。

   `POST /jra/days/{date}/race-scout?max_candidates=10&refresh=false&max_concurrency=3&mode=quick&time_budget_seconds=45`

5. 確認した重賞ごとに `--graded-race "course,race_no,grade,race_name"`、公式URLごとに `--official-source "label=url"` を渡す。

   ```powershell
   rtk uv run python "C:\Users\main\skills\jra-day-confidence-ranking\scripts\rank_confidence.py" --date 2026-08-16 --graded-race "chukyo,7,GIII,中京記念" --graded-race "sapporo,11,GII,札幌記念" --official-source "JRA公式重賞一覧=https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html"
   ```

6. 初回の対象が少ない場合は、下記の逐次補完で未取得分を埋めてから比較する。既定モデルではスクリプトのMarkdown出力を見出し・列・順序を変えずに返す。指定モデルでは同じ章順を保ち、指標と未実装の評価欄を正確に表示する。買い目を加えない。

## 未取得分の逐次補完・指定モデル

- 保存済みデータを優先し、開催一覧で未発走の未取得レースを特定する。ローカルAPIから1件ずつ取得し、1回5件・各リクエスト20秒を目安に範囲を分ける。分割実行・逐次補完を認める。
- 成功データを途中保存し、再開時は取得済み範囲を再利用する。個別の取得失敗は記録して次へ進む。対象範囲の完了またはAPI接続不能など共通の障害で止め、残件を表示する。
- タイムアウトした全件APIを同じ条件で繰り返さない。初回スカウト1回という指定は、未取得分の個別取得を禁止する意味ではない。
- CatBoost v3を指定された場合は、プロジェクトの `scripts/scout_jra_catboost_day.py` と保存済みモデルを使う。例：`--date 2026-10-04 --ranker-model <モデルパス> --fill-missing --max-fetches 5 --request-timeout 20`。
- CatBoostの順位1位と2位のスコア差は未校正の比較指標であり、履歴勝率差・的中確率と同一視しない。モデル名、観測時刻、分析件数、除外・残件を明記し、未実装の評価・S/Vは `—` とする。未分析が残る場合、全日上位とは断定しない。

## 判定規則

- 分析済みは `grade != X` とする。
- 並び順は `history_probability_gap` 降順、同値なら発走時刻、`race_id` 順とする。
- APIの `grade` はスカウト評価であり、G1/G2/G3の格ではない。重賞の格はJRA公式情報だけを使う。
- `S`、`V`、`grade A/B/C` はAPI値をそのまま表示する。
- `public_analysis=not_loaded` や `value_signal=null` を補完・推測しない。
- `time_budget_exceeded`、`skipped_started`、取得エラーは削除せず、未分析・除外へ全件表示する。
- `status=partial` でも分析済みランキングは表示し、重賞が未分析なら重賞欄で明示する。
- API応答を失った場合の調査・再整形に限り、`--from-db data/db/analysis.sqlite` で同日の最新保存結果を読む。通常実行では使わない。

## 固定出力

必ず次の順序にする。

1. `# JRA全レース相対確度`
2. `## 実行状況`
3. `## 相対確度ランキング`
4. `## 重賞`
5. `## 未分析・除外`
6. `## 読み方`

チケット、購入金額、買う・見送るの断定は出力しない。個別馬の予想を求められた場合だけ、選択されたレースを `$jra-race-predictor` に渡す。
