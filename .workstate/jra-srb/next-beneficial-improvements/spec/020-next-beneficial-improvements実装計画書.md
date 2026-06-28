# 次に有益な改修候補 実装計画書

## 推奨優先順位

### P0: MCP / API 入力正規化

目的:
日本語や自然な表記から、既存 API が要求する `course`, `race_no`, `bet_type`, `combination` に変換できるようにする。

背景:
`/mcp` は公開済みだが、利用者やエージェントは「中山 11R 3連単」のように指定することが多い。現状は `nakayama`, `11`, `trifecta` を知っている前提になっている。

主なタスク:

- `src/jra_srb/normalization.py` を追加する。
- 開催場 alias を定義する。
  - `中山` -> `nakayama`
  - `阪神` -> `hanshin`
  - `東京` -> `tokyo`
- 券種 alias を定義する。
  - `単勝` -> `win`
  - `馬連` -> `quinella`
  - `ワイド` -> `wide`
  - `馬単` -> `exacta`
  - `3連複` / `三連複` -> `trio`
  - `3連単` / `三連単` -> `trifecta`
- `11R`, `11レース`, `第11レース` から `race_no=11` を抽出する。
- 正規化結果を返す API または service 関数を追加する。
- FastAPI / MCP から使える導線を追加する。

完了条件:

- 日本語開催場名が英字 course に変換される。
- 日本語券種名が `bet_type` に変換される。
- `11R` 形式が `race_no=11` に変換される。
- 変換不能な入力は `400` 相当の明確なエラーになる。
- unit test と API test が追加される。

### P1: Enum ベースの入力バリデーション

目的:
API 利用者が OpenAPI / Swagger UI で許容値を理解できるようにし、不正入力を早く落とす。

主なタスク:

- `CourseCode` と `BetType` の Enum を追加する。
- API パラメータの `course` と `bet_type` に Enum を適用する。
- `race_no` に `ge=1`, `le=12` を設定する。
- `race_id` の形式検証を追加する。
- 既存 `BadRequestError` / `ResourceNotFoundError` との責務を整理する。

完了条件:

- OpenAPI に `course` と `bet_type` の候補が出る。
- 不正な `course`, `bet_type`, `race_no` が 422 または 400 で返る。
- 既存正常系 API のレスポンスは変わらない。

### P1: 過去結果収集 CLI

目的:
`PastResultCollector` をコードからではなくコマンドで実行できるようにする。

主なタスク:

- `src/jra_srb/cli.py` を追加する。
- `collect-results` コマンドを追加する。
- `--from-date`, `--to-date`, `--courses`, `--output`, `--retries` を受け取る。
- `pyproject.toml` に console script を定義する。
- JSONL 保存、skip-by-`race_id`, retry を既存部品で使う。

完了条件:

- `uv run jra-srb collect-results --from-date 2026-03-22 --to-date 2026-03-22 --courses nakayama --output data/results.jsonl` の形で実行できる。
- CLI 引数不正時に分かりやすく失敗する。
- service を fake に差し替えたテストで JSONL 出力まで検証できる。

### P2: 構造化ログ

目的:
運用時に失敗箇所を追いやすくする。

主なタスク:

- request 単位のログを追加する。
- provider 取得ログを追加する。
- 失敗時に `course`, `race_id`, `race_no`, `cname`, `url`, `status_code` を出す。
- ログ設定を標準 logging で追加する。

完了条件:

- 正常時と異常時の主要イベントがログに出る。
- fixture test でログ出力の最低限を検証できる。
- レスポンス本文に内部詳細を出しすぎない。

### P2: 保存済み結果の読み出し API

目的:
JSONL に保存した過去結果を API から再利用できるようにする。

主なタスク:

- `JsonlRaceResultStorage` に read 系メソッドを追加する。
- `race_id` 指定取得を追加する。
- 日付範囲・開催場フィルタを追加する。
- 保存済み結果用 API を追加する。

完了条件:

- `GET /stored/results/{race_id}` で保存済み結果を取得できる。
- 日付範囲検索ができる。
- JSONL が壊れている行の扱いが定義されている。

### P3: ヘルスチェック強化

目的:
プロセス生存だけでなく、外部取得系の状態を確認できるようにする。

主なタスク:

- `/health` は軽量な生存確認として維持する。
- `/health/upstream` などを追加する。
- timeout を短くし、過剰アクセスにならない確認方法にする。

完了条件:

- upstream 確認失敗時に API プロセス自体の生存とは区別できる。
- 通常の `/health` は外部通信しない。

### P3: 永続キャッシュ / 保存先抽象の拡張

目的:
再起動後も再取得コストを抑え、JSONL 以外の保存先へ拡張しやすくする。

主なタスク:

- `ResultStorage` の read/write 契約を見直す。
- SQLite などの軽量 backend を検討する。
- キャッシュと収集結果保存を混同しない設計にする。

完了条件:

- JSONL 既存挙動を壊さず backend を増やせる。
- API / batch から同じ契約で使える。

## 推奨着手順

1. P0: MCP / API 入力正規化
2. P1: Enum ベースの入力バリデーション
3. P1: 過去結果収集 CLI
4. P2: 構造化ログ
5. P2: 保存済み結果の読み出し API
6. P3: ヘルスチェック強化
7. P3: 永続キャッシュ / 保存先抽象の拡張

最初に P0 を推す理由は、既存 API と MCP の価値を最も短い距離で上げられるため。JRA 取得ロジック本体に触る範囲が小さく、テストで期待値を固定しやすい。
