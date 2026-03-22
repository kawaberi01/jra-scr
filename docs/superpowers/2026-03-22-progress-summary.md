# JRA Data Retrieval Progress Summary

## 目的

このファイルは、2026-03-22 時点で `jra-srb` に対して何を実装し、何が未完了かを次の作業者がすぐ再開できるようにまとめた引き継ぎメモである。

関連ドキュメント:

- 設計書: `docs/superpowers/specs/2026-03-22-jra-data-retrieval-design.md`
- 実装計画: `docs/superpowers/plans/2026-03-22-jra-data-retrieval-implementation-plan.md`

## 今回やったこと

### 1. JRA 固有のナビゲーション層を追加

追加ファイル:

- `src/jra_srb/navigation.py`

実装内容:

- `JRADB/access*.html` の開催選択ページから、`course + date + kind` に対応する `cname` を解決する `JraNavigation` を追加
- 対応した kind:
  - `card`
  - `odds`
  - `result`
  - `payout`
- 開催名の日本語ラベルから `馬番確定` のような余計な表示を除去する正規化を実装

### 2. provider を JRA 導線対応に拡張

変更ファイル:

- `src/jra_srb/provider.py`

実装内容:

- `post_jradb(path, cname)` を追加
  - JRA の `doAction(..., cname)` に相当する POST を再現
- `fetch_jradb(path, cname)` を追加
  - `GET ...?CNAME=...` を使う詳細ページ取得用
- `FixtureProvider` に JRA 向け fixture 分岐を追加
- fixture の文字コードを `utf-8` 優先、失敗時は `shift_jis` + `errors="ignore"` で読めるように変更

### 3. 開催地単位の meeting API を追加

変更ファイル:

- `src/jra_srb/models.py`
- `src/jra_srb/extractors.py`
- `src/jra_srb/service.py`
- `src/jra_srb/app.py`

実装内容:

- `MeetingRace`
- `MeetingSnapshot`

を追加し、`date + course` から 1R-12R の一覧を返す API を実装した。

追加エンドポイント:

- `GET /meetings/{date}/{course}`

抽出内容:

- `race_no`
- `race_id`
- `race_name`
- `start_time`
- `card_cname`
- `odds_cname`
- `result_cname`

補足:

- `race_id` は `YYYYMMDD + course_code + race_no` 形式で再構築している
- course code の逆引きは `service.py` に持たせている

### 4. 開催地座標からの出馬表取得を追加

変更ファイル:

- `src/jra_srb/extractors.py`
- `src/jra_srb/service.py`
- `src/jra_srb/app.py`

実装内容:

- `get_race_card_by_number(date, course, race_no)` を追加
- meeting の `card_cname` から JRA 実ページを取得して `RaceCard` を生成
- 従来のダミー fixture 向け parser は維持しつつ、JRA 実ページ向けのフォールバック parser `_parse_jra_race_card()` を追加

追加エンドポイント:

- `GET /meetings/{date}/{course}/races/{race_no}/card`

### 5. オッズ取得を JRA 実導線に対応

変更ファイル:

- `src/jra_srb/models.py`
- `src/jra_srb/extractors.py`
- `src/jra_srb/service.py`
- `src/jra_srb/app.py`

実装内容:

- 既存の `bet_types=...` 互換は残した
- 新しく `bet_type=...` の単一券種取得を追加
- JRA 実ページについては、meeting にある `odds_cname` を入口にして:
  1. オッズ入口ページを取得
  2. 券種タブから対象券種の `cname` を解決
  3. 券種別ページを取得
  4. 組み合わせを正規化

対応済み bet_type:

- `win`
  - 実体は「単勝・複勝オッズ（馬番順）」ページ
  - `entries` に単勝オッズを入れ、複勝レンジは `odds_min` / `odds_max` に保持
- `trifecta`
  - 実体は「3連単オッズ（馬番順）」ページ
  - `tan3_unit` と `ul.tan3_list > li` を辿り、`[1着, 2着, 3着]` の組み合わせを再構成

追加エンドポイント:

- `GET /meetings/{date}/{course}/races/{race_no}/odds?bet_type=...`
- 既存:
  - `GET /races/{race_id}/odds?bet_type=...`

追加したクエリ:

- `bet_type`
- `combination=1,2,3`
- `refresh=true`

重要:

- `win` と `trifecta` 以外の券種はまだ未対応
- ただし `parse_odds_navigation()` で券種タブの `cname` 取得まではできているので、今後の拡張はしやすい

### 6. 結果・払戻取得を実装

変更ファイル:

- `src/jra_srb/navigation.py`
- `src/jra_srb/provider.py`
- `src/jra_srb/extractors.py`
- `src/jra_srb/service.py`
- `src/jra_srb/app.py`

実装内容:

- `accessS` の個別結果ページでは払戻が取れなかったため、`accessH` の開催単位ページを正とした
- `kind="payout"` を navigation に追加
- `parse_meeting_payout_result(html, race_no)` を追加し、`li#harai_{race_no}R` を起点に:
  - レース結果要約
  - 払戻一覧

を同時に抽出するようにした

追加エンドポイント:

- `GET /meetings/{date}/{course}/races/{race_no}/result`

補足:

- `RaceResult` の `payouts` に `単勝`、`複勝`、`枠連`、`馬連`、`馬単`、`ワイド`、`3連複`、`3連単` を格納している
- `payout` 文字列には現在コンマが残る
- `popularity` も文字列のまま保持している

### 7. 過去結果バッチの最小骨組みを追加

追加ファイル:

- `src/jra_srb/batch.py`

追加内容:

- `PastResultCollector`
- `collect(from_date, to_date, courses)`

現状の挙動:

- 日付と開催地の直積を順に回り、`service.get_meeting()` を呼ぶだけ

未実装:

- 結果・払戻の永続化
- リトライ
- スキップ制御
- 保存先 abstraction

TODO コメントを残してある

### 8. README 更新

変更ファイル:

- `README.md`

追加内容:

- `meetings` 系 API
- `bet_type` / `combination` / `refresh` を使うオッズ例

## 追加・更新された主なファイル

- `src/jra_srb/navigation.py`
- `src/jra_srb/provider.py`
- `src/jra_srb/extractors.py`
- `src/jra_srb/models.py`
- `src/jra_srb/service.py`
- `src/jra_srb/app.py`
- `src/jra_srb/batch.py`
- `tests/test_navigation.py`
- `tests/test_batch.py`
- `tests/test_service.py`
- `tests/test_api.py`
- `README.md`

## 追加した fixture

- `tests/fixtures/jradb_accessD_select.html`
- `tests/fixtures/jradb_accessO_select.html`
- `tests/fixtures/jradb_accessS_select.html`
- `tests/fixtures/jradb_accessH_select.html`
- `tests/fixtures/jradb_accessD_meeting_nakayama_20260322.html`
- `tests/fixtures/jradb_accessD_race_202603220611.html`
- `tests/fixtures/jradb_accessO_race_202603220611.html`
- `tests/fixtures/jradb_accessO_trifecta_202603220611.html`
- `tests/fixtures/jradb_accessH_meeting_nakayama_20260322.html`
- `tests/fixtures/jradb_accessS_race_202603220611.html`

## 現在動くもの

確認済み API:

- `GET /meetings/2026-03-22/nakayama`
- `GET /meetings/2026-03-22/nakayama/races/11/card`
- `GET /meetings/2026-03-22/nakayama/races/11/odds?bet_type=trifecta&combination=1,2,3`
- `GET /meetings/2026-03-22/nakayama/races/11/result`
- 既存の fixture ベース API:
  - `/races/{race_id}/card`
  - `/races/{race_id}/odds?bet_types=...`
  - `/races/{race_id}/result`

## 実行した検証

### テスト

実行コマンド:

```bash
uv run pytest -v
```

結果:

- `18 passed`

### アプリ起動確認

実行コマンド:

```bash
timeout 5s uv run uvicorn jra_srb.app:app --host 127.0.0.1 --port 8000
```

結果:

- 起動成功
- startup / shutdown 正常

## 未完了・次にやるべきこと

優先度順:

1. `win` と `trifecta` 以外の券種対応を追加
   - `枠連`
   - `馬連`
   - `ワイド`
   - `馬単`
   - `3連複`
   - 必要なら `人気順` 版も

2. オッズ parser の整理
   - 今は `parse_jra_win_place_odds()` と `parse_jra_trifecta_odds()` を個別実装している
   - 券種別の parser registry に分離すると拡張しやすい

3. 払戻 parser の正規化
   - `payout` の数値化
   - `popularity` の数値化
   - `combination` の token 化

4. 過去結果バッチの実体化
   - `get_race_result_by_number()` を日付範囲で巡回
   - 保存先を決める
   - 冪等化と再試行

5. MCP 入口の追加
   - `course` 日本語 -> 英字コード変換
   - `race_no` 解釈
   - `bet_type` 自然言語 -> 内部コード変換

## 注意点

### 1. Git 管理外

このワークスペースは今回の実行時点で Git 管理下に見えていなかった。

確認結果:

- `git rev-parse --show-toplevel` は失敗
- そのためコミット、ブランチ操作、PR 作成は未実施

### 2. 文字コード

JRA fixture は Shift_JIS だが、一部に不正バイトが混ざるものがある。

対策:

- `FixtureProvider._load()` は `shift_jis, errors="ignore"` を使用

### 3. 既存の `parse_race_card` / `parse_race_odds` / `parse_race_result` は残してある

理由:

- 旧 fixture ベーステストを壊さずに、JRA 実ページ向け parser を追加したため

次に整理するなら:

- `legacy fixtures` 用
- `jra live pages` 用

で責務を明示的に分けた方がよい

## 再開時の最短ルート

もし次に作業を再開するなら、最初に読むべきファイルは以下。

1. `docs/superpowers/specs/2026-03-22-jra-data-retrieval-design.md`
2. `docs/superpowers/plans/2026-03-22-jra-data-retrieval-implementation-plan.md`
3. `src/jra_srb/service.py`
4. `src/jra_srb/extractors.py`
5. `src/jra_srb/navigation.py`

次の着手候補としては、`3連複` の券種対応を追加するのが一番自然。
