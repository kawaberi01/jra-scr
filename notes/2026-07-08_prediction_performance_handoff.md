# 2026-07-08 川崎予想 遅延対策 引継ぎ

## 目的

南関予想の1ターンあたりの待ち時間を下げる。
主眼は「体感待ち時間の短縮」であり、コード美化や抽象化は後回しにする。

## 現状整理

- 現在の予想では、1レースごとに複数APIを取得している
  - `card`
  - `odds`
  - `trend-context`
  - `best-time`
  - `closing-speed`
  - `pattern`
  - `leading/jockeys`
- 呼び出しは原則 `rtk uv run jra-srb call-local-api ...` で統一済み
- `call-local-api` 自体は単純で、毎回複雑なアクセス方法を組んでいるわけではない
  - 実装: `src/jra_srb/cli.py` の `call_local_api`
  - 内容: URL生成 + `httpx.AsyncClient().get(...)` + JSON整形出力

## 実測

2026-07-08 11Rでの単発実測:

- `card`: 約 9.5 秒
- `odds`: 約 14.6 秒
- `pattern`: 約 2.3 秒

注意:

- この時間には `uv run` の起動コストも含まれる
- `odds` は三連単まで含む巨大JSONのため特に重い
- 予想1回で複数本叩くので、合算で待ち時間が大きくなる

## 結論

主因は次の2点。

1. `uv run` をAPIごとに毎回起動していること
2. 重いAPIを必要本数ぶん個別取得していること

「アクセス方法を毎回組んでいるから遅い」は主因ではない。

## 優先度付き対応案

### 優先度A: 予想用まとめ取得APIを作る

最も効く。

やること:

- 予想に必要な材料を1回で返すローカルAPIを追加する
- 例:
  - `/nankan/meetings/{date}/{course}/races/{race_no}/prediction-bundle`
- 返却候補:
  - `card`
  - `odds` の必要部分のみ
  - `trend-context`
  - `best-time`
  - `closing-speed`
  - `pattern`
  - `leading/jockeys`

効く理由:

- CLI起動回数を減らせる
- スレッド側の取得手順が単純になる
- 取得漏れやテンプレートぶれも減る

実装方針:

- 既存のAPI群をサーバー側でまとめて呼ぶ
- 可能なら並列取得する
- 返却は予想で使う形に整えておく

期待効果:

- 体感で最も大きい改善候補

### 優先度B: `odds` を軽量化する

次に効く。

やること:

- 全券種を返す現行 `odds` とは別に、予想用の軽量オッズAPIを作る
- 例:
  - `win`
  - `wide`
  - `quinella`
  - 必要なら `trio`
- 三連単の全組み合わせは既定では返さない

効く理由:

- 実測で `odds` が最重
- 現状の予想では、全券種を毎回読む必要がない

実装候補:

- 既存 `odds` のレスポンスから必要券種だけ抽出して返す別エンドポイント
- 例:
  - `/nankan/meetings/{date}/{course}/races/{race_no}/odds-summary`

期待効果:

- 取得時間短縮
- JSON量削減
- モデル側の読み取り負荷削減

### 優先度C: CLI起動回数を減らす

効果は高いが、AやBより単独効果は読みづらい。

やること:

- `uv run jra-srb ...` を1回ずつ呼ぶ運用を減らす
- 候補:
  - まとめ取得APIに寄せる
  - 複数パスを一度に取るCLIを追加する
  - 予想専用CLIを作る

候補コマンド案:

- `uv run jra-srb call-local-api-batch ...`
- `uv run jra-srb fetch-nankan-prediction-bundle ...`

効く理由:

- Python起動 + CLI初期化の回数を削れる

### 優先度D: サーバー側で並列取得する

Aの中で一緒にやると効率が良い。

やること:

- `card` / `trend-context` / `best-time` / `closing-speed` / `pattern` / `leading` をサーバー側で並列取得
- `odds` は重いので、軽量化と併用前提

効く理由:

- 個別の待ち時間の合算を減らせる

注意:

- 外部アクセス先への負荷や制限には注意
- キャッシュ済みAPIとライブAPIの混在挙動を確認する

### 優先度E: 予想中の再取得を減らす

補助的に効く。

やること:

- 同一レース内で一度取得したデータを使い回す
- 予想→修正版予想→買い目修正で再取得を避ける

効く理由:

- 同じレースでの無駄な再フェッチを減らせる

## 推奨実施順

1. `odds-summary` か `prediction-bundle` のどちらを先に作るか決める
2. まず `odds-summary` を作る
3. 次に `prediction-bundle` を作る
4. その後、CLIを bundle 前提へ寄せる
5. 最後にテンプレート側の取得手順を bundle 前提へ更新する

この順を推す理由:

- `odds` が最重で、単体改善でも効く
- その後に bundle を作ると構成が整理しやすい

## 次スレッドで依頼すべき内容

推奨依頼文:

`notes/2026-07-08_prediction_performance_handoff.md を読んで、優先度AとBの方針で実装してください。まずは odds-summary API を追加し、その後 prediction-bundle API と CLI 対応まで進めてください。`

## 変更候補ファイル

- `src/jra_srb/cli.py`
- ローカルAPIサーバーのルーティング実装ファイル
- Nankan系サービス層
- 必要ならテスト

## 実装時の注意

- 既存 `call-local-api` は残す
- 新APIは既存予想フローを壊さず追加で入れる
- 予想テンプレート側は、新API完成後に置き換える
- 出力互換性よりも、まず待ち時間の削減を優先してよい

## ひとことで言うと

最優先は「毎回の多本数取得をやめる」こと。
そのために、

- 重い `odds` を軽くする
- 予想に必要な材料を1回で返す

この2本が最も効く。
