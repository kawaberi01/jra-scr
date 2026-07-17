"""Apply the frozen hidden-run rebound policy to untouched 2026 H1 races."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from evaluate_hidden_run_rebound import build_runner_rows, load_data, matrix, summarize


FROZEN_C = 0.1
FROZEN_PROBABILITY_THRESHOLD = 0.30


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/db/analysis.sqlite")
    parser.add_argument(
        "--output",
        default=".workstate/jra-srb/jra-hidden-rebound-validation/external-2026h1.json",
    )
    args = parser.parse_args()
    raw, wide, payouts = load_data(Path(args.db))
    rows = build_runner_rows(raw)
    train = [row for row in rows if row.race_date <= "2025-06-30"]
    external = [row for row in rows if "2026-01-01" <= row.race_date <= "2026-06-30"]
    if not train or not external:
        raise RuntimeError(f"insufficient rows: train={len(train)} external={len(external)}")

    model = make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        LogisticRegression(C=FROZEN_C, max_iter=500, random_state=0),
    )
    model.fit(matrix(train), np.asarray([row.rank <= 3 for row in train]))
    probabilities = model.predict_proba(matrix(external))[:, 1]
    metrics = summarize(
        external,
        probabilities,
        FROZEN_PROBABILITY_THRESHOLD,
        wide,
        payouts,
    )
    report = {
        "theory": "hidden-run-rebound-wide-v1",
        "policy_status": "frozen_before_external_evaluation",
        "training_period": "2025-01-01..2025-06-30",
        "external_period": "2026-01-01..2026-06-30",
        "C": FROZEN_C,
        "probability_threshold": FROZEN_PROBABILITY_THRESHOLD,
        "metrics": metrics,
        "pass": (
            metrics["tickets"] >= 100
            and metrics["return_rate"] >= 1.0
            and metrics["no_max_return_rate"] >= 1.0
            and metrics["no_top3_return_rate"] >= 1.0
        ),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
