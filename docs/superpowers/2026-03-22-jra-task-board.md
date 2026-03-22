# JRA Data Retrieval Task Board

## Goal

JRA API 基盤の現在地を task 状態で再開可能にする

## Summary

- updated at: 2026-03-22 22:38:13 +0900
- tasks: 10
- ready: 2
- in progress: 0
- blocked: 0

## Ready Tasks

- `T9` Expand supported odds bet types
- `T10` Persist past results and retries in batch

## Tasks

- `T1` [done] owner: restoration deps: - paths: src/jra_srb/navigation.py, src/jra_srb/provider.py, tests/test_navigation.py title: JRA navigation layer
  - note: 2026-03-22 22:38:12 +0900 completed by restoration: navigation layer is implemented and covered by tests/test_navigation.py
- `T2` [done] owner: restoration deps: T1 paths: src/jra_srb/service.py, src/jra_srb/app.py, tests/test_service.py, tests/test_api.py title: Meeting-level race index API
  - note: 2026-03-22 22:38:12 +0900 completed by restoration: meeting API is implemented and covered by tests/test_service.py and tests/test_api.py
- `T3` [done] owner: restoration deps: T2 paths: src/jra_srb/service.py, src/jra_srb/app.py title: Race card by meeting coordinates
  - note: 2026-03-22 22:38:13 +0900 completed by restoration: race card by meeting coordinates is implemented
- `T4` [done] owner: restoration deps: T2 paths: src/jra_srb/service.py, src/jra_srb/extractors.py, src/jra_srb/models.py title: Initial JRA odds support for win and trifecta
  - note: 2026-03-22 22:38:13 +0900 completed by restoration: initial live JRA odds support is implemented for win and trifecta only
- `T5` [done] owner: restoration deps: T4 paths: src/jra_srb/service.py, src/jra_srb/app.py title: Meeting-coordinate odds endpoint
  - note: 2026-03-22 22:38:13 +0900 completed by restoration: meeting-coordinate odds endpoint is implemented
- `T6` [done] owner: restoration deps: T2 paths: src/jra_srb/service.py, src/jra_srb/extractors.py, src/jra_srb/app.py title: Results and payouts by meeting coordinates
  - note: 2026-03-22 22:38:13 +0900 completed by restoration: result and payout endpoint by meeting coordinates is implemented
- `T7` [done] owner: restoration deps: T2 paths: src/jra_srb/batch.py, tests/test_batch.py title: Past result batch collector skeleton
  - note: 2026-03-22 22:38:13 +0900 completed by restoration: past result collector skeleton exists in src/jra_srb/batch.py
- `T8` [done] owner: restoration deps: T1, T2, T3, T4, T5, T6, T7 paths: docs/jra/00_成果物計画.md, docs/jra/07_現在地と次の一手.md title: Formal docs restoration and current-state sync
  - note: 2026-03-22 22:38:13 +0900 completed by restoration: formal docs under docs/jra were restored and synced from working docs
- `T9` [ready] owner: - deps: T5 paths: src/jra_srb/extractors.py, src/jra_srb/service.py, tests/test_service.py, tests/test_api.py title: Expand supported odds bet types
- `T10` [ready] owner: - deps: T7 paths: src/jra_srb/batch.py, src/jra_srb/service.py title: Persist past results and retries in batch

## Recent Log

- 2026-03-22 22:37:49 +0900 board initialized with 10 tasks
- 2026-03-22 22:38:12 +0900 restoration completed T1
- 2026-03-22 22:38:12 +0900 restoration completed T2
- 2026-03-22 22:38:13 +0900 restoration completed T3
- 2026-03-22 22:38:13 +0900 restoration completed T4
- 2026-03-22 22:38:13 +0900 restoration completed T5
- 2026-03-22 22:38:13 +0900 restoration completed T6
- 2026-03-22 22:38:13 +0900 restoration completed T7
- 2026-03-22 22:38:13 +0900 restoration completed T8
