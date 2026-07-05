# v80 Follow-up Filter Sweep

| rank | rule | train floor | validation | holdout | wf1 tickets | wf2 tickets | wf3 tickets | val tickets | holdout tickets |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | exclude_middle_trainer_recent_top3_rate=0_25_0_35 | 0.9714 | 0.8889 | 1.386 | 7 | 11 | 8 | 18 | 43 |
| 2 | exclude_middle_odds=15_20 | 0.9455 | 1.205 | 0.8526 | 9 | 11 | 9 | 20 | 38 |
| 3 | exclude_odds_ratio=lt_2 | 0.9187 | 1.5048 | 1.2681 | 10 | 16 | 9 | 21 | 47 |
| 4 | base_v80 | 0.9187 | 1.4364 | 1.2417 | 10 | 16 | 10 | 22 | 48 |
| 5 | exclude_axis_odds=4_6 | 0.9187 | 1.4364 | 1.2417 | 10 | 16 | 10 | 22 | 48 |
| 6 | exclude_middle_jockey_recent_top3_rate=0_15_0_25 | 0.9187 | 1.4364 | 1.2417 | 10 | 16 | 10 | 22 | 48 |
| 7 | exclude_middle_same_dist_top3_rate=0_25_0_35 | 0.8667 | 1.5444 | 0.8143 | 8 | 12 | 6 | 18 | 42 |
| 8 | exclude_middle_same_course_top3_rate=lt_0_15 | 0.8143 | 1.3286 | 1.2957 | 9 | 14 | 9 | 21 | 46 |
| 9 | exclude_middle_jockey_recent_top3_rate=0_25_0_35 | 0.7889 | 1.0867 | 1.3806 | 7 | 9 | 5 | 15 | 31 |
| 10 | exclude_odds_ratio=3_5_5 | 0.76 | 1.58 | 1.161 | 5 | 16 | 9 | 20 | 41 |
| 11 | exclude_middle_same_course_top3_rate=ge_0_35 | 0.7556 | 1.5833 | 1.2868 | 9 | 14 | 5 | 12 | 38 |
| 12 | exclude_middle_trainer_recent_top3_rate=ge_0_35 | 0.5909 | 1.425 | 1.0079 | 9 | 11 | 10 | 16 | 38 |
| 13 | keep_axis_popularity=1 | 0.5909 | 1.1824 | 0.897 | 9 | 11 | 8 | 17 | 33 |
| 14 | exclude_axis_popularity=2 | 0.5909 | 1.1824 | 0.897 | 9 | 11 | 8 | 17 | 33 |
| 15 | exclude_middle_trainer_recent_top3_rate=0_15_0_25 | 0.5462 | 1.5667 | 0.9261 | 8 | 13 | 5 | 12 | 23 |
| 16 | exclude_middle_jockey_recent_top3_rate=ge_0_35 | 0.5417 | 1.3588 | 1.0854 | 8 | 12 | 8 | 17 | 41 |
| 17 | exclude_middle_same_dist_top3_rate=lt_0_15 | 0.43 | 1.1579 | 1.3469 | 8 | 10 | 8 | 19 | 32 |
| 18 | keep_axis_odds=le_2_5 | 0.4125 | 1.2308 | 1.3455 | 7 | 8 | 5 | 13 | 22 |
| 19 | exclude_axis_odds=2_5_4 | 0.4125 | 1.1429 | 1.287 | 7 | 8 | 6 | 14 | 23 |
| 20 | exclude_middle_odds=8_10 | 0.3667 | 1.5857 | 1.3643 | 7 | 9 | 8 | 14 | 28 |
| 21 | exclude_odds_ratio=2_3_5 | 0.33 | 0.7643 | 1.2724 | 7 | 10 | 8 | 14 | 29 |
| 22 | exclude_middle_popularity=4 | 0.0 | 1.925 | 1.3 | 5 | 6 | 7 | 12 | 22 |
| 23 | keep_middle_popularity=5 | 0.0 | 1.925 | 1.3 | 5 | 6 | 7 | 12 | 22 |
| 24 | exclude_middle_trainer_recent_top3_rate=lt_0_15 | 0.0 | 1.58 | 1.3075 | 6 | 13 | 7 | 20 | 40 |
| 25 | exclude_middle_jockey_recent_top3_rate=lt_0_15 | 0.0 | 1.4917 | 0.9462 | 5 | 11 | 7 | 12 | 26 |
| 26 | keep_surface=ダート | 0.0 | 1.46 | 1.3419 | 5 | 7 | 4 | 15 | 31 |
| 27 | exclude_surface=芝 | 0.0 | 1.46 | 1.3419 | 5 | 7 | 4 | 15 | 31 |
