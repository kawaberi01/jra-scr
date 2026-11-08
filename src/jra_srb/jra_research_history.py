"""概要: 固定SQL版の保存結果から既存履歴・近走モデルを元データ複製なしで学習する。
作成日: 2026-10-15
入力: 履歴研究JSON設定、研究専用reader接続。
出力: 共通run内の契約付きモデル・評価・入力digest。
実行例: uv run python scripts/run_jra_research.py history --config configs/research/history_sql_v1.json
注意事項: 旧DB/HTTPを使用しない。事後属性を含む研究品質であり当時利用可能性を証明しない。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import warnings

from .jra_research_contracts import ResearchError, canonical_json, digest
from .jra_research_reader import ResearchReader
from .jra_research_resources import check_memory, memory_bytes


HISTORY_PROFILES = {"history_sql_v1", "recent_form_sql_v2"}
LIVE_TABLES = ("live.races", "live.runners", "live.result_entries", "live.payouts")
HISTORY_COLUMNS = {
    "live.races": ("race_id", "race_date", "race_name", "surface", "distance", "source"),
    "live.runners": ("race_id", "horse_no", "frame_no", "horse_name", "sex_age", "weight_carried", "jockey", "trainer"),
    "live.result_entries": ("race_id", "horse_no", "rank"),
    "live.payouts": ("race_id",),
}


def validate_history_columns(table: str, columns: list[dict]) -> None:
    """実inventoryの使用列・型・長さ・NULL・非計算列契約を照合する。

    Notes:
        2026-10-15の移送済みlive表を基準とする。余分な未使用列は許可し、
        メタデータが不可視・不完全な場合は推測して読取を継続しない。
    """
    if not columns:
        raise ResearchError("history_schema_metadata_unavailable", 3, table=table)
    actual = {row["column_name"]: row for row in columns}
    required = (*HISTORY_COLUMNS[table], "__migration_source_snapshot_id", "__migration_source_rowid")
    for name in required:
        row = actual.get(name)
        bigint = name in {"__migration_source_snapshot_id", "__migration_source_rowid", "rank"}
        expected = ("bigint", 8, name != "__migration_source_snapshot_id", False) if bigint else ("nvarchar", -1, True, False)
        observed = None if row is None else tuple(row.get(key) for key in ("sql_type", "max_length", "is_nullable", "is_computed"))
        if observed != expected:
            raise ResearchError("history_schema_contract_failed", 3, table=table, column=name)


@dataclass(frozen=True)
class HistoryConfig:
    """履歴研究の固定版・期間・物理上限を検証する。"""

    raw: dict

    @property
    def snapshot(self) -> int:
        """明示されたanalysis版を返す。"""
        return self.raw["source_policy"]["snapshot_id"]

    @classmethod
    def load(cls, path: str | Path):
        """秘密を含まない設定だけを読み、未知キーと曖昧な型を拒否する。"""
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            if set(raw) != {"schema_version", "profile_id", "source_policy", "date_through", "validation_fraction", "limits"}:
                raise ValueError("keys")
            if type(raw["schema_version"]) is not int or raw["schema_version"] != 1 or raw["profile_id"] not in HISTORY_PROFILES:
                raise ValueError("profile")
            policy = raw["source_policy"]
            if set(policy) != {"source_key", "snapshot_id"} or policy["source_key"] != "analysis-current" or type(policy["snapshot_id"]) is not int or policy["snapshot_id"] <= 0:
                raise ValueError("source")
            if date.fromisoformat(raw["date_through"]).isoformat() != raw["date_through"]:
                raise ValueError("date")
            fraction = raw["validation_fraction"]
            if isinstance(fraction, bool) or not isinstance(fraction, (int, float)) or not 0 < fraction < 1:
                raise ValueError("fraction")
            limits = raw["limits"]
            if set(limits) != {"fetch_rows", "query_timeout_seconds", "memory_bytes", "max_candidate_rows"}:
                raise ValueError("limits")
            for key, maximum in (("fetch_rows", 10000), ("query_timeout_seconds", 90), ("memory_bytes", 2147483648), ("max_candidate_rows", 1500000)):
                if type(limits[key]) is not int or not 0 < limits[key] <= maximum:
                    raise ValueError("limit")
            return cls(raw)
        except (OSError, ValueError, TypeError, KeyError):
            raise ResearchError("invalid_history_config", 2) from None


class HistoryReader(ResearchReader):
    """既存reader接続を使い履歴用の固定SELECTだけを提供する。"""

    def preflight(self) -> dict:
        """固定analysis版と必要表の読取権限・更新不可を検査する。"""
        identity = self._small("history_identity", "SELECT DB_NAME() database_name,IS_SRVROLEMEMBER('sysadmin') sysadmin,IS_ROLEMEMBER('db_owner') db_owner,IS_ROLEMEMBER('db_ddladmin') db_ddladmin,IS_ROLEMEMBER('db_datawriter') db_datawriter")[0]
        if identity["database_name"] != "jra_unified" or any(identity[k] != 0 for k in ("sysadmin", "db_owner", "db_ddladmin", "db_datawriter")):
            raise ResearchError("unexpected_database_or_privilege", 3)
        for scope, name, permissions in (("DATABASE", "jra_unified", ("CONTROL", "ALTER ANY SCHEMA", "CREATE TABLE")),
                                          ("SCHEMA", "live", ("ALTER", "CONTROL")),
                                          ("SCHEMA", "ops", ("ALTER", "CONTROL")),
                                          *(("OBJECT", table, ("SELECT", "INSERT", "UPDATE", "DELETE", "ALTER", "CONTROL")) for table in (*LIVE_TABLES, "ops.source_database", "ops.source_snapshot"))):
            for permission in permissions:
                row = self._small("history_permission", "SELECT HAS_PERMS_BY_NAME(?,?,?) permitted", (name, scope, permission))[0]
                if row["permitted"] != int(permission == "SELECT"):
                    raise ResearchError("permission_contract_failed", 3, object=name, permission=permission)
        source = self._small("history_source", "SELECT d.source_key,s.source_snapshot_id,s.status,s.schema_catalog_sha256 FROM ops.source_snapshot s JOIN ops.source_database d ON d.source_database_id=s.source_database_id WHERE s.source_snapshot_id=?", (self.config.snapshot,))
        if len(source) != 1 or source[0]["source_key"] != self.config.raw["source_policy"]["source_key"] or source[0]["status"] != "verified":
            raise ResearchError("unverified_source", 3)
        indexes = []
        for table in LIVE_TABLES:
            columns = self._small("history_columns", "SELECT c.name column_name,t.name sql_type,c.max_length,c.is_nullable,c.is_computed FROM sys.columns c JOIN sys.types t ON t.user_type_id=c.user_type_id WHERE c.object_id=OBJECT_ID(?) ORDER BY c.column_id", (table,))
            validate_history_columns(table, columns)
            found = self._small("history_indexes", "SELECT i.name,i.is_unique,c.name column_name,ic.key_ordinal FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.object_id=OBJECT_ID(?) AND i.is_disabled=0 AND i.is_hypothetical=0 AND i.has_filter=0 AND i.filter_definition IS NULL AND ic.key_ordinal>0 ORDER BY i.index_id,ic.key_ordinal", (table,))
            grouped = {}
            for row in found:
                grouped.setdefault(row["name"], []).append(row["column_name"])
            if not any(row["is_unique"] and grouped[row["name"]] == ["__migration_source_snapshot_id", "__migration_source_rowid"] for row in found):
                raise ResearchError("keyset_requires_unique_index", 3, table=table)
            indexes.append({"table": table, "indexes": found})
        self.report = {"identity": identity, "source": source[0], "read_consistency": "chunked_unproven",
                       "availability": "research_only", "feature_availability": "retrospective_compatibility",
                       "index_digest": digest(indexes)}
        return self.report

    def history_rows(self, score_race_id: str | None = None):
        """少数のlive固定表を各一巡し、旧builderと同じ母集団をメモリ結合する。

        Notes:
            期間下限で履歴を切らない。巨大raw表にはこの経路を適用しない。
            馬番は旧SQL同様に元値で照合し、重複は停止する。
        """
        races = {}
        self.excluded_outcome_race_id = score_race_id
        self.score_target = None
        self.result_field_sizes = {}
        self.pass_streams = {}
        candidates = {}
        for row in self._table_rows("live.races", ("race_id", "race_date", "race_name", "surface", "distance", "source")):
            key = row["race_id"]
            if (len(key) != 12 or not "01" <= key[8:10] <= "10"
                    or not (row["source"] or "").lower().startswith("https://www.jra.go.jp/")
                    or row["race_date"] > self.config.raw["date_through"]):
                continue
            if key in candidates:
                raise ResearchError("duplicate_key", 4, table="live.races")
            candidates[key] = {name: value for name, value in row.items() if name != "source"}
        if score_race_id is not None:
            if score_race_id not in candidates:
                raise ResearchError("missing_score_card", 4)
            self.score_target = {**candidates[score_race_id], "runners": []}
            races = {key: row for key, row in candidates.items() if row["race_date"] < self.score_target["race_date"]}
        else:
            races = candidates
        paid = {row["race_id"] for row in self._table_rows("live.payouts", ("race_id",)) if row["race_id"] in races}
        ranks = {}
        for row in self._table_rows("live.result_entries", ("race_id", "horse_no", "rank")):
            if row["race_id"] not in paid:
                continue
            key = row["race_id"], row["horse_no"]
            if key in ranks:
                raise ResearchError("duplicate_key", 4, table="live.result_entries")
            ranks[key] = row["rank"]
            self.result_field_sizes[row["race_id"]] = self.result_field_sizes.get(row["race_id"], 0) + 1
        columns = ("race_id", "horse_no", "frame_no", "horse_name", "sex_age", "weight_carried", "jockey", "trainer")
        for row in self._table_rows("live.runners", columns):
            key = row["race_id"], row["horse_no"]
            if row["race_id"] == score_race_id:
                if any(runner["horse_no"] == row["horse_no"] for runner in self.score_target["runners"]):
                    raise ResearchError("duplicate_key", 4, table="live.runners")
                self.score_target["runners"].append(row)
            if key in ranks:
                yield {**races[row["race_id"]], **row, "rank": ranks[key]}

    def _table_rows(self, table: str, fields: tuple[str, ...]):
        """許可したlive表だけを固定版/一意rowid索引で走査する。"""
        if table not in LIVE_TABLES:
            raise ResearchError("invalid_history_table", 3)
        fields = ("__migration_source_rowid", *fields)
        previous, seen = None, 0
        stream = hashlib.sha256((table + "\n").encode("utf-8"))
        while True:
            limits = self.config.raw["limits"]
            size = min(limits["fetch_rows"], limits["max_candidate_rows"] - seen + 1)
            sql = "SELECT TOP (?) " + ",".join("[" + name + "]" for name in fields)
            sql += f" FROM {table} WHERE __migration_source_snapshot_id=?"
            params = [size, self.config.snapshot]
            excluded = getattr(self, "excluded_outcome_race_id", None)
            if excluded is not None and table in {"live.result_entries", "live.payouts"}:
                sql += " AND race_id<>?"
                params.append(excluded)
            if previous is not None:
                sql += " AND __migration_source_rowid>?"
                params.append(previous)
            sql += " ORDER BY __migration_source_rowid"
            with self._cursor("history_keyset:" + table, sql, params) as cursor:
                rows = cursor.fetchmany(size)
            if not rows:
                self.pass_streams[table] = stream.hexdigest()
                return
            check_memory(limits["memory_bytes"])
            for values in rows:
                row = dict(zip(fields, values, strict=True))
                stream.update((canonical_json(row) + "\n").encode("utf-8"))
                identifier = row.pop("__migration_source_rowid")
                if identifier is None or previous is not None and identifier <= previous:
                    raise ResearchError("invalid_keyset_rowid", 3)
                seen += 1
                self.scan_rows[table] = self.scan_rows.get(table, 0) + 1
                if seen > limits["max_candidate_rows"]:
                    raise ResearchError("scan_row_limit", 4, table=table)
                previous = identifier
                yield row


def collect_history(reader) -> tuple[list[dict], str]:
    """固定版の利用全列を二巡照合し、二重レース馬キーを拒否する。"""
    first, first_stream = None, None
    for _ in range(2):
        rows, keys = [], set()
        stream = hashlib.sha256(b"jra-history-sql-input-v1\n")
        for row in reader.history_rows():
            key = (row["race_id"], str(row["horse_no"]))
            if key in keys:
                raise ResearchError("duplicate_key", 4)
            keys.add(key)
            stream.update((canonical_json(row) + "\n").encode("utf-8"))
            rows.append(row)
        content = stream.hexdigest()
        source_stream = digest(getattr(reader, "pass_streams", {}))
        if first is not None and (first != content or first_stream != source_stream):
            raise ResearchError("source_changed", 5)
        if first is None:
            first = content
            first_stream = source_stream
            del rows, keys
    return rows, content


def legacy_row_order(row: dict) -> tuple:
    """旧SQLiteの開催日・ID・馬番整数順に揃える。非数値馬番は旧CAST同様0扱いとする。"""
    try:
        number = int(row["horse_no"])
    except (TypeError, ValueError):
        number = 0
    return row["race_date"], row["race_id"], number


def numeric_output_digest(model: dict, metrics: dict) -> str:
    """作成時刻とそれに依存する旧artifact hashを除き計算結果の一致を検査する。"""
    numerical_model = {key: value for key, value in model.items() if key not in {"created_at", "artifact_hash"}}
    numerical_metrics = {key: value for key, value in metrics.items() if key != "released_artifact_hash"}
    return digest({"model": numerical_model, "metrics": numerical_metrics})


def collect_history_score(reader: HistoryReader, race_id: str) -> tuple[list[dict], dict, dict, str]:
    """対象結果を除くSQL入力と保存カードを二巡照合する。

    Returns:
        過去行、対象カード、旧近走計算に必要な結果頭数、入力内容SHA。
    Raises:
        ResearchError: 対象カード不足、重複、二巡間の変更。
    """
    previous = None
    for _ in range(2):
        rows, keys = [], set()
        for row in reader.history_rows(score_race_id=race_id):
            key = row["race_id"], str(row["horse_no"])
            if key in keys:
                raise ResearchError("duplicate_key", 4)
            keys.add(key)
            rows.append(row)
        card = reader.score_target
        if card is None or not card["runners"]:
            raise ResearchError("missing_score_card", 4)
        card["runners"].sort(key=lambda runner: legacy_row_order({**card, **runner}))
        content = digest({"history": rows, "card": card, "field_sizes": reader.result_field_sizes,
                          "source_streams": reader.pass_streams})
        if previous is not None and previous != content:
            raise ResearchError("source_changed", 5)
        previous = content
    return rows, card, reader.result_field_sizes, content


def history_score_records(rows: list[dict], card: dict, field_sizes: dict, *, recent: bool) -> list[dict]:
    """SQLメモリ行から旧liveと同じ前日までの履歴・近走特徴を作る。

    Notes:
        共有moduleのDB関数は呼ばず、状態更新と特徴数式の純計算だけを再利用する。
        近走の分母は旧live SQL同様、runner結合数ではなく結果表の全頭数。
    """
    from collections import defaultdict, deque
    from .jra_history_dataset import COURSE_CODES, _build_history_states, _distance_band, _feature_vector, _number, _surface, _text
    from .jra_recent_form_dataset import _append, _result

    target_date = date.fromisoformat(card["race_date"])
    if any(row["race_date"] >= card["race_date"] for row in rows):
        raise ResearchError("score_history_not_before_target", 4)
    rows = sorted(rows, key=legacy_row_order)
    states = _build_history_states(rows)
    course = COURSE_CODES[card["race_id"][8:10]]
    surface, distance = _surface(card["surface"]), _number(card["distance"]) or 0
    band = _distance_band(distance, card["race_name"])
    records = []
    for runner in card["runners"]:
        horse, jockey, trainer = (_text(runner.get(name), "unknown") for name in ("horse_name", "jockey", "trainer"))
        record = {"race_id": card["race_id"], "race_date": card["race_date"], "horse_no": str(runner["horse_no"]),
                  "horse_name": horse, "features": _feature_vector(row=runner, race_date=target_date,
                      race_name=_text(card["race_name"], ""), course=course, surface=surface, distance=distance,
                      field_size=len(card["runners"]), horse=states["horse"][horse],
                      horse_course=states["horse_course"][(horse, course)],
                      horse_surface=states["horse_surface"][(horse, surface)],
                      horse_distance=states["horse_distance"][(horse, band)],
                      jockey=states["jockey"][jockey], trainer=states["trainer"][trainer])}
        records.append(record)
    if recent:
        histories = defaultdict(lambda: deque(maxlen=5))
        names = {record["horse_name"] for record in records}
        for row in rows:
            if row["horse_name"] in names and row["rank"] is not None:
                histories[str(row["horse_name"])].append(_result(int(row["rank"]), field_sizes[row["race_id"]]))
        records = [_append(record, histories[record["horse_name"]]) for record in records]
    return records


def load_history_score_artifact(path: str | Path, config: HistoryConfig) -> tuple[dict, str]:
    """complete runの契約付きモデルだけをhash・列順・有限数値型まで検査する。

    Raises:
        ResearchError: 旧artifact、未完了run、改変、別profile・版、数値構造不一致。
    """
    from .jra_history_dataset import FEATURE_NAMES
    from .jra_recent_form_dataset import RECENT_FORM_SCHEMA
    from .jra_history_model import MODEL_VERSION, RECENT_FORM_MODEL_VERSION, _artifact_hash
    from .jra_research_artifacts import existing_run

    try:
        path = Path(path).resolve()
        run_path = existing_run(path.parent.name).resolve()
        if path.parent != run_path or path.name != "model_history.json":
            raise ValueError("location")
        manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
        wrapper = json.loads(path.read_text(encoding="utf-8"))
        if manifest["status"] != "complete" or manifest["command"] not in {"history", "history-replay"}:
            raise ValueError("state")
        contract, model = wrapper["contract"], wrapper["model"]
        recent = config.raw["profile_id"] == "recent_form_sql_v2"
        names = RECENT_FORM_SCHEMA if recent else FEATURE_NAMES
        expected = {"profile_id": config.raw["profile_id"], "feature_names": names,
                    "history_identity": "horse_name_legacy", "update_policy": "after_each_race_legacy",
                    "source_snapshot": config.snapshot, "source_input_sha256": manifest["input_content_sha256"],
                    "availability": "retrospective_compatibility", "release_fit": "all_rows_after_holdout_evaluation"}
        if (contract != expected or wrapper["contract_sha256"] != digest(contract)
                or manifest["feature_contract_sha256"] != digest(contract) or manifest["model_sha256"] != digest(model)
                or model["feature_names"] != names or model["model_version"] != (RECENT_FORM_MODEL_VERSION if recent else MODEL_VERSION)
                or model["artifact_hash"] != _artifact_hash({k: v for k, v in model.items() if k != "artifact_hash"})):
            raise ValueError("contract")
        vectors = [model["scaler"]["mean"], model["scaler"]["scale"]]
        if set(model["models"]) != {"win", "top3"}:
            raise ValueError("targets")
        intercepts = []
        for target in ("win", "top3"):
            vectors.append(model["models"][target]["coefficients"])
            intercepts.append(model["models"][target]["intercept"])
        if any(not isinstance(vector, list) or len(vector) != len(names) for vector in vectors):
            raise ValueError("shape")
        if any(type(value) not in (int, float) or not math.isfinite(value) for vector in vectors for value in vector):
            raise ValueError("numeric")
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in intercepts):
            raise ValueError("numeric")
        if any(value <= 0 for value in model["scaler"]["scale"]):
            raise ValueError("scale")
        return model, wrapper["contract_sha256"]
    except (OSError, ValueError, KeyError, TypeError, ResearchError):
        raise ResearchError("history_model_contract_mismatch", 2) from None


def execute_history_score(config_path: str | Path, model_path: str | Path, race_id: str) -> dict:
    """対象結果を読まない保存済みSQLカードを、契約付き履歴モデルでscoreする。

    Notes:
        SQL接続を閉じた後に純計算を行う。保存は確率・来歴・digestのみ。
        全量refit済みモデルの過去日scoreは回顧研究であり、未見holdout評価ではない。
    """
    from .jra_history_model import score_live_records
    from .jra_research_artifacts import RunArtifacts

    config = HistoryConfig.load(config_path)
    artifacts = RunArtifacts(config.raw, "history-score")
    reader = None
    try:
        if not isinstance(race_id, str) or len(race_id) != 12 or not race_id.isascii() or not race_id.isdigit() or not "01" <= race_id[8:10] <= "10":
            raise ResearchError("invalid_score_race_id", 2)
        model, contract_sha = load_history_score_artifact(model_path, config)
        with HistoryReader(config) as reader:
            report = reader.preflight()
            artifacts.write_json("preflight.json", report)
            rows, card, field_sizes, content = collect_history_score(reader, race_id)
            artifacts.manifest.update(query_metrics=reader.query_metrics, input_content_sha256=content,
                provenance={**report, "scan_rows_all_passes": reader.scan_rows, "source_table_streams_sha256": reader.pass_streams})
        records = history_score_records(rows, card, field_sizes, recent=config.raw["profile_id"] == "recent_form_sql_v2")
        check_memory(config.raw["limits"]["memory_bytes"])
        scored = score_live_records(model, records)
        output = {"profile_id": config.raw["profile_id"], "race_id": race_id, "outcome_read": False,
                  "history_before": card["race_date"], "availability": "retrospective_compatibility",
                  "model_trained_through": model["trained_through"], "evaluation_kind": "released_model_score_not_holdout",
                  "predictions": [{"horse_no": row["horse_no"], **{key: row[key] for key in
                      ("win_probability", "top3_probability", "win_probability_race_normalized")}} for row in scored]}
        artifacts.write_json("metrics.json", output)
        artifacts.finish(metrics_sha256=digest(output), feature_contract_sha256=contract_sha,
                         model_sha256=digest(model), outcome_read=False)
        return {"status": "passed", "run_id": artifacts.run_id, **output, "overall_complete": False}
    except Exception as error:
        if reader is not None:
            artifacts.manifest["query_metrics"] = reader.query_metrics
        safe = error if isinstance(error, ResearchError) else ResearchError("history_score_failed", 4, error_type=type(error).__name__)
        artifacts.fail(safe)
        safe.details["run_id"] = artifacts.run_id
        raise safe from None


def execute_history(path: str | Path | None = None, *, replay_run_id: str | None = None) -> dict:
    """SQLを閉じてから既存純計算を実行し、モデル・評価だけを保存する。"""
    from sklearn.exceptions import ConvergenceWarning
    from threadpoolctl import threadpool_limits
    from .jra_history_dataset import FEATURE_NAMES, build_history_dataset_from_rows
    from .jra_recent_form_dataset import RECENT_FORM_SCHEMA, append_recent_form_features
    from .jra_history_model import MODEL_VERSION, RECENT_FORM_MODEL_VERSION, train_history_models
    from .jra_research_artifacts import RunArtifacts, existing_run

    original = None
    if replay_run_id:
        prior_path = existing_run(replay_run_id)
        original = json.loads((prior_path / "manifest.json").read_text(encoding="utf-8"))
        if original.get("command") not in {"history", "history-replay"} or original.get("status") != "complete":
            raise ResearchError("run_not_replayable", 2)
        if not original.get("numeric_outputs_sha256"):
            raise ResearchError("run_contract_incomplete", 2)
        path = prior_path / "config.json"
    config = HistoryConfig.load(path)
    artifacts = RunArtifacts(config.raw, "history-replay" if replay_run_id else "history")
    reader = None
    try:
        with HistoryReader(config) as reader:
            report = reader.preflight()
            artifacts.write_json("preflight.json", report)
            rows, content = collect_history(reader)
            artifacts.manifest.update(query_metrics=reader.query_metrics, input_content_sha256=content,
                                      provenance={**report, "scan_rows_all_passes": reader.scan_rows,
                                                  "source_table_streams_sha256": reader.pass_streams})
        if original is not None:
            if content != original.get("input_content_sha256") or artifacts.manifest["provenance"] != original.get("provenance"):
                raise ResearchError("replay_input_changed", 5)
            artifacts.manifest["replay_of"] = replay_run_id
        rows.sort(key=legacy_row_order)
        records, metadata = build_history_dataset_from_rows(rows)
        del rows
        recent = config.raw["profile_id"] == "recent_form_sql_v2"
        if recent:
            records = append_recent_form_features(records)
        check_memory(config.raw["limits"]["memory_bytes"])
        width = len(RECENT_FORM_SCHEMA if recent else FEATURE_NAMES)
        if memory_bytes() + len(records) * width * 8 * 10 > config.raw["limits"]["memory_bytes"]:
            raise ResearchError("model_memory_budget", 4)
        with threadpool_limits(limits=1), warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            model, metrics = train_history_models(records, validation_fraction=config.raw["validation_fraction"],
                feature_names=RECENT_FORM_SCHEMA if recent else FEATURE_NAMES,
                model_version=RECENT_FORM_MODEL_VERSION if recent else MODEL_VERSION)
        check_memory(config.raw["limits"]["memory_bytes"])
        contract = {"profile_id": config.raw["profile_id"], "feature_names": model["feature_names"],
                    "history_identity": "horse_name_legacy", "update_policy": "after_each_race_legacy",
                    "source_snapshot": config.snapshot, "source_input_sha256": content,
                    "availability": "retrospective_compatibility", "release_fit": "all_rows_after_holdout_evaluation"}
        numerical_digest = numeric_output_digest(model, metrics)
        if original is not None and numerical_digest != original["numeric_outputs_sha256"]:
            raise ResearchError("replay_output_changed", 5)
        artifacts.write_json("model_history.json", {"contract": contract, "contract_sha256": digest(contract), "model": model})
        artifacts.write_json("metrics.json", metrics)
        artifacts.write_json("coverage.json", {**metadata, "feature_names": contract["feature_names"], "coverage_basis": "stored_official_result_races"})
        artifacts.finish(metrics_sha256=digest(metrics), model_sha256=digest(model), feature_contract_sha256=digest(contract),
                         numeric_outputs_sha256=numerical_digest)
        return {"status": "passed", "run_id": artifacts.run_id, "profile_id": config.raw["profile_id"],
                "races": metadata["races"], "runner_rows": metadata["runner_rows"], "overall_complete": False}
    except Exception as error:
        if reader is not None:
            artifacts.manifest["query_metrics"] = reader.query_metrics
        safe = error if isinstance(error, ResearchError) else ResearchError("history_execution_failed", 4, error_type=type(error).__name__)
        artifacts.fail(safe)
        safe.details["run_id"] = artifacts.run_id
        raise safe from None
