"""Second bounded batch: ten T-30m methods using existing JSONL fields only."""
from __future__ import annotations

from datetime import date, timedelta
import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import softmax
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.tree import DecisionTreeRegressor

from jra_ten_trials_model import prepare as previous_prepare, pair_probability, direct_pair_design, normalize

EXPERIMENTS = {
    "V102": ("enriched", "win", "既存履歴・斤量・性齢・クラスの相互作用"),
    "V103": ("top3", "win", "上位3着の段階的順位学習"),
    "V104": ("latent", "win", "馬連周辺支持からの潜在単勝支持"),
    "V105": ("boost", "win", "市場残差のレース単位ブースティング"),
    "V106": ("calibrated", "win", "時系列校正による過信の縮小"),
    "V107": ("uncertainty", "win", "開催日bootstrapによる不確実性割引"),
    "V108": ("direct_return", "win", "払戻倍率を直接学習"),
    "V109": ("settlement", "win", "払戻倍率の縮小推定"),
    "V110": ("rank_pair", "quinella", "上位3着学習から馬連確率"),
    "V111": ("direct_pair_return", "quinella", "馬連払戻の市場offset回帰"),
}
EXTRA_HISTORY = (
    "horse_has_history", "horse_course_log_starts", "horse_surface_log_starts", "horse_distance_log_starts",
    "jockey_log_starts", "trainer_log_starts", "weight_carried_scaled", "sex_female", "sex_gelding",
)
CONTEXT_KEYS = ("is_maiden", "is_newcomer", "is_open_or_stakes")


def latent_support(record):
    """Invert O2 top-two marginal shares by fixed-point scaling; no outcomes."""
    if record["pair"] is None:
        return record["market"].copy()
    q = record["pair"]
    target = np.zeros(len(record["keys"]))
    for (i, j), p in zip(q["indices"], q["market"], strict=True):
        target[i] += p / 2
        target[j] += p / 2
    p = record["market"].copy()
    for _ in range(80):
        denominator = np.maximum(1 - p, 1e-10)
        marginal = .5 * p * (1 + np.sum(p / denominator) - p / denominator)
        updated = normalize(p * target / np.maximum(marginal, 1e-12))
        next_p = .5 * p + .5 * updated
        if np.max(np.abs(next_p - p)) < 1e-10:
            p = next_p
            break
        p = next_p
    return normalize(p)


def augment(record, race):
    runners = {str(h["horse_no"]): h["history_features"] for h in race["inputs"]["runners"]}
    extra = np.asarray([[float(runners[k][name]) for name in EXTRA_HISTORY] for k in record["keys"]])
    context = np.asarray([[float(runners[k][name]) for name in CONTEXT_KEYS] for k in record["keys"]])
    if not np.isfinite(extra).all() or not np.isfinite(context).all():
        raise ValueError("nonfinite allowed history values")
    extra -= record["market"] @ extra
    # Race-common class terms affect race-relative ability only via interactions.
    interactions = np.column_stack([record["x"][:, 1:4] * context[:, i:i+1] for i in range(3)])
    weight_age = extra[:, 6] * record["x"][:, 13]
    design = np.column_stack((record["x"], extra, interactions, weight_age))
    record["enriched"] = design
    record["enriched_names"] = [*record["feature_names"], *EXTRA_HISTORY,
                                 *[f"{c}_form_{j}" for c in CONTEXT_KEYS for j in range(3)], "weight_age"]
    latent = latent_support(record)
    difference = np.log(latent / record["market"])
    difference -= record["market"] @ difference
    record["latent"] = np.column_stack((design, difference, difference * record["x"][:, 1]))
    record["boost_x"] = np.column_stack((record["ml"], extra, context, interactions, difference))
    record["latent_probability"] = latent
    return record


def prepare(race):
    return augment(previous_prepare(race), race)


def flatten(records, feature):
    sizes = [len(r["keys"]) for r in records]
    starts = np.cumsum([0] + sizes[:-1])
    group = np.repeat(np.arange(len(records)), sizes)
    return np.concatenate([r[feature] for r in records]), starts, group


def grouped_softmax(z, starts, group):
    maxima = np.maximum.reduceat(z, starts)
    e = np.exp(z - maxima[group])
    sums = np.add.reduceat(e, starts)
    return e / sums[group], maxima + np.log(sums)


def fit_choice(records, feature="enriched", weights=None, penalty=.1):
    x, starts, group = flatten(records, feature)
    scale = np.maximum(x.std(axis=0), 1e-5)
    x = x / scale
    offset = np.log(np.concatenate([r["market"] for r in records]))
    y = np.concatenate([r["target"] for r in records])
    w = np.ones(len(records)) if weights is None else np.asarray(weights, dtype=float)
    if w.sum() <= 0:
        raise ValueError("empty training weights")
    row_w = w[group]
    def objective(beta):
        z = offset + x @ beta
        p, logden = grouped_softmax(z, starts, group)
        loss = (w @ logden - (y * row_w) @ z) / w.sum() + penalty * (beta @ beta) / 2
        gradient = x.T @ ((p-y)*row_w) / w.sum() + penalty * beta
        return loss, gradient
    result = minimize(objective, np.zeros(x.shape[1]), method="L-BFGS-B", jac=True,
                      options={"maxiter": 400, "ftol": 1e-10, "gtol": 1e-7})
    if not result.success:
        raise RuntimeError(str(result.message))
    return {"feature": feature, "scale": scale, "coef": result.x, "optimizer_success": True}


def choice(model, r):
    return softmax(np.log(r["market"]) + (r[model["feature"]] / model["scale"]) @ model["coef"])


def ranking_stages(records):
    """Ranks are training labels only; handle ties by fractional choice targets."""
    stages, weights = [], []
    for r in records:
        ranks = r["training_ranks"]
        levels = sorted({int(v) for v in ranks if 0 < v <= 3})
        race_stages = []
        for rank in levels:
            # Non-finishers (<=0) remain alternatives to the observed top-three finishers.
            mask = (ranks >= rank) | (ranks <= 0)
            if mask.sum() < 2:
                continue
            target = (ranks[mask] == rank).astype(float)
            target /= target.sum()
            race_stages.append({"keys": [k for k, keep in zip(r["keys"], mask, strict=True) if keep],
                                "enriched": r["enriched"][mask], "market": normalize(r["market"][mask]),
                                "target": target})
        stages.extend(race_stages)
        weights.extend([1 / len(race_stages)] * len(race_stages))
    return stages, weights


def fit_boost(records, rounds=100):
    x, starts, group = flatten(records, "boost_x")
    y = np.concatenate([r["target"] for r in records])
    z = np.log(np.concatenate([r["market"] for r in records]))
    trees = []
    for step in range(rounds):
        p, _ = grouped_softmax(z, starts, group)
        hessian = p * (1-p) + .02
        target = np.clip((y-p) / hessian, -2, 2)
        tree = DecisionTreeRegressor(max_leaf_nodes=6, min_samples_leaf=150, random_state=102+step)
        tree.fit(x, target, sample_weight=hessian)
        z += .05 * tree.predict(x)
        trees.append(tree)
    return {"trees": trees, "learning_rate": .05}


def boost_delta(model, r):
    return sum((model["learning_rate"] * tree.predict(r["boost_x"]) for tree in model["trees"]),
               start=np.zeros(len(r["keys"])))


def chronological_calibration_split(records):
    dates = sorted({r["race_date"] for r in records})
    boundary = dates[max(1, int(len(dates) * .75))]
    earlier = [r for r in records if r["race_date"] < boundary]
    later = [r for r in records if r["race_date"] >= boundary]
    return earlier, later, boundary


def fit_calibrated(records):
    earlier, later, boundary = chronological_calibration_split(records)
    model = fit_boost(earlier)
    deltas = [boost_delta(model, r) for r in later]
    def loss(alpha):
        values = [-r["target"] @ np.log(np.maximum(softmax(np.log(r["market"]) + alpha * d), 1e-15))
                  for r, d in zip(later, deltas, strict=True)]
        return float(np.mean(values)) + .01 * alpha**2
    result = minimize_scalar(loss, bounds=(0, 1.5), method="bounded")
    if not result.success:
        raise RuntimeError("calibration failed")
    return {"boost": model, "alpha": float(result.x), "calibration_from": boundary,
            "fit_max_date": earlier[-1]["race_date"], "calibration_races": len(later)}


def settlement_group(r):
    return np.searchsorted([3, 6, 12], r["price"], side="right") + 4 * int(r["surface"] == "turf")


def fit_settlement(records):
    sums = np.zeros(8)
    counts = np.zeros(8)
    for r in records:
        groups = settlement_group(r)
        for i in np.where(r["payout"] > 0)[0]:
            sums[groups[i]] += r["payout"][i] / 100 / r["price"][i]
            counts[groups[i]] += 1
    # Prior ratio 1 with 30 winner observations; do not assume favorable price drift.
    return {"ratios": np.minimum(1., (sums + 30) / (counts + 30)), "counts": counts}


def pair_return_design(r):
    q = r["pair"]
    latent_pair = pair_probability(r["latent_probability"], q["indices"])
    return np.column_stack((direct_pair_design(r), np.log(latent_pair / q["market"])))


def fit_pair_return(records):
    records = [r for r in records if r["pair"] is not None]
    x = np.concatenate([pair_return_design(r) for r in records])
    scale = np.maximum(x.std(axis=0), 1e-5)
    x = np.column_stack((np.ones(len(x)), np.clip(x / scale, -8, 8)))
    y = np.concatenate([r["pair"]["payout"] / 100 for r in records])
    offset = np.log(np.concatenate([r["pair"]["market"] * r["pair"]["price"] for r in records]))
    w = np.concatenate([np.full(len(r["pair"]["keys"]), 1 / len(r["pair"]["keys"])) for r in records])
    penalty = np.r_[.01, np.full(x.shape[1]-1, 1.)]
    def objective(beta):
        z = offset + x @ beta
        mu = np.exp(z)
        return (w @ (mu-y*z) / w.sum() + np.sum(penalty*beta**2)/2,
                x.T @ (w*(mu-y)) / w.sum() + penalty*beta)
    result = minimize(objective, np.zeros(x.shape[1]), method="L-BFGS-B", jac=True,
                      bounds=[(-3, 3)]*x.shape[1], options={"maxiter": 400, "ftol": 1e-10})
    if not result.success:
        raise RuntimeError(f"pair return optimizer: {result.message}")
    return {"scale": scale, "coef": result.x, "optimizer_success": True}


def fit_suite(records, excluded_months=(6, 7, 8), as_of=None):
    as_of = as_of or (date.fromisoformat(records[-1]["race_date"])+timedelta(days=1)).isoformat()
    if any(r["race_date"] >= as_of or int(r["race_date"][5:7]) in excluded_months for r in records):
        raise ValueError("invalid training date or excluded summer race")
    enriched = fit_choice(records)
    stages, weights = ranking_stages(records)
    top3 = fit_choice(stages, weights=weights)
    latent = fit_choice(records, "latent")
    boost = fit_boost(records)
    calibrated = fit_calibrated(records)
    dates = sorted({r["race_date"] for r in records})
    positions = {d: i for i, d in enumerate(dates)}
    members = []
    for seed in range(5):
        counts = np.bincount(np.random.default_rng(102+seed).integers(0, len(dates), size=len(dates)), minlength=len(dates))
        members.append(fit_choice(records, weights=[counts[positions[r["race_date"]]] for r in records]))
    direct = HistGradientBoostingRegressor(loss="poisson", max_iter=120, max_leaf_nodes=7,
                                           min_samples_leaf=150, learning_rate=.04, l2_regularization=20,
                                           early_stopping=False, random_state=108)
    direct.fit(np.concatenate([r["boost_x"] for r in records]),
               np.concatenate([r["payout"] / 100 / r["price"] for r in records]))
    return {"enriched": enriched, "top3": top3, "latent": latent, "boost": boost,
            "calibrated": calibrated, "members": members, "direct_return": direct,
            "settlement": fit_settlement(records), "pair_return": fit_pair_return(records),
            "training_races": len(records), "training_max_date": records[-1]["race_date"],
            "training_as_of": as_of, "excluded_months": list(excluded_months),
            "status": "research_only", "decision_time": "T-30m",
            "enriched_feature_names": records[0]["enriched_names"]}


def score_suite(suite, r):
    if int(r["race_date"][5:7]) in suite["excluded_months"]:
        raise ValueError("summer race excluded")
    if suite["enriched_feature_names"] != r["enriched_names"]:
        raise ValueError("feature schema mismatch")
    base = choice(suite["enriched"], r)
    top3 = choice(suite["top3"], r)
    latent = choice(suite["latent"], r)
    boosted = softmax(np.log(r["market"]) + boost_delta(suite["boost"], r))
    calibration = suite["calibrated"]
    calibrated = softmax(np.log(r["market"]) + calibration["alpha"]*boost_delta(calibration["boost"], r))
    bag = np.asarray([choice(m, r) for m in suite["members"]])
    average = bag.mean(axis=0)
    lower = np.maximum(0., average-bag.std(axis=0, ddof=1))
    direct_return = np.maximum(0., suite["direct_return"].predict(r["boost_x"])) * r["price"]
    settlement = suite["settlement"]["ratios"][settlement_group(r)]
    out = {key: {"probability": p, "projected_return": p*r["price"]}
           for key, p in (("V102", base), ("V103", top3), ("V104", latent), ("V105", boosted),
                          ("V106", calibrated), ("V107", average), ("V108", base), ("V109", base))}
    out["V107"]["projected_return"] = lower*r["price"]
    out["V108"]["projected_return"] = direct_return
    out["V108"]["probability_note"] = "V102 probability shown separately; ticket score is direct expected settlement return."
    out["V109"]["projected_return"] = base*r["price"]*settlement
    if r["pair"] is not None:
        q = r["pair"]
        p = pair_probability(top3, q["indices"])
        out["V110"] = {"probability": p, "projected_return": p*q["price"]}
        model = suite["pair_return"]
        x = np.column_stack((np.ones(len(q["keys"])), np.clip(pair_return_design(r)/model["scale"], -8, 8)))
        expected = np.exp(np.log(q["market"]*q["price"])+x@model["coef"])
        out["V111"] = {"probability": q["market"], "projected_return": expected,
                       "probability_note": "O2 market probability shown separately; ticket score is direct expected settlement return."}
    return out
