"""概要: S06/S08の学習・校正・評価・保存後推論を固定少数日のSQL入力で確認する。
作成日: 2026-10-17
入力: 研究専用SQL接続、固定版31/34、既存のキメラ純計算コード。
出力: 新規runの研究モデル・件数・予測・評価・入力digest。
実行例: uv run --extra ml python scripts/run_jra_tipster_sql_smoke.py
注意事項: 過去の既使用日による接続確認。旧データ・成果物・API・SQLを更新しない。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib
import importlib.util
import json
import os
import sys

from . import jra_history_dataset as history
from .jra_research_artifacts import ROOT, RunArtifacts
from .jra_research_contracts import ResearchError, digest, horse_number, timestamp
from .jra_research_features import numeric_market, unique_rows
from .jra_research_history import HistoryConfig, HistoryReader, collect_history
from .jra_research_reader import ResearchReader


DAYS = {"train": ["2025-09-06", "2025-09-07"], "calibration": ["2025-10-04", "2025-10-05"],
        "evaluation": ["2025-11-01", "2025-11-02"]}
CONTRACT = "analysis34-history-retrospective31-card-v1"
FIELDS = {
    "history.entries": ("race_key", "horse_no", "horse_id", "rank", "abnormal_code", "retrospective_se_json"),
    "market.odds_asof_index": ("race_key", "horizon", "market", "cutoff_at", "announced_at", "content_sha256", "selection_status", "parser_version", "entries_json"),
    "history.payouts": ("race_key", "market", "selection_raw", "payout_raw", "payout_yen", "slot_status", "hr_sha256"),
}


def load_legacy():
    """旧mainを実行せず、v3の純学習・推論部品を読み込む。"""
    path = ROOT / ".workstate/jra-srb/tipster-chimera-pair-v3/evaluate_stable.py"
    spec = importlib.util.spec_from_file_location("tipster_sql_smoke_v3", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_input_guard() -> None:
    """この研究プロセスでSQLite接続と旧JSONL/バックアップ読取を実行時に拒否する。

    Notes:
        audit hookは解除しないため、専用CLIプロセスで使用する。
        新runの予測JSONL書込と、設定・コード・保存モデルの読取は許可する。
    """
    def guard(event, arguments):
        """秘密やファイル名を出力せず、禁止入力を理由コードだけで拒否する。"""
        if event == "sqlite3.connect":
            raise ResearchError("sqlite_input_rejected", 3)
        if event != "open" or not isinstance(arguments[0], (str, bytes, os.PathLike)):
            return
        name = os.fsdecode(arguments[0]).lower()
        mode = arguments[1]
        reading = not isinstance(mode, str) or not any(k in mode for k in ("w", "a", "x"))
        if name.endswith((".sqlite", ".sqlite3", ".sqlite-wal", ".sqlite-shm")):
            raise ResearchError("sqlite_file_rejected", 3)
        if reading and name.endswith((".jsonl", ".jsonl.gz", ".bak")):
            raise ResearchError("legacy_file_input_rejected", 3)
    sys.addaudithook(guard)


class TipsterMarketReader(ResearchReader):
    """固定少数日の市場・ロスター・精算を版+race hashで読む。"""

    def selected(self, days=None):
        """固定31版を検査し、最大7日（省略時はsmoke固定日）の行を返す。"""
        if days is None:
            days = sorted(day for values in DAYS.values() for day in values)
        if not days or len(days) > 7 or len(set(days)) != len(days):
            raise ResearchError("invalid_tipster_days", 2)
        source = self._small("tipster_market:source", "SELECT d.source_key,s.status FROM ops.source_snapshot s JOIN ops.source_database d ON d.source_database_id=s.source_database_id WHERE s.source_snapshot_id=?", (31,))
        if len(source) != 1 or source[0] != {"source_key": "prediction-full-20261008", "status": "verified"}:
            raise ResearchError("unverified_source", 3)
        for table in ("history.races", *FIELDS):
            fields = FIELDS.get(table, ("race_key", "race_date", "venue_code", "race_no", "retrospective_metadata_json"))
            columns = self._small("tipster_market:columns", "SELECT name FROM sys.columns WHERE object_id=OBJECT_ID(?)", (table,))
            if not set((*fields, "__migration_source_snapshot_id", "__unified_race_sha256")) <= {r["name"] for r in columns}:
                raise ResearchError("missing_schema_columns", 3, table=table)
            indexes = self._small("tipster_market:indexes", "SELECT i.name,c.name column_name FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.object_id=OBJECT_ID(?) AND i.is_disabled=0 AND i.is_hypothetical=0 AND i.has_filter=0 AND ic.key_ordinal>0 ORDER BY i.index_id,ic.key_ordinal", (table,))
            grouped = defaultdict(list)
            for row in indexes:
                grouped[row["name"]].append(row["column_name"])
            if not any(v[:2] == ["__migration_source_snapshot_id", "__unified_race_sha256"] for v in grouped.values()):
                raise ResearchError("missing_index_route", 3, table=table)
            for permission in ("SELECT", "INSERT", "UPDATE", "DELETE", "ALTER", "CONTROL"):
                value = self._small("tipster_market:permission", "SELECT HAS_PERMS_BY_NAME(?,'OBJECT',?) permitted", (table, permission))[0]["permitted"]
                if value != int(permission == "SELECT"):
                    raise ResearchError("permission_contract_failed", 3, table=table)
        sql = "SELECT race_key,race_date,venue_code,race_no,retrospective_metadata_json FROM history.races WHERE __migration_source_snapshot_id=? AND race_date IN (" + ",".join("?" for _ in days) + ") ORDER BY race_date,race_key"
        races = self._small("tipster_market:races", sql, (31, *days))
        if not races or len(races) > 200 or len({r["race_key"] for r in races}) != len(races):
            raise ResearchError("invalid_tipster_smoke_races", 4)
        keys = [r["race_key"] for r in races]
        rowsets = {}
        for table, fields in FIELDS.items():
            values, params = [], []
            for key in keys:
                values.append("(CONVERT(binary(32),?),CONVERT(nvarchar(max),?))")
                params.extend((hashlib.sha256(key.encode("utf-16le")).digest(), key))
            sql = "SELECT " + ",".join(f"t.[{k}]" for k in fields)
            sql += f" FROM {table} t JOIN (VALUES {','.join(values)}) k(hash_value,race_key) ON t.__unified_race_sha256=k.hash_value AND CONVERT(varbinary(max),t.race_key)=CONVERT(varbinary(max),k.race_key) WHERE t.__migration_source_snapshot_id=?"
            params.append(31)
            if table == "market.odds_asof_index":
                sql += " AND t.horizon=?"
                params.append("T30")
            rows = self._small("tipster_market:rows:" + table, sql, params)
            if any(row["race_key"] not in keys for row in rows):
                raise ResearchError("race_hash_mismatch", 3)
            rowsets[table] = rows
        self.report = {"source": source[0], "snapshot": 31, "input_digest": digest({"races": races, "rows": rowsets}),
                       "query_metrics": self.query_metrics}
        return races, rowsets


def card_features(race, entries, states):
    """対象日前の34版履歴と31版の事後属性で研究専用43特徴を計算する。"""
    metadata = json.loads(race["retrospective_metadata_json"])
    track = int(metadata["track_code"])
    surface = "turf" if 10 <= track <= 22 else "dirt" if 23 <= track <= 29 else "other"
    name = metadata.get("race_name") or {"701": "新馬", "703": "未勝利", "999": "オープン"}.get(metadata["condition_code"], "条件戦")
    if track >= 50:
        name = "障害 " + name
    course = history.COURSE_CODES[race["venue_code"]]
    distance = int(metadata["distance_raw"])
    records = []
    for entry in entries:
        attrs = json.loads(entry["retrospective_se_json"])
        if attrs.get("status") != "retrospective_SE_unverified_for_T30":
            raise ResearchError("unexpected_retrospective_attributes", 4)
        sex = {"1": "牡", "2": "牝", "3": "セ"}.get(attrs["sex"])
        if sex is None or not attrs["age"].strip().isdigit() or not attrs["horse_name"]:
            raise ResearchError("missing_smoke_identity_attributes", 4)
        runner = {"horse_no": horse_number(entry["horse_no"]), "horse_name": attrs["horse_name"],
                  "frame_no": attrs["frame_no"], "sex_age": sex + str(int(attrs["age"])),
                  "jockey": attrs["jockey"], "trainer": attrs["trainer"],
                  "weight_carried": int(attrs["weight_carried_raw"]) / 10}
        horse = runner["horse_name"]
        vector = history._feature_vector(row=runner, race_date=date.fromisoformat(race["race_date"]), race_name=name,
            course=course, surface=surface, distance=distance, field_size=len(entries),
            horse=states["horse"][horse], horse_course=states["horse_course"][(horse, course)],
            horse_surface=states["horse_surface"][(horse, surface)],
            horse_distance=states["horse_distance"][(horse, history._distance_band(distance, name))],
            jockey=states["jockey"][runner["jockey"] or "unknown"], trainer=states["trainer"][runner["trainer"] or "unknown"])
        runner["history_features"] = dict(zip(history.FEATURE_NAMES, vector, strict=True))
        records.append(runner)
    return {"course": course, "surface": surface, "distance": distance, "race_no": race["race_no"]}, records


def sql_races(races, rowsets, prior_rows, *, state_provider=None):
    """市場時点と精算を確認し、旧純計算の明示入力をメモリで組み立てる。"""
    grouped = {}
    for table, rows in rowsets.items():
        grouped[table] = defaultdict(list)
        for row in rows:
            grouped[table][row["race_key"]].append(row)
    output, excluded = [], []
    states, state_day = None, None
    for race in races:
        key = race["race_key"]
        try:
            markets = unique_rows(grouped["market.odds_asof_index"][key], "market")
            if set(markets) != {"win", "quinella"}:
                raise ResearchError("missing_market", 4)
            for market in markets.values():
                if (market["selection_status"] != "selected" or market["parser_version"] != "jv-o1o2-v2"
                        or not market["content_sha256"] or timestamp(market["announced_at"]) > timestamp(market["cutoff_at"])):
                    raise ResearchError("invalid_smoke_market", 4)
            if timestamp(markets["win"]["cutoff_at"]) != timestamp(markets["quinella"]["cutoff_at"]):
                raise ResearchError("cutoff_mismatch", 4)
            win = numeric_market(markets["win"], "win")
            pairs = numeric_market(markets["quinella"], "quinella")
            entries = unique_rows(grouped["history.entries"][key], "horse_no")
            if (len(win) < 8 or not set(win) <= set(entries)
                    or any(entries[k]["abnormal_code"] != "0" or not isinstance(entries[k]["rank"], int) for k in win)):
                raise ResearchError("roster_or_result_mismatch", 4)
            pairs = {k: v for k, v in pairs.items() if set(k) <= set(win)}
            if len(pairs) != len(win) * (len(win) - 1) // 2:
                raise ResearchError("missing_O2_pairs", 4)
            if state_day != race["race_date"]:
                state_day = race["race_date"]
                states = (state_provider(state_day) if state_provider else
                          history._build_history_states(row for row in prior_rows if row["race_date"] < state_day))
            info, runners = card_features(race, [entries[k] for k in sorted(win, key=int)], states)
            if info["surface"] == "other":
                raise ResearchError("unsupported_surface", 4)
            settled, versions = [], set()
            for payout in grouped["history.payouts"][key]:
                if payout["market"] != "quinella" or payout["slot_status"] != "published":
                    continue
                raw = payout["selection_raw"]
                if (len(raw) != 4 or not raw.isascii() or not raw.isdigit() or payout["payout_yen"] <= 0
                        or int(payout["payout_raw"]) != payout["payout_yen"] or not payout["hr_sha256"]):
                    raise ResearchError("payout_contract_failed", 4)
                pair = tuple(sorted((horse_number(raw[:2]), horse_number(raw[2:])), key=int))
                if pair[0] == pair[1] or any(k not in win or not 1 <= entries[k]["rank"] <= 2 for k in pair):
                    raise ResearchError("winner_payout_mismatch", 4)
                versions.add(payout["hr_sha256"])
                settled.append({"horse_no_1": pair[0], "horse_no_2": pair[1], "payout": payout["payout_yen"]})
            if not settled or len(versions) != 1 or len({(p['horse_no_1'], p['horse_no_2']) for p in settled}) != len(settled):
                raise ResearchError("missing_or_conflicting_payout", 4)
            output.append({"race_id": key, "race_date": race["race_date"], "race": info,
                "inputs": {"runners": runners, "odds": {"T-30m": {
                    "win": {"horses": [{"horse_no": k, "odds": v, "status": "numeric"} for k, v in win.items()]},
                    "quinella": {"pairs": [{"horse_no_1": k[0], "horse_no_2": k[1], "odds": v, "status": "numeric"} for k, v in pairs.items()]}}}},
                "result": {"ranks_by_horse": {k: entries[k]["rank"] for k in win}, "quinella_payout_per_100_yen": settled}})
        except ResearchError as error:
            if error.exit_code != 4:
                raise
            excluded.append({"race_key": key, "reason": error.reason})
    return output, excluded


def execute_smoke():
    """固定日でS06/S08の最小構成を学習・評価し保存後の推論一致を確認する。"""
    import joblib
    import numpy as np
    from threadpoolctl import threadpool_limits

    install_input_guard()
    config = {"contract": CONTRACT, "days": DAYS, "history_snapshot": 34, "market_snapshot": 31,
              "purpose": "sql_path_smoke_only", "availability": "retrospective_research_only"}
    artifacts = RunArtifacts(config, "tipster-sql-smoke")
    try:
        legacy = load_legacy()
        source_files = [ROOT / ".workstate/jra-srb" / name for name in
                        ("tipster-chimera-pair-v3/evaluate_stable.py", "tipster-chimera-pair-v2/evaluate_pairs.py", "tipster-trace-v1/evaluate_chimera.py")]
        source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
        hconfig = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
        with HistoryReader(hconfig) as reader:
            history_preflight = reader.preflight()
            prior_rows, history_digest = collect_history(reader)
        with TipsterMarketReader(hconfig) as reader:
            races, rowsets = reader.selected()
            market_report = reader.report
        artifacts.write_json("preflight.json", {"history": history_preflight, "market": market_report, "source_code": source_hashes})
        inputs, excluded = sql_races(races, rowsets, prior_rows)
        content_provenance = {}
        histories, indices, original_wide, audit = legacy.v2.previous.load_history(sql_provenance=content_provenance)
        normalized_wide = {}
        for key, payouts in original_wide.items():
            normalized_wide[key] = {}
            for pair, value in payouts.items():
                normalized_pair = tuple(sorted((horse_number(k) for k in pair), key=int))
                if normalized_pair in normalized_wide[key] and normalized_wide[key][normalized_pair] != value:
                    raise ResearchError("conflicting_wide_settlement", 4)
                normalized_wide[key][normalized_pair] = value
        bundle = histories, indices, normalized_wide, audit
        input_digest = digest({"history": history_digest, "market": market_report["input_digest"],
                               "content": content_provenance["input_digest"], "contract": CONTRACT,
                               "horse_number_format": "two_digit"})
        rows, metadata, audit, _, _ = legacy.v2.previous.build_rows(
            races=inputs, history_bundle=bundle, source_hashes={"sql": input_digest})
        grouped = defaultdict(list)
        for row in rows:
            grouped[row["race_id"]].append(row)
        records = []
        for key, field in grouped.items():
            meta = metadata[key]
            allowed = [{k: v for k, v in row.items() if k not in {"rank", "top3"}} for row in field]
            record = legacy.v2.design(allowed, {"quinella": meta["quinella"]})
            polluted = legacy.v2.design(field, {**meta, "T-10m": {"fake": 99999}})
            if not all(np.array_equal(record[k], polluted[k], equal_nan=True) for k in ("market_x", "history_x", "full_x", "market", "prices")):
                raise ResearchError("outcome_feature_dependency", 4)
            target = np.asarray([float(k in meta["quinella_payout"]) for k in record["keys"]])
            if target.sum() <= 0:
                raise ResearchError("missing_pair_target", 4)
            record.update(race_id=key, race_date=meta["race_date"], target=target / target.sum(),
                wide_target=np.asarray([float(k in meta["wide_payout"]) for k in record["keys"]]),
                q_payout=meta["quinella_payout"], w_payout=meta["wide_payout"])
            records.append(record)
        splits = {name: [r for r in records if r["race_date"] in days] for name, days in DAYS.items()}
        artifacts.write_json("coverage.json", {"sql_candidate_races": len(races), "input_races": len(inputs),
            "adopted_by_split": {k: len(v) for k, v in splits.items()}, "excluded": excluded,
            "legacy_audit": dict(audit), "history_input_digest": history_digest,
            "content_provenance": content_provenance, "input_digest": input_digest})
        if any(not values for values in splits.values()):
            raise ResearchError("empty_smoke_split", 4)
        train, cal = splits["train"], splits["calibration"]
        with threadpool_limits(limits=1):
            transforms = {"recent_x": legacy.stable_content(train, cal, "recent_x", records)}
            models = {"q_history": legacy.fit_q(train, cal, "history_x"),
                      "q_recent": legacy.fit_q(train, cal, "recent_x"),
                      "w_history": legacy.fit_w(train, cal, "history_x")}
            target = artifacts.path / "models.joblib"
            joblib.dump({"models": models, "transforms": transforms, "config": config}, target)
            saved = joblib.load(target)
            predictions, totals = [], {k: {"tickets": 0, "stake_yen": 0, "payout_yen": 0} for k in ("S06", "S08")}
            for record in splits["evaluation"]:
                allowed = {k: v for k, v in record.items() if k not in {"target", "wide_target", "q_payout", "w_payout"}}
                before = legacy.scores(allowed, models, transforms)
                after = legacy.scores(allowed, saved["models"], saved["transforms"])
                for name in before:
                    if not np.array_equal(before[name], after[name]):
                        raise ResearchError("saved_model_prediction_changed", 5)
                for trial, name in (("S06", "w_history"), ("S08", "q_gated")):
                    kind, positions = legacy.choose(trial, after, allowed)
                    for position in positions:
                        pair = record["keys"][position]
                        payout = record["q_payout"] if kind == "quinella" else record["w_payout"]
                        returned = payout.get(pair, 0) * 6
                        totals[trial]["tickets"] += 1
                        totals[trial]["stake_yen"] += 600
                        totals[trial]["payout_yen"] += returned
                        predictions.append({"race_key": record["race_id"], "race_date": record["race_date"],
                            "venue": metadata[record["race_id"]]["course"], "variant": trial, "split": "evaluation",
                            "horses": list(pair), "probability": float(after[name][position]),
                            "target": int(pair in payout), "ticket": {"kind": kind, "stake_yen": 600, "payout_yen": returned}})
        for value in totals.values():
            value["return_rate"] = value["payout_yen"] / value["stake_yen"] if value["stake_yen"] else None
        prediction_hash = artifacts.write_predictions(predictions)
        output = {"run_id": artifacts.run_id, "stage": "sql_path_smoke", "status": "passed",
            "step3_scoped_path_passed": True, "expanded_research_complete": False, "strict_live_replay_eligible": False,
            "sqlite_used": False, "legacy_jsonl_used": False, "contract": CONTRACT,
            "input_guard_enforced": True,
            "adopted_by_split": {k: len(v) for k, v in splits.items()}, "diagnostic_only": totals,
            "model_sha256": hashlib.sha256(target.read_bytes()).hexdigest(), "input_digest": input_digest,
            "outcome_design_checks": len(records), "reload_score_checks": len(splits["evaluation"])}
        artifacts.write_json("metrics.json", output)
        artifacts.finish(overall_complete=False, stage="sql_path_smoke", metrics_sha256=digest(output),
                         predictions_sha256=prediction_hash, step3_scoped_path_passed=True)
        return output
    except ResearchError as error:
        artifacts.fail(error)
        raise
    except Exception as error:
        failure = ResearchError("tipster_smoke_failed", 4, error_type=type(error).__name__)
        artifacts.fail(failure)
        raise failure from None
