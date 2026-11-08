from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


DEFAULT_DB = Path(r"D:\develop\jra-scr\data\db\analysis.sqlite")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Save one structured Nankan prediction into analysis SQLite."
    )
    parser.add_argument("--input", type=Path, help="Path to a JSON payload. If omitted, stdin is used.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to analysis SQLite.")
    return parser.parse_args()


def load_payload(path: Path | None) -> dict:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    return json.loads(sys.stdin.read())


def bootstrap_store(db_path: Path):
    repo_candidates = []
    env_repo = Path(sys.argv[0]).resolve().anchor
    _ = env_repo  # keep lint-free style without extra dependency
    cwd = Path.cwd()
    repo_candidates.append(cwd)
    repo_candidates.append(db_path.parents[2] if len(db_path.parents) >= 3 else cwd)
    for candidate in repo_candidates:
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
    store = bootstrap_store(args.db)
    result = store.upsert_prediction_record(payload)
    print(json.dumps({"db": str(args.db), **result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
