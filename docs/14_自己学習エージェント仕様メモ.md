# 中穴お祭り馬券・自己学習エージェント仕様案

## 1. 目的

本仕様は、過去競馬データを取得できるMCPを利用し、以下を自動で回すエージェントの設計案である。

- 過去レースの発走前情報を取得する
- 理論バージョンに基づいて買い目を生成する
- 結果・払戻と照合する
- 的中率、回収率、ガミ率、軸馬3着内率、中穴馬券内率を集計する
- 弱点を分析する
- 改善候補ルールを生成する
- 別期間データで再検証する
- 条件を満たした場合のみ、新しい理論バージョンとして昇格する

重要なのは、これは「LLMモデル自体を学習する」仕組みではなく、**理論ルール、重み、制約、買い目生成方針をバージョン管理しながら改善する自己学習ループ**である。

---

## 2. 基本コンセプト

名称案：**中穴お祭り自己検証エージェント**

基本思想：

```text
分析する：逆プロスペクト
楽しむ：観戦価値最大化
買う：ガミ許容・中穴お祭り
検証する：結果照合とバージョン比較
改善する：過学習を避けながらルール候補を作る
```

最終目的は「必ず当てるAI」ではなく、以下のような性質を持つ買い目理論を育てること。

- 大崩れしにくい
- 軸馬の3着内率が一定以上ある
- 中穴が絡んだときに楽しい
- ガミを許容しつつ、押さえすぎを抑える
- 大穴を主役にしない
- 予算を固定し、追加購入しない
- 過去データに合わせすぎない

---

## 3. 全体アーキテクチャ

```text
Orchestrator Agent
  ↓
Race Data MCP
  ├─ get_race_list
  ├─ get_pre_race_snapshot
  ├─ get_race_result
  └─ get_payouts
  ↓
Prediction Agent
  ↓
Prediction Store
  ↓
Evaluator Agent / Deterministic Evaluator
  ↓
Result Store
  ↓
Analyst Agent
  ↓
Rule Revision Agent
  ↓
Validation Agent
  ↓
Theory Registry
```

推奨する役割分担：

| 役割 | 担当 | ポイント |
|---|---|---|
| Orchestrator Agent | 全体制御 | 期間、対象、理論ver、検証セットを決める |
| Race Data MCP | データ取得 | 発走前情報と結果を明確に分離する |
| Prediction Agent | 買い目生成 | 結果を絶対に見ない |
| Evaluator | 的中判定 | できればLLMではなくプログラムで判定する |
| Analyst Agent | 集計・分析 | 弱点、傾向、心理的失敗を分類する |
| Rule Revision Agent | 改善候補生成 | ルール変更案を作るが即採用しない |
| Validation Agent | 別期間検証 | 改善候補をholdoutで検証する |
| Theory Registry | 理論管理 | v1.0、v1.1などを保存する |

---

## 4. 絶対に守る制約

### 4.1 結果リーク禁止

Prediction Agentには、以下を渡してはいけない。

- 着順
- 払戻
- レース後コメント
- 結果を含む記事
- レース後に確定した評価
- 「この馬が勝った」ことを示す情報

Prediction Agentに渡してよいのは、発走前に知り得た情報のみ。

### 4.2 予想と採点を分離する

Prediction Agentは買い目を作るだけ。  
Evaluatorは買い目を採点するだけ。  
Analystは集計と弱点分析をするだけ。

1つのLLMに「予想、結果照合、改善」を全部やらせると、後出し補正が混ざりやすい。

### 4.3 理論バージョンを固定して検証する

検証単位では理論を固定する。

例：

```text
v1.0で2024年G1/G2/G3を検証する
検証中にv1.0のルールを変更しない
検証後にv1.1候補を作る
v1.1候補は別期間で再検証する
```

### 4.4 自動昇格には条件を設定する

Rule Revision Agentが改善候補を作っても、無条件に採用しない。

昇格条件例：

- holdout期間で回収率が改善
- 軸馬3着内率が悪化していない
- 最大連敗数が悪化していない
- ガミ率が極端に増えていない
- 買い目点数が増えすぎていない
- 中穴馬券内率が改善または維持

---

## 5. データセット分割

過学習を避けるため、最低でも3分割する。

| 区分 | 用途 | 例 |
|---|---|---|
| development | 初期理論を作る | 2023年 |
| validation | 改善候補を検証する | 2024年 |
| holdout | 最終確認用。最後まで触らない | 2025年 |

時系列データなので、ランダム分割よりも年単位・期間単位の分割が望ましい。

---

## 6. 理論設定ファイル例

`theory_v1.0.yaml`

```yaml
theory_version: v1.0
name: 中穴お祭り馬券理論

budget:
  total: 3000
  buckets:
    safety: 1200
    middle_hole: 1000
    festival: 600
    mini_firework: 200

odds_rules:
  middle_hole_min: 8.0
  middle_hole_max: 30.0
  practical_middle_hole_max: 25.0
  big_hole_min: 50.0

axis_rules:
  min_positive_reasons: 3
  max_negative_reasons: 2
  prefer_place_probability: true

middle_hole_rules:
  max_middle_holes: 2
  min_positive_reasons: 2
  require_scenario_fit: true

big_hole_rules:
  allow: true
  max_amount: 200
  only_third_column_or_firework: true

ticket_rules:
  allow_gami: true
  allow_additional_purchase: false
  max_total_points: 20
  max_trifecta_points: 4
  max_trio_points: 10

psychology_rules:
  block_recovery_bet: true
  block_budget_over: true
  warn_too_many_cover_bets: true
```

---

## 7. MCPツール想定

既存MCPに合わせて名称は変更してよい。

### 7.1 get_race_list

対象レース一覧を返す。

入力例：

```json
{
  "from": "2024-01-01",
  "to": "2024-12-31",
  "grades": ["G1", "G2", "G3"],
  "course_type": "芝",
  "min_horses": 10
}
```

出力例：

```json
{
  "races": [
    {
      "race_id": "202406020811",
      "date": "2024-06-02",
      "course": "東京",
      "race_no": 11,
      "race_name": "安田記念",
      "grade": "G1"
    }
  ]
}
```

### 7.2 get_pre_race_snapshot

発走前情報のみを返す。結果情報は含めない。

```json
{
  "race_id": "202406020811",
  "include_odds": true,
  "odds_timing": "final_or_near_final"
}
```

### 7.3 get_race_result

着順を返す。

### 7.4 get_payouts

払戻を返す。

### 7.5 save_prediction

Prediction Agentの予想JSONを保存する。

### 7.6 save_evaluation

的中判定結果を保存する。

### 7.7 get_backtest_summary

理論verごとの集計結果を返す。

---

## 8. 予想出力JSONスキーマ

Prediction Agentは自由文章ではなく、必ずJSONで返す。

```json
{
  "race_id": "string",
  "theory_version": "v1.0",
  "mode": "gami_middle_festival",
  "budget": 3000,
  "race_script": {
    "main_scenario": "王道決着",
    "alternative_scenario": "人気馬取りこぼし",
    "middle_hole_scenario": "中穴浮上",
    "firework_scenario": "ミニ花火"
  },
  "axis_candidates": [
    {
      "horse_no": 6,
      "horse_name": "string",
      "confidence": "A|B|C",
      "positive_reasons": ["距離適性", "前走内容", "脚質"],
      "negative_reasons": ["外枠"],
      "place_confidence_note": "3着内軸として妥当"
    }
  ],
  "middle_hole_candidates": [
    {
      "horse_no": 10,
      "horse_name": "string",
      "odds": 14.2,
      "positive_reasons": ["展開利", "馬場替わり"],
      "negative_reasons": ["近走着順が悪い"],
      "role": "中穴券"
    }
  ],
  "excluded_horses": [
    {
      "horse_no": 15,
      "horse_name": "string",
      "reason": "単勝50倍以上で根拠不足。ミニ花火にも不採用"
    }
  ],
  "tickets": [
    {
      "bucket": "safety",
      "bet_type": "wide",
      "selection": [6, 10],
      "amount": 500,
      "reason": "軸と条件付き中穴の組み合わせ"
    }
  ],
  "psychology_check": {
    "recovery_bet_risk": "low",
    "over_cover_risk": "medium",
    "big_hole_desire_risk": "low",
    "comment": "ミニ花火枠は予算内に収まっている"
  },
  "notes": "三連単はミニ花火枠に限定"
}
```

---

## 9. 評価結果JSONスキーマ

Evaluatorは以下を保存する。

```json
{
  "race_id": "string",
  "theory_version": "v1.0",
  "total_bet": 3000,
  "total_payout": 1800,
  "return_rate": 0.60,
  "hit": true,
  "gami": true,
  "axis_in_top3": true,
  "middle_hole_in_top3": false,
  "firework_hit": false,
  "max_odds_selected": 28.5,
  "ticket_results": [
    {
      "bucket": "safety",
      "bet_type": "wide",
      "selection": [6, 10],
      "amount": 500,
      "hit": true,
      "payout": 1200
    }
  ]
}
```

---

## 10. 主要評価指標

| 指標 | 意味 |
|---|---|
| 回収率 | 払戻 ÷ 購入額 |
| 的中率 | 1つ以上的中したレース割合 |
| ガミ率 | 的中したが購入額未満だった割合 |
| 軸馬3着内率 | 軸候補が3着以内に入った割合 |
| 中穴馬券内率 | 中穴候補が3着以内に入った割合 |
| 最大連敗数 | メンタル耐性の確認 |
| 券種別回収率 | ワイド、馬連、三連複、三連単別 |
| バケット別回収率 | 安心券、中穴券、お祭り券、ミニ花火券別 |
| 買い目点数平均 | 押さえすぎ確認 |
| 単勝30倍超採用率 | 大穴寄りすぎ確認 |

---

## 11. Orchestrator Agent プロンプト案

```text
あなたは「中穴お祭り自己検証エージェント」のOrchestratorです。

目的：
指定された理論バージョン、対象期間、対象レース条件に基づき、過去レース検証を自動実行してください。

あなたの役割：
- 検証対象レースを取得する
- 各レースについて発走前情報のみを取得する
- Prediction Agentへ発走前情報のみを渡す
- Prediction Agentの予想JSONを保存する
- 結果と払戻を取得する
- Evaluatorへ照合させる
- 評価結果を保存する
- 全レース完了後、Analyst Agentへ集計を依頼する
- 改善候補が出た場合、Rule Revision Agentへ渡す
- 改善候補は即採用せず、Validation Agentで別期間検証する

厳守事項：
- Prediction Agentに結果情報を渡してはいけない
- 検証中に理論バージョンを変更してはいけない
- エラーが出たレースはスキップせず、失敗理由を記録する
- 最終出力では、検証件数、除外件数、エラー件数を必ず出す
```

---

## 12. Prediction Agent プロンプト案

```text
あなたは「中穴お祭り馬券理論」のPrediction Agentです。

あなたの目的は、発走前情報だけを使って、指定された理論バージョンに従い、予算内の買い目JSONを生成することです。

あなたは結果を知りません。結果を推測して断定してはいけません。

基本思想：
- 軸は3着内確率を重視する
- 中穴は単勝8〜30倍程度から選ぶ
- 大穴は主役にしない
- ガミは許容する
- 押さえすぎは避ける
- 予算超過は禁止
- 追加購入は禁止

出力は必ず指定JSONスキーマに従ってください。
自由文章、Markdown、表は出力しないでください。

判断手順：
1. レース条件を確認する
2. 王道決着、人気馬取りこぼし、中穴浮上、ミニ花火の脚本を作る
3. 軸候補を選ぶ
4. 中穴候補を最大2頭選ぶ
5. 消し候補を出す
6. 安心券、中穴券、お祭り券、ミニ花火券に予算配分する
7. 買い目JSONを出力する

禁止：
- 結果を含む情報に言及すること
- 単勝50倍以上を主役にすること
- 予算を超えること
- 理由のない大穴を買うこと
- 怖いから押さえるだけの買い目を増やすこと
```

---

## 13. Evaluator Agent プロンプト案

原則として、的中判定はプログラムで行う。  
LLMを使う場合は、補助説明だけに限定する。

```text
あなたはEvaluator Agentです。

あなたの役割は、Prediction Agentが出した買い目JSONと、実際の着順・払戻を照合し、評価JSONを作ることです。

あなたは新しい買い目を作ってはいけません。
あなたは理論を修正してはいけません。
あなたは結果に合わせて予想理由を書き換えてはいけません。

評価する項目：
- 的中したか
- 払戻はいくらか
- 回収率
- ガミかどうか
- 軸馬が3着以内に入ったか
- 中穴候補が3着以内に入ったか
- ミニ花火が機能したか
- 券種別の損益
- バケット別の損益

出力は指定JSONスキーマに従ってください。
```

---

## 14. Analyst Agent プロンプト案

```text
あなたはAnalyst Agentです。

あなたの役割は、複数レースの評価結果を集計し、中穴お祭り馬券理論の強み・弱みを分析することです。

あなたは理論を直接変更してはいけません。
あなたは改善候補を出すだけです。

分析対象：
- 回収率
- 的中率
- ガミ率
- 軸馬3着内率
- 中穴馬券内率
- 最大連敗数
- 券種別回収率
- バケット別回収率
- レース格別成績
- 競馬場別成績
- 距離別成績
- 馬場別成績

出力：
1. 全体サマリー
2. 良かった点
3. 悪かった点
4. 明らかに足を引っ張ったルール
5. 変更してはいけないルール
6. 改善候補
7. 過学習リスク
8. 次に検証すべき仮説

注意：
単発の大当たりや単発の大外れを過大評価してはいけません。
最低でも複数回確認された傾向のみ、改善候補として扱ってください。
```

---

## 15. Rule Revision Agent プロンプト案

```text
あなたはRule Revision Agentです。

あなたの役割は、Analyst Agentの分析結果をもとに、次バージョンの理論候補を作ることです。

重要：
あなたは本番理論を直接変更してはいけません。
あなたは candidate version を作るだけです。

入力：
- 現在のtheory.yaml
- backtest summary
- Analyst Agentの改善候補

出力：
- candidate_theory_version
- 変更点一覧
- 変更理由
- 想定される改善
- 想定される副作用
- 検証すべき指標
- rollback条件

変更例：
- 中穴レンジを8〜30倍から8〜25倍に変更
- 三連単最大4点を最大2点に変更
- ミニ花火枠200円を100円に変更
- 軸馬条件に「不安点2つ以下」を追加
- 単勝30倍超は条件根拠3つ以上必須に変更

禁止：
- 1レースだけの結果でルール変更すること
- 回収率だけを理由に変更すること
- 買い目点数を無制限に増やすこと
- 大穴寄りにしすぎること
```

---

## 16. Validation Agent プロンプト案

```text
あなたはValidation Agentです。

あなたの役割は、candidate theory を別期間・別条件のデータで検証し、昇格可否を判定することです。

判定基準：
- 回収率が改善または維持されている
- 軸馬3着内率が悪化していない
- 中穴馬券内率が悪化していない
- 最大連敗数が悪化していない
- ガミ率が許容範囲内
- 買い目点数が増えすぎていない
- 大穴依存が強まっていない

出力：
1. candidate version
2. 検証対象
3. 現行verとの比較
4. 昇格判定：promote / reject / needs_more_test
5. 理由
6. 追加検証条件

注意：
現行verより一部指標が良くても、安定性が落ちる場合は昇格しないでください。
```

---

## 17. Guard Agent プロンプト案

```text
あなたはGuard Agentです。

あなたの役割は、検証エージェント全体が危険な方向に進んでいないか監視することです。

チェック項目：
- Prediction Agentに結果情報が渡っていないか
- 理論バージョンが検証中に変わっていないか
- 買い目点数が増えすぎていないか
- 大穴偏重になっていないか
- 回収率だけで改善判断していないか
- 同一データで過剰にチューニングしていないか
- 予算超過を許していないか
- 取り返し馬券のような設計になっていないか

問題がある場合は処理を止め、理由を出力してください。
```

---

## 18. 自己学習ループ

```text
1. 現行理論verを固定
2. developmentまたはvalidation期間でバックテスト
3. 結果を集計
4. Analystが弱点を抽出
5. Rule Revisionがcandidate理論を作成
6. candidate理論を別期間で検証
7. Validationが現行verと比較
8. 条件を満たせばTheory Registryへpromote
9. 満たさなければrejectまたはneeds_more_test
10. サマリーをlearning_summary.mdへ出力
```

---

## 19. learning_summary.md 出力テンプレート

```md
# Learning Summary

## 対象
- theory_version:
- 検証期間:
- 対象レース:
- 件数:

## 結果
- 購入額:
- 払戻:
- 回収率:
- 的中率:
- ガミ率:
- 軸馬3着内率:
- 中穴馬券内率:
- 最大連敗数:

## 良かった点
-

## 悪かった点
-

## 改善候補
-

## 採用しない改善
-

## 次回検証
-

## 現行ルールへの反映
- promote / reject / needs_more_test
```

---

## 20. 最小PoC手順

最初から完全自動にせず、以下の順で作る。

```text
1. 過去G1・重賞20レースをMCPから取得
2. get_pre_race_snapshotが結果を含まないことを確認
3. theory_v1.0.yamlを固定
4. Prediction Agentに1レースずつ予想JSONを出させる
5. JSONスキーマ検証を行う
6. Evaluatorはプログラムで的中判定する
7. SQLiteに一次保存し、必要に応じてCSV/Parquetへエクスポート
8. Analyst AgentでMarkdownレポートを生成
9. 20レースで処理が安定したら100レースへ拡張
10. Rule RevisionとValidationを追加する
```

---

## 21. 保存テーブル案

実装では、発走前情報と結果情報を分離するため、分析用SQLiteに以下の系統を持たせる。

- 発走前系: `races`, `runners`, `odds_snapshots`, `odds_entries`
- 結果系: `race_results`, `result_entries`, `payouts`
- 収集管理: `collection_runs`, `collection_errors`
- 自己学習系: `theory_versions`, `predictions`, `prediction_tickets`, `evaluations`, `evaluation_ticket_results`

Prediction Agentへ渡す `pre_race_snapshot` は発走前系のみで構成し、結果系・評価系を含めない。

### predictions

| column | type |
|---|---|
| prediction_id | string |
| race_id | string |
| theory_version | string |
| mode | string |
| budget | integer |
| prediction_json | json |
| created_at | datetime |

### evaluations

| column | type |
|---|---|
| evaluation_id | string |
| prediction_id | string |
| race_id | string |
| theory_version | string |
| total_bet | integer |
| total_payout | integer |
| return_rate | decimal |
| hit | boolean |
| gami | boolean |
| axis_in_top3 | boolean |
| middle_hole_in_top3 | boolean |
| firework_hit | boolean |
| evaluation_json | json |

### theory_versions

| column | type |
|---|---|
| theory_version | string |
| parent_version | string |
| status | string |
| theory_yaml | text |
| promoted_at | datetime |
| notes | text |

---

## 22. 実装上の注意

- LLM出力は必ずJSON schema validationする
- 的中判定はLLMではなく deterministic code で行う
- 予想時点の入力JSONを保存しておく
- 予想時点の入力JSONは `pre_race_snapshot_json` として保存し、結果・払戻を含めない
- 後から再現できるように theory_version を必ず保存する
- race_id単位で処理ログを残す
- 失敗したレースは除外理由を保存する
- 1回の大当たりで理論を昇格しない
- 1回の大外れで理論を破棄しない
- 最終判断は promote / reject / needs_more_test の3択にする

---

## 23. まとめ

この仕組みの主役は、GPTsではなくエージェントである。

```text
MCP = 過去データ取得
Prediction Agent = 発走前情報だけで買い目生成
Evaluator = 結果照合
Analyst = 傾向分析
Rule Revision = 改善候補作成
Validation = 別期間検証
Theory Registry = 理論バージョン管理
```

自己学習とは、LLMの重みを変えることではなく、**理論ファイルを検証結果に基づいて安全に進化させること**である。

この形なら、過去データを使いながらも、結果への後出し適合を抑えた「中穴お祭り理論の研究所」を作れる。
