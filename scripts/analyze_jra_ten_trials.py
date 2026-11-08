"""Describe frozen tickets by race attributes; never changes model or policy."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path

import numpy as np

from evaluate_jra_ten_trials import load_records, summarize, write_json
from jra_ten_trials_model import EXPERIMENTS, pick_ticket


def run(root, data_root):
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    records, _ = load_records(data_root, report["protocol"]["excluded_months"])
    by_id = {r["race_id"]: r for r in records}
    stages = defaultdict(lambda: defaultdict(list))
    with gzip.open(root / "predictions.jsonl.gz", "rt", encoding="utf-8") as stream:
        for line in stream:
            item = json.loads(line)
            if item["stage"] not in ("development", "exploratory"):
                continue
            key = item["trial"]
            kind = EXPERIMENTS[key][1]
            r = by_id[item["race_id"]]
            r = r if kind == "win" else r["pair"]
            assert item["keys"] == r["keys"]
            s = {"probability": np.asarray(item["probability"]), "projected_return": np.asarray(item["projected_return"])}
            policy = report["trials"][key]["development"]["policy"]
            ticket = pick_ticket(r, s, kind, policy)
            if ticket:
                ticket.update(payout=int(r["payout"][ticket["index"]]), popularity=int(r["popularity"][ticket["index"]]))
            stages[key][item["stage"]].append({**{k: r[k] for k in ("race_id", "race_date", "surface", "distance", "course")},
                                               "loss": 0., "ticket": ticket})
    output = {"status": "posthoc_descriptive_only_no_policy_change", "trials": {}}
    for key, data in stages.items():
        trial = {}
        for stage, rows in data.items():
            groups = {}
            for row in rows:
                row["distance_band"] = "sprint" if row["distance"] <= 1400 else "middle" if row["distance"] <= 2000 else "stayer"
            for dimension in ("surface", "distance_band", "course"):
                groups[dimension] = {}
                for value in sorted({r[dimension] for r in rows}):
                    subset = [r for r in rows if r[dimension] == value]
                    result = summarize(subset, bootstrap=False)
                    result.pop("mean_race_log_loss")  # This file summarizes tickets, not probabilities.
                    groups[dimension][value] = result
            tickets = [r["ticket"] for r in rows if r["ticket"]]
            winners = [t for t in tickets if t["payout"] > 0]
            trial[stage] = {"groups": groups,
                            "median_odds_t30": float(np.median([t["odds_t30"] for t in tickets])) if tickets else None,
                            "winner_final_return_over_t30_indicative_return":
                                sum(t["payout"] for t in winners) / sum(100 * t["odds_t30"] for t in winners) if winners else None,
                            "winning_tickets": len(winners)}
        output["trials"][key] = trial
    write_json(root / "characteristics.json", output)
    print(json.dumps({"trials_described": len(output["trials"]), "policies_changed": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(".workstate/jra-srb/jra-ten-trials-nosummer-v1"))
    parser.add_argument("--data-root", type=Path, default=Path("data/training/jra_o1o2_asof_v1"))
    args = parser.parse_args()
    run(args.root, args.data_root)
