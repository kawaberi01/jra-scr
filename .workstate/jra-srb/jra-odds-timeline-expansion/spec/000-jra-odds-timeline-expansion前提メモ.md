# 000-jra-odds-timeline-expansion前提メモ

## 1. 対象

- 対象 root: `D:\develop\jra-scr`
- 対象機能: JRA発走前オッズ履歴収集
- 改修目的: 単勝・ワイドに加え、馬連を3時点、三連複を2時点で全組合せ保存する。
- 関連バッチ: `scripts/run_jra_odds_timeline_today.ps1`、Windowsタスク `JRA-SRB-Odds-Weekly-*`

## 2. 入力情報

- ユーザー要件: 実装仕様を作成後、スキル手順で実装する。
- 運用判断: 馬連は発走30・10・2分前、三連複は10・2分前に限定する。
- 実コードで確認した主要コード: `src/jra_srb/jra_odds_timeline.py`、`src/jra_srb/cli.py`、`scripts/run_jra_odds_timeline_today.ps1`。

## 3. 作成する成果物

- `005-jra-odds-timeline-expansion現行仕様整理.md`
- `010-jra-odds-timeline-expansion実装仕様書.md`
- `020-jra-odds-timeline-expansion実装計画書.md`
- `030-jra-odds-timeline-expansion実装指示書.md`

## 4. 注意点

- 全組合せは件数を削らない。負荷抑制は三連複の取得時点を2回に制限して行う。
- 当日すでに経過した取得時点の三連複を後から復元しない。
