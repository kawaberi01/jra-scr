# 010-jra-ticket-safety 実装仕様書

## 変更後仕様

- `build_prediction_record` はワイド組合せオッズが取得できた組だけをワイド買い目にする。
- ワイドオッズが0件、または候補組のオッズがない場合は `prediction_tickets=[]` とする。
- `prediction_json.ticket_policy` に `wide_market_available` または `no_ticket_wide_odds_unavailable` を保存する。
- 順位算出は変更しない。
- 予想作成APIは `win,wide` を取得対象にする。

## 配置

| パス | 変更 |
| --- | --- |
| `src/jra_srb/jra_prediction_engine.py` | ワイドオッズ有無で買い目をゲートする |
| `src/jra_srb/app.py` | 予想作成時に `wide` を要求する |
| `tests/test_jra_prediction_engine.py` | オッズ有無の買い目テスト |

## 対象外

- Ω指数等の順位重み調整
- 履歴モデルの変更
- DBスキーマ変更
- ワイドオッズ取得失敗のスクレイパー改修
