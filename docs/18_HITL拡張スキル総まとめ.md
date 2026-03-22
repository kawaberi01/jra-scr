# HITL拡張スキル総まとめ

## 目的

この文書は、ここまで追加した `superpowers` 向けアドオンスキルと、その使い方、既存スキルとの役割分担、実際の運用フローをまとめた総覧である。

対象は主に次の用途である。

- 個人開発の中小規模 Web アプリ
- 複数セッションにまたがる実装
- `Human in the Loop` での継続開発
- 必要に応じたマルチエージェント並列作業

## 前提整理

既存の `superpowers` は強力だが、主に「その場で高品質に進める」ことに強い。
一方で、次は標準では弱かった。

- 最初に何の資料が必要か決めること
- セッションをまたいで自然に再開すること
- `docs/superpowers` と `docs/` を二層で育てること
- タスク状態を持ち、順番を動的に再評価すること
- マルチエージェントで shared state を安全に扱うこと

今回追加したのは、この弱い部分を補うアドオン群である。

## 追加したスキル一覧

### 1. `addon-superpowers-artifact-planning`

ファイル:

- `/home/main/.codex/skills/addon-superpowers-artifact-planning/SKILL.md`

役割:

- 実装や詳細設計の前に、今回何の成果物を作るべきかを決める
- 正式文書と作業文書を分ける
- `progress-summary` を最初から必須にする

向いている場面:

- 新しいテーマを始めるとき
- API 案件か GUI 案件かで必要文書が変わるとき
- `README` だけで済ませるべきか、`UI設計` や `API仕様` まで分けるべきか判断したいとき

### 2. `addon-superpowers-dual-track-documentation`

ファイル:

- `/home/main/.codex/skills/addon-superpowers-dual-track-documentation/SKILL.md`

役割:

- `docs/superpowers` の作業文書から、`docs/` の正式文書へ知識を反映する
- `update-docs` 的な考え方を運用に組み込む

向いている場面:

- 実装後に docs を育てたいとき
- working docs に閉じた知識を正式文書へ昇格させたいとき
- `README`、`利用ガイド`、`アーキテクチャ`、`設計判断` を整えたいとき

### 3. `addon-superpowers-hitl-execution`

ファイル:

- `/home/main/.codex/skills/addon-superpowers-hitl-execution/SKILL.md`
- `/home/main/.codex/skills/addon-superpowers-hitl-execution/references/session-protocol.md`

役割:

- `writing-plans` 後の Human in the Loop 実行プロトコル
- 毎回 `design -> plan -> progress-summary` を読み、短いセッションで続きから進める
- scope を狭く保ち、終了時に次の一手を残す

向いている場面:

- `続きから進めてください`
- `今回は test だけ`
- `今日はここまで`
- `docs 反映だけやってください`

### 4. `addon-superpowers-auto-progress`

ファイル:

- `/home/main/.codex/skills/addon-superpowers-auto-progress/SKILL.md`
- `/home/main/.codex/skills/addon-superpowers-auto-progress/scripts/update_progress_summary.py`

役割:

- `progress-summary` をローカルファイルとして自動作成・自動更新する
- ユーザーが毎回進捗メモを意識しなくてよいようにする

保持するもの:

- 現在状態
- 完了したこと
- 残り
- 次の一手
- 検証結果
- doc sync 状態
- session log

### 5. `addon-superpowers-concurrent-progress`

ファイル:

- `/home/main/.codex/skills/addon-superpowers-concurrent-progress/SKILL.md`

役割:

- shared `progress-summary` を複数 agent が触っても壊れないようにする
- `update_progress_summary.py` のファイルロック機能と `--agent` を前提に運用する

向いている場面:

- マルチエージェント
- 並列タスク
- 同一テーマを複数レーンで進めるとき

### 6. `addon-superpowers-task-board`

ファイル:

- `/home/main/.codex/skills/addon-superpowers-task-board/SKILL.md`
- `/home/main/.codex/skills/addon-superpowers-task-board/scripts/manage_task_board.py`

役割:

- タスクを静的リストではなく状態つきボードとして管理する
- `ready / in_progress / blocked / done` を持つ
- `depends_on` と `agent` を持ち、次にやるべき task を動的に再評価する

保持ファイル:

- machine state
  - `docs/superpowers/<theme>-task-board.json`
- human view
  - `docs/superpowers/<theme>-task-board.md`

向いている場面:

- タスク順序が固定ではないとき
- 途中で block が入りうるとき
- マルチエージェントで task を claim したいとき

## 既存 `superpowers` との違い

### 既存 `superpowers` が主に扱うもの

- `brainstorming`
  - 設計を固める
- `writing-plans`
  - 実装計画へ落とす
- `test-driven-development`
  - RED-GREEN-REFACTOR
- `requesting-code-review`
  - レビュー確認
- `verification-before-completion`
  - 最終検証
- `finishing-a-development-branch`
  - 完了判断

### 今回のアドオンが補うもの

- `artifact-planning`
  - 最初に何の資料を作るか
- `hitl-execution`
  - セッション継続の実行手順
- `auto-progress`
  - progress-summary の自動更新
- `dual-track-documentation`
  - working docs と formal docs の同期
- `concurrent-progress`
  - shared progress の競合防止
- `task-board`
  - タスク状態と依存関係、担当管理

### 一言でいう違い

- 既存 `superpowers`
  - 設計と実装の質を高める
- 今回のアドオン
  - 継続性、可視性、再開性、並列性を高める

## 実際の使い方

### 単一エージェントの基本フロー

1. `addon-superpowers-artifact-planning`
- 何の資料が必要か決める

2. `brainstorming`
- 設計を固める

3. `writing-plans`
- 実装計画を作る

4. `addon-superpowers-auto-progress`
- `progress-summary` を初期化する

5. `addon-superpowers-hitl-execution`
- 短いセッションを回す

6. `addon-superpowers-dual-track-documentation`
- 節目で正式文書へ反映する

7. `verification-before-completion`
- テストと起動確認を行う

### マルチエージェント版のフロー

1. `artifact-planning`
2. `brainstorming`
3. `writing-plans`
4. `task-board` 初期化
5. `auto-progress` 初期化
6. 各 agent が `ready` task を claim
7. 各 agent が task を `done` または `blocked` に更新
8. 依存解消後に新しい `ready` task が開く
9. `progress-summary` は coordinator が現在地を要約
10. 最後に verification と docs sync

## タスクが途中で変わる場合の扱い

### 前提

最初に作った `plan` は固定の確定表ではない。
実務では、途中で次の変化が普通に起きる。

- タスク追加
- タスク削除
- タスク内容変更
- 順序変更
- block 発生
- 設計変更

したがって、この拡張フローは「最初のタスク分解が最後まで不変」であることを前提にしていない。

### 基本原則

- `design`
  - 何を作るか
- `plan` または `task-board`
  - 今のタスク分解と依存
- `progress-summary`
  - 今回の現在地

この 3 つを更新可能なものとして扱う。

### 変更の種類ごとの対応

#### 1. タスク追加

対応:

- 小さな追加なら `plan` に追記する
- 順序や依存に影響するなら `task-board` に task を追加する
- `progress-summary` の `Remaining` と `Next Step` を更新する

#### 2. タスク削除

対応:

- 不要になった理由を `plan` か `task-board` の note に残す
- 消すだけでなく「なぜ不要になったか」を外に出す
- `progress-summary` からも未完了項目を整理する

#### 3. タスク内容変更

対応:

- 実装詳細レベルなら `plan` を直す
- 影響ファイルや責務が変わるなら `task-board` の paths / notes も更新する
- `Next Step` は再評価する

#### 4. 順序変更

対応:

- 直列の plan だけで無理に表現しない
- `task-board` がある場合は `ready / blocked / done` を再計算する
- `progress-summary` の `Next Step` は候補として更新する

#### 5. block 発生

対応:

- `task-board` では `blocked` にする
- block 理由を notes に残す
- 別の `ready` task があればそちらへ進む
- `progress-summary` にも「止まった理由」と「代わりに進めるもの」を書く

#### 6. 設計変更

対応:

- いったん実装を止める
- `design` を更新する
- その後 `plan` を引き直す
- 既存 task がずれるなら `task-board` も更新する

### `Next Step` の扱い

`progress-summary` の `Next Step` は固定命令ではない。
これは「前回時点の最有力候補」である。

次回セッション開始時には毎回、次を見て再評価する。

- 最新の test 結果
- `blocked` の有無
- `ready` task の有無
- docs 未反映状態
- 設計変更の有無

つまり、`Next Step` は便利だが source of truth ではない。
source of truth は、更新された `plan` または `task-board` である。

### 小さい一直線の開発での扱い

`task-board` を使わない小さな開発でも、途中変更には対応できる。

その場合は:

- 軽微な変更
  - `plan` を修正する
- 今回の現在地
  - `progress-summary` を修正する
- 設計変更
  - `design` に戻る

この 3 段だけでも十分である。

### 中規模以上での扱い

順序変更や block が増える場合は `task-board` を使う方が自然である。

理由:

- `ready` task を機械的に出せる
- 複数 agent の担当が分かる
- block と release を追える
- 「次にやるべき task」が固定順ではなく状態から決まる

### 実務上のポイント

- 変わること自体は問題ではない
- 変わったのに `design / plan / progress-summary` が古いままなのが問題
- 途中変更が起きたら、実装を進める前にまず文書状態を更新する

## 変更が起きたときの簡単な判断表

- 実装の細部だけ変わった
  - `plan` を直す
- 順番だけ変わった
  - `task-board` の状態を直す
- block が出た
  - `blocked` にして別の `ready` へ進む
- 設計の前提が変わった
  - `design` に戻る
- 次に何をやるか迷う
  - `progress-summary` を見てから `task-board` の `ready` を確認する

## `progress-summary` と `task board` の違い

### `progress-summary`

役割:

- 今回の現在地を人間向けに要約する
- 次回セッションの入口を作る

向いている情報:

- 今の状態
- 完了したこと
- 残っていること
- 次の一手
- 検証結果

### `task board`

役割:

- どの task が `ready` かを機械的に出す
- 依存と状態を持つ
- agent ごとの担当を明示する

向いている情報:

- task id
- status
- depends_on
- agent
- blocked reason

### 使い分け

- 人間が「どこまで進んだか」を知る
  - `progress-summary`
- システムが「次にどの task を取るか」を決める
  - `task board`

## どこまで実証したか

### 1. 極小の HITL 実装

対象:

- `tiny counter`

確認したこと:

- 短いセッション反復
- `progress-summary` による再開
- docs-only セッション

関連文書:

- `docs/16_小規模実地検証_tiny_counter.md`

### 2. 既存設計書を使った別フォルダ再構築

対象:

- `jra-flow-hitl-sim`

確認したこと:

- 既存設計書を入力に使えるか
- formal docs / working docs / source / tests を別フォルダに再構成できるか
- `GET /meetings/{date}/{course}` を最小スコープで実装できるか

関連フォルダ:

- `/mnt/d/develop/jra-flow-hitl-sim`

### 3. 小規模でも薄くない成果物を持てるか

対象:

- `hitl-proper-counter-sim`

確認したこと:

- 小規模でも `README` だけにせず、`UI設計`、`API仕様`、`設計判断` まで持てるか
- docs を厚めにしても fat になりすぎないか

関連フォルダ:

- `/mnt/d/develop/hitl-proper-counter-sim`

### 4. task state + multi-agent の最小デモ

対象:

- `multi-agent-taskboard-sim`

確認したこと:

- task board による `ready` 判定
- `agent-api`、`agent-test`、`agent-review` の 3 レーン
- `depends_on` 解消後に verification task が `ready` になること

関連フォルダ:

- `/mnt/d/develop/multi-agent-taskboard-sim`

## 実務でのおすすめ運用

### 小規模アプリ

- `artifact-planning`
- `brainstorming`
- `writing-plans`
- `auto-progress`
- `hitl-execution`
- 必要に応じて `dual-track-documentation`

### 小さく一直線の開発

対象:

- 単機能ツール
- 極小 API
- 画面 1 枚の小さなデモ
- 依存関係がほぼ固定の小機能追加

使うもの:

- `artifact-planning`
- `brainstorming`
- `writing-plans`
- `auto-progress`
- `hitl-execution`

原則:

- `task-board` は使わない
- `plan` をほぼ固定順で進める
- `progress-summary` だけで現在地を持つ
- ユーザーは毎回「今回はここまで」と scope だけ指定する

この形で十分な条件:

- タスクの順番がほぼ変わらない
- `blocked` や担当変更がほぼ起きない
- マルチエージェント並列をしない

この形で弱くなる条件:

- 実装途中で順序変更が頻発する
- docs 反映を別レーンで進めたい
- 複数 task を同時進行したい

### 中規模アプリ

- 上記に加えて `task-board`
- サブテーマごとに board を分ける
- `progress-summary` はテーマ単位
- `task board` はサブテーマ単位

### 並列開発やマルチエージェント

- `concurrent-progress`
- `task-board`
- shared summary は narrative 用
- 実際の担当割り当ては board で持つ

## いま残っている課題

- `blocked` と `reassignment` の実地デモはまだ薄い
- task board と `writing-plans` の出力をさらに自然に接続したい
- `dual-track-documentation` との連動をもう少し強めたい
- 自律モードまで行くなら別途 `execution contract` が必要

## 結論

今回のアドオン群で、`superpowers` は次のように拡張された。

- 設計品質を高めるフレームワーク
  - 既存 `superpowers`
- そこに継続性、再開性、文書育成、タスク状態管理、並列性を加えたもの
  - 今回のアドオン群

つまり、今ある形は「`superpowers` を捨てた別物」ではなく、
`superpowers` を Human in the Loop 実務へ寄せた拡張レイヤーと考えるのが正しい。

一方で、常に全部を使う必要はない。

- 小さく一直線
  - `plan + progress-summary`
- 継続セッションが必要
  - `hitl-execution + auto-progress`
- docs を育てたい
  - `dual-track-documentation`
- 順序が変わる
  - `task-board`
- 並列で進める
  - `task-board + concurrent-progress`

このように、規模と複雑さに応じて段階的に足すのが基本方針である。
