# Ticket Shape Filter Search

| rank | conditions | train no-max floor | validation no-max | wf1 tickets | wf2 tickets | wf3 tickets | validation tickets |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | field_size=ge_14 | 0.645 | 1.1775 | 100 | 120 | 62 | 191 |
| 2 | odds_ratio=2_3_5 | 0.6118 | 0.9899 | 33 | 42 | 17 | 69 |
| 3 | field_size=ge_14, odds_ratio=2_3_5 | 0.6118 | 0.9899 | 33 | 42 | 17 | 69 |
| 4 | middle_popularity=5 | 0.5794 | 1.3708 | 22 | 34 | 18 | 48 |
| 5 | field_size=ge_14, middle_popularity=5 | 0.5794 | 1.3708 | 22 | 34 | 18 | 48 |
| 6 | axis_popularity=1, middle_odds=10_15 | 0.5538 | 0.6079 | 26 | 27 | 19 | 38 |
| 7 | axis_odds=le_2_5 | 0.525 | 1.2784 | 21 | 31 | 12 | 51 |
| 8 | axis_odds=le_2_5, field_size=ge_14 | 0.525 | 1.2784 | 21 | 31 | 12 | 51 |
| 9 | middle_popularity=4 | 0.51 | 0.8462 | 15 | 26 | 10 | 39 |
| 10 | field_size=ge_14, middle_popularity=4 | 0.51 | 0.8462 | 15 | 26 | 10 | 39 |
| 11 | axis_popularity=2 | 0.488 | 0.9797 | 25 | 46 | 18 | 64 |
| 12 | axis_popularity=2, field_size=ge_14 | 0.488 | 0.9797 | 25 | 46 | 18 | 64 |
| 13 | middle_odds=10_15 | 0.4708 | 0.6412 | 45 | 43 | 24 | 80 |
| 14 | field_size=ge_14, middle_odds=10_15 | 0.4708 | 0.6412 | 45 | 43 | 24 | 80 |
| 15 | axis_popularity=1 | 0.4611 | 1.0563 | 53 | 54 | 36 | 87 |
| 16 | axis_popularity=1, field_size=ge_14 | 0.4611 | 1.0563 | 53 | 54 | 36 | 87 |
| 17 | surface=芝 | 0.4429 | 0.581 | 52 | 56 | 29 | 58 |
| 18 | field_size=ge_14, surface=芝 | 0.4429 | 0.581 | 52 | 56 | 29 | 58 |
| 19 | axis_odds=2_5_4 | 0.4182 | 0.7517 | 33 | 39 | 30 | 58 |
| 20 | axis_odds=2_5_4, field_size=ge_14 | 0.4182 | 0.7517 | 33 | 39 | 30 | 58 |
| 21 | middle_odds=10_15, race_no=r06_08 | 0.4182 | 0.5193 | 22 | 11 | 14 | 57 |
| 22 | axis_odds=le_2_5, axis_popularity=1 | 0.3895 | 1.2784 | 19 | 29 | 12 | 51 |
| 23 | axis_popularity=1, race_no=r06_08 | 0.3714 | 0.9567 | 25 | 21 | 18 | 60 |
| 24 | axis_popularity=1, surface=芝 | 0.3 | 0.7615 | 24 | 31 | 21 | 26 |
| 25 | axis_odds=2_5_4, surface=芝 | 0.3 | 0.3696 | 14 | 20 | 20 | 23 |
| 26 | surface=ダート | 0.2917 | 1.3692 | 48 | 64 | 33 | 133 |
| 27 | field_size=ge_14, surface=ダート | 0.2917 | 1.3692 | 48 | 64 | 33 | 133 |
| 28 | middle_odds=10_15, surface=芝 | 0.2842 | 0.2 | 27 | 19 | 12 | 28 |
| 29 | axis_odds=4_6 | 0.28 | 0.6931 | 30 | 40 | 12 | 58 |
| 30 | axis_odds=4_6, field_size=ge_14 | 0.28 | 0.6931 | 30 | 40 | 12 | 58 |
