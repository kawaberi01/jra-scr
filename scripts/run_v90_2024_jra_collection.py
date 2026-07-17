from __future__ import annotations

import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path


BATCHES = [
    ("2024-01-06", "2024-01-08", "nakayama,kyoto"),
    ("2024-01-13", "2024-01-14", "nakayama,kyoto,kokura"), ("2024-01-20", "2024-01-21", "nakayama,kyoto,kokura"), ("2024-01-27", "2024-01-28", "nakayama,kyoto,kokura"),
    ("2024-02-03", "2024-02-04", "tokyo,kyoto,kokura"), ("2024-02-10", "2024-02-12", "tokyo,kyoto,kokura"), ("2024-02-17", "2024-02-18", "tokyo,kyoto,hanshin"), ("2024-02-24", "2024-02-25", "tokyo,kyoto,hanshin"),
    ("2024-03-02", "2024-03-03", "nakayama,chukyo,hanshin"), ("2024-03-09", "2024-03-10", "nakayama,chukyo,hanshin"), ("2024-03-16", "2024-03-17", "nakayama,chukyo,hanshin"), ("2024-03-23", "2024-03-24", "nakayama,chukyo,hanshin"), ("2024-03-30", "2024-03-31", "nakayama,chukyo,hanshin"),
    ("2024-04-06", "2024-04-07", "fukushima,nakayama,hanshin"), ("2024-04-13", "2024-04-14", "fukushima,nakayama,hanshin"), ("2024-04-20", "2024-04-21", "fukushima,tokyo,kyoto"), ("2024-04-27", "2024-04-28", "fukushima,tokyo,kyoto"),
    ("2024-05-04", "2024-05-05", "niigata,tokyo,kyoto"), ("2024-05-11", "2024-05-12", "niigata,tokyo,kyoto"), ("2024-05-18", "2024-05-19", "niigata,tokyo,kyoto"), ("2024-05-25", "2024-05-26", "tokyo,kyoto"),
    ("2024-06-01", "2024-06-02", "tokyo,hanshin"), ("2024-06-08", "2024-06-09", "tokyo,hanshin,hakodate"), ("2024-06-15", "2024-06-16", "tokyo,hanshin,hakodate"), ("2024-06-22", "2024-06-23", "tokyo,hanshin,hakodate"), ("2024-06-29", "2024-06-30", "fukushima,hanshin,hakodate"),
    ("2024-07-06", "2024-07-07", "hakodate,fukushima,kokura"), ("2024-07-13", "2024-07-14", "hakodate,fukushima,kokura"), ("2024-07-20", "2024-07-21", "hakodate,fukushima,kokura,sapporo"), ("2024-07-27", "2024-07-28", "hakodate,fukushima,kokura,sapporo"),
    ("2024-08-03", "2024-08-04", "sapporo,niigata,kokura"), ("2024-08-10", "2024-08-11", "sapporo,niigata,kokura"), ("2024-08-17", "2024-08-18", "sapporo,niigata,chukyo"), ("2024-08-24", "2024-08-25", "sapporo,niigata,chukyo"), ("2024-08-31", "2024-08-31", "sapporo,niigata,chukyo"),
]
DB = Path("data/db/analysis.sqlite")
LOG = Path(".workstate/logs/v90_2024_jra_collection_py.log")
TARGET_FROM = "2024-07-01"
TARGET_TO = "2024-08-31"
CALENDAR = Path(".workstate/jra-srb/prediction-v1-validation/netkeiba_meeting_calendar.2024_07_08.verified.csv")
MAPPING = Path(".workstate/jra-srb/prediction-v1-validation/netkeiba_mapping.v90_external_2024_07_08.csv")
AUDIT = Path(".workstate/jra-srb/prediction-v1-validation/audit_v90_2024_external_data.py")


def result_count(from_date: str, to_date: str) -> int:
    with sqlite3.connect(DB) as conn:
        return conn.execute("select count(*) from race_results rr join races r on r.race_id=rr.race_id where r.race_date>=? and r.race_date<=?", (from_date, to_date)).fetchone()[0]


def race_count(from_date: str, to_date: str) -> int:
    with sqlite3.connect(DB) as conn:
        return conn.execute("select count(*) from races where race_date>=? and race_date<=?", (from_date, to_date)).fetchone()[0]


def missing_runner_count(from_date: str, to_date: str) -> int:
    with sqlite3.connect(DB) as conn:
        return conn.execute("select count(*) from races r where r.race_date>=? and r.race_date<=? and not exists (select 1 from runners ru where ru.race_id=r.race_id)", (from_date, to_date)).fetchone()[0]


def missing_result_count(from_date: str, to_date: str) -> int:
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            """select count(*) from races r
               where r.race_date>=? and r.race_date<=?
               and not exists (select 1 from race_results rr where rr.race_id=r.race_id)""",
            (from_date, to_date),
        ).fetchone()[0]


def missing_result_runner_count(from_date: str, to_date: str) -> int:
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            """select count(*) from runners ru join races r on r.race_id=ru.race_id
               left join result_entries re on re.race_id=ru.race_id and re.horse_no=ru.horse_no
               where r.race_date>=? and r.race_date<=? and re.race_id is null""",
            (from_date, to_date),
        ).fetchone()[0]


def recover_missing_results(from_date: str, to_date: str) -> None:
    for attempt in range(1, 4):
        before = missing_result_count(from_date, to_date)
        if before == 0:
            return
        with LOG.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now().astimezone().isoformat()} {from_date}..{to_date} result-recovery={attempt} missing_results={before}\n")
        run([
            "rtk", "uv", "run", "jra-srb", "collect-analysis",
            "--from-date", from_date, "--to-date", to_date, "--courses", "all", "--db", str(DB),
            "--include-results", "--retries", "1", "--min-interval-seconds", "1.5", "--max-live-requests", "20", "--skip-existing",
        ])
        if missing_result_count(from_date, to_date) >= before:
            break
    remaining = missing_result_count(from_date, to_date)
    if remaining:
        raise RuntimeError(f"JRA result recovery stalled with {remaining} missing races in {from_date}..{to_date}")


def target_jra_is_complete() -> bool:
    with sqlite3.connect(DB) as conn:
        races, results, missing_runners, missing_result_runners = conn.execute(
            """
            select count(*),
                   sum(case when exists (select 1 from race_results rr where rr.race_id=r.race_id) then 1 else 0 end),
                   sum(case when not exists (select 1 from runners ru where ru.race_id=r.race_id) then 1 else 0 end),
                   sum(case when exists (
                       select 1 from runners ru left join result_entries re
                       on re.race_id=ru.race_id and re.horse_no=ru.horse_no
                       where ru.race_id=r.race_id and re.race_id is null
                   ) then 1 else 0 end)
            from races r where r.race_date between ? and ?
            """,
            (TARGET_FROM, TARGET_TO),
        ).fetchone()
    return bool(races and races == results and not missing_runners and not missing_result_runners)


def missing_netkeiba_races() -> int:
    with sqlite3.connect(DB) as conn:
        return conn.execute(
            """
            select count(*)
            from races r
            join race_results rr on rr.race_id=r.race_id
            left join netkeiba_race_mappings m on m.jra_race_id=r.race_id
            where r.race_date between ? and ? and (
                m.netkeiba_race_id is null or m.netkeiba_race_id='' or
                not exists (select 1 from netkeiba_race_results n where n.netkeiba_race_id=m.netkeiba_race_id) or
                not exists (select 1 from netkeiba_result_entries e where e.netkeiba_race_id=m.netkeiba_race_id) or
                not exists (select 1 from netkeiba_payouts p where p.netkeiba_race_id=m.netkeiba_race_id)
            )
            """,
            (TARGET_FROM, TARGET_TO),
        ).fetchone()[0]


def run_external_evaluation_inputs() -> None:
    if not target_jra_is_complete():
        raise RuntimeError("target JRA coverage is incomplete; refusing netkeiba collection and evaluation")
    run([
        "rtk", "uv", "run", "jra-srb", "generate-netkeiba-mapping",
        "--from-date", TARGET_FROM, "--to-date", TARGET_TO, "--db", str(DB),
        "--meeting-calendar-csv", str(CALENDAR), "--output", str(MAPPING), "--save-to-db",
    ])
    idle_attempts = 0
    for attempt in range(1, 121):
        before = missing_netkeiba_races()
        if before == 0:
            break
        with LOG.open("a", encoding="utf-8") as stream:
            stream.write(f"{datetime.now().astimezone().isoformat()} netkeiba attempt={attempt} missing={before}\n")
        run([
            "rtk", "uv", "run", "jra-srb", "collect-netkeiba-results",
            "--from-date", TARGET_FROM, "--to-date", TARGET_TO, "--db", str(DB),
            "--use-db-mapping", "--max-live-requests", "10", "--min-interval-seconds", "5", "--retries", "1",
        ])
        after = missing_netkeiba_races()
        if after >= before:
            idle_attempts += 1
        else:
            idle_attempts = 0
        # A fresh CLI process can recover targets after a transient netkeiba
        # response with an empty payload.  Require several consecutive stalls
        # before declaring the bounded collection irrecoverable.
        if idle_attempts >= 10:
            raise RuntimeError(f"netkeiba coverage stalled with {after} target races missing")
    if missing_netkeiba_races() != 0:
        raise RuntimeError("netkeiba coverage did not complete within the request limit")
    run(["rtk", "uv", "run", "python", str(AUDIT), "--db", str(DB), "--from-date", TARGET_FROM, "--to-date", TARGET_TO])
    run([
        "rtk", "uv", "run", "python", ".workstate/jra-srb/prediction-v1-validation/evaluate_v1_validation.py",
        "--db", str(DB), "--theory-version", "v90", "--from-date", TARGET_FROM, "--to-date", TARGET_TO,
        "--period-label", "v90_external_2024_07_08", "--output-dir", ".workstate/jra-srb/prediction-v1-validation", "--offline",
    ])
    run(["rtk", "uv", "run", "python", ".workstate/jra-srb/prediction-v1-validation/write_v90_external_decision.py"])


def run(command: list[str]) -> bool:
    try:
        completed = subprocess.run(
            command,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=85,
        )
    except subprocess.TimeoutExpired as exc:
        with LOG.open("a", encoding="utf-8") as stream:
            stream.write(f"timeout after 85 seconds: {' '.join(command)}\n")
            if exc.stdout:
                stream.write(str(exc.stdout))
        return False
    with LOG.open("a", encoding="utf-8") as stream:
        stream.write(completed.stdout)
    if completed.returncode:
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}")
    return True


def main() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    for from_date, to_date, _planned_courses in BATCHES:
        # Ask the JRA calendar for the actual venues.  This avoids stale venue
        # assumptions and saves two meeting-page requests on most race days.
        courses = "all"
        # A prior interrupted run may already have completed this window.
        # Do not spend five additional network passes merely to rediscover it.
        if (
            race_count(from_date, to_date) > 0
            and result_count(from_date, to_date) == race_count(from_date, to_date)
            and missing_runner_count(from_date, to_date) == 0
        ):
            with LOG.open("a", encoding="utf-8") as stream:
                stream.write(f"{datetime.now().astimezone().isoformat()} {from_date}..{to_date} already complete; skipping collection\n")
            run(["rtk", "uv", "run", "jra-srb", "verify-analysis-joins", "--from-date", from_date, "--to-date", to_date, "--db", str(DB), "--sample-size", "5"])
            continue
        idle_attempts = 0
        for attempt in range(1, 121):
            before = result_count(from_date, to_date)
            with LOG.open("a", encoding="utf-8") as stream:
                stream.write(f"{datetime.now().astimezone().isoformat()} {from_date}..{to_date} attempt={attempt} results={before}\n")
            run(["rtk", "uv", "run", "jra-srb", "collect-analysis", "--from-date", from_date, "--to-date", to_date, "--courses", courses, "--db", str(DB), "--include-card", "--include-results", "--retries", "1", "--min-interval-seconds", "1.5", "--max-live-requests", "20", "--skip-existing"])
            if result_count(from_date, to_date) == before:
                idle_attempts += 1
            else:
                idle_attempts = 0
            if idle_attempts >= 1:
                break
        for attempt in range(1, 21):
            before_missing = missing_runner_count(from_date, to_date)
            if before_missing == 0:
                break
            with LOG.open("a", encoding="utf-8") as stream:
                stream.write(f"{datetime.now().astimezone().isoformat()} {from_date}..{to_date} backfill={attempt} missing_runners={before_missing}\n")
            run(["rtk", "uv", "run", "jra-srb", "backfill-analysis-runners", "--from-date", from_date, "--to-date", to_date, "--courses", "all", "--db", str(DB), "--only-missing", "--retries", "1", "--min-interval-seconds", "3", "--limit", "10"])
            if missing_runner_count(from_date, to_date) == before_missing:
                break
        recover_missing_results(from_date, to_date)
        missing_result_runners = missing_result_runner_count(from_date, to_date)
        if missing_result_runners:
            raise RuntimeError(f"JRA runner/result join has {missing_result_runners} missing rows in {from_date}..{to_date}")
        run(["rtk", "uv", "run", "jra-srb", "verify-analysis-joins", "--from-date", from_date, "--to-date", to_date, "--db", str(DB), "--sample-size", "5"])
    run_external_evaluation_inputs()


if __name__ == "__main__":
    main()
