from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from datetime import date

from jra_srb.jra_history_dataset import build_history_dataset, write_dataset_jsonl_gz
from jra_srb.jra_history_model import train_history_models, write_model_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the odds-free JRA history model without mutating the source DB.")
    parser.add_argument("--db", default="data/db/analysis.sqlite")
    parser.add_argument("--dataset", default="data/training/jra_history_v1/runner_features.jsonl.gz")
    parser.add_argument("--model-dir", default="data/models/jra_history_v1")
    parser.add_argument("--validation-fraction", type=float, default=0.2)
    parser.add_argument(
        "--through-date", type=date.fromisoformat,
        help="Include source races through this ISO date. Use the day before a live prediction target.",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    before = _fingerprint(db_path)
    records, metadata = build_history_dataset(db_path, through_date=args.through_date)
    write_dataset_jsonl_gz(records, args.dataset)
    artifact, report = train_history_models(records, validation_fraction=args.validation_fraction)
    write_model_artifacts(artifact, report, args.model_dir)
    after = _fingerprint(db_path)
    dataset_fingerprint = _fingerprint(Path(args.dataset))
    metadata.update({
        "source_db": str(db_path),
        "source_db_sha256_before_read": before[2],
        "source_db_sha256_after_run": after[2],
        "source_db_changed_during_run": before != after,
        "source_db_open_mode": "read_only",
        "dataset_path": args.dataset,
        "dataset_sha256": dataset_fingerprint[2],
        "model_dir": args.model_dir,
    })
    metadata_path = Path(args.dataset).with_name("dataset_metadata.json")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"dataset": metadata, "validation": report}, ensure_ascii=False, indent=2))


def _fingerprint(path: Path) -> tuple[int, int, str]:
    stat = path.stat()
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    return stat.st_size, stat.st_mtime_ns, digest


if __name__ == "__main__":
    main()
