# HITLスキル再設計と実シミュレーション結果

## 目的

この文書は、`Human in the Loop` を「全自動実装」ではなく「短いセッションの続きから自然に再開できる運用」として再定義し、そのためにスキルを作り直した結果と、実際に行った最小シミュレーションの結果をまとめる。

## 今回の方針

今回の目的は次のとおりである。

- AI に最後まで勝手に走らせることではない
- 人が短いセッションで小さな指示を出しながら進める
- そのたびに前回の続きから自然に再開できる
- そのための状態保持を `progress-summary` が担う

つまり、目指したのは `autonomous mode` ではなく、**再開しやすい Human in the Loop 実行プロトコル** である。

## 作り直したスキル

### 1. HITL 実行プロトコル

- [SKILL.md](/home/main/.codex/skills/addon-superpowers-hitl-execution/SKILL.md)
- [session-protocol.md](/home/main/.codex/skills/addon-superpowers-hitl-execution/references/session-protocol.md)

変更の要点:

- セッション開始時に必ず `design`、`plan`、`progress-summary` を読む
- 毎回 1 つの小スコープだけを実行する
- 設計に戻るべき条件を明示する
- セッション終了時に必ず状態を閉じる
- `addon-superpowers-auto-progress` を裏方として使う前提を明示する

### 2. progress-summary 自動更新

- [SKILL.md](/home/main/.codex/skills/addon-superpowers-auto-progress/SKILL.md)
- [update_progress_summary.py](/home/main/.codex/skills/addon-superpowers-auto-progress/scripts/update_progress_summary.py)

変更の要点:

- Git 非依存
- ローカルファイルのみで状態を更新
- `Session Log` を追記
- `Current State` と `Next Step` を一貫形式で保持

## 実際に使った最小デモ

### 作成した作業文書

- [design](/mnt/d/develop/jra-scr/docs/superpowers/specs/2026-03-22-hitl-min-demo-design.md)
- [plan](/mnt/d/develop/jra-scr/docs/superpowers/plans/2026-03-22-hitl-min-demo-implementation-plan.md)
- [progress-summary](/mnt/d/develop/jra-scr/docs/superpowers/2026-03-22-hitl-min-demo-progress-summary.md)

### デモの題材

- `GET /tasks` のハンドラ追加を模した最小タスク

### デモで想定した口頭指示

1. 初回:
   - 「このテーマを始めてください」
2. 続き:
   - 「続きから進めてください」
3. もう一回続き:
   - 「続きから進めてください」
4. 終了:
   - 「今日はここまでなので次回再開できるようにしてください」

## 実際にやったシミュレーション

### Step 1. 初期化

`auto-progress` を使って `progress-summary` を初期化した。

結果:

- 必要セクションが自動生成された
- `design` と `plan` の参照が入った
- `Next Step` が 1 つ入った

### Step 2. セッション 1

想定:

- `続きから進めてください`

処理:

- `progress-summary` を読み、`Next Step` を確認
- 一覧 API の失敗テスト準備まで進めた体で更新

結果:

- `Current State` が更新された
- `Session Log` に 2 件目が追加された
- 次回の `Next Step` が切り替わった

### Step 3. セッション 2

想定:

- `続きから進めてください`

処理:

- 再び `progress-summary` を読み、次の一手だけ進めた
- 一覧 API の失敗テスト実装とハンドラ着手まで進めた体で更新

結果:

- 再開して次のタスクへ進める形になった
- `Session Log` がさらに増えた

### Step 4. セッション終了

想定:

- `今日はここまでなので次回再開できるようにしてください`

処理:

- 現在地を checkpoint として残す更新を実行

結果:

- `Current State` は「今日はここまで」の状態に変わった
- 次回の `Next Step` が残った

## うまくいったこと

### 1. 進捗ファイルを起点に再開できた

毎回 `progress-summary` を読めば、次にやる小タスクが分かる状態は作れた。

### 2. Human in the Loop の粒度に合っていた

今回のデモは、機能を一気に終わらせず、短いセッションで少しずつ進める形として成立した。

### 3. Git 非依存でも回せた

Git に頼らなくても、ローカルファイルだけで継続状態を保持できた。

### 4. ユーザーが `progress-summary` の書式を意識しなくてよい

更新はスクリプト側の責務になり、ユーザーは「続きから」「今日はここまで」だけでよい形に近づいた。

## うまくいかなかったこと

### 1. 同じ `progress-summary` への並列更新は壊れる

途中で `セッション2更新` と `セッション3終了更新` を同時に実行したところ、同じファイルへの更新が競合した。

これは Human in the Loop としては重要な制約である。

結論:

- `progress-summary` 更新は直列で行うべき
- 同一ファイルへの並列更新は避けるべき

### 2. 同じ終了処理を再実行するとログが重複する

競合確認後に終了処理を直列でやり直したため、`Session Log` に重複記録が残った。

これは最小版の限界であり、現在のスクリプトには重複防止機構がない。

### 3. 次の一手はまだ完全自動ではない

今回の `Next Step` は、エージェントが文を決めてスクリプトに渡している。

つまり、

- ユーザーは意識しなくてよい
- ただしエージェントはまだ考えている

という状態である。

## この結果から言えること

### 成功判定

次の意味では成功している。

- Human in the Loop の「続きから進める」は成立した
- `progress-summary` が実際にセッション継続の土台になった
- 全自動モードにせず、短いセッション運用に寄せた形で回せた

### まだ足りない点

次の意味では、まだ改善余地がある。

- 並列更新耐性がない
- 重複更新防止がない
- `Next Step` は補助的にまだ人間知能を使っている

## 結論

今回の再設計で、`Human in the Loop` は「全自動実装」ではなく「続きから自然に再開できる短セッション実行」としてかなり現実的になった。

特に、

- `addon-superpowers-hitl-execution`
- `addon-superpowers-auto-progress`

の組み合わせにより、**続きから進める感じ** は実際に作れた。

一方で、完全に実運用へ寄せるには次の改善が有効である。

1. `progress-summary` 更新の直列化を明文化する
2. 同一内容の重複追記防止を入れる
3. `Next Step` の下書き補助を加える

したがって、今回の結論は次のとおりである。

- Human in the Loop 用の再開フローとしては成立した
- ただし最小版なので、競合と重複更新には弱い
- 方向性は正しく、次は堅牢化の段階である
