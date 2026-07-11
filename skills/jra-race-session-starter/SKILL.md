---
name: jra-race-session-starter
description: Start one live or same-day JRA prediction from a short date, course, and race instruction, using the JRA prediction bundle and the full Japanese output format.
---

# JRA Race Session Starter

南関 `nankan-race-session-starter` をJRA用に差し替えた1レース開始ラッパーです。

1. 対象を1レースに固定する。
2. 日付、場、レース番号を解釈する。開催回・開催日が不明なら当日の公開開催情報から確認する。
3. モード未指定は `integrated_betting` とする。
4. 必ず [../jra-race-predictor/SKILL.md](../jra-race-predictor/SKILL.md) を読んで実行する。
5. 開催中は `prediction-bundle` を `refresh=true` で1回取得する。
6. 発走済みなら事前予想を捏造せず、回顧参考か結果検証かを明示する。
7. JRA予想スキルの固定出力順を使い、取得時刻、確定前後、欠損、オッズを必ず表示する。

既定値:

- 対象: 1レース
- モード: 総合買い目型
- 予算: 1000円 / 2000円 / 3000円
- 保存: ユーザーが一連の予想運用を求めた場合は有効
- 結果照合: 確定後のみ
