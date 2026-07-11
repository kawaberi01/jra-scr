# 005-jra-prediction-materials-api 現行仕様整理

## 1. 現在できていること

| 項目 | 現行入口 | 実コード上の状態 |
| --- | --- | --- |
| 開催一覧 | `GET /meetings/{date}/{course}` | `JraService.get_meeting` が60秒TTLで返す。 |
| 出馬表 | `GET /races/{race_id}/card`、開催座標版 | 馬番、枠、馬名、性齢、斤量、騎手、調教師、馬体重、オッズ等のモデルを持つ。 |
| オッズ | `GET /races/{race_id}/odds`、開催座標版 | 単一・複数券種、組み合わせ絞り込み、refreshに対応。 |
| 結果・払戻 | `GET /races/{race_id}/result`、開催座標版 | `RaceResult` は着順、馬番、馬名、騎手、時計と払戻を返す。 |
| netkeiba補完 | `/netkeiba/races/{race_id}/result|odds` | 現状は結果とオッズのみ。data_top・馬柱取得はない。 |
| SQLite保存 | `AnalysisSQLiteStore` | races/runners/odds/resultと、詳細なnetkeiba結果を保存できる。 |
| 南関分析 | `/nankan/...` | trend、best-time、closing-speed、style-profile、pattern、leading jockeys、bundleがある。 |

## 2. 現在不足していること

- JRA向け `odds-summary`、`trend-context`、`best-time-lite`、`closing-speed-lite`、`style-profile-lite` がない。
- JRA向け予想材料をまとめる `prediction-bundle` がない。
- netkeiba data_top、競馬ラボ馬柱、ウマニティ出馬表の公開範囲を取得するProvider/Extractorがない。
- JRA内部race_idは `YYYYMMDD + course + race_no` の12桁で、netkeibaの12桁IDとは意味が違う。
- JRA内部race_idから開催回・開催日を復元できず、netkeiba/ウマニティURL生成には `meeting_no` と `meeting_day` が必要。
- JRA公式 `ResultEntry` は上がり、通過順、枠、調教師、人気を持たず、単独では精密な脚質・当日バイアスを算出できない。
- SQLiteのJRA公式 `result_entries` も上がり・通過順を保持しない。

## 3. 現行の呼び出し経路

```text
FastAPI app.py
  -> JraService
      -> Provider / navigation
      -> extractors
      -> TTLCache
  -> Pydantic model
```

南関bundleはcardを先に取得し、共有contextを作り、独立componentを`asyncio.gather`でまとめる。JRA版もこの配置と呼び出し方を踏襲する。

## 4. データソースごとの現状

| ソース | 現行対応 | 今回使う候補 | 注意点 |
| --- | --- | --- | --- |
| JRA公式 | 対応済み | card、odds、当日確定結果 | 正データ。外部補助値で上書きしない。 |
| netkeiba | result/oddsのみ | `race/data_top.html` の匿名公開分析 | 既存IDと異なる。公開範囲だけ抽出する。 |
| 競馬ラボ | 未対応 | `db/race/{code}/umabashira.html` の馬柱・公開指標 | 1レース1ページを上限にする。 |
| ウマニティ | 未対応 | `racedata/race_8.php` の匿名公開値 | 無料会員限定・有料値は対象外。 |

## 5. 現行テスト

- `tests/test_api.py` にJRA card/odds/result、netkeiba、南関bundleの代表APIテストがある。
- `tests/test_nankan_service.py` にtrend時点制御、best-time、closing-speed、style-profile、bundleの再利用テストがある。
- 外部live取得に依存しないfixture-firstの流儀がある。

## 6. 要件との差分

| 要件 | 現状 | 必要な変更 |
| --- | --- | --- |
| 事前一括収集なし | card/oddsのみ可能 | 公開レースページから近走範囲を取得する。 |
| 少数アクセス | netkeiba result/oddsはレート制御あり | 3ドメイン共通の1ページ/レース制約とTTLを追加。 |
| 南関相当の材料 | JRA分析APIなし | lite契約とcomponent statusを追加。 |
| 一括API | 南関のみ | JRA PredictionServiceとbundle endpointを追加。 |
| 欠損時の継続 | 個別APIは例外中心 | optional componentはpartial responseにする。 |

## 7. 未確認事項

- 3サイトの対象HTMLについて、匿名状態で取得できるフィールドと安定したselectorはfixture採取時に確定する。
- 公開ページに通過順がなければ `style-profile-lite` は `unavailable` とする。馬ごとの追加ページ巡回はv1で行わない。
- 第三者サイトの利用条件が変更された場合、そのProviderを無効化できる構成が必要。

