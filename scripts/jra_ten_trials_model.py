"""Ten fixed T-30m hypotheses, including win and quinella prediction.

Prediction functions have no access to results. Labels are attached by the evaluator.
"""
from __future__ import annotations

from datetime import date, timedelta
import math

import numpy as np
from scipy.optimize import minimize
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from evaluate_jra_o1o2_movement import history_features
from jra_v91_model import features, fit, numeric_market, predict

EXPERIMENTS = {
    "V92": ("basic", "win", "旧basicの再学習"),
    "V93": ("graph", "win", "単勝市場と馬連グラフの残差"),
    "V94": ("nonlinear", "win", "履歴と市場の非線形関係"),
    "V95": ("trees", "win", "複数の決定木と市場確率の混合"),
    "V96": ("agreement", "win", "3モデルが同時に支持する候補"),
    "V97": ("surface", "win", "芝・ダート別の補正"),
    "V98": ("recent", "win", "直近365日の傾向を重視"),
    "V99": ("settlement", "win", "勝った場合の最終払戻倍率を予測"),
    "V100": ("quinella_pl", "quinella", "単勝勝率から馬連確率を導出"),
    "V101": ("quinella_direct", "quinella", "馬連市場の残差を組合せ単位で学習"),
}
GROUPS = ("all", "turf", "dirt", "sprint", "middle", "stayer", "favorite", "middle_popularity", "outsider")
THRESHOLDS = (1.0, 1.1, 1.2, 1.35)


def prepare(race):
    """Build features exclusively from the T-30m inputs."""
    r = features(race)
    runners = {str(h["horse_no"]): h for h in race["inputs"]["runners"]}
    n = len(r["keys"])
    basic = np.asarray([(np.log(r["price"][i]), r["market"][i], *history_features(runners[k]))
                        for i, k in enumerate(r["keys"])])
    context = np.tile([float(race["race"]["surface"] == "turf"),
                       float(race["race"]["distance"]) / 2000, n / 18], (n, 1))
    order = np.argsort(r["price"], kind="stable")
    popularity = np.empty(n, dtype=int)
    popularity[order] = np.arange(1, n + 1)
    r.update(race_id=race["race_id"], race_date=race["race_date"], surface=race["race"]["surface"],
             distance=int(race["race"]["distance"]), course=race["race"]["course"],
             basic=basic, ml=np.column_stack((basic, r["x"], context)), popularity=popularity)
    q = numeric_market(race["inputs"]["odds"]["T-30m"].get("quinella"), "quinella")
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    if r["o2_complete"]:
        pair_price = np.array([q[(r["keys"][i], r["keys"][j])] for i, j in pairs])
        pair_p = 1 / pair_price
        pair_p /= pair_p.sum()
        order = np.argsort(pair_price, kind="stable")
        popularity = np.empty(len(pairs), dtype=int)
        popularity[order] = np.arange(1, len(pairs) + 1)
        r["pair"] = {"indices": pairs, "keys": [f"{r['keys'][i]}-{r['keys'][j]}" for i, j in pairs],
                     "price": pair_price, "market": pair_p, "popularity": popularity,
                     **{k: r[k] for k in ("race_id", "race_date", "surface", "distance", "course")}}
    else:
        r["pair"] = None
    return r


def normalize(p):
    p = np.maximum(np.asarray(p, dtype=float), 1e-12)
    return p / p.sum()


def pair_probability(probabilities, indices):
    p = probabilities
    return normalize([p[i] * p[j] * (1 / max(1 - p[i], 1e-12) + 1 / max(1 - p[j], 1e-12))
                      for i, j in indices])


def direct_pair_design(r):
    q = r["pair"]
    if q is None:
        return None
    implied = pair_probability(r["market"], q["indices"])
    rows = []
    for k, (i, j) in enumerate(q["indices"]):
        a, b = r["x"][i], r["x"][j]
        rows.append([np.log(implied[k] / q["market"][k]), np.log(q["market"][k]),
                     np.log(r["market"][i] / r["market"][j]) ** 2,
                     *(a[1:11] + b[1:11]), *np.abs(a[1:4] - b[1:4]),
                     *(a[-3:] + b[-3:])])
    x = np.asarray(rows)
    x -= q["market"] @ x
    return x


def fit_pair(records):
    valid = [r for r in records if r["pair"] is not None and "target" in r["pair"]]
    xs = [direct_pair_design(r) for r in valid]
    sizes = [len(x) for x in xs]
    starts = np.cumsum([0] + sizes[:-1])
    group = np.repeat(np.arange(len(valid)), sizes)
    x = np.concatenate(xs)
    scale = np.maximum(np.std(x, axis=0), 1e-5)
    x /= scale
    y = np.concatenate([r["pair"]["target"] for r in valid])
    offset = np.log(np.concatenate([r["pair"]["market"] for r in valid]))
    def objective(beta):
        z = offset + x @ beta
        maxima = np.maximum.reduceat(z, starts)
        e = np.exp(z - maxima[group])
        sums = np.add.reduceat(e, starts)
        p = e / sums[group]
        loss = (np.sum(maxima + np.log(sums)) - y @ z) / len(valid) + .1 * (beta @ beta) / 2
        gradient = x.T @ (p - y) / len(valid) + .1 * beta
        return loss, gradient
    result = minimize(objective, np.zeros(x.shape[1]), method="L-BFGS-B", jac=True,
                      options={"maxiter": 400, "ftol": 1e-10, "gtol": 1e-7})
    if not result.success:
        raise RuntimeError(f"pair optimizer: {result.message}")
    return {"scale": scale, "coef": result.x, "training_races": len(valid), "optimizer_success": True}


def fit_suite(records, excluded_months, as_of=None):
    """Each fit is supplied strictly earlier races by the evaluation driver."""
    if any(int(r["race_date"][5:7]) in excluded_months for r in records):
        raise ValueError("summer race leaked into training")
    x = np.concatenate([r["ml"] for r in records])
    labels = np.concatenate([r["target"] > 0 for r in records])
    weights = np.concatenate([np.full(len(r["keys"]), 1 / len(r["keys"])) for r in records])
    weights *= len(weights) / weights.sum()
    basic = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500, C=1.0))
    basic.fit(np.concatenate([r["basic"] for r in records]), labels)
    graph = fit(records, "graph", .1)
    nonlinear = HistGradientBoostingClassifier(max_iter=120, learning_rate=.04, max_leaf_nodes=7,
                                               min_samples_leaf=100, l2_regularization=10,
                                               early_stopping=False, random_state=92)
    nonlinear.fit(x, labels, sample_weight=weights)
    trees = ExtraTreesClassifier(n_estimators=160, max_depth=8, min_samples_leaf=80,
                                  max_features=.8, n_jobs=1, random_state=92)
    trees.fit(x, labels, sample_weight=weights)
    surfaces = {s: fit([r for r in records if r["surface"] == s], "graph", .3)
                for s in ("turf", "dirt") if sum(r["surface"] == s for r in records) >= 200}
    as_of = as_of or (date.fromisoformat(records[-1]["race_date"]) + timedelta(days=1)).isoformat()
    if any(r["race_date"] >= as_of for r in records):
        raise ValueError("training races must precede prediction period")
    recent_start = (date.fromisoformat(as_of) - timedelta(days=365)).isoformat()
    recent = [r for r in records if r["race_date"] >= recent_start]
    recent_model = fit(recent, "graph", .3) if len(recent) >= 400 else graph
    # The payout ratio is a supervised target, never a prediction-time input.
    mask = labels.astype(bool)
    ratio = np.concatenate([r["payout"] / 100 / r["price"] for r in records])[mask]
    settlement = HistGradientBoostingRegressor(max_iter=80, learning_rate=.05, max_leaf_nodes=5,
                                               min_samples_leaf=40, l2_regularization=10,
                                               early_stopping=False, random_state=92)
    settlement.fit(x[mask], np.log(np.maximum(ratio, .01)))
    smearing = float(np.mean(np.exp(np.log(np.maximum(ratio, .01)) - settlement.predict(x[mask]))))
    return {"basic": basic, "graph": graph, "nonlinear": nonlinear, "trees": trees,
            "surface": surfaces, "recent": recent_model, "recent_training_races": len(recent),
            "settlement": settlement, "settlement_smearing": smearing,
            "pair_direct": fit_pair(records), "training_races": len(records),
            "training_max_date": records[-1]["race_date"], "training_as_of": as_of, "excluded_months": list(excluded_months),
            "status": "research_candidate_only", "decision_time": "T-30m"}


def score_suite(suite, r):
    if int(r["race_date"][5:7]) in suite["excluded_months"]:
        raise ValueError("summer race excluded from this model")
    basic = normalize(suite["basic"].predict_proba(r["basic"])[:, 1])
    graph = predict(suite["graph"], r)
    nonlinear = normalize(suite["nonlinear"].predict_proba(r["ml"])[:, 1])
    tree = .5 * r["market"] + .5 * normalize(suite["trees"].predict_proba(r["ml"])[:, 1])
    surface_model = suite["surface"].get(r["surface"], suite["graph"])
    surface = .5 * graph + .5 * predict(surface_model, r)
    recent = .5 * graph + .5 * predict(suite["recent"], r)
    average = (basic + graph + nonlinear) / 3
    conservative = np.minimum(np.minimum(basic, graph), nonlinear)
    ratio = np.clip(np.exp(suite["settlement"].predict(r["ml"])) * suite["settlement_smearing"], .5, 1.5)
    output = {}
    for key, p in (("V92", basic), ("V93", graph), ("V94", nonlinear), ("V95", tree),
                   ("V96", average), ("V97", surface), ("V98", recent), ("V99", graph)):
        score = conservative if key == "V96" else p
        effective_price = r["price"] * ratio if key == "V99" else r["price"]
        output[key] = {"probability": p, "projected_return": score * effective_price}
    if r["pair"] is not None:
        q = r["pair"]
        p = pair_probability(graph, q["indices"])
        output["V100"] = {"probability": p, "projected_return": p * q["price"]}
        model = suite["pair_direct"]
        z = np.log(q["market"]) + (direct_pair_design(r) / model["scale"]) @ model["coef"]
        p = normalize(np.exp(z - z.max()))
        output["V101"] = {"probability": p, "projected_return": p * q["price"]}
    return output


def group_mask(record, group):
    n = len(record["keys"])
    if group == "all":
        return np.ones(n, dtype=bool)
    if group in ("turf", "dirt"):
        return np.full(n, record["surface"] == group)
    if group in ("sprint", "middle", "stayer"):
        d = record["distance"]
        return np.full(n, (d <= 1400 if group == "sprint" else 1400 < d <= 2000 if group == "middle" else d > 2000))
    p = record["popularity"]
    if group == "favorite":
        return p <= 3
    if group == "middle_popularity":
        return (p >= 4) & (p <= 6)
    if group == "outsider":
        return p >= 7
    raise ValueError(group)


def pick_ticket(record, score, kind, policy):
    lo, hi = (2, 30) if kind == "win" else (3, 100)
    eligible = group_mask(record, policy["group"]) & (record["price"] >= lo) & (record["price"] <= hi)
    candidates = np.where(eligible & (score["projected_return"] >= policy["threshold"]))[0]
    if not len(candidates):
        return None
    index = int(candidates[np.argmax(score["projected_return"][candidates])])
    return {"key": record["keys"][index], "index": index,
            "probability": float(score["probability"][index]), "odds_t30": float(record["price"][index]),
            "projected_return": float(score["projected_return"][index])}
