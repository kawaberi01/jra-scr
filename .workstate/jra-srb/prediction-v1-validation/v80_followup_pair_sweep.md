# v80 Follow-up Pair Sweep

| rank | rule | train floor | validation | holdout | wf1 tickets | wf2 tickets | wf3 tickets | val tickets | holdout tickets |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | exclude_middle_same_course_top3_rate=ge_0_35__AND__exclude_odds_ratio=lt_2 | 0.9286 | 1.5706 | 0.8732 | 13 | 21 | 6 | 17 | 56 |
| 2 | exclude_middle_jockey_recent_top3_rate=0_15_0_25__AND__exclude_axis_odds=4_6 | 0.9187 | 1.4364 | 1.2417 | 10 | 16 | 10 | 22 | 48 |
| 3 | exclude_middle_jockey_recent_top3_rate=0_15_0_25__AND__exclude_odds_ratio=lt_2 | 0.9187 | 1.3739 | 1.1686 | 10 | 16 | 11 | 23 | 51 |
| 4 | exclude_middle_same_course_top3_rate=ge_0_35__AND__exclude_axis_odds=4_6 | 0.9167 | 1.5706 | 0.9404 | 12 | 20 | 5 | 17 | 52 |
| 5 | exclude_axis_odds=4_6__AND__exclude_odds_ratio=lt_2 | 0.8478 | 1.2677 | 1.119 | 14 | 23 | 11 | 31 | 63 |
| 6 | exclude_middle_same_course_top3_rate=ge_0_35__AND__exclude_middle_jockey_recent_top3_rate=0_15_0_25 | 0.7556 | 1.4615 | 1.1643 | 9 | 18 | 6 | 13 | 42 |
| 7 | exclude_odds_ratio=lt_2__AND__keep_middle_same_course_top3_rate=missing | 0.7455 | 1.5333 | 0.9588 | 11 | 17 | 5 | 15 | 51 |
| 8 | exclude_middle_same_course_top3_rate=ge_0_35__AND__keep_middle_same_course_top3_rate=missing | 0.7455 | 1.3529 | 0.9226 | 11 | 20 | 5 | 17 | 53 |
| 9 | exclude_axis_odds=4_6__AND__keep_axis_odds=le_2_5 | 0.6909 | 1.3941 | 0.9818 | 7 | 11 | 5 | 17 | 33 |
| 10 | exclude_odds_ratio=lt_2__AND__keep_axis_odds=le_2_5 | 0.6909 | 1.3941 | 0.9818 | 7 | 11 | 5 | 17 | 33 |
| 11 | exclude_middle_same_course_top3_rate=ge_0_35__AND__keep_axis_odds=le_2_5 | 0.5 | 1.67 | 0.8893 | 6 | 10 | 4 | 10 | 28 |
| 12 | exclude_middle_jockey_recent_top3_rate=0_15_0_25__AND__keep_middle_same_course_top3_rate=missing | 0.475 | 1.275 | 1.2225 | 8 | 14 | 5 | 12 | 40 |
| 13 | exclude_middle_jockey_recent_top3_rate=0_15_0_25__AND__keep_axis_odds=le_2_5 | 0.4125 | 1.2308 | 1.3455 | 7 | 8 | 5 | 13 | 22 |
| 14 | exclude_axis_odds=4_6__AND__keep_middle_same_course_top3_rate=missing | 0.38 | 1.5333 | 1.0404 | 10 | 16 | 4 | 15 | 47 |
