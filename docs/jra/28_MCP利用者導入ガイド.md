# JRA Race MCP 利用者導入ガイド

## 文書情報

| 項目 | 内容 |
| --- | --- |
| 文書区分 | MCP 利用者向け正式導入資料 |
| 対象システム | `jra-srb` / `JRA Race MCP` |
| 対象者 | MCP クライアント利用者、クライアント設定担当者、ローカル API 運用者 |
| 対象環境 | Windows、Python 3.12 以上、`uv` |
| MCP transport | Streamable HTTP |
| MCP endpoint | `http://127.0.0.1:8000/mcp` |
| 認証 | なし。ローカル利用限定 |
| 文書版 | 1.0 |
| 初版 | 2026-07-17 |

## 改訂履歴

| 文書版 | 日付 | 内容 |
| --- | --- | --- |
| 1.0 | 2026-07-17 | 初版。MCP 接続、10 ツール、運用・セキュリティ・受け入れ条件を制定 |

## 1. 目的

この文書は、`jra-srb` が提供する MCP サーバーを利用側へ導入するための正式な手順と運用ルールを定めます。

MCP 接続後は、クライアントが各ツールの名前、用途、引数説明、入力スキーマを自動取得します。この文書では、接続前に必要な次の情報を扱います。

- サーバーの起動方法
- MCP クライアントの接続先
- 公開ツールと利用順
- 入力値の共通ルール
- 外部サイトへのアクセス方針
- セキュリティ上の制約
- 初回導入時の受け入れ確認
- エラー発生時の切り分け方法

## 2. 提供範囲

MCP には、JRA の情報取得と予想補助計算を行う読み取り中心の 10 ツールだけを公開します。

次の操作は MCP に公開しません。

- 予想レコードの保存と評価
- レース結果の DB 保存
- 実買い記録の作成と精算
- 結果収集ジョブの作成
- 実際の投票や決済

公開ツールは業務データの保存操作を行いません。ただし、取得結果のキャッシュ更新や外部サイトへの通信は発生する場合があります。

`get_jra_betting_decision` は購入候補または見送り判断を返すだけで、投票は行いません。

## 3. 導入前提

### 3.1 サーバー側

- リポジトリのセットアップが完了していること
- Python 3.12 以上が利用できること
- `uv` が利用できること
- `127.0.0.1:8000` が使用可能であること
- JRA などの取得元サイトへ接続できること

初回セットアップ:

```powershell
uv venv
uv pip install -e .[dev]
```

### 3.2 クライアント側

- Streamable HTTP transport に対応した MCP クライアントであること
- `http://127.0.0.1:8000/mcp` へ接続できること
- サーバーとクライアントを同じ Windows 端末で利用すること

現在は認証がないため、別端末やインターネット経由での利用は対象外です。

## 4. サーバーの起動

リポジトリのルートで次を実行します。

```powershell
uv run uvicorn jra_srb.app:app --host 127.0.0.1 --port 8000
```

開発時に自動再読み込みが必要な場合だけ `--reload` を追加します。

```powershell
uv run uvicorn jra_srb.app:app --host 127.0.0.1 --port 8000 --reload
```

`--host 0.0.0.0` は指定しないでください。認証を導入するまではローカルループバックだけで待ち受けます。

### 4.1 生存確認

別の PowerShell から次を実行します。

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
```

正常時:

```text
status
------
ok
```

MCP endpoint はブラウザーで開く通常の Web ページではありません。MCP クライアントから接続して確認します。

## 5. MCP クライアントへの登録

接続先は次の URL です。

```text
http://127.0.0.1:8000/mcp
```

一般的な設定例:

```json
{
  "mcpServers": {
    "jra": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

設定ファイルの場所と書式は MCP クライアントごとに異なります。利用するクライアントの手順に従い、transport は Streamable HTTP、URL は上記 endpoint を指定してください。

ポートを変更した場合は、サーバー起動コマンドとクライアント設定の両方を同じ値に変更します。

## 6. 初回接続の確認

接続後、クライアント上で次を確認します。

- サーバー名が `JRA Race MCP` である
- ツール数が 10 件である
- 次のツールがすべて表示される
- `create`、`save`、`settle` などの書き込みツールが表示されない

公開ツール:

```text
normalize_race_input
search_jra_races
get_jra_meeting
get_jra_race_card
get_jra_race_odds
get_jra_race_result
get_jra_prediction_bundle
get_jra_odds_summary
compare_jra_prediction_models
get_jra_betting_decision
```

一覧が異なる場合は、変更前の API プロセスが残っている可能性があります。サーバーを停止してから再起動し、MCP クライアントも再接続してください。

## 7. 公開ツール仕様

### 7.1 ツール一覧

| ツール | 用途 | 必須引数 | 主な任意引数 |
| --- | --- | --- | --- |
| `normalize_race_input` | 日本語入力を API 用コードへ変換 | `course`, `race` | `bet_type`, `combination` |
| `search_jra_races` | 開催日などからレースを検索 | `date` | `course`, `keyword`, `limit`, `offset` |
| `get_jra_meeting` | 指定開催のレース一覧を取得 | `date_`, `course` | なし |
| `get_jra_race_card` | 出馬表を取得 | `date_`, `course`, `race_no` | なし |
| `get_jra_race_odds` | 指定券種のオッズを取得 | `date_`, `course`, `race_no`, `bet_type` | `combination`, `refresh=false` |
| `get_jra_race_result` | 確定した着順と払戻を取得 | `date_`, `course`, `race_no` | なし |
| `get_jra_prediction_bundle` | 予想用の当日材料をまとめて取得 | `date_`, `course`, `race_no`, `meeting_no`, `meeting_day` | `sources`, `bet_types`, `refresh=false` |
| `get_jra_odds_summary` | オッズを券種別に要約 | `date_`, `course`, `race_no` | `bet_types`, `refresh=false` |
| `compare_jra_prediction_models` | 複数モデルの順位と一致度を比較 | `date_`, `course`, `race_no`, `meeting_no`, `meeting_day` | `refresh=false` |
| `get_jra_betting_decision` | 期待値から購入候補・見送りを判定 | `date_`, `course`, `race_no`, `meeting_no`, `meeting_day` | `budget=1000`, `refresh=false` |

各引数の型、許容範囲、説明は MCP の `tools/list` で配信される入力スキーマを正とします。

### 7.2 共通入力

#### 開催日

- `date` または `date_`
- `YYYY-MM-DD` 形式
- 例: `2026-07-18`

ツールごとに引数名が `date` と `date_` で異なるため、MCP が提示する入力スキーマの名前をそのまま使用してください。

#### レース番号

- `race_no`: 1 から 12 の整数
- 自然文の `11R` などは `normalize_race_input` の `race` に渡せます

#### 開催回と開催日数

- `meeting_no`: 第 2 回開催なら `2`
- `meeting_day`: 4 日目なら `4`

`get_jra_prediction_bundle`、`compare_jra_prediction_models`、`get_jra_betting_decision` では両方が必須です。

### 7.3 開催場コード

| 日本語 | コード |
| --- | --- |
| 札幌 | `sapporo` |
| 函館 | `hakodate` |
| 福島 | `fukushima` |
| 新潟 | `niigata` |
| 東京 | `tokyo` |
| 中山 | `nakayama` |
| 中京 | `chukyo` |
| 京都 | `kyoto` |
| 阪神 | `hanshin` |
| 小倉 | `kokura` |

日本語で受け取った場合は `normalize_race_input` を先に使用してください。

### 7.4 券種コード

| 日本語 | コード |
| --- | --- |
| 単勝 | `win` |
| 複勝 | `place` |
| 馬連 | `quinella` |
| ワイド | `wide` |
| 馬単 | `exacta` |
| 3連複 | `trio` |
| 3連単 | `trifecta` |

> [!WARNING]
> 現行の日本語正規化では「複勝」が `place` に正規化されません。複勝を取得する場合は `normalize_race_input` を経由せず、券種コード `place` を直接指定してください。

`bet_types` は複数のコードをカンマ区切りで指定します。

```text
win,wide,quinella
```

`combination` もカンマ区切りです。

```text
10,11
4,10,11
```

## 8. 推奨利用フロー

### 8.1 対象レースが自然文で指定された場合

1. `normalize_race_input` で開催場、レース番号、券種を正規化する
2. `get_jra_meeting` または `search_jra_races` で対象レースを確認する
3. `get_jra_race_card` で出馬表を取得する
4. 必要に応じて `get_jra_race_odds` または `get_jra_odds_summary` を取得する

利用者からの依頼例:

```text
2026-07-18の福島11Rについて、出馬表と単勝オッズを確認してください。
```

### 8.2 詳細な予想材料が必要な場合

1. 対象レースと `meeting_no`、`meeting_day` を確認する
2. `get_jra_prediction_bundle` で当日材料をまとめて取得する
3. `compare_jra_prediction_models` でモデル間の一致度を確認する
4. 購入判断が必要な場合だけ `get_jra_betting_decision` を呼ぶ

利用者からの依頼例:

```text
2026-07-18 福島11R、第2回開催4日目を予想してください。
公開材料と履歴モデルを比較し、予算1000円で買うか見送るかも判断してください。
```

### 8.3 レース終了後

`get_jra_race_result` で着順と払戻を確認します。レース確定前は結果が空または未確定の場合があります。

MCP には予想評価や結果保存ツールを公開していません。保存や評価が必要な場合は、管理者が許可した別の API または運用手順を使用してください。

## 9. 外部アクセスとキャッシュの運用

### 9.1 `refresh` の原則

- 通常は `refresh=false` を使用する
- 同じレースに対して短時間に繰り返し取得しない
- 発走直前など、明示的に最新情報が必要な場合だけ `refresh=true` を使用する
- 複数材料が必要な場合は、個別ツールの連続呼び出しより `get_jra_prediction_bundle` を優先する

`refresh=true` は取得元サイトへの通信を増やします。利用者の明示的な要望がない限り、MCP クライアントへ強制させないでください。

### 9.2 情報の時点

- オッズは取得時点の値で、確定値ではない場合がある
- 出馬表、馬体重、取消情報などは公開時刻により未掲載の場合がある
- 結果と払戻はレース確定後に利用する
- 予想結果には取得時点や構成要素の状態が含まれる場合があるため、レスポンスの `as_of`、`fetched_at`、`status`、`component_status` などを確認する

## 10. エラー時の対応

| 症状 | 主な原因 | 対応 |
| --- | --- | --- |
| MCP サーバーへ接続できない | API 未起動、URL・ポート違い | `/health` を確認し、クライアント設定を見直す |
| ツールが 61 件表示される | 変更前プロセスが稼働中 | API を再起動し、MCP クライアントを再接続する |
| ツールが表示されない | MCP endpoint の誤り、transport 非対応 | `/mcp` と Streamable HTTP 対応を確認する |
| 入力が拒否される | 日付形式、開催場、レース番号、券種が不正 | MCP の入力スキーマを確認し、必要なら正規化ツールを使用する |
| 結果が未確定 | レース確定前 | 確定後に再取得する |
| モデルが `unavailable` | モデルファイル未配置、対象期間不整合 | 材料モデルだけを使用するか、サーバー管理者へ確認する |
| 外部取得エラー | 取得元サイトの停止・変更・一時的制限 | 連続再試行せず、時間を空けて管理者へ連絡する |
| 応答が遅い | 複数外部サイトの取得、キャッシュ未生成 | `refresh=false` を確認し、完了を待つ |

API エラーに `request_id` が含まれる場合は、問い合わせ時にその値、使用ツール、入力値、発生時刻を伝えてください。

## 11. セキュリティ

現在の MCP endpoint には認証がありません。次を必須ルールとします。

- `127.0.0.1` だけで待ち受ける
- LAN、VPN、インターネットへ公開しない
- リバースプロキシ経由で公開しない
- 公共端末や共有端末で常時起動しない
- 利用終了後は不要な API プロセスを停止する

外部公開が必要な場合は、公開前に少なくとも次を設計・実装します。

- HTTPS
- MCP endpoint の認証と認可
- 利用者またはクライアント単位のアクセス制御
- レート制限
- 操作監査ログ
- 許可 origin / host の制限
- 認証失敗と異常呼び出しの監視

これらが完了するまで、この資料の接続 URL を別端末向けに変更して配布しないでください。

## 12. 受け入れチェックリスト

導入担当者は、初回利用前に次を確認します。

- [ ] API が `127.0.0.1:8000` で起動している
- [ ] `/health` が `status=ok` を返す
- [ ] MCP endpoint が `http://127.0.0.1:8000/mcp` に設定されている
- [ ] MCP サーバー名が `JRA Race MCP` である
- [ ] 公開ツール数が 10 件である
- [ ] 書き込み・保存・精算ツールが公開されていない
- [ ] `normalize_race_input` で `中山`、`11R`、`3連単` を変換できる
- [ ] 通常呼び出しで `refresh=false` が使われる
- [ ] クライアントが Streamable HTTP に対応している
- [ ] サーバーが `0.0.0.0` で待ち受けていない
- [ ] 利用者が本資料の運用・セキュリティルールを確認している

## 13. 正本と変更管理

この文書を MCP 利用側の導入・運用契約の正本とします。

次の変更を行った場合は、本資料と MCP プロトコルテストを同時に更新します。

- endpoint URL または transport の変更
- 公開ツールの追加・削除・名称変更
- 必須引数、既定値、許容コードの変更
- 認証方式または公開範囲の変更
- `refresh` や外部アクセス方針の変更

HTTP API の詳細仕様は [05_API仕様.md](/D:/develop/jra-scr/docs/jra/05_API仕様.md)、一般的な利用方法は [04_利用ガイド.md](/D:/develop/jra-scr/docs/jra/04_利用ガイド.md) を参照してください。
