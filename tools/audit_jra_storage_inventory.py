"""JRA関連ファイルの用途分類に使う読取専用の容量棚卸し。

作成日: 2026-10-15
入力: --root で指定するフォルダー（複数指定可）、--output の新規JSONパス。
    --excludeは別集計するフォルダー、--summary-onlyは主要ファイルのみ個別記録する指定。
出力: ファイルの所在・論理サイズ・更新時刻・集計・読取エラーをJSONへ保存。
    --summary-only時は個別パスを大容量ファイルとDBに絞る。全ファイルの件数・容量は集計する。
実行例: uv run --no-project python tools/audit_jra_storage_inventory.py --root data --output artifacts/storage-review/inventory.json
注意事項: 原本の内容を読まず、DB接続・削除・移動・圧縮はしない。リンク先は走査しない。
    サイズは論理サイズであり、圧縮後サイズやディスク割当量ではない。既存出力は上書きしない。
"""

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def inventory_roots(roots: list[Path], summary_only: bool = False, excluded: list[Path] | None = None) -> dict:
    """指定範囲をリンク先を辿らず列挙し、容量・DB一覧・読取エラーを返す。

    Args:
        roots: 重複しない対象フォルダー。存在しない対象はエラー記録へ残す。
        summary_only: Trueなら全件のパス一覧を省略し、集計とDB等の主要ファイルを残す。
        excluded: 別方式で集計するフォルダー。結果に除外範囲を明記する。

    Returns:
        取得時刻、全ファイルのメタデータ、フォルダー集計、読取エラー。

    Notes:
        走査中の更新は排除しない。ファイル内容・秘密設定値は読み取らない。
    """
    files = []
    errors = []
    groups = defaultdict(lambda: {"bytes": 0, "files": 0})
    root_totals = {}
    links = []
    excluded_names = {os.path.normcase(os.path.abspath(path)) for path in excluded or []}
    for root in roots:
        root = root.resolve()
        total = 0
        count = 0
        if not root.is_dir():
            errors.append({"path": str(root), "error": "対象ディレクトリが存在しない"})
            continue
        pending = [root]
        while pending:
            directory = pending.pop()
            relative_parts = directory.relative_to(root).parts
            depth = 2 if root.name == "data" else 1
            group = str(root.joinpath(*relative_parts[:depth]))
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        try:
                            if entry.is_symlink():
                                links.append(entry.path)
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if os.path.normcase(os.path.abspath(entry.path)) in excluded_names:
                                    continue
                                if getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) & 0x400:
                                    links.append(entry.path)
                                    continue
                                pending.append(Path(entry.path))
                                continue
                            if not entry.is_file(follow_symlinks=False):
                                continue
                            info = entry.stat(follow_symlinks=False)
                            if not summary_only or info.st_size >= 100_000_000 or ".sqlite" in entry.name or entry.name.endswith(".db"):
                                files.append({"path": entry.path, "bytes": info.st_size,
                                              "modified_utc": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
                                              "group": group})
                            groups[group]["bytes"] += info.st_size
                            groups[group]["files"] += 1
                            total += info.st_size
                            count += 1
                            if count % 1_000_000 == 0:
                                print(json.dumps({"progress_root": str(root), "files": count, "bytes": total}, ensure_ascii=False), flush=True)
                        except OSError as exc:
                            errors.append({"path": entry.path, "error": str(exc)})
            except OSError as exc:
                errors.append({"path": str(directory), "error": str(exc)})
        root_totals[str(root)] = {"bytes": total, "files": count}
        print(json.dumps({"completed_root": str(root), "bytes": total, "files": count}, ensure_ascii=False), flush=True)
    return {"observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "size_kind": "logical_bytes", "file_listing": "selected_large_and_databases" if summary_only else "all", "roots": root_totals,
            "groups": dict(sorted(groups.items())), "files": files,
            "excluded_paths": sorted(excluded_names),
            "skipped_links": links, "errors": errors}


def main() -> None:
    """引数を検証し、新規JSONへ棚卸し結果を保存して集計を表示する。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-only", action="store_true", help="大量の小ファイルの個別パス保存を省略する")
    parser.add_argument("--exclude", type=Path, action="append", default=[], help="別集計するディレクトリ")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("出力が既に存在します。別の出力名を指定してください。")
    resolved = [path.resolve() for path in args.root]
    if any(a == b or a in b.parents or b in a.parents for i, a in enumerate(resolved) for b in resolved[i + 1:]):
        parser.error("走査対象の重複・親子指定はできません。")
    if any(root == args.output.resolve() or root in args.output.resolve().parents for root in resolved):
        parser.error("出力は走査対象の外へ指定してください。")
    result = inventory_roots(resolved, args.summary_only, args.exclude)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("observed_at_utc", "roots", "groups", "skipped_links", "errors")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
