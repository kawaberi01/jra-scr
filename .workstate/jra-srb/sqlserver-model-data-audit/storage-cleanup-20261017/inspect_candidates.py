"""概要: 既存98ファイルの移行対応と現在のファイル情報を容量整理台帳へまとめる。
作成日: 2026-10-17
入力: 既存棚卸し、移行manifest、差分受入、最終同期、NAS保管証跡。
出力: 同じフォルダーのcandidate-evidence.jsonとcandidate-files.csv。
実行例: uv run --frozen python .workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261017/inspect_candidates.py
注意事項: DB内容を開かずファイル情報と小さなJSON証跡だけを読む。再帰走査・コピー・削除・SQL操作なし。
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[4]
OTHER = Path("D:/develop/jra-van-data")
OUT = Path(__file__).parent


def read(path):
    """UTF-8の既存JSON証跡を読み込む。"""
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def identity(path):
    """実ファイルを開かず、所在・長さ・時刻・識別子・reparse属性を返す。"""
    p = Path(path)
    try:
        st = p.lstat()
        return {"exists": True, "bytes": st.st_size, "mtime_ns": st.st_mtime_ns,
                "modified_utc": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
                "file_id": st.st_ino, "device": st.st_dev,
                "reparse_point": bool(getattr(st, "st_file_attributes", 0) & 0x400)}
    except FileNotFoundError:
        return {"exists": False}


def key(path):
    """Windowsの区切りと大文字小文字を正規化した照合キーを返す。"""
    return os.path.normcase(os.path.normpath(str(path)))


def unchanged(now, before):
    """元ファイルの長さ・mtime・識別子が既存の固定記録と合うかを判定する。"""
    return bool(now.get("exists") and now["bytes"] == before.get("size_bytes", before.get("size"))
                and now["mtime_ns"] == before.get("mtime_ns")
                and ("file_id" not in before or now["file_id"] == before["file_id"])
                and ("device" not in before or now["device"] == before["device"]))


def main():
    """移行版の対応・変更有無・既存NAS保管物を記録し、全98件の一覧を出力する。"""
    inv = read(ROOT / "notes/storage-classified-inventory-20261016.json")
    manifest = read(OTHER / "infra/sqlserver2022-poc/unified-source-manifest.json")
    delta = read(OTHER / "data/audits/sqlserver2022-unified-delta-20261011.json")
    sync = read(ROOT / ".workstate/jra-srb/sqlserver-api-cutover/final-sqlite.json")["result"]
    copy = read("C:/jra-sqlserver-migration-stage/20261009/copy-manifest.json")
    prediction_archive = read(OTHER / "data/audits/nas-prediction-full-archive-20261008.json")
    master_archive = read(OTHER / "data/audits/nas-master-archive-20261008.json")
    originals_archive = read(OTHER / "data/audits/nas-original-archive-20261007.json")
    mappings = {}
    for source in manifest["sources"]:
        source_path = Path(source["source_path"])
        if not source_path.is_absolute():
            source_path = OTHER / source_path
        for path, role in ((source_path, "source"), (Path(source["snapshot"]["snapshot_path"]), "snapshot")):
            mappings.setdefault(key(path), []).append({"source_key": source["source_database_key"], "role": role, "manifest": manifest["run_id"]})
    for source in delta["captured_sources"]:
        mappings.setdefault(key(source["snapshot"]["snapshot_path"]), []).append({"source_key": source["source_key"], "role": "delta_snapshot", "manifest": delta["run_id"]})
    items = []
    for original in inv["database_files"]:
        p = Path(original["path"])
        now = identity(p)
        mapping = mappings.get(key(p), [])
        item = {"path": str(p), "inventory_bytes": original["bytes"], "current": now,
                "sidecars": {suffix: identity(str(p) + suffix) for suffix in ("-wal", "-shm", "-journal")},
                "purpose": original["purpose"], "migration_mapping": mapping,
                "matches_inventory_size": now.get("bytes") == original["bytes"],
                "matches_inventory_modified_utc": now.get("modified_utc") == original["modified_utc"],
                "decision": "個別保管または除外根拠の対応待ち"}
        if mapping:
            item["decision"] = "SQL移行証跡あり・PC原版の保管方針を下記グループで判定"
        if ".bak_" in p.name:
            item["decision"] = "移行対象外の旧版backup・一度保管するまで保持"
        items.append(item)
    source_matches = []
    for source in manifest["sources"]:
        p = Path(source["source_path"])
        if not p.is_absolute():
            p = OTHER / p
        before = source["snapshot"]["source_after"]
        if source["source_database_key"] == "analysis-current":
            before = delta["captured_sources"][0]["snapshot"]["source_after"]
        source_matches.append({"source_key": source["source_database_key"], "path": str(p),
                               "unchanged_since_fixed_source": unchanged(identity(p), before),
                               "current_sidecars": {suffix: identity(str(p) + suffix) for suffix in ("-wal", "-shm", "-journal")}})
    final_sync_matches = {name: [{"path": f["path"], "matches": unchanged(identity(f["path"]), f) if f["size"] is not None else not identity(f["path"])["exists"]} for f in files] for name, files in sync["source_files"].items()}
    nas_paths = [prediction_archive["canonical_nas_main_path"], master_archive["canonical_nas_main_path"],
                 str(Path(originals_archive["archive_root"]) / "manifest.json"),
                 r"\\192.168.1.101\jra\sqlserver2022-poc\jra_unified_20261016_053626.bak"]
    stage_identity = identity(copy["stage_file"])
    stage_proof = {"path": copy["stage_file"], "current": stage_identity,
                   "matches_copy_receipt_size_mtime": unchanged(stage_identity, {"size_bytes": copy["stage_size_bytes"], "mtime_ns": copy["stage_mtime_ns"]}),
                   "existing_sha256_agrees_with_nas_archive": copy["stage_sha256"] == prediction_archive["source_sha256"] == prediction_archive["nas_sha256_from_completed_checkpoint"],
                   "copy_full_sha_verified": copy["destination_full_sha256_match"], "sha256": copy["stage_sha256"]}
    result = {"observed_at_utc": datetime.now(timezone.utc).isoformat(), "method": "existing proofs plus metadata; no SQLite content read or recursive scan",
              "inventory_count": len(items), "files": items, "source_identity_checks": source_matches,
              "api_final_sync_identity_checks": final_sync_matches, "stage09_full_prediction": stage_proof,
              "nas_retained_files": [{"path": p, **identity(p)} for p in nas_paths],
              "nas_original_capture_files": [{"path": f["destination"], "current": identity(f["destination"]), "proof_bytes": f["bytes"], "proof_sha256_match": f["source_sha256"] == f["destination_sha256"]} for f in originals_archive["capture_files"]],
              "local_free_bytes": {drive: shutil.disk_usage(drive + ":/").free for drive in ("C", "D")},
              "local_stage_ancestor_metadata": {str(p): identity(p) for p in [Path("C:/jra-sqlserver-migration-stage"), Path("C:/jra-sqlserver-migration-stage/20261009"), Path("C:/jra-sqlserver-migration-stage/20261010-unified")]},
              "source_data_mutations": False}
    (OUT / "candidate-evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with (OUT / "candidate-files.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["path", "bytes", "exists", "inventory_size_same", "inventory_mtime_same", "source_keys", "purpose", "decision"])
        writer.writeheader()
        for item in items:
            writer.writerow({"path": item["path"], "bytes": item["current"].get("bytes"), "exists": item["current"]["exists"],
                             "inventory_size_same": item["matches_inventory_size"], "inventory_mtime_same": item["matches_inventory_modified_utc"],
                             "source_keys": ";".join(m["source_key"] + ":" + m["role"] for m in item["migration_mapping"]), "purpose": item["purpose"], "decision": item["decision"]})
    print(json.dumps({"files": len(items), "missing": [i["path"] for i in items if not i["current"]["exists"]],
                      "changed_since_inventory": [i["path"] for i in items if not i["matches_inventory_size"] or not i["matches_inventory_modified_utc"]],
                      "mapped_files": sum(bool(i["migration_mapping"]) for i in items),
                      "source_identity_mismatches": [s["source_key"] for s in source_matches if not s["unchanged_since_fixed_source"]],
                      "api_final_sync": final_sync_matches, "stage09": stage_proof,
                      "nas_files": result["nas_retained_files"], "free_bytes": result["local_free_bytes"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
