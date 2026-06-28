# 次に有益な改修候補 実装指示書

## 最初に実装する推奨タスク

P0: MCP / API 入力正規化

## 改修目的

「中山 11R 3連単 1,2,3」のような利用者寄りの入力を、既存 API が使う `course=nakayama`, `race_no=11`, `bet_type=trifecta`, `combination=["1", "2", "3"]` に正規化できるようにする。

## 変更してよい範囲

- `src/jra_srb/normalization.py`
- `src/jra_srb/models.py`
- `src/jra_srb/app.py`
- `src/jra_srb/service.py`
- `tests/test_api.py`
- 新規 `tests/test_normalization.py`
- 必要最小限の README / docs 追記

## 変更しない範囲

- JRA HTML 解析ロジックの大幅変更
- `HttpProvider` の通信仕様変更
- 既存 endpoint の互換性破壊
- 既存 fixture の不要な差し替え

## 実装方針

1. `normalization.py` に pure function を置く。
2. alias 辞書はコード内の小さな定数として始める。
3. 変換不能な入力は独自例外または `BadRequestError` に変換する。
4. API には正規化確認用 endpoint を追加する。
5. 既存の取得 endpoint 自体は互換性を保つ。
6. MCP から呼びやすいように、正規化 endpoint の summary / description を日本語で明確にする。

## endpoint 案

```http
GET /normalize?course=中山&race=11R&bet_type=3連単&combination=1,2,3
```

レスポンス案:

```json
{
  "course": "nakayama",
  "race_no": 11,
  "bet_type": "trifecta",
  "combination": ["1", "2", "3"]
}
```

## テスト観点

- `中山` が `nakayama` になる。
- `阪神` が `hanshin` になる。
- `11R`, `11レース`, `第11レース` が `11` になる。
- `3連単`, `三連単` が `trifecta` になる。
- `馬連` が `quinella` になる。
- `combination=1,2,3` が `["1", "2", "3"]` になる。
- 未対応の開催場名は 400 になる。
- 未対応の券種名は 400 になる。
- `race_no` が 1 から 12 の範囲外なら 400 になる。

## 次に続けるタスク

P0 完了後、P1 の Enum ベース入力バリデーションへ進む。正規化で得た canonical value と Enum を同じ定義から使えるようにすると、OpenAPI と service のズレを減らせる。

## 停止条件

- MCP 経由で追加 endpoint が期待通り公開されない場合は、`fastapi-mcp` の公開仕様を確認してから進める。
- 正規化 endpoint を追加すると既存 OpenAPI テストが大きく崩れる場合は、まず API 設計を再確認する。
