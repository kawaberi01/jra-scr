# 実買い記録 API 仕様案

## 目的

予想エージェントの出力と、実際に購入した券、および結果確定後の振り返りを
同じ `analysis.sqlite` で管理できるようにする。

この用途では以下を分けて保存する。

- 予想した内容
- 実際に買った内容
- 結果確定後の精算結果

既存の `predictions` / `prediction_tickets` / `evaluations` は残し、
実買い記録用のテーブルを追加する。

## DB 方針

- 別 DB には分けず、既存 `analysis.sqlite` に追加する
- 既存の `race_id` / `predictions` / `payouts` / `race_results` と直接 join できる構成にする
- 個人の実買いログであるため、理論評価テーブルとは論理分離し、物理分離はしない

## 追加テーブル

### 1. `bet_records`

実際に「このレースでこの買い方を採用した」と決めた単位。

想定カラム:

- `bet_record_id` text primary key
- `race_id` text not null
- `prediction_id` text null
- `theory_version` text null
- `decision_source` text not null
  - `agent`
  - `manual`
  - `agent_plus_manual`
- `purchased_at` text null
- `total_amount` integer not null
- `note` text null
- `created_at` text not null
- `updated_at` text not null

補足:

- `prediction_id` は nullable にする
- 予想を見ずに手動で買うケースも許容する

### 2. `bet_record_tickets`

実際に購入した券 1 点ごとの明細。

想定カラム:

- `bet_ticket_id` text primary key
- `bet_record_id` text not null
- `race_id` text not null
- `prediction_ticket_id` text null
- `bucket` text null
- `bet_type` text not null
- `selection` text not null
- `selection_json` text not null
- `amount` integer not null
- `odds_at_buy` real null
- `is_box_expanded` integer not null default 0
- `reason` text null
- `created_at` text not null

補足:

- `selection` は正規化済み文字列を保存する
  - 例: `wide` の `10,2` は `2-10`
  - 例: `trio` の `10,2,4` は `2-4-10`
- `selection_json` は配列のまま保持する
- BOX は保存前に展開する
  - `wide box 2,4,10` は 3 件に展開
    - `2-4`
    - `2-10`
    - `4-10`

### 3. `bet_record_results`

結果確定後の精算結果。

想定カラム:

- `bet_record_result_id` text primary key
- `bet_record_id` text not null unique
- `race_id` text not null
- `total_bet` integer not null
- `total_payout` integer not null
- `return_rate` real not null
- `hit` integer not null
- `settled_at` text not null
- `result_json` text not null
- `created_at` text not null

補足:

- 1 `bet_record` に対して 1 精算結果
- 再精算時は upsert で更新してよい

## 正規化ルール

既存 API の bet type / combination ルールに合わせる。

### bet_type

以下の API 既存コードを使い回す。

- `win`
- `place`
- `wide`
- `quinella`
- `exacta`
- `trio`
- `trifecta`

### selection

順不同券種:

- `wide`
- `quinella`
- `trio`

は昇順正規化して保存する。

順序券種:

- `exacta`
- `trifecta`

は入力順を保持する。

### box 展開

保存 API は次の両方を受けてよい。

1. 展開済み券
2. `mode=box` を含む圧縮入力

ただし DB 保存時点では必ず展開済みにする。

## API 追加案

### 1. `POST /bet-records`

実買い記録を保存する。

用途:

- 予想に紐づけた実買い保存
- 手動購入記録
- BOX 入力の正規化保存

Request body 例:

```json
{
  "race_id": "202607051011",
  "prediction_id": "pred_xxx",
  "theory_version": "v86",
  "decision_source": "agent_plus_manual",
  "purchased_at": "2026-07-05T15:40:00+09:00",
  "note": "参考判定を見て購入",
  "tickets": [
    {
      "bet_type": "wide",
      "mode": "box",
      "horses": ["2", "4", "10"],
      "amount_per_ticket": 100
    },
    {
      "bet_type": "trio",
      "mode": "normal",
      "horses": ["2", "4", "10"],
      "amount": 100
    }
  ]
}
```

保存後の内部明細:

- `wide 2-4 100`
- `wide 2-10 100`
- `wide 4-10 100`
- `trio 2-4-10 100`

Response 例:

```json
{
  "bet_record_id": "betrec_xxx",
  "race_id": "202607051011",
  "total_amount": 400,
  "tickets": [
    {"bet_type": "wide", "selection": "2-4", "amount": 100},
    {"bet_type": "wide", "selection": "2-10", "amount": 100},
    {"bet_type": "wide", "selection": "4-10", "amount": 100},
    {"bet_type": "trio", "selection": "2-4-10", "amount": 100}
  ]
}
```

### 2. `GET /bet-records/{bet_record_id}`

実買い記録を取得する。

返却対象:

- `bet_records`
- `bet_record_tickets`
- 関連 `prediction`
- 関連 `prediction_tickets`
- 精算済みなら `bet_record_results`

### 3. `GET /bet-records`

実買い記録の検索。

Query 例:

- `from_date`
- `to_date`
- `race_id`
- `course`
- `theory_version`
- `decision_source`
- `limit`
- `offset`

### 4. `POST /bet-records/{bet_record_id}/settle`

保存済み実買い記録を結果確定後に精算する。

動作:

1. `race_id` を取得
2. `payouts` または `netkeiba_payouts` を読む
3. `bet_record_tickets` と正規化照合する
4. 的中明細、払戻合計、回収率を計算する
5. `bet_record_results` に upsert 保存する

Response 例:

```json
{
  "bet_record_id": "betrec_xxx",
  "race_id": "202607051011",
  "total_bet": 400,
  "total_payout": 0,
  "return_rate": 0.0,
  "hit": false,
  "ticket_results": [
    {"bet_type": "wide", "selection": "2-4", "amount": 100, "hit": false, "payout": 0},
    {"bet_type": "wide", "selection": "2-10", "amount": 100, "hit": false, "payout": 0},
    {"bet_type": "wide", "selection": "4-10", "amount": 100, "hit": false, "payout": 0},
    {"bet_type": "trio", "selection": "2-4-10", "amount": 100, "hit": false, "payout": 0}
  ]
}
```

## 既存テーブルとの関係

### `predictions`

- 予想本文、根拠、snapshot を保持
- 実買いとは別

### `prediction_tickets`

- エージェントが提案した券
- `bet_record_tickets.prediction_ticket_id` で参照可能にする

### `evaluations`

- 理論評価用
- 実買い収支とは分離する

## 最低限必要な実装範囲

初回は以下に絞る。

1. schema 追加
2. store 層の CRUD 追加
3. `POST /bet-records`
4. `GET /bet-records/{bet_record_id}`
5. `POST /bet-records/{bet_record_id}/settle`
6. テスト追加

`GET /bet-records` の一覧検索は後回しでもよいが、可能なら同時実装する。

## settle の照合ルール

- `wide`, `quinella`, `trio`:
  - 順不同で照合
- `exacta`, `trifecta`:
  - 順序込みで照合
- `win`, `place`:
  - 馬番 1 件で照合

`selection` の正規化関数は既存 odds API の combination 正規化ロジックと共通化する。

## 今回の例

2026-07-05 小倉11R 北九州記念:

- 購入内容
  - ワイド BOX `2,4,10`
  - 3連複 `2-4-10`
- 展開後
  - `wide 2-4`
  - `wide 2-10`
  - `wide 4-10`
  - `trio 2-4-10`
- 精算結果
  - 全件はずれ
  - `total_bet=400`
  - `total_payout=0`

## API 実装側への指示プロンプト

以下を API 実装側への依頼文として使う。

---

`analysis.sqlite` に実買い記録を保存する API を追加してください。別 DB ではなく既存 DB に同居させてください。

前提:

- 既存の `predictions` / `prediction_tickets` / `evaluations` は残す
- 今回追加したいのは「予想」ではなく「実際に買った券」と「結果確定後の精算結果」
- `race_id` ベースで既存の `races`, `payouts`, `race_results` と結びたい

要件:

1. `analysis.sqlite` に以下の 3 テーブルを追加
   - `bet_records`
   - `bet_record_tickets`
   - `bet_record_results`

2. `bet_records`
   - `bet_record_id` PK
   - `race_id` 必須
   - `prediction_id` nullable
   - `theory_version` nullable
   - `decision_source` 必須 (`agent` / `manual` / `agent_plus_manual`)
   - `purchased_at` nullable
   - `total_amount` 必須
   - `note` nullable
   - `created_at`, `updated_at` 必須

3. `bet_record_tickets`
   - `bet_ticket_id` PK
   - `bet_record_id` 必須
   - `race_id` 必須
   - `prediction_ticket_id` nullable
   - `bucket` nullable
   - `bet_type` 必須
   - `selection` 必須
   - `selection_json` 必須
   - `amount` 必須
   - `odds_at_buy` nullable
   - `is_box_expanded` 必須
   - `reason` nullable
   - `created_at` 必須

4. `bet_record_results`
   - `bet_record_result_id` PK
   - `bet_record_id` unique
   - `race_id` 必須
   - `total_bet`, `total_payout`, `return_rate`, `hit` 必須
   - `settled_at`, `result_json`, `created_at` 必須

5. API を追加
   - `POST /bet-records`
   - `GET /bet-records/{bet_record_id}`
   - `POST /bet-records/{bet_record_id}/settle`
   - 可能なら `GET /bet-records`

6. `POST /bet-records` の入力では BOX を受け付けてよいが、DB 保存時は必ず展開する
   - 例: `wide box 2,4,10` は
     - `2-4`
     - `2-10`
     - `4-10`
     に展開して `bet_record_tickets` に保存

7. `selection` 正規化ルールは既存 odds API と揃える
   - 順不同券種: `wide`, `quinella`, `trio`
   - 順序券種: `exacta`, `trifecta`
   - `win`, `place` は 1 頭

8. `POST /bet-records/{bet_record_id}/settle`
   - `race_id` に紐づく既存 `payouts` または `netkeiba_payouts` から払戻を照合
   - チケット単位で hit / payout を計算
   - 合計を `bet_record_results` に upsert

9. 既存コードの流儀に合わせる
   - store 層に保存処理を寄せる
   - Pydantic model を追加
   - FastAPI endpoint を追加
   - `tests/test_analysis_store.py`, `tests/test_api.py` にテスト追加

10. 最低限テストしてほしいケース
   - `POST /bet-records` でワイド BOX が展開保存される
   - `GET /bet-records/{bet_record_id}` で prediction 紐づき込みで返る
   - settle で全はずれが `total_payout=0` になる
   - settle で順不同券種の照合が正しく動く
   - settle で順序券種の照合が正しく動く

今回の実例:

- race_id: `202607051011`
- 購入:
  - ワイド BOX `2,4,10`
  - 3連複 `2-4-10`
- 結果:
  - 全件はずれ
  - `total_bet=400`
  - `total_payout=0`

実装後は、追加 endpoint の request / response 例を `docs/jra/05_API仕様.md` に追記してください。

---
