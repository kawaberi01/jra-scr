# 小規模アプリでのHITLシミュレーション

## 目的

この文書は、`Human in the Loop` モードが実際に小さめのアプリケーション開発でどう回るかを、具体的な題材でシミュレーションするものである。

今回は、大きなアプリではなく、個人開発で現実的に作りそうな小規模 Web アプリを題材にする。

## 題材

### 作るもの

`1日1回チェックする習慣トラッカー`

### 機能

- 習慣を追加する
- 習慣一覧を表示する
- 今日やったかどうかをチェックで切り替える
- 今日の達成数を表示する

### この題材を選んだ理由

- GUI がある
- API も少しある
- 認証や課金のような重い要素がない
- 1 画面中心なので小さい
- それでも「設計」「計画」「短い実装セッション」「docs 反映」の流れを試せる

## 想定構成

- フロントエンド:
  - 一覧画面 1 枚
  - 追加フォーム
  - チェックボックス
- バックエンド:
  - 習慣一覧取得 API
  - 習慣追加 API
  - 今日の達成状態更新 API

## この題材で必要と判断する資料

### 正式文書

- `docs/01_プロジェクト概要.md`
- `docs/02_アーキテクチャ.md`
- `docs/03_設計判断.md`
- `docs/04_利用ガイド.md`
- `docs/05_UI設計.md`
- `docs/06_API仕様.md`

### 作業文書

- `docs/superpowers/specs/YYYY-MM-DD-habit-tracker-design.md`
- `docs/superpowers/plans/YYYY-MM-DD-habit-tracker-implementation-plan.md`
- `docs/superpowers/YYYY-MM-DD-habit-tracker-progress-summary.md`

## 前提フロー

使うスキルは次とする。

1. `addon-superpowers-artifact-planning`
2. `brainstorming`
3. `using-git-worktrees`
4. `writing-plans`
5. `addon-superpowers-hitl-execution`
6. `addon-superpowers-auto-progress`
7. `requesting-code-review`
8. `addon-superpowers-dual-track-documentation`
9. `verification-before-completion`
10. `finishing-a-development-branch`

## 全体設計フェーズ

### セッション 1: 成果物計画

ユーザー:

> 小さめの Web アプリを作ります。  
> 習慣トラッカーです。  
> まず必要資料を整理してください。

エージェント:

- GUI と API があるので `UI設計` と `API仕様` を含める
- 正式文書と作業文書を分ける
- progress-summary を初期化対象にする

この時点で決まること:

- 正式文書の一覧
- 作業文書の一覧
- docs 反映先

### セッション 2: 設計

ユーザー:

> では設計に入ってください。  
> 1 画面中心で、習慣の追加と今日の達成チェックができればよいです。

エージェント:

- 一覧画面中心の UI を提案
- API は 3 本程度に絞る
- 状態管理は単純に保つ
- 設計書を作る

この時点でできるもの:

- 設計書
- 画面構成の方向
- API の基本方針

### セッション 3: 実装計画

ユーザー:

> 設計が固まったら実装計画に落としてください。

エージェント:

- worktree を作る
- タスクを小さく分解する
- progress-summary を初期化する

分解されるタスク:

1. 一覧取得 API
2. 習慣追加 API
3. 達成切替 API
4. 一覧画面 UI
5. 追加フォーム UI
6. 達成数表示
7. docs 同期

## 実装フェーズ

ここから先は、一気通貫ではなく短いセッションを何度も回す。

## セッション 4: 一覧取得 API

ユーザー:

> 続きから進めてください。  
> まず一覧取得 API だけ進めてください。

エージェント:

- progress-summary を読む
- `一覧取得 API` を今回のセッションスコープに設定する
- 失敗テストを書く
- 最小実装を入れる
- auto-progress で更新する

この回の終了条件:

- 一覧取得 API のテストが通る

残る next step:

- 習慣追加 API に進む

## セッション 5: 習慣追加 API

ユーザー:

> 続きから進めてください。  
> 次は追加 API を進めてください。

エージェント:

- progress-summary の `Next Step` を確認
- 追加 API だけ実装する
- focused test を通す
- auto-progress で更新する

この回でまだやらないこと:

- UI
- docs 更新

## セッション 6: 達成切替 API

ユーザー:

> 続きから進めてください。  
> 達成チェックの切替 API までやってください。

エージェント:

- API を 1 本だけ追加する
- 一覧 API と整合しているか確認する
- review が必要なら差し込む
- auto-progress で更新する

この回が終わると:

- バックエンド API が 3 本そろう

## セッション 7: API docs 同期

ユーザー:

> ここまでの API を docs に反映してください。

エージェント:

- `addon-superpowers-dual-track-documentation` を使う
- `docs/06_API仕様.md` を更新する
- `docs/02_アーキテクチャ.md` と `docs/03_設計判断.md` に最低限反映する
- auto-progress で `Doc Sync Status` を更新する

この回は docs だけのセッションでもよい。

## セッション 8: 一覧画面 UI

ユーザー:

> 続きから進めてください。  
> 一覧画面だけ作ってください。

エージェント:

- 一覧表示の UI を作る
- loading / empty / normal の 3 状態を扱う
- API と接続する
- auto-progress で更新する

## セッション 9: 追加フォーム UI

ユーザー:

> 次は追加フォームだけ作ってください。

エージェント:

- 入力欄と追加ボタンを作る
- submit 後の更新をつなぐ
- フォーム挙動を確認する
- auto-progress で更新する

## セッション 10: 達成チェック UI

ユーザー:

> チェックボックスで達成切替できるようにしてください。

エージェント:

- チェックボックス UI を追加
- 達成切替 API と接続
- 一覧再描画を確認
- auto-progress で更新する

## セッション 11: UI レビュー

ユーザー:

> ここでいったん UI と API のつながりをレビューしてください。

エージェント:

- `requesting-code-review` を使う
- 状態管理、責務分離、エラー表示を確認する
- 必要なら局所修正する
- auto-progress で更新する

## セッション 12: UI docs 同期

ユーザー:

> ここまでの UI を docs に反映してください。

エージェント:

- `docs/05_UI設計.md` を更新する
- `docs/04_利用ガイド.md` を更新する
- auto-progress で `Doc Sync Status` を更新する

## セッション 13: 今日はここまで

ユーザー:

> 今日はここまでなので、次回すぐ再開できるようにしてください。

エージェント:

- 新しいタスクは始めない
- auto-progress で終了 checkpoint を残す
- `Next Step` を 1 つだけ残す

例えば残る next step:

- 今日の達成数表示を実装する

## 実際にこのシミュレーションで分かること

### 1. 小さいアプリでも全体設計は先に必要

アプリ自体は小さいが、何の資料を残し、何をどこまで docs に上げるかは最初に決めた方がよい。

### 2. 実装は一気通貫でなく、短いセッションの繰り返しになる

この規模でも、自然な進め方は:

- API 1 本
- UI 1 画面
- docs 同期 1 回
- review 1 回

のように分かれる。

### 3. progress-summary は裏で回っていればよい

ユーザーは毎回 `progress-summary` を意識しなくてもよいが、フローの裏では毎回更新されている必要がある。

### 4. docs-only セッションが普通に発生する

コードだけではなく、API 反映や UI 設計反映だけを行うセッションも自然に存在する。

## 結論

小規模アプリでも、Human in the Loop の現実的な運用は十分成立する。

今回の題材としては、`1日1回チェックする習慣トラッカー` がちょうどよい。

理由は次のとおりである。

- 小さい
- GUI と API の両方がある
- 実装を短いセッションに分けやすい
- docs 反映の対象も分かりやすい

この規模でフローが回るなら、同じ考え方を少し大きい個人開発にも拡張しやすい。
