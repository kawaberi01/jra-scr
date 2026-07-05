# Ticket Shape Filter Search

| rank | conditions | train no-max floor | validation no-max | wf1 tickets | wf2 tickets | wf3 tickets | validation tickets |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | field_size=ge_14 | 0.9453 | 1.035 | 54 | 64 | 34 | 103 |
| 2 | axis_popularity=1 | 0.7905 | 0.9686 | 30 | 30 | 21 | 51 |
| 3 | axis_popularity=1, field_size=ge_14 | 0.7905 | 0.9686 | 30 | 30 | 21 | 51 |
| 4 | middle_odds=10_15 | 0.7533 | 0.4978 | 25 | 19 | 15 | 45 |
| 5 | field_size=ge_14, middle_odds=10_15 | 0.7533 | 0.4978 | 25 | 19 | 15 | 45 |
| 6 | surface=芝 | 0.5033 | 0.3129 | 27 | 30 | 16 | 31 |
| 7 | field_size=ge_14, surface=芝 | 0.5033 | 0.3129 | 27 | 30 | 16 | 31 |
| 8 | axis_odds=2_5_4 | 0.4211 | 0.3129 | 19 | 21 | 16 | 31 |
| 9 | axis_odds=2_5_4, field_size=ge_14 | 0.4211 | 0.3129 | 19 | 21 | 16 | 31 |
| 10 | surface=ダート | 0.2833 | 1.2306 | 27 | 34 | 18 | 72 |
| 11 | field_size=ge_14, surface=ダート | 0.2833 | 1.2306 | 27 | 34 | 18 | 72 |
| 12 | race_no=r06_08 | 0.0 | 1.0108 | 23 | 20 | 21 | 74 |
| 13 | field_size=ge_14, race_no=r06_08 | 0.0 | 1.0108 | 23 | 20 | 21 | 74 |
