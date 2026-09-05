# 2026年秋シャドー運用・ロールバック

## 日次運用

発走10分以上前に実行する。東京・中山だけを処理し、順位は全対象レース、買い目は実取得wide oddsがある場合だけ保存する。

```powershell
rtk uv run python scripts/jra_major_venue_shadow_day.py --date YYYY-MM-DD --db data/db/analysis.sqlite --min-lead-minutes 10 --output .workstate/jra-srb/tokyo-nakayama-major-model/live/YYYY-MM-DD.json
```

保存先:

- `predictions`: theory_version `v89_autumn_2026_shadow`, mode `paper_validation`
- `prediction_tickets`: 実wide oddsを確認できた候補だけ
- `race_card_snapshots`, `odds_snapshots`: 発走前取得時刻つきsnapshot

再実行時は同一race/theoryが保存済みならskipする。結果取得は予測保存後に別工程で行う。

## 再評価

- 合算30買い目かつ各場10買い目へ到達するまで昇格判定しない。
- 評価時は予測created_at・odds fetched_atが発走より前で、結果保存より前であることを先に監査する。
- 指標・gateは `experiment_contract.json` を使用し、結果を見て変更しない。

## ロールバック

1. `src/jra_srb/jra_v_theory.py` の東京・中山routeを従来の `main_venue_candidate` / `not_final` に戻す。
2. `app.py` のV理論呼出しから `race_odds` 追加を戻す必要はない（後方互換なoptional引数）。
3. 日次shadow scriptの実行を停止する。
4. 保存済み予測は監査証跡のため削除しない。`theory_version` で運用対象から除外する。
5. 夏開催V90には変更がないことをroute testで再確認する。

