"""V91: race-wise market-offset probabilities. No result access in prediction."""
from __future__ import annotations

from datetime import datetime, timedelta
import math

import numpy as np
from scipy.optimize import minimize
from scipy.special import logsumexp

FORM_NAMES = (
    "horse_win", "horse_top3", "horse_strength", "course_top3", "surface_top3",
    "distance_top3", "jockey_win", "jockey_top3", "trainer_win", "trainer_top3",
    "log_starts", "days_since_last", "age",
)
GRAPH_NAMES = ("o2_log_marginal_residual", "o2_opponent_residual", "o2_entropy_residual")


def numeric_market(snapshot, kind):
    out = {}
    for row in (snapshot or {}).get("horses" if kind == "win" else "pairs", []):
        try:
            price = float(row["odds"])
        except (KeyError, TypeError, ValueError):
            continue
        if row.get("status") != "numeric" or not math.isfinite(price) or price < 1:
            continue
        key = str(row["horse_no"]) if kind == "win" else tuple(sorted(
            (str(row["horse_no_1"]), str(row["horse_no_2"])), key=int))
        if key in out:
            raise ValueError(f"duplicate market key: {key}")
        out[key] = price
    return out


def validate_time(race, snapshot):
    cutoff = datetime.fromisoformat(race["race"]["start_at"]) - timedelta(minutes=30)
    if datetime.fromisoformat(snapshot["announced_at"]) > cutoff:
        raise ValueError("odds announced after T-30m")
    history_cutoff = datetime.fromisoformat(race["inputs"]["history_as_of"])
    if history_cutoff.date().isoformat() != race["race_date"] or history_cutoff.time().isoformat() != "00:00:00":
        raise ValueError("unexpected history cutoff")


def form(runner):
    h = runner["history_features"]
    def rate(key, count, neutral):
        n = max(0.0, math.expm1(float(h[count])))
        return (float(h[key]) - neutral) * n / (n + 5.0)
    values = [
        rate("horse_win_rate", "horse_log_starts", .08),
        rate("horse_top3_rate", "horse_log_starts", .25),
        rate("horse_finish_strength", "horse_log_starts", .5),
        rate("horse_course_top3_rate", "horse_course_log_starts", .25),
        rate("horse_surface_top3_rate", "horse_surface_log_starts", .25),
        rate("horse_distance_top3_rate", "horse_distance_log_starts", .25),
        rate("jockey_win_rate", "jockey_log_starts", .08),
        rate("jockey_top3_rate", "jockey_log_starts", .25),
        rate("trainer_win_rate", "trainer_log_starts", .08),
        rate("trainer_top3_rate", "trainer_log_starts", .25),
        float(h["horse_log_starts"]), float(h["days_since_last_scaled"]), float(h["age_scaled"]),
    ]
    if not np.isfinite(values).all():
        raise ValueError("nonfinite history features")
    return values


def features(race):
    """Read only race metadata, runners, history and T-30m odds."""
    snapshot = race["inputs"]["odds"]["T-30m"]
    validate_time(race, snapshot["win"])
    win = numeric_market(snapshot["win"], "win")
    runners = {str(r["horse_no"]): r for r in race["inputs"]["runners"]}
    entries = {str(row["horse_no"]): row for row in snapshot["win"]["horses"]}
    extras = set(runners) - set(win)
    explicit_nonnumeric = {k for k, row in entries.items() if row.get("status") != "numeric"}
    unmatched = {k for k in extras if k not in explicit_nonnumeric}
    # A historical card can spell a cancelled runner's number as "取消".
    # Require nonnumeric O1 evidence; never consult post-race runner status or ranks.
    covered_extras = (all(not k.isdigit() for k in unmatched)
                      and len(unmatched) <= len(explicit_nonnumeric - set(runners)))
    if (len(runners) != len(race["inputs"]["runners"]) or not set(win).issubset(runners)
            or not covered_extras or len(win) < 2):
        raise ValueError("incomplete runner market")
    keys = sorted(win, key=int)
    price = np.asarray([win[k] for k in keys])
    p = 1 / price
    p /= p.sum()
    logp = np.log(p)
    history = np.asarray([form(runners[k]) for k in keys])
    history -= p @ history
    # Race-relative history interactions allow market disagreement to vary by context.
    turf = float(race["race"].get("surface") == "turf")
    sprint = float(int(race["race"].get("distance") or 0) <= 1400)
    centered_logp = logp - p @ logp
    basic = np.column_stack((centered_logp, history, history[:, :3] * turf,
                             history[:, :3] * sprint))
    pairs = numeric_market(snapshot.get("quinella"), "quinella")
    n = len(keys)
    expected = {(keys[i], keys[j]) for i in range(n) for j in range(i + 1, n)}
    valid = expected.issubset(pairs)
    graph = np.zeros((n, 3))
    if valid:
        validate_time(race, snapshot["quinella"])
        actual = np.zeros((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                actual[i, j] = actual[j, i] = 1 / pairs[(keys[i], keys[j])]
        actual /= actual.sum() / 2
        # Unordered top-two probability under a Plackett-Luce market strength model.
        implied = np.outer(p, p) * (1 / (1 - p)[:, None] + 1 / (1 - p)[None, :])
        np.fill_diagonal(implied, 0)
        am, em = actual.sum(axis=1), implied.sum(axis=1)
        ac, ec = actual / am[:, None], implied / em[:, None]
        def entropy(q):
            return -(q * np.log(np.maximum(q, 1e-12))).sum(axis=1)
        graph = np.column_stack((np.log(am / em), (ac - ec) @ logp,
                                 (entropy(ac) - entropy(ec)) / math.log(n)))
        graph -= p @ graph
    names = ["market_temperature_delta", *FORM_NAMES,
             *[f"turf_{k}" for k in FORM_NAMES[:3]], *[f"sprint_{k}" for k in FORM_NAMES[:3]],
             *GRAPH_NAMES]
    return {"keys": keys, "price": price, "market": p, "x": np.column_stack((basic, graph)),
            "feature_names": names, "o2_complete": valid, "unscored_card_keys": sorted(extras)}


def columns(variant):
    if variant == "temperature":
        return [0]
    if variant == "form":
        return list(range(1 + len(FORM_NAMES) + 6))
    if variant == "graph":
        return list(range(1 + len(FORM_NAMES) + 6 + len(GRAPH_NAMES)))
    if variant == "market":
        return []
    raise ValueError(variant)


def fit(records, variant, penalty):
    cols = columns(variant)
    artifact = {"version": "V91", "variant": variant, "penalty": penalty, "columns": cols,
                "feature_names": records[0]["feature_names"], "decision_time": "T-30m",
                "status": "shadow_research_only"}
    if not cols:
        return {**artifact, "scale": np.array([]), "coef": np.array([]), "optimizer": "market"}
    starts = np.cumsum([0] + [len(r["keys"]) for r in records[:-1]])
    sizes = np.asarray([len(r["keys"]) for r in records])
    group = np.repeat(np.arange(len(records)), sizes)
    x = np.concatenate([r["x"][:, cols] for r in records])
    scale = np.maximum(np.std(x, axis=0), 1e-5)
    x = x / scale
    offset = np.log(np.concatenate([r["market"] for r in records]))
    y = np.concatenate([r["target"] for r in records])
    count = len(records)
    def objective(beta):
        z = offset + x @ beta
        maxima = np.maximum.reduceat(z, starts)
        e = np.exp(z - maxima[group])
        sums = np.add.reduceat(e, starts)
        prob = e / sums[group]
        loss = ((maxima + np.log(sums)).sum() - y @ z) / count
        return loss + penalty * (beta @ beta) / 2, x.T @ (prob - y) / count + penalty * beta
    result = minimize(objective, np.zeros(len(cols)), jac=True, method="L-BFGS-B",
                      options={"maxiter": 400, "ftol": 1e-11, "gtol": 1e-7})
    if not result.success:
        raise RuntimeError(f"optimizer failed: {result.message}")
    return {**artifact, "scale": scale, "coef": result.x,
            "optimizer": {"success": True, "iterations": int(result.nit), "loss": float(result.fun)}}


def predict(artifact, record):
    z = np.log(record["market"])
    if artifact["columns"]:
        z = z + (record["x"][:, artifact["columns"]] / artifact["scale"]) @ artifact["coef"]
    return np.exp(z - logsumexp(z))


def forecast(artifact, race):
    record = features(race)
    if artifact["feature_names"] != record["feature_names"]:
        raise ValueError("feature contract mismatch")
    p = predict(artifact, record)
    order = np.argsort(-p, kind="stable")
    return {"race_id": race["race_id"], "race_date": race["race_date"], "theory_version": "V91",
            "decision_time": "T-30m", "status": "shadow_research_only", "o2_complete": record["o2_complete"],
            "ranking": [{"horse_no": record["keys"][i], "win_probability": float(p[i]),
                         "odds_t30": float(record["price"][i]),
                         "projected_return_at_t30": float(p[i] * record["price"][i])} for i in order]}
