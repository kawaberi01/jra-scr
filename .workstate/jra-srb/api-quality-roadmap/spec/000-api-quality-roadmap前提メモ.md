# API 品質向上ロードマップ 前提メモ

作成日: 2026-06-28

## 目的

前回実装後の `jra-srb` API を、公開 API としてより使いやすく、壊れにくく、運用しやすくするために不足機能と改修候補を再整理する。

## 調査対象

- `src/jra_srb/app.py`
- `src/jra_srb/models.py`
- `src/jra_srb/service.py`
- `src/jra_srb/normalization.py`
- `src/jra_srb/batch.py`
- `src/jra_srb/cli.py`
- `tests/test_api.py`
- `README.md`
- `docs/jra/06_スクレイピングと運用注意.md`

## 現在の到達点

- 開催一覧、出馬表、オッズ、結果・払戻の API がある。
- `/normalize` による日本語入力正規化がある。
- `CourseCode` / `BetType` Enum と一部入力制約がある。
- 保存済み結果の読み出し API がある。
- 結果収集 CLI がある。
- JSONL / SQLite 保存先がある。
- upstream health と基本 logging がある。

## 再検討の観点

1. API 契約が分かりやすいか
2. エラーが機械処理しやすいか
3. 大きなレスポンスや保存済みデータに耐えられるか
4. 外部サイトへの配慮と運用制御があるか
5. README / OpenAPI / 実装が同期しているか
