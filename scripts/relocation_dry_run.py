from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dry-run relocation plan for workspace cleanup."
    )
    parser.add_argument(
        "--manifest",
        default="tools/workspace_relocation_manifest.json",
        help="Path to relocation manifest JSON.",
    )
    return parser


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    args = build_parser().parse_args()
    workspace_root = Path.cwd()
    manifest_path = workspace_root / args.manifest

    if not manifest_path.exists():
        print(f"ERROR manifest not found: {manifest_path}")
        return 1

    manifest = load_manifest(manifest_path)
    entries = manifest.get("entries", [])

    if not isinstance(entries, list):
        print("ERROR manifest entries must be a list")
        return 1

    destination_counter: Counter[str] = Counter()
    move_count = 0
    missing_count = 0
    conflict_count = 0

    print(f"Workspace: {workspace_root}")
    print(f"Manifest:  {manifest_path}")
    print(f"Entries:   {len(entries)}")
    print("")

    for entry in entries:
        source_rel = Path(entry["source"])
        destination_rel = Path(entry["destination"])
        reason = entry.get("reason", "")

        source_abs = workspace_root / source_rel
        destination_abs = workspace_root / destination_rel

        source_exists = source_abs.exists()
        destination_exists = destination_abs.exists()

        status = "PLAN"
        if not source_exists:
            status = "MISSING"
            missing_count += 1
        elif destination_exists:
            status = "CONFLICT"
            conflict_count += 1
        else:
            move_count += 1

        destination_counter[str(destination_rel.parent)] += 1

        print(
            f"[{status}] {source_rel} -> {destination_rel}"
            + (f" | {reason}" if reason else "")
        )

    print("")
    print("Summary")
    print(f"- planned moves: {move_count}")
    print(f"- missing sources: {missing_count}")
    print(f"- destination conflicts: {conflict_count}")
    print("")
    print("Destination groups")

    for destination_dir, count in sorted(destination_counter.items()):
        print(f"- {destination_dir}: {count}")

    return 0 if missing_count == 0 and conflict_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
