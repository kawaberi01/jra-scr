# 030-major-venue-model 実装指示書

## 1. 対象概要

- 対象機能: 東京・中山主要場モデル。
- 改修目的: 客観的採否と安全な運用統合。
- 変更可能: 対象モデル、評価/監査成果物、関連API/scout/predictor/保存、関連テスト、運用文書。
- 変更禁止: 夏開催V90のロジック、既存ユーザーログ、無関係なリファクタ、既知holdoutへの再適合。

## 2. 実装順序

1. `006-次回着手メモ.md` と本書を読み、DB・成果物監査を実行する。
2. 汚染台帳とas-of監査を確定し、holdout候補を隔離する。
3. 評価器を本番同等のrace-date逐次履歴にし、リーク/再現性テストを作る。
4. baselineと事前登録候補をholdout以外で比較する。
5. 候補・閾値・採否基準をcommitしてからholdoutを一度だけ開封する。
6. 決定に従い、既存と衝突しないversionを割り当てる。v89をそのまま採用できるなら新versionを作らない。
7. API・予想保存へ後方互換に統合し、全検証を行う。

## 3. 実装ルール

- コード・SQLite・実行結果を正本とする。
- 順位と券種/オッズfilterを分離する。
- 外部取得はDB不足時だけ限定範囲・低負荷で行う。
- 未来/同日結果、結果ページ由来オッズ、holdout結果を特徴量・閾値調整に使わない。
- 新馬・障害を一般戦に混ぜない。
- 既存構成にない抽象化や依存を理由なく追加しない。

## 4. 必須成果物

- data audit、contamination ledger、experiment contract、baseline/candidate results、venue holdout、robustness、decision、operations/rollback、progress。
- 自動テスト: unit、API、時系列リーク防止、再現性、保存。

## 5. 停止条件

- DB値の意味がコード/schemaから確定できない場合は、その特徴量を使わない。
- holdoutが汚染済みまたは30買い目未満なら正式採用を停止しshadowへ移行する。
- push権限・remote競合・既存差分との衝突は破壊的解消をせず阻害要因として報告する。

## 6. 確認コマンド候補

- `rtk uvx ruff check .`
- `rtk uv run --extra dev pytest -q <target tests>`
- `rtk uv run --extra dev pytest -q`
- `rtk git diff --check`
- API再起動後に `/openapi.json` と代表東京・中山レースのmodel comparisonを確認する。

