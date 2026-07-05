# v80 Follow-up Pair Sweep

| rank | rule | train floor | validation | holdout | wf1 tickets | wf2 tickets | wf3 tickets | val tickets | holdout tickets |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | exclude_middle_jockey_recent_top3_rate=0_15_0_25__AND__exclude_odds_ratio=lt_2 | 0.9187 | 1.5048 | 1.2681 | 10 | 16 | 9 | 21 | 47 |
| 2 | exclude_axis_odds=4_6__AND__exclude_odds_ratio=lt_2 | 0.9187 | 1.5048 | 1.2681 | 10 | 16 | 9 | 21 | 47 |
| 3 | exclude_middle_jockey_recent_top3_rate=0_15_0_25__AND__exclude_axis_odds=4_6 | 0.9187 | 1.4364 | 1.2417 | 10 | 16 | 10 | 22 | 48 |
| 4 | exclude_middle_same_course_top3_rate=ge_0_35__AND__exclude_odds_ratio=lt_2 | 0.7556 | 1.7273 | 1.3216 | 9 | 14 | 5 | 11 | 37 |
| 5 | exclude_middle_same_course_top3_rate=ge_0_35__AND__exclude_middle_jockey_recent_top3_rate=0_15_0_25 | 0.7556 | 1.5833 | 1.2868 | 9 | 14 | 5 | 12 | 38 |
| 6 | exclude_middle_same_course_top3_rate=ge_0_35__AND__exclude_axis_odds=4_6 | 0.7556 | 1.5833 | 1.2868 | 9 | 14 | 5 | 12 | 38 |
| 7 | exclude_odds_ratio=lt_2__AND__keep_middle_same_course_top3_rate=missing | 0.475 | 1.53 | 1.3971 | 8 | 11 | 4 | 10 | 35 |
| 8 | exclude_middle_same_course_top3_rate=ge_0_35__AND__keep_middle_same_course_top3_rate=missing | 0.475 | 1.3909 | 1.3583 | 8 | 11 | 4 | 11 | 36 |
| 9 | exclude_middle_jockey_recent_top3_rate=0_15_0_25__AND__keep_middle_same_course_top3_rate=missing | 0.475 | 1.3909 | 1.3583 | 8 | 11 | 4 | 11 | 36 |
| 10 | exclude_axis_odds=4_6__AND__keep_middle_same_course_top3_rate=missing | 0.475 | 1.3909 | 1.3583 | 8 | 11 | 4 | 11 | 36 |
| 11 | exclude_middle_jockey_recent_top3_rate=0_15_0_25__AND__keep_axis_odds=le_2_5 | 0.4125 | 1.2308 | 1.3455 | 7 | 8 | 5 | 13 | 22 |
| 12 | exclude_axis_odds=4_6__AND__keep_axis_odds=le_2_5 | 0.4125 | 1.2308 | 1.3455 | 7 | 8 | 5 | 13 | 22 |
| 13 | exclude_odds_ratio=lt_2__AND__keep_axis_odds=le_2_5 | 0.4125 | 1.2308 | 1.3455 | 7 | 8 | 5 | 13 | 22 |
