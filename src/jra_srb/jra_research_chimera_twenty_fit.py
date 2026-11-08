"""概要: 固定20仮説を前日履歴から構築し、時系列で学習・選抜・性能測定する。
作成日: 2026-10-18
入力: spec230〜232、監査済みSQL履歴、成功済み入力事前判定、T30/HR。
出力: 新規研究runのモデル、仮想購入、競走別性能、選抜/停止判定。
実行例: uv run --frozen --extra ml python scripts/run_jra_chimera_twenty_fit.py
注意事項: 読取のみ。候補追加・重み探索・既定変更・実購入は行わない。
"""

from __future__ import annotations

from collections import defaultdict, deque
import gc
import hashlib
from itertools import combinations
import json
import math

import joblib
import numpy as np
from scipy.optimize import minimize
from scipy.special import softmax, logsumexp
from threadpoolctl import threadpool_limits

from . import jra_research_chimera as old
from . import jra_research_chimera_twenty as plan
from .jra_research_artifacts import ROOT, RunArtifacts, existing_run
from .jra_research_contracts import ResearchError, digest
from .jra_research_history import HistoryConfig
from .jra_research_r1_live import LiveAnnualReader, read_json, require, load_model
from .jra_research_resources import check_memory


PREFLIGHT = "20261018T044558Z_704403f367d8439694a7853cae3408fa"
CONTROL_RUN = "20261018T051310Z_63dae83690c74e219555968c42a2b97b"
CONTROL_SHA = "82f7063bbf80f1b460348482b14b04b4b469435e9a1d28486693cf47b58b2cdd"
REUSED_PRIMARY = ("N0", *(f"H{i:02d}" for i in range(1, 8)))
CONFIG = {**plan.CONFIG, "protocol": "spec232-chimera-twenty-fixed-v1", "preflight_run": PREFLIGHT,
          "penalty": .01, "maxiter": 400, "ftol": 1e-10, "gtol": 1e-6,
          "memory_limit": 2147483648, "batch_pairs": 50000, "bootstrap_replicates": 2000,
          "seed": 232, "train_ends": ["2024-12-31", "2025-06-30", "2025-09-30"],
          "market_weight": .9, "case_count": 20, "max_adjustment_rounds": 0,
          "reused_primary_control_run": CONTROL_RUN, "reused_primary_control_sha256": CONTROL_SHA,
          "reused_primary_models": list(REUSED_PRIMARY)}


class ExtraHorse:
    """追加仮説だけに必要な直近3走と、別ratingを小さく保持する。"""

    __slots__ = ("last", "rating")

    def __init__(self):
        """未観測の馬を空の時計履歴と中立ratingから開始する。"""
        self.last, self.rating = deque(maxlen=3), 0.0


class TwentyStates(old.States):
    """初版履歴を再利用し、仮説差分の過去情報だけを別途管理する。"""

    def __init__(self):
        """全出走平均・180日時計・分散・初観測コホートの集計を用意する。"""
        super().__init__()
        self.extra, self.field_clocks, self.rolling, self.moments, self.cohort = {}, {}, {}, {}, {}

    def rolling_mean(self, key, ordinal):
        """指定日の前180日だけの勝馬時計平均と件数を返す。"""
        values = self.rolling.get(key)
        if not values:
            return 0, 0.0
        while values and values[0][0] < ordinal - 180:
            values.popleft()
        return len(values), sum(v[1] for v in values)

    def public(self, race):
        """現結果を読まず、初版9列と固定27列の仮説差分を返す。

        Args:
            race: 日付・条件と出走馬の公開属性を含む競走。
        Returns:
            dict: 馬番順のx/extra。現在の着順・時計・実ペースを参照しない。
        Raises:
            ResearchError: 同日履歴がすでに反映されている場合。
        """
        public = super().public(race)
        front = sum(bool((h := self.horses.get(r["horse_id"])) and h.last
                         and h.last[-1][3] is not None and h.last[-1][3] <= .3) for r in race["runners"])
        density, values = front / len(race["runners"]), []
        for i, runner in enumerate(race["runners"]):
            horse = self.horses.get(runner["horse_id"])
            extra = self.extra.get(runner["horse_id"])
            history = list(extra.last) if extra else []
            base_last = list(horse.last) if horse else []
            require(all(int(v[0]) < race["ordinal"] for v in history), "twenty_same_day_history")
            out = np.zeros(27)
            for variant in range(3):
                speeds = [float(v[1 + variant]) for v in history]
                out[variant * 3:variant * 3 + 3] = [np.mean(speeds) if speeds else 0,
                    max(speeds, default=0), speeds[-1] - speeds[0] if len(speeds) > 1 else 0]
            speeds = [v[1] for v in base_last]
            days = race["ordinal"] - base_last[-1][0] if base_last else 365
            out[9] = np.median(speeds) if speeds else 0
            out[10] = np.mean([v[4] for v in history]) if history else 0
            out[11] = extra.rating if extra else 0
            out[12] = np.mean([v[5] for v in history]) if history else 0
            if horse:
                weighted_n = weighted_sum = 0.0
                for key, (count, total) in horse.forms.items():
                    if key[0] == "exact_d" and key[1] == race["surface"]:
                        weight = math.exp(-((key[2] - race["distance"]) / 400) ** 2)
                        weighted_n += weight * count
                        weighted_sum += weight * total
                out[13] = weighted_sum / weighted_n - horse.total / horse.n if weighted_n > 0 else 0
                course, count = horse.form(("c", race["surface"], race["course"]))
                out[14] = course * count / (count + 5)
            closing = [v[6] for v in history if np.isfinite(v[6])]
            out[15] = np.mean(closing) if closing else 0
            corner = base_last[-1][3] if base_last and base_last[-1][3] is not None else .5
            out[16:18] = [(density - .3) * (corner - .5), density]
            out[18] = np.mean([v[7] for v in history]) if history else 0
            out[19] = (speeds[-1] - max(speeds)) * math.log1p(days) / math.log(181) if speeds else 0
            out[20:23] = [math.log1p(horse.n) / 5 if horse else 0, min(days / 365, 2), int(not base_last)]
            count, total = self.cohort.get((runner["age"], race["surface"]), (0, 0.0))
            out[23:27] = [total / (count + 20), corner, race["surface"], runner["age"] / 10]
            values.append(np.clip(out, -5, 5))
        return {"x": public["x"].astype(np.float32), "extra": np.asarray(values, dtype=np.float32)}

    def update_day(self, races):
        """当日全結果を同じ過去基準で計算し、初版と追加履歴へ最後に反映する。

        Args:
            races: 同日の(解析競走, 馬番別の時計秒, 馬場コード)の配列。
        Notes:
            全イベントを更新前に計算し、馬履歴・時計基準を最後に更新する。
            元Statesの履歴も再利用し、現在の結果を当日の予測へ先取りしない。
        """
        events, clock_updates, moment_updates, cohorts, exact = [], [], [], [], []
        for race, seconds, going in races:
            generic = (race["surface"], race["distance"])
            detailed = (*generic, race["course"], going)
            gn, gs = self.field_clocks.get(generic, (0, 0.0))
            dn, ds = self.field_clocks.get(detailed, (0, 0.0))
            field_baseline = (ds + 30 * (gs / gn if gn else 16.5)) / (dn + 30)
            rn, rs = self.rolling_mean(generic, race["ordinal"])
            rdn, rds = self.rolling_mean(detailed, race["ordinal"])
            rolling_base = (rds + 30 * (rs / rn if rn else 16.5)) / (rdn + 30)
            wn, ws = self.clocks.get(generic, (0, 0.0))
            cn, cs = self.clocks.get(detailed, (0, 0.0))
            original_base = (cs + 30 * (ws / wn if wn else 16.5)) / (cn + 30)
            mn, total, squares = self.moments.get(generic, (0, 0.0, 0.0))
            mean = (total + 30 * 16.5) / (mn + 30)
            deviation = max(.3, math.sqrt(max(0, (squares + 30 * (4 + 16.5 ** 2)) / (mn + 30) - mean ** 2)))
            ratings = [self.extra.get(r["horse_id"], ExtraHorse()).rating for r in race["runners"]]
            n = len(ratings)
            winner_seconds = min(seconds.values())
            for i, runner in enumerate(race["runners"]):
                speed = race["distance"] / seconds[runner["horse_no"]]
                base_speed = (speed - original_base) / 2
                outcome = (n - runner["rank"] + .5) / n
                relative = float(np.clip((sum(ratings) - ratings[i]) / (n - 1)
                                        + .5 * math.log(outcome / (1 - outcome)), -3, 3))
                corner = runner["corner"] / n if runner["corner"] is not None else .5
                closing = race.get("closing_total")
                closing = (closing - runner["closing"]) / 3 if closing is not None and runner["closing"] is not None else np.nan
                burden = max(0, -(race["pace"] or 0)) * (1 - corner) * (base_speed - (1 - (runner["rank"] - 1) / (n - 1)))
                h = self.horses.get(runner["horse_id"])
                count = h.n if h else 0
                event = np.asarray([race["ordinal"], (speed - field_baseline) / 2, (speed - original_base) / deviation,
                                    (speed - rolling_base) / 2, -10 * (1 - winner_seconds / seconds[runner["horse_no"]]),
                                    relative, closing, burden], dtype=np.float64)
                events.append((runner["horse_id"], event, count))
                exact.append((runner["horse_id"], ("exact_d", race["surface"], race["distance"]), base_speed))
                if count == 0:
                    cohorts.append(((runner["age"], race["surface"]), base_speed))
                if runner["rank"] == 1:
                    moment_updates.append((generic, detailed, race["ordinal"], speed))
            clock_updates.append((generic, detailed, float(np.mean([race["distance"] / v for v in seconds.values()]))))
        super().update_day(races)
        for horse_id, event, count in events:
            h = self.extra.setdefault(horse_id, ExtraHorse())
            rate = .2 * count / (count + 5)
            h.rating = float(np.clip((1 - rate) * h.rating + rate * event[5], -3, 3))
            h.last.append(event)
        for horse_id, key, speed in exact:
            h = self.horses[horse_id]
            count, total = h.forms.get(key, (0, 0.0))
            h.forms[key] = (count + 1, total + speed)
        for key, speed in cohorts:
            count, total = self.cohort.get(key, (0, 0.0))
            self.cohort[key] = count + 1, total + speed
        for generic, detailed, speed in clock_updates:
            for key in (generic, detailed):
                count, total = self.field_clocks.get(key, (0, 0.0))
                self.field_clocks[key] = count + 1, total + speed
        for generic, detailed, ordinal, speed in moment_updates:
            count, total, squares = self.moments.get(generic, (0, 0.0, 0.0))
            self.moments[generic] = count + 1, total + speed, squares + speed ** 2
            for key in (generic, detailed):
                self.rolling.setdefault(key, deque()).append((ordinal, speed))


def horse_features(x, extra, case, knots=None):
    """固定ケースの差分だけをN0へ適用し、有限な馬別行列を返す。"""
    result = x.copy()
    if case in ("H01", "H02", "H03"):
        start = (int(case[1:]) - 1) * 3
        result[:, :3] = extra[:, start:start + 3]
    elif case == "H04":
        result[:, 0] = extra[:, 9]
    elif case == "H05":
        result = np.column_stack((result, extra[:, 10]))
    elif case == "H06":
        result[:, 3:5] = extra[:, 11:13]
    elif case == "H07":
        require(knots is not None, "twenty_missing_train_knots")
        result = np.column_stack((result, np.maximum(0, x[:, :1] - knots)))
    elif case == "H08":
        result = np.column_stack((result, x[:, :5] * extra[:, 25:26]))
    elif case in ("H09", "H10"):
        result[:, 5 if case == "H09" else 6] = extra[:, 13 if case == "H09" else 14]
    elif case == "H11":
        result = np.column_stack((result, extra[:, 15]))
    elif case == "H12":
        result[:, 8] = extra[:, 16]
        result = np.column_stack((result, x[:, 0] * extra[:, 17]))
    elif case in ("H13", "H14"):
        result = np.column_stack((result, extra[:, 18 if case == "H13" else 19]))
    elif case == "H15":
        result = np.column_stack((result, extra[:, 20:23]))
    elif case == "H16":
        mask = extra[:, 22] == 1
        result[mask, :2] = extra[mask, 23:24]
    require(case in ("N0", "H19", "H20") or case in plan.CASES, "twenty_unknown_case")
    require(np.isfinite(result).all(), "twenty_nonfinite_features")
    np.clip(result, -5, 5, out=result)
    return result.astype(np.float32, copy=False)


def local_pairs(horse_x, extra, case):
    """一競走の全ペア特徴を作り、H17の積項も競走内で中心化する。"""
    positions = old.pairs(len(horse_x))
    a, b = horse_x[positions[:, 0]].astype(float), horse_x[positions[:, 1]].astype(float)
    result = np.column_stack(((a + b) / 2, np.abs(a - b)))
    if case == "H17":
        ca, cb = extra[positions[:, 0], 24], extra[positions[:, 1], 24]
        result = np.column_stack((result, a[:, 0] * b[:, 0], (a[:, 0] * cb + b[:, 0] * ca) / 2))
    return result - result.mean(axis=0)


def prepare(artifacts):
    """固定24年度を一巡し、前日時点の馬別値と全時系列のラベルだけを保持する。

    Args:
        artifacts: 来歴・年別進捗を保存する一意run。
    Returns:
        tuple: 競走別の共有配列viewと、監査に照合した年別件数/digest。
    Raises:
        ResearchError: 入力digest、対象件数、時計/馬場、メモリの契約違反。
    Notes:
        SQLは固定版のSELECTだけ。生原文・全特徴をファイルへ複製しない。
    """
    audit = read_json(old.AUDIT / "audit.json")
    reference = read_json(existing_run(old.REFERENCE) / "metrics.json")
    reference_keys = {r["race_key"] for r in reference["race_metrics"] if r["period"] != "calibration"}
    states, records, years = TwentyStates(), [], {}
    # 監査済み全出走数を上限に一度だけ確保し、競走行列はこの領域のviewにする。
    capacity = sum(v["counts"]["runners"] for v in audit["annual"].values())
    flat_x, flat_extra = np.empty((capacity, 9), np.float32), np.empty((capacity, 27), np.float32)
    horse_offset = 0
    with LiveAnnualReader(HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")) as reader:
        artifacts.write_json("preflight.json", {"input_preflight_run": PREFLIGHT, "annual": reader.preflight()})
        for year in range(2003, 2027):
            raw, report = reader.year_before(year, CONFIG["history_before"])
            require(report["input_digest"] == audit["annual"][str(year)]["source_audit"]["input_digest"], "twenty_annual_changed")
            daily, normal = defaultdict(list), 0
            for key, source in sorted(raw.items()):
                race, reason = old.native.parse_race(key, source)
                if reason is None:
                    daily[race["day"]].append(race)
            for day, races in sorted(daily.items()):
                updates = []
                for race in races:
                    source = raw[race["key"]]
                    seconds = {no: old.clock_seconds(row[2][338:342]) for no, row in source["SE"].items()}
                    ra = source["RA"][2]
                    going = old.native.number(ra[888:889] if race["surface"] == 0 else ra[889:890])
                    require(going in (1, 2, 3, 4), "twenty_invalid_going")
                    laps = [old.native.number(ra[890 + i * 3:893 + i * 3]) / 10 for i in range(25)]
                    laps = [v for v in laps if v > 0]
                    race["closing_total"] = sum(laps[-3:]) if race["pace"] is not None else None
                    updates.append((race, seconds, going))
                    if day <= "2025-09-30" or race["key"] in reference_keys:
                        public = states.public(race)
                        count = len(public["x"])
                        require(horse_offset + count <= capacity, "twenty_horse_capacity")
                        flat_x[horse_offset:horse_offset + count] = public["x"]
                        flat_extra[horse_offset:horse_offset + count] = public["extra"]
                        winners = {i for i, r in enumerate(race["runners"]) if r["rank"] <= 2}
                        winner = next(i for i, pair in enumerate(old.pairs(len(race["runners"]))) if set(pair) == winners)
                        record = {"x": flat_x[horse_offset:horse_offset + count],
                                  "extra": flat_extra[horse_offset:horse_offset + count], "_offset": horse_offset,
                                  "winner": winner, "race_key": race["key"], "race_date": day}
                        horse_offset += count
                        if year >= 2025:
                            record["race"] = race
                            if race["key"] in reference_keys:
                                record["legacy_x"] = states.legacy_features(race)[:, old.residual.BASIC].copy()
                        records.append(record)
                    normal += 1
                states.update_day(updates)
            require(normal == audit["annual"][str(year)]["counts"]["races"], "twenty_annual_cohort")
            years[str(year)] = {"races": normal, "input_digest": report["input_digest"]}
            artifacts.write_json("coverage.json", {"stage": "features", "years": years, "records": len(records)})
            print(json.dumps({"stage": "features", "year": year, "records": len(records)}), flush=True)
            del raw, daily
            gc.collect()
            check_memory(CONFIG["memory_limit"])
    return records, years


def pack(records):
    """共通の馬別入力と全ペア位置だけを連結し、巨大なペア行列を作らない。

    Args:
        records: 学習期間を日付順に抽出した競走別の値と教師。
    Returns:
        dict: 共有馬別配列・全ペア整数位置・競走境界・正解位置。
    Raises:
        ResearchError: 学習対象が空の場合。
    Notes:
        本番研究の連続した共有viewは複製しない。合成試験の非共有入力だけ連結する。
    """
    require(bool(records), "twenty_empty_training")
    horse_counts = np.asarray([len(r["x"]) for r in records], dtype=np.int32)
    counts = horse_counts.astype(np.int64) * (horse_counts - 1) // 2
    starts = np.cumsum(np.r_[0, counts[:-1]])
    horse_starts = np.cumsum(np.r_[0, horse_counts[:-1]])
    left, right = np.empty(int(counts.sum()), np.int32), np.empty(int(counts.sum()), np.int32)
    for i, record in enumerate(records):
        positions = old.pairs(len(record["x"])) + horse_starts[i]
        left[starts[i]:starts[i] + counts[i]], right[starts[i]:starts[i] + counts[i]] = positions.T
    shared = all(r.get("_offset") == int(horse_starts[i]) for i, r in enumerate(records))
    total = int(horse_counts.sum())
    x = records[0]["x"].base[:total] if shared else np.concatenate([r["x"] for r in records])
    extra = records[0]["extra"].base[:total] if shared else np.concatenate([r["extra"] for r in records])
    data = {"x": x, "extra": extra, "left": left, "right": right, "counts": counts, "starts": starts,
            "targets": starts + np.asarray([r["winner"] for r in records]), "horse_counts": horse_counts,
            "group": np.repeat(np.arange(len(records), dtype=np.int32), counts),
            "horse_starts": horse_starts,
            "horse_group": np.repeat(np.arange(len(records), dtype=np.int32), horse_counts),
            "train_races": len(records), "trained_through": max(r["race_date"] for r in records)}
    winners = np.asarray([r["winner"] for r in records]) + data["starts"]
    data["winner_left"], data["winner_right"] = data["left"][winners], data["right"][winners]
    return data


def block(data, horse_x, centers, begin, end, scale, case):
    """最大5万ペアだけを計算し、初版のfloat32尺度と同じ順序で演算する。"""
    a, b = horse_x[data["left"][begin:end]].astype(float), horse_x[data["right"][begin:end]].astype(float)
    values = np.column_stack(((a + b) / 2, np.abs(a - b)))
    if case == "H17":
        ca, cb = data["extra"][data["left"][begin:end], 24], data["extra"][data["right"][begin:end], 24]
        values = np.column_stack((values, a[:, 0] * b[:, 0], (a[:, 0] * cb + b[:, 0] * ca) / 2))
    values -= centers[data["group"][begin:end]]
    values = values.astype(np.float32)
    if scale is not None:
        values /= scale.astype(np.float32)
    result = values.astype(float)
    check_memory(CONFIG["memory_limit"])
    return result


def pair_objective(beta, data, horse_x, centers, scale, case):
    """馬連softmaxの等競走重み尤度と勾配を、上限付きブロックで求める。

    Args:
        beta: 固定ケースの学習係数。
        data: 学習競走の整数位置と境界・正解位置。
        horse_x: float32の馬別値。ペア演算時だけ倍精度化する。
        centers: 競走内のペア特徴平均。
        scale: trainだけから得たペア特徴尺度。
        case: 結果参照前に固定したケースID。
    Returns:
        tuple: 正則化込みの損失と解析勾配。
    Raises:
        ResearchError: 設定したメモリ上限を超えた場合。
    Notes:
        logits配列をexp重みへ上書きし、全ペア倍精度配列の重複を減らす。
    """
    z, batch = np.empty(len(data["left"])), CONFIG["batch_pairs"]
    for begin in range(0, len(z), batch):
        z[begin:begin + batch] = block(data, horse_x, centers, begin, begin + batch, scale, case) @ beta
    maximum = np.maximum.reduceat(z, data["starts"])
    target_logits = z[data["targets"]].copy()
    for begin in range(0, len(z), batch):
        z[begin:begin + batch] -= maximum[data["group"][begin:begin + batch]]
    np.exp(z, out=z)
    weights = z
    totals = np.add.reduceat(weights, data["starts"])
    loss = np.mean(maximum + np.log(totals) - target_logits)
    for begin in range(0, len(z), batch):
        weights[begin:begin + batch] /= totals[data["group"][begin:begin + batch]]
    weights[data["targets"]] -= 1
    check_memory(CONFIG["memory_limit"])
    gradient = np.zeros(len(beta))
    for begin in range(0, len(z), batch):
        gradient += block(data, horse_x, centers, begin, begin + batch, scale, case).T @ weights[begin:begin + batch]
    return float(loss + .01 * (beta @ beta) / 2), gradient / data["train_races"] + .01 * beta


def pl_objective(beta, horse_x, data):
    """順序を合算したPL馬連尤度と解析勾配を、競走単位の配列で計算する。

    Args:
        beta: 馬別効用の係数。
        horse_x: train尺度で正規化した馬別特徴。
        data: 競走境界と1/2着馬の位置。
    Returns:
        tuple: 順序を合算した馬連の負対数尤度と、L2込み解析勾配。
    Notes:
        単勝確率の積で代用せず、両着順の条件付き確率を合算する。
    """
    logits = horse_x @ beta
    starts, groups = data["horse_starts"], data["horse_group"]
    maximum = np.maximum.reduceat(logits, starts)
    weights = np.exp(logits - maximum[groups])
    sums = np.add.reduceat(weights, starts)
    left, right = data["winner_left"], data["winner_right"]
    wi, wj = weights[left], weights[right]
    si, sj = np.maximum(sums - wi, 1e-300), np.maximum(sums - wj, 1e-300)
    both = np.maximum(2 * sums - wi - wj, 1e-300)
    logq = (logits[left] - maximum) + (logits[right] - maximum) - np.log(sums) + np.log(both) - np.log(si) - np.log(sj)
    derivative = weights * (-1 / sums + 2 / both - 1 / si - 1 / sj)[groups]
    derivative[left] += 1 + wi * (-1 / both + 1 / si)
    derivative[right] += 1 + wj * (-1 / both + 1 / sj)
    return float(-np.mean(logq) + .01 * (beta @ beta) / 2), -horse_x.T @ derivative / len(starts) + .01 * beta


def fit(data, case):
    """一ケースを固定正則化で学習し、定義・尺度・係数を保存用に返す。

    Args:
        data: 当該学習期間だけの共有値と教師。
        case: 固定ケースID。市場混合はN0の学習を共有する。
    Returns:
        dict: 係数、train尺度/節点、件数/日付、最適化結果。
    Raises:
        ResearchError: メモリ上限または固定反復上限内での収束に失敗した場合。
    Notes:
        検証期間の成績から尺度、節点、正則化を変更しない。
    """
    knots = np.quantile(data["x"][:, 0], [.25, .5, .75]).astype(np.float32) if case == "H07" else None
    horse_x = horse_features(data["x"], data["extra"], case, knots)
    print(json.dumps({"stage": "fit", "case": case, "races": data["train_races"], "through": data["trained_through"]}), flush=True)
    if case == "H18":
        scale = np.maximum(np.sqrt(np.mean(horse_x.astype(float) ** 2, axis=0)), 1e-5)
        centered = horse_x.astype(float) / scale
        function, args = pl_objective, (centered, data)
        dimension = horse_x.shape[1]
    else:
        dimension = horse_x.shape[1] * 2 + (2 if case == "H17" else 0)
        centers = np.empty((data["train_races"], dimension))
        for i, (offset, count) in enumerate(zip(data["horse_starts"], data["horse_counts"], strict=True)):
            local_x = horse_x[offset:offset + count]
            local_e = data["extra"][offset:offset + count]
            indices = old.pairs(int(count))
            a, b = local_x[indices[:, 0]].astype(float), local_x[indices[:, 1]].astype(float)
            values = np.column_stack(((a + b) / 2, np.abs(a - b)))
            if case == "H17":
                values = np.column_stack((values, a[:, 0] * b[:, 0],
                    (a[:, 0] * local_e[indices[:, 1], 24] + b[:, 0] * local_e[indices[:, 0], 24]) / 2))
            centers[i] = values.mean(axis=0)
        squares = np.zeros(dimension)
        for begin in range(0, len(data["left"]), CONFIG["batch_pairs"]):
            values = block(data, horse_x, centers, begin, begin + CONFIG["batch_pairs"], None, case)
            squares += np.einsum("ij,ij->j", values, values)
        scale = np.maximum(np.sqrt(squares / len(data["left"])), 1e-5)
        function, args = pair_objective, (data, horse_x, centers, scale, case)
    check_memory(CONFIG["memory_limit"])
    result = minimize(function, np.zeros(dimension), args=args, jac=True, method="L-BFGS-B",
                      options={"maxiter": 400, "ftol": 1e-10, "gtol": 1e-6})
    require(bool(result.success), "twenty_optimizer_failed_" + case)
    model = {"case": case, "scale": scale, "coef": result.x, "knots": knots,
             "train_races": data["train_races"], "trained_through": data["trained_through"],
             "train_pairs": len(data["left"]), "optimizer": {"iterations": int(result.nit), "objective": float(result.fun)}}
    print(json.dumps({"stage": "fitted", "case": case, "optimizer": model["optimizer"]}), flush=True)
    return model


def predict(model, record):
    """価格・現在結果を読まず、一ケースの全馬連確率を返す。"""
    case = model["case"]
    horse_x = horse_features(record["x"], record["extra"], case, model["knots"])
    if case == "H18":
        logp = (horse_x.astype(float) / model["scale"]) @ model["coef"]
        logp -= logsumexp(logp)
        indices = old.pairs(len(logp))
        a, b = indices[:, 0], indices[:, 1]
        p = np.exp(logp)
        q = np.exp(logp[a] + logp[b]) * (1 / np.maximum(1 - p[a], 1e-300) + 1 / np.maximum(1 - p[b], 1e-300))
        require(np.isclose(q.sum(), 1, atol=1e-10), "twenty_PL_normalization")
        return q / q.sum()
    values = local_pairs(horse_x, record["extra"], case).astype(np.float32)
    values /= model["scale"].astype(np.float32)
    return softmax(values.astype(float) @ model["coef"])


def load_prices(reader, records):
    """一期間のT30/HRを100競走単位で読み、全候補で同じ価格を共有する。

    Args:
        reader: 版・権限検査済みのSQL reader。
        records: 結果参照前に固定した評価対象競走。
    Returns:
        dict: 競走別の全ペア価格・正規化市場・HR払戻と来歴hash。
    Raises:
        ResearchError: 時点、対象馬、払戻またはSELECTの契約違反。
    """
    by_key = {r["race_key"]: r for r in records}
    output = {}
    keys = sorted(by_key)
    for begin in range(0, len(keys), 100):
        batch = keys[begin:begin + 100]
        markets = old.indexed_rows(reader, batch, "market.odds_asof_index", old.base.FIELDS["market.odds_asof_index"],
                                  "AND t.market=N'quinella' AND t.horizon=N'T30'")
        payouts = old.indexed_rows(reader, batch, "history.payouts", old.base.FIELDS["history.payouts"],
                                  "AND t.market=N'quinella' AND t.slot_status=N'published'")
        grouped_m, grouped_p = defaultdict(list), defaultdict(list)
        for row in markets:
            grouped_m[row["race_key"]].append(row)
        for row in payouts:
            grouped_p[row["race_key"]].append(row)
        for key in batch:
            record = by_key[key]
            prices = plan.validate_inputs(record["race"], grouped_m[key], grouped_p[key])
            pair_keys = list(combinations([r["horse_no"] for r in record["race"]["runners"]], 2))
            prices = np.asarray([prices[p] for p in pair_keys])
            market = 1 / prices
            market /= market.sum()
            output[key] = {"prices": prices, "market": market, "payout_yen": int(grouped_p[key][0]["payout_yen"]),
                           "pairs": pair_keys, "market_sha256": grouped_m[key][0]["content_sha256"],
                           "hr_sha256": grouped_p[key][0]["hr_sha256"]}
    return output


def mix(probabilities, market, case):
    """固定0.1の算術/幾何混合だけを適用し、重み探索を行わない。"""
    if case == "H19":
        return .9 * market + .1 * probabilities
    if case == "H20":
        return softmax(.9 * np.log(market) + .1 * np.log(probabilities))
    return probabilities


def evaluate(records, models, prices, phase, baseline=None):
    """全構成を共通競走で比較し、損失モーメントと固定購入政策を保存する。

    Args:
        records: 固定評価競走と事前構築した特徴。
        models: 比較対象IDから保存可能なモデルへの対応。
        prices: 同じT30の価格と確定HR。学習には渡さない。
        phase: 一次・二次・最終の評価区分。
        baseline: 最終段階だけ比較する保存R1。省略時は比較しない。
    Returns:
        tuple: 競走別モーメント/損失、仮想購入、結果非依存の確認件数。
    Raises:
        ResearchError: 確率不正または現在結果による予測変化。
    """
    rows, tickets, checks = [], [], 0
    for record in records:
        source = prices[record["race_key"]]
        market, quoted = source["market"], source["prices"]
        probabilities = {"M0": market}
        cache = {}
        for name, model in models.items():
            identity = id(model)
            if identity not in cache:
                cache[identity] = predict(model, record)
                clean = {"x": record["x"], "extra": record["extra"]}
                require(np.array_equal(cache[identity], predict(model, clean)), "twenty_result_dependency")
                checks += 1
            probabilities[name] = mix(cache[identity], market, name)
        if baseline is not None:
            legacy = np.zeros((len(record["x"]), 48))
            legacy[:, old.residual.BASIC] = record["legacy_x"]
            probabilities["R1"] = old.residual.predict(baseline, {"x": legacy, "market": market})
        winner = record["winner"]
        row = {"race_key": record["race_key"], "race_date": record["race_date"], "period": phase,
               "pair_count": len(quoted), "surface": record["race"]["surface"],
               "no_history_horses": int(np.sum(record["extra"][:, 22] == 1)),
               "market_sha256": source["market_sha256"], "hr_sha256": source["hr_sha256"],
               "loss": {}, "brier": {}, "moments": {}, "stake": {}, "payout": {}}
        for name, p in probabilities.items():
            require(np.isfinite(p).all() and np.all(p > 0) and abs(float(p.sum()) - 1) < 1e-10, "twenty_invalid_probability")
            row["loss"][name] = float(-np.log(p[winner]))
            row["brier"][name] = float((p @ p - 2 * p[winner] + 1) / len(p))
            row["moments"][name] = {"winning_probability": float(p[winner]), "squared_sum": float(p @ p),
                                    "sum": float(p.sum()), "minimum": float(p.min())}
            row["stake"][name] = row["payout"][name] = 0
            index = old.select_pair(p, quoted, np.ones(len(p)))
            if index is not None:
                returned = source["payout_yen"] * 6 if index == winner else 0
                tickets.append({"race_key": record["race_key"], "race_date": record["race_date"],
                    "venue": str(record["race"]["course"]), "variant": name, "split": phase,
                    "horses": list(source["pairs"][index]), "probability": float(p[index]), "target": int(index == winner),
                    "ticket": {"kind": "quinella", "stake_yen": 600, "payout_yen": returned,
                               "quoted_odds": float(quoted[index]), "expected_multiplier": float(p[index] * quoted[index])}})
                row["stake"][name], row["payout"][name] = 600, returned
        rows.append(row)
    return rows, tickets, checks


def summaries(rows, tickets):
    """方式ごとに精度と仮想購入成績を分け、月/芝ダート/少履歴群も併記する。"""
    if not rows:
        return {}
    result = {}
    for name in rows[0]["loss"]:
        selected = [t for t in tickets if t["variant"] == name]
        accounting = old.prior.summary([{**t["ticket"], "race_date": t["race_date"]} for t in selected])
        require(accounting["stake_yen"] == sum(r["stake"][name] for r in rows)
                and accounting["payout_yen"] == sum(r["payout"][name] for r in rows), "twenty_accounting")
        groups = {}
        for row in rows:
            keys = ["month:" + row["race_date"][:7], "surface:" + str(row["surface"]),
                    "history:" + ("has_zero" if row["no_history_horses"] else "all_observed")]
            for key in keys:
                totals = groups.setdefault(key, [0.0, 0.0, 0])
                totals[0] += row["loss"][name]
                totals[1] += row["brier"][name]
                totals[2] += 1
        result[name] = {"logloss": float(np.mean([r["loss"][name] for r in rows])),
                        "brier": float(np.mean([r["brier"][name] for r in rows])),
                        "hits": sum(t["target"] for t in selected), **accounting,
                        "groups": {k: {"races": v[2], "logloss": v[0] / v[2], "brier": v[1] / v[2]} for k, v in groups.items()}}
    return result


def simultaneous_intervals(rows, cases):
    """対応日bootstrapで20候補と市場の損失差の通常/同時区間を作る。

    Args:
        rows: 全候補を同一競走で評価した一次の競走別損失。
        cases: 事前固定した比較ID。
    Returns:
        dict: 市場との差、個別95%区間、最大絶対偏差による同時95%区間。
    Notes:
        seed232・2000反復。全候補で同じ開催日抽出を共有する。
        既参照期間の回顧的選抜であり、未知検証を保証しない。
    """
    dates = sorted({r["race_date"] for r in rows})
    daily = np.zeros((len(dates), len(cases) + 1))
    index = {day: i for i, day in enumerate(dates)}
    for row in rows:
        daily[index[row["race_date"]], :-1] += [row["loss"][case] - row["loss"]["M0"] for case in cases]
        daily[index[row["race_date"]], -1] += 1
    estimate = daily[:, :-1].sum(axis=0) / len(rows)
    draws = np.random.default_rng(232).integers(0, len(dates), (2000, len(dates)))
    sampled = daily[draws].sum(axis=1)
    difference = sampled[:, :-1] / sampled[:, -1:]
    radius = float(np.quantile(np.max(np.abs(difference - estimate), axis=1), .95))
    return {case: {"loss_difference_vs_market": float(estimate[i]),
                   "interval_95": np.quantile(difference[:, i], [.025, .975]).tolist(),
                   "simultaneous_95": [float(estimate[i] - radius), float(estimate[i] + radius)]}
            for i, case in enumerate(cases)}


def secondary_decision(primary_summary, secondary_summary, finalists):
    """固定した上位3案だけを二次条件で判定し、通過した最良1案へ固定する。

    Args:
        primary_summary: 一次で固定した方式別精度。購入成績は選抜へ使わない。
        secondary_summary: 同時点市場・同期間N0と候補の二次精度。
        finalists: 一次の損失順で固定した最大3ID。
    Returns:
        dict: 各条件、選抜1IDまたはNone、全不合格時の停止理由。
    """
    checks, passed = {}, []
    for case in finalists:
        candidate, market, control = secondary_summary[case], secondary_summary["M0"], secondary_summary["N0"]
        condition = {"loss_vs_market": candidate["logloss"] <= market["logloss"] * .9975,
                     "loss_vs_N0": candidate["logloss"] <= control["logloss"] * .995,
                     "brier_vs_market": candidate["brier"] <= market["brier"] * 1.005,
                     "brier_vs_N0": candidate["brier"] <= control["brier"] * 1.005,
                     "primary_better_than_market": primary_summary[case]["logloss"] < primary_summary["M0"]["logloss"]}
        checks[case] = {"passed": all(condition.values()), "checks": condition}
        if all(condition.values()):
            passed.append(case)
    passed.sort(key=lambda c: (secondary_summary[c]["logloss"], c))
    return {"checks": checks, "selected": passed[0] if passed else None,
            "stop_reason": None if passed else "all_secondary_candidates_failed"}


def save_models(artifacts, phase, models, sample):
    """モデルを保存して再読込し、全モデルの推論が完全一致することを確認する。

    Args:
        artifacts: 一意runの保存先。
        phase: 固定した選抜段階。
        models: ID別の係数と尺度を持つモデル。
        sample: 保存後推論に用いる最大3競走。
    Returns:
        str: 書込んだjoblibファイルのSHA256。
    Raises:
        ResearchError: 保存後の推論が変化した場合。
    """
    path = artifacts.path / ("models_" + phase + ".joblib")
    joblib.dump({"config": CONFIG, "models": models}, path)
    saved = joblib.load(path)["models"]
    for name, model in models.items():
        for record in sample[:3]:
            require(np.array_equal(predict(model, record), predict(saved[name], record)), "twenty_reload_changed")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reused_primary_control(data, case):
    """収束済みの同一ケースを再学習せず、目的値を照合して再利用する。

    Args:
        data: 修正後のメモリ共有版で構築した同じ一次学習対象。
        case: 再利用を事前固定したN0またはH01〜H07。
    Returns:
        dict: hash確認済みの係数・尺度・元の収束記録。
    Raises:
        ResearchError: 来歴hash、対象期間/件数、目的値が一致しない場合。
    Notes:
        失敗run全体を成功扱いにはしない。性能評価前に収束した同一定義だけを使う。
    """
    path = existing_run(CONTROL_RUN) / "models_primary_partial.joblib"
    require(hashlib.sha256(path.read_bytes()).hexdigest() == CONTROL_SHA, "twenty_reused_control_hash")
    require(case in REUSED_PRIMARY, "twenty_invalid_reused_case")
    model = joblib.load(path)["models"][case]
    require(model["train_races"] == data["train_races"] and model["trained_through"] == data["trained_through"],
            "twenty_reused_control_scope")
    horse_x = horse_features(data["x"], data["extra"], case, model["knots"])
    centers = old.centers_for(data, horse_x.astype(float))
    value, gradient = pair_objective(model["coef"], data, horse_x, centers, model["scale"], case)
    require(abs(value - model["optimizer"]["objective"]) < 1e-10 and np.isfinite(gradient).all(),
            "twenty_reused_control_objective")
    print(json.dumps({"stage": "reused_control", "case": case, "objective": value, "source_run": CONTROL_RUN}), flush=True)
    return model


def execute():
    """20案を上限内で学習比較し、二次未達なら最終評価を追加せず終了する。

    Returns:
        dict: run ID、各段階の損失・選抜・合否、モデル学習数。
    Raises:
        ResearchError: 入力/実装異常。failed証跡とrun IDを残して停止する。
    Notes:
        固定SQLのSELECTと新規runへの書込のみ。実購入や既定変更は行わない。
        性能未達は実装失敗と分離し、正常な研究終了として保存する。
    """
    old.base.install_input_guard()
    ready_path = existing_run(PREFLIGHT)
    ready = read_json(ready_path / "metrics.json")
    ready_manifest = read_json(ready_path / "manifest.json")
    require(ready_manifest["status"] == "complete" and digest(ready) == ready_manifest["metrics_sha256"]
            and ready["input_ready"] and read_json(ready_path / "verification.json")["status"] == "passed", "twenty_preflight_not_ready")
    artifacts = RunArtifacts(CONFIG, "chimera-twenty-fixed-fit")
    for name in ("scripts/run_jra_chimera_twenty_fit.py", "scripts/verify_jra_chimera_twenty_fit.py"):
        artifacts.manifest["code_sha256"][name] = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
    artifacts.manifest["spec_sha256"] = {str(i): hashlib.sha256(next((ROOT / ".workstate/jra-srb/sqlserver-model-data-audit/spec").glob(str(i) + "-*.md")).read_bytes()).hexdigest() for i in (230, 231, 232)}
    artifacts.write_json("manifest.json", artifacts.manifest)
    print(json.dumps({"stage": "starting", "run_id": artifacts.run_id}), flush=True)
    try:
        with threadpool_limits(limits=1):
            records, years = prepare(artifacts)
            primary = [r for r in records if plan.split_for(r["race_date"]) == "primary"]
            secondary = [r for r in records if plan.split_for(r["race_date"]) == "secondary"]
            require(len(primary) == 1436 and len(secondary) == 715, "twenty_preflight_cohort_changed")
            training = pack([r for r in records if r["race_date"] <= "2024-12-31"])
            model_map, histories, hashes = {}, {}, {}
            for case in ("N0", *plan.CASES[:18]):
                model_map[case] = reused_primary_control(training, case) if case in REUSED_PRIMARY else fit(training, case)
                histories["primary:" + case] = {k: model_map[case][k] for k in ("train_races", "train_pairs", "trained_through", "optimizer")}
                artifacts.write_json("model_history.json", histories)
                joblib.dump({"models": model_map, "config": CONFIG}, artifacts.path / "models_primary_partial.joblib")
                gc.collect()
            model_map["H19"] = model_map["H20"] = model_map["N0"]
            hashes["models_primary.joblib"] = save_models(artifacts, "primary", model_map, primary)
            del training
            gc.collect()
            config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
            with old.prior.ExperimentMarketReader(config) as reader:
                reader.selected(["2025-11-01"])
                primary_prices = load_prices(reader, primary)
                primary_rows, primary_tickets, primary_checks = evaluate(primary, model_map, primary_prices, "primary")
                primary_summary = summaries(primary_rows, primary_tickets)
                intervals = simultaneous_intervals(primary_rows, plan.CASES)
                finalists = sorted(plan.CASES, key=lambda c: (primary_summary[c]["logloss"], c))[:3]
                partial = {"stage": "primary_selection_frozen", "primary_results": primary_summary,
                           "primary_intervals": intervals, "finalists": finalists}
                artifacts.write_json("metrics.json", partial)
                print(json.dumps({"stage": "primary_selected", "finalists": finalists,
                                  "losses": {c: primary_summary[c]["logloss"] for c in ["M0", "N0", *finalists]}}), flush=True)
                del model_map, primary_prices
                training = pack([r for r in records if r["race_date"] <= "2025-06-30"])
                secondary_models = {"N0": fit(training, "N0")}
                histories["secondary:N0"] = {k: secondary_models["N0"][k] for k in ("train_races", "train_pairs", "trained_through", "optimizer")}
                for case in finalists:
                    if case not in ("H19", "H20"):
                        secondary_models[case] = fit(training, case)
                        histories["secondary:" + case] = {k: secondary_models[case][k] for k in ("train_races", "train_pairs", "trained_through", "optimizer")}
                    else:
                        secondary_models[case] = secondary_models["N0"]
                artifacts.write_json("model_history.json", histories)
                hashes["models_secondary.joblib"] = save_models(artifacts, "secondary", secondary_models, secondary)
                del training
                gc.collect()
                secondary_prices = load_prices(reader, secondary)
                secondary_rows, secondary_tickets, secondary_checks = evaluate(secondary, secondary_models, secondary_prices, "secondary")
                secondary_summary = summaries(secondary_rows, secondary_tickets)
                decision = secondary_decision(primary_summary, secondary_summary, finalists)
                artifacts.write_json("metrics.json", {**partial, "stage": "secondary_selection_frozen", "secondary_results": secondary_summary,
                                                     "secondary_decision": decision})
                print(json.dumps({"stage": "secondary_decision", **decision}), flush=True)
                development_rows, development_tickets, evaluation_rows, evaluation_tickets = [], [], [], []
                development_gate = evaluation_gate = purchase_gate = None
                selected = decision["selected"]
                if selected:
                    del secondary_prices, secondary_models
                    training = pack([r for r in records if r["race_date"] <= "2025-09-30"])
                    fitted = fit(training, "N0" if selected in ("H19", "H20") else selected)
                    histories["final:" + selected] = {k: fitted[k] for k in ("train_races", "train_pairs", "trained_through", "optimizer")}
                    artifacts.write_json("model_history.json", histories)
                    hashes["models_final.joblib"] = save_models(artifacts, "final", {selected: fitted}, primary)
                    del training
                    gc.collect()
                    reference = read_json(existing_run(old.REFERENCE) / "metrics.json")
                    ref_rows = {r["race_key"]: r for r in reference["race_metrics"]}
                    baseline, _ = load_model()
                    development = [r for r in records if r["race_key"] in ref_rows and ref_rows[r["race_key"]]["period"] == "evaluation_2025"]
                    development_prices = load_prices(reader, development)
                    development_rows, development_tickets, _ = evaluate(development, {selected: fitted}, development_prices, "development", baseline)
                    # 候補のIDは選抜後に固定したまま、共有ゲートのABC名へ対応する。
                    development_rows, development_tickets = alias_candidate(development_rows, development_tickets, selected)
                    assert_reference(development_rows, ref_rows)
                    development_gate = old.accuracy_gate(development_rows, 485, "development")
                    artifacts.write_json("metrics.json", {**partial, "stage": "development_decision_frozen",
                        "secondary_decision": decision, "development_gate": development_gate})
                    if development_gate["passed"]:
                        evaluation = [r for r in records if r["race_key"] in ref_rows and ref_rows[r["race_key"]]["period"] in ("evaluation_early", "evaluation_late", "later_2026")]
                        evaluation_prices = load_prices(reader, evaluation)
                        evaluation_rows, evaluation_tickets, _ = evaluate(evaluation, {selected: fitted}, evaluation_prices, "evaluation", baseline)
                        evaluation_rows, evaluation_tickets = alias_candidate(evaluation_rows, evaluation_tickets, selected)
                        assert_reference(evaluation_rows, ref_rows)
                        evaluation_gate = old.accuracy_gate(evaluation_rows, 1279, "evaluation")
                        for period in ("evaluation_early", "evaluation_late", "later_2026"):
                            subset = [r for r in evaluation_rows if ref_rows[r["race_key"]]["period"] == period]
                            evaluation_gate["checks"]["non_worse_" + period] = bool(subset) and bool(np.mean([r["loss"]["ABC"] - r["loss"]["R1"] for r in subset]) <= 0)
                        evaluation_gate["passed"] = all(evaluation_gate["checks"].values())
                        # 共通購入ゲートはABC/M0/R1のみを参照する。
                        aliases = {"M30": "M0", "M10": "M0", "R30": "R1", "R10": "ABC"}
                        converted = [{**t, "variant": alias} for alias, name in aliases.items()
                                     for t in evaluation_tickets if t["variant"] == name]
                        purchase_gate = old.timing.purchase_gate(old.gate_rows(evaluation_rows), converted)
            supported = bool(evaluation_gate and evaluation_gate["passed"])
            tickets = primary_tickets + secondary_tickets + development_tickets + evaluation_tickets
            predictions_hash = artifacts.write_predictions(tickets)
            metrics = {"stage": "complete", "research_status": "prospective_validation_only" if supported else "closed_failed_performance_gate",
                       "accuracy_candidate_supported": supported, "selected_case": selected, "finalists": finalists,
                       "secondary_decision": decision, "primary_results": primary_summary, "primary_intervals": intervals,
                       "secondary_results": secondary_summary, "development_gate": development_gate,
                       "evaluation_gate": evaluation_gate, "purchase_gate": purchase_gate,
                       "model_fits": len(histories), "case_count": 20, "primary_evaluated_cases": list(plan.CASES),
                       "new_model_fits": len(histories) - len(REUSED_PRIMARY), "reused_model_fits": len(REUSED_PRIMARY),
                       "result_dependency_checks": primary_checks + secondary_checks,
                       "race_metrics": primary_rows + secondary_rows + development_rows + evaluation_rows,
                       "development_results": summaries(development_rows, development_tickets),
                       "evaluation_results": summaries(evaluation_rows, evaluation_tickets),
                       "stop_further_tuning": True, "default_changed": False, "unseen_test": False}
            artifacts.write_json("coverage.json", {"years": years, "primary": len(primary_rows), "secondary": len(secondary_rows),
                "development": len(development_rows), "evaluation": len(evaluation_rows), "preflight_run": PREFLIGHT})
            artifacts.write_json("metrics.json", metrics)
            (artifacts.path / "models_primary_partial.joblib").unlink(missing_ok=True)
            artifacts.finish(overall_complete=False, research_status=metrics["research_status"],
                             performance_gate_passed=supported, metrics_sha256=digest(metrics),
                             predictions_sha256=predictions_hash, model_sha256=hashes)
            return {"run_id": artifacts.run_id, "research_status": metrics["research_status"], "case_count": 20,
                    "model_fits": len(histories), "finalists": finalists, "secondary_decision": decision,
                    "new_model_fits": len(histories) - len(REUSED_PRIMARY), "reused_model_fits": len(REUSED_PRIMARY),
                    "development_gate": development_gate, "evaluation_gate": evaluation_gate,
                    "primary_loss": {c: primary_summary[c]["logloss"] for c in primary_summary},
                    "secondary_loss": {c: secondary_summary[c]["logloss"] for c in secondary_summary}}
    except Exception as error:
        safe = error if isinstance(error, ResearchError) else ResearchError("twenty_fit_execution_failed", 4, error_type=type(error).__name__)
        artifacts.fail(safe)
        safe.details["run_id"] = artifacts.run_id
        raise safe from None


def alias_candidate(rows, tickets, selected):
    """固定最終候補だけを共有ゲートのABC名へ対応させる。"""
    for row in rows:
        for field in ("loss", "brier", "moments", "stake", "payout"):
            row[field]["ABC"] = row[field].pop(selected)
    return rows, [{**t, "variant": "ABC"} if t["variant"] == selected else t for t in tickets]


def assert_reference(rows, reference):
    """最終段階の元R1・市場を保存済み競走別性能へ照合する。"""
    for row in rows:
        old_row = reference[row["race_key"]]
        require(abs(row["loss"]["R1"] - old_row["loss"]["C0"]) < 1e-12
                and abs(row["loss"]["M0"] - old_row["loss"]["M0"]) < 1e-12
                and row["stake"]["R1"] == old_row["stake"]["C0_P0"]
                and row["payout"]["R1"] == old_row["payout"]["C0_P0"], "twenty_R1_reference_changed")


def verify(run_id):
    """保存モーメント・購入・モデル・選抜/停止をSQLなしで再計算する。

    Args:
        run_id: 完了済みの一意な研究run ID。
    Returns:
        dict: 検証状態、件数、選抜/停止の確認結果。
    Raises:
        ResearchError: hash、モーメント、会計、選抜、時点/停止条件の不一致。
    Notes:
        SQL再読取・再学習なし。成功時だけrun内verification.jsonを保存する。
    """
    import gzip

    path = existing_run(run_id)
    manifest, metrics = read_json(path / "manifest.json"), read_json(path / "metrics.json")
    config, history = read_json(path / "config.json"), read_json(path / "model_history.json")
    require(manifest["status"] == "complete" and digest(metrics) == manifest["metrics_sha256"]
            and config == CONFIG, "twenty_fit_saved_hash")
    for filename, sha in manifest["model_sha256"].items():
        require(hashlib.sha256((path / filename).read_bytes()).hexdigest() == sha, "twenty_fit_model_hash")
        payload = joblib.load(path / filename)
        require(payload["config"] == CONFIG, "twenty_fit_model_config")
    for filename, sha in manifest["code_sha256"].items():
        require(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest() == sha, "twenty_fit_source_changed")
    for i, sha in manifest["spec_sha256"].items():
        require(hashlib.sha256(next((ROOT / ".workstate/jra-srb/sqlserver-model-data-audit/spec").glob(i + "-*.md")).read_bytes()).hexdigest() == sha,
                "twenty_fit_spec_changed")
    with gzip.open(path / "predictions.jsonl.gz", "rt", encoding="utf-8") as stream:
        tickets = [json.loads(line) for line in stream]
    require(digest(tickets) == manifest["predictions_sha256"], "twenty_fit_prediction_hash")
    rows = metrics["race_metrics"]
    ticket_index = defaultdict(list)
    for ticket in tickets:
        ticket_index[ticket["split"], ticket["race_key"], ticket["variant"]].append(ticket)
    require(len({(r["period"], r["race_key"]) for r in rows}) == len(rows), "twenty_fit_duplicate_race")
    for row in rows:
        for name, moments in row["moments"].items():
            p, sq = moments["winning_probability"], moments["squared_sum"]
            require(0 < p <= 1 and 0 < moments["minimum"] <= p and abs(moments["sum"] - 1) < 1e-10,
                    "twenty_fit_invalid_moments")
            require(abs(-math.log(p) - row["loss"][name]) < 1e-12
                    and abs((sq - 2 * p + 1) / row["pair_count"] - row["brier"][name]) < 1e-12,
                    "twenty_fit_loss_reconstruction")
            selected = ticket_index[row["period"], row["race_key"], name]
            require(len(selected) <= 1 and row["stake"][name] == sum(t["ticket"]["stake_yen"] for t in selected)
                    and row["payout"][name] == sum(t["ticket"]["payout_yen"] for t in selected), "twenty_fit_ticket_accounting")
    phase_rows = {p: [r for r in rows if r["period"] == p] for p in ("primary", "secondary", "development", "evaluation")}
    require(len(phase_rows["primary"]) == 1436 and len(phase_rows["secondary"]) == 715,
            "twenty_fit_scope")
    for phase in ("primary", "secondary"):
        measured = summaries(phase_rows[phase], [t for t in tickets if t["split"] == phase])
        require(digest(measured) == digest(metrics[phase + "_results"]), "twenty_fit_summary_changed")
    require(metrics["primary_evaluated_cases"] == list(plan.CASES) and metrics["case_count"] == 20,
            "twenty_fit_not_twenty_cases")
    for row in phase_rows["primary"]:
        require(set(row["loss"]) == {"M0", "N0", *plan.CASES}, "twenty_fit_missing_case")
    primary, secondary = metrics["primary_results"], metrics["secondary_results"]
    expected_finalists = sorted(plan.CASES, key=lambda c: (primary[c]["logloss"], c))[:3]
    require(metrics["finalists"] == expected_finalists, "twenty_fit_primary_selection")
    require(digest(simultaneous_intervals(phase_rows["primary"], plan.CASES)) == digest(metrics["primary_intervals"]),
            "twenty_fit_intervals")
    # 独立した式で二次選抜を確認し、実行時のsecondary_decisionへ依存しない。
    eligible = []
    for case in expected_finalists:
        conditions = {"loss_vs_market": secondary[case]["logloss"] <= secondary["M0"]["logloss"] * .9975,
            "loss_vs_N0": secondary[case]["logloss"] <= secondary["N0"]["logloss"] * .995,
            "brier_vs_market": secondary[case]["brier"] <= secondary["M0"]["brier"] * 1.005,
            "brier_vs_N0": secondary[case]["brier"] <= secondary["N0"]["brier"] * 1.005,
            "primary_better_than_market": primary[case]["logloss"] < primary["M0"]["logloss"]}
        require(metrics["secondary_decision"]["checks"][case] == {"passed": all(conditions.values()), "checks": conditions},
                "twenty_fit_secondary_checks")
        if all(conditions.values()):
            eligible.append(case)
    eligible.sort(key=lambda c: (secondary[c]["logloss"], c))
    chosen = eligible[0] if eligible else None
    require(chosen == metrics["selected_case"] == metrics["secondary_decision"]["selected"], "twenty_fit_selected_case")
    if chosen is None:
        require(not phase_rows["development"] and not phase_rows["evaluation"]
                and metrics["development_gate"] is None and metrics["evaluation_gate"] is None
                and metrics["research_status"] == "closed_failed_performance_gate", "twenty_fit_stop_violated")
    else:
        require(digest(old.accuracy_gate(phase_rows["development"], 485, "development")) == digest(metrics["development_gate"]),
                "twenty_fit_development_gate")
        if not metrics["development_gate"]["passed"]:
            require(not phase_rows["evaluation"] and metrics["evaluation_gate"] is None, "twenty_fit_evaluation_after_failure")
    require(metrics["model_fits"] == len(history) and not metrics["default_changed"] and not metrics["unseen_test"]
            and metrics["stop_further_tuning"], "twenty_fit_status")
    require(metrics["new_model_fits"] == len(history) - len(REUSED_PRIMARY) and metrics["reused_model_fits"] == len(REUSED_PRIMARY),
            "twenty_fit_reuse_count")
    for name, model_history in history.items():
        phase = name.split(":")[0]
        limit = {"primary": "2024-12-31", "secondary": "2025-06-30", "final": "2025-09-30"}[phase]
        require(model_history["trained_through"] <= limit, "twenty_fit_future_training")
    result = {"status": "passed", "run_id": run_id, "races": len(rows), "saved_predictions": len(tickets),
              "cases": 20, "model_fits": len(history), "sql_reads": 0, "refits": 0,
              "selected_case": chosen, "research_status": metrics["research_status"]}
    (path / "verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
