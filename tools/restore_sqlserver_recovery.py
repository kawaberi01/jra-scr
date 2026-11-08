"""概要: SQL回収ファイルから、旧SQLiteの構造を保った切戻し用コピーを作る。
作成日: 2026-10-15
入力: export-recoveryのSQLite、保持した旧analysis/jobs SQLite、未使用の出力ディレクトリ。
出力: 切戻し候補analysis.sqlite・jobs.sqlite、名前空間別JSONLと検証manifest。
実行例: uv run python tools/restore_sqlserver_recovery.py --help
注意事項: SQL writer停止後に使う。元DBを上書きせず、生成物は自動採用しない。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3

from jra_srb.sqlserver_schema import TABLES


def readonly(path: Path):
    """明示された回収ファイルまたは旧DBを読み取り専用で開く。"""
    return sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)


def restore_copy(recovery, original: Path, output: Path, source_key: str) -> dict:
    """旧DBの制約と索引をbackupで保持し、回収した業務値を新規コピーへ復元する。"""
    if output.exists():
        raise ValueError("復元先ファイルを上書きできません")
    with output.open("xb"):
        pass
    source = readonly(original)
    target = sqlite3.connect(output)
    counts = {}
    try:
        source.backup(target)
        source.close()
        target.execute("PRAGMA foreign_keys=OFF")
        target.execute("BEGIN")
        selected = [table for table in TABLES.values() if table.get("source", {}).get("key") == source_key]
        for table in reversed(selected):
            target.execute(f'DELETE FROM "{table["name"]}"')
        for table in selected:
            name = table["name"]
            columns = [column["name"] for column in table["columns"]]
            actual = {row[1] for row in target.execute(f'PRAGMA table_info("{name}")')}
            if set(columns) != actual:
                raise ValueError(f"保持した旧DBと回収契約の列が不一致: {name}")
            quoted = ",".join(f'"{column}"' for column in columns)
            cursor = recovery.execute(f'SELECT rowid,{quoted} FROM "{name}" ORDER BY rowid')
            query = f'INSERT INTO "{name}"(rowid,{quoted}) VALUES(' + ",".join("?" for _ in range(len(columns) + 1)) + ")"
            count = 0
            while rows := cursor.fetchmany(10000):
                target.executemany(query, rows)
                count += len(rows)
            if target.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] != count:
                raise ValueError(f"復元件数不一致: {name}")
            # NULL・型・文字列の差異を含め全値を、rowid順で回収元と照合する。
            source_rows = recovery.execute(f'SELECT rowid,{quoted} FROM "{name}" ORDER BY rowid')
            target_rows = target.execute(f'SELECT rowid,{quoted} FROM "{name}" ORDER BY rowid')
            for before, after in zip(source_rows, target_rows, strict=True):
                if before != after:
                    raise ValueError(f"復元値不一致: {name}")
            counts[name] = count
        target.commit()
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("復元SQLiteの整合性検査に失敗しました")
    except Exception:
        target.rollback()
        raise
    finally:
        source.close()
        target.close()
    return counts


def export_result_namespaces(recovery, output: Path) -> list:
    """SQL結果保存の全名前空間を安全なファイル名でJSONLに展開する。"""
    namespaces = recovery.execute("SELECT DISTINCT storage_namespace FROM stored_race_results ORDER BY storage_namespace").fetchall()
    result = []
    if namespaces:
        output.mkdir()
    for (namespace,) in namespaces:
        path = output / (hashlib.sha256(namespace.encode("utf-8")).hexdigest() + ".jsonl")
        rows = recovery.execute("SELECT race_id,race_date,course,race_no,result_json FROM stored_race_results WHERE storage_namespace=? ORDER BY race_date,course,race_no,race_id", (namespace,))
        count = 0
        with path.open("x", encoding="utf-8") as stream:
            for race_id, race_date, course, race_no, payload in rows:
                stream.write(json.dumps({"race_id": race_id, "date": race_date, "course": course,
                                         "race_no": race_no, "result": json.loads(payload)}, ensure_ascii=False) + "\n")
                count += 1
        result.append({"namespace": namespace, "staged_jsonl": str(path), "rows": count})
    return result


def main() -> int:
    """元データへ書かずに復元候補を作り、成功した場合だけmanifestを確定する。"""
    parser = argparse.ArgumentParser(description="SQL recovery export to reviewed SQLite copies")
    parser.add_argument("--recovery", type=Path, required=True)
    parser.add_argument("--original-analysis", type=Path, required=True)
    parser.add_argument("--original-jobs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    recovery = readonly(args.recovery)
    try:
        result = {"analysis": restore_copy(recovery, args.original_analysis, args.output_dir / "analysis.sqlite", "analysis-current"),
                  "jobs": restore_copy(recovery, args.original_jobs, args.output_dir / "jobs.sqlite", "jobs-current"),
                  "results": export_result_namespaces(recovery, args.output_dir / "results"),
                  "automatic_activation": False, "cache": "regenerable; not restored", "audit_source": str(args.recovery)}
        (args.output_dir / "verified-manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "verified", "output_dir": str(args.output_dir)}))
        return 0
    finally:
        recovery.close()


if __name__ == "__main__":
    raise SystemExit(main())
