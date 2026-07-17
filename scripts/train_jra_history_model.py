from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from datetime import date

from jra_srb.jra_history_dataset import build_history_dataset, write_dataset_jsonl_gz
from jra_srb.jra_history_model import train_history_models, write_model_artifacts
from jra_srb.jra_history_model import RECENT_FORM_MODEL_VERSION
from jra_srb.jra_recent_form_dataset import (
    RECENT_FORM_SCHEMA, append_recent_form_features,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the odds-free JRA history model without mutating the source DB.")
    parser.add_argument("--db", default="data/db/analysis.sqlite")
    parser.add_argument("--dataset")
    parser.add_argument("--model-dir")
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument("--recent-form", action="store_true")
    parser.add_argument(
        "--through-date", type=date.fromisoformat,
        help="Include source races through this ISO date. Use the day before a live prediction target.",
    )
    args = parser.parse_args()
    dataset_path = args.dataset or (
        "data/training/jra_history_recent_form_v2/runner_features.jsonl.gz"
        if args.recent_form else "data/training/jra_history_v1/runner_features.jsonl.gz"
    )
    model_dir = args.model_dir or (
        "data/models/jra_history_recent_form_v2" if args.recent_form else "data/models/jra_history_v1"
    )

    db_path = Path(args.db)
    before = _fingerprint(db_path)
    records, metadata = build_history_dataset(db_path, through_date=args.through_date)
    if args.recent_form:
        records = append_recent_form_features(records)
        metadata["feature_names"] = RECENT_FORM_SCHEMA
    write_dataset_jsonl_gz(records, dataset_path)
    artifact, report = train_history_models(
        records,
        validation_fraction=args.validation_fraction,
        feature_names=RECENT_FORM_SCHEMA if args.recent_form else None,
        model_version=RECENT_FORM_MODEL_VERSION if args.recent_form else "jra-history-logistic-v1",
    )
    write_model_artifacts(artifact, report, model_dir)
    after = _fingerprint(db_path)
    dataset_fingerprint = _fingerprint(Path(dataset_path))
    metadata.update({
        "source_db": str(db_path),
        "source_db_sha256_before_read": before[2],
        "source_db_sha256_after_run": after[2],
        "source_db_changed_during_run": before != after,
        "source_db_open_mode": "read_only",
        "dataset_path": dataset_path,
        "dataset_sha256": dataset_fingerprint[2],
        "model_dir": model_dir,
    })
    metadata_path = Path(dataset_path).with_name("dataset_metadata.json")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"dataset": metadata, "validation": report}, ensure_ascii=False, indent=2))


def _fingerprint(path: Path) -> tuple[int, int, str]:
    stat = path.stat()
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return stat.st_size, stat.st_mtime_ns, digest


if __name__ == "__main__":
    main()
