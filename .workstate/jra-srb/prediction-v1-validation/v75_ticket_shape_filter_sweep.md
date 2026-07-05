# v75 Ticket Shape Filter Sweep

| rank | rule | train floor | validation | holdout | wf1 tickets | wf2 tickets | wf3 tickets | val tickets | holdout tickets |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | exclude_trainer_0_15_0_25 | 0.9891 | 1.2182 | 0.52 | 39 | 46 | 21 | 77 | 110 |
| 2 | base_v75 | 0.9453 | 1.035 | 0.6497 | 54 | 64 | 34 | 103 | 183 |
| 3 | axis_le2_ex_trainer_0_15_0_25 | 0.9025 | 1.135 | 0.4644 | 33 | 40 | 18 | 60 | 87 |
| 4 | exclude_ratio_lt2 | 0.875 | 0.9605 | 0.7671 | 48 | 52 | 30 | 86 | 155 |
| 5 | axis_le2_ex_same_course_lt_0_15 | 0.8735 | 1.0293 | 0.7308 | 34 | 49 | 23 | 75 | 130 |
| 6 | exclude_same_course_lt_0_15 | 0.8691 | 1.1065 | 0.6856 | 44 | 55 | 25 | 93 | 167 |
| 7 | exclude_midpop_7 | 0.8605 | 1.1714 | 0.6902 | 38 | 59 | 29 | 91 | 164 |
| 8 | axis_le2_midpop_4_5 | 0.8097 | 1.0342 | 0.9658 | 16 | 31 | 14 | 38 | 73 |
| 9 | exclude_midpop_6_7 | 0.7891 | 1.481 | 0.7573 | 19 | 46 | 21 | 63 | 117 |
| 10 | keep_axis_popularity=2__odds_ratio=2_3_5 | 0.5333 | 0.3294 | 0.8407 | 3 | 9 | 5 | 17 | 27 |
| 11 | keep_axis_popularity=1__middle_same_course_top3_rate=missing | 0.2111 | 0.9769 | 0.675 | 18 | 22 | 8 | 26 | 56 |
| 12 | keep_middle_trainer_recent_top3_rate=lt_0_15__middle_same_course_top3_rate=missing | 0.0 | 1.7182 | 0.0778 | 12 | 3 | 2 | 11 | 27 |
| 13 | keep_middle_popularity=5__middle_same_course_top3_rate=missing | 0.0 | 1.6091 | 0.6459 | 5 | 14 | 6 | 11 | 37 |
| 14 | keep_axis_popularity=2__middle_trainer_recent_top3_rate=lt_0_15 | 0.0 | 1.5667 | 0.0 | 7 | 3 | 2 | 6 | 9 |
| 15 | keep_axis_popularity=1__middle_popularity=5 | 0.0 | 1.2063 | 1.176 | 7 | 8 | 7 | 16 | 25 |
| 16 | keep_middle_popularity=5__odds_ratio=2_3_5 | 0.0 | 0.7462 | 0.0 | 3 | 7 | 1 | 13 | 14 |
| 17 | keep_axis_popularity=1__middle_trainer_recent_top3_rate=0_15_0_25 | 0.0 | 0.5 | 0.88 | 7 | 6 | 10 | 15 | 35 |
| 18 | keep_axis_popularity=2__middle_same_course_top3_rate=missing | 0.0 | 0.4214 | 0.3976 | 7 | 14 | 1 | 14 | 42 |
| 19 | keep_middle_popularity=5__middle_trainer_recent_top3_rate=0_15_0_25 | 0.0 | 0.4111 | 1.3 | 1 | 5 | 6 | 9 | 22 |
| 20 | keep_axis_popularity=1__odds_ratio=2_3_5 | 0.0 | 0.41 | 0.3353 | 6 | 8 | 4 | 10 | 17 |
| 21 | keep_axis_popularity=1__middle_popularity=4 | 0.0 | 0.3556 | 0.2609 | 7 | 9 | 2 | 9 | 23 |
| 22 | keep_axis_popularity=1__middle_popularity=6 | 0.0 | 0.3267 | 0.0 | 8 | 5 | 4 | 15 | 18 |
| 23 | keep_axis_popularity=1__middle_popularity=7 | 0.0 | 0.0 | 0.0 | 6 | 1 | 5 | 5 | 12 |
| 24 | keep_axis_popularity=1__odds_ratio=3_5_5 | 0.0 | 0.0 | 0.6056 | 9 | 5 | 5 | 7 | 18 |
| 25 | keep_axis_popularity=1__middle_trainer_recent_top3_rate=lt_0_15 | 0.0 | 0.0 | 0.245 | 13 | 5 | 5 | 8 | 20 |
| 26 | keep_axis_popularity=1__middle_same_course_top3_rate=lt_0_15 | 0.0 | 0.0 | 0.0 | 5 | 2 | 4 | 6 | 10 |
| 27 | keep_axis_popularity=2__middle_popularity=4 | 0.0 | 0.0 | 1.2769 | 2 | 8 | 2 | 6 | 13 |
| 28 | keep_axis_popularity=2__middle_popularity=6 | 0.0 | 0.0 | 0.0 | 7 | 6 | 2 | 8 | 18 |
| 29 | keep_axis_popularity=2__odds_ratio=lt_2 | 0.0 | 0.0 | 0.0 | 2 | 7 | 1 | 6 | 7 |
| 30 | keep_axis_popularity=2__odds_ratio=3_5_5 | 0.0 | 0.0 | 0.0 | 7 | 4 | 3 | 8 | 14 |
