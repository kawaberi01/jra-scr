# Agent / Skill 改善ログ

更新方式: 追記型。

## 2026-10-15 実装前レビュー

- 対象: SQL Server共通研究基盤。使用skill: project-enhancement-analysis-orchestrator、project-reference-router、project-enhancement-analysis、project-enhancement-implementation-spec、project-enhancement-progress-pack。
- ユーザーが対話レビューを明示したため3名へ限定調査を委譲。初回調査だけで終わらず、仕様草案への指摘と親の修正を再確認した。
- 有効だった確認: 列名から金額と推定せず生成元を確認し、official_win_settlement=0/1と判明。ラベルと払戻を分ける契約・回帰試験へ修正した。
- 有効だった確認: 既存索引を表ごとに確認し、labelsだけrace索引なしと判明。一律scan禁止で不可能にする/レースごと再scanする両方を避け、版/rowidの有界routeへ修正した。
- 再発防止: 実装前に単位・enum実値・索引経路・artifactの全variantを実コード/実DDLと照合する。未確認をゲートに残すだけで済ませず、静的に確定できる意味は先に固定する。
- 限界: 本レビューは静的確認。実SQLの権限・入力整合・実行性能や全研究族の動作を確認したものではない。未実施は005/004に明記した。


## 2026-10-16 再開時の実装・監視の改善

- 実DDLを本体と同じhelperから生成する循環テストを避け、migration literalで独立に照合する。
- Windowsのテストread_textもUTF-8を明示する。
- 軽量agentにも絶対パスと直読対象を指定し、artifacts/data全域探索を禁止する。今回の広域研究検索3組は親がcommand/parent一致を確認して停止。API processには触れていない。
- metadataのfilter_definitionがNULLという事実と非filtered索引を区別し、has_filter=0で判定する。
- 受入済み証拠のmetrics/config等もartifact別SHAで固定する。

## 2026-10-17 棚卸しで修正した説明

- V89/V90について過去研究の未昇格/rejectだけを伝え、現行スキルの仮正式運用指定との違いを落としていた。029へ両方を併記して修正。
- 全研究SQL移行の2/21という件数を、普段の予想が使える程度やデータ移行率のように伝わる説明にした。今後はデータ移送/通常API/採用方式/終了済み研究を分け、運用上必要な対象を先に棚卸しする。
- SQLite名の引数/importが残っても、open_analysis_read/build_analysis_storeのSQL分岐を確認してから実依存を説明する。削除可否は個別監査なしに断定しない。

## 2026-10-23 有効性判定と参照入口実装の順序

事実: 利用者が『使えるモデルと判定したか』『何を行おうとしているか』と問い直した。069〜070は技術的な版/入力互換性を具体化したが、採用根拠を強める工程を先にすべきだった。影響: 未採用の候補について実装了承を求め、利用者の主目的から離れた。対応: 071で製品実装優先を撤回し、未使用期間を実ファイル照合。再発防止: 有効性の判定に必要な証拠、独立評価の可否、合否契約を先に固定し、入口完成を性能改善と混同しない。
