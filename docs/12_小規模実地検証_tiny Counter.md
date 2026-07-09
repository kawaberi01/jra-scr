# 小規模実地検証: tiny counter

## 目的

Human in the Loop フローが本当に回るかを確認するため、極小の Web アプリを実際に作成し、短いセッションで進めて検証した結果をまとめる。

## 検証の観点

今回の検証では、単に tiny counter が動くかではなく、次の 2 つを分けて確認する。

1. 全体設計から入るフローが成立するか
2. その後の短い実装セッション反復が成立するか

前回の版では 2 に寄りすぎていたため、この版では 1 も明示する。

## 今回作ったもの

題材:

- `Tiny Counter`

機能:

- 現在値表示
- `+1` ボタン
- `Reset` ボタン

追加したコード:

- [app.py](/mnt/d/develop/jra-scr/src/hitl_tiny_counter/app.py)
- [__init__.py](/mnt/d/develop/jra-scr/src/hitl_tiny_counter/__init__.py)
- [test_hitl_tiny_counter.py](/mnt/d/develop/jra-scr/tests/test_hitl_tiny_counter.py)

関連文書:

- [design](/mnt/d/develop/jra-scr/docs/superpowers/specs/2026-03-22-tiny-counter-design.md)
- [plan](/mnt/d/develop/jra-scr/docs/superpowers/plans/2026-03-22-tiny-counter-implementation-plan.md)
- [progress-summary](/mnt/d/develop/jra-scr/docs/superpowers/2026-03-22-tiny-counter-progress-summary.md)

## どう進めたか

今回は、次の 4 フェーズで進めた。

1. 成果物計画
2. 全体設計
3. 実装計画
4. 短い実装セッション反復

つまり、検証対象は「短いセッション」だけではなく、その前にある全体設計フェーズも含む。

## フェーズ 1: 成果物計画

この tiny counter を題材にしたとき、まず次を作ると決めた。

### 正式文書

- `README.md`

今回は極小検証なので、正式文書の更新は `README` のみに絞った。

### 作業文書

- design
- plan
- progress-summary

### この段階で確認したこと

- このアプリは GUI + API の極小構成
- 認証や永続化がないので、`セキュリティと運用注意` や `Runbook` は今回は不要
- ただし、HITL 検証のために design / plan / progress-summary の 3 点セットは必要

## フェーズ 2: 全体設計

全体設計として次を定義した。

### アプリの目的

- 1 画面で値を表示し、増加とリセットができること

### 画面設計

- 単一画面
- 現在値表示
- `+1` ボタン
- `Reset` ボタン

### API 設計

- `GET /api/value`
- `POST /api/increment`
- `POST /api/reset`

### 状態設計

- 状態はメモリ上の整数 1 個
- 永続化しない

### 実装方針

- FastAPI の独立アプリとして `src/hitl_tiny_counter` に置く
- HTML は直接返す
- 画面更新は軽い JavaScript で行う

この段階の成果物:

- [design](/mnt/d/develop/jra-scr/docs/superpowers/specs/2026-03-22-tiny-counter-design.md)

## フェーズ 3: 実装計画

全体設計をもとに、次のタスクへ分解した。

1. progress-summary 初期化
2. バックエンド API とテスト
3. HTML UI
4. 起動確認
5. docs 反映

この段階の成果物:

- [plan](/mnt/d/develop/jra-scr/docs/superpowers/plans/2026-03-22-tiny-counter-implementation-plan.md)
- [progress-summary](/mnt/d/develop/jra-scr/docs/superpowers/2026-03-22-tiny-counter-progress-summary.md)

## フェーズ 4: 短い実装セッション反復

ここから先は、一気通貫ではなく短いセッションとして進めた。

### セッション 1

やったこと:

- tiny counter の API と画面の最小実装
- テスト追加
- focused test 実行

結果:

- `uv run --extra dev pytest tests/test_hitl_tiny_counter.py -q`
- `1 passed`

### セッション 2

やったこと:

- README に tiny demo の起動方法を追記
- `uvicorn` で実際に起動
- HTTP で画面と API を確認
- progress-summary を次状態へ更新

### セッション 3 として残したもの

今回の検証では、あえて次の一手を残した。

- 検証結果を文書化して、このフローが回るかを評価する

つまり、tiny counter 開発自体は小さいが、HITL フローとしては「次回セッションへ自然に続く状態」が残っていることを確認対象にした。

確認内容:

- `GET /`
- `GET /api/value`
- `POST /api/increment`
- `POST /api/reset`

結果:

- HTML 画面が返った
- 値取得が返った
- increment で `{"value":1}`
- reset で `{"value":0}`

## 実際に確認したコマンド

### テスト

```bash
uv run --extra dev pytest tests/test_hitl_tiny_counter.py -q
```

結果:

- `1 passed in 1.18s`

### 起動

```bash
uv run uvicorn hitl_tiny_counter.app:app --host 127.0.0.1 --port 8010
```

### HTTP 確認

```bash
curl -s http://127.0.0.1:8010/
curl -s http://127.0.0.1:8010/api/value
curl -s -X POST http://127.0.0.1:8010/api/increment
curl -s -X POST http://127.0.0.1:8010/api/reset
```

## Human in the Loop フローで回ったか

### 結論

この規模では回った。

ただし、正確には次の条件付きで回った。

1. 最初に design と plan がある
2. progress-summary が初期化されている
3. セッションごとにスコープを小さく切る
4. セッション終了時に progress-summary を更新する

## どこが良かったか

### 1. 全体設計から短セッションへ自然に落とせた

今回の tiny counter は、最初に

- 目的
- 画面
- API
- 状態
- 実装方針

を定義したうえで、そこから短い実装セッションへ落とせた。

これにより、「全体設計が最後に乗っていない」という弱さは避けられる形になった。

### 2. 小タスクで区切れた

今回の tiny counter では、自然に次の 2 セッションへ分かれた。

- 実装とテスト
- 起動確認と docs 反映

これは Human in the Loop の想定に合っていた。

### 3. progress-summary が再開の軸になった

ユーザーが毎回詳細を思い出さなくても、`progress-summary` に次の一手が残る構造は成立した。

### 4. docs-only に近いセッションも作れた

2 セッション目は、コード追加よりも README 反映と起動確認が中心だった。これは現実の運用に近い。

## どこがまだ弱いか

### 1. progress-summary 更新はまだ明示的に呼んでいる

ユーザーが直接書く必要はないが、エージェントはまだ更新スクリプトを明示的に呼んでいる。

### 2. 並列更新には弱い

別の検証で見えたとおり、同一 `progress-summary` への並列更新には競合リスクがある。

### 3. スコープの切り方はまだエージェントの判断に依存する

「今日は何だけ進めるか」は、まだスキルのプロトコルを守る前提で回っている。

## 判定

### このフローで回るか

小規模アプリでは回る。

### 本当に回るか

次の意味では「はい」である。

- 小さなアプリを実際に作れた
- テストが通った
- 起動確認も通った
- セッションを分けて進められた
- progress-summary を使って続き前提の状態を残せた

### ただし条件付き

次が必要である。

- セッションごとにスコープを小さく固定する
- progress-summary を裏で必ず更新する
- 同じ progress-summary を並列更新しない

## 今回の検証でまだ浅い部分

前回の版よりは改善したが、まだ完全ではない点もある。

### 1. 正式文書の層は最小化している

今回は tiny counter が極小すぎるため、正式文書は `README` しか更新していない。

したがって、

- `アーキテクチャ`
- `設計判断`
- `利用ガイド`

まで分かれた中規模フローの完全検証にはなっていない。

### 2. 複数サブテーマへの分解は試していない

今回のアプリは小さすぎるため、

- 認証
- 一覧
- 編集
- 通知

のようなサブテーマ分解までは発生していない。

### 3. docs 同期の判断はまだ単純

今回は `README` だけで済んでおり、正式文書の取捨選択の難しさまでは試していない。

## 総評

今回の tiny counter 検証に限れば、Human in the Loop フローは机上の空論ではなく、実際に動かせる形になっている。

特に、

- `addon-superpowers-hitl-execution`
- `addon-superpowers-auto-progress`

の組み合わせは、「続きから少しずつ進める」使い方に対して有効だった。

一方で、「全体設計から正式文書群まで含めて完全に回るか」の検証としては、今回の tiny counter はまだ最小寄りである。

したがって、今回の結論は次の 2 段階で整理するのが正しい。

1. 小規模の実装反復フローとしては成立した
2. 中規模相当の文書運用まで含む完全検証はまだ次の課題である
