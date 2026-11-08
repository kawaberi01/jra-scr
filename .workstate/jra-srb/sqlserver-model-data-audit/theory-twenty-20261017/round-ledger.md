# 理論壁打ち・検証20件台帳

各案はT01基準に対する独立の仮説比較。20回の逐次最適化ではない。数値は2026年の再使用1082競走。対数損失は小さいほどよい。市場混合前の診断値であり、全19案の市場混合係数は0。T20は校正済3案の合成。

## 01 T01 2003年からの生涯成績

- 仮説：2003年からの生涯成績を予測要因として比較する。
- 反論・制約：古い環境の影響で近年を予測しにくくなる可能性
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, no_history`。
- 結果：市場混合前の対数損失 4.343072。
- 基準T01との差：+0.000000、日単位bootstrap 95%区間 [+0.000000, +0.000000]。事後診断・多重比較未補正。
- 判断：今回の基準との差は小さく、区間は0を含む。単独での優先度を下げる。

## 02 T02 2020年以降の学習との比較

- 仮説：2020年以降の学習との比較を予測要因として比較する。
- 反論・制約：古い年の学習を除いても履歴自体は2003年から保持する
- 検証方法：学習開始年2020、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, no_history`。
- 結果：市場混合前の対数損失 4.418061。
- 基準T01との差：+0.074989、日単位bootstrap 95%区間 [+0.069011, +0.080321]。事後診断・多重比較未補正。
- 判断：2020年以降への短縮は悪化。今回の固定方式では2003年以降を含む学習を保持。履歴自体は両案とも2003年以降。

## 03 T03 直近3走の上昇下降

- 仮説：直近3走の上昇下降を予測要因として比較する。
- 反論・制約：生涯能力の言い換えに過ぎない可能性
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, days_since_last, last_strength, mean3_strength, best3_strength, strength_drop, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, no_history`。
- 結果：市場混合前の対数損失 4.113353。
- 基準T01との差：-0.229720、日単位bootstrap 95%区間 [-0.245102, -0.213456]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 04 T04 相対上がり

- 仮説：相対上がりを予測要因として比較する。
- 反論・制約：終盤の良さと着順が重複する可能性
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, last_closing_rank, mean3_closing_rank, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, missing_closing, no_history`。
- 結果：市場混合前の対数損失 4.261172。
- 基準T01との差：-0.081900、日単位bootstrap 95%区間 [-0.093177, -0.069504]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 05 T05 通過位置からの進出

- 仮説：通過位置からの進出を予測要因として比較する。
- 反論・制約：後方にいた馬の機械的な順位上昇の可能性
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, last_position_gain, mean3_position_gain, last_corner_ratio, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, missing_corner, no_history`。
- 結果：市場混合前の対数損失 4.153561。
- 基準T01との差：-0.189511、日単位bootstrap 95%区間 [-0.202194, -0.174633]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 06 T06 先行馬の速い流れの負荷

- 仮説：先行馬の速い流れの負荷を予測要因として比較する。
- 反論・制約：実際の進路不利や消耗を観測していない
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, last_corner_ratio, last_pace, adverse_pace, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, missing_corner, missing_pace, no_history`。
- 結果：市場混合前の対数損失 4.271757。
- 基準T01との差：-0.071315、日単位bootstrap 95%区間 [-0.080303, -0.061911]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 07 T07 過去の終盤加速

- 仮説：過去の終盤加速を予測要因として比較する。
- 反論・制約：レース全体のラップと個別馬の能力は別
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, late_acceleration, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, missing_pace, no_history`。
- 結果：市場混合前の対数損失 4.342331。
- 基準T01との差：-0.000742、日単位bootstrap 95%区間 [-0.002285, +0.000915]。事後診断・多重比較未補正。
- 判断：今回の基準との差は小さく、区間は0を含む。単独での優先度を下げる。

## 08 T08 長距離消耗への適性

- 仮説：長距離消耗への適性を予測要因として比較する。
- 反論・制約：過去の長距離高回収を事後条件として選ばない
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, last_pace, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, endurance, missing_pace, no_history`。
- 結果：市場混合前の対数損失 4.342599。
- 基準T01との差：-0.000473、日単位bootstrap 95%区間 [-0.001910, +0.001181]。事後診断・多重比較未補正。
- 判断：今回の基準との差は小さく、区間は0を含む。単独での優先度を下げる。

## 09 T09 距離適性と距離変更

- 仮説：距離適性と距離変更を予測要因として比較する。
- 反論・制約：距離別の小標本を縮約する必要
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, distance_form_delta, distance_change, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, no_history`。
- 結果：市場混合前の対数損失 4.326523。
- 基準T01との差：-0.016549、日単位bootstrap 95%区間 [-0.019101, -0.013794]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 10 T10 芝ダート適性と復帰

- 仮説：芝ダート適性と復帰を予測要因として比較する。
- 反論・制約：馬場別に分けるだけでは一般化しない可能性
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, surface_form_delta, same_surface, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, no_history`。
- 結果：市場混合前の対数損失 4.316748。
- 基準T01との差：-0.026324、日単位bootstrap 95%区間 [-0.029025, -0.023558]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 11 T11 競馬場への適性

- 仮説：競馬場への適性を予測要因として比較する。
- 反論・制約：能力の高い馬が同じ場に集まるだけの可能性
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, course_form_delta, same_course, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, no_history`。
- 結果：市場混合前の対数損失 4.333830。
- 基準T01との差：-0.009242、日単位bootstrap 95%区間 [-0.010836, -0.007663]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 12 T12 低下後の得意条件復帰

- 仮説：低下後の得意条件復帰を予測要因として比較する。
- 反論・制約：過去失敗した必須フィルタにはせず連続特徴で比較
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, best3_strength, strength_drop, distance_form_delta, surface_form_delta, course_form_delta, distance_change, same_surface, same_course, restored_conditions, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, no_history`。
- 結果：市場混合前の対数損失 4.145526。
- 基準T01との差：-0.197546、日単位bootstrap 95%区間 [-0.209406, -0.184969]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 13 T13 休養と再出走間隔

- 仮説：休養と再出走間隔を予測要因として比較する。
- 反論・制約：好都合な休養日数の閾値探索をしない
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, days_since_last, field_size, age, weight_carried, frame, interval_deviation, distance, surface_dirt, maiden, open, season_sin, season_cos, no_history`。
- 結果：市場混合前の対数損失 4.337649。
- 基準T01との差：-0.005423、日単位bootstrap 95%区間 [-0.008774, -0.001876]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 14 T14 斤量変化

- 仮説：斤量変化を予測要因として比較する。
- 反論・制約：現在の斤量自体と前走からの変化を分ける
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, weight_change, no_history`。
- 結果：市場混合前の対数損失 4.343005。
- 基準T01との差：-0.000068、日単位bootstrap 95%区間 [-0.000139, +0.000002]。事後診断・多重比較未補正。
- 判断：今回の基準との差は小さく、区間は0を含む。単独での優先度を下げる。

## 15 T15 騎手と厩舎の経験

- 仮説：騎手と厩舎の経験を予測要因として比較する。
- 反論・制約：同日結果の混入と少標本の過信を避ける
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, jockey_top3, trainer_top3, no_history`。
- 結果：市場混合前の対数損失 4.271932。
- 基準T01との差：-0.071140、日単位bootstrap 95%区間 [-0.078948, -0.063840]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 16 T16 季節適性

- 仮説：季節適性を予測要因として比較する。
- 反論・制約：過去年の季節経験だけを使う
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, season_form_delta, no_history`。
- 結果：市場混合前の対数損失 4.336468。
- 基準T01との差：-0.006604、日単位bootstrap 95%区間 [-0.008328, -0.004640]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 17 T17 先行馬の密度と役割

- 仮説：先行馬の密度と役割を予測要因として比較する。
- 反論・制約：脚質の代理値が実展開を表すとは限らない
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, last_corner_ratio, field_size, age, weight_carried, frame, front_density, density_x_style, distance, surface_dirt, maiden, open, season_sin, season_cos, missing_corner, no_history`。
- 結果：市場混合前の対数損失 4.264373。
- 基準T01との差：-0.078700、日単位bootstrap 95%区間 [-0.088093, -0.068944]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 18 T18 経験量と能力の不確実性

- 仮説：経験量と能力の不確実性を予測要因として比較する。
- 反論・制約：少標本を高評価する能力推定を抑えられるか
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, field_size, age, weight_carried, frame, distance, surface_dirt, maiden, open, season_sin, season_cos, no_history, ability_uncertainty`。
- 結果：市場混合前の対数損失 4.338053。
- 基準T01との差：-0.005019、日単位bootstrap 95%区間 [-0.005982, -0.004089]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 19 T19 内容と条件の統合

- 仮説：内容と条件の統合を予測要因として比較する。
- 反論・制約：特徴を増やすことでノイズと相関を増やす可能性
- 検証方法：学習開始年2003、特徴 `lifetime_strength, lifetime_win, lifetime_top3, history_size, days_since_last, last_strength, mean3_strength, last_closing_rank, mean3_closing_rank, last_position_gain, mean3_position_gain, last_corner_ratio, last_pace, adverse_pace, best3_strength, strength_drop, distance_form_delta, surface_form_delta, course_form_delta, distance_change, same_surface, same_course, restored_conditions, late_acceleration, field_size, age, weight_carried, frame, interval_deviation, front_density, density_x_style, distance, surface_dirt, maiden, open, season_sin, season_cos, jockey_top3, trainer_top3, season_form_delta, weight_change, closing_x_gain, endurance, missing_closing, missing_corner, missing_pace, no_history, ability_uncertainty`。
- 結果：市場混合前の対数損失 4.023297。
- 基準T01との差：-0.319775、日単位bootstrap 95%区間 [-0.337975, -0.299525]。事後診断・多重比較未補正。
- 判断：基準モデルより生の予測損失が改善。研究部品として保持するが、市場への追加価値・購入収益は未確認。

## 20 T20 開発期間で選ぶ3案等重み合成

- 仮説：開発期間で選ぶ3案等重み合成を予測要因として比較する。
- 反論・制約：選択に使った開発成績は楽観的。2026年も既参照の探索評価
- 検証方法：学習開始年2003、特徴 `ensemble`。
- 結果：校正済合成の対数損失3.374066（市場と同一）。生モデルの値なし。
- 判断：校正後の損失は全案同点。ID順でT01/T02/T03を選択したため独立した改善なし。優秀な3理論を選べたとは扱わない。
