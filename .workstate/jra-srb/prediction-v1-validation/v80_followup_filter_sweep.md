# v80 Follow-up Filter Sweep

| rank | rule | train floor | validation | holdout | wf1 tickets | wf2 tickets | wf3 tickets | val tickets | holdout tickets |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | exclude_middle_same_course_top3_rate=ge_0_35 | 1.004 | 1.4053 | 0.8431 | 13 | 25 | 6 | 19 | 58 |
| 2 | keep_middle_popularity=4 | 0.9176 | 0.2133 | 0.7694 | 9 | 17 | 4 | 15 | 36 |
| 3 | exclude_middle_popularity=5 | 0.9176 | 0.2133 | 0.7694 | 9 | 17 | 4 | 15 | 36 |
| 4 | exclude_middle_same_dist_top3_rate=ge_0_35 | 0.9043 | 0.8941 | 1.3237 | 9 | 23 | 9 | 17 | 38 |
| 5 | exclude_middle_jockey_recent_top3_rate=0_15_0_25 | 0.8864 | 1.1704 | 1.1037 | 11 | 22 | 12 | 27 | 54 |
| 6 | keep_surface=ダート | 0.85 | 0.9125 | 1.05 | 6 | 18 | 6 | 24 | 50 |
| 7 | exclude_surface=芝 | 0.85 | 0.9125 | 1.05 | 6 | 18 | 6 | 24 | 50 |
| 8 | exclude_axis_odds=4_6 | 0.8478 | 1.2281 | 1.1016 | 14 | 23 | 12 | 32 | 64 |
| 9 | exclude_odds_ratio=3_5_5 | 0.8367 | 1.1559 | 0.8984 | 9 | 30 | 12 | 34 | 62 |
| 10 | base_v80 | 0.8097 | 1.0342 | 0.9658 | 16 | 31 | 14 | 38 | 73 |
| 11 | exclude_middle_same_course_top3_rate=lt_0_15 | 0.8074 | 0.9889 | 1.0071 | 15 | 27 | 13 | 36 | 70 |
| 12 | exclude_middle_odds=15_20 | 0.8 | 0.7088 | 0.7121 | 15 | 26 | 12 | 34 | 58 |
| 13 | exclude_odds_ratio=lt_2 | 0.78 | 1.1559 | 1.0071 | 15 | 25 | 13 | 34 | 70 |
| 14 | exclude_middle_trainer_recent_top3_rate=0_15_0_25 | 0.7727 | 1.1522 | 0.5878 | 12 | 22 | 8 | 23 | 41 |
| 15 | exclude_middle_jockey_recent_top3_rate=0_25_0_35 | 0.7609 | 0.8276 | 1.0132 | 12 | 23 | 9 | 29 | 53 |
| 16 | keep_middle_same_course_top3_rate=missing | 0.7455 | 1.3529 | 0.9226 | 11 | 20 | 5 | 17 | 53 |
| 17 | exclude_middle_same_dist_top3_rate=0_25_0_35 | 0.735 | 1.1452 | 0.6922 | 11 | 20 | 8 | 31 | 64 |
| 18 | exclude_middle_trainer_recent_top3_rate=lt_0_15 | 0.7167 | 0.9029 | 1.0456 | 12 | 25 | 10 | 35 | 57 |
| 19 | exclude_middle_trainer_recent_top3_rate=0_25_0_35 | 0.7087 | 0.7714 | 1.119 | 10 | 23 | 10 | 28 | 63 |
| 20 | exclude_axis_odds=2_5_4 | 0.6947 | 0.9875 | 0.7535 | 9 | 19 | 8 | 24 | 43 |
| 21 | keep_axis_odds=le_2_5 | 0.6909 | 1.3941 | 0.9818 | 7 | 11 | 5 | 17 | 33 |
| 22 | exclude_middle_jockey_recent_top3_rate=ge_0_35 | 0.6833 | 0.9333 | 0.84 | 14 | 24 | 11 | 33 | 65 |
| 23 | exclude_middle_jockey_recent_top3_rate=lt_0_15 | 0.6792 | 0.9154 | 0.7245 | 11 | 24 | 10 | 26 | 49 |
| 24 | exclude_odds_ratio=ge_5 | 0.6611 | 0.625 | 0.8523 | 13 | 18 | 7 | 24 | 44 |
| 25 | exclude_odds_ratio=2_3_5 | 0.66 | 0.8364 | 0.9233 | 11 | 20 | 10 | 22 | 43 |
| 26 | keep_odds_ratio=2_3_5 | 0.6455 | 0.9375 | 0.7567 | 5 | 11 | 4 | 16 | 30 |
| 27 | keep_axis_popularity=1 | 0.6118 | 1.112 | 0.8438 | 14 | 17 | 9 | 25 | 48 |
| 28 | exclude_axis_popularity=2 | 0.6118 | 1.112 | 0.8438 | 14 | 17 | 9 | 25 | 48 |
| 29 | keep_middle_odds=8_10 | 0.6 | 0.3154 | 0.6033 | 5 | 17 | 3 | 13 | 30 |
| 30 | exclude_axis_odds=le_2_5 | 0.595 | 0.4619 | 0.75 | 9 | 20 | 9 | 21 | 40 |
| 31 | exclude_middle_same_dist_top3_rate=lt_0_15 | 0.588 | 0.7971 | 1.0189 | 13 | 25 | 12 | 35 | 53 |
| 32 | exclude_middle_odds=8_10 | 0.5429 | 1.196 | 1.0767 | 11 | 14 | 11 | 25 | 43 |
| 33 | keep_axis_odds=2_5_4 | 0.5429 | 0.6929 | 1.0 | 7 | 12 | 6 | 14 | 30 |
| 34 | exclude_middle_odds=10_15 | 0.5 | 0.9941 | 1.0067 | 6 | 22 | 5 | 17 | 45 |
| 35 | exclude_middle_trainer_recent_top3_rate=ge_0_35 | 0.4913 | 1.0893 | 0.8483 | 14 | 23 | 14 | 28 | 58 |
| 36 | keep_middle_jockey_recent_top3_rate=lt_0_15 | 0.4571 | 0.65 | 1.1542 | 5 | 7 | 4 | 12 | 24 |
| 37 | keep_middle_odds=10_15 | 0.3667 | 0.7 | 0.6107 | 10 | 9 | 9 | 21 | 28 |
| 38 | exclude_surface=ダート | 0.3 | 0.6929 | 0.5217 | 10 | 13 | 8 | 14 | 23 |
| 39 | keep_surface=芝 | 0.3 | 0.6929 | 0.5217 | 10 | 13 | 8 | 14 | 23 |
| 40 | exclude_middle_popularity=4 | 0.2786 | 1.3391 | 0.9919 | 7 | 14 | 10 | 23 | 37 |
