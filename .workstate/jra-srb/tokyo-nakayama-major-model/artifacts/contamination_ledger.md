# 汚染済み期間と未使用holdout台帳

- generated_at: `2026-09-05T09:23:33`
- scanned_files: 1049
- skipped_files: 0

## 最終holdoutから固定除外

- `2025-01-05..2025-09-30`: train/walk-forward explored
- `2025-10-01..2025-12-31`: validation explored
- `2026-01-01..2026-06-28`: v89 known holdout explored
- `2024-12-28..2024-12-28`: collection/evaluation pilot inspected

## 成果物から検出した参照期間

- `2024-07-01..2024-08-31`: 4 files
- `2025-01-01..2025-02-28`: 2 files
- `2025-01-01..2025-06-30`: 200 files
- `2025-01-01..2025-09-30`: 2 files
- `2025-01-05..2025-09-30`: 1 files
- `2025-03-01..2025-04-30`: 2 files
- `2025-05-01..2025-06-30`: 2 files
- `2025-07-01..2025-07-31`: 49 files
- `2025-07-01..2025-08-31`: 2 files
- `2025-07-01..2025-10-31`: 60 files
- `2025-08-01..2025-08-31`: 43 files
- `2025-09-01..2025-09-30`: 51 files
- `2025-09-01..2025-10-31`: 2 files
- `2025-10-01..2025-12-31`: 287 files
- `2025-11-01..2025-12-31`: 6 files
- `2026-01-01..2026-06-28`: 26 files

## 未使用holdoutの扱い

- Only completed Tokyo/Nakayama autumn races after 2026-06-28 that were not used for model or threshold changes; fewer than 30 tickets means shadow-only.
- 開封前に候補と基準をcommitし、開封は一回だけ行う。
- 現時点で30買い目を確保できなければ正式採用とは呼ばない。
