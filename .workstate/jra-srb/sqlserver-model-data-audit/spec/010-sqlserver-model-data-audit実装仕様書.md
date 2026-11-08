# SQL Server共通研究基盤の実装仕様

作成日: 2026-10-15。状態: 対話レビュー反映済み・実装前。優先順位: 利用者指示 → 本仕様と040/050/060 → 過去提案。

## 1. 入出力と実装範囲

入口は新規`scripts/run_jra_research.py`。SQL正本への読取り、入力契約の検査、特徴量生成/再利用、学習・予測・共通評価を行い、`artifacts/jra_research/runs/<run_id>/`へ研究成果を保存する。DB・APIの変更や収集は行わない。

新規配置は既存のflat module構成に合わせる。

| ファイル | 責務 |
|---|---|
| `src/jra_srb/jra_research_contracts.py` | 設定、版、InputRace、OutcomeBundle、FeatureContract、エラー、profile登録情報 |
| `src/jra_srb/jra_research_reader.py` | mssql-pythonのreader接続、allowlist SELECT、採用版解決、分割抽出、入力digest |
| `src/jra_srb/jra_research_sources.py` | frozen/runtimeの採用規則、ID、時点、coverage、再現可否。SQL以外へfallbackしない |
| `src/jra_srb/jra_research_features.py` | profile別の特徴量、既存定義再利用、必要履歴範囲、マスク/型/順序 |
| `src/jra_srb/jra_research_evaluation.py` | 日付分割、校正・精度・精算・比較母集団・集計 |
| `src/jra_srb/jra_research_artifacts.py` | 許可成果物、manifest、モデル契約、atomicな完了公開 |
| `src/jra_srb/jra_research_profiles.py` | 初期profileと050の族adapter。ファイルが大きくなる時だけ族別分割 |
| `scripts/run_jra_research.py` | CLI。既存API/CLIをimportして起動しない |

依存は既存mssql-python、numpy、scipy、scikit-learn、joblib等を再利用。analysis extrasの既存定義を確認し、不足依存を勝手に恒久追加しない。不要なORM・別DB・DI基盤は追加しない。

## 2. CLI契約

共通設定はJSON。`schema_version=1`、`profile_id`、開始/終了日、`source_policy`、`horizon`、学習/調整/評価の期間、seed、モデル/購入設定、quality要求、batch上限を持つ。source_policyは040の固定IDを明示する。未知キー、重複期間、T30にT10列が入る構成、意図NULLの補完指定は入力エラー。

| コマンド | 契約 |
|---|---|
| `profiles` | 050の族・profile・必要capability・対応状況を表示。接続不要 |
| `preflight --config <json>` | 接続・権限・schema・版・既存索引・分離レベル・必要capabilityを読取検査。SQL本文/rawを出力しない |
| `coverage --config <json>` | 対象レース集合、採用/除外/不足、重複・時刻・精算状態の集計。学習なし |
| `run --config <json>` | 検査→固定入力→学習/評価→成果物。途中不足を除外した理由を保存 |
| `replay --run-id <id>` | 元manifestの具体版・キー・契約で再読取。入力digest不一致なら学習せず終了 |
| `score --model <path> --race-key <key> --config <json>` | SQLから予測用入力だけ生成。feature contract不一致は拒否。結果を読まず、final/rank/精算の有無を採否に使わない |

`--db`、`--data-root`、`--race-json`による研究入力指定、元データexportオプションは新CLIへ設けない。モデル/設定/予測成果物のファイル入力は許す。SQLの切断時も他経路へ後退しない。

終了コード: 0=当該コマンド成功、2=設定/モデル契約不正、3=接続/権限/schema/版不一致、4=必要データ・整合性・quality不足、5=replay入力変更、1=予期しない実行エラー。coverageコマンドは不足があればreport保存のうえ4。runは0でも当該profileの完了だけであり全体完了ではない。

## 3. 接続とデータ契約

- `JRA_SRB_RESEARCH_READER_CONNECTION_STRING`を必須とし、DBは`jra_unified`固定。秘密値をCLI・ログ・manifestへ書かない。APIのruntime.envやwriter設定を自動で読み込まない。
- 操作性のため同じreaderキーだけを`data/storage/research.env`に保存できる。環境変数を優先し、ファイル変更指定は`JRA_SRB_RESEARCH_ENV_FILE`。他キー/writer設定は拒否する。APIの設定とは別ファイル。
- 自動DB起動・DDL・GRANT・管理者接続なし。接続前後にDB名、db_owner/sysadmin、対象表へのSELECTとDML/DDL権限を検査。過剰権限は拒否する。研究readerが未準備なら必要権限表を出して3で停止。
- 接続は研究側の専用contextで所有し、SQLは固定allowlistとparameterだけ。任意SQL入力や動的テーブル名を許さない。040に参照表・列・sourceを定義する。
- APIの`SqlServerConnection/compile_sql`を拡張しない。既存driverと設定を扱う形式だけ再利用し、API用writer資格を研究側へ渡さない。

## 4. 最初のprofileと有学習モデル

`cross_pool_sql_masked_v2`を新設。snapshot31のT30に限定し、単勝のmarket baseline、basic8特徴、cross9特徴を同一レース・同一馬集合で比較する。旧cross_pool/joblibとは非互換。旧モデルの数値再現・成績改善・本番採用をM1完了条件にしない。旧研究の意味互換は050の最終DoDで別に検証する。

固定特徴順:

1. log_win_odds
2. normalized_win_market_share
3. horse_log_starts
4. horse_win_rate
5. horse_top3_rate
6. horse_finish_strength
7. horse_course_top3_rate
8. days_since_last_scaled
9. log_o2_marginal_over_o1_share（crossのみ）

意図NULLの9履歴項目は005参照。上記特徴に予期しないNULL・非有限値があるレースは理由付きで除外し、列削除や0補完を自動で行わない。23マスクと利用項目が交差すれば契約違反。生成定義が違うデータの混合を拒否する。

学習: 既存cross_poolと同じStandardScaler→LogisticRegressionを利用。初期はC=1.0、solver=lbfgs、max_iter=1000、seed=42、thread制約を記録。各馬等重み、sample_weightなし。fitはtrainだけ、devは観測用でモデル/閾値の自動選択をしない。収束失敗は成功にしない。勝ち馬をbinary y=1としてfitし、予測確率はレース内で正規化して精度指標と購入の両方へ渡す。確率が非有限または和<=0なら停止。dead heatの精度用targetは勝ち馬間の均等配分、精算は実払戻をそのまま使う。旧報告と指標の意味が変わるため新report版にする。

評価・購入の初期固定条件: 1レース最大1頭、2.0<=時点単勝オッズ<=30.0、正規化予測確率×時点オッズ>=1.05の候補から期待倍率最大、同値は馬番昇順。1点100円。baseline/basic/cross全て同じ規則・対象集合。見送りは0点として集計する。対象集合を購入結果で絞らない。

baselineは逆数オッズ正規化なので期待倍率が全馬同じになり、購入0件も正常。baselineの0点を失敗扱いして閾値を変えない。初期scoreは固定版内の保存済み入力を採点する機能で、将来開催のライブ予測対応を保証しない。

期間の既定はtrain=2004-01-01〜2023-12-31、dev=2024年、evaluation=2025年。M1は既存featuresを使い、生成履歴の起点・条件をmanifestで照合するだけで再計算しない。履歴再計算profileだけ必要な前期間を別に読む。2026年は過去研究使用済みで未使用テストと称さない。これらの期間も過去に全く未参照だった保証はなく、報告はretrospective validationとする。最小smokeの期間短縮は可能だが期間の重複は不可、1レースを分割しない。

## 5. 入力と結果を分離する契約

InputRaceはrace_key/source/snapshot/horse_no/horizon/cutoff/known_at/feature values/marketだけを保持する。結果rank、払戻、最終SE、retrospective属性、評価対象外理由はモデル関数へ渡さない。

OutcomeBundleは同一採用版のrank・異常状態・返還・払戻・根拠hashを保持。学習器へ渡すのは目的変数、予測器へ渡さない。事後の芝/距離などを使う分析sliceはdescriptive_onlyと表示し、入力や対象選択には使わない。050の旧モデル再現用に事後属性が必須なら、`retrospective_compatibility`という別quality/profileでのみ扱い、通常asofモデルと混同しない。

InputRace・OutcomeBundle・coverageを別のdataclassで持ち、全rawを入れた巨大dictを予測へ渡さない。プロフィールが必要とする時点・券種・ロスターを050/040の契約から決める。

## 6. 共通評価と精算

日付・レース単位でtrain/dev/evaluationを分離。前処理と特徴量選択をfitする範囲もtrainだけ。T30単独profileをT10の有無で選別しない。movement profileだけ明示的に両時点の共通集合を使う。

単勝の実払戻は同snapshotの`history.payouts`でmarket=win、slot_status=published、payout_yen>0の行から取得する。selection_rawを2桁馬番へ検証付き正規化し、labelsのhorse_noとhr_sha256を照合する。payout_yenは100円当りの払戻円として扱い、M0では同rowのHR由来9桁金額文字列payout_rawを整数化してpayout_yenと少数照合する。raw本文解凍とHR直接照合はM2のraw capability検証へ分離する。`history.labels.official_win_settlement`は0/1のHR的中フラグであり、払戻金額・倍率ではない。rank=1/HR公表勝馬/同フラグの整合検査だけに使う。正常かつ公式結果束が完全な非勝馬の払戻は0、同着は馬ごとの公式払戻をそのまま使う。

refundは払戻100円、賭金100円、net0、予測精度の目的変数から除外。中止/未確定/不明精算は賭金対象にしない。取消時点と確定返還の区別ができないレースは初期profileから除外する。非返還の異常馬もrank NULLを敗戦と推測せず、初期profileはabnormal_code=0かつ正常rankの全ロスターが検証できるレースを用いる。

複合券はhistory.payoutsのvalid slot・組合せ正規化・返還・同着を検証した券種だけ有効化。単勝ラベルから馬連払戻を推定しない。券種未対応profileは4で止まり、全体完了にはしない。

報告: 候補/採用/除外のレース数と馬数、期間別カバー率、比較共通集合、race平均log loss/Brier、校正bin、購入点数・賭金・払戻・net・回収率・的中率・最大累積損失と最大drawdown。的中率の分母は購入点数、回収率は払戻/賭金、0件時はnull。年度/競馬場別も出す。

精度はレースごとCE=-sum(y_i*log(clip(p_i,1e-15,1)))、Brier=sum((p_i-y_i)^2)を計算しレース等重み平均。校正は固定10bin [0,.1),...,[.9,1]へ全馬を入れ、平均p/平均target/countを保存し空binはnull。net累積C_0=0、C_t=C_(t-1)+払戻_t-賭金_t。最大累積損失=max(0,-min C_t)、最大drawdown=max_t(max_(s<=t) C_s-C_t)。順序は開催日・race_key昇順で固定するが、同日の実発走順とは限らないと表示する。

## 7. 保存と再現

唯一の通常保存rootは`artifacts/jra_research/runs`。run_idはUTC日時+UUID。既存runの上書き禁止。完了前status=running、成功時のみcomplete、失敗時failedと非秘密エラー分類を保存し、モデルを採用済みへ自動昇格しない。

許可ファイル: config.json、manifest.json、coverage.json、excluded.jsonl（キー+理由のみ）、metrics.json、predictions.jsonl.gz、failure.json、およびprofile registryが事前宣言するモデルartifact（joblib/cbm等）とfold/校正/ensembleのmetadata。M1のモデル名はmodel_basic.joblib/model_cross.joblibに固定する。他profileは050の各variantに保存名・形式を対応付け、任意path指定を許さない。predictionsはキー・モデル版・score・購入・実精算のみ。raw本文、odds明細全量、全特徴量ベクトル、raw SQL結果は保存禁止。モデルのscaler統計・係数は許可する。

実装で追加した診断用preflight.jsonも許可する。予測SHAは保存時に逐次計算し、全予測JSONの一括複製をメモリ上にも作らない。replayは入力に加え予測・評価SHAも照合し、コード変更があればmanifestへ明記する。

manifestは具体source/snapshot、query/feature/model契約版、入力キー集合と内容digest、選択receiptキー、schema digest、quality、抽出整合性、分割、seed、依存版、Git HEADと対象コード内容hash（dirty時必須）、件数と除外理由を持つ。秘密/個人会話は持たない。将来の完全復元の保証は040による。

replayはsnapshot/receiptの再選択後、入力全内容digest一致を必須とする。source_currentの再解決、別版への置換、差分を隠して再学習はしない。完全なold版が残らない場合はreplay不可、通常runの新IDとしてしか扱えない。

## 8. 性能・エラー・完了

初期抽出は1か月か最大500レース/チャンク、horse明細は選択race_keyのみ、cursor.fetchmany上限10,000行。labelsだけは040の例外routeで固定snapshotを1回keyset走査し、対象キーのOutcomeのみ保持する。M0で索引付きquery routeを検証する。キーを500件にしただけで巨大表のscanが無いとはみなさない。全件fetchall・N+1・任意巨大IN・巨大raw JOIN禁止。SQL実行timeout既定30秒、設定上限90秒、メモリ予算既定2GiB・最大候補行数を設定に持ち、超過時は学習前停止。永続cacheや索引追加で迂回しない。

timeout/driver障害で依存処理を止める。SQLSTATE・例外型・query_id・期間・経過時間を秘密除去して記録し、自動再試行しない。小さな期間への変更は新実行として記録。接続文字列やSQLパラメータ本文はログへ出さない。

M1/全体のDoD・試験は020/050/060。未確認事項は004に分け、M1開始を妨げるものと、後続profileだけを止めるものを混同しない。
