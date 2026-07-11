# 020-jra-prediction-materials-api 実装計画書

## 1. 対象と目的

- 対象機能: JRA当日予想材料API
- 改修目的: 当日の少数アクセスだけで、JRA予想エージェントが利用できる欠損許容bundleを提供する。
- 今回の対象範囲: source key、公開ページProvider/Extractor、lite算出、当日trend、個別API、bundle、fixtureテスト、文書。
- 今回やらないこと: 過去一括収集、DB migration、精密指数、予想ロジック変更。

## 2. 実装フェーズ

### Phase 1: 公開範囲とfixtureの固定

- 指定3URLを匿名状態で各1回取得し、保存するfixtureを最小化する。
- 公開項目、会員/有料項目、HTML内に存在しない項目を表にする。
- race key生成をサンプルURLで検証する。
- 停止条件に該当するsourceは無効扱いにする。

### Phase 2: モデルと純粋計算

- component status、recent form、lite材料、public analysis、bundleモデルを追加する。
- source key、時計変換、馬名照合、best/closing/style計算を純粋関数で実装する。
- fixture不要の単体テストを先に追加する。

### Phase 3: Provider/Extractor

- 3sourceのProviderを共通基底/個別実装で追加する。
- 1ページ/レース、timeout、retry、min interval、TTLを実装する。
- source別Extractorとfixtureテストを追加する。

### Phase 4: JRA trendとbundle

- JRA公式の既存serviceを使い、対象以前の確定結果だけを集計する。
- public analysisを1回取得し、3つのlite計算で共有する。
- card先行、optional component並列のJraPredictionServiceを追加する。

### Phase 5: APIと文書

- 個別APIとbundleを`app.py`へ追加する。
- dependency factory、query validation、OpenAPI説明を追加する。
- API仕様・利用ガイドを更新する。

### Phase 6: テストとレビュー

- 対象テスト、全体回帰、静的レビューを実装担当から人間へ引き継ぐ。
- live確認は対象レース1件のみとし、アクセス数をログで確認する。

## 3. タスク一覧

| ID | フェーズ | 作業内容 | 入力 | 出力 | 依存 | DoD |
| --- | --- | --- | --- | --- | --- | --- |
| JRA-PM-01 | 1 | 3sourceの匿名公開fixtureと項目表 | サンプルURL | fixture、確認表 | なし | 有料/非公開項目が明示される |
| JRA-PM-02 | 1 | source key resolver確定 | date/course/meeting/day/race | 3source code | 01 | サンプルURLと一致する |
| JRA-PM-03 | 2 | Pydanticモデル追加 | 010仕様 | models | 01 | status/quality/scopeを表現できる |
| JRA-PM-04 | 2 | lite純粋計算追加 | recent form | best/closing/style | 03 | 欠損・同率テストが通る |
| JRA-PM-05 | 3 | Providerとレート制御 | source URL | page content | 02 | 1source1GET、TTL共有 |
| JRA-PM-06 | 3 | Extractor追加 | fixture | public analysis | 01,03 | 公開値だけを抽出する |
| JRA-PM-07 | 4 | JRA trend-context追加 | 既存JRA service | trend | 03 | 未来結果を参照しない |
| JRA-PM-08 | 4 | JraPredictionService追加 | card/odds/trend/public | bundle | 04-07 | 重複取得せずpartial成功する |
| JRA-PM-09 | 5 | 個別API/bundle追加 | service/model | FastAPI routes | 08 | OpenAPIとvalidationを満たす |
| JRA-PM-10 | 5 | 文書更新 | API契約 | docs | 09 | curl例と欠損仕様が記載される |
| JRA-PM-11 | 6 | 自動テスト・回帰 | tests | 結果ログ | 01-10 | 対象/全体テスト結果を記録する |
| JRA-PM-12 | 6 | live 1件確認 | 当日レース | 検証メモ | 11 | 各外部source 1GET以下を確認する |

## 4. 完了判定

- 実装完了条件: 7個のJRA予想材料APIがOpenAPIに現れ、公開データだけでbundleを返せる。
- テスト完了条件: extractor、純粋計算、service、API、回帰テストが成功する。
- レビュー完了条件: 結果リークなし、アクセス予算、欠損表示、source優先順位を静的確認済み。

## 5. 別タスク候補

- 日々のJRA結果を蓄積してliteを精密版へ昇格する。
- 上がり・通過順を公式/許可済みソースから永続化するDB拡張。
- 騎手・調教師・血統の長期条件別統計。
- 取得sourceごとの利用条件監査と既定source見直し。

