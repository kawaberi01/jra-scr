"""概要: 承認済みB/C対象を読取ロックし、NASへ重複排除して圧縮保管・読戻し検証する。
作成日: 2026-10-25
入力: 10/17の対象CSV・証跡JSON、PATH上のzstd.exe。
出力: NASの新規zstd保管物、同フォルダーのbc-archive.json/jsonl。
実行例: uv run python .workstate/jra-srb/sqlserver-model-data-audit/storage-cleanup-20261025/archive_bc.py
注意事項: 元ファイルの削除・更新は行わない。NASへ通信・新規保存する。失敗時は停止する。
"""

import csv
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import shutil
import subprocess
import time

HERE = Path(__file__).resolve().parent
PREVIOUS = HERE.parent / "storage-cleanup-20261017"
DEST = Path(r"\\192.168.1.101\jra\jra-van-data\retired\pc-cleanup-20261025")
LOG = HERE / "bc-archive.jsonl"
REPORT = HERE / "bc-archive.json"
ZSTD = shutil.which("zstd.exe")
CHUNK = 8 * 1024 * 1024


def record(event, **values):
    """進捗を秘密を含まないJSON行として永続化・表示する。"""
    entry = {"time_utc": datetime.now(timezone.utc).isoformat(), "event": event, **values}
    with LOG.open("a", encoding="utf-8") as output:
        output.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(json.dumps(entry, ensure_ascii=False), flush=True)


def identity(path):
    """パスの内容を開かず、版照合用のファイル識別情報を返す。"""
    state = os.stat(path)
    return {"bytes": state.st_size, "mtime_ns": state.st_mtime_ns,
            "file_id": state.st_ino, "device": state.st_dev}


def safe_path(path):
    """対象と祖先にreparse pointがないことを確認する。"""
    for part in (path, *path.parents):
        if os.lstat(part).st_file_attributes & 0x400:
            raise RuntimeError(f"reparse point: {part}")


def lock_read(path):
    """Windows共有モードを読取のみとして開き、他プロセスの更新・削除を防ぐ。"""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), "rb")


def digest_stream(stream, label):
    """ストリームのSHA-256を計算し、大容量処理では30秒ごとに進捗を残す。"""
    digest = hashlib.sha256()
    count = 0
    last = time.monotonic()
    while chunk := stream.read(CHUNK):
        digest.update(chunk)
        count += len(chunk)
        if time.monotonic() - last >= 30:
            record("hash_progress", label=label, bytes=count)
            last = time.monotonic()
    return digest.hexdigest(), count


def main():
    """B/C本体と既存sidecarを保管し、検証済みファイルの実施manifestを生成する。"""
    if not ZSTD or REPORT.exists() or LOG.exists() or DEST.exists():
        raise RuntimeError("既存実行への上書き、またはzstd未配置のため停止")
    previous = json.loads((PREVIOUS / "candidate-evidence.json").read_text(encoding="utf-8-sig"))
    entries = {entry["path"]: entry for entry in previous["files"]}
    with (PREVIOUS / "deletion-decisions.csv").open(encoding="utf-8-sig", newline="") as source:
        rows = [row for row in csv.DictReader(source) if row["group"] in {"B", "C"}]
    if len(rows) != 68:
        raise RuntimeError("B/C本体件数不一致")
    if shutil.disk_usage(DEST.parent).free < 100_000_000_000:
        raise RuntimeError("NAS空き100GB未満")
    targets, locks, objects = [], [], {}
    try:
        for row in rows:
            path = Path(row["path"])
            prior = entries[str(path)]
            for suffix in ("", "-wal", "-shm", "-journal"):
                item = Path(str(path) + suffix)
                expected = prior["current"] if not suffix else prior["sidecars"][suffix]
                if not item.exists():
                    if expected.get("exists"):
                        raise RuntimeError(f"期待するファイルなし: {item}")
                    continue
                if suffix == "-journal":
                    raise RuntimeError(f"journalあり: {item}")
                safe_path(item)
                lock = lock_read(item)
                locks.append(lock)
                current = identity(item)
                if any(current[key] != expected[key] for key in current):
                    raise RuntimeError(f"証跡から版変化: {item}")
                targets.append({"path": str(item), "unit": str(path), "group": row["group"],
                                "identity": current, "lock": lock})
        DEST.mkdir()
        record("preflight_passed", main_files=len(rows), total_files=len(targets),
               total_bytes=sum(target["identity"]["bytes"] for target in targets),
               free_before={drive: shutil.disk_usage(drive + ":/").free for drive in ("C", "D")})
        for index, target in enumerate(targets, 1):
            record("source_hash_start", index=index, total=len(targets), path=target["path"])
            digest, size = digest_stream(target["lock"], target["path"])
            if size != target["identity"]["bytes"]:
                raise RuntimeError("読取長不一致")
            archive = DEST / (digest + ".zst")
            if digest not in objects:
                partial = DEST / (digest + ".partial.zst")
                record("compress_start", path=target["path"], bytes=size)
                subprocess.run([ZSTD, "-q", "-3", "-T2", "--no-progress", "-o", str(partial),
                                "--", target["path"]], check=True)
                record("readback_start", path=str(partial))
                with subprocess.Popen([ZSTD, "-q", "-d", "-c", "--", str(partial)],
                                      stdout=subprocess.PIPE) as decoder:
                    restored_hash, restored_size = digest_stream(decoder.stdout, str(partial))
                    code = decoder.wait()
                if code or (restored_hash, restored_size) != (digest, size):
                    raise RuntimeError("圧縮保管の読戻し不一致")
                partial.rename(archive)
                objects[digest] = {"archive": str(archive), "source_bytes": size,
                                   "archive_bytes": archive.stat().st_size, "sha256": digest}
            if identity(target["path"]) != target["identity"]:
                raise RuntimeError("保管後に元版変化")
            target.update(sha256=digest, archive=str(archive))
            record("archived_verified", index=index, path=target["path"], archive=str(archive),
                   sha256=digest, bytes=size)
        result = {"status": "archived_verified_not_deleted", "created_at_utc": datetime.now(timezone.utc).isoformat(),
                  "targets": [{key: value for key, value in target.items() if key != "lock"} for target in targets],
                  "objects": list(objects.values()), "nas_added_bytes": sum(obj["archive_bytes"] for obj in objects.values())}
        REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.copyfile(REPORT, DEST / "manifest.json")
        if json.loads((DEST / "manifest.json").read_text(encoding="utf-8")) != result:
            raise RuntimeError("NAS manifest読戻し不一致")
        record("complete", files=len(targets), objects=len(objects), nas_added_bytes=result["nas_added_bytes"])
    except Exception as error:
        record("failed", error_type=type(error).__name__, message=str(error))
        raise
    finally:
        for lock in locks:
            lock.close()


if __name__ == "__main__":
    main()
