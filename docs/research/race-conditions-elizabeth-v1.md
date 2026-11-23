# エリザベス女王杯の既知条件予想ツール

同じ重賞の過去の全出走馬と事前履歴を対応させ、条件別実績、各馬の参考順位、過去年の時系列検証を作ります。反復的な機械学習、外部取得、購入、通常予想の置換は行いません。

## 出力

- `dataset.json`: 必要な解析済み対象行と対象馬の保存履歴。原文本文や秘密は含めません。
- `comparisons.csv`: 各年・各馬・条件・結果。取消等も理由付きで残します。
- `conditions.csv`: 年ごとの全カテゴリの該当・非該当数と3着以内数。
- `predictions.json`: 過去年について、以前の年だけの集計から出した推定3着内確率と理由。
- `metrics.json`: 一律基準、固定の全条件、各条件群を外す比較の年別・開催場別結果。
- `report.md`: 比較結果と評価理由の読みやすい一覧。
- `coverage.json` / `manifest.json`: 欠損、来歴、設定と入力・出力・コードのSHA。

CSVはExcelの日本語表示用にUTF-8 BOM付き、JSONとMarkdownはUTF-8です。出力フォルダーは毎回未使用の名前を指定します。

## 実行

ワークスペースrootから実行します。研究reader設定は既存の `JRA_SRB_RESEARCH_READER_CONNECTION_STRING` または `JRA_SRB_RESEARCH_ENV_FILE` を使います。秘密をコマンドや資料へ直接書かないでください。別worktreeで保存済みの設定ファイルも、明示した参照先として利用できます。

```powershell
# 必要な場合だけ、既存の研究reader設定ファイルのパスを指定します。
$env:JRA_SRB_RESEARCH_ENV_FILE = '設定ファイルの絶対パス'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'

uv run python scripts/run_jra_race_conditions.py export --output artifacts/jra_research/elizabeth-export-01
uv run python scripts/run_jra_race_conditions.py analyze --dataset artifacts/jra_research/elizabeth-export-01/dataset.json --output artifacts/jra_research/elizabeth-analysis-01
```

exportはSQL reader専用、analyzeは保存データだけで動きます。設定は `configs/research/race_conditions_elizabeth_v1.json` です。固定したパラメーターを結果に合わせて変更する場合は別版・別研究として記録してください。

## 将来カード

カードの許可属性は、競走の `race_key`（日付8桁＋場2桁＋競走番号2桁）、`race_date`、`race_name`、`venue_code`、`distance`、`track_code`、timezone付き `observed_at` / `start_at` と `runners` です。

各馬は `horse_id`（登録ID10桁）、`horse_name`、`horse_no`、`age`、`sex`（牝はコード2）、`frame_no`、`weight_carried`（kg）、`status`（active/excluded）を持ちます。任意属性は `jockey`、`trainer`、独立した出馬表等で確認した `latest_race_date` です。当該着順や払戻を入れると拒否します。出走馬・取消や公開時刻は実際に確認したものを入力してください。

```powershell
uv run python scripts/run_jra_race_conditions.py export --card '事前カード.json' --output artifacts/jra_research/elizabeth-with-card-01
uv run python scripts/run_jra_race_conditions.py predict --dataset artifacts/jra_research/elizabeth-with-card-01/dataset.json --card '事前カード.json' --output artifacts/jra_research/elizabeth-prediction-01
```

カード付きexportでは、新たな出走馬IDも既存DBから調べます。カードを追加せず、昔の出走馬だけのexportを流用すると新しい馬の履歴が不足し得ます。元の固定版にない走りを外部から自動補完することはありません。

将来の出力は常に `reference_only` です。最新性の申告とDB内直近日を並べますが、公表時点・全履歴の独立検証が完了したことにはしません。過去の最終オッズを前日の入力に転用せず、初版の確率にはオッズを使用しません。

## 算出と説明

基本属性、前哨戦経路、直近成績と間隔、条件変更、過去実績の5条件群を等重みで扱います。同名競走での条件率を20件分の基準率へ縮約し、同場の少数例は全場へ寄せます。未観測の条件は中立です。重みの探索や、成績の良かった条件だけの事後選択はしません。

各馬の推定3着内確率は合計3へ合わせた周辺確率です。勝率・組合せ馬券の確率・検証済みの校正値ではありません。説明のptは、当該条件群を外して全馬の確率を再計算した差です。因果効果や単純加算できる寄与ではありません。

## 検証の読み方

過去5開催を満たす年から順次、以前の年だけで集計して評価します。二値Brier/logloss、上位1頭の3着内率、上位3頭の好走馬捕捉数を一律3/頭数と比較します。開催場別の結果と全ての除去比較も保存します。同確率の馬番順表示を技能と見なさず、一律基準の順位指標は無作為選択の期待値です。

過去属性と実出走集合は事後版です。地方・海外等を含む履歴の網羅、当時の発表時点、将来の優位性・収益は未証明です。保存開始直後の履歴欠損も残ります。好走馬が3頭ではない同着年等は記述表へ残し、合計3の確率評価からは外します。京都と阪神、前哨戦の名称・日程変更を同一条件と決め付けません。

## 確認コマンド

2026-11-08の実行では2003〜2025の23開催392行と保存履歴5,913行を取得し、関連RA3,535競走を照合しました。過去5開催後の18開催310行で全条件のBrierは0.140648、一律基準は0.143733でした。これは後ろ向きの参考評価で、2026年予想や市場との比較ではありません。

保存済み結果は [検証レポート](../../artifacts/jra_research/elizabeth_conditions_v1_20261108_analysis/report.md)、実装契約は [実装仕様書](../../.workstate/jra-srb/context-first-research/spec/010-実装仕様書.md) です。対象と関連テストは51 passed / 2 skipped、指標と4,194件の条件根拠は保存CSV/JSONから独立再計算して一致しました。

```powershell
uv run pytest -q tests/test_jra_race_conditions.py
uv run python scripts/run_jra_race_conditions.py --help
```

SQLや入力契約の不成立では非0終了し、作成済み出力内にfailureと照会診断を残します。原因を確認するまで後続analyze/predictへ進めないでください。出力先の既存フォルダー拒否は元の成果物を変更しません。

## 全32構成の精査（2026-11-13追加）

```powershell
uv run python scripts/run_jra_conditions_search.py --dataset artifacts/jra_research/elizabeth_conditions_v1_20261108_export_v4/dataset.json --output artifacts/jra_research/elizabeth-subsets-new
uv run pytest -q tests/test_jra_conditions_search.py tests/test_jra_race_conditions.py
```

仕様は `.workstate/jra-srb/context-first-research/spec/040-全32構成の精査と時系列選択.md`。5群の係数1/5を保ったまま、0〜5群の全32通りを比較します。重みや条件区切りの最適化ではありません。過去の検証5開催以上から構成を選び、翌年に適用した13開催を、同期間の全群固定/一律と比較します。

結果は [全32構成レポート](../../artifacts/jra_research/elizabeth_subsets_20261113/report.md)。18開催でBrier最小は全5群P31、次点は条件変更なしP23。各群を足す全16対では全て確率損失が改善しました。1開催ずつ除いた首位はP31が15回、P23が3回。全体では5群固定を保持する判断です。

過去年だけで選び直した13開催のBrierは0.141350、全群固定は0.141127、一律0.144167。選び直しが全群固定を上回る根拠は得られませんでした。全体候補を毎年入れ替える実装は通常予想へ反映しません。阪神3開催の全群Brier0.141161は一律0.140954より悪く、京都の傾向を全場の優位と呼びません。

最上位馬の3着内率が最大なのはP21（基本属性＋直近成績と間隔＋過去実績）で58.3%ですが、Brierは0.141936と全群より悪く、主基準を変えて採用しません。今回は全構成の同確率を公平な無作為選択の期待値で評価するため、一部順位指標は初版の馬番順表示による値と異なり、実的中回数が整数でない期待値も含みます。予測確率/Brier/loglossの初版との整合は確認済みです。

32構成は各18開催・計576予測、9,920行の確率を保存済み。選択過程と全候補はselection.json、全場/場別指標はsummary.json、全年度CSVと予測JSON、追加/年除外診断、manifestも保存します。新旧対象テスト38件成功。独立検算では予測モジュールを使わず全確率・指標・13件の選択とSHAを照合しました。
