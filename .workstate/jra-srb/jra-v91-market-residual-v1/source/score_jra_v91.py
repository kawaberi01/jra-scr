"""Score a supplied as-of JSON race without API/DB access or result reads."""
import argparse
import json
from pathlib import Path

import joblib

from jra_v91_model import forecast


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--race-json", type=Path, required=True)
    args = parser.parse_args()
    artifact = joblib.load(args.model)
    race = json.loads(args.race_json.read_text(encoding="utf-8"))
    if race["race_date"] <= artifact["training_max_date"]:
        raise ValueError("Use frozen historical evaluation for dates covered by training; final artifact is for future shadow predictions.")
    print(json.dumps(forecast(artifact, race), ensure_ascii=False, indent=2))
