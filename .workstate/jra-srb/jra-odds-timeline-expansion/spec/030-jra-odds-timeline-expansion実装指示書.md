# 030-jra-odds-timeline-expansion実装指示書

## 1. 対象概要

- 対象機能: JRAオッズ履歴の券種別時点収集。
- 変更してよい範囲: CLI、timeline collector、定期実行PowerShell、関連テスト。
- 変更してはいけない範囲: DBスキーマ、予想・購入ロジック、外部取得元。

## 2. 実装順序

1. `cli.py` に券種別時点の解析を追加し、既存引数との後方互換を維持する。
2. `jra_odds_timeline.py` が時点ごとに必要な券種だけを収集するよう修正する。
3. PowerShellスクリプトを4券種設定へ更新し、上限を432にする。
4. テストを追加・実行し、差分をレビューする。

## 3. 追加 / 修正対象

| 種別 | パス | 内容 |
| --- | --- | --- |
| 修正 | `src/jra_srb/cli.py` | 新引数と解析・検証。 |
| 修正 | `src/jra_srb/jra_odds_timeline.py` | 時点別の券種選択。 |
| 修正 | `scripts/run_jra_odds_timeline_today.ps1` | 運用値。 |
| 修正 | `tests/test_cli.py` | 解析の回帰。 |
| 修正 | `tests/test_jra_odds_timeline.py` | 収集対象の回帰。 |

## 4. 実装ルール

- `SUPPORTED_JRA_BET_TYPES` を唯一の券種許可リストとして使う。
- 新しいRepository、DTO、設定ファイルは作らない。
- 既存の`--bet-types`と`--offset-minutes`だけの呼び出しは維持する。
- ログへ全オッズ行を追加出力しない。

## 5. レビュー観点

- 30分前の三連複API呼び出しがない。
- 同一時点・同一券種の重複取得がない。
- ライブリクエスト上限が理論最大を下回らない。
- 当日進行中の実行へ無理な再起動をしない。
