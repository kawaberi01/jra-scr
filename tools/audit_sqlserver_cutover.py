"""概要: 全HTTP/MCP入口と残存SQLite接続を実コードから棚卸しする。
作成日: 2026-10-15
入力: src/scripts/通常worker補助、切替前API契約インベントリ。
出力: 入口の互換性、接続の用途、通常経路の未対応を示すJSON。
実行例: uv run python tools/audit_sqlserver_cutover.py --baseline ... --output ...
注意事項: 読み取り専用の静的監査。実DB契約テストと稼働確認を代用しない。
"""

from __future__ import annotations

import argparse
import ast
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SQLITE_REASONS = {
    "src/jra_srb/analysis_store.py": "明示sqlite backend専用。sqlserver設定時は直接writer生成を拒否する。",
    "src/jra_srb/cache.py": "旧backend専用。SQL運用のcache factoryはSqlServerTTLCacheを選ぶ。",
    "src/jra_srb/jobs.py": "旧backend専用。通常SQL jobはSqlServerJobRegistryを選ぶ。",
    "src/jra_srb/batch.py": "明示--storage sqliteのファイルexport、または旧backend。通常結果保存の既定値はSQL。",
    "src/jra_srb/storage.py": "明示旧backendのread-only接続。SQL選択時はSQL readerを返す。",
    "scripts/build_jra_odds_asof_dataset.py": "明示指定した原本・解析済みオッズ・旧analysisファイルのread-only時点学習export。API/workerから未呼出し。",
    "scripts/build_jra_o1o2_asof_dataset.py": "明示ファイルからのread-only学習export。API/workerから未呼出し。",
    "scripts/build_v89_recovery_2025_audit.py": "明示ファイルからのread-only過去検証export。API/workerから未呼出し。",
}
ACTIVE_WORKSTATE = [
    ".workstate/jra-srb/prediction-v1-validation/audit_v90_2024_external_data.py",
    ".workstate/jra-srb/prediction-v1-validation/evaluate_v1_validation.py",
]


def route_inventory(module: ast.Module) -> list[dict]:
    """FastAPI decoratorから公開method/path/handler/response modelを抽出する。"""
    routes = []
    for node in module.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                continue
            if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "app" or decorator.func.attr not in {"get", "post", "put", "delete", "patch"}:
                continue
            keywords = {keyword.arg: keyword.value for keyword in decorator.keywords}
            routes.append({"method": decorator.func.attr.upper(), "path": ast.literal_eval(decorator.args[0]),
                           "handler": node.name, "response_model": ast.unparse(keywords["response_model"]) if "response_model" in keywords else None,
                           "parameters": [argument.arg for argument in node.args.args], "line": node.lineno})
    return routes


def main() -> int:
    """切替前契約と現実装を比較し、未分類の通常SQLite接続があれば失敗する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    app_path = ROOT / "src/jra_srb/app.py"
    module = ast.parse(app_path.read_text(encoding="utf-8-sig"))
    routes = route_inventory(module)
    current = {(route["method"], route["path"]): route for route in routes}
    expected = {(route["method"], route["path"]): route for route in baseline["routes"]}
    errors = []
    if current.keys() != expected.keys():
        errors.append("HTTP method/path set differs from the 69-route baseline")
    for key in current.keys() & expected.keys():
        for field in ("handler", "response_model"):
            if current[key][field] != expected[key][field]:
                errors.append(f"{key}: {field} changed")
        old_names = [parameter["name"] for parameter in expected[key]["params"]]
        if current[key]["parameters"] != old_names:
            errors.append(f"{key}: public/dependency parameter names changed")
    mcp = next(ast.literal_eval(node.value) for node in module.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "MCP_OPERATION_IDS" for target in node.targets))
    if mcp != baseline["mcp_operation_ids"]:
        errors.append("MCP operation names or order changed")
    model_module = ast.parse((ROOT / "src/jra_srb/models.py").read_text(encoding="utf-8-sig"))
    model_fields = {node.name: [{"name": field.target.id, "type": ast.unparse(field.annotation),
                                 "default": ast.unparse(field.value) if field.value else None}
                                for field in node.body if isinstance(field, ast.AnnAssign) and isinstance(field.target, ast.Name)]
                    for node in model_module.body if isinstance(node, ast.ClassDef)}
    if model_fields.keys() != baseline["models"].keys():
        errors.append("public model names changed")
    for name, fields in model_fields.items():
        old_fields = [{key: field[key] for key in ("name", "type", "default")} for field in baseline["models"][name]["fields"]]
        if fields != old_fields:
            errors.append(f"model fields or defaults changed: {name}")
    paths = [*ROOT.joinpath("src/jra_srb").rglob("*.py"), *ROOT.joinpath("scripts").glob("*.py"), *(ROOT / name for name in ACTIVE_WORKSTATE)]
    connections = []
    direct_stores = []
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = ast.unparse(node.func)
            if name == "sqlite3.connect":
                reason = SQLITE_REASONS.get(relative)
                connections.append({"file": relative, "line": node.lineno, "reason": reason,
                                    "arguments": [ast.unparse(value) for value in node.args]})
                if reason is None:
                    errors.append(f"unclassified sqlite connection: {relative}:{node.lineno}")
            if name == "AnalysisSQLiteStore" and relative != "src/jra_srb/storage.py":
                direct_stores.append({"file": relative, "line": node.lineno})
                errors.append(f"normal entry bypasses backend factory: {relative}:{node.lineno}")
    report = {"observed_at_utc": datetime.now(UTC).isoformat(), "static_inventory_only": True,
              "http_routes": routes, "http_route_count": len(routes), "mcp_operation_ids": mcp,
              "sqlite_connections": connections, "direct_legacy_store_calls": direct_stores,
              "active_workstate_helpers": ACTIVE_WORKSTATE, "errors": errors,
              "app_sha256": hashlib.sha256(app_path.read_bytes()).hexdigest(),
              "model_count": len(model_fields), "model_field_count": sum(len(fields) for fields in model_fields.values()),
              "compatible_additions": ["ResultStorageKind.sqlserver", "optional Idempotency-Key header"],
              "archival_workstate_policy": "過去の単発調査成果物は通常の入口と区別して保持する。通常workerが直接参照する2補助は上記の監査対象。"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"http_routes": len(routes), "mcp_operations": len(mcp), "sqlite_connections": len(connections), "errors": errors}))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
