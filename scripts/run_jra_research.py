"""概要: SQL Serverだけを入力とする共通研究CLIを提供する。
作成日: 2026-10-15
入力: JSON研究設定、研究reader環境変数、契約付きモデルまたはrun ID。
出力: 非秘密のJSON応答とartifacts/jra_research/runsの研究成果物。
実行例: uv run python scripts/run_jra_research.py run --config configs/research/cross_pool_sql_masked_v2.json
注意事項: API/DBを起動・更新せず、元データのfile exportや別DBへのfallbackを行わない。
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jra_srb.jra_research_contracts import ResearchConfig, ResearchError, digest
from jra_srb.jra_research_profiles import profiles, require_profile


def execute(args) -> dict:
    """研究コマンドを実行し、失敗時は依存処理を止め証跡を残す。"""
    if args.command == "profiles":
        return {"profiles": profiles(), "overall_complete": False}
    if args.command == "acceptance-audit":
        from jra_srb.jra_research_acceptance import audit_acceptance_registry
        from jra_srb.jra_research_artifacts import RunArtifacts
        artifacts = RunArtifacts({"registry": str(args.registry)}, "acceptance-audit")
        try:
            report = audit_acceptance_registry(args.registry)
            artifacts.write_json("metrics.json", report)
            if report["errors"]:
                raise ResearchError("acceptance_registry_invalid", 4, errors=len(report["errors"]))
            artifacts.finish(overall_complete=report["overall_complete"], audit_status=report["status"])
            return {"status": report["status"], "run_id": artifacts.run_id,
                    "overall_complete": report["overall_complete"], "counts": report["counts"],
                    "updates_required": len(report["updates_required"])}
        except ResearchError as error:
            artifacts.fail(error)
            error.details["run_id"] = artifacts.run_id
            raise
    if args.command == "history":
        from jra_srb.jra_research_history import execute_history
        return execute_history(args.config)
    if args.command == "history-replay":
        from jra_srb.jra_research_history import execute_history
        return execute_history(replay_run_id=args.run_id)
    if args.command == "history-score":
        from jra_srb.jra_research_history import execute_history_score
        return execute_history_score(args.config, args.model, args.race_id)
    if args.command == "native-card-score":
        from jra_srb.jra_research_native_card import execute_native_card_score
        return execute_native_card_score(args.config, args.model, args.race_id,
                                         args.race_date, args.course, args.race_no,
                                         args.knowledge_cutoff, source=args.source)
    if args.command in {"cross-market", "cross-market-replay", "cross-market-score"}:
        from jra_srb.jra_research_cross_market_sql import execute_cross_market
        if args.command == "cross-market-replay":
            return execute_cross_market(replay_run_id=args.run_id)
        return execute_cross_market(args.config, race_id=args.race_id if args.command == "cross-market-score" else None)
    if args.command == "verify-raw":
        from jra_srb.jra_research_raw_sql import execute_raw_verification
        return execute_raw_verification(args.config, args.race_key, args.cutoff)
    if args.command == "verify-runtime":
        from jra_srb.jra_research_runtime_sql import execute_runtime_verification
        return execute_runtime_verification(args.config)
    from jra_srb.jra_research_artifacts import RunArtifacts, existing_run, verify_replay_outputs
    from jra_srb.jra_research_reader import ResearchReader
    from jra_srb.jra_research_sources import load_dataset
    original = None
    if args.command == "replay":
        source_path = existing_run(args.run_id)
        original = json.loads((source_path / "manifest.json").read_text(encoding="utf-8"))
        if original.get("status") != "complete" or original.get("command") not in {"run", "replay"}:
            raise ResearchError("run_not_replayable", 2)
        config = ResearchConfig.load(source_path / "config.json")
    else:
        config = ResearchConfig.load(args.config)
    require_profile(config.raw["profile_id"])
    artifacts = RunArtifacts(config.raw, args.command)
    reader = None
    try:
        with ResearchReader(config) as reader:
            report = reader.preflight()
            artifacts.write_json("preflight.json", report)
            if args.command == "readiness":
                from jra_srb.jra_research_readiness import audit_readiness
                readiness = audit_readiness(reader, args.since)
                artifacts.write_json("coverage.json", readiness)
                artifacts.manifest.update(query_metrics=reader.query_metrics)
                if not readiness["data_complete"]:
                    raise ResearchError("runtime_data_incomplete", 4, missing_result_bundles=len(readiness["runtime_missing_result_bundles"]))
                artifacts.finish(readiness_summary={"runtime_races": readiness["runtime_races"], "runtime_complete_result_bundles": readiness["runtime_complete_result_bundles"]})
                return {"status": "passed", "run_id": artifacts.run_id, "readiness": readiness}
            if args.command == "preflight":
                artifacts.finish(preflight=report)
                return {"status": "passed", "run_id": artifacts.run_id, "database": report["identity"]["database_name"],
                        "read_consistency": report["read_consistency"]}
            dataset = load_dataset(reader, config, score_key=args.race_key if args.command == "score" else None)
            query_metrics = reader.query_metrics
        coverage, content = dataset.coverage(), dataset.content_digest()
        artifacts.write_json("coverage.json", coverage)
        artifacts.write_excluded(dataset.excluded)
        artifacts.manifest.update(input_content_sha256=content, provenance=dataset.provenance, query_metrics=query_metrics,
                                  input_keys_sha256=digest([(r.race_key, list(r.horses)) for r in dataset.races]))
        if args.command == "coverage":
            if dataset.excluded or not dataset.races:
                raise ResearchError("coverage_incomplete", 4, adopted_races=len(dataset.races), excluded_races=len(dataset.excluded))
            artifacts.finish(coverage=coverage)
            return {"status": "passed", "run_id": artifacts.run_id, "coverage": coverage}
        if not dataset.races:
            raise ResearchError("no_eligible_races")
        from jra_srb.jra_research_evaluation import evaluate, probabilities, train_models
        from jra_srb.jra_research_resources import check_memory
        check_memory(config.raw["limits"]["memory_bytes"])
        if args.command == "score":
            import joblib
            artifact = joblib.load(args.model)
            race = dataset.races[0]
            values = probabilities(artifact, race, build_identity_sha256=dataset.provenance["build_identity_sha256"])
            output = {"race_key": race.race_key, "horses": list(race.horses), "probability": values.tolist(),
                      "variant": artifact["contract"]["variant"], "outcome_read": False}
            artifacts.write_json("metrics.json", output)
            artifacts.finish(coverage=coverage)
            return {"status": "passed", "run_id": artifacts.run_id, **output}
        if original is not None:
            if original.get("input_content_sha256") != content or original.get("provenance") != dataset.provenance:
                raise ResearchError("replay_input_changed", 5)
            artifacts.manifest["replay_of"] = args.run_id
        models = train_models(dataset, config)
        check_memory(config.raw["limits"]["memory_bytes"])
        metrics, predictions = evaluate(dataset, config, models)
        artifacts.write_models(models)
        artifacts.write_json("metrics.json", metrics)
        predictions_sha256 = artifacts.write_predictions(predictions)
        check_memory(config.raw["limits"]["memory_bytes"])
        if original is not None:
            verify_replay_outputs(original, metrics, predictions_sha256)
            artifacts.manifest["replay_code_changed"] = original.get("code_sha256") != artifacts.manifest["code_sha256"]
        artifacts.finish(coverage=coverage, metrics_sha256=digest(metrics), predictions_sha256=predictions_sha256)
        return {"status": "passed", "run_id": artifacts.run_id, "coverage": coverage,
                "evaluation": {k: {name: value for name, value in v.items() if name in {"races", "log_loss", "brier", "tickets", "roi"}}
                               for k, v in metrics["splits"]["evaluation"].items()}, "overall_complete": False}
    except ResearchError as error:
        if reader is not None:
            artifacts.manifest["query_metrics"] = reader.query_metrics
        artifacts.fail(error)
        error.details["run_id"] = artifacts.run_id
        raise
    except Exception as error:
        safe = ResearchError("unexpected_execution_error", 1, error_type=type(error).__name__)
        artifacts.fail(safe)
        safe.details["run_id"] = artifacts.run_id
        raise safe from None


def main(argv: list[str] | None = None) -> int:
    """引数を解析し、固定終了コードと非秘密JSONを返す。"""
    parser = argparse.ArgumentParser(description="SQL Server専用の再現可能なJRA研究")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("profiles")
    acceptance = commands.add_parser("acceptance-audit")
    acceptance.add_argument("--registry", type=Path, default=Path("configs/research/acceptance_registry.json"))
    history = commands.add_parser("history")
    history.add_argument("--config", required=True, type=Path)
    history_replay = commands.add_parser("history-replay")
    history_replay.add_argument("--run-id", required=True)
    history_score = commands.add_parser("history-score")
    history_score.add_argument("--config", required=True, type=Path)
    history_score.add_argument("--model", required=True, type=Path)
    history_score.add_argument("--race-id", required=True)
    native_score = commands.add_parser("native-card-score", help="SQL保存済み公式出馬表を履歴モデルで評価")
    native_score.add_argument("--config", required=True, type=Path)
    native_score.add_argument("--model", required=True, type=Path)
    native_score.add_argument("--race-id", required=True)
    native_score.add_argument("--race-date", required=True)
    native_score.add_argument("--course", required=True)
    native_score.add_argument("--race-no", required=True, type=int)
    native_score.add_argument("--knowledge-cutoff", required=True)
    native_score.add_argument("--source", default="official")
    raw_verification = commands.add_parser("verify-raw")
    raw_verification.add_argument("--config", required=True, type=Path)
    raw_verification.add_argument("--race-key", required=True)
    raw_verification.add_argument("--cutoff", required=True)
    runtime_verification = commands.add_parser("verify-runtime")
    runtime_verification.add_argument("--config", required=True, type=Path)
    for name in ("cross-market", "cross-market-score", "cross-market-replay"):
        child = commands.add_parser(name)
        if name == "cross-market-replay":
            child.add_argument("--run-id", required=True)
        else:
            child.add_argument("--config", required=True, type=Path)
            if name == "cross-market-score":
                child.add_argument("--race-id", required=True)
    for name in ("preflight", "coverage", "run", "score", "readiness"):
        child = commands.add_parser(name)
        child.add_argument("--config", required=True, type=Path)
        if name == "score":
            child.add_argument("--model", required=True, type=Path)
            child.add_argument("--race-key", required=True)
        if name == "readiness":
            child.add_argument("--since", required=True)
    replay = commands.add_parser("replay")
    replay.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(execute(args), ensure_ascii=True, allow_nan=False))
        return 0
    except ResearchError as error:
        print(json.dumps({"status": "failed", "reason": error.reason, "details": error.details}, ensure_ascii=True))
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
