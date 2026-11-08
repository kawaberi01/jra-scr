"""概要: 固定SQL版から研究入力・結果・coverageを作り、読取整合性を検査する。
作成日: 2026-10-15
入力: 検証済み研究設定と研究専用SQL reader。
出力: メモリ内ResearchDataset、除外理由、内容digestと来歴。
実行例: uv run python scripts/run_jra_research.py coverage --config configs/research/cross_pool_sql_masked_v2.json
注意事項: 元データを保存せず、結果を予測入力へ混ぜない。版変更時は抽出結果を破棄する。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib
import sys

from .jra_research_contracts import (
    InputRace, OutcomeBundle, ResearchConfig, ResearchDataset, ResearchError, canonical_json, digest, horse_number,
)
from .jra_research_features import build_input, unique_rows
from .jra_research_resources import check_memory


def outcome_bundle(race: InputRace, labels: list[dict], payouts: list[dict]) -> OutcomeBundle:
    """HR的中フラグと実払戻円を照合し、正常結果の束を返す。"""
    if not labels:
        raise ResearchError("missing_result")
    indexed = unique_rows(labels, "horse_no")
    if set(indexed) != set(race.horses):
        raise ResearchError("roster_mismatch")
    if any(row["abnormal_code"] != "0" or row["settlement_status"] != "official_HR_payout" or
           type(row["rank"]) is not int or not 1 <= row["rank"] <= len(race.horses) or
           row["official_win_settlement"] not in (0, 1) for row in labels):
        raise ResearchError("settlement_unknown")
    hashes = {row["hr_sha256"] for row in labels}
    if len(hashes) != 1 or not next(iter(hashes)):
        raise ResearchError("result_version_conflict")
    hr_hash = next(iter(hashes))
    published = {}
    for row in payouts:
        if row["market"] != "win" or row["slot_status"] != "published":
            continue
        number, raw = horse_number(row["selection_raw"]), row["payout_raw"]
        if (not isinstance(raw, str) or len(raw) != 9 or not raw.isascii() or not raw.isdigit()
                or type(row["payout_yen"]) is not int or row["payout_yen"] <= 0
                or int(raw) != row["payout_yen"] or row["hr_sha256"] != hr_hash):
            raise ResearchError("payout_contract_failed")
        if number in published or number not in indexed:
            raise ResearchError("duplicate_or_unknown_payout")
        published[number] = row["payout_yen"]
    if not published:
        raise ResearchError("missing_payout")
    winners = {key for key in indexed if indexed[key]["rank"] == 1}
    flagged = {key for key in indexed if indexed[key]["official_win_settlement"] == 1}
    if winners != set(published) or winners != flagged:
        raise ResearchError("winner_payout_mismatch")
    return OutcomeBundle(race.race_key, race.horses, tuple(indexed[k]["rank"] for k in race.horses),
                         tuple(published.get(k, 0) for k in race.horses), hr_hash)


def _group(rows: list[dict]) -> dict[str, list[dict]]:
    """取得済みの同版行をレースキーで分類する。"""
    result = defaultdict(list)
    for row in rows:
        result[row["race_key"]].append(row)
    return result


def _sparse_batches(reader, config, candidates: list[dict], tables: list[str]):
    """少数レースを既存hash索引から取得する。"""
    size = config.raw["limits"]["batch_races"]
    for offset in range(0, len(candidates), size):
        batch = candidates[offset:offset + size]
        keys = [race["race_key"] for race in batch]
        yield batch, {table: reader.race_rows(table, keys) for table in tables}


def _collect(reader, config: ResearchConfig, *, score_key: str | None = None) -> tuple[ResearchDataset, str]:
    """一巡の抽出で必要行だけを保持し、SQL全利用列のstream digestを計算する。"""
    result, candidates, seen = ResearchDataset(), [], set()
    stream = hashlib.sha256(b"jra-research-stream-v1\n")
    all_races = 0
    for row in reader.keyset("history.races", maximum=100000):
        all_races += 1
        key, day = row["race_key"], row["race_date"]
        try:
            parsed = date.fromisoformat(day)
        except (ValueError, TypeError):
            raise ResearchError("invalid_race_date") from None
        if str(parsed) != day:
            raise ResearchError("invalid_race_date")
        selected = key == score_key if score_key else config.raw["date_from"] <= day <= config.raw["date_through"]
        if not selected:
            continue
        if key in seen:
            raise ResearchError("duplicate_key")
        seen.add(key)
        candidates.append(row)
        input_fields = {name: value for name, value in row.items() if name not in {"status", "feature_eligibility"}} if score_key else row
        stream.update((canonical_json(input_fields) + "\n").encode("utf-8"))
    candidates.sort(key=lambda r: r["race_key"])
    if score_key and not candidates:
        raise ResearchError("missing_race")
    result.candidate_count = len(candidates)
    total_rows, payout_groups, status = 0, {}, {r["race_key"]: r["status"] for r in candidates}
    tables = ["history.entries", "prediction.features_asof", "market.odds_asof_index"]
    if not score_key:
        tables.append("history.payouts")
    batches = _sparse_batches(reader, config, candidates, tables)
    for batch, rowsets in batches:
        grouped = {}
        for table in tables:
            rows = rowsets[table]
            for row in sorted(rows, key=canonical_json):
                stream.update((table + ":" + canonical_json(row) + "\n").encode("utf-8"))
            grouped[table] = _group(rows)
        for race in batch:
            key = race["race_key"]
            try:
                item = build_input(race, grouped["prediction.features_asof"].get(key, []),
                                   grouped["history.entries"].get(key, []), grouped["market.odds_asof_index"].get(key, []),
                                   snapshot=config.snapshot, horizon=config.raw["horizon"])
                result.races.append(item)
                total_rows += len(item.horses)
                if total_rows > config.raw["limits"]["max_candidate_rows"]:
                    raise ResearchError("candidate_row_limit", 3)
                if not score_key:
                    payout_groups[key] = [row for row in grouped["history.payouts"].get(key, [])
                                          if row["market"] == "win" and row["slot_status"] == "published"]
            except ResearchError as error:
                if error.exit_code != 4:
                    raise
                result.excluded.append({"race_key": key, "reason": error.reason})
        estimate = total_rows * 1600 + len(result.races) * 2000
        if estimate > config.raw["limits"]["memory_bytes"]:
            raise ResearchError("memory_limit")
        check_memory(config.raw["limits"]["memory_bytes"])
    label_groups, label_stream, scanned = defaultdict(list), hashlib.sha256(), 0
    if not score_key and result.races:
        input_map = {r.race_key: r for r in result.races}
        completed = set()
        for row in reader.keyset("history.labels", maximum=config.raw["limits"]["max_label_scan_rows"]):
            scanned += 1
            label_stream.update((canonical_json(row) + "\n").encode("utf-8"))
            key = row["race_key"]
            if key in input_map:
                if key in completed:
                    raise ResearchError("duplicate_key")
                label_groups[key].append(row)
                if len(label_groups[key]) == len(input_map[key].horses):
                    completed.add(key)
                    try:
                        if status[key] != "final":
                            raise ResearchError("unfinalized_result")
                        result.outcomes[key] = outcome_bundle(input_map[key], label_groups.pop(key), payout_groups.pop(key, []))
                    except ResearchError as error:
                        if error.exit_code != 4:
                            raise
                        label_groups.pop(key, None)
                        payout_groups.pop(key, None)
                        result.excluded.append({"race_key": key, "reason": error.reason})
            if scanned % 10000 == 0:
                check_memory(config.raw["limits"]["memory_bytes"])
        stream.update(label_stream.digest())
        final = []
        for item in result.races:
            if item.race_key in result.outcomes:
                final.append(item)
            elif item.race_key not in completed:
                result.excluded.append({"race_key": item.race_key, "reason": "missing_result"})
        result.races = final
    result.races.sort(key=lambda r: (r.race_date, r.race_key))
    result.excluded.sort(key=lambda row: row["race_key"])
    result.provenance = {"labels_scan_rows_per_pass": scanned, "labels_snapshot_stream_sha256": label_stream.hexdigest(),
                         "races_scan_rows": all_races}
    return result, stream.hexdigest()


def load_dataset(reader, config: ResearchConfig, *, score_key: str | None = None) -> ResearchDataset:
    """読取qualityに応じて一巡または二巡を比較し、固定版の研究入力を返す。"""
    with reader.read_transaction():
        dataset, first = _collect(reader, config, score_key=score_key)
    passes = 1
    if reader.report["read_consistency"] == "chunked_unproven":
        first_content = dataset.content_digest()
        del dataset
        with reader.read_transaction():
            dataset, after = _collect(reader, config, score_key=score_key)
        passes = 2
        if first != after or first_content != dataset.content_digest():
            raise ResearchError("source_changed", 5)
    dataset.provenance.update({"source": reader.report["source"], "build_identity_sha256": reader.report["build_identity_sha256"],
                               "schema_digest": reader.report["schema_digest"], "index_digest": reader.report["index_digest"],
                               "read_consistency": reader.report["read_consistency"], "availability": "research_only",
                               "strict_live_replay_eligible": False, "replayability": "content_match_only",
                               "read_route": "race_hash",
                               "scan_rows_all_passes": dict(getattr(reader, "scan_rows", {})),
                               "source_stream_identity": "route_and_batch_dependent_extraction_evidence",
                               "read_passes": passes, "source_stream_sha256": first})
    return dataset
