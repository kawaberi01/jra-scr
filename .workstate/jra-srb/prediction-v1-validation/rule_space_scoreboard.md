# Rule Space Scoreboard

Date: 2026-07-04

## Headline

- Aggregated theories: 78
- Holdout-tested theories: 1
- Current candidate count by fixed train+validation gate: 0
- Practical conclusion: no theory in the current rule space clears train walk-forward and validation together.

## Best Validation Theories

| theory | validation no-max | Jul no-max | Aug no-max | Sep no-max | holdout no-max | verdict |
|---|---:|---:|---:|---:|---:|---|
| v25_a4_8_rle2_fg5 | 1.0786 | 0.8019 | 0.8432 | 0.6234 | - | reject_train_validation |
| v25_sg_a2_10_rle2 | 1.0771 | 0.6398 | 0.9157 | 0.6213 | - | reject_train_validation |
| hy_fg7_5_a2_10_rle2 | 1.0596 | 0.7643 | 0.7662 | 0.7493 | - | reject_train_validation |
| v24 | 1.0564 | 0.7753 | 0.8069 | 0.5078 | - | reject_train_validation |
| v25_sg_a4_8_rle2 | 1.0548 | 0.7449 | 0.9423 | 0.6132 | - | reject_train_validation |
| v40 | 1.0532 | 0.9234 | 0.8477 | 0.5106 | - | reject_train_validation |
| v25_sg_a4_6_rle2 | 1.0527 | 0.8059 | 0.9478 | 0.5753 | - | reject_train_validation |
| v25_a4_6_rle2_fg5 | 1.0476 | 0.8637 | 0.8569 | 0.5821 | - | reject_train_validation |
| v25_a4_8_rle2_fg2_5 | 1.0446 | 0.8108 | 0.8750 | 0.6472 | - | reject_train_validation |
| v39 | 1.0406 | 0.8584 | 0.8587 | 0.5623 | - | reject_train_validation |
| v19 | 1.0379 | 0.8837 | 0.7535 | 0.5259 | - | reject_train_validation |
| v10 | 1.0361 | 0.7755 | 0.8631 | 0.5615 | 0.8200 | reject_holdout |

## Representative Theories

| theory | validation no-max | Jul no-max | Aug no-max | Sep no-max | holdout no-max | comment |
|---|---:|---:|---:|---:|---:|---|
| v10 | 1.0361 | 0.7755 | 0.8631 | 0.5615 | 0.8200 | frozen holdout failure |
| v17 | 1.0124 | 0.8812 | 0.7401 | 0.5787 | - | baseline of later work |
| v22 | 0.9819 | 0.8011 | 0.9294 | 0.5955 | - | standard one-ticket branch |
| sg_a4_6_r3_5 | 1.0014 | 0.8663 | 0.7742 | 0.6221 | - | shape guard branch |
| hy_fg7_5_a2_10_rle2 | 1.0596 | 0.7643 | 0.7662 | 0.7493 | - | strong validation, weak Jul/Aug |
| v24 | 1.0564 | 0.7753 | 0.8069 | 0.5078 | - | target hard gate <=8 |
| v25 | 1.0313 | 0.8815 | 0.8570 | 0.5614 | - | best simple target gate |
| v25_sg_a4_6_rle2 | 1.0527 | 0.8059 | 0.9478 | 0.5753 | - | v25 plus weak-shape filter |
| v25_a4_6_rle2_fg2_5 | 1.0171 | 0.8709 | 0.8872 | 0.6052 | - | v25 plus weak-shape and first gap |
| v25_a4_8_rle2_fg2_5 | 1.0446 | 0.8108 | 0.8750 | 0.6472 | - | wider ratio window |
| v25_a4_8_rle2_fg5 | 1.0786 | 0.8019 | 0.8432 | 0.6234 | - | highest validation no-max in current space |

## Decision Support

- `v10` is the only frozen holdout-tested theory and it failed.
- The best validation-only rows are concentrated in `v25` derivatives, but every one of them still breaks at least one train month.
- The main failure pattern is unchanged: improving validation no-max tends to push `wf3_2025_09` below an acceptable floor.

## Source Files

- `custom_theory_sweep.json`
- `train_walkforward_summary.json`
- `train_walkforward_v11_v16.json`
- `train_walkforward_v11_v18.json`
- `train_walkforward_v17_v20.json`
- `train_walkforward_v17_v21.json`
- `train_walkforward_v17_v22.json`
- `train_walkforward_v23_v26.json`
- `train_walkforward_v27_v30.json`
- `train_walkforward_v31_v34.json`
- `train_walkforward_v35_v38.json`
- `train_walkforward_v39_v41.json`
- `train_walkforward_v39_v42.json`
- `train_walkforward_v42.json`
- `train_walkforward_v9_v13.json`
- `v10_holdout_summary.json`
- `v10_validation_summary.json`
- `v11_validation_summary.json`
- `v12_validation_summary.json`
- `v13_validation_summary.json`
- `v14_validation_summary.json`
- `v15_validation_summary.json`
- `v16_validation_summary.json`
- `v17_first_middle_gap_sweep.json`
- `v17_hybrid_guard_sweep.json`
- `v17_second_ticket_gap_sweep.json`
- `v17_shape_guard_matrix_sweep.json`
- `v17_validation_summary.json`
- `v18_validation_summary.json`
- `v19_validation_summary.json`
- `v1_validation_summary.json`
- `v20_validation_summary.json`
- `v21_validation_summary.json`
- `v22_validation_summary.json`
- `v23_validation_summary.json`
- `v24_validation_summary.json`
- `v25_ratio_guard_with_first_gap_sweep.json`
- `v25_shape_guard_sweep.json`
- `v25_validation_summary.json`
- `v26_validation_summary.json`
- `v27_validation_summary.json`
- `v28_validation_summary.json`
- `v29_validation_summary.json`
- `v2_validation_summary.json`
- `v30_validation_summary.json`
- `v31_validation_summary.json`
- `v32_validation_summary.json`
- `v34_validation_summary.json`
- `v36_validation_summary.json`
- `v38_validation_summary.json`
- `v39_validation_summary.json`
- `v3_validation_summary.json`
- `v40_validation_summary.json`
- `v41_validation_summary.json`
- `v42_validation_summary.json`
- `v4_validation_summary.json`
- `v5_validation_summary.json`
- `v6_validation_summary.json`
- `v7_validation_summary.json`
- `v8_validation_summary.json`
- `v9_validation_summary.json`

