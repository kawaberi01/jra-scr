# Superpowers拡張構成と運用シミュレーション

## 目的

この文書は、既存の Superpowers を外さずに、上位の成果物計画と文書反映を追加した運用形を定義する。

対象は次の 2 点である。

- どれが既存スキルで、どれが追加スキルか
- それらを組み合わせたとき、実際にどのような流れでプロジェクトを進めるか

## 前提

現在の Superpowers は、個別テーマの設計と実装を強く前進させる一方で、次の点は弱い。

- プロジェクト全体として最初に必要な成果物を決めること
- 正式文書と作業文書を分けて運用すること
- 複数セッション前提で progress-summary を標準化すること
- `update-docs` のように正式文書を育てること

この不足を補うために、既存 Superpowers の前段と途中に新しいスキルを加える。

## 既存スキルと新規スキル

### 既存スキル

以下は現在の Superpowers 群に存在し、引き続き利用するスキルである。

- `brainstorming`
- `using-git-worktrees`
- `writing-plans`
- `subagent-driven-development`
- `executing-plans`
- `test-driven-development`
- `requesting-code-review`
- `verification-before-completion`
- `finishing-a-development-branch`

### 新規スキル候補

以下は今回の問題意識に対応するために追加するスキルである。

#### 1. `artifact-planning`

役割:

- テーマ開始前に必要成果物を決める
- 正式文書と作業文書を分ける
- 更新対象の正式文書を先に決める
- `progress-summary` を最初から必須成果物にする

このスキルは、`brainstorming` の前に使う。

#### 2. `dual-track-documentation`

役割:

- `docs/superpowers` の作業文書と `docs/` の正式文書を二層で運用する
- 実装の節目で `update-docs` を行う
- 正式文書への未反映を `progress-summary` に残す

このスキルは、実装中およびセッション終了時に使う。

## スキル構成の全体像

### 上位フロー

1. `artifact-planning`
2. `brainstorming`
3. `using-git-worktrees`
4. `writing-plans`
5. `subagent-driven-development` または `executing-plans`
6. `test-driven-development`
7. `requesting-code-review`
8. `dual-track-documentation`
9. `verification-before-completion`
10. `finishing-a-development-branch`

### 位置づけ

- `artifact-planning` は「何を成果物として残すか」を決める上位スキル
- `brainstorming` は「個別テーマをどう設計するか」を決める設計スキル
- `writing-plans` は「どう実装するか」を決める実装準備スキル
- `dual-track-documentation` は「どう正式文書へ反映するか」を支える運用スキル

## 各スキルの責務

### `artifact-planning`

出力:

- 更新対象の正式文書一覧
- 作業文書一覧
- 初期 `progress-summary`
- 完了条件
- 検証方針

この段階では、まだ詳細設計には入らない。

### `brainstorming`

出力:

- テーマの設計書
- 選択肢比較
- 採用方針

この段階では、設計の妥当性を固める。

### `using-git-worktrees`

出力:

- 隔離された作業環境
- 対応ブランチ
- 必要なら worktree パス

### `writing-plans`

出力:

- 実装計画
- タスク分解
- 検証ステップ

### `test-driven-development`

出力:

- 失敗から始まるテスト
- 最小実装
- リファクタリング済みコード

### `requesting-code-review`

出力:

- 指摘事項
- 残課題
- 修正要否

### `dual-track-documentation`

出力:

- 更新済み正式文書
- `progress-summary` の `Doc sync status`
- 未反映事項の一覧

### `verification-before-completion`

出力:

- 実行済み確認コマンド
- 実際の結果
- 完了主張の根拠

### `finishing-a-development-branch`

出力:

- 最終 handoff
- マージまたは PR 判断
- cleanup 方針

## JRA テーマでのシミュレーション

題材:

- 「JRA のスクレイピング基盤を作る」

ここでは、作業を 3 セッションに分けてシミュレーションする。

## セッション 1: 成果物計画と設計

### 使うスキル

- 新規: `artifact-planning`
- 既存: `brainstorming`

### 進め方

#### Step 1. `artifact-planning`

最初に「何を作るか」ではなく「何を残すか」を決める。

この時点で決める内容:

- 正式文書:
  - `docs/01_プロジェクト概要.md`
  - `docs/02_アーキテクチャ.md`
  - `docs/03_設計判断.md`
  - `docs/04_利用ガイド.md`
  - `docs/06_セキュリティと運用注意.md`
- 作業文書:
  - `docs/superpowers/specs/2026-03-22-jra-data-retrieval-design.md`
  - `docs/superpowers/plans/2026-03-22-jra-data-retrieval-implementation-plan.md`
  - `docs/superpowers/2026-03-22-jra-data-retrieval-progress-summary.md`

さらに決める内容:

- 進捗メモは最初から必須
- セッション終了前に `Next step` を更新する
- API 追加時には `docs/04_利用ガイド.md` を更新する
- JRA 固有の導線判断は `docs/03_設計判断.md` に反映する

#### Step 2. `brainstorming`

JRA の `JRADB + cname` 導線をどう扱うかを設計する。

ここで固まる内容:

- navigation 層を分離する
- provider / extractors / service / app の層構造を維持する
- `course + date + race_no` から実ページへ解決する
- オッズと結果は開催単位導線を使う

### セッション 1 の終了時点で残る成果物

- 正式文書:
  - `docs/00_成果物戦略と開発フロー.md`
- 作業文書:
  - 設計書
  - progress-summary 初版

### progress-summary に残す内容

- `Current status`: 設計完了、実装未着手
- `Completed`: 成果物計画、設計書作成
- `Remaining`: 実装計画、navigation 実装、API 実装
- `Next step`: 実装計画を作成する
- `Doc sync status`: 正式文書への詳細反映は未着手

## セッション 2: 実装計画と初回実装

### 使うスキル

- 既存: `using-git-worktrees`
- 既存: `writing-plans`
- 既存: `test-driven-development`
- 既存: `executing-plans`
- 既存: `requesting-code-review`
- 新規: `dual-track-documentation`

### 進め方

#### Step 1. `using-git-worktrees`

ブランチと worktree を作り、隔離された環境で作業を開始する。

残すべき状態:

- 現在ブランチ
- worktree パス
- baseline テスト結果

#### Step 2. `writing-plans`

設計書から実装計画を作る。

分解されるタスク例:

- Task 1: navigation 層の追加
- Task 2: provider の JRA POST 対応
- Task 3: meeting API の追加
- Task 4: card API の追加

この段階で `progress-summary` にも反映する。

#### Step 3. `test-driven-development` + `executing-plans`

Task 1 と Task 2 を実装する。

例:

- `tests/test_navigation.py` を RED から書く
- `src/jra_srb/navigation.py` を追加する
- `provider.py` に `post_jradb()` を追加する

#### Step 4. `requesting-code-review`

navigation 層の責務分離や fixture の妥当性を確認する。

#### Step 5. `dual-track-documentation`

この節目で `update-docs` を行う。

反映先:

- `docs/02_アーキテクチャ.md`
  - navigation 層の追加
- `docs/03_設計判断.md`
  - `cname` を外部 API に出さない判断

### セッション 2 の終了時点で残る成果物

- 作業文書:
  - 実装計画
  - 更新済み progress-summary
- 正式文書:
  - アーキテクチャ更新
  - 設計判断更新

### progress-summary に残す内容

- `Current status`: navigation 実装完了、meeting API 着手前
- `Completed`: Task 1, Task 2
- `Remaining`: Task 3 以降
- `Next step`: meeting API のテストを先に書く
- `Verification`: navigation テスト通過
- `Doc sync status`: architecture と design decisions は反映済み

## セッション 3: API 拡張と文書反映

### 使うスキル

- 既存: `test-driven-development`
- 既存: `executing-plans`
- 既存: `requesting-code-review`
- 新規: `dual-track-documentation`
- 既存: `verification-before-completion`

### 進め方

#### Step 1. meeting/card/odds/result API を実装

順番:

1. meeting API
2. card API
3. odds API
4. result API

各タスクで RED-GREEN-REFACTOR を回す。

#### Step 2. `requesting-code-review`

レビュー対象:

- API の整合性
- モデル設計
- パーサの責務肥大
- テスト不足

#### Step 3. `dual-track-documentation`

この段階で `update-docs` を行う。

反映先:

- `docs/04_利用ガイド.md`
  - エンドポイント例
  - `bet_type`、`combination`、`refresh`
- `docs/06_セキュリティと運用注意.md`
  - JRA 依存
  - 文字コード注意
  - fixture と実ページの差

#### Step 4. `verification-before-completion`

例:

- `uv run --extra dev pytest -q`
- `uv run uvicorn jra_srb.app:app`

#### Step 5. セッション終了

完了していなくても、`progress-summary` を更新して終える。

残す内容:

- 未対応券種
- 次回の最初の一手
- 正式文書未反映箇所

## この構成の利点

- 既存 Superpowers の強みを維持できる
- `brainstorming` がいきなり孤立した設計書づくりにならない
- 作業文書と正式文書の役割が分かれる
- 1 セッションで終わらなくても再開しやすい
- 別 PC、別セッション、別作業者でも追いやすい

## 推奨ルール

当面の標準は次のとおりとする。

1. テーマ開始時に必ず `artifact-planning` を実行する
2. `brainstorming` の前に、更新対象の正式文書を決める
3. `writing-plans` と同時に `progress-summary` を初期化する
4. 各セッション終了前に `progress-summary` を更新する
5. 節目で必ず `dual-track-documentation` により `update-docs` を行う
6. 完了前に `verification-before-completion` を通す

## 結論

既存の Superpowers は、実装フローの中核としてそのまま使ってよい。

不足しているのは、開始時に成果物体系を決める上位スキルと、正式文書を育てる中間スキルである。

したがって、採るべき構成は次のとおりである。

- 元スキル:
  - `brainstorming`
  - `using-git-worktrees`
  - `writing-plans`
  - `executing-plans`
  - `test-driven-development`
  - `requesting-code-review`
  - `verification-before-completion`
  - `finishing-a-development-branch`
- 新スキル:
  - `artifact-planning`
  - `dual-track-documentation`

この構成であれば、Superpowers を捨てずに、あなたの求める「大きな枠から始まる開発標準」を作れる。
