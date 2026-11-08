"""概要: 固定した6案で予想家由来研究のSQL増量・内容効果を比較する。
作成日: 2026-10-17
入力: 固定SQL31/34版、spec100の期間・方式、既存研究純計算。
出力: 新規run内のモデル・全ペア予測・買い目・比較・入力充足。
実行例: uv run --frozen --extra ml python scripts/run_jra_tipster_experiment.py
注意事項: SELECT専用。既参照期間の事後研究。旧成果物・運用・SQLは変更しない。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
import hashlib
from itertools import combinations
import json
import traceback

import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from .jra_research_artifacts import ROOT, RunArtifacts
from .jra_research_contracts import ResearchError, digest, horse_number
from .jra_research_history import HistoryConfig, HistoryReader, collect_history
from .jra_research_resources import check_memory
from . import jra_research_tipster_smoke as base


CONFIG = {
    "contract": base.CONTRACT, "protocol": "spec100-tipster-six-v1",
    "train": ["2024-01-01", "2025-09-30"], "recent_from": "2025-01-01",
    "calibration": ["2025-10-01", "2025-10-31"],
    "evaluation": ["2025-11-01", "2026-05-31"], "exclude_months": [6, 7, 8],
    "variants": [f"{span}_{trial}" for span in ("recent", "long")
                 for trial in ("S06", "S08_history", "S08")],
    "availability": "retrospective_research_only", "unseen_test": False,
    "seed": 42, "stake_yen": 600, "max_races": 12000,
}


def split(day):
    """事前固定した季節除外と時系列分割を返す。"""
    if int(day[5:7]) in CONFIG["exclude_months"]:
        return None
    if CONFIG["train"][0] <= day <= CONFIG["train"][1]:
        return "train"
    if CONFIG["calibration"][0] <= day <= CONFIG["calibration"][1]:
        return "calibration"
    if "2025-11-01" <= day <= "2025-12-31":
        return "evaluation_2025"
    if "2026-01-01" <= day <= "2026-02-28":
        return "evaluation_early"
    if "2026-03-01" <= day <= "2026-05-31":
        return "evaluation_late"
    return None


class ExperimentMarketReader(base.TipsterMarketReader):
    """同一接続の固定版・列・索引・権限検査を一度だけ実施する。"""

    def _small(self, query_id, sql, params=()):
        """metadata検査だけを接続内再利用し、市場・カード・払戻は毎回SQLから読む。"""
        if query_id in {"tipster_market:" + name for name in ("source", "columns", "indexes", "permission")}:
            if not hasattr(self, "_metadata_cache"):
                self._metadata_cache = {}
            key = (query_id, tuple(params))
            if key not in self._metadata_cache:
                self._metadata_cache[key] = super()._small(query_id, sql, params)
            return self._metadata_cache[key]
        return super()._small(query_id, sql, params)


class PriorStates:
    """共有純計算と同じレース順で対象日前だけの履歴統計を逐次更新する。"""

    def __init__(self, rows):
        """有効履歴をレース単位にまとめ、更新前の空統計を用意する。"""
        grouped = defaultdict(list)
        for row in rows:
            if base.history._valid_row(row):
                grouped[str(row["race_id"])].append(row)
        self.races = sorted(grouped.items(), key=lambda item: (item[1][0]["race_date"], item[0]))
        self.states = base.history._build_history_states([])
        self.position, self.last_day = 0, ""

    def before(self, day):
        """同日成績を含めず日付昇順の統計を返し、逆行を拒否する。"""
        if day < self.last_day:
            raise ResearchError("history_date_regression", 4)
        self.last_day = day
        h = base.history
        while self.position < len(self.races):
            race_id, rows = self.races[self.position]
            first = rows[0]
            if first["race_date"] >= day:
                break
            course = h.COURSE_CODES[race_id[8:10]]
            surface = h._surface(first.get("surface"))
            band = h._distance_band(h._number(first.get("distance")) or 0, first.get("race_name"))
            for row in rows:
                horse = h._text(row.get("horse_name"), "unknown")
                identities = {
                    "horse": horse, "horse_course": (horse, course), "horse_surface": (horse, surface),
                    "horse_distance": (horse, band), "jockey": h._text(row.get("jockey"), "unknown"),
                    "trainer": h._text(row.get("trainer"), "unknown"),
                }
                for name, key in identities.items():
                    self.states[name][key].update(int(row["rank"]), len(rows), date.fromisoformat(first["race_date"]))
            self.position += 1
        return self.states


def state_signature(states):
    """逐次更新と共有純計算の統計内容だけを比較できる表現へ変換する。"""
    return {name: {key: vars(value) for key, value in values.items()} for name, values in states.items()}


def normalized_wide(original):
    """ワイド精算の馬番を2桁へ統一し、衝突を拒否する。"""
    output = {}
    for key, values in original.items():
        output[key] = {}
        for pair, value in values.items():
            normalized = tuple(sorted((horse_number(k) for k in pair), key=int))
            if normalized in output[key] and output[key][normalized] != value:
                raise ResearchError("conflicting_wide_settlement", 4)
            output[key][normalized] = value
    return output


def settlement_reason(race, wide):
    """通常一意着順とワイド全3本の対応を確認し、不適格理由を返す。"""
    ranks = race["result"]["ranks_by_horse"]
    if sorted(ranks.values()) != list(range(1, len(ranks) + 1)):
        return "non_unique_or_incomplete_ranks"
    top = sorted((key for key, rank in ranks.items() if rank <= 3), key=int)
    expected = set(combinations(top, 2))
    info = race["race"]
    payouts = wide.get((race["race_date"], info["course"], int(info["race_no"])), {})
    if set(payouts) != expected or any(type(v) is not int or v <= 0 for v in payouts.values()):
        return "incomplete_wide_settlement"
    return None


def batch_records(inputs, legacy, bundle, observed):
    """最大7日分だけ馬別中間行を保持し、結果非依存を検証した設計へ変換する。"""
    rows, metadata, _, _, _ = legacy.v2.previous.build_rows(
        races=inputs, history_bundle=bundle, source_hashes={"contract": base.CONTRACT}, split_selector=split)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["race_id"]].append(row)
    records = []
    for key, field in grouped.items():
        meta = metadata[key]
        allowed = [{k: v for k, v in row.items() if k not in {"rank", "top3"}} for row in field]
        record = legacy.v2.design(allowed, {"quinella": meta["quinella"]})
        polluted = legacy.v2.design(field, {**meta, "T-10m": {"fake": 99999}})
        if not all(np.array_equal(record[k], polluted[k], equal_nan=True)
                   for k in ("market_x", "history_x", "full_x", "market", "prices")):
            raise ResearchError("outcome_feature_dependency", 4)
        target = np.asarray([float(k in meta["quinella_payout"]) for k in record["keys"]])
        if target.sum() != 1:
            raise ResearchError("ambiguous_pair_target", 4)
        # 同じfloat64列の重複所有を避ける。値・順序・精度は変えない。
        record["history_x"] = record["full_x"][:, :record["history_x"].shape[1]]
        del record["market_x"]
        record.update(race_id=key, race_date=meta["race_date"], course=meta["course"],
            period=split(meta["race_date"]), target=target,
            wide_target=np.asarray([float(k in meta["wide_payout"]) for k in record["keys"]]),
            q_payout=meta["quinella_payout"], w_payout=meta["wide_payout"],
            runner_market={row["key"]: row["market_probability"] for row in field})
        if record["period"] == "train" and record["race_date"] < CONFIG["recent_from"]:
            record["history_x"] = record["history_x"].copy()
            del record["full_x"]
        records.append(record)
        for row in field:
            counter = observed[record["period"]]
            counter["runners"] += 1
            counter["with_history"] += int(row["has_history"])
            counter["with_content"] += int(row["past_runs"] > 0)
            counter["with_corner"] += int(np.isfinite(row["content"][9]))
            counter["with_pace"] += int(np.isfinite(row["content"][10]))
    return records


def prepare(artifacts, legacy):
    """SQLだけを有界読取し入力充足と全設計行列の結果非依存を保存する。"""
    hconfig = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
    with HistoryReader(hconfig) as reader:
        hpreflight = reader.preflight()
        prior_rows, history_digest = collect_history(reader)
    state = PriorStates(prior_rows)
    for day in ("2024-01-01", "2025-09-06", "2026-05-31"):
        actual = state.before(day)
        expected = base.history._build_history_states(row for row in prior_rows if row["race_date"] < day)
        if state_signature(actual) != state_signature(expected):
            raise ResearchError("incremental_history_mismatch", 4)
    del actual, expected
    state = PriorStates(prior_rows)
    provenance = {}
    histories, indices, original, audit = legacy.v2.previous.load_history(sql_provenance=provenance)
    wide = normalized_wide(original)
    bundle = histories, indices, wide, audit
    days, current = [], date.fromisoformat(CONFIG["train"][0])
    while current.isoformat() <= CONFIG["evaluation"][1]:
        if split(current.isoformat()):
            days.append(current.isoformat())
        current += timedelta(days=1)
    candidates, records, excluded, batch_reports = [], [], [], []
    observed = defaultdict(Counter)
    input_count = 0
    with ExperimentMarketReader(hconfig) as reader:
        for offset in range(0, len(days), 7):
            races, rowsets = reader.selected(days[offset:offset + 7])
            candidates.extend(races)
            if len(candidates) > CONFIG["max_races"]:
                raise ResearchError("experiment_race_limit", 4)
            batch_reports.append({"days": days[offset:offset + 7], "digest": reader.report["input_digest"]})
            converted, missing = base.sql_races(races, rowsets, prior_rows, state_provider=state.before)
            excluded.extend(missing)
            inputs = []
            for race in converted:
                reason = settlement_reason(race, wide)
                if reason:
                    excluded.append({"race_key": race["race_id"], "reason": reason})
                else:
                    inputs.append(race)
            input_count += len(inputs)
            batch = batch_records(inputs, legacy, bundle, observed)
            adopted_batch = {r["race_id"] for r in batch}
            for race in inputs:
                if race["race_id"] not in adopted_batch:
                    excluded.append({"race_key": race["race_id"], "reason": "trace_ineligible"})
            records.extend(batch)
            check_memory(2147483648)
            if offset % 140 == 0:
                print(json.dumps({"stage": "sql_input", "through": days[min(offset + 6, len(days) - 1)],
                                  "candidates": len(candidates), "usable": len(records)}), flush=True)
        market_report = {"source": reader.report["source"], "batches": batch_reports,
                         "queries": reader.query_metrics}
    input_digest = digest({"history": history_digest, "content": provenance["input_digest"],
                           "batches": batch_reports, "contract": base.CONTRACT})
    artifacts.write_json("preflight.json", {"history": hpreflight, "market": market_report,
        "content": provenance, "incremental_checks": 3,
        "legacy_code": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in (ROOT / legacy.__file__, ROOT / legacy.v2.__file__, ROOT / legacy.v2.previous.__file__)}})
    adopted = {r["race_id"] for r in records}
    strata = defaultdict(Counter)
    for race in candidates:
        meta = json.loads(race["retrospective_metadata_json"])
        group = (race["race_date"][:7], race["venue_code"], str(meta.get("track_code")))
        strata[group]["candidate"] += 1
        strata[group]["adopted"] += int(race["race_key"] in adopted)
    coverage = {"candidate_races": len(candidates), "input_races": input_count,
        "adopted_by_split": dict(Counter(r["period"] for r in records)),
        "months": {month: {"candidate": sum(r["race_date"].startswith(month) for r in candidates),
                            "adopted": sum(r["race_date"].startswith(month) for r in records)}
                   for month in sorted({d[:7] for d in days})},
        "strata": [{"month": k[0], "venue": k[1], "track": k[2], **v} for k, v in sorted(strata.items())],
        "observed": dict(observed), "excluded_reasons": dict(Counter(r["reason"] for r in excluded)),
        "legacy_audit": dict(audit), "input_digest": input_digest}
    artifacts.write_excluded(excluded)
    artifacts.write_json("coverage.json", coverage)
    if len(adopted) != len(records) or len(candidates) != len(records) + len(excluded):
        raise ResearchError("coverage_accounting_failed", 4)
    if any(not any(r["period"] == p for r in records)
           for p in ("train", "calibration", "evaluation_2025", "evaluation_early", "evaluation_late")):
        raise ResearchError("empty_experiment_split", 4)
    return records, coverage


def summary(tickets):
    """時系列買い目の会計・最大資金減少・払戻集中を集計する。"""
    stake = sum(t["stake_yen"] for t in tickets)
    payout = sum(t["payout_yen"] for t in tickets)
    balance = peak = drawdown = 0
    for ticket in tickets:
        balance += ticket["payout_yen"] - ticket["stake_yen"]
        peak = max(peak, balance)
        drawdown = max(drawdown, peak - balance)
    top = max((t["payout_yen"] for t in tickets), default=0)
    return {"races": len(tickets), "days": len({t["race_date"] for t in tickets}),
            "stake_yen": stake, "payout_yen": payout, "profit_yen": payout - stake,
            "return_rate": payout / stake if stake else None, "max_drawdown_yen": drawdown,
            "top_payout_share": top / payout if payout else None,
            "return_rate_without_top_payout": (payout - top) / stake if stake else None}


def evaluate(artifacts, legacy, records, coverage):
    """固定6案を学習し全予測・保存後一致・同一対象比較を保存する。"""
    train = [r for r in records if r["period"] == "train"]
    recent = [r for r in train if r["race_date"] >= CONFIG["recent_from"]]
    calibration = [r for r in records if r["period"] == "calibration"]
    evaluated = [r for r in records if r["period"].startswith("evaluation")]
    families = {}
    transforms = {"recent_x": legacy.stable_content(recent, calibration, "recent_x", recent + calibration)}
    check_memory(2147483648)
    q_recent = legacy.fit_q(recent, calibration, "recent_x")
    for name, data in (("recent", recent), ("long", train)):
        models = {"q_history": legacy.fit_q(data, calibration, "history_x"),
                  "q_recent": q_recent,
                  "w_history": legacy.fit_w(data, calibration, "history_x")}
        check_memory(2147483648)
        families[name] = {"models": models, "transforms": transforms, "training_races": len(data)}
        print(json.dumps({"stage": "trained", "family": name, "races": len(data)}), flush=True)
    path = artifacts.path / "models.joblib"
    joblib.dump({"families": families, "config": CONFIG}, path)
    saved = joblib.load(path)["families"]
    tickets, losses = defaultdict(list), defaultdict(list)
    reload_checks = 0
    def prediction_rows():
        """全ペア予測を逐次保存へ渡し、大量予測のメモリ保持を避ける。"""
        nonlocal reload_checks
        for record in evaluated:
            allowed = {k: v for k, v in record.items() if k not in {"target", "wide_target", "q_payout", "w_payout"}}
            market_wide = legacy.market_wide(allowed)
            values = {"q_market": record["market"], "w_market": market_wide}
            for span, family in families.items():
                before = legacy.scores(allowed, family["models"], family["transforms"])
                after = legacy.scores(allowed, saved[span]["models"], saved[span]["transforms"])
                if not all(np.array_equal(before[k], after[k]) for k in before):
                    raise ResearchError("saved_model_prediction_changed", 5)
                reload_checks += 1
                values.update({span + "/" + k: v for k, v in after.items()})
                for trial, score_name in (("S06", "w_history"), ("S08_history", "q_history"), ("S08", "q_gated")):
                    variant = span + "_" + trial
                    supplied = after if trial != "S08_history" else {**after, "q_gated": after["q_history"]}
                    kind, positions = legacy.choose("S06" if trial == "S06" else "S08", supplied, allowed)
                    payouts = record["w_payout"] if kind == "wide" else record["q_payout"]
                    chosen = set(positions)
                    for index, pair in enumerate(record["keys"]):
                        ticket = {"kind": kind, "stake_yen": 600 if index in chosen else 0,
                                  "payout_yen": payouts.get(pair, 0) * 6 if index in chosen else 0}
                        if index in chosen:
                            tickets[variant].append({**ticket, "race_key": record["race_id"],
                                                    "race_date": record["race_date"], "period": record["period"]})
                        yield {"race_key": record["race_id"], "race_date": record["race_date"],
                            "venue": record["course"], "variant": variant, "split": record["period"],
                            "horses": list(pair), "probability": float(after[score_name][index]),
                            "target": int(pair in payouts), "ticket": ticket}
            for name, probability in values.items():
                is_wide = name.split("/")[-1].startswith("w_")
                target = record["wide_target"] if is_wide else record["target"]
                label = "brier" if is_wide else "logloss"
                loss = (np.mean((probability - target) ** 2) if is_wide else
                        -target @ np.log(np.maximum(probability, 1e-15)))
                for part in (record["period"], "all"):
                    losses[(part, name, label)].append(float(loss))
                    if not is_wide:
                        losses[(part, name, "brier")].append(float(np.mean((probability - target) ** 2)))
            check_memory(2147483648)
    prediction_hash = artifacts.write_predictions(prediction_rows())
    parts = ("evaluation_2025", "evaluation_early", "evaluation_late", "all")
    results = {variant: {part: summary([t for t in tickets[variant] if part == "all" or t["period"] == part])
                         for part in parts} for variant in CONFIG["variants"]}
    comparisons = {}
    pairs = [("recent_" + trial, "long_" + trial) for trial in ("S06", "S08_history", "S08")]
    pairs += [(span + "_S08_history", span + "_S08") for span in ("recent", "long")]
    for left, right in pairs:
        common = {t["race_key"] for t in tickets[left]} & {t["race_key"] for t in tickets[right]}
        comparisons[left + " -> " + right] = {"common_races": len(common),
            "left": summary([t for t in tickets[left] if t["race_key"] in common]),
            "right": summary([t for t in tickets[right] if t["race_key"] in common])}
    metrics = {"run_id": artifacts.run_id, "stage": "tipster_step4_fixed_experiment", "status": "passed",
        "step3_s06_s08_period_path_complete": True, "step4_fixed_experiment_complete": True,
        "all_priority_models_complete": False, "live_adopted": False, "strict_live_replay_eligible": False,
        "unseen_test": False, "sqlite_used": False, "legacy_jsonl_used": False, "input_guard_enforced": True,
        "contract": base.CONTRACT, "input_digest": coverage["input_digest"],
        "adopted_by_split": coverage["adopted_by_split"], "recent_training_races": len(recent),
        "outcome_design_checks": len(records), "reload_score_checks": reload_checks,
        "quality": [{"period": k[0], "model": k[1], "metric": k[2], "value": float(np.mean(v)), "races": len(v)}
                    for k, v in sorted(losses.items())],
        "feature_selection": {span: {"kept": family["transforms"]["recent_x"]["keep"].tolist(),
            "train_observed": family["transforms"]["recent_x"]["train_observed"].tolist(),
            "calibration_observed": family["transforms"]["recent_x"]["calibration_observed"].tolist()}
                              for span, family in families.items()},
        "results": results, "matched_comparisons": comparisons,
        "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    artifacts.write_json("metrics.json", metrics)
    artifacts.finish(overall_complete=False, stage=metrics["stage"], step4_fixed_experiment_complete=True,
                     predictions_sha256=prediction_hash, metrics_sha256=digest(metrics))
    return {"run_id": artifacts.run_id, "counts": coverage["adopted_by_split"],
            "results": {k: v["all"] for k, v in results.items()}}


def execute_experiment():
    """拒否ガード付き専用プロセスで実行し、失敗を秘密なしで保存する。"""
    base.install_input_guard()
    np.random.seed(CONFIG["seed"])
    artifacts = RunArtifacts(CONFIG, "tipster-step4-fixed-experiment")
    print(json.dumps({"run_id": artifacts.run_id, "stage": "starting"}), flush=True)
    try:
        legacy = base.load_legacy()
        records, coverage = prepare(artifacts, legacy)
        with threadpool_limits(limits=1):
            return evaluate(artifacts, legacy, records, coverage)
    except ResearchError as error:
        artifacts.fail(error)
        raise
    except Exception as error:
        frames = [{"file": f.filename.replace("\\", "/").rsplit("/", 1)[-1],
                   "line": f.lineno, "function": f.name} for f in traceback.extract_tb(error.__traceback__)]
        failure = ResearchError("tipster_experiment_failed", 4, error_type=type(error).__name__, frames=frames)
        artifacts.fail(failure)
        raise failure from None
