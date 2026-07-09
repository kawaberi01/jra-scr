from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply relocation plan for workspace cleanup."
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

    moved = 0

    for entry in entries:
        source_rel = Path(entry["source"])
        destination_rel = Path(entry["destination"])

        source_abs = workspace_root / source_rel
        destination_abs = workspace_root / destination_rel

        if not source_abs.exists():
            print(f"ERROR missing source: {source_rel}")
            return 2

        if destination_abs.exists():
            print(f"ERROR destination exists: {destination_rel}")
            return 3

        destination_abs.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_abs), str(destination_abs))
        moved += 1
        print(f"MOVED {source_rel} -> {destination_rel}")

    print(f"Completed: {moved} files moved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
