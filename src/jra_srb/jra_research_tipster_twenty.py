"""概要: 2003年以降のSQL保存RA/SEで予想家由来の20仮説を比較する。
作成日: 2026-10-17
入力: spec140、年別SQL snapshot4〜27、市場SQL31、既存評価集合。
出力: 新規runの年別充足・20件台帳・モデル・選択ペア・時系列評価。
実行例: uv run --frozen --extra ml python scripts/run_jra_tipster_twenty.py
注意事項: SELECT専用。取得/SQLite/旧JSONL/原データ複製/削除/運用変更なし。
"""

from __future__ import annotations

from collections import Counter, defaultdict, deque
from datetime import date, datetime, timezone
import gc
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import traceback

import joblib
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import expit, softmax
from sklearn.linear_model import SGDClassifier
from threadpoolctl import threadpool_limits

from .jra_research_artifacts import ROOT, RunArtifacts
from .jra_research_contracts import ResearchError, digest, horse_number
from .jra_research_history import HistoryConfig
from .jra_research_reader import ResearchReader
from .jra_research_resources import check_memory
from . import jra_research_tipster_experiment as previous
from . import jra_research_tipster_smoke as base


REFERENCE = ROOT / "artifacts/jra_research/runs/20261017T091533Z_631037c77cb34fd895c779df1ba77e8d"
FEATURES = ["lifetime_strength", "lifetime_win", "lifetime_top3", "history_size", "days_since_last",
            "last_strength", "mean3_strength", "last_closing_rank", "mean3_closing_rank", "last_position_gain",
            "mean3_position_gain", "last_corner_ratio", "last_pace", "adverse_pace", "best3_strength", "strength_drop",
            "distance_form_delta", "surface_form_delta", "course_form_delta", "distance_change", "same_surface",
            "same_course", "restored_conditions", "late_acceleration", "field_size", "age", "weight_carried", "frame",
            "interval_deviation", "front_density", "density_x_style", "distance", "surface_dirt", "maiden", "open",
            "season_sin", "season_cos", "jockey_top3", "trainer_top3", "season_form_delta", "weight_change",
            "closing_x_gain", "endurance", "missing_closing", "missing_corner", "missing_pace", "no_history", "ability_uncertainty"]
BASIC = [0, 1, 2, 3, 24, 25, 26, 27, 31, 32, 33, 34, 35, 36, 46]
THEORIES = [
    ("T01", "2003年からの生涯成績", [], 2003, "古い環境の影響で近年を予測しにくくなる可能性"),
    ("T02", "2020年以降の学習との比較", [], 2020, "古い年の学習を除いても履歴自体は2003年から保持する"),
    ("T03", "直近3走の上昇下降", [4, 5, 6, 14, 15], 2003, "生涯能力の言い換えに過ぎない可能性"),
    ("T04", "相対上がり", [7, 8, 43], 2003, "終盤の良さと着順が重複する可能性"),
    ("T05", "通過位置からの進出", [9, 10, 11, 44], 2003, "後方にいた馬の機械的な順位上昇の可能性"),
    ("T06", "先行馬の速い流れの負荷", [11, 12, 13, 44, 45], 2003, "実際の進路不利や消耗を観測していない"),
    ("T07", "過去の終盤加速", [23, 45], 2003, "レース全体のラップと個別馬の能力は別"),
    ("T08", "長距離消耗への適性", [42, 12, 45], 2003, "過去の長距離高回収を事後条件として選ばない"),
    ("T09", "距離適性と距離変更", [16, 19], 2003, "距離別の小標本を縮約する必要"),
    ("T10", "芝ダート適性と復帰", [17, 20], 2003, "馬場別に分けるだけでは一般化しない可能性"),
    ("T11", "競馬場への適性", [18, 21], 2003, "能力の高い馬が同じ場に集まるだけの可能性"),
    ("T12", "低下後の得意条件復帰", [14, 15, 16, 17, 18, 19, 20, 21, 22], 2003, "過去失敗した必須フィルタにはせず連続特徴で比較"),
    ("T13", "休養と再出走間隔", [4, 28], 2003, "好都合な休養日数の閾値探索をしない"),
    ("T14", "斤量変化", [40], 2003, "現在の斤量自体と前走からの変化を分ける"),
    ("T15", "騎手と厩舎の経験", [37, 38], 2003, "同日結果の混入と少標本の過信を避ける"),
    ("T16", "季節適性", [39], 2003, "過去年の季節経験だけを使う"),
    ("T17", "先行馬の密度と役割", [11, 29, 30, 44], 2003, "脚質の代理値が実展開を表すとは限らない"),
    ("T18", "経験量と能力の不確実性", [47], 2003, "少標本を高評価する能力推定を抑えられるか"),
    ("T19", "内容と条件の統合", list(range(len(FEATURES))), 2003, "特徴を増やすことでノイズと相関を増やす可能性"),
]
CONFIG = {"protocol": "spec140-jv-theory-twenty-v1", "history_from": "2003-01-01", "train_through": "2025-09-30",
          "calibration": ["2025-10-01", "2025-10-31"], "development": ["2025-11-01", "2025-12-31"],
          "reused_evaluation": ["2026-01-01", "2026-05-31"], "market_snapshot": 31,
          "annual_snapshots": list(range(4, 28)), "theory_count": 20, "unseen_test": False,
          "availability": "retrospective_SE_RA_attributes_not_proven_T30", "stake_yen": 600,
          "sgd": {"loss": "log_loss", "alpha": .0001, "average": True, "random_state": 42,
                  "shuffle": False, "learning_rate": "constant", "eta0": .02},
          "limits": {"year_rows": 500000, "all_rows": 4000000, "memory_bytes": 2147483648}}


def number(raw, default=0):
    """固定byte欄を整数にし、空欄や非数値は指定の欠測値へ変換する。"""
    value = raw.strip()
    return int(value) if value.isdigit() else default


class AnnualReader(ResearchReader):
    """年別RA/SEだけを固定snapshotと一意rowidで一巡する。"""

    def preflight(self):
        """研究reader権限、年別固定版、既存keyset索引を確認する。"""
        identity = self._small("annual:identity", "SELECT DB_NAME() db,IS_ROLEMEMBER('db_owner') [owner],IS_SRVROLEMEMBER('sysadmin') [admin],IS_ROLEMEMBER('db_datawriter') writer")[0]
        if identity != {"db": "jra_unified", "owner": 0, "admin": 0, "writer": 0}:
            raise ResearchError("annual_identity_failed", 3)
        for permission in ("SELECT", "INSERT", "UPDATE", "DELETE", "ALTER", "CONTROL"):
            row = self._small("annual:permission", "SELECT HAS_PERMS_BY_NAME(N'raw.year_raw_records','OBJECT',?) permitted", (permission,))[0]
            if row["permitted"] != int(permission == "SELECT"):
                raise ResearchError("annual_permission_failed", 3)
        sources = self._small("annual:sources", "SELECT d.source_key,s.source_snapshot_id,s.status FROM ops.source_snapshot s JOIN ops.source_database d ON d.source_database_id=s.source_database_id WHERE d.source_key LIKE N'jv-results-%' ORDER BY d.source_key")
        if sources != [{"source_key": f"jv-results-{y}", "source_snapshot_id": y - 1999, "status": "verified"} for y in range(2003, 2027)]:
            raise ResearchError("annual_sources_failed", 3)
        indexes = self._small("annual:index", "SELECT i.name,i.is_unique,c.name column_name,ic.key_ordinal FROM sys.indexes i JOIN sys.index_columns ic ON ic.object_id=i.object_id AND ic.index_id=i.index_id JOIN sys.columns c ON c.object_id=ic.object_id AND c.column_id=ic.column_id WHERE i.object_id=OBJECT_ID(N'raw.year_raw_records') AND i.is_disabled=0 AND i.is_hypothetical=0 AND i.has_filter=0 AND ic.key_ordinal>0 ORDER BY i.index_id,ic.key_ordinal")
        grouped = defaultdict(list)
        for row in indexes:
            if row["is_unique"]:
                grouped[row["name"]].append(row["column_name"])
        if ["__migration_source_snapshot_id", "__migration_source_rowid"] not in grouped.values():
            raise ResearchError("annual_index_failed", 3)
        sdk = next(Path("D:/develop/jra-van-data/tools/jra-van-sdk").glob("**/JVData_Struct.cs"))
        self.report = {"identity": identity, "sources": sources, "indexes": indexes,
                       "sdk_layout_sha256": hashlib.sha256(sdk.read_bytes()).hexdigest(), "read_consistency": "fixed_sources_chunked"}
        return self.report

    def year(self, year):
        """1年の本文を検証して最終版候補を保持し、同順位版の衝突を記録する。"""
        races, audit, stream = {}, Counter(), hashlib.sha256()
        last, total = 0, 0
        while True:
            sql = "SELECT TOP (5000) __migration_source_rowid,record_type,race_key,is_valid,sha256,payload FROM raw.year_raw_records WHERE __migration_source_snapshot_id=? AND __migration_source_rowid>? AND record_type IN (N'RA',N'SE') ORDER BY __migration_source_rowid"
            with self._cursor("annual:keyset", sql, (year - 1999, last)) as cursor:
                rows = cursor.fetchmany(5000)
            if not rows:
                break
            for rowid, kind, key, valid, sha, payload in rows:
                if rowid <= last:
                    raise ResearchError("annual_rowid_order_failed", 4)
                last, total = rowid, total + 1
                self.scan_rows["annual_all"] = self.scan_rows.get("annual_all", 0) + 1
                if total > 500000 or self.scan_rows["annual_all"] > 4000000:
                    raise ResearchError("annual_row_cap", 4)
                audit["scanned_" + kind] += 1
                if not valid or not key or not key.startswith(str(year)) or key[:8] > "20260531":
                    audit["invalid_or_outside_scope"] += 1
                    continue
                raw = bytes(payload)
                if (len(raw) != {"RA": 1272, "SE": 555}[kind] or raw[:2] != kind.encode() or not raw.endswith(b"\r\n")
                        or hashlib.sha256(raw).hexdigest() != sha.lower() or (raw[11:21] + raw[25:27]).decode("ascii") != key):
                    raise ResearchError("annual_body_contract_failed", 4, year=year)
                stream.update((str(rowid) + ":" + sha + "\n").encode())
                race = races.setdefault(key, {"RA": None, "SE": {}, "conflict": False})
                slot = "RA" if kind == "RA" else f"{number(raw[28:30]):02d}"
                destination = race if kind == "RA" else race["SE"]
                version = (raw[3:11], raw[2:3])
                before = destination.get(slot)
                if before is None or version > before[0]:
                    destination[slot] = (version, sha, raw)
                elif version == before[0] and sha != before[1]:
                    race["conflict"] = True
                    audit["conflicting_versions"] += 1
            check_memory(2147483648)
        return races, {**audit, "input_digest": stream.hexdigest()}


def parse_race(key, source):
    """RA/SEをSDK定義で解析し、一意な正常平地競走だけを返す。"""
    if source["RA"] is None or source["conflict"]:
        return None, "missing_RA_or_conflicting_version"
    ra = source["RA"][2]
    track, distance = number(ra[705:707]), number(ra[697:701])
    if not 10 <= track <= 29 or not "01" <= key[8:10] <= "10":
        return None, "non_flat_or_non_JRA"
    runners = []
    for _, _, se in source["SE"].values():
        rank, horse_id = number(se[334:336]), se[30:40].decode("ascii")
        if se[331:332] != b"0" or not horse_id.isdigit() or int(horse_id) == 0 or rank < 1:
            return None, "abnormal_or_missing_identity"
        corners = [number(se[o:o + 2]) for o in (351, 353, 355, 357)]
        corner = next((v for v in reversed(corners) if v > 0), None)
        closing = number(se[390:393]) / 10
        runners.append({"horse_no": f"{number(se[28:30]):02d}", "horse_id": horse_id, "rank": rank,
                        "closing": closing if 5 < closing < 100 else None, "corner": corner,
                        "frame": number(se[27:28]), "age": number(se[82:84]), "weight": number(se[288:291]) / 10,
                        "jockey": se[296:301].decode("ascii"), "trainer": se[90:98].decode("cp932", errors="replace").strip()})
    n = len(runners)
    if n < 8 or sorted(r["rank"] for r in runners) != list(range(1, n + 1)) or len({r["horse_id"] for r in runners}) != n:
        return None, "small_or_non_unique_ranks"
    for runner in runners:
        if runner["corner"] is not None and not 1 <= runner["corner"] <= n:
            runner["corner"] = None
    runners.sort(key=lambda r: r["horse_no"])
    laps = [number(ra[890 + i * 3:893 + i * 3]) / 10 for i in range(25)]
    laps = [v for v in laps if v > 0]
    eligible = distance % 200 == 0 and len(laps) == distance // 200 and len(laps) >= 6 and all(8 < v < 20 for v in laps)
    pace = float(np.mean(laps[:3]) - np.mean(laps[-3:])) if eligible else None
    late = float(np.mean(laps[-6:-3]) - np.mean(laps[-3:])) if eligible else None
    day = f"{key[:4]}-{key[4:6]}-{key[6:8]}"
    return {"key": key, "day": day, "ordinal": date.fromisoformat(day).toordinal(), "surface": int(track >= 23),
            "distance": distance, "course": int(key[8:10]), "condition": ra[634:637].decode("ascii"),
            "pace": pace, "late": late, "runners": runners}, None


class HorseState:
    """馬ID単位の過去集計と直近3走だけを保持する。"""

    __slots__ = ("n", "strength", "wins", "top3", "last", "conditions")

    def __init__(self):
        """結果を見ていない状態と小さな履歴を用意する。"""
        self.n = self.strength = self.wins = self.top3 = 0
        self.last = deque(maxlen=3)
        self.conditions = {}

    def form(self, key, prior):
        """条件別の強さを生涯平均へ5走分だけ縮約する。"""
        count, total = self.conditions.get(key, (0, 0))
        return (total + 5 * prior) / (count + 5) - prior


class States:
    """過去日だけの馬/騎手/厩舎統計から48特徴を作る。"""

    def __init__(self):
        """空の履歴と集計器を用意する。"""
        self.horses, self.jockeys, self.trainers = {}, {}, {}

    def vector(self, runner, race, density):
        """現レースの公開属性と過去統計だけで有限な特徴を返す。"""
        h = self.horses.get(runner["horse_id"])
        if h is None:
            h = HorseState()
        strength = (h.strength + 2.5) / (h.n + 5)
        past = list(h.last)
        last = past[-1] if past else None
        best = max(past, key=lambda v: v[1]) if past else None
        mean = lambda i, default: float(np.mean([p[i] for p in past if p[i] is not None])) if any(p[i] is not None for p in past) else default
        closing = last[2] if last and last[2] is not None else .5
        corner = last[3] if last and last[3] is not None else .5
        pace = last[5] if last and last[5] is not None else 0
        drop = best[1] - last[1] if last else 0
        days = race["ordinal"] - last[0] if last else 365
        if last and days <= 0:
            raise ResearchError("same_day_history_leak", 5)
        restored = bool(best and last and drop >= .15 and best[6] == race["surface"] and abs(best[7] - race["distance"]) <= 200
                        and (last[6] != race["surface"] or abs(last[7] - race["distance"]) > 200))
        def actor(table, name):
            """騎手/厩舎の過去3着内率を20走で縮約する。"""
            n, top = table.get(name, (0, 0))
            return (top + 4) / (n + 20)
        month = int(race["day"][5:7])
        x = [strength, (h.wins + 1) / (h.n + 12), (h.top3 + 3) / (h.n + 12), min(math.log1p(h.n) / 5, 2),
             min(days / 365, 2), last[1] if last else .5, mean(1, .5), closing, mean(2, .5),
             last[4] if last and last[4] is not None else 0, mean(4, 0), corner, pace / 5,
             max(0, -pace * (.5 - corner)) / 5, best[1] if best else .5, drop,
             h.form(("d", race["distance"] // 400), strength), h.form(("s", race["surface"]), strength),
             h.form(("c", race["course"]), strength), (race["distance"] - last[7]) / 2000 if last else 0,
             int(bool(last and last[6] == race["surface"])), int(bool(last and last[8] == race["course"])), int(restored),
             (last[10] or 0) / 5 if last else 0, len(race["runners"]) / 18, runner["age"] / 10, runner["weight"] / 60,
             runner["frame"] / 8, min(abs(days - 35) / 365, 2), density, density * (.5 - corner), race["distance"] / 4000,
             race["surface"], int(race["condition"] == "703"), int(race["condition"] == "999"),
             math.sin(2 * math.pi * month / 12), math.cos(2 * math.pi * month / 12),
             actor(self.jockeys, runner["jockey"]), actor(self.trainers, runner["trainer"]),
             h.form(("q", (month - 1) // 3), strength), (runner["weight"] - last[9]) / 10 if last else 0,
             closing * (last[4] if last and last[4] is not None else 0),
             mean(1, .5) * max(0, race["distance"] - 2000) / 2000 * max(0, -pace) / 5,
             int(not last or last[2] is None), int(not last or last[3] is None), int(not last or last[5] is None),
             int(h.n == 0), strength / math.sqrt(h.n + 1)]
        value = np.clip(np.asarray(x, dtype=np.float64), -3, 3)
        if value.shape != (48,) or not np.isfinite(value).all():
            raise ResearchError("theory_features_invalid", 5)
        return value

    def update(self, race):
        """その日の特徴生成が全て終わってから結果を履歴へ加える。"""
        n, month = len(race["runners"]), int(race["day"][5:7])
        closings = sorted(r["closing"] for r in race["runners"] if r["closing"] is not None)
        for runner in race["runners"]:
            h = self.horses.setdefault(runner["horse_id"], HorseState())
            rank = runner["rank"]
            strength = 1 - (rank - 1) / (n - 1)
            closing = 1 - closings.index(runner["closing"]) / max(len(closings) - 1, 1) if runner["closing"] is not None else None
            corner = runner["corner"] / n if runner["corner"] is not None and 1 <= runner["corner"] <= n else None
            gain = corner - rank / n if corner is not None else None
            h.n += 1
            h.strength += strength
            h.wins += int(rank == 1)
            h.top3 += int(rank <= 3)
            h.last.append((race["ordinal"], strength, closing, corner, gain, race["pace"], race["surface"], race["distance"], race["course"], runner["weight"], race["late"]))
            for key in (("d", race["distance"] // 400), ("s", race["surface"]), ("c", race["course"]), ("q", (month - 1) // 3)):
                count, total = h.conditions.get(key, (0, 0))
                h.conditions[key] = (count + 1, total + strength)
            for table, name in ((self.jockeys, runner["jockey"]), (self.trainers, runner["trainer"])):
                count, top = table.get(name, (0, 0))
                table[name] = (count + 1, top + int(rank <= 3))


def prepare_annual(artifacts, reference, reuse=None):
    """全24年を一巡し、19モデルを低メモリ学習して必要日の特徴だけ保持する。"""
    ids = {r["race_key"] for r in reference["race_diagnostics"]}
    models, columns, counts = {}, {}, Counter()
    for name, _, extra, _, _ in THEORIES:
        models[name] = SGDClassifier(**CONFIG["sgd"])
        columns[name] = sorted(set(BASIC + extra))
    if reuse is not None:
        models, columns = reuse["models"], reuse["columns"]
        counts.update(reuse["trained_rows"])
    states, target, year_reports = States(), {}, {}
    buffer_x, buffer_y, buffer_weight, buffer_year = [], [], [], []
    feature_checks = 0

    def flush():
        """1万馬行以下の共通batchから各仮説の列だけを学習する。"""
        if not buffer_x:
            return
        x, y, weights, years = np.asarray(buffer_x), np.asarray(buffer_y), np.asarray(buffer_weight), np.asarray(buffer_year)
        for name, _, _, floor, _ in THEORIES:
            included = years >= floor
            if included.any():
                models[name].partial_fit(x[included][:, columns[name]], y[included], classes=np.asarray([0, 1]), sample_weight=weights[included])
                counts[name] += int(included.sum())
        buffer_x.clear(); buffer_y.clear(); buffer_weight.clear(); buffer_year.clear()

    config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
    with AnnualReader(config) as reader:
        artifacts.write_json("preflight.json", reader.preflight())
        for year in range(2003, 2027):
            raw, audit = reader.year(year)
            grouped = defaultdict(list)
            for key in sorted(raw):
                race, reason = parse_race(key, raw[key])
                if reason:
                    audit[reason] = audit.get(reason, 0) + 1
                else:
                    grouped[race["day"]].append(race)
            del raw
            report = Counter()
            for day, races in sorted(grouped.items()):
                for race in races:
                    report["usable_races"] += 1
                    report["runner_rows"] += len(race["runners"])
                    report["pace_observed_races"] += int(race["pace"] is not None)
                    report["corner_observed"] += sum(r["corner"] is not None for r in race["runners"])
                    report["closing_observed"] += sum(r["closing"] is not None for r in race["runners"])
                    if day <= CONFIG["train_through"]:
                        report["training_races"] += 1
                    need = (reuse is None and day <= CONFIG["train_through"]) or day.startswith("2025-10") or race["key"] in ids
                    if not need:
                        continue
                    density = sum(bool((h := states.horses.get(r["horse_id"])) and h.last and h.last[-1][3] is not None and h.last[-1][3] <= .3) for r in race["runners"]) / len(race["runners"])
                    public = [{k: r[k] for k in ("horse_id", "horse_no", "frame", "age", "weight", "jockey", "trainer")} for r in race["runners"]]
                    x = np.asarray([states.vector(r, race, density) for r in public])
                    changed = states.vector({**public[0], "rank": 999, "closing": 99, "corner": 99}, race, density)
                    if not np.array_equal(changed, x[0]):
                        raise ResearchError("theory_result_feature_leak", 5)
                    feature_checks += 1
                    if day <= CONFIG["train_through"]:
                        n = len(public)
                        buffer_x.extend(x)
                        buffer_y.extend(int(r["rank"] == 1) for r in race["runners"])
                        buffer_weight.extend(.5 if r["rank"] == 1 else .5 / (n - 1) for r in race["runners"])
                        buffer_year.extend([year] * n)
                        if len(buffer_x) >= 8000:
                            flush()
                    else:
                        target[race["key"]] = {"x": x, "runners": race["runners"], "race": {k: race[k] for k in ("key", "day", "surface", "distance", "course")}}
                for race in races:
                    states.update(race)
            flush()
            year_reports[str(year)] = {**audit, **report}
            artifacts.write_json("coverage.json", {"stage": "annual_training", "years": year_reports, "trained_rows": dict(counts), "feature_result_checks": feature_checks})
            print(json.dumps({"stage": "annual_training", "year": year, "races": report["usable_races"], "trained_rows_T01": counts["T01"], "private_state_horses": len(states.horses)}), flush=True)
            del grouped
            gc.collect()
            check_memory(2147483648)
        queries = reader.query_metrics
    coverage = {"years": year_reports, "trained_rows": dict(counts), "feature_result_checks": feature_checks,
                "query_count": len(queries), "input_digest": digest({y: v["input_digest"] for y, v in year_reports.items()})}
    del states
    return models, columns, target, coverage


def market_records(target, reference, coverage):
    """必要日のSQL31市場を読み、年別原文の馬ID/着順/ロスターを照合する。"""
    expected = {r["race_key"] for r in reference["race_diagnostics"]}
    days = sorted({value["race"]["day"] for key, value in target.items() if key in expected or value["race"]["day"].startswith("2025-10")})
    records, excluded, batch_digests = [], [], []
    config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
    empty = base.history._build_history_states([])
    with previous.ExperimentMarketReader(config) as reader:
        for offset in range(0, len(days), 4):
            races, rowsets = reader.selected(days[offset:offset + 4])
            converted, missing = base.sql_races(races, rowsets, [], state_provider=lambda _: empty)
            excluded.extend(missing)
            entry_ids = {(r["race_key"], r["horse_no"]): r["horse_id"] for r in rowsets["history.entries"]}
            batch_digests.append(reader.report["input_digest"])
            for data in converted:
                key, day = data["race_id"], data["race_date"]
                if key not in expected and not day.startswith("2025-10"):
                    continue
                native = target.get(key)
                if native is None:
                    excluded.append({"race_key": key, "reason": "annual_native_missing"})
                    continue
                native_rows = native["runners"]
                rank = data["result"]["ranks_by_horse"]
                if (set(rank) != {r["horse_no"] for r in native_rows}
                        or any(rank[r["horse_no"]] != r["rank"] or entry_ids.get((key, r["horse_no"])) != r["horse_id"] for r in native_rows)):
                    excluded.append({"race_key": key, "reason": "native_market_identity_or_result_mismatch"})
                    continue
                prices = {tuple(sorted((p["horse_no_1"], p["horse_no_2"]), key=int)): p["odds"] for p in data["inputs"]["odds"]["T-30m"]["quinella"]["pairs"]}
                pairs = list(combinations([r["horse_no"] for r in native_rows], 2))
                q = np.asarray([1 / prices[p] for p in pairs]); q /= q.sum()
                payouts = {tuple(sorted((p["horse_no_1"], p["horse_no_2"]), key=int)): p["payout"] for p in data["result"]["quinella_payout_per_100_yen"]}
                label = np.asarray([float(p in payouts) for p in pairs])
                if label.sum() != 1:
                    excluded.append({"race_key": key, "reason": "non_unique_quinella_target"})
                    continue
                period = "calibration" if day.startswith("2025-10") else previous.split(day)
                records.append({"race_key": key, "race_date": day, "period": period, "venue": data["race"]["course"],
                                "x": native["x"], "keys": pairs, "market": q, "prices": np.asarray([prices[p] for p in pairs]),
                                "target": label, "payouts": payouts})
    selected = {r["race_key"] for r in records if r["period"] != "calibration"}
    for key in sorted(expected - selected):
        if not any(e["race_key"] == key for e in excluded):
            excluded.append({"race_key": key, "reason": "annual_native_missing"})
    coverage.update(market_digest=digest(batch_digests), adopted_by_split=dict(Counter(r["period"] for r in records)), excluded=excluded,
                    reference_races=len(expected), common_evaluation_races=len(selected))
    if not selected or not any(r["period"] == "calibration" for r in records):
        raise ResearchError("twenty_empty_market_split", 4)
    return records


def pair_probability(record, model, columns):
    """馬の値からレース内支持を作り、PL上位2頭確率を返す。"""
    raw = expit(np.clip(model.decision_function(record["x"][:, columns]), -8, 8))
    p = raw / raw.sum()
    values = np.asarray([p[i] * p[j] * (1 / (1 - p[i]) + 1 / (1 - p[j])) for i, j in combinations(range(len(p)), 2)])
    return values / values.sum()


def mix(market, prediction, alpha):
    """市場と内容予測を固定校正係数で対数混合する。"""
    if alpha == 0:
        return market.copy()
    return softmax((1 - alpha) * np.log(market) + alpha * np.log(np.maximum(prediction, 1e-15)))


def evaluate(artifacts, models, columns, records, coverage, reference):
    """校正・開発で選択を固定した後、20案全てを同じ再使用評価へ通す。"""
    calibration = [r for r in records if r["period"] == "calibration"]
    development = [r for r in records if r["period"] == "evaluation_2025"]
    evaluated = sorted((r for r in records if r["period"] != "calibration"), key=lambda r: (r["race_date"], r["race_key"]))
    if not calibration or not development or not any(r["period"] == "evaluation_late" for r in evaluated):
        raise ResearchError("twenty_empty_evaluation_split", 4)
    alphas, development_loss, calibration_losses = {}, {}, {}
    for name, _, _, _, _ in THEORIES:
        predictions = [pair_probability(r, models[name], columns[name]) for r in calibration]
        def loss(alpha):
            """校正期間だけのレース平均対数損失を計算する。"""
            return float(np.mean([-r["target"] @ np.log(np.maximum(mix(r["market"], p, alpha), 1e-15)) for r, p in zip(calibration, predictions)]))
        result = minimize_scalar(loss, bounds=(0, 1), method="bounded")
        options = [(loss(0), 0.), (loss(1), 1.), (float(result.fun), float(result.x))]
        best = min(options, key=lambda item: (item[0], item[1]))
        alphas[name] = best[1]
        calibration_losses[name] = {"market_alpha0": options[0][0], "content_alpha1": options[1][0],
                                    "interior_alpha": float(result.x), "interior_loss": float(result.fun),
                                    "selected_alpha": best[1], "selected_loss": best[0]}
        development_loss[name] = float(np.mean([-r["target"] @ np.log(np.maximum(mix(r["market"], pair_probability(r, models[name], columns[name]), alphas[name]), 1e-15)) for r in development]))
    selected = sorted(development_loss, key=lambda k: (development_loss[k], k))[:3]
    frozen = {"selected": selected, "criterion": "development_logloss_then_id", "weights": "equal_1/3",
              "development_loss": development_loss, "frozen_before_current_run_2026_scoring": datetime.now(timezone.utc).isoformat(),
              "not_independent_unseen_evaluation": True}
    artifacts.write_json("metrics.json", {"stage": "selection_frozen", "selection": frozen, "alphas": alphas, "calibration_losses": calibration_losses})
    path = artifacts.path / "models.joblib"
    joblib.dump({"models": models, "columns": columns, "alphas": alphas, "selection": frozen, "features": FEATURES, "config": CONFIG}, path)
    loaded = joblib.load(path)
    results_rows, tickets, reload_checks = [], defaultdict(list), 0

    def prediction_rows():
        """全ペアの追加保存を避け、選択したペアと評価だけを保存する。"""
        nonlocal reload_checks
        for record in evaluated:
            probabilities, raw_losses = {}, {}
            for name, _, _, _, _ in THEORIES:
                a = pair_probability(record, models[name], columns[name])
                b = pair_probability(record, loaded["models"][name], loaded["columns"][name])
                if not np.array_equal(a, b):
                    raise ResearchError("twenty_saved_prediction_changed", 5)
                probabilities[name] = mix(record["market"], a, alphas[name])
                raw_losses[name] = float(-record["target"] @ np.log(np.maximum(a, 1e-15)))
                reload_checks += 1
            probabilities["T20"] = record["market"].copy() if all(alphas[k] == 0 for k in selected) else np.mean([probabilities[k] for k in selected], axis=0)
            probabilities["market"] = record["market"]
            row = {"race_key": record["race_key"], "race_date": record["race_date"], "period": record["period"], "loss": {}, "brier": {}, "raw_content_loss": raw_losses}
            for name, q in probabilities.items():
                if not np.isfinite(q).all() or not np.isclose(q.sum(), 1):
                    raise ResearchError("twenty_invalid_probability", 5)
                row["loss"][name] = float(-record["target"] @ np.log(np.maximum(q, 1e-15)))
                row["brier"][name] = float(np.mean((q - record["target"]) ** 2))
                valid = np.flatnonzero((record["prices"] >= 4) & (record["prices"] <= 80) & (q >= .015))
                choices = sorted(valid, key=lambda i: (-round(float(q[i] * record["prices"][i]), 12), int(i)))[:1]
                for index in choices:
                    pair = record["keys"][index]
                    ticket = {"kind": "quinella", "stake_yen": 600, "payout_yen": record["payouts"].get(pair, 0) * 6,
                              "quoted_odds": float(record["prices"][index]), "expected_multiplier": float(q[index] * record["prices"][index])}
                    tickets[name].append({**ticket, "race_key": record["race_key"], "race_date": record["race_date"], "period": record["period"]})
                    yield {"race_key": record["race_key"], "race_date": record["race_date"], "venue": record["venue"], "variant": name,
                           "split": record["period"], "horses": list(pair), "probability": float(q[index]), "target": int(record["target"][index]), "ticket": ticket}
            results_rows.append(row)
    prediction_hash = artifacts.write_predictions(prediction_rows())
    results = {}
    names = [t[0] for t in THEORIES] + ["T20", "market"]
    for name in names:
        results[name] = {}
        for period in ("evaluation_2025", "evaluation_early", "evaluation_late", "all", "reused_2026"):
            included = lambda r: period == "all" or r["period"] == period or period == "reused_2026" and r["period"] in ("evaluation_early", "evaluation_late")
            rows = [r for r in results_rows if included(r)]
            results[name][period] = {**previous.summary([t for t in tickets[name] if included(t)]),
                                     "logloss": float(np.mean([r["loss"][name] for r in rows])), "brier": float(np.mean([r["brier"][name] for r in rows])),
                                     "raw_content_logloss": float(np.mean([r["raw_content_loss"][name] for r in rows])) if name in alphas else None}
    ledger = []
    for name, title, _, floor, criticism in THEORIES + [("T20", "開発期間で選ぶ3案等重み合成", [], 2003, "選択に使った開発成績は楽観的。2026年も既参照の探索評価")]:
        actual = results[name]["reused_2026"]
        control = results["market"]["reused_2026"]
        market_only = alphas[name] == 0 if name in alphas else all(alphas[k] == 0 for k in selected)
        ledger.append({"round": int(name[1:]), "id": name, "hypothesis": title, "criticism": criticism,
                       "training_from_year": floor, "trained_horse_rows": coverage["trained_rows"].get(name),
                       "features": [FEATURES[i] for i in columns[name]] if name != "T20" else {"ensemble": selected},
                       "market_mix_alpha": alphas.get(name), "reused_2026": actual,
                       "loss_difference_vs_market": actual["logloss"] - control["logloss"],
                       "market_only_after_calibration": market_only,
                       "decision": "校正で内容重み0。今回の形では市場への追加情報を支持できず、購入の差として解釈しない" if market_only else "研究比較のみ・運用不採用。独立検証と収益安定性は未確認"})
    raw_comparisons = {}
    rows_2026 = [r for r in results_rows if r["period"] in ("evaluation_early", "evaluation_late")]
    for name in alphas:
        grouped = defaultdict(list)
        for row in rows_2026:
            grouped[row["race_date"]].append(row["raw_content_loss"][name] - row["raw_content_loss"]["T01"])
        daily = np.asarray([(sum(v), len(v)) for _, v in sorted(grouped.items())])
        rng = np.random.default_rng(42)
        sampled = daily[rng.integers(0, len(daily), size=(1000, len(daily)))].sum(axis=1)
        raw_comparisons[name] = {"raw_logloss_difference_vs_T01": float(daily[:, 0].sum() / daily[:, 1].sum()),
                                 "day_bootstrap_95": np.quantile(sampled[:, 0] / sampled[:, 1], [.025, .975]).tolist(),
                                 "posthoc_diagnostic_not_model_selection": True}
    common = {r["race_key"] for r in evaluated}
    reference_matched = {}
    for name in ("history", "full", "no_pace"):
        rows = [r for r in reference["race_diagnostics"] if r["race_key"] in common]
        rt = [{**t, "race_date": r["race_date"]} for r in rows for t in r["tickets"][name]]
        reference_matched[name] = {**previous.summary(rt), "logloss": float(np.mean([r["logloss"][name] for r in rows]))}
    metrics = {"status": "passed", "stage": "jv_tipster_twenty", "theory_count_completed": len(ledger), "live_adopted": False,
               "unseen_test": False, "sqlite_used": False, "input_guard_enforced": True, "coverage": coverage,
               "selection": frozen, "alphas": alphas, "calibration_losses": calibration_losses, "results": results, "ledger": ledger,
               "matched_prior_models": reference_matched, "raw_content_comparisons": raw_comparisons,
               "race_metrics": results_rows, "reload_score_checks": reload_checks,
               "model_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    artifacts.write_json("coverage.json", coverage)
    artifacts.write_json("metrics.json", metrics)
    if len(ledger) != 20 or any(count <= 0 for count in coverage["trained_rows"].values()):
        raise ResearchError("twenty_not_complete", 5)
    artifacts.finish(overall_complete=False, stage=metrics["stage"], theory_count_completed=20, predictions_sha256=prediction_hash,
                     metrics_sha256=digest(metrics))
    return {"run_id": artifacts.run_id, "completed": 20, "reference_common_races": len(common),
            "results_2026": {name: results[name]["reused_2026"] for name in names}, "selected": selected}


def execute_twenty(reuse_run=None):
    """固定20回の研究を旧入力拒否下で実行し、失敗も非秘密証跡へ保存する。"""
    base.install_input_guard()
    artifacts = RunArtifacts(CONFIG, "tipster-theory-twenty")
    print(json.dumps({"stage": "starting", "run_id": artifacts.run_id}), flush=True)
    try:
        reference = json.loads((REFERENCE / "metrics.json").read_text(encoding="utf-8"))
        reuse = None
        if reuse_run is not None:
            from .jra_research_artifacts import existing_run
            old_path = existing_run(reuse_run)
            old = json.loads((old_path / "metrics.json").read_text(encoding="utf-8"))
            raw_models = (old_path / "models.joblib").read_bytes()
            if old["status"] != "passed" or hashlib.sha256(raw_models).hexdigest() != old["model_sha256"]:
                raise ResearchError("twenty_reuse_model_mismatch", 3)
            reuse = joblib.load(old_path / "models.joblib")
            if reuse["config"]["protocol"] != CONFIG["protocol"] or reuse["features"] != FEATURES:
                raise ResearchError("twenty_reuse_contract_mismatch", 3)
            reuse["trained_rows"] = old["coverage"]["trained_rows"]
            artifacts.manifest["trained_models_reused_from"] = reuse_run
            artifacts.manifest["reused_models_sha256"] = old["model_sha256"]
        with threadpool_limits(limits=1):
            models, columns, target, coverage = prepare_annual(artifacts, reference, reuse)
            if reuse_run is not None:
                if coverage["input_digest"] != old["coverage"]["input_digest"]:
                    raise ResearchError("twenty_reuse_input_changed", 4)
                coverage["trained_models_reused_from"] = reuse_run
                coverage["new_fits"] = 0
            records = market_records(target, reference, coverage)
            del target
            gc.collect()
            return evaluate(artifacts, models, columns, records, coverage, reference)
    except ResearchError as error:
        artifacts.fail(error)
        raise
    except Exception as error:
        frames = [{"file": Path(f.filename).name, "line": f.lineno, "function": f.name} for f in traceback.extract_tb(error.__traceback__)]
        failure = ResearchError("tipster_twenty_failed", 4, error_type=type(error).__name__, frames=frames)
        artifacts.fail(failure)
        raise failure from None
