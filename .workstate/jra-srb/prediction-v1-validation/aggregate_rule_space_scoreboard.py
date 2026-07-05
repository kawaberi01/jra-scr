from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_JSON = BASE_DIR / "rule_space_scoreboard.json"
OUTPUT_MD = BASE_DIR / "rule_space_scoreboard.md"

SOURCE_PATTERNS = [
    "*_validation_summary.json",
    "*_holdout_summary.json",
    "train_walkforward*.json",
    "*sweep*.json",
]

PHASE_ORDER = {
    "validation_2025Q4": 0,
    "wf1_2025_07": 1,
    "wf2_2025_08": 2,
    "wf3_2025_09": 3,
    "holdout_2026H1": 4,
}


@dataclass
class TheoryAggregate:
    theory_version: str
    theory_note: str = ""
    sources: set[str] = field(default_factory=set)
    phases: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_record(self, source_name: str, record: dict[str, Any]) -> None:
        self.sources.add(source_name)
        if not self.theory_note:
            self.theory_note = str(record.get("theory_note") or "")
        phase = normalize_phase(record)
        current = self.phases.get(phase)
        if current is None or phase_rank(record) >= phase_rank(current):
            self.phases[phase] = record


def normalize_phase(record: dict[str, Any]) -> str:
    if "split_label" in record:
        return str(record["split_label"])
    phase = record.get("phase")
    if phase:
        return str(phase)
    period = str(record.get("evaluation_period") or "")
    if period == "2025-10-01..2025-12-31":
        return "validation_2025Q4"
    if period == "2026-01-01..2026-06-28":
        return "holdout_2026H1"
    return period or "unknown"


def phase_rank(record: dict[str, Any]) -> int:
    phase = normalize_phase(record)
    return PHASE_ORDER.get(phase, 999)


def load_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    return []


def discover_source_files() -> list[Path]:
    files: dict[Path, None] = {}
    for pattern in SOURCE_PATTERNS:
        for path in BASE_DIR.glob(pattern):
            if path.name in {"rule_space_scoreboard.json"}:
                continue
            files[path] = None
    return sorted(files)


def build_scoreboard() -> list[TheoryAggregate]:
    theories: dict[str, TheoryAggregate] = {}
    for path in discover_source_files():
        for record in load_records(path):
            theory_version = str(record.get("theory_version") or "").strip()
            if not theory_version:
                continue
            agg = theories.setdefault(theory_version, TheoryAggregate(theory_version=theory_version))
            agg.add_record(path.name, record)
    return sorted(theories.values(), key=scoreboard_sort_key)


def get_metric(record: dict[str, Any] | None, key: str) -> float | None:
    if record is None:
        return None
    value = record.get(key)
    if value is None:
        return None
    return float(value)


def fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.4f}"


def scoreboard_sort_key(theory: TheoryAggregate) -> tuple[float, float, float, str]:
    validation = theory.phases.get("validation_2025Q4")
    holdout = theory.phases.get("holdout_2026H1")
    validation_no_max = get_metric(validation, "return_rate_without_max_payout") or -1.0
    train_floor = min_train_no_max(theory)
    holdout_no_max = get_metric(holdout, "return_rate_without_max_payout") or -1.0
    return (-validation_no_max, -train_floor, -holdout_no_max, theory.theory_version)


def min_train_no_max(theory: TheoryAggregate) -> float:
    values: list[float] = []
    for phase in ("wf1_2025_07", "wf2_2025_08", "wf3_2025_09"):
        value = get_metric(theory.phases.get(phase), "return_rate_without_max_payout")
        if value is not None:
            values.append(value)
    return min(values) if values else -1.0


def verdict(theory: TheoryAggregate) -> str:
    holdout = theory.phases.get("holdout_2026H1")
    validation = theory.phases.get("validation_2025Q4")
    train_floor = min_train_no_max(theory)
    validation_no_max = get_metric(validation, "return_rate_without_max_payout")
    holdout_no_max = get_metric(holdout, "return_rate_without_max_payout")
    if holdout_no_max is not None:
        return "reject_holdout" if holdout_no_max < 1.0 else "holdout_pass"
    if validation_no_max is None:
        return "incomplete"
    if validation_no_max >= 1.0 and train_floor >= 1.0:
        return "candidate"
    return "reject_train_validation"


def theory_row(theory: TheoryAggregate) -> dict[str, Any]:
    validation = theory.phases.get("validation_2025Q4")
    holdout = theory.phases.get("holdout_2026H1")
    return {
        "theory_version": theory.theory_version,
        "theory_note": theory.theory_note,
        "verdict": verdict(theory),
        "sources": sorted(theory.sources),
        "validation": summarize_record(validation),
        "wf1_2025_07": summarize_record(theory.phases.get("wf1_2025_07")),
        "wf2_2025_08": summarize_record(theory.phases.get("wf2_2025_08")),
        "wf3_2025_09": summarize_record(theory.phases.get("wf3_2025_09")),
        "holdout_2026H1": summarize_record(holdout),
        "train_no_max_floor": min_train_no_max(theory),
    }


def summarize_record(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    keys = [
        "evaluation_period",
        "return_rate",
        "return_rate_without_max_payout",
        "return_rate_without_top3_payouts",
        "axis_top3_rate",
        "middle_hole_top3_rate",
        "wide_hit_rate",
        "bet_races",
        "tickets",
        "max_payout",
    ]
    return {key: record.get(key) for key in keys if key in record}


def write_json(theories: list[TheoryAggregate]) -> None:
    rows = [theory_row(theory) for theory in theories]
    payload = {
        "generated_from": sorted(path.name for path in discover_source_files()),
        "theory_count": len(rows),
        "candidate_count": sum(1 for row in rows if row["verdict"] == "candidate"),
        "holdout_tested_count": sum(1 for row in rows if row["holdout_2026H1"] is not None),
        "rows": rows,
    }
    OUTPUT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_markdown(theories: list[TheoryAggregate]) -> None:
    candidate_count = sum(1 for theory in theories if verdict(theory) == "candidate")
    holdout_failed = [theory for theory in theories if verdict(theory) == "reject_holdout"]
    top_validation = theories[:12]
    representative_names = [
        "v10",
        "v17",
        "v22",
        "sg_a4_6_r3_5",
        "hy_fg7_5_a2_10_rle2",
        "v24",
        "v25",
        "v25_sg_a4_6_rle2",
        "v25_a4_6_rle2_fg2_5",
        "v25_a4_8_rle2_fg2_5",
        "v25_a4_8_rle2_fg5",
    ]
    representative = [theory_lookup(theories, name) for name in representative_names]
    representative = [theory for theory in representative if theory is not None]

    lines: list[str] = []
    lines.append("# Rule Space Scoreboard")
    lines.append("")
    lines.append("Date: 2026-07-04")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- Aggregated theories: {len(theories)}")
    lines.append(f"- Holdout-tested theories: {len(holdout_failed)}")
    lines.append(f"- Current candidate count by fixed train+validation gate: {candidate_count}")
    lines.append("- Practical conclusion: no theory in the current rule space clears train walk-forward and validation together.")
    lines.append("")
    lines.append("## Best Validation Theories")
    lines.append("")
    lines.append("| theory | validation no-max | Jul no-max | Aug no-max | Sep no-max | holdout no-max | verdict |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for theory in top_validation:
        lines.append(
            "| "
            + " | ".join(
                [
                    theory.theory_version,
                    fmt(get_metric(theory.phases.get("validation_2025Q4"), "return_rate_without_max_payout")),
                    fmt(get_metric(theory.phases.get("wf1_2025_07"), "return_rate_without_max_payout")),
                    fmt(get_metric(theory.phases.get("wf2_2025_08"), "return_rate_without_max_payout")),
                    fmt(get_metric(theory.phases.get("wf3_2025_09"), "return_rate_without_max_payout")),
                    fmt(get_metric(theory.phases.get("holdout_2026H1"), "return_rate_without_max_payout")),
                    verdict(theory),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Representative Theories")
    lines.append("")
    lines.append("| theory | validation no-max | Jul no-max | Aug no-max | Sep no-max | holdout no-max | comment |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for theory in representative:
        lines.append(
            "| "
            + " | ".join(
                [
                    theory.theory_version,
                    fmt(get_metric(theory.phases.get("validation_2025Q4"), "return_rate_without_max_payout")),
                    fmt(get_metric(theory.phases.get("wf1_2025_07"), "return_rate_without_max_payout")),
                    fmt(get_metric(theory.phases.get("wf2_2025_08"), "return_rate_without_max_payout")),
                    fmt(get_metric(theory.phases.get("wf3_2025_09"), "return_rate_without_max_payout")),
                    fmt(get_metric(theory.phases.get("holdout_2026H1"), "return_rate_without_max_payout")),
                    representative_comment(theory.theory_version),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## Decision Support")
    lines.append("")
    lines.append("- `v10` is the only frozen holdout-tested theory and it failed.")
    lines.append("- The best validation-only rows are concentrated in `v25` derivatives, but every one of them still breaks at least one train month.")
    lines.append("- The main failure pattern is unchanged: improving validation no-max tends to push `wf3_2025_09` below an acceptable floor.")
    lines.append("")
    lines.append("## Source Files")
    lines.append("")
    for path in discover_source_files():
        lines.append(f"- `{path.name}`")
    lines.append("")
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def representative_comment(theory_version: str) -> str:
    comments = {
        "v10": "frozen holdout failure",
        "v17": "baseline of later work",
        "v22": "standard one-ticket branch",
        "sg_a4_6_r3_5": "shape guard branch",
        "hy_fg7_5_a2_10_rle2": "strong validation, weak Jul/Aug",
        "v24": "target hard gate <=8",
        "v25": "best simple target gate",
        "v25_sg_a4_6_rle2": "v25 plus weak-shape filter",
        "v25_a4_6_rle2_fg2_5": "v25 plus weak-shape and first gap",
        "v25_a4_8_rle2_fg2_5": "wider ratio window",
        "v25_a4_8_rle2_fg5": "highest validation no-max in current space",
    }
    return comments.get(theory_version, "")


def theory_lookup(theories: list[TheoryAggregate], theory_version: str) -> TheoryAggregate | None:
    for theory in theories:
        if theory.theory_version == theory_version:
            return theory
    return None


def main() -> None:
    theories = build_scoreboard()
    write_json(theories)
    write_markdown(theories)
    print(f"wrote {OUTPUT_JSON.name} and {OUTPUT_MD.name} for {len(theories)} theories")


if __name__ == "__main__":
    main()
