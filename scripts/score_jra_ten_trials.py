"""Score a future non-summer race with a frozen development-selected policy."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import joblib
from threadpoolctl import threadpool_limits

from evaluate_jra_o1o2_movement import sha256
from jra_ten_trials_model import EXPERIMENTS, pick_ticket, prepare, score_suite


def forecast(suite, race, trial=None):
    if race["race_date"] <= suite["training_max_date"]:
        raise ValueError("race date must be later than the final training date")
    record = prepare(race)
    trial = trial or suite["development_champion"]
    scores = score_suite(suite, record)
    if trial not in scores:
        return {"race_id": race["race_id"], "trial": trial, "status": "missing_market", "ticket": None}
    kind = EXPERIMENTS[trial][1]
    data = record if kind == "win" else record["pair"]
    score = scores[trial]
    return {"race_id": race["race_id"], "race_date": race["race_date"], "trial": trial,
            "status": "research_candidate_only", "created_at": datetime.now(timezone.utc).isoformat(),
            "decision_time": "T-30m", "bet_type": kind, "policy": suite["policies"][trial],
            "historical_candidate_gate_passed": suite["candidate_gate_passed"][trial],
            "ticket": pick_ticket(data, score, kind, suite["policies"][trial]),
            "probabilities": dict(zip(data["keys"], score["probability"].tolist(), strict=True))}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--race-json", type=Path, required=True)
    parser.add_argument("--trial", choices=list(EXPERIMENTS))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        result = forecast(joblib.load(args.model), json.loads(args.race_json.read_text(encoding="utf-8")), args.trial)
    result["model_sha256"] = sha256(args.model)
    result["input_sha256"] = sha256(args.race_json)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(text)
