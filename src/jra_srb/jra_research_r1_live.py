"""概要: 保存済みR1を明示指定し、発走前の馬連市場とSQL履歴から参考推論する。
作成日: 2026-10-18
入力: 対象日・場・R、ローカルAPI、研究reader設定、spec150保存モデル。
出力: 既存研究run内の参考確率・入力品質・検証結果。SQL保存は専用CLIで指定する。
実行例: uv run --frozen --extra ml python scripts/score_jra_r1_live.py --date 2026-10-18 --course kyoto --race-no 11
注意事項: 再学習・既定変更・原データ更新なし。API取得とSQL SELECTを行う。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import gc
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import re
from urllib.parse import urlparse

import httpx
import joblib
import numpy as np
from threadpoolctl import threadpool_limits

from .jra_research_artifacts import ROOT, RunArtifacts, existing_run
from .jra_research_contracts import ResearchError, digest, horse_number
from .jra_research_history import HistoryConfig
from .jra_research_resources import check_memory
from . import jra_research_tipster_twenty as native
from . import jra_research_tipster_residual as residual


BASELINE = "20261017T103959Z_3fb50c45b61d4ef29e906c148b5e07a8"
COURSES = {name: f"{index:02d}" for index, name in enumerate(
    ("sapporo", "hakodate", "fukushima", "niigata", "tokyo", "nakayama", "chukyo", "kyoto", "hanshin", "kokura"), 1)}
JST = timezone(timedelta(hours=9))
R1_COLUMNS = ["lifetime_strength", "lifetime_win", "lifetime_top3", "history_size", "age", "weight_carried", "frame", "no_history"]


def require(condition, reason):
    """入力・計算の不整合を秘密を含まない固定理由で停止する。"""
    if not condition:
        raise ResearchError(reason, 4)


def read_json(path):
    """保存JSONをUTF-8として読む。"""
    return json.loads(path.read_text(encoding="utf-8-sig"))


def numeric(text):
    """単位付き公開値から有限数値を取り出し、欠測は拒否する。"""
    match = re.search(r"\d+(?:\.\d+)?", str(text))
    require(match is not None, "r1_missing_numeric_attribute")
    value = float(match.group())
    require(math.isfinite(value), "r1_nonfinite_attribute")
    return value


def utc(value):
    """タイムゾーンのある観測時刻をUTCへ正規化する。"""
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(stamp.tzinfo is not None, "r1_naive_timestamp")
    return stamp.astimezone(timezone.utc)


def validate_card(card, day, course, race_no, now):
    """公式の完全な発走前カードを確認し、取消を除いた馬番順の出走馬を返す。"""
    expected = day.replace("-", "") + COURSES[course] + f"{race_no:02d}"
    require(card["race_id"] == expected, "r1_card_identity_mismatch")
    require(urlparse(card["source"]).hostname in {"www.jra.go.jp", "jra.go.jp", "sp.jra.jp", "own.jra.jp"}, "r1_nonofficial_card")
    status = card.get("data_status") or {}
    require(status.get("runner_set") == "complete" and status.get("source_kind") == "pre_race_card", "r1_incomplete_card")
    times = re.fullmatch(r"(\d{1,2})時(\d{2})分", card.get("start_time") or "")
    require(times is not None, "r1_missing_post_time")
    post = datetime.combine(date.fromisoformat(day), datetime.min.time(), JST).replace(hour=int(times[1]), minute=int(times[2]))
    require(now < post, "r1_race_already_started")
    require(timedelta(0) <= now - utc(card["fetched_at"]) <= timedelta(minutes=10), "r1_stale_card")
    runners = sorted((dict(r, horse_no=horse_number(r["horse_no"])) for r in card["runners"] if r.get("status") == "active"), key=lambda r: int(r["horse_no"]))
    require(8 <= len(runners) <= 18 and len({r["horse_no"] for r in runners}) == len(runners), "r1_invalid_active_roster")
    require(all(r.get("status") in {"active", "withdrawn", "excluded"} for r in card["runners"]), "r1_unknown_runner_status")
    for r in runners:
        require(1 <= numeric(r["frame_no"]) <= 8 and 2 <= numeric(r["sex_age"]) <= 15
                and 40 <= numeric(r["weight_carried"]) <= 70, "r1_invalid_runner_attribute")
    return runners, post


def market_record(card, runners, odds, x, now):
    """有効馬の全馬連価格を検証し、研究と同じ順序と正規化の入力を作る。"""
    require(odds["race_id"] == card["race_id"], "r1_odds_identity_mismatch")
    require(timedelta(0) <= now - utc(odds["fetched_at"]) <= timedelta(minutes=10), "r1_stale_odds")
    require(abs((utc(odds["fetched_at"]) - utc(card["fetched_at"])).total_seconds()) <= 300, "r1_card_odds_time_gap")
    keys = list(combinations([r["horse_no"] for r in runners], 2))
    active = {r["horse_no"] for r in runners}
    prices = {}
    for row in odds.get("odds", {}).get("quinella", []):
        pair = tuple(sorted((horse_number(n) for n in row["combination"]), key=int))
        require(len(pair) == 2 and pair[0] != pair[1], "r1_invalid_odds_pair")
        if not set(pair) <= active:
            continue
        require(pair not in prices, "r1_duplicate_odds_pair")
        value = float(row["odds"])
        require(math.isfinite(value) and value > 1, "r1_invalid_odds_price")
        prices[pair] = value
    require(set(prices) == set(keys), "r1_missing_active_pair_odds")
    values = np.asarray([prices[p] for p in keys])
    market = 1 / values
    market /= market.sum()
    require(x.shape == (len(runners), 48) and np.isfinite(x).all(), "r1_feature_shape")
    return {"keys": keys, "prices": values, "market": market, "x": x}


def load_model(baseline=BASELINE):
    """検証済みspec150からR1だけを読み、入力定義とモデルhashを照合する。"""
    path = existing_run(baseline)
    metrics, manifest = read_json(path / "metrics.json"), read_json(path / "manifest.json")
    require(manifest["status"] == "complete" and metrics["status"] == "passed", "r1_baseline_incomplete")
    require(digest(metrics) == manifest["metrics_sha256"], "r1_metrics_hash_changed")
    model_hash = hashlib.sha256((path / "models.joblib").read_bytes()).hexdigest()
    require(model_hash == metrics["model_sha256"], "r1_model_hash_changed")
    payload = joblib.load(path / "models.joblib")
    config, model = payload["config"], payload["models"]["R1"]
    names = [payload["feature_names"][i] for i in config["basic_indices"]]
    require(names == R1_COLUMNS and names == [native.FEATURES[i] for i in residual.BASIC], "r1_feature_contract_changed")
    require(model["variant"] == "R1" and model["scale"].shape == model["coef"].shape == (17,)
            and np.isfinite(model["coef"]).all() and np.isfinite(model["scale"]).all()
            and (model["scale"] > 0).all(), "r1_model_shape")
    return model, {"baseline_run": baseline, "model_sha256": model_hash, "trained_through": model["trained_through"], "feature_names": names}


class LiveAnnualReader(native.AnnualReader):
    """既存の年別固定SQL版を対象日未満まで読む当日用reader。"""

    def year_before(self, year, before):
        """研究時と同じ版選択で当日以降を除外し、原文をメモリだけに保持する。

        Args:
            year: 読取対象の西暦年。
            before: 対象レース日。これ以降の原文は解析・履歴更新に使用しない。
        Returns:
            tuple: 正規化前のRA/SE競走と、件数・内容digest・最終日。
        Raises:
            ResearchError: 本文・順序・件数・hashの不整合。
        """
        races, audit, stream = {}, Counter(), hashlib.sha256()
        last = total = 0
        latest = None
        while True:
            sql = "SELECT TOP (5000) __migration_source_rowid,record_type,race_key,is_valid,sha256,payload FROM raw.year_raw_records WHERE __migration_source_snapshot_id=? AND __migration_source_rowid>? AND record_type IN (N'RA',N'SE') ORDER BY __migration_source_rowid"
            with self._cursor("r1_live:annual_keyset", sql, (year - 1999, last)) as cursor:
                rows = cursor.fetchmany(5000)
            if not rows:
                break
            for rowid, kind, key, valid, sha, payload in rows:
                require(rowid > last, "r1_annual_rowid_order")
                last, total = rowid, total + 1
                require(total <= 500000, "r1_annual_row_cap")
                audit["scanned_" + kind] += 1
                if not valid or not key or not key.startswith(str(year)) or key[:8] >= before.replace("-", ""):
                    audit["outside_scope"] += 1
                    continue
                raw = bytes(payload)
                require(len(raw) == {"RA": 1272, "SE": 555}[kind] and raw[:2] == kind.encode()
                        and raw.endswith(b"\r\n") and hashlib.sha256(raw).hexdigest() == sha.lower()
                        and (raw[11:21] + raw[25:27]).decode("ascii") == key, "r1_annual_body_contract")
                latest = max(latest or key[:8], key[:8])
                stream.update((str(rowid) + ":" + sha + "\n").encode())
                race = races.setdefault(key, {"RA": None, "SE": {}, "conflict": False})
                slot = "RA" if kind == "RA" else f"{native.number(raw[28:30]):02d}"
                destination = race if kind == "RA" else race["SE"]
                version, old = (raw[3:11], raw[2:3]), destination.get(slot)
                if old is None or version > old[0]:
                    destination[slot] = (version, sha, raw)
                elif version == old[0] and sha != old[1]:
                    race["conflict"] = True
                    audit["conflicting_versions"] += 1
            check_memory(2147483648)
        return races, {**audit, "input_digest": stream.hexdigest(), "latest_raw_day": latest}


def build_history(runners, day, artifacts):
    """対象馬の生年以降のSQL履歴からR1に必要な生涯集計を再構築する。

    Notes:
        R1は馬単位の生涯集計と公開属性だけを参照する。騎手/厩舎の全期間
        集計を使用しないため、対象馬の生年前の走査を省略できる。
        正常8頭以上という研究時の履歴条件は維持する。
    """
    births = {r["horse_name"]: date.fromisoformat(day).year - int(numeric(r["sex_age"])) for r in runners}
    require(len(births) == len(runners), "r1_duplicate_active_horse_name")
    require(min(births.values()) >= 2003, "r1_history_before_supported_source")
    states, identities, years = native.States(), defaultdict(set), {}
    latest = {}
    config = HistoryConfig.load(ROOT / "configs/research/history_sql_v1.json")
    with LiveAnnualReader(config) as reader:
        artifacts.write_json("preflight.json", reader.preflight())
        for year in range(min(births.values()), date.fromisoformat(day).year + 1):
            raw, audit = reader.year_before(year, day)
            grouped = defaultdict(list)
            for key, source in sorted(raw.items()):
                for _, _, se in source["SE"].values():
                    name = se[40:76].decode("cp932").strip().replace("\u3000", "")
                    born = year - native.number(se[82:84])
                    if name in births and born == births[name]:
                        identities[name].add(se[30:40].decode("ascii"))
                race, reason = native.parse_race(key, source)
                if reason:
                    audit[reason] = audit.get(reason, 0) + 1
                else:
                    grouped[race["day"]].append(race)
            del raw
            for race_day, races in sorted(grouped.items()):
                require(race_day < day, "r1_history_contains_target_day")
                for race in races:
                    states.update(race)
                    audit["usable_races"] = audit.get("usable_races", 0) + 1
                    for r in race["runners"]:
                        latest[r["horse_id"]] = {"race_date": race_day, "race_key": race["key"], "rank": r["rank"], "field_size": len(race["runners"])}
            years[str(year)] = audit
            artifacts.write_json("coverage.json", {"stage": "r1_live_history", "years": years})
            print(json.dumps({"stage": "r1_live_history", "year": year, "usable_races": audit.get("usable_races", 0), "latest_raw_day": audit["latest_raw_day"]}), flush=True)
            del grouped
            gc.collect()
            check_memory(2147483648)
        queries = reader.query_metrics
    current, coverage = [], []
    for r in runners:
        matches = identities.get(r["horse_name"], set())
        require(len(matches) == 1, "r1_horse_identity_missing_or_ambiguous")
        horse_id = next(iter(matches))
        require(horse_id.isdigit() and len(horse_id) == 10, "r1_invalid_horse_id")
        h = states.horses.get(horse_id)
        require(h is not None and h.n > 0, "r1_no_eligible_horse_history")
        recent = [v for v in r.get("official_recent_races", []) if v.get("source_date") and v["source_date"] < day
                  and v.get("finish_rank") is not None and (v.get("field_size") or 0) >= 8]
        recent_day = max((v["source_date"] for v in recent), default=None)
        matched_latest = latest[horse_id]["race_date"]
        require(recent_day is None or matched_latest >= recent_day, "r1_history_stale_vs_official_card")
        current.append({"horse_no": r["horse_no"], "horse_id": horse_id, "age": int(numeric(r["sex_age"])),
                        "weight": numeric(r["weight_carried"]), "frame": int(numeric(r["frame_no"])),
                        "jockey": "", "trainer": ""})
        coverage.append({"horse_no": r["horse_no"], "horse_name": r["horse_name"], "horse_id": horse_id,
                         "history_starts": h.n, "latest_eligible_history": matched_latest,
                         "official_latest_eligible_day": recent_day, "identity_method": "exact_name_and_observed_birth_year"})
    audit = {"years": years, "horses": coverage, "queries": len(queries), "history_before": day,
             "history_scan_from_year": min(births.values()), "r1_uses_no_actor_features": True,
             "input_digest": digest({y: v["input_digest"] for y, v in years.items()}),
             "read_consistency": "fixed_sources_chunked", "sqlite_used": False}
    return states, current, audit


def score(model, record, runners):
    """保存R1と独立式を照合し、馬連参考順位・条件合致・2着内周辺値を返す。"""
    probabilities = residual.predict(model, record)
    x = record["x"][:, residual.BASIC]
    pairs = list(combinations(range(len(x)), 2))
    logq = np.log(record["market"])
    logq -= record["market"] @ logq
    features = np.asarray([[logq[k], *((x[i] + x[j]) / 2), *np.abs(x[i] - x[j])] for k, (i, j) in enumerate(pairs)])
    features -= record["market"] @ features
    z = np.log(record["market"]) + (features / model["scale"]) @ model["coef"]
    independent = np.exp(z - z.max())
    independent /= independent.sum()
    require(np.allclose(probabilities, independent, rtol=1e-12, atol=1e-14)
            and np.isfinite(probabilities).all() and np.isclose(probabilities.sum(), 1), "r1_independent_score_mismatch")
    dirty = {**record, "target": np.ones(len(probabilities)), "payouts": {"fake": 999}}
    require(np.array_equal(probabilities, residual.predict(model, dirty)), "r1_outcome_dependency")
    names = {r["horse_no"]: r["horse_name"] for r in runners}
    rows, marginal = [], {n: 0.0 for n in names}
    for index, pair in enumerate(record["keys"]):
        p, price, market = float(probabilities[index]), float(record["prices"][index]), float(record["market"][index])
        eligible = 4 <= price <= 80 and p >= .015 and p * price >= 1.05
        row = {"horses": list(pair), "horse_names": [names[n] for n in pair], "odds": price,
               "market_probability": market, "probability": p, "probability_delta": p - market,
               "expected_multiplier": p * price, "research_policy_eligible": eligible}
        rows.append(row)
        for n in pair:
            marginal[n] += p
    ordered = sorted(rows, key=lambda r: (-r["probability"], *map(int, r["horses"])))
    eligible = sorted((r for r in rows if r["research_policy_eligible"]), key=lambda r: (-round(r["expected_multiplier"], 12), *map(int, r["horses"])))
    require(np.isclose(sum(marginal.values()), 2), "r1_marginal_sum")
    return {"pairs": ordered, "research_policy_candidate": eligible[:1], "research_policy_status": "candidate" if eligible else "no_bet",
            "runner_top2_marginals": sorted(({"horse_no": n, "horse_name": names[n], "top2_probability": p} for n, p in marginal.items()), key=lambda r: (-r["top2_probability"], int(r["horse_no"]))),
            "verification": {"independent_softmax": True, "probability_sum": float(probabilities.sum()),
                             "marginal_sum": sum(marginal.values()), "outcome_independent": True}}


def execute(day, course, race_no, meeting_no, meeting_day, api_base="http://127.0.0.1:8000"):
    """当日参考推論を新規runへ保存し、既定モデルや学習成果物を変更しない。

    Raises:
        ResearchError: 入力期限・同定・履歴・モデル・推論に不整合。
    Notes:
        SQL結果は対象日より前の履歴だけ。対象結果のAPIは呼ばない。
        失敗はrunへ固定理由で保存し、依存する推論出力を採用しない。
    """
    date.fromisoformat(day)
    require(course in COURSES and 1 <= race_no <= 12, "r1_invalid_race_scope")
    model, provenance = load_model()
    require(model["trained_through"] < day, "r1_model_not_before_target")
    settings = {"protocol": "spec170-r1-live-reference-v1", "date": day, "course": course, "race_no": race_no,
                "meeting_no": meeting_no, "meeting_day": meeting_day, **provenance,
                "default_changed": False, "new_fits": 0, "live_adopted": False}
    artifacts = RunArtifacts(settings, "r1-live-reference")
    try:
        with httpx.Client(base_url=api_base, timeout=90) as client:
            response = client.get(f"/meetings/{day}/{course}/races/{race_no}/card")
            response.raise_for_status()
            card = response.json()
            runners, post = validate_card(card, day, course, race_no, datetime.now(timezone.utc))
            states, current, coverage = build_history(runners, day, artifacts)
            require(numeric(card["distance"].replace(",", "")) > 0 and card["surface"] in {"芝", "ダート"}, "r1_invalid_race_attribute")
            race = {"day": day, "ordinal": date.fromisoformat(day).toordinal(), "surface": int(card["surface"] == "ダート"),
                    "course": int(COURSES[course]), "distance": int(numeric(card["distance"].replace(",", ""))),
                    "condition": "999", "runners": current}
            x = residual.public_features(states, race)
            del states
            # 履歴構築後にカードを再確認し、価格取得と近い時点に揃える。
            response = client.get(f"/meetings/{day}/{course}/races/{race_no}/card")
            response.raise_for_status()
            fresh_card = response.json()
            fresh_runners, post = validate_card(fresh_card, day, course, race_no, datetime.now(timezone.utc))
            fields = ("horse_no", "horse_name", "sex_age", "frame_no", "weight_carried")
            require([{k: r[k] for k in fields} for r in runners] == [{k: r[k] for k in fields} for r in fresh_runners], "r1_roster_changed_during_history")
            card, runners = fresh_card, fresh_runners
            response = client.get(f"/jra/meetings/{day}/{course}/races/{race_no}/odds-summary",
                                  params={"meeting_no": meeting_no, "meeting_day": meeting_day, "bet_types": "quinella", "refresh": "true"})
            response.raise_for_status()
            odds = response.json()
        now = datetime.now(timezone.utc)
        require(now < post, "r1_race_started_during_preparation")
        record = market_record(card, runners, odds, x, now)
        with threadpool_limits(limits=1):
            prediction = score(model, record, runners)
        coverage.update({"active_runners": len(runners), "pairs": len(record["keys"]),
                         "excluded_horse_numbers": [r["horse_no"] for r in card["runners"] if r["status"] != "active"],
                         "card_sha256": digest(card), "odds_sha256": digest(odds)})
        output = {"status": "passed", "race_id": card["race_id"], "race_name": card["race_name"], "race_date": day,
                  "course": course, "race_no": race_no, "post_time": post.isoformat(), "scored_at": now.isoformat(),
                  "card_fetched_at": card["fetched_at"], "odds_fetched_at": odds["fetched_at"],
                  "minutes_to_post": (post - now).total_seconds() / 60, "odds_horizon": "current_observation_not_T30",
                  "model": provenance, "research_only": True, "default_changed": False, "outcome_read": False,
                  "new_fits": 0, "actual_tickets": [], "policy_stake_yen": 600,
                  "pre_race_snapshot": {"card": card, "odds_summary": odds}, **prediction}
        artifacts.write_json("coverage.json", coverage)
        artifacts.write_json("metrics.json", output)
        artifacts.finish(overall_complete=False, metrics_sha256=digest(output), outcome_read=False, default_changed=False,
                         verification_scope="R1_explicit_live_reference", model_sha256=provenance["model_sha256"])
        return {"run_id": artifacts.run_id, **output}
    except Exception as error:
        safe = error if isinstance(error, ResearchError) else ResearchError("r1_live_failed", 4, error_type=type(error).__name__)
        artifacts.fail(safe)
        safe.details["run_id"] = artifacts.run_id
        raise safe from None
