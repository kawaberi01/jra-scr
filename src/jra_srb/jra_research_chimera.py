"""概要: 時計・相手水準・ラップ適性・信頼度の固定キメラ3構成を学習比較する。
作成日: 2026-10-18
入力: spec226、監査済み年別SQL原文、固定T30市場/HR、保存R1。
出力: 新規研究runのモデル・予測・合否・保存後検証用統計。
実行例: uv run --frozen --extra ml python scripts/run_jra_chimera.py
注意事項: SQL読取のみ。開発未達なら後続評価停止。既定・API・元R1は変更しない。
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from functools import lru_cache
import gc
import hashlib
from itertools import combinations
import json
import math

import joblib
import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax
from threadpoolctl import threadpool_limits

from .jra_research_artifacts import ROOT, RunArtifacts, existing_run
from .jra_research_contracts import ResearchError, digest, timestamp
from .jra_research_features import numeric_market
from .jra_research_history import HistoryConfig
from .jra_research_r1_live import LiveAnnualReader, load_model, read_json, require
from .jra_research_r1_calibration import select_pair
from .jra_research_r1_timing import indexed_rows
from . import jra_research_r1_timing as timing
from .jra_research_resources import check_memory
from . import jra_research_tipster_twenty as native
from . import jra_research_tipster_residual as residual
from . import jra_research_tipster_experiment as prior
from . import jra_research_tipster_smoke as base


REFERENCE = "20261017T163427Z_79bd6188d33b46c19164600dd57840e8"
AUDIT = ROOT / "artifacts/diagnostics/chimera-data-20261017T211746Z"
VARIANTS = ("A", "AB", "ABC")
ALL_VARIANTS = ("M0", "R1", *VARIANTS)
FEATURE_NAMES = ("recent_speed", "best_speed", "speed_trend", "opponent_rating", "recent_relative_form",
                 "distance_fit", "course_fit", "pace_fit", "style_fit", "quality_a", "quality_b")
CONFIG = {"protocol": "spec226-chimera-clock-opponent-v1", "reference_run": REFERENCE,
          "history_from": "2003-01-01", "history_before": "2026-10-18", "train_through": "2025-09-30",
          "train_expected": 65389, "variants": list(VARIANTS), "main_candidate": "ABC", "market_offset": False,
          "market_mix": False, "penalty": .01, "maxiter": 400, "ftol": 1e-10, "gtol": 1e-6,
          "clock_prior_speed": 16.5, "clock_prior_races": 30, "pace_threshold_seconds": .5,
          "rating_update": .2, "a_shrink": 2, "b_shrink": 5, "decay_days": 365,
          "matrix_dtype": "float32", "dot_batch_pairs": 50000, "memory_limit": 2147483648,
          "candidate_count": 1, "diagnostic_controls": 2, "max_adjustment_rounds": 0,
          "default_changed": False, "unseen_test": False}


def clock_seconds(raw):
    """SDKのSE339byte目4桁を分・秒・0.1秒に分け、異常なら拒否する。"""
    require(len(raw) == 4 and raw.isdigit() and int(raw) > 0 and int(raw[1:3]) < 60, "chimera_invalid_clock")
    return int(raw[:1]) * 60 + int(raw[1:3]) + int(raw[3:4]) / 10


@lru_cache(maxsize=16)
def pairs(n):
    """頭数ごとの全馬連組を、馬番順に対応する整数位置で返す。"""
    return np.asarray(list(combinations(range(n), 2)), dtype=np.int32)


def pace_type(value):
    """前半平均−後半平均秒差を事前固定の速い/中間/遅いへ分類する。"""
    return 0 if value < -.5 else 2 if value > .5 else 1


class Horse:
    """馬IDの過去成績だけを、直近3走と条件別の小さな集計で保持する。"""

    __slots__ = ("n", "total", "rating", "last", "forms", "strength", "wins", "top3")

    def __init__(self):
        """履歴のない馬を基礎事前値0から開始する。"""
        self.n, self.total, self.rating = 0, 0.0, 0.0
        self.strength, self.wins, self.top3 = 0.0, 0, 0
        self.last, self.forms = deque(maxlen=3), {}

    def form(self, key):
        """条件付き平均速度差と、その観測件数を返す。"""
        n, total = self.forms.get(key, (0, 0.0))
        overall = self.total / self.n if self.n else 0.0
        return (total / n - overall if n else 0.0), n


class States:
    """過去日だけの時計基準・相手評価・展開分布を一つの時系列で管理する。"""

    def __init__(self):
        """入力履歴のない基準と、固定した分布事前値を用意する。"""
        self.horses, self.clocks, self.paces = {}, {}, {}
        self.pace_all = np.ones(3)

    def density_key(self, race):
        """現レースの出走馬の過去脚質だけから先行密度の区分を作る。"""
        front = 0
        for runner in race["runners"]:
            h = self.horses.get(runner["horse_id"])
            front += bool(h and h.last and h.last[-1][3] is not None and h.last[-1][3] <= .3)
        density = front / len(race["runners"])
        return race["surface"], race["distance"] // 400, 0 if density < .2 else 2 if density >= .4 else 1

    def expected_pace(self, race):
        """対象レースの実ペースを参照せず、過去日までの分布を返す。"""
        counts = self.paces.get(self.density_key(race), np.zeros(3))
        return (counts + 30 * self.pace_all / self.pace_all.sum()) / (counts.sum() + 30)

    def public(self, race):
        """馬の現在結果を一切読まず、9特徴と縮約率・観測品質を作る。

        Args:
            race: 日付・距離・場・芝ダートと出走馬IDを含む競走。
        Returns:
            dict: 馬番順のx/rel/quality。現在の着順・時計・実ラップは使わない。
        Raises:
            ResearchError: 同日履歴の混入、非有限値、形状の不整合。
        """
        probabilities = self.expected_pace(race)
        values, reliability, quality = [], [], []
        for runner in race["runners"]:
            h = self.horses.get(runner["horse_id"], Horse())
            last = list(h.last)
            require(all(v[0] < race["ordinal"] for v in last), "chimera_same_day_history")
            speeds = [v[1] for v in last]
            days = race["ordinal"] - last[-1][0] if last else 365
            a_quality = len(last) / (len(last) + 2) * math.exp(-days / 365)
            distance_fit, dn = h.form(("d", race["surface"], race["distance"] // 400))
            course_fit, cn = h.form(("c", race["surface"], race["course"]))
            pace_forms = [h.form(("p", i)) for i in range(3)]
            pace_fit = sum(probabilities[i] * pace_forms[i][0] for i in range(3))
            pn = sum(probabilities[i] * pace_forms[i][1] for i in range(3))
            corner = last[-1][3] if last and last[-1][3] is not None else .5
            style = (probabilities[0] - probabilities[2]) * (corner - .5)
            sn = sum(v[3] is not None for v in last)
            rel_b = [dn / (dn + 5), cn / (cn + 5), pn / (pn + 5), sn / (sn + 5)]
            x = [float(np.mean(speeds)) if speeds else 0, max(speeds, default=0),
                 speeds[-1] - speeds[0] if len(speeds) > 1 else 0, h.rating,
                 float(np.mean([v[2] for v in last])) if last else 0,
                 distance_fit, course_fit, pace_fit, style]
            values.append(x)
            reliability.append([a_quality] * 5 + rel_b)
            quality.append([a_quality, float(np.mean(rel_b))])
        x = np.clip(np.asarray(values, dtype=np.float64), -5, 5)
        require(x.shape == (len(race["runners"]), 9) and np.isfinite(x).all(), "chimera_public_features")
        return {"x": x, "rel": np.asarray(reliability), "quality": np.asarray(quality)}

    def legacy_features(self, race):
        """元R1が使う8列だけを同じ集計式で作り、不要な48列履歴の重複保持を避ける。"""
        result = np.zeros((len(race["runners"]), 48))
        for i, runner in enumerate(race["runners"]):
            h = self.horses.get(runner["horse_id"], Horse())
            result[i, residual.BASIC] = [(h.strength + 2.5) / (h.n + 5), (h.wins + 1) / (h.n + 12),
                (h.top3 + 3) / (h.n + 12), min(math.log1p(h.n) / 5, 2),
                runner["age"] / 10, runner["weight"] / 60, runner["frame"] / 8, int(h.n == 0)]
        return np.clip(result, -3, 3)

    def update_day(self, races):
        """当日全レースの特徴生成後に、同じ過去基準で計算した結果を一括反映する。

        Args:
            races: (解析済み競走, 馬番ごとの時計秒, 馬場コード)の同日リスト。
        Notes:
            イベントを全て計算してから基準と馬履歴を更新する。同日結果の先取りを防ぐ。
        """
        events, clock_updates, pace_updates = [], [], []
        for race, seconds, going in races:
            generic = (race["surface"], race["distance"])
            detailed = (*generic, race["course"], going)
            gn, gs = self.clocks.get(generic, (0, 0.0))
            base_speed = gs / gn if gn else 16.5
            n, total = self.clocks.get(detailed, (0, 0.0))
            baseline = (total + 30 * base_speed) / (n + 30)
            ratings = [self.horses.get(r["horse_id"], Horse()).rating for r in race["runners"]]
            count = len(ratings)
            for i, runner in enumerate(race["runners"]):
                speed = (race["distance"] / seconds[runner["horse_no"]] - baseline) / 2
                outcome = (count - runner["rank"] + .5) / count
                opponents = (sum(ratings) - ratings[i]) / (count - 1)
                relative = float(np.clip(opponents + .5 * math.log(outcome / (1 - outcome)), -3, 3))
                corner = runner["corner"] / count if runner["corner"] is not None else None
                events.append((runner, race, speed, relative, corner))
                if runner["rank"] == 1:
                    clock_updates.append((generic, detailed, race["distance"] / seconds[runner["horse_no"]]))
            if race["pace"] is not None:
                pace_updates.append((self.density_key(race), pace_type(race["pace"])))
        for runner, race, speed, relative, corner in events:
            h = self.horses.setdefault(runner["horse_id"], Horse())
            h.n, h.total = h.n + 1, h.total + speed
            h.strength += 1 - (runner["rank"] - 1) / (len(race["runners"]) - 1)
            h.wins += int(runner["rank"] == 1)
            h.top3 += int(runner["rank"] <= 3)
            h.rating = float(np.clip(.8 * h.rating + .2 * relative, -3, 3))
            h.last.append((race["ordinal"], speed, relative, corner))
            keys = [("d", race["surface"], race["distance"] // 400), ("c", race["surface"], race["course"])]
            if race["pace"] is not None:
                keys.append(("p", pace_type(race["pace"])))
            for key in keys:
                n, total = h.forms.get(key, (0, 0.0))
                h.forms[key] = (n + 1, total + speed)
        for generic, detailed, speed in clock_updates:
            for key in (generic, detailed):
                n, total = self.clocks.get(key, (0, 0.0))
                self.clocks[key] = (n + 1, total + speed)
        for key, label in pace_updates:
            counts = self.paces.setdefault(key, np.zeros(3))
            counts[label] += 1
            self.pace_all[label] += 1


def pair_features(record, variant):
    """馬別の固定値を全馬連の平均・絶対差へ変換し、競走内で中心化する。"""
    require(variant in VARIANTS, "chimera_unknown_variant")
    x = record["x"][:, :5] if variant == "A" else record["x"]
    if variant == "ABC":
        x = np.column_stack((x * record["rel"], record["quality"]))
    indices = pairs(len(x))
    a, b = x[indices[:, 0]], x[indices[:, 1]]
    result = np.column_stack(((a + b) / 2, np.abs(a - b)))
    result -= result.mean(axis=0)
    require(np.isfinite(result).all(), "chimera_nonfinite_pair_features")
    return result


def objective(beta, x, starts, counts, targets, penalty):
    """競走等重みの条件付き対数損失と解析勾配を小分けの倍精度演算で返す。"""
    batch = CONFIG["dot_batch_pairs"]
    z = np.empty(len(x), dtype=np.float64)
    for begin in range(0, len(x), batch):
        z[begin:begin + batch] = x[begin:begin + batch].astype(np.float64) @ beta
    maxima = np.maximum.reduceat(z, starts)
    e = np.exp(z - np.repeat(maxima, counts))
    sums = np.add.reduceat(e, starts)
    loss = float(np.mean(maxima + np.log(sums) - z[targets]))
    e /= np.repeat(sums, counts)
    e[targets] -= 1
    gradient = np.zeros(len(beta))
    for begin in range(0, len(x), batch):
        gradient += x[begin:begin + batch].astype(np.float64).T @ e[begin:begin + batch]
    return loss + penalty * float(beta @ beta) / 2, gradient / len(counts) + penalty * beta


def pack_training(records):
    """馬別値と全組の整数位置だけを保持し、巨大なペア特徴行列を作らない。"""
    require(records and all(r["race_date"] <= CONFIG["train_through"] for r in records), "chimera_training_date")
    counts = np.asarray([len(pairs(len(r["x"]))) for r in records], dtype=np.int64)
    starts = np.cumsum(np.r_[0, counts[:-1]])
    left, right = np.empty(int(counts.sum()), dtype=np.int32), np.empty(int(counts.sum()), dtype=np.int32)
    targets = np.empty(len(records), dtype=np.int64)
    horse_offset = 0
    for i, record in enumerate(records):
        positions = pairs(len(record["x"])) + horse_offset
        left[starts[i]:starts[i] + counts[i]], right[starts[i]:starts[i] + counts[i]] = positions.T
        targets[i] = starts[i] + record["winner"]
        horse_offset += len(record["x"])
    return {"x": np.concatenate([r["x"] for r in records]), "rel": np.concatenate([r["rel"] for r in records]),
            "quality": np.concatenate([r["quality"] for r in records]), "left": left, "right": right,
            "starts": starts, "counts": counts, "targets": targets,
            "group": np.repeat(np.arange(len(records), dtype=np.int32), counts),
            "horse_counts": np.asarray([len(r["x"]) for r in records]),
            "train_races": len(records), "trained_through": max(r["race_date"] for r in records)}


def centers_for(data, horse_x):
    """競走別の平均特徴だけを保持し、従来と同じ中心化を再現する。"""
    result = np.empty((data["train_races"], horse_x.shape[1] * 2))
    offset = 0
    for i, n in enumerate(data["horse_counts"]):
        local = horse_x[offset:offset + n]
        indices = pairs(int(n))
        a, b = local[indices[:, 0]], local[indices[:, 1]]
        result[i] = np.column_stack(((a + b) / 2, np.abs(a - b))).mean(axis=0)
        offset += n
    return result


def pair_block(data, horse_x, centers, begin, end, scale):
    """最大5万組だけを中心化・float32正規化し、演算用の倍精度で返す。"""
    a, b = horse_x[data["left"][begin:end]], horse_x[data["right"][begin:end]]
    values = np.column_stack(((a + b) / 2, np.abs(a - b))) - centers[data["group"][begin:end]]
    block = values.astype(np.float32)
    if scale is not None:
        block /= scale.astype(np.float32)
    return block.astype(np.float64)


def packed_objective(beta, data, horse_x, centers, scale):
    """全量保持版と同じ尤度・勾配を、位置配列と小さい特徴ブロックで計算する。"""
    size, batch = len(data["left"]), CONFIG["dot_batch_pairs"]
    z = np.empty(size)
    for begin in range(0, size, batch):
        z[begin:begin + batch] = pair_block(data, horse_x, centers, begin, begin + batch, scale) @ beta
    maxima = np.maximum.reduceat(z, data["starts"])
    e = np.exp(z - maxima[data["group"]])
    sums = np.add.reduceat(e, data["starts"])
    loss = float(np.mean(maxima + np.log(sums) - z[data["targets"]]))
    e /= sums[data["group"]]
    e[data["targets"]] -= 1
    gradient = np.zeros(len(beta))
    for begin in range(0, size, batch):
        gradient += pair_block(data, horse_x, centers, begin, begin + batch, scale).T @ e[begin:begin + batch]
    return loss + CONFIG["penalty"] * float(beta @ beta) / 2, gradient / data["train_races"] + CONFIG["penalty"] * beta


def fit(data, variant):
    """学習期間だけの全競走から一つの固定構成をブロック方式で最適化する。"""
    if isinstance(data, list):
        data = pack_training(data)
    horse_x = data["x"][:, :5] if variant == "A" else data["x"]
    if variant == "ABC":
        horse_x = np.column_stack((horse_x * data["rel"], data["quality"]))
    centers = centers_for(data, horse_x)
    size, dimension = len(data["left"]), centers.shape[1]
    squares = np.zeros(dimension)
    for begin in range(0, size, CONFIG["dot_batch_pairs"]):
        block = pair_block(data, horse_x, centers, begin, begin + CONFIG["dot_batch_pairs"], None)
        squares += np.einsum("ij,ij->j", block, block)
    scale = np.maximum(np.sqrt(squares / size), 1e-5)
    check_memory(CONFIG["memory_limit"])
    print(json.dumps({"stage": "fit", "variant": variant, "races": data["train_races"], "pairs": size, "columns": dimension}), flush=True)
    result = minimize(packed_objective, np.zeros(dimension), args=(data, horse_x, centers, scale),
                      jac=True, method="L-BFGS-B", options={"maxiter": CONFIG["maxiter"], "ftol": CONFIG["ftol"], "gtol": CONFIG["gtol"]})
    require(bool(result.success), "chimera_optimizer_failed_" + variant)
    artifact = {"variant": variant, "scale": scale, "coef": result.x, "train_races": data["train_races"],
                "train_pairs": size, "trained_through": data["trained_through"],
                "optimizer": {"success": True, "iterations": int(result.nit), "objective": float(result.fun)}}
    gc.collect()
    return artifact


def predict(model, record):
    """市場・現在結果を参照せず、全馬連の条件付き確率を返す。"""
    logits = (pair_features(record, model["variant"]) / model["scale"]) @ model["coef"]
    return softmax(logits)


def prepare(artifacts, reference):
    """年別原文を一巡し、当日更新前の新旧特徴と学習ラベルを構築する。"""
    config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
    audit, verified = read_json(AUDIT / "audit.json"), read_json(AUDIT / "verification.json")
    require(audit["status"] == "complete" and verified["status"] == "passed", "chimera_missing_data_audit")
    scope = {r["race_key"] for r in reference["race_metrics"] if r["period"] != "calibration"}
    old = {r["race_key"]: r["period"] for r in reference["race_metrics"]}
    states, train, targets, years = States(), [], {}, {}
    with LiveAnnualReader(config) as reader:
        artifacts.write_json("preflight.json", reader.preflight())
        for year in range(2003, 2027):
            raw, report = reader.year_before(year, CONFIG["history_before"])
            require(report["input_digest"] == audit["annual"][str(year)]["source_audit"]["input_digest"]
                    == reference["coverage"]["years"][str(year)]["input_digest"], "chimera_input_digest_changed")
            daily, adopted = defaultdict(list), 0
            for key, source in sorted(raw.items()):
                race, reason = native.parse_race(key, source)
                if reason is None:
                    daily[race["day"]].append(race)
            for day, races in sorted(daily.items()):
                updates = []
                for race in races:
                    source = raw[race["key"]]
                    seconds = {no: clock_seconds(row[2][338:342]) for no, row in source["SE"].items()}
                    ra = source["RA"][2]
                    going = native.number(ra[888:889] if race["surface"] == 0 else ra[889:890])
                    require(going in (1, 2, 3, 4), "chimera_invalid_going")
                    updates.append((race, seconds, going))
                    adopted += 1
                    if day <= CONFIG["train_through"] or race["key"] in scope:
                        public = states.public(race)
                        winners = {i for i, r in enumerate(race["runners"]) if r["rank"] <= 2}
                        winner = next(i for i, pair in enumerate(pairs(len(race["runners"]))) if set(pair) == winners)
                        record = {**public, "race_key": race["key"], "race_date": day, "winner": winner}
                        if day <= CONFIG["train_through"]:
                            train.append(record)
                        else:
                            record.update(race=race, legacy_x=states.legacy_features(race), period=old[race["key"]])
                            targets[race["key"]] = record
                states.update_day(updates)
            require(adopted == audit["annual"][str(year)]["counts"]["races"], "chimera_audit_cohort_changed")
            years[str(year)] = {"input_digest": report["input_digest"], "races": adopted}
            artifacts.write_json("coverage.json", {"stage": "features", "years": years, "train_races": len(train), "targets": len(targets)})
            print(json.dumps({"stage": "features", "year": year, "train": len(train), "targets": len(targets)}), flush=True)
            del raw, daily
            gc.collect()
            check_memory(CONFIG["memory_limit"])
    require(len(train) == CONFIG["train_expected"] and set(targets) == scope, "chimera_feature_scope")
    return train, targets, years


def gate_rows(rows):
    """共有ゲートの比較名へ変換する。同じT30のABC/R1/市場であり時点は変更しない。"""
    aliases = {"M30": "M0", "M10": "M0", "R30": "R1", "R10": "ABC"}
    return [{"race_date": r["race_date"], **{k: {alias: r[k][name] for alias, name in aliases.items()}
             for k in ("loss", "brier", "stake", "payout")}} for r in rows]


def accuracy_gate(rows, expected, stage):
    """spec225の改善率・区間・標本・Brierを既存の固定ゲートで判定する。"""
    result = timing.accuracy_gate(gate_rows(rows), expected, stage)
    checks = {k.replace("r30", "r1").replace("m10", "market"): v for k, v in result["checks"].items()}
    return {"stage": stage, "passed": all(checks.values()), "checks": checks, "races": result["races"],
            "expected_races": expected, "days": result["days"], "vs_r1": result["vs_r30"],
            "vs_market": result["vs_m10"], "brier": {"ABC": result["brier"]["R10"], "R1": result["brier"]["R30"],
            "M0": result["brier"]["M10"]}, "all_variants_horizon": "T30"}


def summaries(rows, tickets):
    """各構成の予測損失と同一政策の購入会計・集中度を別々に集計する。"""
    result = {}
    for name in ALL_VARIANTS:
        chosen = [t for t in tickets if t["variant"] == name]
        accounting = prior.summary([{**t["ticket"], "race_date": t["race_date"]} for t in chosen])
        require(accounting["stake_yen"] == sum(r["stake"][name] for r in rows)
                and accounting["payout_yen"] == sum(r["payout"][name] for r in rows), "chimera_summary_accounting")
        result[name] = {"logloss": float(np.mean([r["loss"][name] for r in rows])) if rows else None,
            "mean_pair_brier": float(np.mean([r["brier"][name] for r in rows])) if rows else None,
            **accounting, "hits": sum(t["target"] for t in chosen), "expected_hits": sum(t["probability"] for t in chosen)}
    return result


def purchase_gate(rows, tickets):
    """ABCの購入採用を精度と分離し、共有の固定標本・ROI・利益差条件で判定する。"""
    aliases = {"M30": "M0", "M10": "M0", "R30": "R1", "R10": "ABC"}
    converted = [{**t, "variant": alias} for alias, name in aliases.items() for t in tickets if t["variant"] == name]
    result = timing.purchase_gate(gate_rows(rows), converted)
    return {k: v for k, v in result.items() if k != "summaries"} | {"summaries": summaries(rows, tickets)}


def evaluate_phase(keys, targets, reference, models, reloaded, baseline, reader):
    """指定期間のT30/HRだけを読み、基準再現と保存後推論を行う。"""
    old = {r["race_key"]: r for r in reference["race_metrics"]}
    rows, tickets, excluded, reload_checks = [], [], [], 0
    for begin in range(0, len(keys), 100):
        batch = keys[begin:begin + 100]
        markets = indexed_rows(reader, batch, "market.odds_asof_index", base.FIELDS["market.odds_asof_index"],
                               "AND t.market=N'quinella' AND t.horizon=N'T30'")
        payouts = indexed_rows(reader, batch, "history.payouts", base.FIELDS["history.payouts"],
                               "AND t.market=N'quinella' AND t.slot_status=N'published'")
        by_market, by_payout = defaultdict(list), defaultdict(list)
        for r in markets:
            by_market[r["race_key"]].append(r)
        for r in payouts:
            by_payout[r["race_key"]].append(r)
        for key in batch:
            record = targets[key]
            race = record["race"]
            pair_keys = list(combinations([r["horse_no"] for r in race["runners"]], 2))
            source = by_market[key]
            try:
                require(len(source) == 1 and source[0]["selection_status"] == "selected"
                        and source[0]["content_sha256"] and source[0]["parser_version"] == "jv-o1o2-v2"
                        and timestamp(source[0]["announced_at"]) <= timestamp(source[0]["cutoff_at"]), "chimera_invalid_market")
                prices_map = numeric_market(source[0], "quinella")
                require(set(prices_map) == set(pair_keys), "chimera_market_roster")
            except ResearchError as error:
                excluded.append({"race_key": key, "reason": error.reason})
                continue
            prices = np.asarray([prices_map[p] for p in pair_keys])
            market = 1 / prices
            market /= market.sum()
            winner = record["winner"]
            winner_pair = pair_keys[winner]
            hr = by_payout[key]
            require(len(hr) == 1 and hr[0]["hr_sha256"] and hr[0]["selection_raw"] == "".join(winner_pair)
                    and hr[0]["payout_yen"] > 0 and int(hr[0]["payout_raw"]) == hr[0]["payout_yen"], "chimera_hr_contract")
            probabilities = {"M0": market, "R1": residual.predict(baseline, {"x": record["legacy_x"], "market": market})}
            for name, model in models.items():
                p = predict(model, record)
                require(np.array_equal(p, predict(reloaded[name], record)), "chimera_model_reload")
                require(np.array_equal(p, predict(model, {"x": record["x"], "rel": record["rel"], "quality": record["quality"],
                        "winner": -1, "market": np.zeros(len(p)), "payout": -1})), "chimera_prediction_result_dependency")
                z = (pair_features(record, name) / model["scale"]) @ model["coef"]
                independent = np.exp(z - max(z))
                independent /= independent.sum()
                require(np.allclose(p, independent, rtol=1e-12, atol=1e-14), "chimera_independent_softmax")
                probabilities[name] = p
                reload_checks += 1
            row = {"race_key": key, "race_date": record["race_date"], "period": record["period"], "pair_count": len(pair_keys),
                   "loss": {}, "brier": {}, "stake": {}, "payout": {}, "moments": {}}
            for name, p in probabilities.items():
                require(np.isfinite(p).all() and np.isclose(p.sum(), 1) and np.all(p > 0), "chimera_invalid_probability")
                row["loss"][name] = float(-np.log(p[winner]))
                row["brier"][name] = float((p @ p - 2 * p[winner] + 1) / len(p))
                row["moments"][name] = {"winning_probability": float(p[winner]), "squared_sum": float(p @ p),
                                        "sum": float(p.sum()), "minimum": float(p.min())}
                row["stake"][name] = row["payout"][name] = 0
                index = select_pair(p, prices, np.ones(len(p)))
                if index is not None:
                    actual = int(hr[0]["payout_yen"]) * 6 if index == winner else 0
                    ticket = {"kind": "quinella", "stake_yen": 600, "payout_yen": actual, "quoted_odds": float(prices[index]),
                              "expected_multiplier": float(p[index] * prices[index])}
                    tickets.append({"race_key": key, "race_date": record["race_date"], "venue": str(race["course"]),
                                    "variant": name, "split": record["period"], "horses": list(pair_keys[index]),
                                    "probability": float(p[index]), "target": int(index == winner), "ticket": ticket})
                    row["stake"][name], row["payout"][name] = 600, actual
            require(abs(row["loss"]["R1"] - old[key]["loss"]["C0"]) < 1e-12
                    and abs(row["loss"]["M0"] - old[key]["loss"]["M0"]) < 1e-12
                    and row["stake"]["R1"] == old[key]["stake"]["C0_P0"]
                    and row["payout"]["R1"] == old[key]["payout"]["C0_P0"], "chimera_reference_reproduction")
            rows.append(row)
    return rows, tickets, excluded, reload_checks


def execute():
    """固定3構成を学習し、本体の開発未達なら後続評価を実行せず完了記録を残す。"""
    base.install_input_guard()
    reference_path = existing_run(REFERENCE)
    reference, manifest = read_json(reference_path / "metrics.json"), read_json(reference_path / "manifest.json")
    require(manifest["status"] == "complete" and digest(reference) == manifest["metrics_sha256"], "chimera_reference_integrity")
    baseline, provenance = load_model()
    artifacts = RunArtifacts({**CONFIG, "base_model": provenance, "data_audit": str(AUDIT.relative_to(ROOT))}, "chimera-fixed-abc")
    for name in ("scripts/run_jra_chimera.py", "scripts/verify_jra_chimera.py"):
        artifacts.manifest["code_sha256"][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    artifacts.manifest["spec_sha256"] = hashlib.sha256((ROOT / ".workstate/jra-srb/sqlserver-model-data-audit/spec/226-キメラ初版の固定実装契約.md").read_bytes()).hexdigest()
    artifacts.write_json("manifest.json", artifacts.manifest)
    print(json.dumps({"stage": "starting", "run_id": artifacts.run_id}), flush=True)
    try:
        with threadpool_limits(limits=1):
            train, targets, years = prepare(artifacts, reference)
            packed = pack_training(train)
            del train
            gc.collect()
            models = {}
            for name in VARIANTS:
                models[name] = fit(packed, name)
                artifacts.write_json("model_history.json", {k: {i: m[i] for i in ("train_races", "train_pairs", "trained_through", "optimizer")} for k, m in models.items()})
                joblib.dump({"models": models, "config": CONFIG, "feature_names": FEATURE_NAMES}, artifacts.path / "models.joblib")
                print(json.dumps({"stage": "fitted", "variant": name, "optimizer": models[name]["optimizer"]}), flush=True)
            joblib.dump({"models": models, "config": CONFIG, "feature_names": FEATURE_NAMES}, artifacts.path / "models.joblib")
            reloaded = joblib.load(artifacts.path / "models.joblib")["models"]
            del packed
            gc.collect()
            old = reference["race_metrics"]
            dev_keys = sorted(r["race_key"] for r in old if r["period"] == "evaluation_2025")
            eval_keys = sorted(r["race_key"] for r in old if r["period"] in ("evaluation_early", "evaluation_late", "later_2026"))
            config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
            evaluation, eval_tickets, eval_excluded, eval_reload = [], [], [], 0
            with prior.ExperimentMarketReader(config) as reader:
                reader.selected(["2025-11-01"])
                development, dev_tickets, excluded, reload_checks = evaluate_phase(dev_keys, targets, reference, models, reloaded, baseline, reader)
                screen = accuracy_gate(development, len(dev_keys), "development")
                artifacts.write_json("metrics.json", {"stage": "development_decision_frozen", "development_gate": screen})
                print(json.dumps({"stage": "development_decision", "passed": screen["passed"], "checks": screen["checks"]}), flush=True)
                if screen["passed"]:
                    evaluation, eval_tickets, eval_excluded, eval_reload = evaluate_phase(eval_keys, targets, reference, models, reloaded, baseline, reader)
            final = accuracy_gate(evaluation, len(eval_keys), "evaluation") if screen["passed"] else None
            if final is not None:
                for period in ("evaluation_early", "evaluation_late", "later_2026"):
                    subset = [r for r in evaluation if r["period"] == period]
                    final["checks"]["non_worse_" + period] = bool(subset) and bool(np.mean([r["loss"]["ABC"] for r in subset]) <= np.mean([r["loss"]["R1"] for r in subset]))
                final["passed"] = all(final["checks"].values())
            supported = screen["passed"] and final is not None and final["passed"]
            tickets = dev_tickets + eval_tickets
            prediction_hash = artifacts.write_predictions(tickets)
            decision = {"accuracy_candidate_supported": bool(supported), "research_status": "prospective_validation_only" if supported else "closed_failed_performance_gate",
                        "reason": "retrospective_gate_passed" if supported else "development_gate_failed" if not screen["passed"] else "evaluation_gate_failed",
                        "stop_further_tuning": True, "next_variants_allowed": 0, "controls_not_reselected": True}
            metrics = {"status": "passed", "stage": "chimera_fixed_abc", "development_gate": screen, "evaluation_gate": final,
                       "decision": decision, "development_results": summaries(development, dev_tickets),
                       "evaluation_results": purchase_gate(evaluation, eval_tickets) if evaluation else None,
                       "race_metrics": development + evaluation, "model_fits": 3, "main_candidates": 1,
                       "reload_score_checks": reload_checks + eval_reload, "base_model": provenance,
                       "evaluation_executed": bool(screen["passed"]), "default_changed": False, "unseen_test": False}
            coverage = {"years": years, "train_races": CONFIG["train_expected"], "target_features": len(targets),
                        "development_expected": len(dev_keys), "development_adopted": len(development),
                        "evaluation_expected": len(eval_keys), "evaluation_adopted": len(evaluation),
                        "evaluation_market_not_read_when_screen_failed": not screen["passed"],
                        "excluded": excluded + eval_excluded, "sqlite_used": False}
            model_hash = hashlib.sha256((artifacts.path / "models.joblib").read_bytes()).hexdigest()
            artifacts.write_json("coverage.json", coverage)
            artifacts.write_json("metrics.json", metrics)
            artifacts.finish(overall_complete=False, metrics_sha256=digest(metrics), predictions_sha256=prediction_hash,
                             model_sha256=model_hash, research_status=decision["research_status"], performance_gate_passed=bool(supported))
            return {"run_id": artifacts.run_id, "development_gate": screen, "evaluation_gate": final,
                    "decision": decision, "development_results": metrics["development_results"]}
    except Exception as error:
        safe = error if isinstance(error, ResearchError) else ResearchError("chimera_execution_failed", 4, error_type=type(error).__name__)
        artifacts.fail(safe)
        safe.details["run_id"] = artifacts.run_id
        raise safe from None
