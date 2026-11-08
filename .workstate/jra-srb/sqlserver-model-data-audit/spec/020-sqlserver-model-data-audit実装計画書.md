# SQL Server共通研究基盤の実装計画

作成日: 2026-10-15。対象: 既存jra-scr内の研究基盤。API改修とは所有ファイルを分離する。

## 1. 実装方針

最初に全モデルを変更しない。固定SQL版→共通Input/Outcome→baseline/basic/cross→評価/保存/replayを一つの縦断機能として完成させ、その契約を既存研究族へ展開する。既存source/版を上書きして最新化する方式、研究ごとのdataset再生成方式は採らない。

## 2. フェーズと依存

| 順序 | ID | 作業と成果物 | 依存 | 完了条件 |
|---|---|---|---|---|
| 1 | M0a | 作業差分・入口registry・schema列/型/索引契約の固定。SQL専用readerとpreflight | 030/040/050 | DB名/権限/版/schema検査、秘密非出力。API共有ファイル変更0 |
| 2 | M0b | entries_json/HR払戻金額と的中フラグの整合/ロスター/定義版の少数SQL読取照合 | M0a | 初期契約を検査で確定。フラグを金額にしない。失敗時証跡と必要権限/列/版を出力 |
| 3 | M1a | frozen source解決・chunk reader・InputRace/OutcomeBundle・coverage | M0b | 全JOIN版固定、一意/時刻/mask/欠損を理由別に返す。必要集合だけ読む |
| 4 | M1b | cross_pool_sql_masked_v2のbaseline/basic8/cross9、時系列学習 | M1a | fit/score入力契約一致、trainのみfit、同じ比較集合、予測から結果非参照 |
| 5 | M1c | 共通単勝精算/metrics・成果物/manifest・replay・CLI/設定例 | M1b | 許可成果物だけ、入力変更でreplay拒否、M1縦断受入 |
| 6 | M2 | 原本/履歴/券種capability、SQL既存データの再解析adapter、互換入力検査 | M1 | raw本文検証・履歴条件・各券種のslot/返還を明示。コピー/DB書込なし |
| 7 | M3 | R01〜R15の各profile/variantを050順に接続 | M2または必要capability | 研究族ごとの等価試験・smoke・score・共通精算完了。新profileと旧互換を分離 |
| 8 | M4 | runtime receipt/baseline・ID map・最新データcoverage/replay | M1、API保存契約安定 | 同一operation束、known_at/cutoff、ID対応、曖昧版除外を検証 |
| 9 | M5 | 入口の呼出閉包監査、全研究受入、使用導線と記録更新 | M3/M4 | 未分類/未移行/必要データ不足0、DB0/コピー0の最終監査 |

M2〜M4は全体目的の必須残作業。M1受入を最終完了と報告しない。M4のAPI収集タスク再開・不足データ取得・権限付与は本実装では行わず別担当の依存とする。必要情報はprofile/期間/レース集合/券種/時点/列/除外理由/保存契約を添えて渡す。

## 3. M0の判定と止め方

M0は再設計の自由探索ではなく、040の契約に対する実装済みpreflightの受入。必要table/列/型と読取結果をassertし、互換なら次へ進む。失敗が出た箇所に依存するprofileのみ停止する。

- 接続/権限/固定snapshot・生成定義・HR払戻と的中フラグの整合・JSON構造の検査失敗はM1を停止。labelsは040の既存UXを使う有界keysetを実装し、レース毎の全走査を避ける。
- snapshot isolation無効はM1のresearch_only/非atomic契約では記録して進められる。strict profileは停止。
- raw codec/別券種/runtime新IDの未確認はM1を止めず、M2/M4の当該profileを止める。
- 新DB/schema/index、API変更、別DB参照、意味変更が必要ならこの仕様内で迂回しない。契約差分と根拠を記録する。

## 4. 設定例として実装する内容

`configs/research/cross_pool_sql_masked_v2.json`を新規作成し、次を固定する。資格情報は含めない。

```json
{
  "schema_version": 1,
  "profile_id": "cross_pool_sql_masked_v2",
  "source_policy": {"policy_id": "frozen_prediction_v1", "source_key": "prediction-full-20261008", "snapshot_id": 31},
  "date_from": "2004-01-01", "date_through": "2025-12-31", "horizon": "T30",
  "splits": {"train": ["2004-01-01", "2023-12-31"], "dev": ["2024-01-01", "2024-12-31"], "evaluation": ["2025-01-01", "2025-12-31"]},
  "seed": 42,
  "model": {"C": 1.0, "solver": "lbfgs", "max_iter": 1000},
  "ticket": {"stake_yen": 100, "odds_min": 2.0, "odds_max": 30.0, "min_expected_return": 1.05, "max_tickets_per_race": 1},
  "quality": {"availability": "research_only", "require_atomic_snapshot": false},
  "limits": {"batch_races": 500, "fetch_rows": 10000, "query_timeout_seconds": 30, "memory_bytes": 2147483648, "max_candidate_rows": 1500000, "max_label_scan_rows": 1500000}
}
```

31は本環境で監査済みの明示版例。ソース台帳の別版へ勝手に差替えない。小規模テスト設定は別fixtureで期間を短縮して生成できるが元データを保存しない。

## 5. テスト・レビューの順序

各段階で意味のある単体試験→対象機能のSQL読取結合試験→必要な回帰だけ実行。060を主入力とし、新規ファイルのdocstring/日本語ヘッダー、UTF-8、秘密非出力、型と単位、例外停止、副作用を静的レビューする。

初期受入で同じ版・コード・seedを2回実行し入力digestと予測を照合。数値比較許容は同環境1e-10、別環境では依存/BLAS差を記録し完全一致と称さない。ファイル全体のgzip時刻やrun時刻は比較対象外。

## 6. 全体DoDと残件の扱い

仕様010/040、一覧050、試験060を満たし、全研究族がSQLのみで実行できることを証跡で確認する。取得不能・未実装・競合は004に残し、対象外へ自動移動しない。旧DBを削除しなくても通常研究からのアクセスが0なら要件達成とする。

先送り候補は永続共有cache、SQL最適化/索引、モデル性能改善、APIライブ採用、原本全量再照合。これらを必要と断定せず、今回の全体DoDを満たすため必須になった場合は別契約へ切り出し、未達状態を維持する。
