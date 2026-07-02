# netkeiba odds combination 正規化 実装計画書

## 実装順序

1. `src/jra_srb/netkeiba_service.py` に `UNORDERED_NETKEIBA_BET_TYPES` を追加する。
2. combination 正規化関数を追加する。
3. `NetkeibaService._filter_odds` の `combination` 比較を正規化比較に変更する。
4. netkeiba odds API のテストを追加する。
5. 対象テストを実行する。
6. 全体テストを実行する。

## 実装詳細

### Step 1: 定数追加

`SUPPORTED_NETKEIBA_BET_TYPES` の近くに追加する。

```python
UNORDERED_NETKEIBA_BET_TYPES = {
    "bracket_quinella",
    "quinella",
    "wide",
    "trio",
}
```

### Step 2: 正規化関数追加

候補:

```python
@staticmethod
def _normalize_combination(combination: list[str], ordered: bool) -> list[str]:
    normalized = [
        str(int(item)) if item.isdigit() else item
        for item in combination
    ]
    if ordered:
        return normalized
    return sorted(normalized, key=lambda item: (0, int(item)) if item.isdigit() else (1, item))
```

必要なら `item.strip()` も関数内で行う。API 層ではすでに strip しているが、service 単体テストから直接呼ぶ場合に備えるなら関数内で行うほうが堅い。

### Step 3: `_filter_odds` 変更

候補:

```python
if combination:
    ordered = bet_type not in UNORDERED_NETKEIBA_BET_TYPES
    normalized = NetkeibaService._normalize_combination(combination, ordered=ordered)
    entries = [
        entry
        for entry in entries
        if NetkeibaService._normalize_combination(entry.combination, ordered=ordered) == normalized
    ]
```

`bet_type is None` の分岐は変更しない。

### Step 4: テスト追加

API テストに追加する場合は、既存の `NetkeibaFixtureProvider` override を使う。

追加観点:

- `wide` は `13,17` と `17,13` が同じ entry に一致する。
- `quinella` は逆順指定でも一致する。
- `trio` は `1,11,17` と `17,11,1` が同じ entry に一致する。
- `exacta` は `17,11` と `11,17` が別 entry になる。
- `trifecta` は `17,13,5` が一致し、`17,5,13` は同じ entry に丸めない。

fixture `netkeiba_odds_api_202605021211.json` で確認済みの代表値:

- wide `13,17`: `odds_min=5.1`, `odds_max=5.6`, `popularity=3`
- quinella `11,17`: `odds=7.6`, `popularity=1`
- trio `1,11,17`: `odds=20.7`, `popularity=1`
- trifecta `17,13,5`: `odds=470.5`

exacta は順序ありのため、存在する組み合わせを fixture から選ぶ。候補:

- `17,11`
- `11,17`

両方が fixture に存在する場合、それぞれ別 entry として返ることを確認する。片方しかない場合は、存在する順が1件、逆順が0件または別 odds になることを確認する。

## 実行するテスト

最小:

```powershell
cd D:\develop\jra-scr
.venv-win\Scripts\pytest.exe tests/test_api.py -q
```

netkeiba extractor も含める場合:

```powershell
cd D:\develop\jra-scr
.venv-win\Scripts\pytest.exe tests/test_netkeiba_extractors.py tests/test_api.py -q
```

最終:

```powershell
cd D:\develop\jra-scr
.venv-win\Scripts\pytest.exe -q
```

## リスク

- 順不同券種で entry の返却順までソートしてしまうと、既存レスポンスの見た目が変わる。比較用だけ正規化する。
- `bet_type` 未指定時に全 entry を加工すると不要な差分が出る。未指定時は現状維持する。
- JRA 公式側に同名の odds 処理があるため、変更対象を `netkeiba_service.py` に限定する。
