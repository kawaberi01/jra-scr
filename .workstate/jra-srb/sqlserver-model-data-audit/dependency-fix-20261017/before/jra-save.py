from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


DEFAULT_DB = Path(r"D:\develop\jra-scr\data\db\analysis.sqlite")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Save one structured pre-race JRA prediction into analysis SQLite."
    )
    parser.add_argument("--input", type=Path, help="UTF-8 JSON payload. If omitted, stdin is used.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to analysis SQLite.")
    return parser.parse_args()


def load_payload(path: Path | None) -> dict:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(sys.stdin.read())


def bootstrap_store(db_path: Path):
    cwd = Path.cwd()
    candidates = [cwd, db_path.parents[2] if len(db_path.parents) >= 3 else cwd]
    for candidate in candidates:
        src_dir = candidate / "src"
        if src_dir.exists():
            sys.path.insert(0, str(src_dir))
            break
    from jra_srb.analysis_store import AnalysisSQLiteStore

    return AnalysisSQLiteStore(db_path)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    payload = load_payload(args.input)
    prediction_json = payload.get("prediction_json", {})
    is_pre_race = prediction_json.get("generated_before_result") is True
    is_reconstruction = (
        prediction_json.get("generated_before_result") is False
        and prediction_json.get("reconstruction_after_result") is True
        and prediction_json.get("reconstruction_label") == "結果判明後の復元予想"
    )
    if not (is_pre_race or is_reconstruction):
        raise ValueError(
            "prediction_json.generated_before_result must be true, or an explicitly labeled "
            "post-result reconstruction must be supplied"
        )
    store = bootstrap_store(args.db)
    result = store.upsert_prediction_record(payload)
    saved = store.get_prediction_record(str(payload["prediction_id"]))
    print(json.dumps({
        "db": str(args.db),
        **result,
        "verified": saved.race_id == str(payload["race_id"]),
        "created_at": saved.created_at.isoformat(),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
