"""Future race scoring using the second batch's fixed policy."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import joblib
from threadpoolctl import threadpool_limits

from evaluate_jra_o1o2_movement import sha256
from jra_ten_trials_model import pick_ticket
from jra_second_ten_model import EXPERIMENTS, prepare, score_suite


def forecast(suite, race, trial=None):
    if race["race_date"] <= suite["training_max_date"]:
        raise ValueError("race date must be later than training")
    r = prepare(race)
    trial = trial or suite["development_champion"]
    scores = score_suite(suite, r)
    if trial not in scores:
        return {"race_id": r["race_id"], "trial": trial, "status": "missing_market", "ticket": None}
    kind = EXPERIMENTS[trial][1]
    record = r if kind == "win" else r["pair"]
    score = scores[trial]
    return {"race_id": r["race_id"], "trial": trial, "race_date": r["race_date"],
            "created_at": datetime.now(timezone.utc).isoformat(), "status": "research_only",
            "decision_time": "T-30m", "bet_type": kind,
            "candidate_gate_passed": suite["candidate_gate_passed"][trial],
            "ticket": pick_ticket(record, score, kind, suite["fixed_policy"]),
            "probabilities": dict(zip(record["keys"], score["probability"].tolist(), strict=True)),
            "probability_note": score.get("probability_note")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--race-json", type=Path, required=True)
    parser.add_argument("--trial", choices=list(EXPERIMENTS))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        result = forecast(joblib.load(args.model), json.loads(args.race_json.read_text(encoding="utf-8")), args.trial)
    result.update(model_sha256=sha256(args.model), input_sha256=sha256(args.race_json))
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(text)
