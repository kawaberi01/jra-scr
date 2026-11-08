# 現行仕様と要件との差分

確認日: 2026-10-15。静的調査。稼働確認はprogress/005の20:59 JST記録を参照。

## 確認できた経路

| 対象 | 現行挙動・根拠 | 必要な変更 |
|---|---|---|
| API/SQL | `storage.py:22` factory、`:30` open_analysis_read。SQL業務schemaはapi_runtime | API経路は保持、研究側の履歴schema readerを分離 |
| SQL接続 | `sqlserver_db.py:224` 接続はreader/writer双方の設定とbaseline readyを前提、`:185` compile_sqlは許可業務表だけ | arbitrary SQLをAPI接続へ追加せず、研究専用のSELECT allowlistを持つ |
| 長期研究 | inspect_data.py:25,36-57とinventory。prediction-full-20261008、snapshot31 | verified版を開始時に固定、全結合に版を適用 |
| 時点特徴量 | coverage.feature_sample、inventory.coverage_columns。46項目、23マスク、T30/T10 | 定義・mask・品質をmanifestに固定。旧モデルへそのまま投入不可 |
| O1/O2旧生成 | `build_jra_o1o2_asof_dataset.py:28` SQLite、`:376` 年別gzip、`:616` 3DB引数 | ファイル生成を通常研究の必須段階にしない |
| cross/movement | `evaluate_jra_o1o2_movement.py:20` 15履歴、`:77` float必須、`:96` JSONL読取。cross_pool:33,59-63 | メモリの共通入力、profile別条件、別版学習 |
| V91 | evaluate_jra_v91.py:25 制約、:41 ファイルhash監査。jra_v91_model.py:45 数値必須、:93 交互作用 | 全43履歴・距離等の契約を確認。監査機能を消さずSQL監査へ置換 |
| ten/second | ten_trials_model.py:36 V91+履歴+文脈+馬連。second_ten.py:26 追加ラベル、:41 fold成果物 | 券種・各仮説・foldの意味を保持、学習入力を結果と分離 |
| history学習 | train_jra_history_model.py:19 --db、:35 ファイルhash、:43 特徴量gzip保存 | SQLでも旧DBファイル必須になる処理を除きメモリ学習へ |
| saved分析/overlay | 050参照。いくつかopen_analysis_readへ既に変更 | factory利用だけで列・型・時刻・精算互換を保証しない |

## SQL側のデータ構造

- `history.races/entries/labels/payouts`、`prediction.features_asof`、`market.odds_asof_index`は研究元のsnapshotを保持する。
- `history.race_identity_map`には元ID・API ID・unified ID・出典・検証状態がある。runtime新IDが自動で登録される根拠はない。
- `odds_asof_index.entries_json`に時点別の解析済み明細がある。初期研究で巨大parsed_entriesとのJOINは不要。
- SQL inventoryに`raw.master_contents.compressed_payload/codec/sha256/raw_length`を確認。SQL内に原本本文があるが、全件のcodec解凍・SHA照合は未実施。
- `market.parsed_observations.source_sha256`とasofのcontent_sha256の同一性は未確認。同じSHAという名前だけで結合しない。
- 追加レビューで生成元`D:/develop/jra-van-data/tools/build_jv_prediction_db.py:1298-1319`を確認。official_win_settlementはHR的中0/1フラグ。実払戻円は同`:633-657`のhistory.payouts（market=win、slot_status=published）。ラベルを金額に使わない。
- SQL inventoryの索引を確認するとlabelsはrace_key索引が無く(snapshot,source_rowid)一意索引のみ。他のraces/entries/payouts/features/asofにはunified race hash索引がある。labelsには040の有界keyset例外を設ける。
- 通常writerは`api_runtime`、移送用currentビューは自動更新されない。receiptはrace_card/odds/race_resultの入力を同一transactionで保存する。

## データ品質と性能の限界

記録時点でhistoryは2003-01-05〜2026-10-04、特徴量は2003年10月〜2026-09-27。10/12のAPIレース24件のうち結果束を確認できたのは1件。最新全開催網羅は未検証。

T30 O1/O2完全79,263レースとT10 78,320レースは同一集合ではない。履歴馬ID・当日発走時刻は未証明のためstrict_live_replay=false。generated featuresの不足を事後属性で無条件に埋めない。

特徴量全件状態集計は90秒設定下でOperationalError。原因不明、後続全件重複・払戻slot集計は未実行。大規模JOINや全4.7億行再走査を前提にしない。

## 互換性で確定した差

旧履歴15項目のうち、SQLで利用候補は6、意図NULLは9。さらに旧生成は馬名キーと結果頭数、SQL生成は馬ID・O1 rosterを用いるため、非NULL項目も旧入力の同一性を保証しない。比較の初期profileは新名称で再学習し、旧artifact・成績を継承しない。

## 未実施を成功扱いしない項目

研究用単一loginで全必要schemaのSELECT可否、固定31の物理不変性、snapshot isolation設定、raw解凍、全研究族の必要項目充足、runtime新ID対応・全券種精算。これらは040/060の実装時ゲートで検出する。初期M1は既存features/labels/asofだけで成立するためrawやruntimeの未検証と切り離せる。
