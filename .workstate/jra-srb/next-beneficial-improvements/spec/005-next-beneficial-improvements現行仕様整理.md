# 次に有益な改修候補 現行仕様整理

## 現在できていること

- FastAPI API がある。
- `/health` がある。
- `/mcp` が `fastapi-mcp` で公開されている。
- 開催一覧、出馬表、オッズ、結果・払戻を取得できる。
- `race_id` ベースと、開催日・開催場・レース番号ベースの API がある。
- `win`, `quinella`, `wide`, `exacta`, `trio`, `trifecta` のオッズ取得に対応している。
- `ProviderError`, `LookupError`, `JraApiError` の HTTP レスポンス化がある。
- `HttpProvider` に retry / backoff / timeout がある。
- `PastResultCollector` と `JsonlRaceResultStorage` により、過去結果を JSONL 保存できる。
- fixture provider とテストがあり、実サイトに依存しない検証ができる。

## 現在の制約

- API 入力は `nakayama`, `trifecta` など英字コード前提で、自然言語や日本語表記を直接扱えない。
- `course` と `bet_type` が OpenAPI 上で Enum として明示されていない。
- `race_no` の範囲制約が API パラメータで明示されていない。
- 過去結果収集の部品はあるが、利用者が直接実行できる CLI がない。
- JSONL に保存した結果を API から検索・再利用する入口がない。
- ログが整備されておらず、失敗時に `course`, `race_id`, `cname`, upstream URL 単位で追いにくい。
- `/health` はプロセス生存確認のみで、upstream 到達性や provider 状態までは見ない。
- キャッシュはインメモリのみで、再起動後の再取得抑制はできない。

## 完了済みとして扱う候補

`docs/jra/08_実装タスクと優先順位.md` にある以下は、現行コード上では概ね完了済みとして扱う。

- API 例外の HTTP レスポンス化
- `HttpProvider` の retry / backoff / timeout 整備
- README の日本語メイン化

ただし、文字化けについては PowerShell 表示上の問題と、既存 docs / source の実体を分けて確認する余地がある。機能改修の主タスクではなく、必要時の検証タスクとして扱う。
