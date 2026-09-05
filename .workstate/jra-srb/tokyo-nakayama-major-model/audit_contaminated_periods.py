from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path


RANGE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})\s*(?:\.\.|～|to|through)\s*(20\d{2}-\d{2}-\d{2})", re.IGNORECASE)
RESULT_NAME_MARKERS = ("summary", "report", "races", "walkforward", "iteration", "decision", "scoreboard", "holdout")


def audit(root: Path) -> dict:
    ranges: dict[tuple[str, str], set[str]] = defaultdict(set)
    scanned = 0
    skipped = 0
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".md", ".json", ".log"}:
            continue
        name = path.name.lower()
        if not any(marker in name for marker in RESULT_NAME_MARKERS):
            continue
        if path.stat().st_size > 5_000_000:
            skipped += 1
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped += 1
            continue
        scanned += 1
        for start, end in RANGE_RE.findall(text):
            ranges[(start, end)].add(path.relative_to(root).as_posix())
    entries = [
        {"from_date": start, "to_date": end, "source_count": len(sources), "sources": sorted(sources)[:20]}
        for (start, end), sources in sorted(ranges.items())
    ]
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "scan_root": str(root),
        "scanned_files": scanned,
        "skipped_files": skipped,
        "contaminated_ranges": entries,
        "fixed_exclusions": [
            {"from_date": "2025-01-05", "to_date": "2025-09-30", "reason": "train/walk-forward explored"},
            {"from_date": "2025-10-01", "to_date": "2025-12-31", "reason": "validation explored"},
            {"from_date": "2026-01-01", "to_date": "2026-06-28", "reason": "v89 known holdout explored"},
            {"from_date": "2024-12-28", "to_date": "2024-12-28", "reason": "collection/evaluation pilot inspected"},
        ],
        "fresh_holdout_rule": "Only completed Tokyo/Nakayama autumn races after 2026-06-28 that were not used for model or threshold changes; fewer than 30 tickets means shadow-only.",
    }


def markdown(report: dict) -> str:
    lines = [
        "# 汚染済み期間と未使用holdout台帳",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- scanned_files: {report['scanned_files']}",
        f"- skipped_files: {report['skipped_files']}",
        "",
        "## 最終holdoutから固定除外",
        "",
    ]
    for item in report["fixed_exclusions"]:
        lines.append(f"- `{item['from_date']}..{item['to_date']}`: {item['reason']}")
    lines.extend(["", "## 成果物から検出した参照期間", ""])
    for item in report["contaminated_ranges"]:
        lines.append(f"- `{item['from_date']}..{item['to_date']}`: {item['source_count']} files")
    lines.extend(
        [
            "",
            "## 未使用holdoutの扱い",
            "",
            f"- {report['fresh_holdout_rule']}",
            "- 開封前に候補と基準をcommitし、開封は一回だけ行う。",
            "- 現時点で30買い目を確保できなければ正式採用とは呼ばない。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-root", type=Path, default=Path(".workstate/jra-srb/prediction-v1-validation"))
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "artifacts")
    args = parser.parse_args()
    report = audit(args.scan_root)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "contamination_ledger.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    (args.output_dir / "contamination_ledger.md").write_text(markdown(report), encoding="utf-8", newline="\n")
    print(json.dumps({key: report[key] for key in ("scanned_files", "skipped_files", "fixed_exclusions", "contaminated_ranges")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

