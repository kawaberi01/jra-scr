# 010-major-venue-model 実装仕様書

## 0. 最初に読む要約

- 対象機能: 東京・中山主要場モデルの監査、検証、採否、運用統合。
- 改修目的: 未来情報を使わず、再現可能な正式順位と買い目判断を提供する。
- 現行仕様: v89は候補のままAPIに露出し、買い目はshadow only。
- 最重要注意点: holdout開封前に契約をJSON/Markdownへ固定し、開封後は条件を変えない。

## 1. 実験契約

- データ監査で参照済み期間を列挙し、未使用期間のみholdout候補とする。
- 時系列を development（学習・候補作成）、validation（候補/閾値固定）、final holdoutに分離する。
- 1世代最大10候補、最大3世代。候補ID・特徴量・閾値・生成理由を実行前に登録する。
- baselineは v89、単純人気、既存履歴モデル。順位とticket policyを別々に比較する。
- final holdoutの採用条件は最低30買い目、ROI>=1.00、no-max ROI>=1.00、軸3着内率>=0.45。上位3除外ROI<0.90は高配当依存として不採用/継続審査とする。
- 東京・中山それぞれの標本・ROI・no-max・上位3除外・軸/相手3着内率・的中率・対象率を必須表示する。片場が極端に不安定なら合算合格だけで採用しない。
- 30買い目未満は `insufficient_sample` とし正式採用しない。

## 2. データ監査仕様

- `races`, `runners`, `result_entries`, `payouts`, 近走・ラップ・オッズスナップショット関連表のschema、期間、場別件数、欠損率、重複を記録する。
- 特徴量ごとに「発走前に取得可能」「過去レース確定後のみ」「当日スナップショット時点依存」「使用禁止」を分類する。
- 対象race_date以上のresult/payout/lapを履歴特徴へ入れないテストを設ける。
- オッズを使う券種は対象時点以前の実取得スナップショットがある場合だけ候補化する。推測・結果ページ由来代替値は購入判断に使わない。

## 3. モデル出力契約

- `theory_version`, `model_status`, `history_as_of`, `ranking`, `head_candidates`, `axis_candidates`, `partner_candidates`, `ticket_candidates`, `ticket_status`, `limitations` を返す。
- 各順位に馬番、馬名、スコア、根拠を持たせる。確率・校正済み期待値・利益保証とは表現しない。
- `ticket_candidates` は券種、組合せ、参照オッズ、オッズ取得時刻、根拠を持つ。単勝、ワイド、馬連、3連複は該当実オッズがある場合だけ生成する。
- 夏場コースは既存V90経路を維持する。東京・中山だけを採用版またはシャドー版へルーティングする。

## 4. 新馬・障害

- 障害は一般平地と混ぜず、初期版では除外する。
- 新馬は過去走特徴が成立しないため一般モデルから除外し、単純人気baselineの診断だけを別集計する。
- 除外理由を出力・評価に残す。

## 5. 配置候補

- 評価/監査: `.workstate/jra-srb/tokyo-nakayama-major-model/` 配下の再実行可能スクリプトと成果物。
- 本番順位・候補契約: `src/jra_srb/jra_v_theory.py`。
- API: `src/jra_srb/app.py` の既存model-comparison契約を後方互換な追加項目で拡張。
- 保存: 既存のpre-race snapshot / prediction recordの流れを再利用する。
- tests: 既存 `tests/test_jra_v_theory.py` とAPI/予想保存の既存テストへ追加。

## 6. エラー・運用

- DB/オッズ不足は推測せず `unavailable` / `no_candidate` と理由を返す。
- モデルstatusは `adopted`, `shadow`, `rejected` のいずれか。標本不足は `shadow`。
- ロールバックはルーティング定数をv89 `not_final`へ戻せる局所変更にする。

## 7. テスト観点

- target date当日・未来の結果追加で順位が変わらない。
- 同一DB・同一as-of・同一入力の出力が一致する。
- 東京/中山は新status、夏場はV90のまま、中京等は既存挙動を維持する。
- オッズ不足時に券種候補を出さない。
- 新馬・障害の分離、場別・セグメント別集計、30買い目判定を確認する。

## 8. 要確認事項

- DB監査後に未使用holdoutが存在するかを確定する。
- 既存pre-race保存経路がV理論詳細を保存できるかを実装前に再確認する。

