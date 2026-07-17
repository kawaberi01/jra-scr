# JRA公式オッズAPI 0件応答 調査レポート

## インシデント概要

- 対象: `GET /meetings/{date}/{course}/races/{race_no}/odds`
- 再現条件: `2026-07-12 / hakodate / 6R`、`bet_type=quinella|wide|trio`、`refresh=true`
- 症状: HTTP 200 だが `entries=[]` になる。単勝は取得できる。
- 調査範囲: API入口、JRA券種ナビ、ライブHTML、HTMLパーサー、fixtureテスト。コード変更は行っていない。

## 期待値 / 実際値

### 期待値

- 馬連・ワイド・3連複の券種別ページから全組合せを解析する。
- `combination` 指定時は、解析済み一覧から対象組合せを返す。

### 実際値

- 券種別ページへの遷移は成功している。
- ページタイトルもそれぞれ `馬連オッズ（馬番順） JRA`、`ワイドオッズ（馬番順） JRA`、`3連複オッズ（馬番順） JRA` だった。
- しかし `parse_jra_table_odds()` が全券種で0件を返す。

## 処理フロー

1. `app.py` の日付・場・R指定APIが `JraService.get_race_odds_by_number()` を呼ぶ。
2. `service.py` が初期オッズCNAMEを取得する。
3. `parse_odds_navigation()` が券種別CNAMEを取得する。
4. JRAの券種別ページへPOSTする。
5. `parse_jra_table_odds()` が `#odds_list table.odds_table tbody tr` を解析する。
6. 現在のライブHTMLには `table.odds_table` がないため、5で0件になる。

## 確認できた事実

### 券種ナビは正常

- 馬連: `pw154...`
- ワイド: `pw155...`
- 3連複: `pw157...`

対象ページのタイトルと券種が一致しており、誤ったCNAMEへの遷移ではない。

### ライブHTMLの構造

| 券種 | 現在のtable class | table数 | tbody行数 | 現行パーサー結果 |
| --- | --- | ---: | ---: | ---: |
| 馬連 | `basic narrow-xy umaren` | 15 | 120 | 0 |
| ワイド | `basic narrow-xy wide` | 15 | 120 | 0 |
| 3連複 | `basic narrow-xy fuku3` | 105 | 560 | 0 |

現在の組合せ構造は次の形式になっている。

- 馬連・ワイド: `caption` が1頭目、各行の `th` が2頭目
- 3連複: `caption` が1頭目と2頭目（例: `1-2`）、各行の `th` が3頭目
- 馬連・3連複のオッズ: 行内の `td` または `strong`
- ワイドのオッズ: `.min` と `.max`

### 現行パーサーと不一致

`extractors.py` の `parse_jra_table_odds()` は以下を前提としている。

- table: `#odds_list table.odds_table`
- 組合せ: 行内の `.num` 要素が2個または3個
- オッズ: 行内の `.odds`

ライブHTMLでは `odds_table` が0件で、組合せの一部が `caption` に移っている。このため、単に絞り込み後に対象組合せが見つからないのではなく、絞り込み前の全件解析が0件になっている。

### 既存テストの盲点

- 対象APIテストは4件成功した。
- fixtureは `table class="basic odds_table"` という旧構造を使用している。
- そのためfixtureテストは現行実装との整合性は確認できるが、現在のJRAライブHTMLとの互換性は検出できない。

## 原因候補

### 最有力（事実に基づき確定）

JRA公式オッズページのHTML構造と `parse_jra_table_odds()` のセレクタ・組合せ抽出方式が不一致になっている。

### 否定済み

- APIそのものが未実装: 実装済み。
- `bet_type` が未対応: `quinella`、`wide`、`trio` は分岐実装済み。
- 券種別CNAMEの解決失敗: 正しいページタイトルまで到達している。
- 発売前でオッズが存在しない: ライブHTML内に各券種の数値オッズが存在する。
- `combination` の並び順だけが原因: 全件解析の段階で0件なので該当しない。

## 判定結果

**実装引き継ぎ可能**。

根本原因は `src/jra_srb/extractors.py` の `parse_jra_table_odds()` に局所化できる。API入口や券種ナビ、HTTP取得経路を変更する根拠はない。

## 最小修正単位

- 現在の `umaren`、`wide`、`fuku3` テーブルを解析できるようにする。
- 馬連・ワイドでは `caption + th`、3連複では `captionの2頭 + th` から組合せを構成する。
- ワイドは `odds_min` / `odds_max` を保持する。
- 既存fixture形式との後方互換を維持するか、対応不要ならfixtureを現行構造へ更新する。
- 空配列を正常取得と誤認しない回帰テストを追加する。

## 回帰確認観点

- 馬連・ワイド・馬単・3連複の全件数が0より大きいこと。
- 指定組合せが順不同券種で正規化されること。
- ワイドの下限・上限が保持されること。
- 単勝・3連単の既存専用パーサーに影響がないこと。
- ライブ構造相当fixtureを使い、API経由でも対象組合せが1件返ること。

## 次に取るべき行動

`parse_jra_table_odds()` とライブ相当fixture・テストだけを最小範囲で修正し、対象APIおよびオッズbundleの回帰テストを実施する。

## 要確認

- 馬単ページも同じ `caption + th` 構造か（同一汎用パーサーを使うため、実装時に確認が必要）。
- JRA側が旧形式と現行形式を条件によって出し分ける可能性があるため、後方互換を残すか判断する。
