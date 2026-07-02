# netkeiba odds combination 正規化 実装指示書

## 改修目的

`GET /netkeiba/races/{race_id}/odds` の `combination` 絞り込みで、順不同券種の逆順指定を一致させ、順序あり券種の順序性は維持する。

## 変更してよい範囲

- `D:\develop\jra-scr\src\jra_srb\netkeiba_service.py`
- `D:\develop\jra-scr\tests\test_api.py`
- 必要なら `D:\develop\jra-scr\tests\test_netkeiba_service.py`

## 変更してはいけない範囲

- JRA 公式 API 側の `service.py`
- JRA 公式 provider / extractor
- netkeiba provider の取得 URL やリトライ仕様
- netkeiba extractor の payload parse 仕様
- fixture の内容変更
- DB 保存仕様

## 実装指示

1. `netkeiba_service.py` に以下を追加する。

```python
UNORDERED_NETKEIBA_BET_TYPES = {
    "bracket_quinella",
    "quinella",
    "wide",
    "trio",
}
```

2. combination 正規化関数を追加する。

要件:

- `05` は `5` にする。
- `ordered=True` では順序維持。
- `ordered=False` では数値昇順でソート。
- 非数字文字列が来ても例外にしない。

3. `_filter_odds` の combination 比較を次の考え方に変更する。

- `bet_type is None` は現状維持。
- `ordered = bet_type not in UNORDERED_NETKEIBA_BET_TYPES`
- query 側と entry 側の両方を同じ関数で正規化して比較する。
- 返却する `entry.combination` 自体は書き換えない。

4. テストを追加する。

必須ケース:

- wide:
  - `combination=13,17` と `combination=17,13` が同じ entry に一致する。
- quinella:
  - 逆順指定でも一致する。
- trio:
  - `1,11,17` と `17,11,1` が同じ entry に一致する。
- exacta:
  - `17,11` と `11,17` は別扱いになる。
- trifecta:
  - `17,13,5` は一致する。
  - `17,5,13` は `17,13,5` と同じ entry に丸めない。

注: ユーザー例の `1,2,3` / `3,2,1` は fixture に存在しない可能性があるため、fixture に存在する `1,11,17` / `17,11,1` で同じ仕様を検証してよい。

## 受け入れ条件

- 順不同券種で逆順指定が一致する。
- `exacta` / `trifecta` は順序指定を維持する。
- `win` / `place` は単一要素として従来通り動く。
- `bet_type` 未指定時の全件返却が壊れていない。
- 既存 JRA API 側のテストが壊れていない。

## 実行する確認

対象テスト:

```powershell
cd D:\develop\jra-scr
.venv-win\Scripts\pytest.exe tests/test_api.py -q
```

全体テスト:

```powershell
cd D:\develop\jra-scr
.venv-win\Scripts\pytest.exe -q
```

## 禁止事項

- JRA 公式 API 側の `_filter_entries` に同じ変更を入れない。
- entry の `combination` 表示順を変更しない。
- fixture を都合よく書き換えない。
- ライブ netkeiba に依存するテストを追加しない。
